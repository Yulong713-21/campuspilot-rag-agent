from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.tool_agent import RuleBasedToolAgent


class FakeTools:
    def __init__(
        self,
        faq_hit: bool,
        documents: list[dict] | None = None,
        rag_ok: bool = True,
        rag_retryable: bool = False,
        rag_error_type: str | None = None,
    ) -> None:
        self.faq_hit = faq_hit
        self.documents = documents or []
        self.rag_ok = rag_ok
        self.rag_retryable = rag_retryable
        self.rag_error_type = rag_error_type
        self.rag_called = False
        self.rag_call_count = 0
        self.rag_timeout_seconds: list[float | None] = []

    def search_faq(self, query: str, threshold: float = 0.85):
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {
                "hit": self.faq_hit,
                "answer": "faq answer" if self.faq_hit else None,
                "need_rag": not self.faq_hit,
                "source": "faq" if self.faq_hit else None,
            },
            "error": None,
        }

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ):
        self.rag_called = True
        self.rag_call_count += 1
        self.rag_timeout_seconds.append(timeout_seconds)
        return {
            "tool": "search_rag",
            "ok": self.rag_ok,
            "data": {
                "documents": self.documents,
                "count": len(self.documents),
                "source": "rag",
            },
            "error": None if self.rag_ok else "vector database unavailable",
            "error_type": self.rag_error_type,
            "retryable": self.rag_retryable,
        }


class SequencedRagTools(FakeTools):
    def __init__(self, rag_results: list[dict]) -> None:
        super().__init__(faq_hit=False)
        self.rag_results = rag_results

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ):
        self.rag_called = True
        self.rag_call_count += 1
        self.rag_timeout_seconds.append(timeout_seconds)
        index = min(self.rag_call_count - 1, len(self.rag_results) - 1)
        return self.rag_results[index]


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleep_calls: list[float] = []

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.advance(seconds)


class TimedSequencedRagTools(SequencedRagTools):
    def __init__(
        self,
        rag_results: list[dict],
        clock: FakeClock,
        call_seconds: float,
    ) -> None:
        super().__init__(rag_results)
        self.clock = clock
        self.call_seconds = call_seconds

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ):
        result = super().search_rag(
            query,
            source_filter=source_filter,
            k=k,
            timeout_seconds=timeout_seconds,
        )
        self.clock.advance(self.call_seconds)
        return result


def rag_error(error_type: str, retryable: bool = True) -> dict:
    return {
        "tool": "search_rag",
        "ok": False,
        "data": {"documents": [], "count": 0, "source": "rag"},
        "error": "vector database unavailable",
        "error_type": error_type,
        "retryable": retryable,
    }


def rag_success(documents: list[dict]) -> dict:
    return {
        "tool": "search_rag",
        "ok": True,
        "data": {"documents": documents, "count": len(documents), "source": "rag"},
        "error": None,
        "error_type": None,
        "retryable": False,
    }


