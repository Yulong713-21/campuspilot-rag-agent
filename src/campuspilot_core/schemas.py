from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import CourseRecordStatus, CourseRole, ErrorCode


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EvidenceItem(BaseModel):
    source_type: str
    source_id: str | None = None
    rule_id: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RuleResult(BaseModel):
    passed: bool
    error_code: ErrorCode
    message: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


class UniversityCreate(BaseModel):
    code: str
    name: str
    country_code: str = "AU"
    official_url: str | None = None


class ProgramCreate(BaseModel):
    university_id: int
    code: str
    name: str
    award_type: str


class ProgramVersionCreate(BaseModel):
    program_id: int
    handbook_year: int
    total_credits: int = Field(gt=0)
    max_shared_credits: int = Field(default=0, ge=0)
    source_url: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class AdmissionCriterionCreate(BaseModel):
    pathway_code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    duration_months: int | None = Field(default=None, gt=0)
    credits_to_complete: int | None = Field(default=None, gt=0)
    minimum_average_percent: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    criteria_text: str = Field(min_length=1)
    requirements: dict[str, Any] = Field(default_factory=dict)
    alternative_pathways: list[dict[str, Any]] = Field(default_factory=list)
    available_intakes: list[str] = Field(default_factory=list)
    source_url: str = Field(min_length=1, max_length=512)
    source_sha256: str = Field(min_length=64, max_length=64)
    evidence: dict[str, Any] = Field(default_factory=dict)


class SpecialisationCreate(BaseModel):
    program_version_id: int
    code: str
    name: str
    required_credits: int = Field(default=0, ge=0)
    evidence: dict[str, Any] = Field(default_factory=dict)


class CourseCreate(BaseModel):
    university_id: int
    code: str
    canonical_name: str


class CourseVersionCreate(BaseModel):
    course_id: int
    handbook_year: int
    title: str
    credit_points: int = Field(gt=0)
    source_url: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class StudentCourseRecordInput(BaseModel):
    course_id: int
    status: CourseRecordStatus
    attempt_number: int = Field(default=1, gt=0)
    term_code: str | None = None
    grade: str | None = None
    credit_points_awarded: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_explicit_adjusted_credits(
        self,
    ) -> "StudentCourseRecordInput":
        if (
            self.status
            in {
                CourseRecordStatus.EXEMPTED,
                CourseRecordStatus.TRANSFERRED,
            }
            and self.credit_points_awarded is None
        ):
            raise ValueError("减免或转学分记录必须填写学校核准的学分值。")
        return self


class PlannedTermInput(BaseModel):
    term_code: str
    sequence_number: int = Field(gt=0)
    course_ids: list[int]


class StudyPlanInput(BaseModel):
    student_id: int
    name: str
    terms: list[PlannedTermInput]


class CourseRequirementView(BaseModel):
    course_id: int
    course_code: str
    title: str
    credit_points: int
    role: CourseRole
    evidence: list[EvidenceItem] = Field(default_factory=list)


class RequirementGroupView(BaseModel):
    group_id: int
    code: str
    name: str
    scope: str
    group_type: str
    min_credits: int
    max_credits: int | None
    allow_shared_credit: bool
    courses: list[CourseRequirementView]
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ProgramRequirementsResponse(BaseModel):
    result: RuleResult
    program_version_id: int
    program_code: str
    program_name: str
    handbook_year: int
    total_credits: int
    max_shared_credits: int
    specialisation_id: int
    specialisation_code: str
    specialisation_name: str
    groups: list[RequirementGroupView]


class CourseRoleResponse(BaseModel):
    result: RuleResult
    program_version_id: int
    specialisation_id: int
    course_id: int
    course_code: str
    roles: list[CourseRole]
    groups: list[str]


class PrerequisiteCheckResponse(BaseModel):
    result: RuleResult
    course_id: int
    course_code: str
    eligible: bool
    group_results: list[RuleResult]


class GroupProgress(BaseModel):
    group_id: int
    code: str
    name: str
    counted_credits: int
    min_credits: int
    max_credits: int | None
    satisfied: bool
    counted_course_codes: list[str]


class DegreeProgressResponse(BaseModel):
    result: RuleResult
    student_id: int
    earned_credits: int
    projected_credits: int
    required_total_credits: int
    completion_ratio: float
    group_progress: list[GroupProgress]
    violations: list[RuleResult]


class StudyPlanValidationResponse(BaseModel):
    result: RuleResult
    study_plan_id: int
    valid: bool
    term_results: list[RuleResult]
    requirement_results: list[RuleResult]
    projected_progress: DegreeProgressResponse
