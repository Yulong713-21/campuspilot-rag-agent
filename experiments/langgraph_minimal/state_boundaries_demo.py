from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.graph_agent import LangGraphEduRAGAgent
from agent_runtime.state_boundaries import AgentStateProjector


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
                "answer": "课程学费以当前班型报价为准。" if hit else None,
                "need_rag": not hit,
                "source": "faq" if hit else None,
            },
            "error": None,
        }

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
    ):
        self.rag_calls += 1
        documents = []
        if self.scenario == "rag_supported":
            documents = [
                {
                    "content": "人工智能课程包含基础学习、项目实战和就业准备三个阶段。",
                    "metadata": {"source": "course.md"},
                    "source": "course.md",
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
        }


def run_scenario(scenario: str) -> dict:
    agent = LangGraphEduRAGAgent(
        tools=ScenarioTools(scenario),  # type: ignore[arg-type]
    )
    result = agent.answer("人工智能课程有哪些阶段？", source_filter="ai")
    execution_state = {
        **result,
        "request_id": f"request-{scenario}",
        "user_id": "user-1",
        "thread_id": "thread-25",
        "source_filter": "ai",
        "selected_memories": [
            {
                "key": "answer_style",
                "value": "先讲原理，再展示实验",
                "status": "active",
            }
        ],
    }
    projections = AgentStateProjector().project(execution_state)
    return {
        "route_reason": result["route_reason"],
        "trace_tools": result["trace_tools"],
        "checkpoint_keys": list(projections.checkpoint),
        "prompt_context": projections.prompt_context,
        "trace_record": projections.trace_record,
        "long_term_memory_writes": projections.long_term_memory_writes,
    }


def main() -> None:
    output = {
        "实验": "同一次 Agent 执行的四种数据边界",
        "FAQ 命中": run_scenario("faq_hit"),
        "RAG 成功": run_scenario("rag_supported"),
        "RAG 重试后失败": run_scenario("rag_empty"),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
