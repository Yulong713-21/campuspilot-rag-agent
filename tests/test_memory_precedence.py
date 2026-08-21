from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_precedence import (
    MemoryPreferenceResolver,
    PreferenceCandidate,
)


class MemoryPreferenceResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = MemoryPreferenceResolver()

    def test_current_turn_overrides_long_term_memory(self) -> None:
        result = self.resolver.resolve(
            "answer_detail",
            [
                PreferenceCandidate(
                    "answer_detail",
                    "简短",
                    "long_term_memory",
                ),
                PreferenceCandidate(
                    "answer_detail",
                    "详细",
                    "current_turn",
                ),
            ],
        )

        self.assertEqual(result.selected.value, "详细")
        self.assertEqual(result.selected.source, "current_turn")

    def test_long_term_memory_returns_after_turn_override_expires(self) -> None:
        result = self.resolver.resolve(
            "answer_detail",
            [
                PreferenceCandidate(
                    "answer_detail",
                    "简短",
                    "long_term_memory",
                ),
                PreferenceCandidate(
                    "answer_detail",
                    "中等",
                    "product_default",
                ),
            ],
        )

        self.assertEqual(result.selected.value, "简短")
        self.assertEqual(result.selected.source, "long_term_memory")

    def test_thread_preference_overrides_long_term_memory(self) -> None:
        result = self.resolver.resolve(
            "answer_language",
            [
                PreferenceCandidate(
                    "answer_language",
                    "英文",
                    "long_term_memory",
                ),
                PreferenceCandidate(
                    "answer_language",
                    "中文",
                    "thread",
                ),
            ],
        )

        self.assertEqual(result.selected.value, "中文")
        self.assertEqual(result.selected.source, "thread")

    def test_requires_at_least_one_matching_candidate(self) -> None:
        with self.assertRaisesRegex(ValueError, "no preference candidate"):
            self.resolver.resolve("answer_style", [])


if __name__ == "__main__":
    unittest.main()
