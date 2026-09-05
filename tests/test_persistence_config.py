from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import resolve_database_url  # noqa: E402


class DatabaseUrlResolutionTest(unittest.TestCase):
    def test_database_url_is_supported(self) -> None:
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql+psycopg://primary/db"},
            clear=True,
        ):
            self.assertEqual(
                resolve_database_url(),
                "postgresql+psycopg://primary/db",
            )

    def test_legacy_campuspilot_database_url_is_supported(self) -> None:
        with patch.dict(
            os.environ,
            {"CAMPUSPILOT_DATABASE_URL": "sqlite:///legacy.sqlite3"},
            clear=True,
        ):
            self.assertEqual(
                resolve_database_url(),
                "sqlite:///legacy.sqlite3",
            )

    def test_database_url_wins_over_legacy_alias(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://primary/db",
                "CAMPUSPILOT_DATABASE_URL": "sqlite:///legacy.sqlite3",
            },
            clear=True,
        ):
            self.assertEqual(
                resolve_database_url(),
                "postgresql+psycopg://primary/db",
            )


if __name__ == "__main__":
    unittest.main()
