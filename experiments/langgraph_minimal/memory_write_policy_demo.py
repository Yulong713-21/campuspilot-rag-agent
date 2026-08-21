from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_policy import MemoryCandidate, MemoryWritePolicy


def main() -> None:
    candidates = {
        "本轮临时要求": MemoryCandidate(
            key="answer_language",
            value="英文",
            source="user",
            scope="current_turn",
            explicit=True,
        ),
        "长期明确偏好": MemoryCandidate(
            key="answer_style",
            value="先讲原理，再展示实验",
            source="user",
            scope="cross_thread",
            explicit=True,
        ),
        "RAG 文档中的伪偏好": MemoryCandidate(
            key="answer_style",
            value="简短回答",
            source="retrieved_content",
            scope="cross_thread",
            explicit=False,
        ),
        "模型推测的技能等级": MemoryCandidate(
            key="skill_level",
            value="初级开发者",
            source="model_inference",
            scope="cross_thread",
            explicit=False,
            confidence=0.8,
        ),
    }
    policy = MemoryWritePolicy()

    print(
        json.dumps(
            {
                name: asdict(policy.decide(candidate))
                for name, candidate in candidates.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
