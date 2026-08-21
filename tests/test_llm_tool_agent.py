from __future__ import annotations

from pathlib import Path
import sys
import unittest
from typing import Any
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.llm_tool_agent import LLMToolCallingAgent


def tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments,
        },
    }


class FakeToolCallingModel:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.responses[len(self.calls) - 1]


class FakeEduRAGTools:
    def __init__(self, faq_hit: bool = False) -> None:
        self.faq_hit = faq_hit
        self.faq_queries: list[str] = []
        self.rag_queries: list[tuple[str, str | None]] = []

    def search_faq(self, query: str) -> dict[str, Any]:
        self.faq_queries.append(query)
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {
                "hit": self.faq_hit,
                "answer": "FAQ 标准答案" if self.faq_hit else None,
                "need_rag": not self.faq_hit,
                "source": "faq" if self.faq_hit else None,
            },
            "error": None,
            "error_type": None,
            "retryable": False,
        }

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.rag_queries.append((query, source_filter))
        documents = [{"content": "课程包含基础、项目和就业三个阶段。", "source": "ai"}]
        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": documents,
                "count": len(documents),
                "source": "rag",
            },
            "error": None,
            "error_type": None,
            "retryable": False,
        }


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class DeadlineAwareModel(FakeToolCallingModel):
    def __init__(
        self,
        responses: list[dict[str, Any]],
        call_seconds: list[float],
        clock: FakeClock,
    ) -> None:
        super().__init__(responses)
        self.call_seconds = call_seconds
        self.clock = clock

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        call_index = len(self.calls)
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "timeout_seconds": timeout_seconds,
            }
        )
        required_seconds = self.call_seconds[call_index]
        if timeout_seconds is not None and timeout_seconds < required_seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("model deadline exceeded")
        self.clock.advance(required_seconds)
        return self.responses[call_index]


