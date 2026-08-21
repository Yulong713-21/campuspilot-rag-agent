from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.graph_agent import LangGraphEduRAGAgent
from agent_runtime.memory_retrieval import MemoryRecord


class BudgetTools:
    def __init__(self, rag_tokens: int) -> None:
        self.rag_tokens = rag_tokens

    def search_faq(self, query: str, threshold: float = 0.85):
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
    ):
        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": [
                    {
                        "content": "课程包含基础、项目和就业三个阶段。",
                        "metadata": {
                            "document_id": "course",
                            "estimated_tokens": self.rag_tokens,
                            "relevance_score": 0.95,
                        },
                        "source": "course.md",
                    }
                ],
                "count": 1,
                "source": "rag",
            },
            "error": None,
        }


def memory(tokens: int) -> MemoryRecord:
    return MemoryRecord(
        memory_id="answer-style",
        content="用户偏好：先讲原理，再展示实验。",
        estimated_tokens=tokens,
        relevance=0.9,
        importance=0.9,
        confidence=1.0,
        recency=1.0,
    )


def run(rag_tokens: int, memories: list[MemoryRecord]) -> dict:
    agent = LangGraphEduRAGAgent(
        tools=BudgetTools(rag_tokens),  # type: ignore[arg-type]
        memory_loader=lambda user_id, query: memories,
        memory_budget_ratio=0.2,
    )
    result = agent.answer(
        "课程有哪些阶段？",
        user_id="user-1",
        context_token_budget=100,
    )
    return {
        "memory_policy": result["memory_policy"],
        "context_policy": result["context_policy"],
        "selected_memory_ids": [
            item["memory_id"] for item in result["selected_memories"]
        ],
        "selected_document_ids": [
            item["metadata"]["document_id"] for item in result["documents"]
        ],
        "trace_tools": result["trace_tools"],
    }


def main() -> None:
    print(
        json.dumps(
            {
                "实验": "Memory 与 RAG 共享 100-token 上下文预算",
                "Memory 20 + RAG 80": run(80, [memory(20)]),
                "没有可用 Memory": run(100, []),
                "Memory 超过自身上限": run(100, [memory(30)]),
                "Memory 挡住高质量 RAG": run(90, [memory(20)]),
                "优先级": "事实证据完整性 > 个性化表达",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
