from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_retrieval import MemoryRecord, MemoryRetriever


def memory(
    memory_id: str,
    tokens: int,
    relevance: float,
    importance: float = 0.8,
    confidence: float = 1.0,
    recency: float = 0.8,
    **kwargs,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=memory_id,
        content=f"Memory {memory_id}",
        estimated_tokens=tokens,
        relevance=relevance,
        importance=importance,
        confidence=confidence,
        recency=recency,
        **kwargs,
    )


class MemoryRetrieverTest(unittest.TestCase):
    def test_selects_dba_within_300_token_budget(self) -> None:
        memories = [
            memory("A", 60, 0.65, importance=0.9),
            memory("B", 80, 0.82),
            memory("C", 40, 0.02),
            memory("D", 150, 0.94, importance=0.85, recency=0.9),
            memory("E", 50, 0.30, scope_active=False),
        ]

        result = MemoryRetriever().retrieve(memories, token_budget=300)

        self.assertEqual(
            [item.record.memory_id for item in result.selected],
            ["D", "B", "A"],
        )
        self.assertEqual(result.used_tokens, 290)
        self.assertEqual(result.remaining_tokens, 10)
        self.assertEqual(
            {item.memory_id: item.reason for item in result.dropped},
            {
                "C": "below_relevance_threshold",
                "E": "scope_expired",
            },
        )

    def test_skips_oversized_memory_and_checks_later_candidate(self) -> None:
        result = MemoryRetriever().retrieve(
            [
                memory("A", 90, 0.9),
                memory("B", 30, 0.8),
                memory("C", 10, 0.7),
            ],
            token_budget=100,
        )

        self.assertEqual(
            [item.record.memory_id for item in result.selected],
            ["A", "C"],
        )
        self.assertEqual(result.dropped[0].memory_id, "B")
        self.assertEqual(result.dropped[0].reason, "token_budget_exceeded")

    def test_rejects_untrusted_and_sensitive_memories(self) -> None:
        result = MemoryRetriever().retrieve(
            [
                memory("A", 20, 0.9, trusted=False),
                memory("B", 20, 0.9, sensitive=True),
            ],
            token_budget=100,
        )

        self.assertEqual(result.selected, [])
        self.assertEqual(
            {item.memory_id: item.reason for item in result.dropped},
            {
                "A": "untrusted_source",
                "B": "sensitive_memory",
            },
        )

    def test_rejects_negative_token_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "token_budget"):
            MemoryRetriever().retrieve([], token_budget=-1)


if __name__ == "__main__":
    unittest.main()