class RuleBasedToolAgentTest(unittest.TestCase):
    def test_faq_hit_returns_observable_fields(self) -> None:
        tools = FakeTools(faq_hit=True)
        agent = RuleBasedToolAgent(tools=tools)  # type: ignore[arg-type]

        result = agent.answer("known question", source_filter="ai")

        self.assertEqual(result["answer_source"], "faq")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["next_action"], "answer_user")
        self.assertEqual(result["trace_tools"], ["search_faq"])
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["route_reason"], "faq_hit")
        self.assertEqual(len(result["route_trace"]), 1)
        self.assertFalse(tools.rag_called)

    def test_rag_context_returns_observable_fields(self) -> None:
        tools = FakeTools(
            faq_hit=False,
            documents=[{"content": "rag context", "metadata": {"source": "ai"}, "source": "ai"}],
        )
        agent = RuleBasedToolAgent(tools=tools)  # type: ignore[arg-type]

        result = agent.answer("unknown question", source_filter="ai")

        self.assertEqual(result["answer_source"], "rag_context")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["next_action"], "generate_answer_from_context")
        self.assertEqual(result["trace_tools"], ["search_faq", "search_rag"])
        self.assertEqual(result["documents"][0]["content"], "rag context")
        self.assertEqual(result["route_reason"], "rag_documents_found")
        self.assertEqual(
            [decision["reason"] for decision in result["route_trace"]],
            ["faq_miss", "rag_documents_found"],
        )
        self.assertTrue(tools.rag_called)

    def test_empty_rag_context_asks_for_clarification(self) -> None:
        tools = FakeTools(faq_hit=False)
        agent = RuleBasedToolAgent(tools=tools)  # type: ignore[arg-type]

        result = agent.answer("unknown question", source_filter="ai")

        self.assertEqual(result["answer_source"], "no_answer")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["next_action"], "ask_clarification_or_create_ticket")
        self.assertEqual(result["trace_tools"], ["search_faq", "search_rag"])
        self.assertEqual(result["route_reason"], "rag_empty")

    def test_retryable_rag_error_succeeds_after_one_retry(self) -> None:
        tools = SequencedRagTools(
            [
                rag_error("connection_error"),
                rag_success([{"content": "rag context", "source": "ai"}]),
            ]
        )
        sleep_calls: list[float] = []
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=tools,
            max_rag_retries=1,
            backoff_base_seconds=0.25,
            sleeper=sleep_calls.append,
            jitter=lambda upper_bound: upper_bound,
        )

        result = agent.answer("unknown question", source_filter="ai")

        self.assertEqual(result["answer_source"], "rag_context")
        self.assertEqual(result["next_action"], "generate_answer_from_context")
        self.assertEqual(result["route_reason"], "rag_documents_found")
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(tools.rag_call_count, 2)
        self.assertEqual(sleep_calls, [0.25])

    def test_retryable_rag_error_stops_after_retry_budget(self) -> None:
        tools = SequencedRagTools(
            [rag_error("connection_error"), rag_error("connection_error")]
        )
        sleep_calls: list[float] = []
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=tools,
            max_rag_retries=1,
            backoff_base_seconds=0.25,
            sleeper=sleep_calls.append,
            jitter=lambda upper_bound: upper_bound,
        )

        result = agent.answer("unknown question", source_filter="ai")

        self.assertEqual(result["answer_source"], "tool_error")
        self.assertEqual(result["next_action"], "create_ticket_after_retry_exhausted")
        self.assertEqual(result["route_reason"], "rag_retry_exhausted")
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(tools.rag_call_count, 2)
        self.assertEqual(sleep_calls, [0.25])

    def test_non_retryable_rag_error_does_not_request_retry(self) -> None:
        tools = FakeTools(
            faq_hit=False,
            rag_ok=False,
            rag_retryable=False,
            rag_error_type="permission_error",
        )
        agent = RuleBasedToolAgent(tools=tools)  # type: ignore[arg-type]

        result = agent.answer("unknown question", source_filter="ai")

        self.assertEqual(result["answer_source"], "tool_error")
        self.assertEqual(result["next_action"], "create_ticket_or_fix_request")
        self.assertEqual(result["route_reason"], "rag_non_retryable_error")
        self.assertEqual(result["trace"][-1]["error_type"], "permission_error")
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(tools.rag_call_count, 1)

    def test_backoff_grows_exponentially(self) -> None:
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=FakeTools(faq_hit=False),
            backoff_base_seconds=0.5,
            max_backoff_seconds=10.0,
            jitter=lambda upper_bound: upper_bound,
        )

        self.assertEqual(
            [agent._backoff_seconds(retry_count) for retry_count in range(3)],
            [0.5, 1.0, 2.0],
        )

    def test_backoff_stops_growing_at_configured_cap(self) -> None:
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=FakeTools(faq_hit=False),
            backoff_base_seconds=1.0,
            max_backoff_seconds=2.0,
            jitter=lambda upper_bound: upper_bound,
        )

        self.assertEqual(
            [agent._backoff_seconds(retry_count) for retry_count in range(4)],
            [1.0, 2.0, 2.0, 2.0],
        )

    def test_full_jitter_uses_a_value_within_backoff_cap(self) -> None:
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=FakeTools(faq_hit=False),
            backoff_base_seconds=1.0,
            max_backoff_seconds=2.0,
            jitter=lambda upper_bound: upper_bound * 0.25,
        )

        self.assertEqual(
            [agent._backoff_seconds(retry_count) for retry_count in range(3)],
            [0.25, 0.5, 0.5],
        )

    def test_deadline_stops_retry_when_remaining_budget_is_too_small(self) -> None:
        clock = FakeClock()
        tools = TimedSequencedRagTools(
            [
                rag_error("connection_error"),
                rag_error("connection_error"),
                rag_success([{"content": "too late", "source": "ai"}]),
            ],
            clock=clock,
            call_seconds=3.0,
        )
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=tools,
            max_rag_retries=2,
            backoff_base_seconds=0.5,
            sleeper=clock.sleep,
            jitter=lambda upper_bound: upper_bound,
            clock=clock,
            minimum_retry_call_budget_seconds=3.0,
        )

        result = agent.answer("unknown question", source_filter="ai", timeout_seconds=8.0)

        self.assertEqual(tools.rag_call_count, 2)
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["route_reason"], "rag_deadline_exhausted")
        self.assertEqual(result["next_action"], "fallback_after_deadline_exhausted")
        self.assertEqual(result["time_budget"]["remaining_seconds"], 1.5)
        self.assertEqual(clock.sleep_calls, [0.5])
        self.assertEqual(tools.rag_timeout_seconds, [8.0, 4.5])
        self.assertEqual(
            [step["timeout_seconds"] for step in result["trace"][1:]],
            [8.0, 4.5],
        )

    def test_deadline_allows_retry_when_budget_is_sufficient(self) -> None:
        clock = FakeClock()
        tools = TimedSequencedRagTools(
            [
                rag_error("connection_error"),
                rag_error("connection_error"),
                rag_success([{"content": "rag context", "source": "ai"}]),
            ],
            clock=clock,
            call_seconds=3.0,
        )
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=tools,
            max_rag_retries=2,
            backoff_base_seconds=0.5,
            sleeper=clock.sleep,
            jitter=lambda upper_bound: upper_bound,
            clock=clock,
            minimum_retry_call_budget_seconds=3.0,
        )

        result = agent.answer("unknown question", source_filter="ai", timeout_seconds=11.0)

        self.assertEqual(tools.rag_call_count, 3)
        self.assertEqual(result["retry_count"], 2)
        self.assertEqual(result["route_reason"], "rag_documents_found")
        self.assertEqual(result["next_action"], "generate_answer_from_context")
        self.assertEqual(result["time_budget"]["remaining_seconds"], 0.5)
        self.assertEqual(clock.sleep_calls, [0.5, 1.0])
        self.assertEqual(tools.rag_timeout_seconds, [11.0, 7.5, 3.5])

    def test_should_not_call_rag_when_faq_hits(self) -> None:
        agent = RuleBasedToolAgent(tools=FakeTools(faq_hit=True))  # type: ignore[arg-type]
        faq_result = {
            "tool": "search_faq",
            "ok": True,
            "data": {"hit": True, "answer": "faq answer"},
            "error": None,
        }

        self.assertFalse(agent._should_call_rag(faq_result))

    def test_should_call_rag_when_faq_misses(self) -> None:
        agent = RuleBasedToolAgent(tools=FakeTools(faq_hit=False))  # type: ignore[arg-type]
        faq_result = {
            "tool": "search_faq",
            "ok": True,
            "data": {"hit": False, "answer": None},
            "error": None,
        }

        self.assertTrue(agent._should_call_rag(faq_result))

    def test_should_call_rag_when_faq_tool_fails(self) -> None:
        agent = RuleBasedToolAgent(tools=FakeTools(faq_hit=False))  # type: ignore[arg-type]
        faq_result = {
            "tool": "search_faq",
            "ok": False,
            "data": {"hit": False, "answer": None},
            "error": "db unavailable",
        }

        self.assertTrue(agent._should_call_rag(faq_result))

    def test_routes_to_faq_answer_when_faq_hits(self) -> None:
        agent = RuleBasedToolAgent(tools=FakeTools(faq_hit=True))  # type: ignore[arg-type]
        faq_result = {
            "tool": "search_faq",
            "ok": True,
            "data": {"hit": True, "answer": "faq answer"},
            "error": None,
        }

        self.assertEqual(
            agent._route_after_faq(faq_result),
            {"route": "faq_answer", "reason": "faq_hit"},
        )

    def test_routes_to_rag_search_when_faq_misses(self) -> None:
        agent = RuleBasedToolAgent(tools=FakeTools(faq_hit=False))  # type: ignore[arg-type]
        faq_result = {
            "tool": "search_faq",
            "ok": True,
            "data": {"hit": False, "answer": None},
            "error": None,
        }

        self.assertEqual(
            agent._route_after_faq(faq_result),
            {"route": "rag_search", "reason": "faq_miss"},
        )

    def test_routes_to_rag_search_when_faq_tool_fails(self) -> None:
        agent = RuleBasedToolAgent(tools=FakeTools(faq_hit=False))  # type: ignore[arg-type]
        faq_result = {
            "tool": "search_faq",
            "ok": False,
            "data": {"hit": False, "answer": None},
            "error": "db unavailable",
        }

        self.assertEqual(
            agent._route_after_faq(faq_result),
            {"route": "rag_search", "reason": "faq_error"},
        )


if __name__ == "__main__":
    unittest.main()
