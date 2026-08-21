from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_consolidation import (
    MemoryConsolidator,
    MemoryUpdate,
    VersionedMemory,
)


def summarize(result) -> dict:
    return {
        "action": result.action,
        "reason": result.reason,
        "active_memory": (
            {
                "memory_id": result.active_memory.memory_id,
                "key": result.active_memory.key,
                "value": result.active_memory.value,
                "version": result.active_memory.version,
            }
            if result.active_memory
            else None
        ),
        "history": [
            {
                "memory_id": memory.memory_id,
                "value": memory.value,
                "version": memory.version,
                "status": memory.status,
                "superseded_by": memory.superseded_by,
            }
            for memory in result.memories
        ],
    }


def main() -> None:
    old = VersionedMemory(
        memory_id="stack-v1",
        user_id="user-1",
        key="primary_stack",
        value="Java",
        origin="explicit_user",
        version=1,
    )
    consolidator = MemoryConsolidator()

    explicit_update = consolidator.consolidate(
        [old],
        MemoryUpdate(
            memory_id="stack-v2",
            user_id="user-1",
            key="primary_stack",
            value="Python Agent",
            origin="explicit_user",
        ),
    )
    inference_conflict = consolidator.consolidate(
        [old],
        MemoryUpdate(
            memory_id="stack-inferred",
            user_id="user-1",
            key="primary_stack",
            value="Go",
            origin="model_inference",
        ),
    )

    print(
        json.dumps(
            {
                "实验": "长期记忆冲突与版本化",
                "用户明确更新": summarize(explicit_update),
                "模型推断冲突": summarize(inference_conflict),
                "召回规则": "只召回 status=active 的当前版本",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
