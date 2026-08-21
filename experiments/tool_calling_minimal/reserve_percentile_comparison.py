from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestSample:
    rag_seconds: float
    generation_seconds: float


SAMPLES = (
    [RequestSample(rag_seconds=2.0, generation_seconds=1.2) for _ in range(15)]
    + [RequestSample(rag_seconds=2.5, generation_seconds=1.8) for _ in range(2)]
    + [RequestSample(rag_seconds=3.0, generation_seconds=1.8) for _ in range(2)]
    + [RequestSample(rag_seconds=3.5, generation_seconds=3.6)]
)


def evaluate_reserve(
    reserve_seconds: float,
    total_timeout_seconds: float = 5.0,
    tool_selection_seconds: float = 0.5,
) -> dict[str, float | int]:
    complete_answers = 0
    partial_fallbacks = 0
    cache_fallbacks = 0
    wasted_rag_seconds = 0.0
    retrieval_budget = (
        total_timeout_seconds - tool_selection_seconds - reserve_seconds
    )

    for sample in SAMPLES:
        if sample.rag_seconds > retrieval_budget:
            cache_fallbacks += 1
            continue

        final_generation_budget = (
            total_timeout_seconds
            - tool_selection_seconds
            - sample.rag_seconds
        )
        if sample.generation_seconds <= final_generation_budget:
            complete_answers += 1
        else:
            partial_fallbacks += 1
            wasted_rag_seconds += sample.rag_seconds

    sample_count = len(SAMPLES)
    return {
        "generation_reserve_seconds": reserve_seconds,
        "retrieval_budget_seconds": round(max(retrieval_budget, 0.0), 3),
        "complete_answers": complete_answers,
        "complete_answer_rate": round(complete_answers / sample_count, 3),
        "partial_fallbacks": partial_fallbacks,
        "cache_fallbacks": cache_fallbacks,
        "wasted_rag_seconds": round(wasted_rag_seconds, 3),
    }


def main() -> None:
    result = {
        "实验请求数": len(SAMPLES),
        "总 Deadline": 5.0,
        "前置模型耗时": 0.5,
        "策略对比": {
            "平均值预留": evaluate_reserve(1.1),
            "P95 加余量": evaluate_reserve(2.0),
            "P99 加余量": evaluate_reserve(3.8),
        },
        "说明": (
            "缓存降级假设存在可接受的新鲜缓存；没有缓存时应改为受控失败。"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
