from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import Base  # noqa: E402
from campuspilot_core.enums import (  # noqa: E402
    RequirementGroupType,
    RequirementScope,
)
from campuspilot_core.models import RequirementGroup  # noqa: E402
from campuspilot_core.seed import (  # noqa: E402
    inspect_minimal_seed_fixture,
    seed_minimal_domain_data,
)
from campuspilot_core.services import DegreeAuditService  # noqa: E402
from campuspilot_core.smoke import run_deterministic_rule_smoke  # noqa: E402


class DeterministicPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.ids = seed_minimal_domain_data(self.session)
        self.service = DegreeAuditService(self.session)
        self.university_id = self.ids["university_id"]

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_program_and_course_versions_are_year_scoped(self) -> None:
        program_2025 = self.service.get_program_version(
            university_id=self.university_id,
            program_code="MIT",
            handbook_year=2025,
        )
        program_2026 = self.service.get_program_version(
            university_id=self.university_id,
            program_code="MIT",
            handbook_year=2026,
        )
        course_2025 = self.service.get_course_version(
            university_id=self.university_id,
            course_code="CPT100",
            handbook_year=2025,
        )
        course_2026 = self.service.get_course_version(
            university_id=self.university_id,
            course_code="CPT100",
            handbook_year=2026,
        )

        self.assertNotEqual(program_2025.id, program_2026.id)
        self.assertNotEqual(course_2025.id, course_2026.id)

    def test_offerings_follow_the_exact_course_version(self) -> None:
        course_2025 = self.service.get_course_version(
            university_id=self.university_id,
            course_code="CPT100",
            handbook_year=2025,
        )
        course_2026 = self.service.get_course_version(
            university_id=self.university_id,
            course_code="CPT100",
            handbook_year=2026,
        )

        self.assertTrue(
            self.service.is_course_offered(
                course_version_id=course_2025.id,
                teaching_period="Semester 1",
            )
        )
        self.assertFalse(
            self.service.is_course_offered(
                course_version_id=course_2025.id,
                teaching_period="Semester 2",
            )
        )
        response = self.service.get_course_offerings(
            course_version_id=course_2026.id
        )
        self.assertEqual(response.handbook_year, 2026)
        self.assertEqual(
            [item.teaching_period for item in response.offerings],
            ["Semester 2"],
        )

    def test_program_and_specialisation_rules_do_not_leak(self) -> None:
        mit_2026 = self.ids["program_version_ids"]["MIT-2026"]
        ai = self.ids["specialisation_ids"]["MIT-2026-AI"]
        cyber = self.ids["specialisation_ids"]["MIT-2026-CYB"]
        ai_groups = self.service.get_program_requirements(mit_2026, ai)
        cyber_groups = self.service.get_program_requirements(mit_2026, cyber)

        self.assertIn("MIT_PROGRAM_CORE", {g.code for g in ai_groups.groups})
        self.assertIn("AI_CORE", {g.code for g in ai_groups.groups})
        self.assertNotIn("CYB_CORE", {g.code for g in ai_groups.groups})
        self.assertIn("CYB_CORE", {g.code for g in cyber_groups.groups})
        self.assertNotIn("AI_CORE", {g.code for g in cyber_groups.groups})

    def test_prerequisites_are_specialisation_scoped(self) -> None:
        mit_2026 = self.ids["program_version_ids"]["MIT-2026"]
        ai = self.ids["specialisation_ids"]["MIT-2026-AI"]
        cyber = self.ids["specialisation_ids"]["MIT-2026-CYB"]
        ai300 = self.ids["course_ids"]["AI300"]

        self.assertEqual(
            len(self.service.get_prerequisites(mit_2026, ai, ai300)),
            2,
        )
        self.assertEqual(
            self.service.get_prerequisites(mit_2026, cyber, ai300),
            [],
        )

    def test_prerequisites_are_handbook_year_scoped(self) -> None:
        ai300 = self.ids["course_ids"]["AI300"]
        groups_2025 = self.service.get_prerequisites(
            self.ids["program_version_ids"]["MIT-2025"],
            self.ids["specialisation_ids"]["MIT-2025-AI"],
            ai300,
        )
        groups_2026 = self.service.get_prerequisites(
            self.ids["program_version_ids"]["MIT-2026"],
            self.ids["specialisation_ids"]["MIT-2026-AI"],
            ai300,
        )

        self.assertTrue(groups_2025)
        self.assertTrue(groups_2026)
        self.assertEqual(
            {item.program_version_id for item in groups_2025},
            {self.ids["program_version_ids"]["MIT-2025"]},
        )
        self.assertEqual(
            {item.program_version_id for item in groups_2026},
            {self.ids["program_version_ids"]["MIT-2026"]},
        )

    def test_duplicate_program_wide_rule_is_rejected(self) -> None:
        self.session.add(
            RequirementGroup(
                program_version_id=(
                    self.ids["program_version_ids"]["MIT-2026"]
                ),
                specialisation_id=None,
                code="MIT_PROGRAM_CORE",
                name="Duplicate",
                scope=RequirementScope.PROGRAM,
                group_type=RequirementGroupType.CORE,
                min_credits=0,
                max_credits=0,
                evidence={},
            )
        )
        with self.assertRaises(IntegrityError):
            self.session.flush()

    def test_rule_engine_has_no_rag_runtime_dependency(self) -> None:
        with patch.dict(os.environ, {"VECTOR_SEARCH": "0"}, clear=False):
            result = self.service.get_program_requirements(
                self.ids["program_version_ids"]["MIT-2026"],
                self.ids["specialisation_ids"]["MIT-2026-AI"],
            )

        self.assertTrue(result.result.passed)

    def test_deterministic_smoke_path_needs_no_rag_services(self) -> None:
        with patch.dict(os.environ, {"VECTOR_SEARCH": "0"}, clear=False):
            result = run_deterministic_rule_smoke(self.session)

        self.assertTrue(result["prerequisite_evaluated"])
        self.assertEqual(result["offering_periods"], ["Semester 2"])
        self.assertEqual(result["required_credits"], 72)
        self.assertTrue(result["study_plan_valid"])

    def test_fixture_status_detects_complete_and_incomplete_data(self) -> None:
        state, _ = inspect_minimal_seed_fixture(self.session)
        self.assertEqual(state, "complete")
        self.session.query(RequirementGroup).delete()
        self.session.flush()
        state, counts = inspect_minimal_seed_fixture(self.session)
        self.assertEqual(state, "incomplete")
        self.assertEqual(counts["requirement_groups"], 0)


if __name__ == "__main__":
    unittest.main()
