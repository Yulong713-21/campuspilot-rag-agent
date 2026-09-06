"""Seed the synthetic deterministic-domain fixture for local verification."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import func, select


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import (  # noqa: E402
    create_session_factory,
    resolve_database_url,
)
from campuspilot_core.models import Course, StudentProfile  # noqa: E402
from campuspilot_core.seed import (  # noqa: E402
    inspect_minimal_seed_fixture,
    seed_minimal_domain_data,
)


DEFAULT_DATABASE_URL = "sqlite:///logs/campuspilot_domain.sqlite3"


def main() -> None:
    """Seed once, accept a complete fixture, and reject partial fixture state."""
    parser = argparse.ArgumentParser(
        description="写入 CampusPilot 合成领域测试数据。",
    )
    parser.add_argument(
        "--database-url",
        default=resolve_database_url(default=DEFAULT_DATABASE_URL),
        help=(
            "SQLAlchemy 数据库 URL；优先读取 DATABASE_URL，兼容旧的 "
            "CAMPUSPILOT_DATABASE_URL，本地缺省使用 SQLite。"
        ),
    )
    args = parser.parse_args()
    factory = create_session_factory(args.database_url)

    with factory() as session:
        fixture_state, fixture_counts = inspect_minimal_seed_fixture(session)
        if fixture_state == "complete":
            print("目标合成 fixture 已完整存在，本次未重复写入。")
            return
        if fixture_state == "incomplete":
            raise RuntimeError(
                "检测到不完整的 CPTU 合成 fixture；为避免混合规则，"
                f"未自动修复。当前计数：{fixture_counts}"
            )
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
