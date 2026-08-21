from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RAGQualityReport:
    retrieval_precision: float
    retrieval_recall: float
    reciprocal_rank: float
    answer_completeness: float
    answer_groundedness: float
    diagnosis: str
    owner: str

    def to_dict(self) -> dict[str, float | str]:
        return asdict(self)


class RAGQualityEvaluator:
    """Separates retrieval failures from answer-generation failures."""

    def evaluate(
        self,
        *,
        relevant_document_ids: list[str],
        retrieved_document_ids: list[str],
        required_claim_ids: list[str],
        answer_claim_ids: list[str],
        document_claims: dict[str, list[str]],
        external_judge_passed: bool | None = None,
    ) -> RAGQualityReport:
        relevant = set(relevant_document_ids)
        retrieved = set(retrieved_document_ids)
        required_claims = set(required_claim_ids)
        answer_claims = set(answer_claim_ids)
        retrieved_claims = {
            claim_id
            for document_id in retrieved_document_ids
            for claim_id in document_claims.get(document_id, [])
        }

        retrieval_precision = self._ratio(
            len(retrieved & relevant),
            len(retrieved_document_ids),
        )
        retrieval_recall = self._ratio(
            len(retrieved & relevant),
            len(relevant),
        )
        reciprocal_rank = self._reciprocal_rank(
            retrieved_document_ids,
            relevant,
        )
        answer_completeness = self._ratio(
            len(answer_claims & required_claims),
            len(required_claims),
        )
        answer_groundedness = self._ratio(
            len(answer_claims & retrieved_claims),
            len(answer_claims),
        )
        diagnosis, owner = self._diagnose(
            retrieval_recall=retrieval_recall,
            answer_completeness=answer_completeness,
            answer_groundedness=answer_groundedness,
            external_judge_passed=external_judge_passed,
        )

        return RAGQualityReport(
            retrieval_precision=retrieval_precision,
            retrieval_recall=retrieval_recall,
            reciprocal_rank=reciprocal_rank,
            answer_completeness=answer_completeness,
            answer_groundedness=answer_groundedness,
            diagnosis=diagnosis,
            owner=owner,
        )

    @staticmethod
    def _diagnose(
        *,
        retrieval_recall: float,
        answer_completeness: float,
        answer_groundedness: float,
        external_judge_passed: bool | None,
    ) -> tuple[str, str]:
        if retrieval_recall < 1.0:
            return "retrieval_miss", "retrieval"
        if answer_groundedness < 1.0:
            return "generation_unsupported", "generation"
        if answer_completeness < 1.0:
            return "generation_incomplete", "generation"
        if external_judge_passed is False:
            return "evaluator_false_negative", "evaluation"
        return "healthy", "none"

    @staticmethod
    def _reciprocal_rank(
        retrieved_document_ids: list[str],
        relevant_document_ids: set[str],
    ) -> float:
        for rank, document_id in enumerate(retrieved_document_ids, start=1):
            if document_id in relevant_document_ids:
                return round(1 / rank, 4)
        return 0.0

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0
