from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.rag_quality import RAGQualityEvaluator


class RAGQualityEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluator = RAGQualityEvaluator()
        self.base = {
            "relevant_document_ids": ["course-outline"],
            "required_claim_ids": ["basic", "project", "career"],
            "document_claims": {
                "course-outline": ["basic", "project", "career"],
                "tuition": ["price"],
            },
        }

    def test_retrieval_miss_is_owned_by_retrieval(self) -> None:
        report = self.evaluator.evaluate(
            **self.base,
            retrieved_document_ids=["tuition"],
            answer_claim_ids=[],
        )

        self.assertEqual(report.retrieval_recall, 0.0)
        self.assertEqual(report.diagnosis, "retrieval_miss")
        self.assertEqual(report.owner, "retrieval")

    def test_unsupported_claim_is_owned_by_generation(self) -> None:
        report = self.evaluator.evaluate(
            **self.base,
            retrieved_document_ids=["course-outline"],
            answer_claim_ids=["basic", "project", "career", "guaranteed_job"],
        )

        self.assertEqual(report.retrieval_recall, 1.0)
        self.assertEqual(report.answer_groundedness, 0.75)
        self.assertEqual(report.diagnosis, "generation_unsupported")

    def test_incomplete_answer_is_owned_by_generation(self) -> None:
        report = self.evaluator.evaluate(
            **self.base,
            retrieved_document_ids=["course-outline"],
            answer_claim_ids=["basic", "project"],
        )

        self.assertEqual(report.answer_groundedness, 1.0)
        self.assertEqual(report.answer_completeness, 0.6667)
        self.assertEqual(report.diagnosis, "generation_incomplete")

    def test_false_negative_is_owned_by_evaluation(self) -> None:
        report = self.evaluator.evaluate(
            **self.base,
            retrieved_document_ids=["course-outline"],
            answer_claim_ids=["basic", "project", "career"],
            external_judge_passed=False,
        )

        self.assertEqual(report.answer_groundedness, 1.0)
        self.assertEqual(report.answer_completeness, 1.0)
        self.assertEqual(report.diagnosis, "evaluator_false_negative")
        self.assertEqual(report.owner, "evaluation")

    def test_rank_score_penalizes_late_relevant_document(self) -> None:
        report = self.evaluator.evaluate(
            **self.base,
            retrieved_document_ids=["tuition", "noise", "course-outline"],
            answer_claim_ids=["basic", "project", "career"],
        )

        self.assertEqual(report.retrieval_precision, 0.3333)
        self.assertEqual(report.retrieval_recall, 1.0)
        self.assertEqual(report.reciprocal_rank, 0.3333)

    def test_duplicate_result_does_not_inflate_precision(self) -> None:
        report = self.evaluator.evaluate(
            **self.base,
            retrieved_document_ids=["course-outline", "course-outline"],
            answer_claim_ids=["basic", "project", "career"],
        )

        self.assertEqual(report.retrieval_precision, 0.5)
        self.assertEqual(report.retrieval_recall, 1.0)


if __name__ == "__main__":
    unittest.main()
