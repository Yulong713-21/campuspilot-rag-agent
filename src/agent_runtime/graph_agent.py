from __future__ import annotations

import os
import re
import time
from inspect import signature
from typing import Any, Callable, Literal, TypedDict

from langgraph.graph import END, StateGraph

from .content_guard import RetrievedContentGuard
from .context_budget import ContextBudgetPacker, ContextDocument
from .memory_retrieval import MemoryRecord, MemoryRetriever, RankedMemory
from .ollama_client import OllamaChatClient
from .tools import EduRAGTools


class EduRAGGraphState(TypedDict, total=False):
    """State carried through the first LangGraph EduRAG workflow."""

    query: str
    user_id: str | None
    original_query: str
    effective_query: str
    source_filter: str | None
    context_token_budget: int
    memory_budget_ratio: float
    started_at: float
    deadline: float | None
    timeout_seconds: float | None
    generation_reserve_seconds: float
    deadline_exhausted: bool
    retry_count: int
    faq_result: dict[str, Any]
    rag_result: dict[str, Any]
    answer: str | None
    answer_source: str
    documents: list[dict[str, Any]]
    selected_memories: list[dict[str, Any]]
    eligible_memories: list[dict[str, Any]]
    memory_policy: dict[str, Any]
    context_policy: dict[str, Any]
    confidence: str
    evaluation: dict[str, Any]
    next_action: str
    route_reason: str
    trace: list[dict[str, Any]]


