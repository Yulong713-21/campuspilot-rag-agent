from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class JudgeCalibrationReport:
    total_cases: int
    human_pass_cases: int
    human_fail_cases: int
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    alignment_rate: float
    judge_precision: float
    judge_recall: float
    false_pass_rate: float
    false_reject_rate: float
    release_gate_passed: bool

    def to_dict(self) -> dict[str, int | float | bool]:
        return asdict(self)


class JudgeCalibrationEvaluator:
    """Compares an automated judge with human reference labels."""

    def evaluate(
        self,
        human_labels: list[bool],
        judge_labels: list[bool],
        *,
        max_false_pass_rate: float = 0.0,
        max_false_reject_rate: float = 0.1,
        minimum_alignment_rate: float = 0.9,
    ) -> JudgeCalibrationReport:
        if len(human_labels) != len(judge_labels):
            raise ValueError("human_labels and judge_labels must have equal length")

        true_positive = sum(
            human and judge
            for human, judge in zip(human_labels, judge_labels)
        )
        true_negative = sum(
            not human and not judge
            for human, judge in zip(human_labels, judge_labels)
        )
        false_positive = sum(
            not human and judge
            for human, judge in zip(human_labels, judge_labels)
        )
        false_negative = sum(
            human and not judge
            for human, judge in zip(human_labels, judge_labels)
        )
        human_pass_cases = sum(human_labels)
        human_fail_cases = len(human_labels) - human_pass_cases
        alignment_rate = self._ratio(
            true_positive + true_negative,
            len(human_labels),
        )
        false_pass_rate = self._ratio(
            false_positive,
            human_fail_cases,
        )
        false_reject_rate = self._ratio(
            false_negative,
            human_pass_cases,
        )

        return JudgeCalibrationReport(
            total_cases=len(human_labels),
            human_pass_cases=human_pass_cases,
            human_fail_cases=human_fail_cases,
            true_positive=true_positive,
            true_negative=true_negative,
            false_positive=false_positive,
            false_negative=false_negative,
            alignment_rate=alignment_rate,
            judge_precision=self._ratio(
                true_positive,
                true_positive + false_positive,
            ),
            judge_recall=self._ratio(
                true_positive,
                true_positive + false_negative,
            ),
            false_pass_rate=false_pass_rate,
            false_reject_rate=false_reject_rate,
            release_gate_passed=bool(human_pass_cases and human_fail_cases)
            and false_pass_rate <= max_false_pass_rate
            and false_reject_rate <= max_false_reject_rate
            and alignment_rate >= minimum_alignment_rate,
        )

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0


def lexical_judge(answer: str, required_terms: list[str]) -> bool:
    """A deliberately simple baseline that requires literal term matches."""

    return all(term in answer for term in required_terms)
