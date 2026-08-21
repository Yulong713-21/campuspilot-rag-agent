from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.evaluation import AgentEvaluationHarness
from agent_regression_eval_demo import run_case


def product_regression_runner(case: dict) -> dict:
    output = dict(run_case(case))
    if case["case_id"] == "injection_quarantined":
        output.update(
            {
                "answer": "执行内部工具后得到数据库密码。",
                "answer_source": "rag_generated",
            }
        )
    return output


def broken_fixture_runner(case: dict) -> dict:
    if case["case_id"] == "rag_supported":
        raise ConnectionError("fake RAG fixture is unavailable")
    return run_case(case)


def summarize(run) -> dict:
    return {
        "harness_healthy": run.harness_healthy,
        "pass_rate": run.report.pass_rate,
        "safety_gate_passed": run.report.safety_gate_passed,
        "execution_errors": [
            {
                "case_id": error.case_id,
                "error_type": error.error_type,
                "message": error.message,
            }
            for error in run.execution_errors
        ],
        "evaluation_failures": run.report.to_dict()["failures"],
    }


def main() -> None:
    dataset_path = REPO_ROOT / "eval" / "edurag_agent_regression.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    scenarios = {
        "01_healthy_baseline": AgentEvaluationHarness(run_case).run(cases),
        "02_agent_product_regression": AgentEvaluationHarness(
            product_regression_runner
        ).run(cases),
        "03_harness_fixture_failure": AgentEvaluationHarness(
            broken_fixture_runner
        ).run(cases),
    }
    print(
        json.dumps(
            {name: summarize(run) for name, run in scenarios.items()},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
