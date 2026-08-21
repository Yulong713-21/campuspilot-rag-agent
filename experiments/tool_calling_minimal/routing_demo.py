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


class ScenarioTools:
    def __init__(
        self,
        faq_hit: bool,
        rag_ok: bool,
        documents: list[dict[str, Any]],
        error_type: str | None = None,
        retryable: bool = False,
    ) -> None:
        self.faq_hit = faq_hit
        self.rag_ok = rag_ok
        self.documents = documents
        self.error_type = error_type
        self.retryable = retryable

    def search_faq(self, query: str, threshold: float = 0.85) -> dict[str, Any]:
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {
                "hit": self.faq_hit,
                "answer": "这是 FAQ 标准答案。" if self.faq_hit else None,
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
    ) -> dict[str, Any]:
        return {
            "tool": "search_rag",
            "ok": self.rag_ok,
            "data": {
                "documents": self.documents,
                "count": len(self.documents),
                "source": "rag",
            },
            "error": None if self.rag_ok else "Milvus 连接失败",
            "error_type": self.error_type,
            "retryable": self.retryable,
        }


def main() -> int:
    scenarios = {
        "FAQ 命中": ScenarioTools(faq_hit=True, rag_ok=True, documents=[]),
        "RAG 有证据": ScenarioTools(
            faq_hit=False,
            rag_ok=True,
            documents=[{"content": "课程包含基础、项目和就业三个阶段。", "source": "ai"}],
        ),
        "RAG 空结果": ScenarioTools(faq_hit=False, rag_ok=True, documents=[]),
        "RAG 临时故障": ScenarioTools(
            faq_hit=False,
            rag_ok=False,
            documents=[],
            error_type="connection_error",
            retryable=True,
        ),
        "RAG 权限错误": ScenarioTools(
            faq_hit=False,
            rag_ok=False,
            documents=[],
            error_type="permission_error",
            retryable=False,
        ),
    }

    results = []
    for name, tools in scenarios.items():
        result = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=tools,
            sleeper=lambda _: None,
            jitter=lambda upper_bound: upper_bound,
        ).answer(
            "课程有哪些阶段？",
            source_filter="ai",
        )
        results.append(
            {
                "scenario": name,
                "answer_source": result["answer_source"],
                "confidence": result["confidence"],
                "next_action": result["next_action"],
                "route_reason": result["route_reason"],
                "route_trace": result["route_trace"],
                "trace_tools": result["trace_tools"],
                "error_type": result["trace"][-1].get("error_type"),
                "retryable": result["trace"][-1].get("retryable"),
                "retry_count": result["retry_count"],
            }
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
