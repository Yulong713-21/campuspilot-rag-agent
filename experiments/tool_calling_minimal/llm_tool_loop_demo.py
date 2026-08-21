from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.llm_tool_agent import LLMToolCallingAgent


class ScriptedToolModel:
    def __init__(self) -> None:
        self.call_count = 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.call_count += 1
        if self.call_count == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "search_faq",
                            "arguments": {"query": "人工智能就业课有哪些阶段？"},
                        },
                    }
                ],
            }
        if self.call_count == 2:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "search_rag",
                            "arguments": {
                                "query": "人工智能就业课有哪些阶段？",
                                "source_filter": "ai",
                            },
                        },
                    }
                ],
            }
        return {
            "role": "assistant",
            "content": "课程包括基础学习、项目实战和就业准备三个阶段。",
        }


class DemoTools:
    def search_faq(self, query: str) -> dict[str, Any]:
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {
                "hit": False,
                "answer": None,
                "need_rag": True,
                "source": None,
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
        documents = [
            {
                "content": "人工智能就业课包括基础学习、项目实战和就业准备三个阶段。",
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


def main() -> int:
    agent = LLMToolCallingAgent(  # type: ignore[arg-type]
        tools=DemoTools(),
        model=ScriptedToolModel(),
    )
    result = agent.answer("人工智能就业课有哪些阶段？", source_filter="ai")
    summary = {
        "answer": result["answer"],
        "answer_source": result["answer_source"],
        "confidence": result["confidence"],
        "next_action": result["next_action"],
        "tool_round_count": result["tool_round_count"],
        "trace_tools": result["trace_tools"],
        "route_reason": result["route_reason"],
        "route_trace": result["route_trace"],
        "document_count": len(result["documents"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
