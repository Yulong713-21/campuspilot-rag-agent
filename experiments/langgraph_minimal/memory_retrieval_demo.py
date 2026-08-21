from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_retrieval import MemoryRecord, MemoryRetriever


def main() -> None:
    memories = [
        MemoryRecord(
            "A",
            "用户喜欢先讲原理再做实验。",
            60,
            0.65,
            0.9,
            1.0,
            0.8,
        ),
        MemoryRecord(
            "B",
            "用户熟悉后端开发，可以减少通用后端基础讲解。",
            80,
            0.82,
            0.8,
            1.0,
            0.9,
        ),
        MemoryRecord(
            "C",
            "用户喜欢川菜。",
            40,
            0.02,
            0.5,
            1.0,
            0.7,
        ),
        MemoryRecord(
            "D",
            "用户曾把 Deadline 误认为每次调用都会重新获得完整 Timeout。",
            150,
            0.94,
            0.85,
            1.0,
            0.9,
        ),
        MemoryRecord(
            "E",
            "上一个线程要求使用英文。",
            50,
            0.30,
            0.5,
            1.0,
            0.9,
            scope_active=False,
        ),
    ]
    result = MemoryRetriever().retrieve(memories, token_budget=300)

    print(
        json.dumps(
            {
                "query": "Deadline 和 Timeout 有什么区别？",
                "token_budget": result.token_budget,
                "selected": [
                    {
                        "memory_id": item.record.memory_id,
                        "score": item.score,
                        "tokens": item.record.estimated_tokens,
                    }
                    for item in result.selected
                ],
                "dropped": [
                    {
                        "memory_id": item.memory_id,
                        "reason": item.reason,
                    }
                    for item in result.dropped
                ],
                "used_tokens": result.used_tokens,
                "remaining_tokens": result.remaining_tokens,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
