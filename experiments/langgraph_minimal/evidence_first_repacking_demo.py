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


class SingleDocumentTools:
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
                            "document_id": "A",
                            "estimated_tokens": 180,
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


def memory(memory_id: str, tokens: int) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        content=f"用户个性化偏好 {memory_id}",
        estimated_tokens=tokens,
        relevance=0.9,
        importance=0.9,
        confidence=1.0,
        recency=1.0,
    )


def main() -> None:
    agent = LangGraphEduRAGAgent(
        tools=SingleDocumentTools(),  # type: ignore[arg-type]
        memory_loader=lambda user_id, query: [
            memory("M1", 25),
            memory("M2", 20),
        ],
        memory_budget_ratio=0.2,
    )
    result = agent.answer(
        "课程有哪些阶段？",
        user_id="user-1",
        context_token_budget=200,
    )

    output = {
        "实验": "证据优先后的剩余预算二次装箱",
        "输入": {
            "total_budget": 200,
            "initial_memory_cap": 40,
            "memories": {"M1": 25, "M2": 20},
            "rag_documents": {"A": 180},
        },
        "旧策略": {
            "selected_rag": ["A"],
            "selected_memory": [],
            "used_tokens": 180,
            "remaining_tokens": 20,
        },
        "新策略": {
            "selected_rag": [
                item["metadata"]["document_id"] for item in result["documents"]
            ],
            "selected_memory": [
                item["memory_id"] for item in result["selected_memories"]
            ],
            "memory_policy": result["memory_policy"],
            "context_policy": result["context_policy"],
        },
        "结论": "先保证事实证据，再用剩余预算重新选择个性化 Memory。",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
