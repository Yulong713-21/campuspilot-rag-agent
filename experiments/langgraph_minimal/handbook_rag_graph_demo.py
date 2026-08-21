from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_qa import HandbookQuestionAnsweringAgent


def document(*, quality: str, content: str) -> dict[str, Any]:
    scores = {
        "high": {"retrieval_channels": ["bm25", "dense"], "score": 0.031},
        "medium": {"retrieval_channels": ["dense"], "dense_score": 0.44},
        "low": {"retrieval_channels": ["dense"], "dense_score": 0.20},
    }
    return {
        "chunk_id": f"fit5120-{quality}",
        "document_id": f"fit5120-{quality}",
        "source_id": "monash-unit-fit5120-2026",
        "title": "Monash Unit FIT5120",
        "heading": "FIT5120 > Assessments",
        "handbook_year": 2026,
        "source_type": "unit_handbook",
        "source_url": "https://handbook.monash.edu/2026/units/FIT5120",
        "content": content,
        **scores[quality],
    }


class QueryAwareRetriever:
    def __init__(self, results: dict[str, list[dict[str, Any]]]) -> None:
        self.results = results

    def search(self, query: str, **_: Any) -> list[dict[str, Any]]:
        return self.results.get(query, [])


class FixedRewriter:
    def __init__(self, rewritten: str) -> None:
        self.rewritten = rewritten

    def rewrite(self, _: str) -> str:
        return self.rewritten


class FixedChatClient:
    def __init__(self, answer: str) -> None:
        self.answer = answer

    def chat(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {
            "message": {"content": self.answer},
            "model": "demo-model",
            "usage": {},
        }


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    rewritten_search = next(
        (
            item
            for item in result["trace"]
            if item["tool"] == "search_handbook_rewritten"
        ),
        None,
    )
    return {
        "answer_source": result["answer_source"],
        "confidence": result["confidence"],
        "retrieval_quality": result["retrieval_quality"],
        "original_query": result["original_query"],
        "effective_query": result["effective_query"],
        "retry_count": result["retry_count"],
        "rewritten_result_selected": (
            rewritten_search.get("selected") if rewritten_search else None
        ),
        "trace_tools": [item["tool"] for item in result["trace"]],
        "next_action": result["next_action"],
    }


def main() -> None:
    original = "这门课怎么考核"
    rewritten = "FIT5120 assessment examination handbook"
    medium = document(quality="medium", content="Assessment information summary.")
    high = document(
        quality="high",
        content="The unit uses project assessment and an examination.",
    )
    weak = document(quality="low", content="Unrelated course overview.")

    improved = HandbookQuestionAnsweringAgent(
        QueryAwareRetriever({original: [medium], rewritten: [high]}),
        FixedChatClient("该课程采用项目与考试考核。[1]"),
        FixedRewriter(rewritten),
    ).answer(original, handbook_year=2026)

    rejected = HandbookQuestionAnsweringAgent(
        QueryAwareRetriever({original: [medium], rewritten: [weak]}),
        query_rewriter=FixedRewriter(rewritten),
    ).answer(original, handbook_year=2026)

    invalid_citation = HandbookQuestionAnsweringAgent(
        QueryAwareRetriever({"FIT5120 怎么考核": [high]}),
        FixedChatClient("该课程有考试，但我没有给出证据编号。"),
    ).answer("FIT5120 怎么考核", handbook_year=2026)

    print(
        json.dumps(
            {
                "实验主题": "Handbook RAG LangGraph 可观测路由",
                "改写后召回更好": summarize(improved),
                "改写后召回更差": summarize(rejected),
                "模型答案缺少引用": summarize(invalid_citation),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
