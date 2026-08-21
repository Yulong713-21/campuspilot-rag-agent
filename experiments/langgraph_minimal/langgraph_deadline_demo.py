from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.graph_agent import LangGraphEduRAGAgent


class DemoClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class DemoTools:
    def __init__(
        self,
        clock: DemoClock,
        faq_seconds: float,
        rag_seconds: float,
    ) -> None:
        self.clock = clock
        self.faq_seconds = faq_seconds
        self.rag_seconds = rag_seconds
        self.rag_timeouts: list[float | None] = []

    def search_faq(self, query: str, threshold: float = 0.85):
        self.clock.advance(self.faq_seconds)
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
    ):
        self.rag_timeouts.append(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds < self.rag_seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("RAG timeout")
        self.clock.advance(self.rag_seconds)
        documents = [
            {
                "content": "课程包含基础、项目和就业三个阶段。",
                "metadata": {
                    "document_id": "course",
                    "estimated_tokens": 50,
                    "relevance_score": 0.95,
                },
                "source": "course.md",
            }
        ]
        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": documents,
                "count": 1,
                "source": "rag",
            },
            "error": None,
        }


class DemoLLM:
    def __init__(self, clock: DemoClock, seconds: float) -> None:
        self.clock = clock
        self.seconds = seconds
        self.timeouts: list[float | None] = []

    def generate_grounded_answer(
        self,
        query: str,
        context: str,
        timeout_seconds: float | None = None,
    ) -> str:
        self.timeouts.append(timeout_seconds)
        if timeout_seconds is not None and timeout_seconds < self.seconds:
            self.clock.advance(timeout_seconds)
            raise TimeoutError("generation timeout")
        self.clock.advance(self.seconds)
        return "课程包含基础、项目和就业三个阶段。"


def run(
    total: float,
    reserve: float,
    faq_seconds: float,
    rag_seconds: float,
    generation_seconds: float,
) -> dict:
    clock = DemoClock()
    tools = DemoTools(clock, faq_seconds, rag_seconds)
    llm = DemoLLM(clock, generation_seconds)
    agent = LangGraphEduRAGAgent(
        tools=tools,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        use_ollama=True,
        clock=clock,
        generation_reserve_seconds=reserve,
    )
    result = agent.answer("课程有哪些阶段？", timeout_seconds=total)
    return {
        "configured_deadline_seconds": total,
        "generation_reserve_seconds": reserve,
        "rag_timeout_seconds": tools.rag_timeouts,
        "llm_timeout_seconds": llm.timeouts,
        "answer_source": result["answer_source"],
        "route_reason": result["route_reason"],
        "next_action": result["next_action"],
        "document_count": len(result["documents"]),
        "time_budget": result["time_budget"],
    }


def main() -> None:
    print(
        json.dumps(
            {
                "实验": "统一 LangGraph 的端到端 Deadline",
                "预算充足": run(7.0, 2.0, 0.5, 2.0, 1.5),
                "最终生成超时": run(5.0, 1.0, 0.5, 2.5, 3.0),
                "RAG 超时": run(4.0, 1.5, 0.5, 3.0, 1.0),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
