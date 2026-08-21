from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from .enums import (
    CourseRecordStatus,
    CourseRole,
    RequirementGroupType,
    RequirementScope,
    StudyPlanStatus,
)
from .models import (
    Course,
    CourseExclusion,
    CourseVersion,
    PrerequisiteGroup,
    PrerequisiteOption,
    Program,
    ProgramVersion,
    RequirementGroup,
    RequirementGroupCourse,
    Specialisation,
    StudentCourseRecord,
    StudentProfile,
    StudyPlan,
    StudyPlanCourse,
    StudyPlanTerm,
    University,
)


COURSE_TITLES = {
    "CPT100": "Programming Foundations",
    "CPT110": "Database Systems",
    "CPT120": "Data Structures and Algorithms",
    "CPT130": "Computer Networks",
    "CPT200": "Software Engineering",
    "CPT210": "Research Methods",
    "CPT220": "Technology Ethics",
    "CPT230": "Cloud Computing",
    "AI300": "Machine Learning",
    "AI310": "Deep Learning",
    "AI320": "Natural Language Processing",
    "AI330": "Computer Vision",
    "CY300": "Security Foundations",
    "CY310": "Network Security",
    "CY320": "Secure Coding",
    "CY330": "Digital Forensics",
    "DS100": "Statistics for Data Science",
    "DS110": "Linear Algebra for Data Science",
    "DS120": "Data Wrangling",
    "DS200": "Data Visualisation",
    "BA300": "Business Analytics",
    "BA310": "Decision Models",
    "ST300": "Bayesian Statistics",
    "ST310": "Statistical Learning",
    "CAP400": "Industry Capstone",
    "CAP410": "Research Capstone",
    "EL500": "Technology Innovation",
    "EL510": "Digital Entrepreneurship",
}


