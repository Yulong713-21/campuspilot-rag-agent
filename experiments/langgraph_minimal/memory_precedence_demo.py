from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_precedence import (
    MemoryPreferenceResolver,
    PreferenceCandidate,
)


def format_resolution(resolution) -> dict:
    return {
        "selected": asdict(resolution.selected),
        "ignored": [asdict(item) for item in resolution.ignored],
    }


def main() -> None:
    resolver = MemoryPreferenceResolver()
    long_term = PreferenceCandidate(
        "answer_detail",
        "简短",
        "long_term_memory",
    )
    product_default = PreferenceCandidate(
        "answer_detail",
        "中等",
        "product_default",
    )
    current_turn = PreferenceCandidate(
        "answer_detail",
        "详细",
        "current_turn",
    )

    current_result = resolver.resolve(
        "answer_detail",
        [long_term, product_default, current_turn],
    )
    next_turn_result = resolver.resolve(
        "answer_detail",
        [long_term, product_default],
    )

    print(
        json.dumps(
            {
                "当前轮明确要求详细": format_resolution(current_result),
                "下一轮没有临时要求": format_resolution(next_turn_result),
                "不可覆盖约束": (
                    "System 安全规则与权限检查不进入偏好排序，始终先执行。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
