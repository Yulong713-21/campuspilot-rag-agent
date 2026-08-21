from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.graph_agent import LangGraphEduRAGAgent
from agent_runtime.memory_retrieval import MemoryRecord


class RecordingLLM:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def generate_grounded_answer(
        self,
        query: str,
        context: str,
        timeout_seconds: float | None = None,
    ) -> str:
        self.contexts.append(context)
        return "课程包含基础、项目和就业三个阶段。"


class RAGTools:
    def __init__(self, document_tokens: int = 80) -> None:
        self.document_tokens = document_tokens

    def search_faq(self, query: str, threshold: float = 0.85):
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {"hit": False, "answer": None, "need_rag": True},
            "error": None,
        }

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
    ):
        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": [
                    {
                        "content": "课程包含基础、项目和就业三个阶段。",
                        "metadata": {
                            "document_id": "course",
                            "estimated_tokens": self.document_tokens,
                            "relevance_score": 0.95,
                        },
                        "source": "course.md",
                    }
                ],
                "count": 1,
                "source": "rag",
            },
            "error": None,
        }


def preference_memory(
    tokens: int = 20,
    memory_id: str = "preference-1",
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        content="用户偏好：先讲原理，再展示实验。",
        estimated_tokens=tokens,
        relevance=0.9,
        importance=0.9,
        confidence=1.0,
        recency=1.0,
    )


class GraphMemoryIntegrationTest(unittest.TestCase):
    def test_memory_uses_capped_budget_and_rag_receives_the_remainder(self) -> None:
        llm = RecordingLLM()
        loader_calls: list[tuple[str, str]] = []

        def loader(user_id: str, query: str) -> list[MemoryRecord]:
            loader_calls.append((user_id, query))
            return [preference_memory(tokens=20)]

        agent = LangGraphEduRAGAgent(
            tools=RAGTools(document_tokens=80),  # type: ignore[arg-type]
            llm=llm,  # type: ignore[arg-type]
            use_ollama=True,
            memory_loader=loader,
            memory_budget_ratio=0.2,
        )

        result = agent.answer(
            "课程有哪些阶段？",
            user_id="user-1",
            context_token_budget=100,
        )

        self.assertEqual(loader_calls, [("user-1", "课程有哪些阶段？")])
        self.assertEqual(result["memory_policy"]["budget_tokens"], 20)
        self.assertEqual(result["memory_policy"]["used_tokens"], 20)
        self.assertEqual(result["context_policy"]["used_tokens"], 80)
        self.assertEqual(result["context_policy"]["remaining_tokens"], 0)
        self.assertIn("只用于调整表达方式", llm.contexts[0])
        self.assertIn("先讲原理", llm.contexts[0])
        self.assertIn("知识库事实证据", llm.contexts[0])

    def test_unused_memory_budget_returns_to_rag(self) -> None:
        agent = LangGraphEduRAGAgent(
            tools=RAGTools(document_tokens=100),  # type: ignore[arg-type]
            memory_loader=lambda user_id, query: [],
            memory_budget_ratio=0.2,
        )

        result = agent.answer(
            "课程有哪些阶段？",
            user_id="user-1",
            context_token_budget=100,
        )

        self.assertEqual(result["memory_policy"]["used_tokens"], 0)
        self.assertEqual(result["context_policy"]["selected_count"], 1)
        self.assertEqual(result["context_policy"]["used_tokens"], 100)

    def test_missing_authenticated_user_skips_memory_loader(self) -> None:
        loader_called = False

        def loader(user_id: str, query: str) -> list[MemoryRecord]:
            nonlocal loader_called
            loader_called = True
            return [preference_memory()]

        agent = LangGraphEduRAGAgent(
            tools=RAGTools(),  # type: ignore[arg-type]
            memory_loader=loader,
        )

        result = agent.answer("课程有哪些阶段？")

        self.assertFalse(loader_called)
        self.assertEqual(
            result["memory_policy"]["status"],
            "skipped_missing_authenticated_user",
        )
        self.assertEqual(result["selected_memories"], [])

    def test_oversized_memory_does_not_steal_rag_budget(self) -> None:
        agent = LangGraphEduRAGAgent(
            tools=RAGTools(document_tokens=100),  # type: ignore[arg-type]
            memory_loader=lambda user_id, query: [
                preference_memory(tokens=30)
            ],
            memory_budget_ratio=0.2,
        )

        result = agent.answer(
            "课程有哪些阶段？",
            user_id="user-1",
            context_token_budget=100,
        )

        self.assertEqual(result["memory_policy"]["selected_count"], 0)
        self.assertEqual(result["memory_policy"]["used_tokens"], 0)
        self.assertEqual(result["context_policy"]["selected_count"], 1)

    def test_releases_memory_when_it_blocks_top_rag_evidence(self) -> None:
        agent = LangGraphEduRAGAgent(
            tools=RAGTools(document_tokens=90),  # type: ignore[arg-type]
            memory_loader=lambda user_id, query: [
                preference_memory(tokens=20)
            ],
            memory_budget_ratio=0.2,
        )

        result = agent.answer(
            "课程有哪些阶段？",
            user_id="user-1",
            context_token_budget=100,
        )

        self.assertEqual(
            result["memory_policy"]["status"],
            "evidence_first_repacked",
        )
        self.assertEqual(result["memory_policy"]["released_tokens"], 20)
        self.assertEqual(result["selected_memories"], [])
        self.assertEqual(result["context_policy"]["used_tokens"], 90)
        self.assertEqual(result["context_policy"]["remaining_tokens"], 10)

    def test_repacks_shorter_memory_into_rag_residual_budget(self) -> None:
        agent = LangGraphEduRAGAgent(
            tools=RAGTools(document_tokens=180),  # type: ignore[arg-type]
            memory_loader=lambda user_id, query: [
                preference_memory(tokens=25, memory_id="M1"),
                preference_memory(tokens=20, memory_id="M2"),
            ],
            memory_budget_ratio=0.2,
        )

        result = agent.answer(
            "课程有哪些阶段？",
            user_id="user-1",
            context_token_budget=200,
        )

        self.assertEqual(
            result["memory_policy"]["status"],
            "evidence_first_repacked",
        )
        self.assertEqual(
            [memory["memory_id"] for memory in result["selected_memories"]],
            ["M2"],
        )
        self.assertEqual(result["memory_policy"]["residual_budget_tokens"], 20)
        self.assertEqual(result["memory_policy"]["used_tokens"], 20)
        self.assertEqual(result["context_policy"]["used_tokens"], 180)
        self.assertEqual(result["context_policy"]["total_used_tokens"], 200)
        self.assertEqual(result["context_policy"]["remaining_tokens"], 0)

    def test_rejects_invalid_memory_budget_ratio(self) -> None:
        with self.assertRaisesRegex(ValueError, "memory_budget_ratio"):
            LangGraphEduRAGAgent(
                tools=RAGTools(),  # type: ignore[arg-type]
                memory_budget_ratio=1.1,
            )


if __name__ == "__main__":
    unittest.main()