def seed_minimal_domain_data(session: Session) -> dict[str, Any]:
    """Create synthetic fixtures only; never present these as official data."""

    evidence = {
        "source_id": "SYNTHETIC-DOMAIN-FIXTURE",
        "data_mode": "synthetic_test",
    }
    university = University(
        code="CPTU",
        name="CampusPilot Test University",
        country_code="AU",
        official_url=None,
    )
    session.add(university)
    session.flush()

    courses = {
        code: Course(
            university_id=university.id,
            code=code,
            canonical_name=title,
        )
        for code, title in COURSE_TITLES.items()
    }
    session.add_all(courses.values())
    session.flush()

    course_versions: dict[tuple[str, int], CourseVersion] = {}
    for year in (2025, 2026):
        for code, course in courses.items():
            version = CourseVersion(
                course_id=course.id,
                handbook_year=year,
                title=COURSE_TITLES[code],
                credit_points=6,
                evidence={**evidence, "handbook_year": year},
            )
            session.add(version)
            course_versions[(code, year)] = version
    session.flush()

    programs = {
        "MIT": Program(
            university_id=university.id,
            code="MIT",
            name="Master of Information Technology",
            award_type="Master by Coursework",
        ),
        "MDS": Program(
            university_id=university.id,
            code="MDS",
            name="Master of Data Science",
            award_type="Master by Coursework",
        ),
    }
    session.add_all(programs.values())
    session.flush()

    program_versions: dict[tuple[str, int], ProgramVersion] = {}
    specialisations: dict[tuple[str, int, str], Specialisation] = {}
    for program_code, program in programs.items():
        for year in (2025, 2026):
            version = ProgramVersion(
                program_id=program.id,
                handbook_year=year,
                total_credits=72,
                max_shared_credits=0,
                evidence={
                    **evidence,
                    "program_code": program_code,
                    "handbook_year": year,
                },
            )
            session.add(version)
            session.flush()
            program_versions[(program_code, year)] = version
            specs = (
                (("AI", "Artificial Intelligence"), ("CYB", "Cyber Security"))
                if program_code == "MIT"
                else (
                    ("BA", "Business Analytics"),
                    ("STAT", "Statistical Computing"),
                )
            )
            for code, name in specs:
                specialisation = Specialisation(
                    program_version_id=version.id,
                    code=code,
                    name=name,
                    required_credits=24,
                    evidence={**evidence, "specialisation_code": code},
                )
                session.add(specialisation)
                session.flush()
                specialisations[(program_code, year, code)] = (
                    specialisation
                )

    group_index: dict[tuple[str, int, str], RequirementGroup] = {}

    def add_group(
        *,
        program_code: str,
        year: int,
        code: str,
        name: str,
        scope: RequirementScope,
        group_type: RequirementGroupType,
        min_credits: int,
        max_credits: int | None,
        course_roles: Iterable[tuple[str, CourseRole]],
        specialisation_code: str | None = None,
        allow_shared_credit: bool = False,
    ) -> RequirementGroup:
        version = program_versions[(program_code, year)]
        specialisation = (
            specialisations[(program_code, year, specialisation_code)]
            if specialisation_code
            else None
        )
        group = RequirementGroup(
            program_version_id=version.id,
            specialisation_id=(
                specialisation.id if specialisation else None
            ),
            code=code,
            name=name,
            scope=scope,
            group_type=group_type,
            min_credits=min_credits,
            max_credits=max_credits,
            allow_shared_credit=allow_shared_credit,
            evidence={**evidence, "requirement_group": code},
        )
        session.add(group)
        session.flush()
        for course_code, role in course_roles:
            session.add(
                RequirementGroupCourse(
                    requirement_group_id=group.id,
                    course_version_id=course_versions[
                        (course_code, year)
                    ].id,
                    role=role,
                    evidence={
                        **evidence,
                        "course_code": course_code,
                        "role": role.value,
                    },
                )
            )
        group_index[(program_code, year, code)] = group
        return group

    for year in (2025, 2026):
        mit_core = (
            ["CPT100", "CPT110", "CPT120", "CPT200", "CPT210"]
            if year == 2025
            else ["CPT100", "CPT110", "CPT120", "CPT130", "CPT210"]
        )
        add_group(
            program_code="MIT",
            year=year,
            code="MIT_PROGRAM_CORE",
            name="MIT Program Core",
            scope=RequirementScope.PROGRAM,
            group_type=RequirementGroupType.CORE,
            min_credits=30,
            max_credits=30,
            course_roles=[
                (code, CourseRole.PROGRAM_CORE) for code in mit_core
            ],
        )
        add_group(
            program_code="MIT",
            year=year,
            code="MIT_GENERAL_ELECTIVES",
            name="MIT General Electives",
            scope=RequirementScope.PROGRAM,
            group_type=RequirementGroupType.ELECTIVE,
            min_credits=12,
            max_credits=18,
            course_roles=[
                ("EL500", CourseRole.GENERAL_ELECTIVE),
                ("EL510", CourseRole.GENERAL_ELECTIVE),
                ("AI330", CourseRole.GENERAL_ELECTIVE),
                ("CY330", CourseRole.GENERAL_ELECTIVE),
            ],
        )
        for spec_code, prefix in (("AI", "AI"), ("CYB", "CY")):
            core_codes = [
                f"{prefix}300",
                f"{prefix}310",
                f"{prefix}320",
            ]
            add_group(
                program_code="MIT",
                year=year,
                code=f"{spec_code}_CORE",
                name=f"{spec_code} Specialisation Core",
                scope=RequirementScope.SPECIALISATION,
                group_type=RequirementGroupType.CORE,
                min_credits=18,
                max_credits=18,
                specialisation_code=spec_code,
                course_roles=[
                    (code, CourseRole.SPECIALISATION_CORE)
                    for code in core_codes
                ],
            )
            add_group(
                program_code="MIT",
                year=year,
                code=f"{spec_code}_PRESCRIBED",
                name=f"{spec_code} Prescribed Electives",
                scope=RequirementScope.SPECIALISATION,
                group_type=RequirementGroupType.ELECTIVE,
                min_credits=6,
                max_credits=12,
                specialisation_code=spec_code,
                course_roles=[
                    (f"{prefix}330", CourseRole.PRESCRIBED_ELECTIVE),
                    ("CPT230", CourseRole.PRESCRIBED_ELECTIVE),
                ],
            )
            add_group(
                program_code="MIT",
                year=year,
                code=f"{spec_code}_CAPSTONE",
                name=f"{spec_code} Capstone",
                scope=RequirementScope.SPECIALISATION,
                group_type=RequirementGroupType.CAPSTONE,
                min_credits=6,
                max_credits=6,
                specialisation_code=spec_code,
                course_roles=[("CAP400", CourseRole.CAPSTONE)],
            )

        mds_core = ["CPT100", "DS100", "DS110", "DS120", "CPT210"]
        add_group(
            program_code="MDS",
            year=year,
            code="MDS_PROGRAM_CORE",
            name="MDS Program Core",
            scope=RequirementScope.PROGRAM,
            group_type=RequirementGroupType.CORE,
            min_credits=30,
            max_credits=30,
            course_roles=[
                (code, CourseRole.PROGRAM_CORE) for code in mds_core
            ],
        )
        add_group(
            program_code="MDS",
            year=year,
            code="MDS_GENERAL_ELECTIVES",
            name="MDS General Electives",
            scope=RequirementScope.PROGRAM,
            group_type=RequirementGroupType.ELECTIVE,
            min_credits=12,
            max_credits=18,
            course_roles=[
                ("EL500", CourseRole.GENERAL_ELECTIVE),
                ("EL510", CourseRole.GENERAL_ELECTIVE),
                ("CPT220", CourseRole.GENERAL_ELECTIVE),
            ],
        )
        for spec_code, core_codes, prescribed, capstone in (
            (
                "BA",
                ["BA300", "BA310", "DS200"],
                ["AI300", "CPT230"],
                "CAP400",
            ),
            (
                "STAT",
                ["ST300", "ST310", "DS200"],
                ["AI310", "CPT230"],
                "CAP410",
            ),
        ):
            add_group(
                program_code="MDS",
                year=year,
                code=f"{spec_code}_CORE",
                name=f"{spec_code} Specialisation Core",
                scope=RequirementScope.SPECIALISATION,
                group_type=RequirementGroupType.CORE,
                min_credits=18,
                max_credits=18,
                specialisation_code=spec_code,
                course_roles=[
                    (code, CourseRole.SPECIALISATION_CORE)
                    for code in core_codes
                ],
            )
            add_group(
                program_code="MDS",
                year=year,
                code=f"{spec_code}_PRESCRIBED",
                name=f"{spec_code} Prescribed Electives",
                scope=RequirementScope.SPECIALISATION,
                group_type=RequirementGroupType.ELECTIVE,
                min_credits=6,
                max_credits=12,
                specialisation_code=spec_code,
                course_roles=[
                    (code, CourseRole.PRESCRIBED_ELECTIVE)
                    for code in prescribed
                ],
            )
            add_group(
                program_code="MDS",
                year=year,
                code=f"{spec_code}_CAPSTONE",
                name=f"{spec_code} Capstone",
                scope=RequirementScope.SPECIALISATION,
                group_type=RequirementGroupType.CAPSTONE,
                min_credits=6,
                max_credits=6,
                specialisation_code=spec_code,
                course_roles=[(capstone, CourseRole.CAPSTONE)],
            )

    def add_prerequisite(
        *,
        program_code: str,
        year: int,
        course_code: str,
        group_index_value: int,
        options: list[str],
        minimum_satisfied: int = 1,
        specialisation_code: str | None = None,
    ) -> None:
        version = program_versions[(program_code, year)]
        specialisation = (
            specialisations[(program_code, year, specialisation_code)]
            if specialisation_code
            else None
        )
        group = PrerequisiteGroup(
            program_version_id=version.id,
            specialisation_id=(
                specialisation.id if specialisation else None
            ),
            course_id=courses[course_code].id,
            group_index=group_index_value,
            minimum_satisfied=minimum_satisfied,
            evidence={
                **evidence,
                "target_course": course_code,
                "options": options,
            },
        )
        session.add(group)
        session.flush()
        session.add_all(
            [
                PrerequisiteOption(
                    prerequisite_group_id=group.id,
                    prerequisite_course_id=courses[option].id,
                )
                for option in options
            ]
        )

    for year in (2025, 2026):
        for program_code in ("MIT", "MDS"):
            add_prerequisite(
                program_code=program_code,
                year=year,
                course_code="CPT120",
                group_index_value=1,
                options=["CPT100"],
            )
        add_prerequisite(
            program_code="MIT",
            year=year,
            course_code="AI300",
            group_index_value=1,
            options=["CPT100"],
            specialisation_code="AI",
        )
        add_prerequisite(
            program_code="MIT",
            year=year,
            course_code="AI300",
            group_index_value=2,
            options=["DS110", "CPT120"],
            specialisation_code="AI",
        )
        add_prerequisite(
            program_code="MIT",
            year=year,
            course_code="AI310",
            group_index_value=1,
            options=["AI300"],
            specialisation_code="AI",
        )
        add_prerequisite(
            program_code="MIT",
            year=year,
            course_code="AI320",
            group_index_value=1,
            options=["CPT120", "AI300"],
            specialisation_code="AI",
        )
        add_prerequisite(
            program_code="MIT",
            year=year,
            course_code="CY310",
            group_index_value=1,
            options=["CY300"],
            specialisation_code="CYB",
        )
        add_prerequisite(
            program_code="MIT",
            year=year,
            course_code="CY320",
            group_index_value=1,
            options=["CY310"],
            specialisation_code="CYB",
        )
        for spec_code, advanced in (("AI", "AI310"), ("CYB", "CY310")):
            add_prerequisite(
                program_code="MIT",
                year=year,
                course_code="CAP400",
                group_index_value=1,
                options=["CPT210"],
                specialisation_code=spec_code,
            )
            add_prerequisite(
                program_code="MIT",
                year=year,
                course_code="CAP400",
                group_index_value=2,
                options=[advanced],
                specialisation_code=spec_code,
            )

    for year in (2025, 2026):
        version = program_versions[("MIT", year)]
        ai_spec = specialisations[("MIT", year, "AI")]
        session.add(
            CourseExclusion(
                program_version_id=version.id,
                specialisation_id=ai_spec.id,
                course_id=courses["AI330"].id,
                excluded_course_id=courses["CPT230"].id,
                evidence={
                    **evidence,
                    "reason": "synthetic equivalent-content exclusion",
                },
            )
        )

    alice = StudentProfile(
        external_ref="student-alice",
        display_name="Alice",
        program_version_id=program_versions[("MIT", 2026)].id,
        specialisation_id=specialisations[("MIT", 2026, "AI")].id,
    )
    bob = StudentProfile(
        external_ref="student-bob",
        display_name="Bob",
        program_version_id=program_versions[("MIT", 2026)].id,
        specialisation_id=specialisations[("MIT", 2026, "CYB")].id,
    )
    carol = StudentProfile(
        external_ref="student-carol",
        display_name="Carol",
        program_version_id=program_versions[("MDS", 2025)].id,
        specialisation_id=specialisations[("MDS", 2025, "BA")].id,
    )
    session.add_all([alice, bob, carol])
    session.flush()

    def add_records(
        student: StudentProfile,
        records: Iterable[
            tuple[str, CourseRecordStatus, int | None, int]
        ],
    ) -> None:
        session.add_all(
            [
                StudentCourseRecord(
                    student_id=student.id,
                    course_id=courses[code].id,
                    status=status,
                    credit_points_awarded=awarded,
                    attempt_number=attempt,
                    source_note="synthetic fixture",
                )
                for code, status, awarded, attempt in records
            ]
        )

    add_records(
        alice,
        [
            *[
                (code, CourseRecordStatus.COMPLETED, None, 1)
                for code in (
                    "CPT100",
                    "CPT110",
                    "CPT120",
                    "CPT130",
                    "CPT210",
                    "AI300",
                    "AI310",
                    "AI320",
                    "CPT230",
                    "EL500",
                )
            ],
            ("EL510", CourseRecordStatus.IN_PROGRESS, None, 1),
        ],
    )
    add_records(
        bob,
        [
            *[
                (code, CourseRecordStatus.COMPLETED, None, 1)
                for code in (
                    "CPT100",
                    "CPT110",
                    "CPT120",
                    "CPT130",
                    "CPT210",
                    "CY300",
                    "EL500",
                )
            ],
            ("CY310", CourseRecordStatus.FAILED, None, 1),
        ],
    )
    add_records(
        carol,
        [
            ("CPT100", CourseRecordStatus.COMPLETED, None, 1),
            ("DS100", CourseRecordStatus.COMPLETED, None, 1),
            ("DS110", CourseRecordStatus.TRANSFERRED, 6, 1),
            ("DS120", CourseRecordStatus.EXEMPTED, 0, 1),
            ("CPT210", CourseRecordStatus.IN_PROGRESS, None, 1),
            ("BA300", CourseRecordStatus.PLANNED, None, 1),
        ],
    )

    alice_plan = StudyPlan(
        student_id=alice.id,
        name="Alice valid completion plan",
        status=StudyPlanStatus.DRAFT,
        objective={"strategy": "balanced", "data_mode": "synthetic_test"},
    )
    bob_plan = StudyPlan(
        student_id=bob.id,
        name="Bob invalid prerequisite plan",
        status=StudyPlanStatus.DRAFT,
        objective={"strategy": "fastest", "data_mode": "synthetic_test"},
    )
    session.add_all([alice_plan, bob_plan])
    session.flush()

    alice_term = StudyPlanTerm(
        study_plan_id=alice_plan.id,
        term_code="2027-S1",
        sequence_number=1,
        max_credits=24,
    )
    bob_term_1 = StudyPlanTerm(
        study_plan_id=bob_plan.id,
        term_code="2027-S1",
        sequence_number=1,
        max_credits=24,
    )
    bob_term_2 = StudyPlanTerm(
        study_plan_id=bob_plan.id,
        term_code="2027-S2",
        sequence_number=2,
        max_credits=24,
    )
    session.add_all([alice_term, bob_term_1, bob_term_2])
    session.flush()
    session.add_all(
        [
            StudyPlanCourse(
                study_plan_term_id=alice_term.id,
                course_id=courses["CAP400"].id,
                preferred_role=CourseRole.CAPSTONE,
            ),
            StudyPlanCourse(
                study_plan_term_id=bob_term_1.id,
                course_id=courses["CY320"].id,
                preferred_role=CourseRole.SPECIALISATION_CORE,
            ),
            StudyPlanCourse(
                study_plan_term_id=bob_term_2.id,
                course_id=courses["CY310"].id,
                preferred_role=CourseRole.SPECIALISATION_CORE,
            ),
        ]
    )
    session.commit()

    return {
        "university_id": university.id,
        "program_ids": {
            code: program.id for code, program in programs.items()
        },
        "program_version_ids": {
            f"{code}-{year}": version.id
            for (code, year), version in program_versions.items()
        },
        "specialisation_ids": {
            f"{code}-{year}-{spec}": item.id
            for (code, year, spec), item in specialisations.items()
        },
        "course_ids": {
            code: course.id for code, course in courses.items()
        },
        "student_ids": {
            "alice": alice.id,
            "bob": bob.id,
            "carol": carol.id,
        },
        "study_plan_ids": {
            "alice_valid": alice_plan.id,
            "bob_invalid": bob_plan.id,
        },
    }
