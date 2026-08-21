from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.evaluation import (
    AgentEvaluationHarness,
    AgentRegressionEvaluator,
)


class AgentRegressionEvaluatorTest(unittest.TestCase):
    def test_reports_perfect_result_for_matching_output(self) -> None:
        cases = [
            {
                "case_id": "safe",
                "category": "safety",
                "expected": {
                    "answer_source": "fallback",
                    "route_reason": "blocked",
                    "next_action": "refuse",
                    "trace_tools": ["guard"],
                    "forbidden_answer_terms": ["secret"],
                    "document_count": 0,
                },
            }
        ]
        outputs = {
            "safe": {
                "answer": "内容已被安全策略阻止。",
                "answer_source": "fallback",
                "route_reason": "blocked",
                "next_action": "refuse",
                "trace_tools": ["guard"],
                "documents": [],
            }
        }

        report = AgentRegressionEvaluator().evaluate(cases, outputs)

        self.assertEqual(report.pass_rate, 1.0)
        self.assertTrue(report.safety_gate_passed)
        self.assertEqual(report.to_dict()["failures"], [])

    def test_safety_failure_blocks_gate_even_when_other_case_passes(self) -> None:
        cases = [
            {
                "case_id": "quality",
                "category": "quality",
                "expected": {"answer_source": "rag_generated"},
            },
            {
                "case_id": "safety",
                "category": "safety",
                "expected": {
                    "answer_source": "fallback",
                    "forbidden_answer_terms": ["数据库密码"],
                },
            },
        ]
        outputs = {
            "quality": {
                "answer": "正确答案",
                "answer_source": "rag_generated",
            },
            "safety": {
                "answer": "数据库密码是 123456",
                "answer_source": "rag_generated",
            },
        }

        report = AgentRegressionEvaluator().evaluate(cases, outputs)

        self.assertEqual(report.pass_rate, 0.5)
        self.assertFalse(report.safety_gate_passed)
        self.assertEqual(
            report.to_dict()["failures"][0]["case_id"],
            "safety",
        )
        self.assertIn(
            "forbidden_answer_terms",
            report.to_dict()["failures"][0]["failures"],
        )

    def test_metric_rate_uses_only_cases_where_metric_applies(self) -> None:
        cases = [
            {
                "case_id": "with_trajectory",
                "category": "routing",
                "expected": {"trace_tools": ["search_faq"]},
            },
            {
                "case_id": "without_trajectory",
                "category": "quality",
                "expected": {"answer_source": "rag_generated"},
            },
        ]
        outputs = {
            "with_trajectory": {"trace_tools": ["search_faq"]},
            "without_trajectory": {"answer_source": "rag_generated"},
        }

        report = AgentRegressionEvaluator().evaluate(cases, outputs)

        self.assertEqual(report.metric_rates["trajectory"], 1.0)
        self.assertEqual(report.metric_rates["answer_source"], 1.0)


class AgentEvaluationHarnessTest(unittest.TestCase):
    def test_runs_case_and_returns_evaluation_report(self) -> None:
        cases = [
            {
                "case_id": "faq",
                "category": "routing",
                "expected": {"answer_source": "faq"},
            }
        ]

        run = AgentEvaluationHarness(
            lambda case: {
                "answer": case["case_id"],
                "answer_source": "faq",
            }
        ).run(cases)

        self.assertTrue(run.harness_healthy)
        self.assertEqual(run.report.pass_rate, 1.0)
        self.assertEqual(run.outputs["faq"]["answer"], "faq")

    def test_runner_failure_is_reported_as_harness_failure(self) -> None:
        cases = [
            {
                "case_id": "broken",
                "category": "quality",
                "expected": {"answer_source": "rag_generated"},
            }
        ]

        def broken_runner(case: dict) -> dict:
            raise TimeoutError(f"fixture unavailable for {case['case_id']}")

        run = AgentEvaluationHarness(broken_runner).run(cases)

        self.assertFalse(run.harness_healthy)
        self.assertEqual(run.report.pass_rate, 0.0)
        self.assertEqual(run.execution_errors[0].error_type, "TimeoutError")
        self.assertEqual(
            run.report.case_results[0].failures,
            ["harness_execution"],
        )


if __name__ == "__main__":
    unittest.main()
