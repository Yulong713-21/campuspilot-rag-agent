from __future__ import annotations

import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import Base
from campuspilot_core.seed import seed_minimal_domain_data
from campuspilot_core.services import DegreeAuditService


def main() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        ids = seed_minimal_domain_data(session)
        service = DegreeAuditService(session)
        ai300 = ids["course_ids"]["AI300"]
        cpt100 = ids["course_ids"]["CPT100"]
        cpt120 = ids["course_ids"]["CPT120"]

        result = {
            "实验数据": {
                "data_mode": "synthetic_test",
                "大学数": 1,
                "项目数": 2,
                "项目版本数": 4,
                "方向数": 8,
                "课程数": len(ids["course_ids"]),
                "学生档案数": 3,
            },
            "同一课程的角色随培养方案变化": {
                "MIT_2026_AI": service.classify_course_role(
                    ids["program_version_ids"]["MIT-2026"],
                    ids["specialisation_ids"]["MIT-2026-AI"],
                    ai300,
                ).model_dump(mode="json"),
                "MDS_2026_BA": service.classify_course_role(
                    ids["program_version_ids"]["MDS-2026"],
                    ids["specialisation_ids"]["MDS-2026-BA"],
                    ai300,
                ).model_dump(mode="json"),
            },
            "AI300先修校验": {
                "仅完成CPT100": service.check_prerequisites(
                    ids["program_version_ids"]["MIT-2026"],
                    ids["specialisation_ids"]["MIT-2026-AI"],
                    ai300,
                    [cpt100],
                ).model_dump(mode="json"),
                "完成CPT100和CPT120": service.check_prerequisites(
                    ids["program_version_ids"]["MIT-2026"],
                    ids["specialisation_ids"]["MIT-2026-AI"],
                    ai300,
                    [cpt100, cpt120],
                ).model_dump(mode="json"),
            },
            "Alice学分进度": {
                "只计算已获得学分": service.calculate_degree_progress(
                    ids["student_ids"]["alice"],
                ).model_dump(mode="json"),
                "包含在修与计划": service.calculate_degree_progress(
                    ids["student_ids"]["alice"],
                    include_projected=True,
                ).model_dump(mode="json"),
            },
            "学习方案校验": {
                "Alice有效方案": service.validate_study_plan(
                    ids["study_plan_ids"]["alice_valid"],
                ).model_dump(mode="json"),
                "Bob错误顺序方案": service.validate_study_plan(
                    ids["study_plan_ids"]["bob_invalid"],
                ).model_dump(mode="json"),
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
