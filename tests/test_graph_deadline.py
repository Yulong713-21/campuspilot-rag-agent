from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.graph_agent import LangGraphEduRAGAgent


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class TimedTools:
    def __init__(
        self,
        clock: FakeClock,
        faq_seconds: float,
        rag_seconds: float,
    ) -> None:
        self.clock = clock
        self.faq_seconds = faq_seconds
        self.rag_seconds = rag_seconds
        self.rag_timeouts: list[float | None] = []

    def search_faq(self, query: str, threshold: float = 0.85):
        self.clock.advance(self.faq_seconds)
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
        timeout_seconds: float | None = None,
    ):
        self.rag_timeouts.append(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds < self.rag_seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("RAG deadline exceeded")
        self.clock.advance(self.rag_seconds)
        documents = [
            {
                "content": "课程包含基础、项目和就业三个阶段。",
                "metadata": {
                    "document_id": "course",
                    "estimated_tokens": 50,
                    "relevance_score": 0.95,
                },
                "source": "course.md",
            }
        ]
        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": documents,
                "count": 1,
                "source": "rag",
            },
            "error": None,
        }


class TimedLLM:
    def __init__(
        self,
        clock: FakeClock,
        generation_seconds: float,
    ) -> None:
        self.clock = clock
        self.generation_seconds = generation_seconds
        self.timeouts: list[float | None] = []

    def generate_grounded_answer(
        self,
        query: str,
        context: str,
        timeout_seconds: float | None = None,
    ) -> str:
        self.timeouts.append(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds < self.generation_seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("generation deadline exceeded")
        self.clock.advance(self.generation_seconds)
        return "课程包含基础、项目和就业三个阶段。"


class GraphDeadlineTest(unittest.TestCase):
    def test_propagates_remaining_budget_to_rag_and_generation(self) -> None:
        clock = FakeClock()
        tools = TimedTools(clock, faq_seconds=0.5, rag_seconds=2.0)
        llm = TimedLLM(clock, generation_seconds=1.5)
        agent = LangGraphEduRAGAgent(
            tools=tools,  # type: ignore[arg-type]
            llm=llm,  # type: ignore[arg-type]
            use_ollama=True,
            clock=clock,
            generation_reserve_seconds=2.0,
        )

        result = agent.answer("课程有哪些阶段？", timeout_seconds=7.0)

        self.assertEqual(tools.rag_timeouts, [4.5])
        self.assertEqual(llm.timeouts, [4.5])
        self.assertEqual(result["answer_source"], "rag_llm")
        self.assertEqual(result["time_budget"]["elapsed_seconds"], 4.0)
        self.assertEqual(result["time_budget"]["remaining_seconds"], 3.0)
        self.assertFalse(result["time_budget"]["budget_exceeded"])

    def test_returns_partial_context_when_final_generation_times_out(self) -> None:
        clock = FakeClock()
        tools = TimedTools(clock, faq_seconds=0.5, rag_seconds=2.5)
        llm = TimedLLM(clock, generation_seconds=3.0)
        agent = LangGraphEduRAGAgent(
            tools=tools,  # type: ignore[arg-type]
            llm=llm,  # type: ignore[arg-type]
            use_ollama=True,
            clock=clock,
            generation_reserve_seconds=1.0,
        )

        result = agent.answer("课程有哪些阶段？", timeout_seconds=5.0)

        self.assertEqual(tools.rag_timeouts, [3.5])
        self.assertEqual(llm.timeouts, [2.0])
        self.assertEqual(result["answer_source"], "rag_partial_fallback")
        self.assertEqual(
            result["route_reason"],
            "final_generation_timed_out",
        )
        self.assertEqual(
            result["next_action"],
            "answer_user_with_partial_context",
        )
        self.assertIn("内容可能不完整", result["answer"])
        self.assertEqual(result["time_budget"]["remaining_seconds"], 0.0)
        self.assertFalse(result["time_budget"]["budget_exceeded"])

    def test_rag_timeout_preserves_generation_reserve_without_fake_answer(self) -> None:
        clock = FakeClock()
        tools = TimedTools(clock, faq_seconds=0.5, rag_seconds=3.0)
        llm = TimedLLM(clock, generation_seconds=1.0)
        agent = LangGraphEduRAGAgent(
            tools=tools,  # type: ignore[arg-type]
            llm=llm,  # type: ignore[arg-type]
            use_ollama=True,
            clock=clock,
            generation_reserve_seconds=1.5,
        )

        result = agent.answer("课程有哪些阶段？", timeout_seconds=4.0)

        self.assertEqual(tools.rag_timeouts[0], 2.0)
        self.assertEqual(result["documents"], [])
        self.assertEqual(result["answer_source"], "fallback")
        self.assertEqual(
            result["next_action"],
            "ask_clarification_or_create_ticket",
        )
        self.assertNotIn("三个阶段", result["answer"])
        self.assertEqual(result["time_budget"]["remaining_seconds"], 1.5)
        self.assertEqual(llm.timeouts, [])
        timeout_events = [
            event
            for event in result["trace"]
            if event.get("error_type") == "tool_timeout"
        ]
        self.assertEqual(len(timeout_events), 1)

    def test_rejects_negative_timeout_before_graph_execution(self) -> None:
        clock = FakeClock()
        tools = TimedTools(clock, faq_seconds=0.5, rag_seconds=1.0)
        agent = LangGraphEduRAGAgent(
            tools=tools,  # type: ignore[arg-type]
            clock=clock,
        )

        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            agent.answer("课程有哪些阶段？", timeout_seconds=-1.0)

        self.assertEqual(clock.current, 0.0)

    def test_rejects_negative_generation_reserve(self) -> None:
        with self.assertRaisesRegex(ValueError, "generation_reserve_seconds"):
            LangGraphEduRAGAgent(
                tools=object(),  # type: ignore[arg-type]
                generation_reserve_seconds=-1.0,
            )


if __name__ == "__main__":
    unittest.main()
