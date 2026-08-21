from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.context_budget import ContextBudgetPacker, ContextDocument


def document(
    document_id: str,
    relevance_score: float,
    estimated_tokens: int,
) -> ContextDocument:
    return ContextDocument(
        document_id=document_id,
        content=f"{document_id} content",
        relevance_score=relevance_score,
        estimated_tokens=estimated_tokens,
        source="ai",
    )


class ContextBudgetPackerTest(unittest.TestCase):
    def test_selects_abc_within_1896_token_budget(self) -> None:
        documents = [
            document("A", 0.92, 600),
            document("B", 0.88, 700),
            document("C", 0.81, 500),
            document("D", 0.76, 650),
            document("E", 0.70, 550),
        ]

        result = ContextBudgetPacker().pack(documents, token_budget=1896)

        self.assertEqual(
            [item.document_id for item in result.selected],
            ["A", "B", "C"],
        )
        self.assertEqual(
            [item.document_id for item in result.dropped],
            ["D", "E"],
        )
        self.assertEqual(result.used_tokens, 1800)
        self.assertEqual(result.remaining_tokens, 96)

    def test_checks_later_shorter_document_after_oversized_document(self) -> None:
        documents = [
            document("A", 0.9, 80),
            document("B", 0.8, 30),
            document("C", 0.7, 20),
        ]

        result = ContextBudgetPacker().pack(documents, token_budget=100)

        self.assertEqual(
            [item.document_id for item in result.selected],
            ["A", "C"],
        )
        self.assertEqual(
            [item.document_id for item in result.dropped],
            ["B"],
        )

    def test_rejects_negative_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "token_budget"):
            ContextBudgetPacker().pack([], token_budget=-1)

    def test_rejects_non_positive_document_tokens(self) -> None:
        with self.assertRaisesRegex(ValueError, "estimated_tokens"):
            document("A", 0.9, 0)


if __name__ == "__main__":
    unittest.main()
