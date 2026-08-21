from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy import func, select


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import create_session_factory
from campuspilot_core.models import Course, StudentProfile, University
from campuspilot_core.seed import seed_minimal_domain_data


DEFAULT_DATABASE_URL = "sqlite:///logs/campuspilot_domain.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="写入 CampusPilot 合成领域测试数据。",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv(
            "CAMPUSPILOT_DATABASE_URL",
            DEFAULT_DATABASE_URL,
        ),
        help="SQLAlchemy 数据库 URL；默认写入本地 SQLite。",
    )
    args = parser.parse_args()
    factory = create_session_factory(args.database_url)

    with factory() as session:
        university_count = session.scalar(
            select(func.count()).select_from(University)
        )
        if university_count:
            print("数据库已有大学数据，本次未重复写入。")
            return
        ids = seed_minimal_domain_data(session)
        course_count = session.scalar(
            select(func.count()).select_from(Course)
        )
        student_count = session.scalar(
            select(func.count()).select_from(StudentProfile)
        )

    print("CampusPilot 合成测试数据写入完成。")
    print(f"university_id={ids['university_id']}")
    print(f"course_count={course_count}")
    print(f"student_count={student_count}")
    print("data_mode=synthetic_test（不可当作官方培养方案）")


if __name__ == "__main__":
    main()
