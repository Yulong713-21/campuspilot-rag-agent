from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import create_session_factory  # noqa: E402
from campuspilot_core.seed import (  # noqa: E402
    inspect_minimal_seed_fixture,
    seed_minimal_domain_data,
)
from campuspilot_core.smoke import (  # noqa: E402
    run_deterministic_rule_smoke,
)


POSTGRES_TEST_URL = os.getenv("TEST_POSTGRES_DATABASE_URL")


@unittest.skipUnless(
    POSTGRES_TEST_URL,
    "set TEST_POSTGRES_DATABASE_URL to run PostgreSQL integration tests",
)
class PostgreSQLPersistenceIntegrationTest(unittest.TestCase):
    def test_migrate_seed_repeat_and_run_rule_engine(self) -> None:
        assert POSTGRES_TEST_URL is not None
        self.assertTrue(POSTGRES_TEST_URL.startswith("postgresql+psycopg://"))
        config = Config(str(REPO_ROOT / "alembic.ini"))
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": POSTGRES_TEST_URL,
                "VECTOR_SEARCH": "0",
            },
            clear=False,
        ):
            command.upgrade(config, "head")
            factory = create_session_factory()
            with factory() as session:
                state, counts = inspect_minimal_seed_fixture(session)
                if state == "absent":
                    seed_minimal_domain_data(session)
                elif state == "incomplete":
                    self.fail(f"incomplete fixture: {counts}")
                first_state, first_counts = inspect_minimal_seed_fixture(
                    session
                )
                second_state, second_counts = inspect_minimal_seed_fixture(
                    session
                )
                result = run_deterministic_rule_smoke(session)

        self.assertEqual(first_state, "complete")
        self.assertEqual(second_state, "complete")
        self.assertEqual(first_counts, second_counts)
        self.assertTrue(result["prerequisite_evaluated"])
        self.assertEqual(result["offering_periods"], ["Semester 2"])
        self.assertEqual(result["required_credits"], 72)
        self.assertTrue(result["study_plan_valid"])


if __name__ == "__main__":
    unittest.main()
