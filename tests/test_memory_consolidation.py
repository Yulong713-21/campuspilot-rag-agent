from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_consolidation import (
    MemoryConsolidator,
    MemoryUpdate,
    VersionedMemory,
)


def active_memory(
    memory_id: str = "memory-v1",
    key: str = "primary_stack",
    value: str = "Java",
) -> VersionedMemory:
    return VersionedMemory(
        memory_id=memory_id,
        user_id="user-1",
        key=key,
        value=value,
        origin="explicit_user",
        version=1,
    )


class MemoryConsolidatorTest(unittest.TestCase):
    def test_explicit_update_supersedes_old_value_and_preserves_history(self) -> None:
        old = active_memory()

        result = MemoryConsolidator().consolidate(
            [old],
            MemoryUpdate(
                memory_id="memory-v2",
                user_id="user-1",
                key="primary_stack",
                value="Python Agent",
                origin="explicit_user",
            ),
        )

        self.assertEqual(result.action, "superseded")
        self.assertEqual(result.active_memory.value, "Python Agent")
        self.assertEqual(result.active_memory.version, 2)
        self.assertEqual(result.memories[0].status, "superseded")
        self.assertEqual(result.memories[0].superseded_by, "memory-v2")

    def test_duplicate_write_is_ignored(self) -> None:
        old = active_memory()

        result = MemoryConsolidator().consolidate(
            [old],
            MemoryUpdate(
                memory_id="duplicate",
                user_id="user-1",
                key="primary_stack",
                value="Java",
                origin="explicit_user",
            ),
        )

        self.assertEqual(result.action, "duplicate_ignored")
        self.assertEqual(result.memories, [old])

    def test_model_inference_cannot_replace_explicit_memory(self) -> None:
        old = active_memory()

        result = MemoryConsolidator().consolidate(
            [old],
            MemoryUpdate(
                memory_id="inferred",
                user_id="user-1",
                key="primary_stack",
                value="Go",
                origin="model_inference",
            ),
        )

        self.assertEqual(result.action, "require_confirmation")
        self.assertEqual(result.active_memory, old)
        self.assertEqual(result.memories, [old])

    def test_different_key_creates_independent_active_memory(self) -> None:
        old = active_memory()

        result = MemoryConsolidator().consolidate(
            [old],
            MemoryUpdate(
                memory_id="style-v1",
                user_id="user-1",
                key="answer_style",
                value="先讲原理，再展示实验",
                origin="explicit_user",
            ),
        )

        self.assertEqual(result.action, "created")
        self.assertEqual(result.active_memory.version, 1)
        self.assertEqual(len(result.memories), 2)


if __name__ == "__main__":
    unittest.main()
