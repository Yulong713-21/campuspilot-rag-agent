from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agent_runtime.campuspilot import (
    CampusPilotCatalog,
    CampusPilotPlanningAgent,
)


def main() -> None:
    catalog = CampusPilotCatalog()
    agent = CampusPilotPlanningAgent(catalog)

    comparison = catalog.compare_programs(
        "MONASH-C6001-EL1",
        "MONASH-C6001-EL2",
        2026,
        "Industry Experience",
    )
    course_role = catalog.classify_course_role(
        program_variant_id="MONASH-C6001-EL2",
        handbook_year=2026,
        study_stream="Industry Experience",
        course_code="FIT5120",
    )
    result = agent.plan(
        {
            "program_variant_id": "MONASH-C6001-EL2",
            "handbook_year": 2026,
            "study_stream": "Industry Experience",
            "completed_courses": ["FIT5057", "FIT5125"],
            "max_courses_per_semester": 4,
            "preserve_policy_flexibility": True,
            "start_semester": "2026-S2",
        }
    )

    output = {
        "数据模式": result["data_mode"],
        "培养方案版本": catalog.data["catalog_version"],
        "项目比较": comparison["programs"],
        "FIT5120课程角色": course_role["rule_type"],
        "已完成学分": result["completed_credits"],
        "剩余学分": result["remaining_credits"],
        "三套方案": [
            {
                "方案": plan["name"],
                "预计学期数": plan["estimated_semesters"],
                "有效": plan["validation"]["valid"],
                "学期": [
                    {
                        "semester": semester["semester"],
                        "courses": [
                            course["course_code"]
                            for course in semester["courses"]
                        ],
                    }
                    for semester in plan["semesters"]
                ],
            }
            for plan in result["plans"]
        ],
        "调用轨迹": result["trace_tools"],
        "RAG命中证据": [
            {
                "document_id": document["document_id"],
                "title": document["title"],
                "score": document["score"],
            }
            for document in result["evidence"]
        ],
        "来源": result["source_ids"],
        "风险提示": result["disclaimer"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
