from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.tool_agent import RuleBasedToolAgent


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleep_calls: list[float] = []

    def __call__(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.current += seconds


class TimedTools:
    def __init__(self, clock: FakeClock, succeed_on_call: int) -> None:
        self.clock = clock
        self.succeed_on_call = succeed_on_call
        self.rag_call_count = 0
        self.rag_timeout_seconds: list[float | None] = []

    def search_faq(self, query: str, threshold: float = 0.85) -> dict[str, Any]:
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
    ) -> dict[str, Any]:
        self.rag_call_count += 1
        self.rag_timeout_seconds.append(timeout_seconds)
        self.clock.current += 3.0
        if self.rag_call_count >= self.succeed_on_call:
            documents = [{"content": "课程包含基础、项目和就业三个阶段。", "source": "ai"}]
            return {
                "tool": "search_rag",
                "ok": True,
                "data": {"documents": documents, "count": 1, "source": "rag"},
                "error": None,
                "error_type": None,
                "retryable": False,
            }
        return {
            "tool": "search_rag",
            "ok": False,
            "data": {"documents": [], "count": 0, "source": "rag"},
            "error": "Milvus 临时连接失败",
            "error_type": "connection_error",
            "retryable": True,
        }


def run_scenario(timeout_seconds: float) -> dict[str, Any]:
    clock = FakeClock()
    tools = TimedTools(clock=clock, succeed_on_call=3)
    agent = RuleBasedToolAgent(  # type: ignore[arg-type]
        tools=tools,
        max_rag_retries=2,
        backoff_base_seconds=0.5,
        sleeper=clock.sleep,
        jitter=lambda upper_bound: upper_bound,
        clock=clock,
        minimum_retry_call_budget_seconds=3.0,
    )
    result = agent.answer(
        "课程有哪些阶段？",
        source_filter="ai",
        timeout_seconds=timeout_seconds,
    )
    return {
        "timeout_seconds": timeout_seconds,
        "rag_call_count": tools.rag_call_count,
        "retry_count": result["retry_count"],
        "sleep_calls": clock.sleep_calls,
        "rag_timeout_seconds": tools.rag_timeout_seconds,
        "route_reason": result["route_reason"],
        "next_action": result["next_action"],
        "time_budget": result["time_budget"],
    }


def main() -> int:
    results = [run_scenario(8.0), run_scenario(11.0)]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
