from __future__ import annotations

import unittest
from pathlib import Path
import sys

from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.db import Base
from campuspilot_core.enums import (
    CourseRecordStatus,
    CourseRole,
    ErrorCode,
)
from campuspilot_core.models import (
    Course,
    Program,
    ProgramVersion,
    Specialisation,
    StudentCourseRecord,
    StudentProfile,
    StudyPlan,
    StudyPlanCourse,
    StudyPlanTerm,
    University,
)
from campuspilot_core.schemas import StudentCourseRecordInput
from campuspilot_core.seed import seed_minimal_domain_data
from campuspilot_core.services import DegreeAuditService, DomainLookupError


class CampusPilotDomainCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.ids = seed_minimal_domain_data(self.session)
        self.service = DegreeAuditService(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_seed_contains_requested_minimum_domain_data(self) -> None:
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(University)),
            1,
        )
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(Program)),
            2,
        )
        self.assertEqual(
            self.session.scalar(
                select(func.count()).select_from(ProgramVersion)
            ),
            4,
        )
        self.assertEqual(
            self.session.scalar(
                select(func.count()).select_from(Specialisation)
            ),
            8,
        )
        self.assertGreaterEqual(
            self.session.scalar(select(func.count()).select_from(Course)),
            20,
        )
        self.assertEqual(
            self.session.scalar(
                select(func.count()).select_from(StudentProfile)
            ),
            3,
        )

    def test_get_program_requirements_returns_both_scopes_with_evidence(
        self,
    ) -> None:
        response = self.service.get_program_requirements(
            self.ids["program_version_ids"]["MIT-2026"],
            self.ids["specialisation_ids"]["MIT-2026-AI"],
        )

        self.assertTrue(response.result.passed)
        self.assertEqual(response.total_credits, 72)
        self.assertEqual(len(response.groups), 5)
        self.assertEqual(
            {group.scope for group in response.groups},
            {"PROGRAM", "SPECIALISATION"},
        )
        self.assertTrue(
            all(group.evidence for group in response.groups)
        )
        self.assertTrue(
            all(
                course.evidence
                for group in response.groups
                for course in group.courses
            )
        )

    def test_same_course_has_different_roles_in_different_programs(
        self,
    ) -> None:
        ai300 = self.ids["course_ids"]["AI300"]

        mit_role = self.service.classify_course_role(
            self.ids["program_version_ids"]["MIT-2026"],
            self.ids["specialisation_ids"]["MIT-2026-AI"],
            ai300,
        )
        mds_role = self.service.classify_course_role(
            self.ids["program_version_ids"]["MDS-2026"],
            self.ids["specialisation_ids"]["MDS-2026-BA"],
            ai300,
        )

        self.assertEqual(mit_role.roles, [CourseRole.SPECIALISATION_CORE])
        self.assertEqual(mds_role.roles, [CourseRole.PRESCRIBED_ELECTIVE])
        self.assertTrue(mit_role.result.evidence)
        self.assertTrue(mds_role.result.evidence)

    def test_course_outside_scope_is_not_eligible(self) -> None:
        response = self.service.classify_course_role(
            self.ids["program_version_ids"]["MDS-2026"],
            self.ids["specialisation_ids"]["MDS-2026-BA"],
            self.ids["course_ids"]["CY320"],
        )

        self.assertFalse(response.result.passed)
        self.assertEqual(
            response.result.error_code,
            ErrorCode.COURSE_NOT_IN_PROGRAM,
        )
        self.assertEqual(response.roles, [CourseRole.NOT_ELIGIBLE])
        self.assertTrue(response.result.evidence)

    def test_prerequisite_groups_use_and_between_groups_and_or_within_group(
        self,
    ) -> None:
        version_id = self.ids["program_version_ids"]["MIT-2026"]
        spec_id = self.ids["specialisation_ids"]["MIT-2026-AI"]
        ai300 = self.ids["course_ids"]["AI300"]
        cpt100 = self.ids["course_ids"]["CPT100"]
        cpt120 = self.ids["course_ids"]["CPT120"]

        failed = self.service.check_prerequisites(
            version_id,
            spec_id,
            ai300,
            [cpt100],
        )
        passed = self.service.check_prerequisites(
            version_id,
            spec_id,
            ai300,
            [cpt100, cpt120],
        )

        self.assertFalse(failed.eligible)
        self.assertEqual(
            failed.result.error_code,
            ErrorCode.PREREQUISITE_NOT_MET,
        )
        self.assertEqual([item.passed for item in failed.group_results],
                         [True, False])
        self.assertTrue(passed.eligible)
        self.assertEqual(passed.result.error_code, ErrorCode.OK)
        self.assertEqual([item.passed for item in passed.group_results],
                         [True, True])

    def test_degree_progress_distinguishes_earned_and_projected_credits(
        self,
    ) -> None:
        student_id = self.ids["student_ids"]["alice"]

        earned = self.service.calculate_degree_progress(student_id)
        projected = self.service.calculate_degree_progress(
            student_id,
            include_projected=True,
        )

        self.assertEqual(earned.earned_credits, 60)
        self.assertEqual(earned.projected_credits, 66)
        self.assertEqual(earned.completion_ratio, round(60 / 72, 4))
        self.assertEqual(projected.completion_ratio, round(66 / 72, 4))
        self.assertTrue(earned.violations)
        self.assertTrue(
            all(item.evidence for item in earned.violations)
        )

    def test_transfer_and_zero_credit_exemption_have_distinct_effects(
        self,
    ) -> None:
        progress = self.service.calculate_degree_progress(
            self.ids["student_ids"]["carol"]
        )

        self.assertEqual(progress.earned_credits, 18)
        self.assertEqual(progress.projected_credits, 30)

    def test_adjusted_credit_records_require_an_explicit_awarded_value(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            StudentCourseRecordInput(
                course_id=self.ids["course_ids"]["DS120"],
                status=CourseRecordStatus.EXEMPTED,
            )

        record = StudentCourseRecordInput(
            course_id=self.ids["course_ids"]["DS120"],
            status=CourseRecordStatus.EXEMPTED,
            credit_points_awarded=0,
        )
        self.assertEqual(record.credit_points_awarded, 0)

    def test_valid_study_plan_reaches_degree_requirements(self) -> None:
        response = self.service.validate_study_plan(
            self.ids["study_plan_ids"]["alice_valid"]
        )

        self.assertTrue(response.valid)
        self.assertEqual(response.result.error_code, ErrorCode.OK)
        self.assertEqual(response.projected_progress.projected_credits, 72)
        self.assertTrue(all(item.passed for item in response.term_results))
        self.assertEqual(response.requirement_results, [])

    def test_invalid_study_plan_reports_prerequisite_evidence(self) -> None:
        response = self.service.validate_study_plan(
            self.ids["study_plan_ids"]["bob_invalid"]
        )

        failures = [
            item
            for item in response.term_results
            if item.error_code == ErrorCode.PREREQUISITE_NOT_MET
        ]
        self.assertFalse(response.valid)
        self.assertTrue(failures)
        self.assertTrue(all(item.evidence for item in failures))
        self.assertNotIn(
            "2027-S1 的课程顺序与学分负荷已检查。",
            [item.message for item in response.term_results],
        )

    def test_in_progress_course_does_not_satisfy_a_prerequisite(self) -> None:
        record = self.session.scalar(
            select(StudentCourseRecord).where(
                StudentCourseRecord.student_id
                == self.ids["student_ids"]["bob"],
                StudentCourseRecord.course_id
                == self.ids["course_ids"]["CY310"],
            )
        )
        record.status = CourseRecordStatus.IN_PROGRESS
        self.session.commit()

        response = self.service.validate_study_plan(
            self.ids["study_plan_ids"]["bob_invalid"]
        )
        first_term_failures = [
            item
            for item in response.term_results
            if item.error_code == ErrorCode.PREREQUISITE_NOT_MET
        ]

        self.assertFalse(response.valid)
        self.assertTrue(first_term_failures)

    def test_plan_rejects_course_outside_program_scope(self) -> None:
        plan = StudyPlan(
            student_id=self.ids["student_ids"]["alice"],
            name="Out-of-scope course plan",
        )
        self.session.add(plan)
        self.session.flush()
        term = StudyPlanTerm(
            study_plan_id=plan.id,
            term_code="2028-S1",
            sequence_number=1,
        )
        self.session.add(term)
        self.session.flush()
        self.session.add(
            StudyPlanCourse(
                study_plan_term_id=term.id,
                course_id=self.ids["course_ids"]["CY320"],
            )
        )
        self.session.commit()

        response = self.service.validate_study_plan(plan.id)
        codes = {item.error_code for item in response.term_results}

        self.assertFalse(response.valid)
        self.assertIn(ErrorCode.COURSE_NOT_IN_PROGRAM, codes)

    def test_plan_rejects_same_course_in_multiple_terms(self) -> None:
        plan = StudyPlan(
            student_id=self.ids["student_ids"]["alice"],
            name="Duplicate course plan",
        )
        self.session.add(plan)
        self.session.flush()
        terms = [
            StudyPlanTerm(
                study_plan_id=plan.id,
                term_code=f"2028-S{sequence}",
                sequence_number=sequence,
            )
            for sequence in (1, 2)
        ]
        self.session.add_all(terms)
        self.session.flush()
        self.session.add_all(
            [
                StudyPlanCourse(
                    study_plan_term_id=term.id,
                    course_id=self.ids["course_ids"]["EL510"],
                )
                for term in terms
            ]
        )
        self.session.commit()

        response = self.service.validate_study_plan(plan.id)
        codes = {item.error_code for item in response.term_results}

        self.assertFalse(response.valid)
        self.assertIn(ErrorCode.PLAN_COURSE_ALREADY_COMPLETED, codes)

    def test_exclusion_and_duplicate_counting_are_both_detected(self) -> None:
        self.session.add(
            StudentCourseRecord(
                student_id=self.ids["student_ids"]["alice"],
                course_id=self.ids["course_ids"]["AI330"],
                status=CourseRecordStatus.COMPLETED,
                attempt_number=1,
                source_note="test overlap and exclusion",
            )
        )
        self.session.commit()

        progress = self.service.calculate_degree_progress(
            self.ids["student_ids"]["alice"]
        )
        codes = {item.error_code for item in progress.violations}

        self.assertIn(ErrorCode.DUPLICATE_CREDIT_COUNTING, codes)
        self.assertIn(ErrorCode.MUTUALLY_EXCLUSIVE_COURSES, codes)

    def test_lookup_errors_keep_the_unified_rule_result_contract(
        self,
    ) -> None:
        with self.assertRaises(DomainLookupError) as context:
            self.service.get_program_requirements(
                999_999,
                999_999,
            )

        result = context.exception.result
        self.assertFalse(result.passed)
        self.assertEqual(
            result.error_code,
            ErrorCode.PROGRAM_VERSION_NOT_FOUND,
        )
        self.assertTrue(result.message)
        self.assertTrue(result.evidence)


if __name__ == "__main__":
    unittest.main()
