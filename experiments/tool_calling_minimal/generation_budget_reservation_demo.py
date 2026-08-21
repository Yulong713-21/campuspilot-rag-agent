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

    def spend(self, required: float, timeout: float | None) -> None:
        if timeout is not None and timeout < required:
            self.current += timeout
            raise TimeoutError("调用超过分配预算")
        self.current += required


class TimedModel:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.call_count = 0
        self.timeouts: list[float | None] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        self.call_count += 1
        if self.call_count == 1:
            self.clock.spend(1.0, timeout_seconds)
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
        self.clock.spend(2.0, timeout_seconds)
        return {
            "role": "assistant",
            "content": "课程包括基础、项目和就业三个阶段。",
        }


class RetryingRagTools:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.timeouts: list[float | None] = []
        self.retry_timeouts: list[float | None] = []

    def search_faq(self, query: str) -> dict[str, Any]:
        raise AssertionError("本实验不调用 FAQ")

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.timeouts.append(timeout_seconds)
        # 首次网络失败 0.4 秒，退避 0.2 秒，重试成功 1.2 秒。
        self.clock.spend(0.4, timeout_seconds)
        remaining = (
            None if timeout_seconds is None else max(timeout_seconds - 0.4, 0.0)
        )
        self.clock.spend(0.2, remaining)
        remaining = None if remaining is None else max(remaining - 0.2, 0.0)
        self.retry_timeouts.append(
            None if remaining is None else round(remaining, 3)
        )
        self.clock.spend(1.2, remaining)
        documents = [{"content": "课程包括基础、项目和就业三个阶段。"}]
        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": documents,
                "count": 1,
                "source": "rag",
            },
            "error": None,
            "error_type": None,
            "retryable": False,
        }


def main() -> None:
    clock = FakeClock()
    model = TimedModel(clock)
    tools = RetryingRagTools(clock)
    agent = LLMToolCallingAgent(  # type: ignore[arg-type]
        tools=tools,
        model=model,
        clock=clock,
        generation_reserve_seconds=2.0,
    )

    result = agent.answer(
        "课程有哪些阶段？",
        source_filter="ai",
        timeout_seconds=5.0,
    )

    print(
        json.dumps(
            {
                "总预算": 5.0,
                "最终生成预留": 2.0,
                "RAG过程": {
                    "首次失败": 0.4,
                    "退避": 0.2,
                    "重试成功": 1.2,
                },
                "model_timeout_seconds": model.timeouts,
                "rag_timeout_seconds": tools.timeouts,
                "rag_retry_timeout_seconds": tools.retry_timeouts,
                "answer": result["answer"],
                "answer_source": result["answer_source"],
                "route_reason": result["route_reason"],
                "time_budget": result["time_budget"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
