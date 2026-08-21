from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.judge_calibration import JudgeCalibrationEvaluator
from agent_runtime.live_judge import OllamaSemanticJudge
from agent_runtime.ollama_client import OllamaChatClient


QUESTION = "人工智能就业课课程大纲有哪些阶段和模块？"
REFERENCE_ANSWER = "课程包含基础学习、项目实战和就业准备三个阶段。"
REPEAT_CASE_IDS = {
    "good_paraphrase_05",
    "bad_keyword_01",
    "bad_unsupported_01",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实 Ollama Judge 校准实验")
    parser.add_argument("--limit", type=int, default=None, help="只运行前 N 条样例")
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="高风险样例的总运行次数，包含首次运行",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="可选：将完整 JSON 实验结果保存到指定文件",
    )
    return parser.parse_args()


def load_cases(limit: int | None) -> list[dict[str, Any]]:
    path = REPO_ROOT / "eval" / "judge_calibration_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    return cases if limit is None else cases[:limit]


def run_case(
    judge: OllamaSemanticJudge,
    case: dict[str, Any],
) -> dict[str, Any]:
    try:
        verdict = judge.evaluate(
            question=QUESTION,
            reference_answer=REFERENCE_ANSWER,
            candidate_answer=case["answer"],
        )
        return {
            "case_id": case["case_id"],
            "human_pass": case["human_pass"],
            "judge_pass": verdict.passed,
            "aligned": verdict.passed == case["human_pass"],
            "confidence": verdict.confidence,
            "reason": verdict.reason,
            "error": None,
        }
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "human_pass": case["human_pass"],
            "judge_pass": False,
            "aligned": False,
            "confidence": 0.0,
            "reason": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    args = parse_args()
    if args.repeats < 1:
        raise ValueError("--repeats must be at least 1")

    model = os.getenv("EDURAG_JUDGE_MODEL", "qwen3.5:0.8b")
    client = OllamaChatClient(
        model=model,
        temperature=0.0,
        num_predict=180,
        num_ctx=2048,
        timeout_seconds=90,
    )
    judge = OllamaSemanticJudge(client)
    cases = load_cases(args.limit)
    first_results = [run_case(judge, case) for case in cases]

    valid_results = [result for result in first_results if result["error"] is None]
    report = JudgeCalibrationEvaluator().evaluate(
        [result["human_pass"] for result in valid_results],
        [result["judge_pass"] for result in valid_results],
    )

    repeated_results = []
    cases_by_id = {case["case_id"]: case for case in cases}
    for case_id in sorted(REPEAT_CASE_IDS & cases_by_id.keys()):
        first = next(result for result in first_results if result["case_id"] == case_id)
        runs = [first]
        runs.extend(
            run_case(judge, cases_by_id[case_id])
            for _ in range(args.repeats - 1)
        )
        labels = [
            run["judge_pass"]
            for run in runs
            if run["error"] is None
        ]
        majority_count = max(Counter(labels).values()) if labels else 0
        repeated_results.append(
            {
                "case_id": case_id,
                "human_pass": cases_by_id[case_id]["human_pass"],
                "judge_votes": [run["judge_pass"] for run in runs],
                "confidence_values": [run["confidence"] for run in runs],
                "reasons": [run["reason"] for run in runs],
                "call_errors": sum(
                    run["error"] is not None for run in runs
                ),
                "unanimous": len(set(labels)) == 1 if labels else False,
                "stability_rate": round(majority_count / len(labels), 4)
                if labels
                else 0.0,
            }
        )

    output = {
        "实验类型": "真实本地 Ollama Judge，非固定回放",
        "模型": model,
        "temperature": 0.0,
        "一次校准": {
            "请求样例数": len(cases),
            "成功判决数": len(valid_results),
            "调用错误数": len(first_results) - len(valid_results),
            "指标": report.to_dict(),
            "逐条结果": first_results,
        },
        "重复稳定性": {
            "每条总运行次数": args.repeats,
            "高风险样例": repeated_results,
        },
    }
    output_text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_text + "\n", encoding="utf-8")
        print(f"实验结果已保存：{args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
