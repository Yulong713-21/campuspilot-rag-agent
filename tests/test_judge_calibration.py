from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.judge_calibration import (
    JudgeCalibrationEvaluator,
    lexical_judge,
)


class JudgeCalibrationEvaluatorTest(unittest.TestCase):
    def test_calculates_confusion_matrix_and_rates(self) -> None:
        report = JudgeCalibrationEvaluator().evaluate(
            human_labels=[True, True, False, False],
            judge_labels=[True, False, True, False],
        )

        self.assertEqual(report.true_positive, 1)
        self.assertEqual(report.true_negative, 1)
        self.assertEqual(report.false_positive, 1)
        self.assertEqual(report.false_negative, 1)
        self.assertEqual(report.alignment_rate, 0.5)
        self.assertEqual(report.false_pass_rate, 0.5)
        self.assertEqual(report.false_reject_rate, 0.5)
        self.assertFalse(report.release_gate_passed)

    def test_perfect_balanced_result_satisfies_release_gate(self) -> None:
        report = JudgeCalibrationEvaluator().evaluate(
            human_labels=[True, True, False, False],
            judge_labels=[True, True, False, False],
        )

        self.assertTrue(report.release_gate_passed)

    def test_rejecting_everything_does_not_game_release_gate(self) -> None:
        report = JudgeCalibrationEvaluator().evaluate(
            human_labels=[True, False],
            judge_labels=[False, False],
        )

        self.assertFalse(report.release_gate_passed)
        self.assertEqual(report.false_reject_rate, 1.0)

    def test_release_gate_requires_balanced_labels(self) -> None:
        report = JudgeCalibrationEvaluator().evaluate(
            human_labels=[True, True],
            judge_labels=[True, True],
        )

        self.assertFalse(report.release_gate_passed)

    def test_rejects_label_length_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            JudgeCalibrationEvaluator().evaluate(
                human_labels=[True],
                judge_labels=[],
            )

    def test_lexical_judge_cannot_understand_paraphrase(self) -> None:
        answer = "先学入门知识，再做真实项目，最后训练求职能力。"

        passed = lexical_judge(
            answer,
            ["基础学习", "项目实战", "就业准备"],
        )

        self.assertFalse(passed)

    def test_lexical_judge_can_be_fooled_by_keyword_stuffing(self) -> None:
        answer = "基础学习、项目实战、就业准备都不存在。"

        passed = lexical_judge(
            answer,
            ["基础学习", "项目实战", "就业准备"],
        )

        self.assertTrue(passed)

    def test_calibration_dataset_is_balanced(self) -> None:
        cases = self._load_cases()
        labels = [case["human_pass"] for case in cases]

        self.assertEqual(len(cases), 20)
        self.assertEqual(sum(labels), 10)
        self.assertEqual(len(labels) - sum(labels), 10)

    def test_dataset_reproduces_expected_judge_baselines(self) -> None:
        cases = self._load_cases()
        human_labels = [case["human_pass"] for case in cases]
        evaluator = JudgeCalibrationEvaluator()
        lexical_report = evaluator.evaluate(
            human_labels,
            [
                lexical_judge(case["answer"], case["required_terms"])
                for case in cases
            ],
        )
        v2_report = evaluator.evaluate(
            human_labels,
            [case["judge_v2_pass"] for case in cases],
        )

        self.assertEqual(lexical_report.alignment_rate, 0.5)
        self.assertEqual(v2_report.alignment_rate, 0.95)
        self.assertEqual(v2_report.false_positive, 1)
        self.assertFalse(v2_report.release_gate_passed)

    @staticmethod
    def _load_cases() -> list[dict]:
        dataset_path = REPO_ROOT / "eval" / "judge_calibration_cases.json"
        return json.loads(dataset_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
