from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.tool_agent import RuleBasedToolAgent


def compact_trace(trace: list[dict]) -> list[dict]:
    compact = []
    for step in trace:
        data = step.get("data", {})
        compact.append(
            {
                "tool": step.get("tool"),
                "ok": step.get("ok"),
                "hit": data.get("hit"),
                "need_rag": data.get("need_rag"),
                "count": data.get("count"),
                "source": data.get("source"),
                "error": step.get("error"),
                "error_type": step.get("error_type"),
                "retryable": step.get("retryable"),
            }
        )
    return compact


def main() -> int:
    os.environ.setdefault("EDURAG_PROJECT_ROOT", r"D:\agentdev\integrated_qa_system")
    os.environ.setdefault("EDURAG_LIGHT_EMBEDDING", "1")

    query = sys.argv[1] if len(sys.argv) > 1 else "人工智能就业课课程大纲有哪些阶段和模块？"
    source_filter = sys.argv[2] if len(sys.argv) > 2 else "ai"
    timeout_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else None

    agent = RuleBasedToolAgent()
    result = agent.answer(
        query,
        source_filter=source_filter,
        timeout_seconds=timeout_seconds,
    )
    summary = {
        "answer_source": result["answer_source"],
        "confidence": result["confidence"],
        "next_action": result["next_action"],
        "original_query": result["original_query"],
        "effective_query": result["effective_query"],
        "retry_count": result["retry_count"],
        "document_count": len(result["documents"]),
        "trace_tools": result["trace_tools"],
        "route_reason": result["route_reason"],
        "route_trace": result["route_trace"],
        "time_budget": result["time_budget"],
        "trace": compact_trace(result["trace"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
