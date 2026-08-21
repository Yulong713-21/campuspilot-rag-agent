from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.llm_tool_agent import LLMToolCallingAgent


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class TimedScriptedModel:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.call_count = 0
        self.timeout_seconds: list[float | None] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.timeout_seconds.append(timeout_seconds)
        self.call_count += 1

        if self.call_count == 1:
            self._spend_time(1.0, timeout_seconds)
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "search_rag",
                            "arguments": {"query": "课程有哪些阶段？"},
                        },
                    }
                ],
            }

        self._spend_time(2.0, timeout_seconds)
        return {
            "role": "assistant",
            "content": "课程包括基础学习、项目实战和就业准备三个阶段。",
        }

    def _spend_time(
        self,
        required_seconds: float,
        timeout_seconds: float | None,
    ) -> None:
        if timeout_seconds is not None and timeout_seconds < required_seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("模型调用超过剩余时间")
        self.clock.advance(required_seconds)


class TimedTools:
    def __init__(
        self,
        clock: FakeClock,
        required_seconds: float = 3.0,
    ) -> None:
        self.clock = clock
        self.required_seconds = required_seconds
        self.rag_timeout_seconds: list[float | None] = []

    def search_faq(self, query: str) -> dict[str, Any]:
        raise AssertionError("本实验不应该调用 FAQ")

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.rag_timeout_seconds.append(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds < self.required_seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("RAG 调用超过剩余时间")
        self.clock.advance(self.required_seconds)
        documents = [
            {
                "content": "课程包括基础、项目和就业三个阶段。",
                "source": source_filter,
            }
        ]
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


def run_scenario(
    configured_budget_seconds: float,
    rag_required_seconds: float = 3.0,
) -> dict[str, Any]:
    clock = FakeClock()
    model = TimedScriptedModel(clock)
    tools = TimedTools(clock, required_seconds=rag_required_seconds)
    agent = LLMToolCallingAgent(  # type: ignore[arg-type]
        tools=tools,
        model=model,
        clock=clock,
    )

    started_at = clock()
    result = agent.answer(
        "课程有哪些阶段？",
        source_filter="ai",
        timeout_seconds=configured_budget_seconds,
    )
    elapsed_seconds = clock() - started_at

    return {
        "configured_budget_seconds": configured_budget_seconds,
        "elapsed_seconds": elapsed_seconds,
        "budget_exceeded": elapsed_seconds > configured_budget_seconds,
        "model_timeout_seconds": model.timeout_seconds,
        "rag_timeout_seconds": tools.rag_timeout_seconds,
        "answer": result["answer"],
        "answer_source": result["answer_source"],
        "next_action": result["next_action"],
        "trace_tools": result["trace_tools"],
        "route_reason": result["route_reason"],
        "time_budget": result["time_budget"],
    }


def main() -> None:
    print(
        json.dumps(
            {
                "实验阶段": "接入 Deadline 之后",
                "预算充足": run_scenario(7.0),
                "最终生成超时": run_scenario(5.0),
                "RAG 超时且无文档": run_scenario(
                    5.0,
                    rag_required_seconds=5.0,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
