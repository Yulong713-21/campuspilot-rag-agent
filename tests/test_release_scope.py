from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from agent_runtime.api import create_app


class CampusPilotReleaseScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "release-scope.sqlite3"
        self.client = TestClient(create_app(database_path=database))
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def _programs(self, discipline_id: str) -> list[dict]:
        response = self.client.get(
            "/api/admissions/programs",
            params={
                "university": "Monash",
                "discipline_id": discipline_id,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["programs"]

    def test_release_exposes_monash_business_and_computing_catalogs(self) -> None:
        business = self._programs("business")
        computing = self._programs("computing")

        self.assertEqual(len(business), 21)
        self.assertEqual(len(computing), 6)
        self.assertIn("B6022", {item["program_code"] for item in business})
        self.assertIn("C6001", {item["program_code"] for item in computing})

    def test_only_verified_program_can_make_hard_admission_decision(self) -> None:
        programs = self._programs("business") + self._programs("computing")
        evaluation_ready = {
            item["program_code"]
            for item in programs
            if item["evaluation_ready"]
        }

        self.assertEqual(evaluation_ready, {"C6001"})


if __name__ == "__main__":
    unittest.main()