class LangGraphEduRAGAgent:
    """LangGraph version of the deterministic FAQ -> RAG agent.

    This is intentionally small: it teaches state, nodes, conditional edges,
    and traces without introducing LLM tool-choice yet.
    """

    def __init__(
        self,
        tools: EduRAGTools | None = None,
        llm: OllamaChatClient | None = None,
        use_ollama: bool | None = None,
        content_guard: RetrievedContentGuard | None = None,
        context_packer: ContextBudgetPacker | None = None,
        memory_loader: Callable[[str, str], list[MemoryRecord]] | None = None,
        memory_retriever: MemoryRetriever | None = None,
        memory_budget_ratio: float = 0.2,
        clock: Callable[[], float] | None = None,
        generation_reserve_seconds: float = 0.0,
    ) -> None:
        if not 0.0 <= memory_budget_ratio <= 1.0:
            raise ValueError("memory_budget_ratio must be between 0 and 1")
        if generation_reserve_seconds < 0:
            raise ValueError("generation_reserve_seconds must be at least 0")
        self.tools = tools or EduRAGTools()
        should_use_ollama = (
            os.getenv("EDURAG_USE_OLLAMA", "").lower() in {"1", "true", "yes"}
            if use_ollama is None
            else use_ollama
        )
        self.llm = llm or (
            OllamaChatClient(model=os.getenv("EDURAG_OLLAMA_MODEL", "qwen3:1.7b"))
            if should_use_ollama
            else None
        )
        self.content_guard = content_guard or RetrievedContentGuard()
        self.context_packer = context_packer or ContextBudgetPacker()
        self.memory_loader = memory_loader
        self.memory_retriever = memory_retriever or MemoryRetriever()
        self.memory_budget_ratio = memory_budget_ratio
        self.clock = clock or time.monotonic
        self.generation_reserve_seconds = generation_reserve_seconds
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(EduRAGGraphState)

        workflow.add_node("retrieve_memory", self._retrieve_memory)
        workflow.add_node("search_faq", self._search_faq)
        workflow.add_node("search_rag", self._search_rag)
        workflow.add_node("prepare_context", self._prepare_context)
        workflow.add_node("finalize_faq", self._finalize_faq)
        workflow.add_node("generate_answer", self._generate_answer)
        workflow.add_node("deadline_fallback", self._deadline_fallback)
        workflow.add_node("evaluate_answer", self._evaluate_answer)
        workflow.add_node("rewrite_query", self._rewrite_query)
        workflow.add_node("handle_unsupported", self._handle_unsupported)

        workflow.set_entry_point("retrieve_memory")
        workflow.add_edge("retrieve_memory", "search_faq")
        workflow.add_conditional_edges(
            "search_faq",
            self._route_after_faq,
            {
                "faq_hit": "finalize_faq",
                "need_rag": "search_rag",
            },
        )
        workflow.add_edge("search_rag", "prepare_context")
        workflow.add_conditional_edges(
            "prepare_context",
            self._route_before_generation,
            {
                "generate": "generate_answer",
                "deadline_fallback": "deadline_fallback",
            },
        )
        workflow.add_edge("finalize_faq", END)
        workflow.add_conditional_edges(
            "generate_answer",
            self._route_after_generation,
            {
                "evaluate": "evaluate_answer",
                "deadline_exhausted": END,
            },
        )
        workflow.add_edge("deadline_fallback", END)
        workflow.add_conditional_edges(
            "evaluate_answer",
            self._route_after_evaluation,
            {
                "supported": END,
                "retry": "rewrite_query",
                "unsupported": "handle_unsupported",
            },
        )
        workflow.add_edge("rewrite_query", "search_rag")
        workflow.add_edge("handle_unsupported", END)

        return workflow.compile()

    def _retrieve_memory(self, state: EduRAGGraphState) -> EduRAGGraphState:
        retrieval_budget = self._retrieval_budget_seconds(state)
        if retrieval_budget is not None and retrieval_budget <= 0:
            return {
                "selected_memories": [],
                "eligible_memories": [],
                "memory_policy": {
                    "status": "skipped_to_preserve_generation_deadline",
                    "candidate_count": 0,
                    "selected_count": 0,
                    "used_tokens": 0,
                },
            }
        if self.memory_loader is None:
            return {
                "selected_memories": [],
                "eligible_memories": [],
                "memory_policy": {
                    "status": "disabled",
                    "candidate_count": 0,
                    "selected_count": 0,
                    "used_tokens": 0,
                },
            }

        user_id = state.get("user_id")
        if not user_id:
            return {
                "selected_memories": [],
                "eligible_memories": [],
                "memory_policy": {
                    "status": "skipped_missing_authenticated_user",
                    "candidate_count": 0,
                    "selected_count": 0,
                    "used_tokens": 0,
                },
            }

        query = state.get("effective_query") or state["query"]
        memory_budget = int(
            state["context_token_budget"] * state["memory_budget_ratio"]
        )
        try:
            candidates = self.memory_loader(user_id, query)
            result = self.memory_retriever.retrieve(
                candidates,
                token_budget=memory_budget,
            )
        except Exception as exc:
            event = {
                "tool": "retrieve_memory",
                "ok": False,
                "data": {
                    "candidate_count": 0,
                    "selected_count": 0,
                    "used_tokens": 0,
                },
                "error": str(exc),
            }
            return {
                "selected_memories": [],
                "eligible_memories": [],
                "memory_policy": {
                    "status": "loader_error",
                    **event["data"],
                },
                "trace": [*state.get("trace", []), event],
            }

        selected = self._ranked_memories_to_state(result.selected)
        eligible_ids = {
            item.record.memory_id for item in result.selected
        } | {
            item.memory_id
            for item in result.dropped
            if item.reason == "token_budget_exceeded"
        }
        eligible_memories = [
            self._memory_record_to_state(candidate)
            for candidate in candidates
            if candidate.memory_id in eligible_ids
        ]
        policy = {
            "status": "completed",
            "budget_tokens": memory_budget,
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "dropped_count": len(result.dropped),
            "used_tokens": result.used_tokens,
            "remaining_tokens": result.remaining_tokens,
        }
        event = {
            "tool": "retrieve_memory",
            "ok": True,
            "data": policy,
            "error": None,
        }
        return {
            "selected_memories": selected,
            "eligible_memories": eligible_memories,
            "memory_policy": policy,
            "trace": [*state.get("trace", []), event],
        }

    def _search_faq(self, state: EduRAGGraphState) -> EduRAGGraphState:
        remaining = self._remaining_seconds(state)
        if remaining is not None and remaining <= 0:
            result = self._deadline_tool_error(
                "search_faq",
                "overall deadline exhausted before FAQ search",
            )
        else:
            result = self.tools.search_faq(state["query"])
        return {
            "faq_result": result,
            "trace": [*state.get("trace", []), result],
        }

    def _route_after_faq(self, state: EduRAGGraphState) -> Literal["faq_hit", "need_rag"]:
        faq_data = state.get("faq_result", {}).get("data", {})
        if state.get("faq_result", {}).get("ok") and faq_data.get("hit"):
            return "faq_hit"
        return "need_rag"

    def _search_rag(self, state: EduRAGGraphState) -> EduRAGGraphState:
        timeout_seconds = self._retrieval_budget_seconds(state)
        if timeout_seconds is not None and timeout_seconds <= 0:
            result = self._deadline_tool_error(
                "search_rag",
                "RAG search skipped to preserve final generation budget",
                error_type="retrieval_budget_exhausted",
            )
        else:
            kwargs: dict[str, Any] = {
                "source_filter": state.get("source_filter"),
            }
            if (
                timeout_seconds is not None
                and "timeout_seconds" in signature(self.tools.search_rag).parameters
            ):
                kwargs["timeout_seconds"] = timeout_seconds
            try:
                result = self.tools.search_rag(
                    state.get("effective_query") or state["query"],
                    **kwargs,
                )
            except TimeoutError:
                result = self._deadline_tool_error(
                    "search_rag",
                    "RAG search exceeded its remaining deadline budget",
                    error_type="tool_timeout",
                )
            result = {
                **result,
                "timeout_seconds": (
                    None
                    if timeout_seconds is None
                    else round(timeout_seconds, 3)
                ),
            }
        return {
            "rag_result": result,
            "trace": [*state.get("trace", []), result],
        }

    def _finalize_faq(self, state: EduRAGGraphState) -> EduRAGGraphState:
        faq_data = state.get("faq_result", {}).get("data", {})
        return {
            "answer": faq_data.get("answer"),
            "answer_source": "faq",
            "documents": [],
            "confidence": "high",
            "evaluation": {
                "supported": True,
                "reason": "FAQ answer was returned from the structured FAQ layer.",
                "evaluator": "rule_based",
            },
            "next_action": "answer_user",
            "route_reason": "faq_hit",
        }

    def _prepare_context(self, state: EduRAGGraphState) -> EduRAGGraphState:
        raw_documents = state.get("rag_result", {}).get("data", {}).get("documents", [])
        context_documents = [
            self._to_context_document(document, index)
            for index, document in enumerate(raw_documents)
        ]
        guarded = self.content_guard.inspect(context_documents)
        total_budget = state.get("context_token_budget", 600)
        memory_used_tokens = state.get("memory_policy", {}).get("used_tokens", 0)
        rag_budget = max(0, total_budget - memory_used_tokens)
        packed = self.context_packer.pack(
            guarded.accepted,
            token_budget=rag_budget,
        )
        selected_memories = state.get("selected_memories", [])
        memory_policy = dict(state.get("memory_policy", {}))
        top_document = max(
            guarded.accepted,
            key=lambda document: document.relevance_score,
            default=None,
        )
        if (
            top_document is not None
            and top_document in packed.dropped
            and top_document.estimated_tokens <= total_budget
            and memory_used_tokens > 0
        ):
            packed = self.context_packer.pack(
                guarded.accepted,
                token_budget=total_budget,
            )
            residual_memory_budget = packed.remaining_tokens
            eligible_memories = [
                self._memory_record_from_state(memory)
                for memory in state.get("eligible_memories", [])
            ]
            repacked_memory = self.memory_retriever.retrieve(
                eligible_memories,
                token_budget=residual_memory_budget,
            )
            selected_memories = self._ranked_memories_to_state(
                repacked_memory.selected
            )
            memory_policy.update(
                {
                    "status": "evidence_first_repacked",
                    "selected_count": len(selected_memories),
                    "used_tokens": repacked_memory.used_tokens,
                    "released_tokens": memory_used_tokens,
                    "residual_budget_tokens": residual_memory_budget,
                    "remaining_tokens": repacked_memory.remaining_tokens,
                }
            )
        selected_ids = {document.document_id for document in packed.selected}
        selected_documents = [
            document
            for index, document in enumerate(raw_documents)
            if self._document_id(document, index) in selected_ids
        ]
        policy = {
            "input_count": len(raw_documents),
            "accepted_count": len(guarded.accepted),
            "quarantined_count": len(guarded.quarantined),
            "quarantined": [
                {
                    "document_id": finding.document_id,
                    "signals": finding.signals,
                }
                for finding in guarded.findings
            ],
            "selected_count": len(packed.selected),
            "dropped_by_budget_count": len(packed.dropped),
            "used_tokens": packed.used_tokens,
            "remaining_tokens": (
                packed.remaining_tokens
                - memory_policy.get("used_tokens", 0)
                if memory_policy.get("status") == "evidence_first_repacked"
                else packed.remaining_tokens
            ),
            "memory_released_tokens": memory_policy.get("released_tokens", 0),
            "total_used_tokens": (
                packed.used_tokens + memory_policy.get("used_tokens", 0)
            ),
        }
        policy_event = {
            "tool": "prepare_context",
            "ok": True,
            "data": policy,
            "error": None,
        }
        return {
            "documents": selected_documents,
            "selected_memories": selected_memories,
            "memory_policy": memory_policy,
            "context_policy": policy,
            "trace": [*state.get("trace", []), policy_event],
        }

    @staticmethod
    def _memory_record_to_state(memory: MemoryRecord) -> dict[str, Any]:
        return {
            "memory_id": memory.memory_id,
            "content": memory.content,
            "estimated_tokens": memory.estimated_tokens,
            "relevance": memory.relevance,
            "importance": memory.importance,
            "confidence": memory.confidence,
            "recency": memory.recency,
            "scope_active": memory.scope_active,
            "trusted": memory.trusted,
            "sensitive": memory.sensitive,
        }

    @staticmethod
    def _memory_record_from_state(memory: dict[str, Any]) -> MemoryRecord:
        return MemoryRecord(**memory)

    @staticmethod
    def _ranked_memories_to_state(
        memories: list[RankedMemory],
    ) -> list[dict[str, Any]]:
        return [
            {
                "memory_id": item.record.memory_id,
                "content": item.record.content,
                "estimated_tokens": item.record.estimated_tokens,
                "score": item.score,
                "status": "active",
            }
            for item in memories
        ]

    def _generate_answer(self, state: EduRAGGraphState) -> EduRAGGraphState:
        documents = state.get("documents", [])
        query = state.get("effective_query") or state["query"]
        try:
            answer = self._generate_with_llm(
                query,
                documents,
                state.get("selected_memories", []),
                timeout_seconds=self._remaining_seconds(state),
            )
        except TimeoutError:
            return self._deadline_fallback(
                state,
                reason="final_generation_timed_out",
            )
        answer_source = "rag_llm" if answer and self.llm and documents else None
        if not answer:
            answer = self._synthesize_from_documents(query, documents)
            answer_source = "rag_generated" if documents else "no_answer"
        return {
            "answer": answer,
            "answer_source": answer_source,
            "documents": documents,
            "confidence": "medium" if documents else "low",
            "deadline_exhausted": False,
        }

    def _to_context_document(
        self,
        document: dict[str, Any],
        index: int,
    ) -> ContextDocument:
        metadata = document.get("metadata", {})
        content = str(document.get("content", ""))
        estimated_tokens = metadata.get("estimated_tokens")
        if not isinstance(estimated_tokens, int) or estimated_tokens <= 0:
            estimated_tokens = max(1, (len(content) + 3) // 4)
        relevance_score = next(
            (
                float(metadata[field])
                for field in ("rerank_score", "relevance_score", "score")
                if isinstance(metadata.get(field), (int, float))
            ),
            max(0.0, 1.0 - index * 0.01),
        )
        return ContextDocument(
            document_id=self._document_id(document, index),
            content=content,
            relevance_score=relevance_score,
            estimated_tokens=estimated_tokens,
            source=document.get("source"),
        )

    @staticmethod
    def _document_id(document: dict[str, Any], index: int) -> str:
        metadata = document.get("metadata", {})
        return str(
            metadata.get("document_id")
            or metadata.get("id")
            or f"rag-document-{index + 1}"
        )

    def _generate_with_llm(
        self,
        query: str,
        documents: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        timeout_seconds: float | None = None,
    ) -> str | None:
        if not self.llm or not documents:
            return None
        context = self._format_context_for_llm(documents, memories)
        if not context:
            return None
        try:
            return self.llm.generate_grounded_answer(
                query,
                context,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            raise
        except Exception:
            return None

    def _route_before_generation(
        self,
        state: EduRAGGraphState,
    ) -> Literal["generate", "deadline_fallback"]:
        remaining = self._remaining_seconds(state)
        if remaining is not None and remaining <= 0:
            return "deadline_fallback"
        return "generate"

    @staticmethod
    def _route_after_generation(
        state: EduRAGGraphState,
    ) -> Literal["evaluate", "deadline_exhausted"]:
        return (
            "deadline_exhausted"
            if state.get("deadline_exhausted")
            else "evaluate"
        )

    def _deadline_fallback(
        self,
        state: EduRAGGraphState,
        reason: str = "deadline_exhausted_before_generation",
    ) -> EduRAGGraphState:
        documents = state.get("documents", [])
        if documents:
            snippets = [
                str(document.get("content", "")).strip()
                for document in documents[:2]
                if str(document.get("content", "")).strip()
            ]
            evidence = "\n".join(f"- {snippet}" for snippet in snippets)
            answer = (
                "请求已达到时间上限。根据已完成检索的资料，先提供以下信息，"
                f"内容可能不完整：\n{evidence}"
            )
            answer_source = "rag_partial_fallback"
            next_action = "answer_user_with_partial_context"
        else:
            answer = "请求已达到时间上限，目前没有足够资料形成可靠答案。"
            answer_source = "fallback"
            next_action = "fallback_after_deadline_exhausted"
        return {
            "answer": answer,
            "answer_source": answer_source,
            "confidence": "low",
            "next_action": next_action,
            "route_reason": reason,
            "deadline_exhausted": True,
        }

    def _remaining_seconds(
        self,
        state: EduRAGGraphState,
    ) -> float | None:
        deadline = state.get("deadline")
        if deadline is None:
            return None
        return max(deadline - self.clock(), 0.0)

    def _retrieval_budget_seconds(
        self,
        state: EduRAGGraphState,
    ) -> float | None:
        remaining = self._remaining_seconds(state)
        if remaining is None:
            return None
        return max(
            remaining - state.get("generation_reserve_seconds", 0.0),
            0.0,
        )

    @staticmethod
    def _deadline_tool_error(
        tool: str,
        message: str,
        error_type: str = "deadline_exhausted",
    ) -> dict[str, Any]:
        return {
            "tool": tool,
            "ok": False,
            "data": {
                "hit": False,
                "answer": None,
                "need_rag": True,
                "documents": [],
                "count": 0,
            },
            "error": message,
            "error_type": error_type,
            "retryable": False,
        }

    def _evaluate_answer(self, state: EduRAGGraphState) -> EduRAGGraphState:
        answer = state.get("answer") or ""
        documents = state.get("documents", [])

        if not documents:
            return {
                "confidence": "low",
                "evaluation": {
                    "supported": False,
                    "reason": "No retrieved documents were available to support the answer.",
                    "evaluator": "rule_based",
                },
                "route_reason": "rag_context_empty",
            }

        support_score = self._estimate_support_score(answer, documents)
        supported = support_score >= 0.08
        return {
            "confidence": "medium" if supported else "low",
            "evaluation": {
                "supported": supported,
                "support_score": round(support_score, 3),
                "reason": (
                    "Answer shares enough keywords with retrieved documents."
                    if supported
                    else "Answer has weak lexical overlap with retrieved documents."
                ),
                "evaluator": "rule_based",
            },
            "next_action": "answer_user" if supported else "fallback",
            "route_reason": (
                "rag_answer_supported_after_rewrite"
                if supported and state.get("retry_count", 0) > 0
                else "rag_answer_supported"
                if supported
                else "rag_answer_unsupported"
            ),
        }

    def _route_after_evaluation(self, state: EduRAGGraphState) -> Literal["supported", "retry", "unsupported"]:
        if state.get("evaluation", {}).get("supported"):
            return "supported"
        if state.get("retry_count", 0) < 1:
            return "retry"
        return "unsupported"

    def _rewrite_query(self, state: EduRAGGraphState) -> EduRAGGraphState:
        original_query = state.get("original_query") or state["query"]
        rewritten_query = self._rule_based_rewrite(original_query, state.get("source_filter"))
        retry_count = state.get("retry_count", 0) + 1
        rewrite_trace = {
            "tool": "rewrite_query",
            "ok": True,
            "data": {
                "original_query": original_query,
                "rewritten_query": rewritten_query,
                "retry_count": retry_count,
            },
            "error": None,
        }
        return {
            "effective_query": rewritten_query,
            "retry_count": retry_count,
            "trace": [*state.get("trace", []), rewrite_trace],
        }

    def _handle_unsupported(self, state: EduRAGGraphState) -> EduRAGGraphState:
        return {
            "answer": (
                "这个问题我暂时没有在知识库中找到足够可靠的依据，"
                "所以不建议直接给出确定答案。你可以补充学科、课程阶段、"
                "具体班型或想了解的模块，我会再尝试检索。"
            ),
            "answer_source": "fallback",
            "confidence": "low",
            "next_action": "ask_clarification_or_create_ticket",
            "route_reason": "rag_answer_unsupported_after_retry",
        }

    def _rule_based_rewrite(self, query: str, source_filter: str | None) -> str:
        hints = []
        if source_filter:
            hints.append(f"{source_filter} 学科")
        if not any(word in query for word in ("课程", "大纲", "模块", "阶段", "优势", "就业")):
            hints.append("课程 大纲 模块 阶段 优势")
        if not any(word.lower() in query.lower() for word in ("agent", "rag", "大模型", "人工智能")):
            hints.append("人工智能 大模型 RAG Agent")
        if not hints:
            hints.append("课程内容 学习阶段 项目实战")
        return f"{query} {' '.join(hints)}"

    def _synthesize_from_documents(
        self,
        query: str,
        documents: list[dict[str, Any]],
        max_points: int = 6,
    ) -> str:
        if not documents:
            return "当前知识库中没有检索到足够相关的内容，建议换一个更具体的问题或联系人工老师确认。"

        points: list[str] = []
        for document in documents[:3]:
            content = self._clean_document_text(str(document.get("content", "")))
            if not content:
                continue
            for line in content.splitlines():
                normalized = line.strip(" -#0123456789.、:：")
                if len(normalized) < 8:
                    continue
                if self._is_editorial_noise(normalized):
                    continue
                if normalized in points:
                    continue
                points.append(normalized[:120])
                if len(points) >= max_points:
                    break
            if len(points) >= max_points:
                break

        if not points:
            return "当前检索结果为空，暂时无法基于知识库生成可靠答案。"

        joined = "\n".join(f"- {point}" for point in points)
        return (
            "根据知识库检索结果，可以这样回答：\n\n"
            f"问题：{query}\n\n"
            f"参考要点：\n{joined}\n\n"
            "说明：这是基于检索内容整理的开发版答案，后续会接入大模型生成更自然的回复。"
        )

    def _format_context_for_llm(
        self,
        documents: list[dict[str, Any]],
        memories: list[dict[str, Any]],
        max_chars: int = 2400,
    ) -> str:
        chunks: list[str] = []
        remaining = max_chars
        for index, document in enumerate(documents[:4], start=1):
            content = self._clean_document_text(str(document.get("content", "")))
            if not content:
                continue
            content = content[:remaining]
            chunks.append(f"[{index}] {content}")
            remaining -= len(content)
            if remaining <= 0:
                break
        sections = ["## 知识库事实证据\n" + "\n\n".join(chunks)]
        if memories:
            memory_lines = "\n".join(
                f"- {memory.get('content', '')}"
                for memory in memories
                if memory.get("content")
            )
            if memory_lines:
                sections.append(
                    "## 用户个性化偏好\n"
                    "以下内容只用于调整表达方式，不能作为课程事实依据：\n"
                    f"{memory_lines}"
                )
        return "\n\n".join(sections)

    def _clean_document_text(self, text: str) -> str:
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())

    def _is_editorial_noise(self, text: str) -> bool:
        noise_markers = (
            "学科编辑要求",
            "学科编辑请更新",
            "标题结构不可删减",
            "具体内容请根据",
            "项目展示需配图",
            "设计需求说明",
        )
        return any(marker in text for marker in noise_markers)

    def _estimate_support_score(self, answer: str, documents: list[dict[str, Any]]) -> float:
        answer_terms = self._keyword_set(answer)
        document_terms = self._keyword_set(
            "\n".join(str(document.get("content", "")) for document in documents)
        )
        if not answer_terms or not document_terms:
            return 0.0
        return len(answer_terms & document_terms) / len(answer_terms)

    def _keyword_set(self, text: str) -> set[str]:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_+-]{2,}", text.lower())
        stopwords = {
            "根据",
            "知识库",
            "检索",
            "结果",
            "可以",
            "这样",
            "回答",
            "问题",
            "参考",
            "要点",
            "说明",
            "开发版",
            "答案",
            "后续",
            "接入",
            "生成",
            "更自然",
            "回复",
        }
        return {token for token in tokens if token not in stopwords}

    def answer(
        self,
        query: str,
        source_filter: str | None = None,
        context_token_budget: int = 600,
        user_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if context_token_budget < 0:
            raise ValueError("context_token_budget must be at least 0")
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be at least 0")
        started_at = self.clock()
        deadline = (
            None
            if timeout_seconds is None
            else started_at + timeout_seconds
        )
        state = self.graph.invoke(
            {
                "query": query,
                "user_id": user_id,
                "original_query": query,
                "effective_query": query,
                "source_filter": source_filter,
                "context_token_budget": context_token_budget,
                "memory_budget_ratio": self.memory_budget_ratio,
                "started_at": started_at,
                "deadline": deadline,
                "timeout_seconds": timeout_seconds,
                "generation_reserve_seconds": self.generation_reserve_seconds,
                "deadline_exhausted": False,
                "retry_count": 0,
                "trace": [],
            }
        )
        return {
            "answer": state.get("answer"),
            "answer_source": state.get("answer_source"),
            "documents": state.get("documents", []),
            "confidence": state.get("confidence"),
            "evaluation": state.get("evaluation", {}),
            "next_action": state.get("next_action"),
            "original_query": state.get("original_query", query),
            "effective_query": state.get("effective_query", query),
            "retry_count": state.get("retry_count", 0),
            "trace": state.get("trace", []),
            "trace_tools": [
                step.get("tool")
                for step in state.get("trace", [])
                if step.get("tool")
            ],
            "route_reason": state.get("route_reason"),
            "context_policy": state.get("context_policy", {}),
            "selected_memories": state.get("selected_memories", []),
            "memory_policy": state.get("memory_policy", {}),
            "time_budget": self._time_budget(started_at, timeout_seconds),
        }

    def _time_budget(
        self,
        started_at: float,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        elapsed = max(self.clock() - started_at, 0.0)
        remaining = (
            None
            if timeout_seconds is None
            else max(timeout_seconds - elapsed, 0.0)
        )
        return {
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": round(elapsed, 3),
            "remaining_seconds": (
                None if remaining is None else round(remaining, 3)
            ),
            "generation_reserve_seconds": self.generation_reserve_seconds,
            "budget_exceeded": (
                False
                if timeout_seconds is None
                else elapsed > timeout_seconds
            ),
        }
