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


def rag_error() -> dict[str, Any]:
    return {
        "tool": "search_rag",
        "ok": False,
        "data": {"documents": [], "count": 0, "source": "rag"},
        "error": "Milvus 临时连接失败",
        "error_type": "connection_error",
        "retryable": True,
    }


def rag_success() -> dict[str, Any]:
    documents = [{"content": "课程包含基础、项目和就业三个阶段。", "source": "ai"}]
    return {
        "tool": "search_rag",
        "ok": True,
        "data": {"documents": documents, "count": len(documents), "source": "rag"},
        "error": None,
        "error_type": None,
        "retryable": False,
    }


class SequencedTools:
    def __init__(self, rag_results: list[dict[str, Any]]) -> None:
        self.rag_results = rag_results
        self.rag_call_count = 0

    def search_faq(self, query: str, threshold: float = 0.85) -> dict[str, Any]:
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {"hit": False, "answer": None, "need_rag": True, "source": None},
            "error": None,
        }

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
    ) -> dict[str, Any]:
        index = min(self.rag_call_count, len(self.rag_results) - 1)
        self.rag_call_count += 1
        return self.rag_results[index]


def run_scenario(name: str, rag_results: list[dict[str, Any]]) -> dict[str, Any]:
    sleep_calls: list[float] = []
    tools = SequencedTools(rag_results)
    agent = RuleBasedToolAgent(  # type: ignore[arg-type]
        tools=tools,
        max_rag_retries=1,
        backoff_base_seconds=0.25,
        sleeper=sleep_calls.append,
        jitter=lambda upper_bound: upper_bound,
    )
    result = agent.answer("课程有哪些阶段？", source_filter="ai")
    return {
        "scenario": name,
        "rag_call_count": tools.rag_call_count,
        "retry_count": result["retry_count"],
        "recorded_backoff_seconds": sleep_calls,
        "route_reason": result["route_reason"],
        "next_action": result["next_action"],
        "trace_tools": result["trace_tools"],
    }


def main() -> int:
    results = [
        run_scenario("首次失败，重试成功", [rag_error(), rag_success()]),
        run_scenario("首次失败，重试仍失败", [rag_error(), rag_error()]),
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
