from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.judge_calibration import (
    JudgeCalibrationEvaluator,
    lexical_judge,
)


def main() -> None:
    dataset_path = REPO_ROOT / "eval" / "judge_calibration_cases.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    human_labels = [case["human_pass"] for case in cases]
    judges = {
        "关键词规则": [
            lexical_judge(case["answer"], case["required_terms"])
            for case in cases
        ],
        "语义 Judge V1": [case["judge_v1_pass"] for case in cases],
        "加入人工纠错后的 Judge V2": [
            case["judge_v2_pass"]
            for case in cases
        ],
    }
    evaluator = JudgeCalibrationEvaluator()
    reports = {
        name: evaluator.evaluate(human_labels, labels).to_dict()
        for name, labels in judges.items()
    }
    disagreements = {
        name: [
            case["case_id"]
            for case, judge_pass in zip(cases, labels)
            if case["human_pass"] != judge_pass
        ]
        for name, labels in judges.items()
    }
    result = {
        "实验说明": "V1/V2 是固定重放结果，用于学习校准，不是真实在线模型调用。",
        "样例数": len(cases),
        "人工合格": sum(human_labels),
        "人工不合格": len(cases) - sum(human_labels),
        "阅卷器成绩": reports,
        "与人工不一致的样例": disagreements,
        "发布策略": {
            "错误放行率上限": 0.0,
            "错误拦截率上限": 0.1,
            "最低人工对齐率": 0.9,
            "说明": "这是 EduRAG 实验门禁，不是通用行业标准。",
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
