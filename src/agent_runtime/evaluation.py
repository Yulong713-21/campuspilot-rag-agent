from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class EvaluationCaseResult:
    case_id: str
    category: str
    passed: bool
    checks: dict[str, bool]
    failures: list[str]


@dataclass(frozen=True)
class AgentEvaluationReport:
    total_cases: int
    passed_cases: int
    pass_rate: float
    metric_rates: dict[str, float]
    category_rates: dict[str, float]
    safety_gate_passed: bool
    case_results: list[EvaluationCaseResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "pass_rate": self.pass_rate,
            "metric_rates": self.metric_rates,
            "category_rates": self.category_rates,
            "safety_gate_passed": self.safety_gate_passed,
            "failures": [
                {
                    "case_id": result.case_id,
                    "category": result.category,
                    "failures": result.failures,
                }
                for result in self.case_results
                if not result.passed
            ],
        }


@dataclass(frozen=True)
class HarnessExecutionError:
    case_id: str
    error_type: str
    message: str


@dataclass(frozen=True)
class AgentHarnessRun:
    report: AgentEvaluationReport
    outputs: dict[str, dict[str, Any]]
    execution_errors: list[HarnessExecutionError]

    @property
    def harness_healthy(self) -> bool:
        return not self.execution_errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness_healthy": self.harness_healthy,
            "execution_errors": [
                {
                    "case_id": error.case_id,
                    "error_type": error.error_type,
                    "message": error.message,
                }
                for error in self.execution_errors
            ],
            "evaluation": self.report.to_dict(),
        }


class AgentEvaluationHarness:
    """Runs Agent cases and keeps infrastructure failures separate from regressions."""

    def __init__(
        self,
        run_case: Callable[[dict[str, Any]], dict[str, Any]],
        evaluator: AgentRegressionEvaluator | None = None,
    ) -> None:
        self.run_case = run_case
        self.evaluator = evaluator or AgentRegressionEvaluator()

    def run(self, cases: list[dict[str, Any]]) -> AgentHarnessRun:
        outputs: dict[str, dict[str, Any]] = {}
        errors: list[HarnessExecutionError] = []

        for case in cases:
            case_id = case["case_id"]
            try:
                outputs[case_id] = self.run_case(case)
            except Exception as exc:  # The harness must report, not hide, runner failures.
                error = HarnessExecutionError(
                    case_id=case_id,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
                errors.append(error)
                outputs[case_id] = {
                    "__harness_error__": {
                        "type": error.error_type,
                        "message": error.message,
                    }
                }

        return AgentHarnessRun(
            report=self.evaluator.evaluate(cases, outputs),
            outputs=outputs,
            execution_errors=errors,
        )


class AgentRegressionEvaluator:
    """Deterministic response, trajectory, safety, and budget evaluator."""

    def evaluate(
        self,
        cases: list[dict[str, Any]],
        outputs: dict[str, dict[str, Any]],
    ) -> AgentEvaluationReport:
        results = [
            self._evaluate_case(case, outputs[case["case_id"]])
            for case in cases
        ]
        metric_rates = self._metric_rates(results)
        category_rates = self._category_rates(results)
        safety_results = [
            result for result in results if result.category == "safety"
        ]
        passed_cases = sum(result.passed for result in results)
        return AgentEvaluationReport(
            total_cases=len(results),
            passed_cases=passed_cases,
            pass_rate=self._rate(passed_cases, len(results)),
            metric_rates=metric_rates,
            category_rates=category_rates,
            safety_gate_passed=bool(safety_results)
            and all(result.passed for result in safety_results),
            case_results=results,
        )

    def _evaluate_case(
        self,
        case: dict[str, Any],
        output: dict[str, Any],
    ) -> EvaluationCaseResult:
        expected = case["expected"]
        answer = str(output.get("answer") or "")
        checks: dict[str, bool] = {
            "harness_execution": "__harness_error__" not in output,
        }

        if not checks["harness_execution"]:
            return EvaluationCaseResult(
                case_id=case["case_id"],
                category=case["category"],
                passed=False,
                checks=checks,
                failures=["harness_execution"],
            )

        self._check_equal(
            checks,
            "answer_source",
            output.get("answer_source"),
            expected.get("answer_source"),
        )
        self._check_equal(
            checks,
            "route_reason",
            output.get("route_reason"),
            expected.get("route_reason"),
        )
        self._check_equal(
            checks,
            "next_action",
            output.get("next_action"),
            expected.get("next_action"),
        )

        if "trace_tools" in expected:
            checks["trajectory"] = (
                output.get("trace_tools", []) == expected["trace_tools"]
            )
        if "required_answer_terms" in expected:
            checks["required_answer_terms"] = all(
                term in answer for term in expected["required_answer_terms"]
            )
        if "forbidden_answer_terms" in expected:
            checks["forbidden_answer_terms"] = all(
                term not in answer for term in expected["forbidden_answer_terms"]
            )
        if "document_count" in expected:
            checks["document_count"] = (
                len(output.get("documents", [])) == expected["document_count"]
            )
        if "selected_memory_count" in expected:
            checks["selected_memory_count"] = (
                len(output.get("selected_memories", []))
                == expected["selected_memory_count"]
            )
        if "minimum_quarantined_count" in expected:
            checks["quarantine"] = (
                output.get("context_policy", {}).get(
                    "quarantined_count",
                    0,
                )
                >= expected["minimum_quarantined_count"]
            )
        if "maximum_elapsed_seconds" in expected:
            checks["deadline"] = (
                output.get("time_budget", {}).get(
                    "elapsed_seconds",
                    float("inf"),
                )
                <= expected["maximum_elapsed_seconds"]
            )

        failures = [name for name, passed in checks.items() if not passed]
        return EvaluationCaseResult(
            case_id=case["case_id"],
            category=case["category"],
            passed=not failures,
            checks=checks,
            failures=failures,
        )

    @staticmethod
    def _check_equal(
        checks: dict[str, bool],
        name: str,
        actual: Any,
        expected: Any,
    ) -> None:
        if expected is not None:
            checks[name] = actual == expected

    def _metric_rates(
        self,
        results: list[EvaluationCaseResult],
    ) -> dict[str, float]:
        names = sorted(
            {
                name
                for result in results
                for name in result.checks
            }
        )
        return {
            name: self._rate(
                sum(
                    result.checks[name]
                    for result in results
                    if name in result.checks
                ),
                sum(name in result.checks for result in results),
            )
            for name in names
        }

    def _category_rates(
        self,
        results: list[EvaluationCaseResult],
    ) -> dict[str, float]:
        categories = sorted({result.category for result in results})
        return {
            category: self._rate(
                sum(
                    result.passed
                    for result in results
                    if result.category == category
                ),
                sum(
                    result.category == category
                    for result in results
                ),
            )
            for category in categories
        }

    @staticmethod
    def _rate(passed: int, total: int) -> float:
        return round(passed / total, 4) if total else 0.0
