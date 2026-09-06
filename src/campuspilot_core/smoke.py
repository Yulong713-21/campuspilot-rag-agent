"""Small end-to-end checks for the structured rule service boundary."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import StudentProfile, University
from .services import DegreeAuditService


def run_deterministic_rule_smoke(session: Session) -> dict[str, Any]:
    """Exercise version, prerequisite, offering, credit, and plan lookups."""

    university = session.scalar(
        select(University).where(University.code == "CPTU")
    )
    student = session.scalar(
        select(StudentProfile).where(
            StudentProfile.external_ref == "student-alice"
        )
    )
    if university is None or student is None or not student.study_plans:
        raise RuntimeError("CPTU deterministic smoke fixture is unavailable")

    service = DegreeAuditService(session)
    program_version = service.get_program_version(
        university_id=university.id,
        program_code="MIT",
        handbook_year=2026,
    )
    course_version = service.get_course_version(
        university_id=university.id,
        course_code="CPT100",
        handbook_year=2026,
    )
    ai300 = service.get_course_version(
        university_id=university.id,
        course_code="AI300",
        handbook_year=2026,
    )
    prerequisite = service.check_prerequisites(
        program_version.id,
        student.specialisation_id,
        ai300.course_id,
        [course_version.course_id],
    )
    offerings = service.get_course_offerings(
        course_version_id=course_version.id
    )
    requirements = service.get_program_requirements(
        program_version.id,
        student.specialisation_id,
    )
    plan = service.validate_study_plan(student.study_plans[0].id)

    return {
        "program_version_id": program_version.id,
        "course_version_id": course_version.id,
        "prerequisite_evaluated": bool(prerequisite.group_results),
        "offering_periods": [
            item.teaching_period for item in offerings.offerings
        ],
        "required_credits": requirements.total_credits,
        "study_plan_valid": plan.valid,
    }
