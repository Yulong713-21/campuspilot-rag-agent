from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .enums import (
    CourseRecordStatus,
    CourseRole,
    ErrorCode,
    RequirementGroupType,
    RequirementScope,
)
from .models import (
    Course,
    CourseExclusion,
    CourseVersion,
    PrerequisiteGroup,
    PrerequisiteOption,
    ProgramVersion,
    RequirementGroup,
    RequirementGroupCourse,
    Specialisation,
    StudentCourseRecord,
    StudentProfile,
    StudyPlan,
    StudyPlanTerm,
)
from .schemas import (
    CourseRequirementView,
    CourseRoleResponse,
    DegreeProgressResponse,
    EvidenceItem,
    GroupProgress,
    PrerequisiteCheckResponse,
    ProgramRequirementsResponse,
    RequirementGroupView,
    RuleResult,
    StudyPlanValidationResponse,
)


EARNED_STATUSES = {
    CourseRecordStatus.COMPLETED,
    CourseRecordStatus.EXEMPTED,
    CourseRecordStatus.TRANSFERRED,
}
PROJECTED_STATUSES = EARNED_STATUSES | {
    CourseRecordStatus.IN_PROGRESS,
    CourseRecordStatus.PLANNED,
}


class DomainLookupError(ValueError):
    def __init__(self, result: RuleResult) -> None:
        super().__init__(result.message)
        self.result = result


