from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.rag_quality import RAGQualityEvaluator


def main() -> None:
    evaluator = RAGQualityEvaluator()
    dataset_path = REPO_ROOT / "eval" / "rag_quality_cases.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    result = {}
    for case in cases:
        name = case.pop("name")
        report = evaluator.evaluate(**case)
        result[name] = {
            **report.to_dict(),
            "大白话": {
                "retrieval_miss": "该找检索层：正确资料根本没拿回来。",
                "generation_unsupported": "该找生成层：资料没说这件事，模型自己加了。",
                "generation_incomplete": "该找生成层：资料齐全，但答案漏答。",
                "evaluator_false_negative": "该查评估器：答案其实合格，阅卷规则误判。",
            }[report.diagnosis],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