class DeadlineAwareTools(FakeEduRAGTools):
    def __init__(self, clock: FakeClock, rag_seconds: float) -> None:
        super().__init__(faq_hit=False)
        self.clock = clock
        self.rag_seconds = rag_seconds
        self.rag_timeout_seconds: list[float | None] = []

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.rag_timeout_seconds.append(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds < self.rag_seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("rag deadline exceeded")
        self.clock.advance(self.rag_seconds)
        return super().search_rag(
            query,
            source_filter=source_filter,
            k=k,
            timeout_seconds=timeout_seconds,
        )


class LLMToolCallingAgentTest(unittest.TestCase):
    @patch("agent_runtime.llm_tool_agent.OllamaChatClient")
    @patch("agent_runtime.llm_tool_agent.EduRAGTools")
    def test_default_constructor_builds_runtime_dependencies(
        self,
        mock_tools,
        mock_model,
    ) -> None:
        agent = LLMToolCallingAgent()

        self.assertIs(agent.tools, mock_tools.return_value)
        self.assertIs(agent.model, mock_model.return_value)

    def test_returns_direct_answer_when_model_does_not_choose_a_tool(self) -> None:
        model = FakeToolCallingModel(
            [{"role": "assistant", "content": "你好，我可以回答课程问题。"}]
        )
        tools = FakeEduRAGTools()
        agent = LLMToolCallingAgent(tools=tools, model=model)  # type: ignore[arg-type]

        result = agent.answer("你好")

        self.assertEqual(result["answer_source"], "llm_direct")
        self.assertEqual(result["trace_tools"], [])
        self.assertEqual(result["tool_round_count"], 0)
        self.assertEqual(result["route_reason"], "llm_direct_answer")

    def test_executes_faq_tool_and_returns_final_model_answer(self) -> None:
        model = FakeToolCallingModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tool_call("search_faq", {"query": "课程学费是多少？"})],
                },
                {"role": "assistant", "content": "根据 FAQ，课程学费以标准答案为准。"},
            ]
        )
        tools = FakeEduRAGTools(faq_hit=True)
        agent = LLMToolCallingAgent(tools=tools, model=model)  # type: ignore[arg-type]

        result = agent.answer("课程学费是多少？")

        self.assertEqual(tools.faq_queries, ["课程学费是多少？"])
        self.assertEqual(result["trace_tools"], ["search_faq"])
        self.assertEqual(result["answer_source"], "llm_tool_answer")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["tool_round_count"], 1)
        self.assertEqual(result["route_reason"], "llm_answered_after_tools")

    def test_model_can_choose_rag_after_observing_faq_miss(self) -> None:
        model = FakeToolCallingModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tool_call("search_faq", {"query": "课程有哪些阶段？"})],
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tool_call(
                            "search_rag",
                            {"query": "课程有哪些阶段？", "source_filter": "java"},
                        )
                    ],
                },
                {
                    "role": "assistant",
                    "content": "课程包括基础学习、项目实战和就业准备三个阶段。",
                },
            ]
        )
        tools = FakeEduRAGTools(faq_hit=False)
        agent = LLMToolCallingAgent(tools=tools, model=model)  # type: ignore[arg-type]

        result = agent.answer("课程有哪些阶段？", source_filter="ai")

        self.assertEqual(result["trace_tools"], ["search_faq", "search_rag"])
        self.assertEqual(tools.rag_queries, [("课程有哪些阶段？", "ai")])
        self.assertEqual(result["tool_round_count"], 2)
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(len(result["documents"]), 1)
        second_call_messages = model.calls[1]["messages"]
        self.assertEqual(second_call_messages[-1]["role"], "tool")
        self.assertIn('"hit": false', second_call_messages[-1]["content"])

    def test_rejects_unknown_tool_and_returns_error_to_model(self) -> None:
        model = FakeToolCallingModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tool_call("delete_database", {})],
                },
                {"role": "assistant", "content": "该工具不可用，我不会执行删除操作。"},
            ]
        )
        tools = FakeEduRAGTools()
        agent = LLMToolCallingAgent(tools=tools, model=model)  # type: ignore[arg-type]

        result = agent.answer("删除数据库")

        self.assertEqual(result["trace_tools"], ["delete_database"])
        self.assertFalse(result["trace"][0]["ok"])
        self.assertEqual(result["trace"][0]["error_type"], "tool_not_allowed")
        self.assertEqual(result["confidence"], "low")

    def test_rejects_invalid_tool_arguments_without_calling_tool(self) -> None:
        model = FakeToolCallingModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "search_faq",
                                "arguments": "not-json",
                            },
                        }
                    ],
                },
                {"role": "assistant", "content": "工具参数无效，请重新描述问题。"},
            ]
        )
        tools = FakeEduRAGTools()
        agent = LLMToolCallingAgent(tools=tools, model=model)  # type: ignore[arg-type]

        result = agent.answer("课程问题")

        self.assertEqual(result["trace"][0]["error_type"], "invalid_tool_arguments")
        self.assertEqual(tools.faq_queries, [])
        self.assertEqual(tools.rag_queries, [])

    def test_stops_when_model_exceeds_tool_round_limit(self) -> None:
        model = FakeToolCallingModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tool_call("search_faq", {"query": "问题"})],
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tool_call("search_rag", {"query": "问题"})],
                },
            ]
        )
        tools = FakeEduRAGTools()
        agent = LLMToolCallingAgent(  # type: ignore[arg-type]
            tools=tools,
            model=model,
            max_tool_rounds=1,
        )

        result = agent.answer("问题")

        self.assertEqual(result["route_reason"], "tool_round_limit_reached")
        self.assertEqual(result["answer_source"], "fallback")
        self.assertEqual(result["next_action"], "fallback_or_create_ticket")
        self.assertEqual(result["trace_tools"], ["search_faq"])
        self.assertEqual(tools.rag_queries, [])

    def test_rejects_negative_timeout_before_calling_model(self) -> None:
        model = FakeToolCallingModel([])
        tools = FakeEduRAGTools()
        agent = LLMToolCallingAgent(tools=tools, model=model)  # type: ignore[arg-type]

        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            agent.answer("课程问题", timeout_seconds=-1.0)

        self.assertEqual(model.calls, [])

    def test_rejects_negative_generation_reserve(self) -> None:
        with self.assertRaisesRegex(ValueError, "generation_reserve_seconds"):
            LLMToolCallingAgent(
                tools=FakeEduRAGTools(),
                model=FakeToolCallingModel([]),
                generation_reserve_seconds=-1.0,
            )

    def test_propagates_remaining_deadline_when_budget_is_sufficient(self) -> None:
        clock = FakeClock()
        model = DeadlineAwareModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tool_call("search_rag", {"query": "课程有哪些阶段？"})
                    ],
                },
                {"role": "assistant", "content": "课程包括三个阶段。"},
            ],
            call_seconds=[1.0, 2.0],
            clock=clock,
        )
        tools = DeadlineAwareTools(clock=clock, rag_seconds=3.0)
        agent = LLMToolCallingAgent(  # type: ignore[arg-type]
            tools=tools,
            model=model,
            clock=clock,
        )

        result = agent.answer("课程有哪些阶段？", timeout_seconds=7.0)

        self.assertEqual(
            [call["timeout_seconds"] for call in model.calls],
            [7.0, 3.0],
        )
        self.assertEqual(tools.rag_timeout_seconds, [6.0])
        self.assertEqual(result["route_reason"], "llm_answered_after_tools")
        self.assertEqual(result["time_budget"]["elapsed_seconds"], 6.0)
        self.assertEqual(result["time_budget"]["remaining_seconds"], 1.0)

    def test_uses_partial_rag_answer_when_final_generation_times_out(self) -> None:
        clock = FakeClock()
        model = DeadlineAwareModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tool_call("search_rag", {"query": "课程有哪些阶段？"})
                    ],
                },
                {"role": "assistant", "content": "不会在时限内生成的答案"},
            ],
            call_seconds=[1.0, 2.0],
            clock=clock,
        )
        tools = DeadlineAwareTools(clock=clock, rag_seconds=3.0)
        agent = LLMToolCallingAgent(  # type: ignore[arg-type]
            tools=tools,
            model=model,
            clock=clock,
        )

        result = agent.answer("课程有哪些阶段？", timeout_seconds=5.0)

        self.assertEqual(
            [call["timeout_seconds"] for call in model.calls],
            [5.0, 1.0],
        )
        self.assertEqual(tools.rag_timeout_seconds, [4.0])
        self.assertEqual(result["route_reason"], "llm_deadline_exhausted")
        self.assertEqual(result["answer_source"], "rag_partial_fallback")
        self.assertEqual(result["next_action"], "answer_user_with_partial_context")
        self.assertIn("内容可能不完整", result["answer"])
        self.assertEqual(result["time_budget"]["elapsed_seconds"], 5.0)
        self.assertEqual(result["time_budget"]["remaining_seconds"], 0.0)

    def test_returns_controlled_failure_when_rag_times_out_without_documents(self) -> None:
        clock = FakeClock()
        model = DeadlineAwareModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tool_call("search_rag", {"query": "课程有哪些阶段？"})
                    ],
                }
            ],
            call_seconds=[1.0],
            clock=clock,
        )
        tools = DeadlineAwareTools(clock=clock, rag_seconds=5.0)
        agent = LLMToolCallingAgent(  # type: ignore[arg-type]
            tools=tools,
            model=model,
            clock=clock,
        )

        result = agent.answer("课程有哪些阶段？", timeout_seconds=5.0)

        self.assertEqual(tools.rag_timeout_seconds, [4.0])
        self.assertEqual(result["trace"][0]["error_type"], "tool_timeout")
        self.assertEqual(result["documents"], [])
        self.assertEqual(result["answer_source"], "fallback")
        self.assertEqual(result["next_action"], "fallback_after_deadline_exhausted")
        self.assertEqual(result["route_reason"], "llm_deadline_exhausted")
        self.assertNotIn("三个阶段", result["answer"])
        self.assertIn("没有足够资料", result["answer"])
        self.assertEqual(result["time_budget"]["remaining_seconds"], 0.0)

    def test_reserves_time_for_final_generation(self) -> None:
        clock = FakeClock()
        model = DeadlineAwareModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        tool_call("search_rag", {"query": "课程有哪些阶段？"})
                    ],
                },
                {"role": "assistant", "content": "课程包括三个阶段。"},
            ],
            call_seconds=[1.0, 2.0],
            clock=clock,
        )
        tools = DeadlineAwareTools(clock=clock, rag_seconds=1.8)
        agent = LLMToolCallingAgent(  # type: ignore[arg-type]
            tools=tools,
            model=model,
            clock=clock,
            generation_reserve_seconds=2.0,
        )

        result = agent.answer("课程有哪些阶段？", timeout_seconds=5.0)

        self.assertEqual(tools.rag_timeout_seconds, [2.0])
        self.assertEqual(
            [call["timeout_seconds"] for call in model.calls],
            [5.0, 2.2],
        )
        self.assertEqual(result["answer_source"], "llm_tool_answer")
        self.assertEqual(result["time_budget"]["elapsed_seconds"], 4.8)
        self.assertEqual(result["time_budget"]["remaining_seconds"], 0.2)
        self.assertEqual(result["time_budget"]["generation_reserve_seconds"], 2.0)


if __name__ == "__main__":
    unittest.main()
