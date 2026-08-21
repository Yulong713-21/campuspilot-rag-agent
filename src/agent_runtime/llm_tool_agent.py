from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from .ollama_client import OllamaChatClient
from .tools import EduRAGTools


class ToolCallingModel(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]: ...


class LLMToolCallingAgent:
    """Minimal model-driven tool loop with an application-side allowlist."""

    def __init__(
        self,
        tools: EduRAGTools | None = None,
        model: ToolCallingModel | None = None,
        max_tool_rounds: int = 3,
        clock: Callable[[], float] | None = None,
        generation_reserve_seconds: float = 0.0,
    ) -> None:
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be at least 1")
        if generation_reserve_seconds < 0:
            raise ValueError("generation_reserve_seconds must be at least 0")
        self.tools = tools or EduRAGTools()
        self.model = model or OllamaChatClient()
        self.max_tool_rounds = max_tool_rounds
        self.clock = clock or time.monotonic
        self.generation_reserve_seconds = generation_reserve_seconds

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_faq",
                    "description": "查询高频标准 FAQ。命中时返回可靠的标准答案。",
                    "parameters": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "需要查询的用户问题",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_rag",
                    "description": "从 EduRAG 知识库检索候选资料，不直接生成最终答案。",
                    "parameters": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "需要检索的用户问题",
                            },
                            "source_filter": {
                                "type": "string",
                                "description": "可选的知识库来源过滤条件，例如 ai",
                            },
                        },
                    },
                },
            },
        ]

    def _tool_error(self, tool_name: str, message: str, error_type: str) -> dict[str, Any]:
        return {
            "tool": tool_name,
            "ok": False,
            "data": {},
            "error": message,
            "error_type": error_type,
            "retryable": False,
        }

    def _parse_arguments(self, raw_arguments: Any) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if isinstance(raw_arguments, str):
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("tool arguments must be a JSON object")

    def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        default_source_filter: str | None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        function = tool_call.get("function", {})
        tool_name = str(function.get("name", "unknown_tool"))

        if tool_name not in {"search_faq", "search_rag"}:
            return self._tool_error(
                tool_name,
                f"Tool is not allowed: {tool_name}",
                "tool_not_allowed",
            )

        try:
            arguments = self._parse_arguments(function.get("arguments", {}))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._tool_error(tool_name, str(exc), "invalid_tool_arguments")

        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return self._tool_error(
                tool_name,
                "query must be a non-empty string",
                "invalid_tool_arguments",
            )

        if tool_name == "search_faq":
            return self.tools.search_faq(query.strip())

        source_filter = (
            default_source_filter
            if default_source_filter is not None
            else arguments.get("source_filter")
        )
        if source_filter is not None and not isinstance(source_filter, str):
            return self._tool_error(
                tool_name,
                "source_filter must be a string",
                "invalid_tool_arguments",
            )
        try:
            return self.tools.search_rag(
                query.strip(),
                source_filter=source_filter,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            return self._tool_error(
                tool_name,
                "tool call exceeded the remaining deadline",
                "tool_timeout",
            )

    def _remaining_seconds(self, deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(deadline - self.clock(), 0.0)

    def _time_budget(
        self,
        started_at: float,
        timeout_seconds: float | None,
    ) -> dict[str, float | None]:
        elapsed_seconds = max(self.clock() - started_at, 0.0)
        remaining_seconds = (
            None
            if timeout_seconds is None
            else max(timeout_seconds - elapsed_seconds, 0.0)
        )
        return {
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "remaining_seconds": (
                None if remaining_seconds is None else round(remaining_seconds, 3)
            ),
            "generation_reserve_seconds": self.generation_reserve_seconds,
        }

    def _tool_timeout_seconds(
        self,
        remaining_seconds: float | None,
    ) -> float | None:
        if remaining_seconds is None:
            return None
        return max(remaining_seconds - self.generation_reserve_seconds, 0.0)

    def _partial_context_answer(self, documents: list[dict[str, Any]]) -> str:
        snippets = [
            str(document.get("content", "")).strip()
            for document in documents[:2]
            if str(document.get("content", "")).strip()
        ]
        if not snippets:
            return "请求已达到时间上限，目前没有足够资料形成可靠答案。"
        evidence = "\n".join(f"- {snippet}" for snippet in snippets)
        return (
            "最终生成已达到时间上限。根据当前检索资料，先提供以下信息，"
            f"内容可能不完整：\n{evidence}"
        )

    def _confidence(self, trace: list[dict[str, Any]], documents: list[dict[str, Any]]) -> str:
        if any(not step.get("ok") for step in trace):
            return "low"
        if any(step.get("data", {}).get("hit") for step in trace):
            return "high"
        if documents:
            return "medium"
        return "low"

    def answer(
        self,
        query: str,
        source_filter: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be at least 0")

        started_at = self.clock()
        deadline = None if timeout_seconds is None else started_at + timeout_seconds
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "你是 EduRAG 工具型问答 Agent。课程标准问题优先查询 FAQ；"
                    "FAQ 未命中时可以查询 RAG。只根据工具结果回答，不要编造。"
                    "获得足够证据后直接给出中文最终答案。"
                ),
            },
            {"role": "user", "content": query},
        ]
        trace: list[dict[str, Any]] = []
        route_trace: list[dict[str, Any]] = []
        documents: list[dict[str, Any]] = []
        tool_round_count = 0
        answer = ""
        route_reason = "llm_direct_answer"
        next_action = "answer_user"
        forced_answer_source: str | None = None

        while True:
            remaining_seconds = self._remaining_seconds(deadline)
            if remaining_seconds is not None and remaining_seconds <= 0:
                answer = self._partial_context_answer(documents)
                route_reason = "llm_deadline_exhausted"
                next_action = (
                    "answer_user_with_partial_context"
                    if documents
                    else "fallback_after_deadline_exhausted"
                )
                forced_answer_source = (
                    "rag_partial_fallback" if documents else "fallback"
                )
                break

            try:
                assistant_message = self.model.chat(
                    messages,
                    tools=self._tool_schemas(),
                    timeout_seconds=remaining_seconds,
                )
            except TimeoutError:
                answer = self._partial_context_answer(documents)
                route_reason = "llm_deadline_exhausted"
                next_action = (
                    "answer_user_with_partial_context"
                    if documents
                    else "fallback_after_deadline_exhausted"
                )
                forced_answer_source = (
                    "rag_partial_fallback" if documents else "fallback"
                )
                break
            messages.append(assistant_message)
            tool_calls = assistant_message.get("tool_calls") or []

            if not tool_calls:
                answer = str(assistant_message.get("content", "")).strip()
                route_reason = (
                    "llm_direct_answer" if not trace else "llm_answered_after_tools"
                )
                break

            if tool_round_count >= self.max_tool_rounds:
                answer = "工具调用轮次已达到上限，暂时无法生成可靠答案。"
                route_reason = "tool_round_limit_reached"
                next_action = "fallback_or_create_ticket"
                break

            tool_round_count += 1
            selected_tools = [
                str(call.get("function", {}).get("name", "unknown_tool"))
                for call in tool_calls
            ]
            route_trace.append(
                {
                    "stage": "llm_tool_choice",
                    "round": tool_round_count,
                    "tools": selected_tools,
                }
            )

            for tool_call in tool_calls:
                remaining_seconds = self._remaining_seconds(deadline)
                tool_timeout_seconds = self._tool_timeout_seconds(remaining_seconds)
                if (
                    tool_timeout_seconds is not None
                    and tool_timeout_seconds <= 0
                ):
                    result = self._tool_error(
                        str(
                            tool_call.get("function", {}).get(
                                "name",
                                "unknown_tool",
                            )
                        ),
                        "tool call skipped to preserve the generation budget",
                        "retrieval_budget_exhausted",
                    )
                else:
                    result = self._execute_tool_call(
                        tool_call,
                        source_filter,
                        timeout_seconds=tool_timeout_seconds,
                    )
                trace.append(result)
                if result.get("tool") == "search_rag":
                    documents.extend(result.get("data", {}).get("documents", []))
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": result.get("tool", "unknown_tool"),
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        answer_source = (
            forced_answer_source
            if forced_answer_source is not None
            else ("llm_direct" if not trace else "llm_tool_answer")
        )
        if route_reason == "tool_round_limit_reached" and forced_answer_source is None:
            answer_source = "fallback"

        return {
            "answer": answer or None,
            "answer_source": answer_source,
            "documents": documents,
            "confidence": self._confidence(trace, documents),
            "next_action": next_action,
            "original_query": query,
            "effective_query": query,
            "retry_count": 0,
            "trace": trace,
            "trace_tools": [step["tool"] for step in trace],
            "route_reason": route_reason,
            "route_trace": route_trace,
            "tool_round_count": tool_round_count,
            "time_budget": self._time_budget(started_at, timeout_seconds),
        }
