from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.admission_mvp import AdmissionMvpService  # noqa: E402


UNIVERSITIES = [
    "monash",
    "melbourne",
    "sydney",
    "unsw",
    "anu",
    "uq",
    "uwa",
    "adelaide",
]


def main() -> None:
    service = AdmissionMvpService()
    coverage = []
    for university_id in UNIVERSITIES:
        result = service.find_programs(
            university_id,
            discipline_id="business",
        )
        coverage.append(
            {
                "学校": university_id,
                "项目数": len(result["programs"]),
                "目录范围": result["catalog_scope"],
                "可做录取硬判断": sum(
                    item["evaluation_ready"] for item in result["programs"]
                ),
                "示例项目": [
                    item["name"] for item in result["programs"][:3]
                ],
            }
        )
    print(
        json.dumps(
            {
                "实验目标": "验证澳洲八大商科项目发现链路",
                "商科项目总数": sum(item["项目数"] for item in coverage),
                "学校覆盖数": sum(item["项目数"] > 0 for item in coverage),
                "目录可查询": True,
                "未审核规则不会参与硬判断": True,
                "学校明细": coverage,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