class DegreeAuditService:
    """Deterministic degree-audit services with evidence-bearing results."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_program_requirements(
        self,
        program_version_id: int,
        specialisation_id: int,
    ) -> ProgramRequirementsResponse:
        version, specialisation = self._load_scope(
            program_version_id,
            specialisation_id,
        )
        groups = self._load_requirement_groups(
            program_version_id,
            specialisation_id,
        )
        group_views = [
            RequirementGroupView(
                group_id=group.id,
                code=group.code,
                name=group.name,
                scope=group.scope.value,
                group_type=group.group_type.value,
                min_credits=group.min_credits,
                max_credits=group.max_credits,
                allow_shared_credit=group.allow_shared_credit,
                courses=[
                    CourseRequirementView(
                        course_id=link.course_version.course.id,
                        course_code=link.course_version.course.code,
                        title=link.course_version.title,
                        credit_points=link.course_version.credit_points,
                        role=link.role,
                        evidence=self._evidence(
                            "requirement_group_course",
                            link.id,
                            link.evidence,
                        ),
                    )
                    for link in sorted(
                        group.course_links,
                        key=lambda item: item.course_version.course.code,
                    )
                ],
                evidence=self._evidence(
                    "requirement_group",
                    group.id,
                    group.evidence,
                ),
            )
            for group in groups
        ]
        return ProgramRequirementsResponse(
            result=self._ok(
                "已加载项目版本、方向和全部要求组。",
                self._evidence(
                    "program_version",
                    version.id,
                    version.evidence,
                ),
            ),
            program_version_id=version.id,
            program_code=version.program.code,
            program_name=version.program.name,
            handbook_year=version.handbook_year,
            total_credits=version.total_credits,
            max_shared_credits=version.max_shared_credits,
            specialisation_id=specialisation.id,
            specialisation_code=specialisation.code,
            specialisation_name=specialisation.name,
            groups=group_views,
        )

    def classify_course_role(
        self,
        program_version_id: int,
        specialisation_id: int,
        course_id: int,
    ) -> CourseRoleResponse:
        self._load_scope(program_version_id, specialisation_id)
        course = self.session.get(Course, course_id)
        if course is None:
            raise self._lookup_error(
                ErrorCode.COURSE_NOT_FOUND,
                f"课程 ID {course_id} 不存在。",
                "course",
                course_id,
            )
        groups = self._load_requirement_groups(
            program_version_id,
            specialisation_id,
        )
        matching = [
            (group, link)
            for group in groups
            for link in group.course_links
            if link.course_version.course_id == course_id
        ]
        if not matching:
            return CourseRoleResponse(
                result=self._failed(
                    ErrorCode.COURSE_NOT_IN_PROGRAM,
                    f"{course.code} 不计入当前项目版本与方向。",
                    [
                        EvidenceItem(
                            source_type="classification_scope",
                            details={
                                "program_version_id": program_version_id,
                                "specialisation_id": specialisation_id,
                                "course_id": course_id,
                            },
                        )
                    ],
                ),
                program_version_id=program_version_id,
                specialisation_id=specialisation_id,
                course_id=course.id,
                course_code=course.code,
                roles=[CourseRole.NOT_ELIGIBLE],
                groups=[],
            )
        roles = list(
            dict.fromkeys(
                link.role
                for _, link in sorted(
                    matching,
                    key=lambda item: self._role_priority(item[1].role),
                )
            )
        )
        evidence = [
            item
            for _, link in matching
            for item in self._evidence(
                "requirement_group_course",
                link.id,
                link.evidence,
            )
        ]
        return CourseRoleResponse(
            result=self._ok(
                f"已识别 {course.code} 在当前范围内的课程角色。",
                evidence,
            ),
            program_version_id=program_version_id,
            specialisation_id=specialisation_id,
            course_id=course.id,
            course_code=course.code,
            roles=roles,
            groups=[group.code for group, _ in matching],
        )

    def check_prerequisites(
        self,
        program_version_id: int,
        specialisation_id: int,
        course_id: int,
        completed_course_ids: Iterable[int],
    ) -> PrerequisiteCheckResponse:
        self._load_scope(program_version_id, specialisation_id)
        course = self.session.get(Course, course_id)
        if course is None:
            raise self._lookup_error(
                ErrorCode.COURSE_NOT_FOUND,
                f"课程 ID {course_id} 不存在。",
                "course",
                course_id,
            )
        completed = set(completed_course_ids)
        groups = list(
            self.session.scalars(
                select(PrerequisiteGroup)
                .where(
                    PrerequisiteGroup.program_version_id
                    == program_version_id,
                    PrerequisiteGroup.course_id == course_id,
                    or_(
                        PrerequisiteGroup.specialisation_id.is_(None),
                        PrerequisiteGroup.specialisation_id
                        == specialisation_id,
                    ),
                )
                .options(
                    selectinload(
                        PrerequisiteGroup.options
                    ).selectinload(PrerequisiteOption.prerequisite_course)
                )
                .order_by(PrerequisiteGroup.group_index)
            )
        )
        group_results = []
        for group in groups:
            matched = [
                option.prerequisite_course
                for option in group.options
                if option.prerequisite_course_id in completed
            ]
            required_codes = [
                option.prerequisite_course.code for option in group.options
            ]
            passed = len(matched) >= group.minimum_satisfied
            evidence = self._evidence(
                "prerequisite_group",
                group.id,
                {
                    **group.evidence,
                    "minimum_satisfied": group.minimum_satisfied,
                    "options": required_codes,
                    "matched": [item.code for item in matched],
                },
            )
            group_results.append(
                self._ok(
                    f"先修组 {group.group_index} 已满足。",
                    evidence,
                )
                if passed
                else self._failed(
                    ErrorCode.PREREQUISITE_NOT_MET,
                    (
                        f"{course.code} 的先修组 {group.group_index} "
                        f"至少需要完成 {group.minimum_satisfied} 门："
                        + "、".join(required_codes)
                    ),
                    evidence,
                )
            )
        eligible = all(result.passed for result in group_results)
        if eligible:
            result = self._ok(
                f"{course.code} 的全部先修条件已满足。",
                [
                    item
                    for group_result in group_results
                    for item in group_result.evidence
                ],
            )
        else:
            result = next(
                item for item in group_results if not item.passed
            )
        return PrerequisiteCheckResponse(
            result=result,
            course_id=course.id,
            course_code=course.code,
            eligible=eligible,
            group_results=group_results,
        )

    def calculate_degree_progress(
        self,
        student_id: int,
        *,
        include_projected: bool = False,
        additional_course_ids: Iterable[int] = (),
    ) -> DegreeProgressResponse:
        student = self._load_student(student_id)
        version, _ = self._load_scope(
            student.program_version_id,
            student.specialisation_id,
        )
        earned, projected = self._record_credit_maps(student)
        selected = dict(projected if include_projected else earned)
        course_versions = self._course_versions_for_year(
            version.handbook_year
        )
        for course_id in additional_course_ids:
            course_version = course_versions.get(course_id)
            if course_version is not None:
                selected.setdefault(
                    course_id,
                    course_version.credit_points,
                )
        group_progress, violations, counted_total = self._audit_requirements(
            version,
            student.specialisation_id,
            selected,
        )
        if counted_total < version.total_credits:
            violations.insert(
                0,
                self._failed(
                    ErrorCode.TOTAL_CREDITS_NOT_MET,
                    (
                        f"当前计入 {counted_total} 学分，"
                        f"项目要求 {version.total_credits} 学分。"
                    ),
                    self._evidence(
                        "program_version",
                        version.id,
                        {
                            **version.evidence,
                            "counted_credits": counted_total,
                            "required_credits": version.total_credits,
                        },
                    ),
                ),
            )
        violations.extend(
            self._check_exclusions(
                version.id,
                student.specialisation_id,
                set(selected),
            )
        )
        result = (
            self._ok(
                "当前课程记录满足全部毕业要求。",
                self._evidence(
                    "program_version",
                    version.id,
                    version.evidence,
                ),
            )
            if not violations
            else violations[0]
        )
        earned_total = self._eligible_total(
            student.program_version_id,
            student.specialisation_id,
            earned,
        )
        projected_total = self._eligible_total(
            student.program_version_id,
            student.specialisation_id,
            projected,
        )
        return DegreeProgressResponse(
            result=result,
            student_id=student.id,
            earned_credits=earned_total,
            projected_credits=max(projected_total, counted_total),
            required_total_credits=version.total_credits,
            completion_ratio=round(
                min(counted_total / version.total_credits, 1.0),
                4,
            ),
            group_progress=group_progress,
            violations=violations,
        )

    def validate_study_plan(
        self,
        study_plan_id: int,
    ) -> StudyPlanValidationResponse:
        plan = self.session.scalar(
            select(StudyPlan)
            .where(StudyPlan.id == study_plan_id)
            .options(
                selectinload(StudyPlan.student).selectinload(
                    StudentProfile.course_records
                ),
                selectinload(StudyPlan.terms)
                .selectinload(StudyPlanTerm.courses),
            )
        )
        if plan is None:
            raise self._lookup_error(
                ErrorCode.STUDY_PLAN_NOT_FOUND,
                f"学习方案 ID {study_plan_id} 不存在。",
                "study_plan",
                study_plan_id,
            )
        student = plan.student
        version, _ = self._load_scope(
            student.program_version_id,
            student.specialisation_id,
        )
        earned, projected = self._record_credit_maps(student)
        completed_before = set(earned)
        scheduled_course_ids: set[int] = set()
        all_plan_ids = {
            plan_course.course_id
            for term in plan.terms
            for plan_course in term.courses
        }
        term_results: list[RuleResult] = []
        course_versions = self._course_versions_for_year(
            version.handbook_year
        )

        for term in sorted(
            plan.terms,
            key=lambda item: item.sequence_number,
        ):
            failure_count_before = sum(
                not item.passed for item in term_results
            )
            term_course_ids = [item.course_id for item in term.courses]
            term_credits = sum(
                course_versions[item].credit_points
                for item in term_course_ids
                if item in course_versions
            )
            if term.max_credits is not None and term_credits > term.max_credits:
                term_results.append(
                    self._failed(
                        ErrorCode.GROUP_MAX_CREDITS_EXCEEDED,
                        (
                            f"{term.term_code} 安排 {term_credits} 学分，"
                            f"超过上限 {term.max_credits}。"
                        ),
                        [
                            EvidenceItem(
                                source_type="study_plan_term",
                                rule_id=term.id,
                                details={
                                    "term_code": term.term_code,
                                    "planned_credits": term_credits,
                                    "max_credits": term.max_credits,
                                },
                            )
                        ],
                    )
                )
            for course_id in term_course_ids:
                course = self.session.get(Course, course_id)
                if course_id in earned or course_id in scheduled_course_ids:
                    term_results.append(
                        self._failed(
                            ErrorCode.PLAN_COURSE_ALREADY_COMPLETED,
                            f"{course.code} 已完成或已在更早学期安排。",
                            [
                                EvidenceItem(
                                    source_type="student_course_record",
                                    details={"course_id": course_id},
                                )
                            ],
                        )
                    )
                role = self.classify_course_role(
                    student.program_version_id,
                    student.specialisation_id,
                    course_id,
                )
                if not role.result.passed:
                    term_results.append(role.result)
                prerequisite = self.check_prerequisites(
                    student.program_version_id,
                    student.specialisation_id,
                    course_id,
                    completed_before,
                )
                if not prerequisite.eligible:
                    term_results.append(prerequisite.result)
                scheduled_course_ids.add(course_id)
            term_results.extend(
                self._check_exclusions(
                    student.program_version_id,
                    student.specialisation_id,
                    completed_before | set(term_course_ids),
                )
            )
            failure_count_after = sum(
                not item.passed for item in term_results
            )
            if failure_count_after == failure_count_before:
                term_results.append(
                    self._ok(
                        f"{term.term_code} 的课程顺序与学分负荷已检查。",
                        [
                            EvidenceItem(
                                source_type="study_plan_term",
                                rule_id=term.id,
                                details={
                                    "term_code": term.term_code,
                                    "course_ids": term_course_ids,
                                    "credits": term_credits,
                                },
                            )
                        ],
                    )
                )
            completed_before.update(term_course_ids)

        progress = self.calculate_degree_progress(
            student.id,
            include_projected=True,
            additional_course_ids=all_plan_ids,
        )
        requirement_results = progress.violations
        failures = [
            item
            for item in [*term_results, *requirement_results]
            if not item.passed
        ]
        return StudyPlanValidationResponse(
            result=(
                self._ok(
                    "学习方案满足课程顺序与毕业规则。",
                    [
                        EvidenceItem(
                            source_type="study_plan",
                            rule_id=plan.id,
                            details={"term_count": len(plan.terms)},
                        )
                    ],
                )
                if not failures
                else failures[0]
            ),
            study_plan_id=plan.id,
            valid=not failures,
            term_results=term_results,
            requirement_results=requirement_results,
            projected_progress=progress,
        )

    def _load_scope(
        self,
        program_version_id: int,
        specialisation_id: int,
    ) -> tuple[ProgramVersion, Specialisation]:
        version = self.session.scalar(
            select(ProgramVersion)
            .where(ProgramVersion.id == program_version_id)
            .options(selectinload(ProgramVersion.program))
        )
        if version is None:
            raise self._lookup_error(
                ErrorCode.PROGRAM_VERSION_NOT_FOUND,
                f"项目版本 ID {program_version_id} 不存在。",
                "program_version",
                program_version_id,
            )
        specialisation = self.session.get(
            Specialisation,
            specialisation_id,
        )
        if (
            specialisation is None
            or specialisation.program_version_id != program_version_id
        ):
            raise self._lookup_error(
                ErrorCode.SPECIALISATION_NOT_FOUND,
                "方向不存在，或不属于指定项目版本。",
                "specialisation",
                specialisation_id,
            )
        return version, specialisation

    def _load_student(self, student_id: int) -> StudentProfile:
        student = self.session.scalar(
            select(StudentProfile)
            .where(StudentProfile.id == student_id)
            .options(selectinload(StudentProfile.course_records))
        )
        if student is None:
            raise self._lookup_error(
                ErrorCode.STUDENT_NOT_FOUND,
                f"学生档案 ID {student_id} 不存在。",
                "student_profile",
                student_id,
            )
        return student

    def _load_requirement_groups(
        self,
        program_version_id: int,
        specialisation_id: int,
    ) -> list[RequirementGroup]:
        return list(
            self.session.scalars(
                select(RequirementGroup)
                .where(
                    RequirementGroup.program_version_id
                    == program_version_id,
                    or_(
                        RequirementGroup.specialisation_id.is_(None),
                        RequirementGroup.specialisation_id
                        == specialisation_id,
                    ),
                )
                .options(
                    selectinload(
                        RequirementGroup.course_links
                    )
                    .selectinload(
                        RequirementGroupCourse.course_version
                    )
                    .selectinload(CourseVersion.course)
                )
                .order_by(
                    RequirementGroup.scope,
                    RequirementGroup.code,
                )
            )
        )

    def _record_credit_maps(
        self,
        student: StudentProfile,
    ) -> tuple[dict[int, int], dict[int, int]]:
        course_versions = self._course_versions_for_year(
            student.program_version.handbook_year
        )
        earned: dict[int, int] = {}
        projected: dict[int, int] = {}
        for record in sorted(
            student.course_records,
            key=lambda item: item.attempt_number,
        ):
            course_version = course_versions.get(record.course_id)
            default_credit = (
                course_version.credit_points if course_version else 0
            )
            credit = (
                record.credit_points_awarded
                if record.credit_points_awarded is not None
                else default_credit
            )
            if record.status in EARNED_STATUSES:
                earned[record.course_id] = credit
                projected[record.course_id] = credit
            elif (
                record.status in PROJECTED_STATUSES
                and record.course_id not in earned
            ):
                projected[record.course_id] = credit
        return earned, projected

    def _course_versions_for_year(
        self,
        handbook_year: int,
    ) -> dict[int, CourseVersion]:
        return {
            item.course_id: item
            for item in self.session.scalars(
                select(CourseVersion)
                .where(CourseVersion.handbook_year == handbook_year)
                .options(selectinload(CourseVersion.course))
            )
        }

    def _eligible_total(
        self,
        program_version_id: int,
        specialisation_id: int,
        credits: dict[int, int],
    ) -> int:
        eligible_ids = {
            link.course_version.course_id
            for group in self._load_requirement_groups(
                program_version_id,
                specialisation_id,
            )
            for link in group.course_links
        }
        return sum(
            credit
            for course_id, credit in credits.items()
            if course_id in eligible_ids
        )

    def _audit_requirements(
        self,
        version: ProgramVersion,
        specialisation_id: int,
        selected_credits: dict[int, int],
    ) -> tuple[list[GroupProgress], list[RuleResult], int]:
        groups = self._load_requirement_groups(
            version.id,
            specialisation_id,
        )
        progress: list[GroupProgress] = []
        violations: list[RuleResult] = []
        memberships: dict[int, list[RequirementGroup]] = defaultdict(list)
        eligible_ids = set()

        for group in groups:
            link_by_course = {
                link.course_version.course_id: link
                for link in group.course_links
            }
            counted_ids = set(selected_credits) & set(link_by_course)
            counted_credits = sum(
                selected_credits[item] for item in counted_ids
            )
            eligible_ids.update(link_by_course)
            for course_id in counted_ids:
                memberships[course_id].append(group)
            missing_mandatory = [
                link.course_version.course.code
                for link in group.course_links
                if link.role
                in {
                    CourseRole.PROGRAM_CORE,
                    CourseRole.SPECIALISATION_CORE,
                    CourseRole.CAPSTONE,
                }
                and link.course_version.course_id not in counted_ids
            ]
            group_evidence = self._evidence(
                "requirement_group",
                group.id,
                {
                    **group.evidence,
                    "counted_credits": counted_credits,
                    "counted_course_ids": sorted(counted_ids),
                },
            )
            if missing_mandatory:
                code = (
                    ErrorCode.SPECIALISATION_CORE_NOT_MET
                    if group.scope == RequirementScope.SPECIALISATION
                    else ErrorCode.PROGRAM_CORE_NOT_MET
                )
                violations.append(
                    self._failed(
                        code,
                        (
                            f"{group.name} 缺少必修课程："
                            + "、".join(missing_mandatory)
                        ),
                        group_evidence,
                    )
                )
            if counted_credits < group.min_credits:
                code = (
                    ErrorCode.SPECIALISATION_CORE_NOT_MET
                    if group.scope == RequirementScope.SPECIALISATION
                    and group.group_type
                    in {
                        RequirementGroupType.CORE,
                        RequirementGroupType.CAPSTONE,
                    }
                    else ErrorCode.PROGRAM_CORE_NOT_MET
                    if group.scope == RequirementScope.PROGRAM
                    and group.group_type
                    in {
                        RequirementGroupType.CORE,
                        RequirementGroupType.CAPSTONE,
                    }
                    else ErrorCode.GROUP_MIN_CREDITS_NOT_MET
                )
                violations.append(
                    self._failed(
                        code,
                        (
                            f"{group.name} 已计入 {counted_credits} 学分，"
                            f"最低要求 {group.min_credits} 学分。"
                        ),
                        group_evidence,
                    )
                )
            if (
                group.max_credits is not None
                and counted_credits > group.max_credits
            ):
                violations.append(
                    self._failed(
                        ErrorCode.GROUP_MAX_CREDITS_EXCEEDED,
                        (
                            f"{group.name} 已计入 {counted_credits} 学分，"
                            f"最高允许 {group.max_credits} 学分。"
                        ),
                        group_evidence,
                    )
                )
            progress.append(
                GroupProgress(
                    group_id=group.id,
                    code=group.code,
                    name=group.name,
                    counted_credits=counted_credits,
                    min_credits=group.min_credits,
                    max_credits=group.max_credits,
                    satisfied=(
                        not missing_mandatory
                        and counted_credits >= group.min_credits
                        and (
                            group.max_credits is None
                            or counted_credits <= group.max_credits
                        )
                    ),
                    counted_course_codes=sorted(
                        link_by_course[item].course_version.course.code
                        for item in counted_ids
                    ),
                )
            )

        shared_course_ids = {
            course_id
            for course_id, course_groups in memberships.items()
            if len(course_groups) > 1
            and not all(
                group.allow_shared_credit for group in course_groups
            )
        }
        shared_credits = sum(
            selected_credits[item] for item in shared_course_ids
        )
        if shared_credits > version.max_shared_credits:
            violations.append(
                self._failed(
                    ErrorCode.DUPLICATE_CREDIT_COUNTING,
                    (
                        f"有 {shared_credits} 学分被多个要求组重复使用，"
                        f"当前版本最多允许 {version.max_shared_credits} 学分。"
                    ),
                    [
                        EvidenceItem(
                            source_type="duplicate_counting_policy",
                            rule_id=version.id,
                            details={
                                "course_ids": sorted(shared_course_ids),
                                "shared_credits": shared_credits,
                                "max_shared_credits": (
                                    version.max_shared_credits
                                ),
                            },
                        )
                    ],
                )
            )
        counted_total = sum(
            credits
            for course_id, credits in selected_credits.items()
            if course_id in eligible_ids
        )
        return progress, self._deduplicate_results(violations), counted_total

    def _check_exclusions(
        self,
        program_version_id: int,
        specialisation_id: int,
        selected_course_ids: set[int],
    ) -> list[RuleResult]:
        rules = self.session.scalars(
            select(CourseExclusion)
            .where(
                CourseExclusion.program_version_id == program_version_id,
                or_(
                    CourseExclusion.specialisation_id.is_(None),
                    CourseExclusion.specialisation_id
                    == specialisation_id,
                ),
            )
            .options(
                selectinload(CourseExclusion.course),
                selectinload(CourseExclusion.excluded_course),
            )
        )
        return [
            self._failed(
                ErrorCode.MUTUALLY_EXCLUSIVE_COURSES,
                (
                    f"{rule.course.code} 与 "
                    f"{rule.excluded_course.code} 不能同时计入。"
                ),
                self._evidence(
                    "course_exclusion",
                    rule.id,
                    rule.evidence,
                ),
            )
            for rule in rules
            if rule.course_id in selected_course_ids
            and rule.excluded_course_id in selected_course_ids
        ]

    @staticmethod
    def _role_priority(role: CourseRole) -> int:
        order = {
            CourseRole.PROGRAM_CORE: 0,
            CourseRole.SPECIALISATION_CORE: 1,
            CourseRole.CAPSTONE: 2,
            CourseRole.PRESCRIBED_ELECTIVE: 3,
            CourseRole.GENERAL_ELECTIVE: 4,
            CourseRole.NOT_ELIGIBLE: 5,
        }
        return order[role]

    @staticmethod
    def _evidence(
        source_type: str,
        rule_id: int | None,
        details: dict[str, Any] | None,
    ) -> list[EvidenceItem]:
        payload = dict(details or {})
        source_id = payload.pop("source_id", None)
        return [
            EvidenceItem(
                source_type=source_type,
                source_id=source_id,
                rule_id=rule_id,
                details=payload,
            )
        ]

    @staticmethod
    def _ok(
        message: str,
        evidence: list[EvidenceItem],
    ) -> RuleResult:
        return RuleResult(
            passed=True,
            error_code=ErrorCode.OK,
            message=message,
            evidence=evidence,
        )

    @staticmethod
    def _failed(
        code: ErrorCode,
        message: str,
        evidence: list[EvidenceItem],
    ) -> RuleResult:
        return RuleResult(
            passed=False,
            error_code=code,
            message=message,
            evidence=evidence,
        )

    def _lookup_error(
        self,
        code: ErrorCode,
        message: str,
        source_type: str,
        rule_id: int,
    ) -> DomainLookupError:
        return DomainLookupError(
            self._failed(
                code,
                message,
                [
                    EvidenceItem(
                        source_type=source_type,
                        rule_id=rule_id,
                    )
                ],
            )
        )

    @staticmethod
    def _deduplicate_results(
        results: list[RuleResult],
    ) -> list[RuleResult]:
        seen = set()
        unique = []
        for result in results:
            key = (result.error_code, result.message)
            if key not in seen:
                seen.add(key)
                unique.append(result)
        return unique
