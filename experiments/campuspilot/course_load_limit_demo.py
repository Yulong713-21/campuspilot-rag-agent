from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot import CampusPilotConversationAgent  # noqa: E402


BASE_REQUEST = {
    "program_variant_id": "MONASH-C6001-EL1",
    "handbook_year": 2026,
    "study_stream": "Industry Experience",
    "completed_courses": ["FIT5057", "FIT5058"],
    "max_courses_per_semester": 4,
    "start_semester": "2026-S2",
}


def run(query: str) -> dict:
    result = CampusPilotConversationAgent().respond(
        {**BASE_REQUEST, "message": query}
    )
    plan = result["study_plans"]["plans"][0]
    return {
        "用户诉求": query,
        "生效的每学期上限": result["study_plans"]["profile"][
            "max_courses_per_semester"
        ],
        "首选方案": plan["name"],
        "预计学期数": plan["estimated_semesters"],
        "学期安排": [
            {
                "学期": semester["semester"],
                "课程数": len(semester["courses"]),
                "课程": [
                    {
                        "代码": course["course_code"],
                        "负载": course["workload_level"],
                    }
                    for course in semester["courses"]
                ],
            }
            for semester in plan["semesters"]
        ],
    }


def main() -> None:
    print(
        json.dumps(
            [
                run("怎么选课实现负载均衡"),
                run("帮我负载均衡，每学期选两门课"),
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
