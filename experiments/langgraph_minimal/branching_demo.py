from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.graph_agent import LangGraphEduRAGAgent


class ScenarioTools:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.rag_calls = 0

    def search_faq(self, query: str, threshold: float = 0.85):
        hit = self.scenario == "faq_hit"
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {
                "hit": hit,
                "answer": "这是 FAQ 结构化问答直接返回的答案。" if hit else None,
                "need_rag": not hit,
                "source": "faq" if hit else None,
            },
            "error": None,
        }

    def search_rag(self, query: str, source_filter: str | None = None, k: int | None = None):
        self.rag_calls += 1
        if self.scenario == "rag_supported":
            documents = [
                {
                    "content": "人工智能课程包含大模型开发、LangChain、RAG 检索增强、Function Calling 和 Agent 项目实战。",
                    "metadata": {"source": source_filter},
                    "source": source_filter,
                }
            ]
        elif self.scenario == "rewrite_success" and self.rag_calls > 1:
            documents = [
                {
                    "content": "改写后的问题命中了人工智能课程资料：课程包含 RAG、Agent、Function Calling 和大模型项目阶段。",
                    "metadata": {"source": source_filter},
                    "source": source_filter,
                }
            ]
        else:
            documents = []

        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": documents,
                "count": len(documents),
                "source": "rag",
            },
            "error": None,
        }


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "rag_supported"
    if scenario not in {"faq_hit", "rag_supported", "rewrite_success", "rag_empty"}:
        raise SystemExit(
            "scenario must be one of: faq_hit, rag_supported, rewrite_success, rag_empty"
        )

    agent = LangGraphEduRAGAgent(tools=ScenarioTools(scenario))  # type: ignore[arg-type]
    result = agent.answer("人工智能课程包含哪些 Agent 相关内容？", source_filter="ai")
    summary = {
        "scenario": scenario,
        "answer_source": result["answer_source"],
        "confidence": result["confidence"],
        "next_action": result["next_action"],
        "original_query": result["original_query"],
        "effective_query": result["effective_query"],
        "retry_count": result["retry_count"],
        "evaluation": result["evaluation"],
        "trace_tools": [step["tool"] for step in result["trace"]],
        "answer": result["answer"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
