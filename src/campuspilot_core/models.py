"""SQLAlchemy models for versioned academic rules and student plans.

Rule-bearing records point to explicit program/course versions so different
Handbook years and specialisations can coexist without ambiguous lookups.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    Float,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .enums import (
    CourseRecordStatus,
    CourseRole,
    RequirementGroupType,
    RequirementScope,
    StudyPlanStatus,
)


def enum_column(enum_type: type[Any]) -> SqlEnum:
    return SqlEnum(
        enum_type,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=40,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class University(TimestampMixin, Base):
    __tablename__ = "universities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        default="AU",
    )
    official_url: Mapped[str | None] = mapped_column(String(512))

    programs: Mapped[list["Program"]] = relationship(
        back_populates="university",
        cascade="all, delete-orphan",
    )
    courses: Mapped[list["Course"]] = relationship(
        back_populates="university",
        cascade="all, delete-orphan",
    )


class Program(TimestampMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("university_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[int] = mapped_column(
        ForeignKey("universities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    award_type: Mapped[str] = mapped_column(String(80), nullable=False)

    university: Mapped[University] = relationship(back_populates="programs")
    versions: Mapped[list["ProgramVersion"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
    )


class ProgramVersion(TimestampMixin, Base):
    __tablename__ = "program_versions"
    __table_args__ = (
        UniqueConstraint("program_id", "handbook_year"),
        CheckConstraint(
            "total_credits > 0",
            name="positive_total_credits",
        ),
        CheckConstraint(
            "max_shared_credits >= 0",
            name="non_negative_shared_credits",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    handbook_year: Mapped[int] = mapped_column(Integer, nullable=False)
    total_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    max_shared_credits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    effective_from: Mapped[str | None] = mapped_column(String(32))
    effective_to: Mapped[str | None] = mapped_column(String(32))
    source_url: Mapped[str | None] = mapped_column(String(512))
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    program: Mapped[Program] = relationship(back_populates="versions")
    specialisations: Mapped[list["Specialisation"]] = relationship(
        back_populates="program_version",
        cascade="all, delete-orphan",
    )
    requirement_groups: Mapped[list["RequirementGroup"]] = relationship(
        back_populates="program_version",
        cascade="all, delete-orphan",
    )
    admission_criteria: Mapped[list["AdmissionCriterion"]] = relationship(
        back_populates="program_version",
        cascade="all, delete-orphan",
    )
    catalog_profile: Mapped["ProgramCatalogProfile | None"] = relationship(
        back_populates="program_version",
        cascade="all, delete-orphan",
        uselist=False,
    )
    alternative_admission_pathways: Mapped[list["AlternativeAdmissionPathway"]] = (
        relationship(
            back_populates="program_version",
            cascade="all, delete-orphan",
        )
    )


class ProgramCatalogProfile(TimestampMixin, Base):
    __tablename__ = "program_catalog_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    faculty_name: Mapped[str | None] = mapped_column(String(255))
    display_name_zh: Mapped[str | None] = mapped_column(String(255))
    discipline_id: Mapped[str] = mapped_column(String(64), nullable=False)
    coursework_master: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    duration_months_min: Mapped[int | None] = mapped_column(Integer)
    duration_months_max: Mapped[int | None] = mapped_column(Integer)
    available_intakes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    official_url: Mapped[str] = mapped_column(String(512), nullable=False)
    release_stage: Mapped[str] = mapped_column(String(40), nullable=False)

    program_version: Mapped[ProgramVersion] = relationship(
        back_populates="catalog_profile"
    )


class AdmissionEvidence(TimestampMixin, Base):
    __tablename__ = "admission_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_key: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        unique=True,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_year: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    evidence_grade: Mapped[str] = mapped_column(String(24), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    hard_decision_allowed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    admission_rules: Mapped[list["AdmissionRule"]] = relationship(
        back_populates="evidence"
    )
    alternative_pathways: Mapped[list["AlternativeAdmissionPathway"]] = relationship(
        back_populates="evidence"
    )


class AdmissionCriterion(TimestampMixin, Base):
    """One official admission pathway for a versioned program."""

    __tablename__ = "admission_criteria"
    __table_args__ = (
        UniqueConstraint(
            "program_version_id",
            "pathway_code",
            name="uq_admission_criteria_version_pathway",
        ),
        CheckConstraint(
            "credits_to_complete IS NULL OR credits_to_complete > 0",
            name="positive_admission_credits",
        ),
        CheckConstraint(
            "duration_months IS NULL OR duration_months > 0",
            name="positive_admission_duration",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pathway_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_months: Mapped[int | None] = mapped_column(Integer)
    credits_to_complete: Mapped[int | None] = mapped_column(Integer)
    minimum_average_percent: Mapped[float | None] = mapped_column(Float)
    criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    alternative_pathways: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    available_intakes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    program_version: Mapped[ProgramVersion] = relationship(
        back_populates="admission_criteria"
    )
    rules: Mapped[list["AdmissionRule"]] = relationship(
        back_populates="criterion",
        cascade="all, delete-orphan",
    )


class AdmissionRule(TimestampMixin, Base):
    __tablename__ = "admission_rules"
    __table_args__ = (
        UniqueConstraint("criterion_id", "rule_code"),
        CheckConstraint(
            "minimum_value IS NULL OR minimum_value >= 0",
            name="non_negative_admission_minimum",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    criterion_id: Mapped[int] = mapped_column(
        ForeignKey("admission_criteria.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("admission_evidence.id"),
        nullable=False,
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(80), nullable=False)
    applicant_condition: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    metric_type: Mapped[str] = mapped_column(String(40), nullable=False)
    minimum_value: Mapped[float | None] = mapped_column(Float)
    scale_max: Mapped[float | None] = mapped_column(Float)
    applicable_intakes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    criterion: Mapped[AdmissionCriterion] = relationship(back_populates="rules")
    evidence: Mapped[AdmissionEvidence] = relationship(back_populates="admission_rules")


class AlternativeAdmissionPathway(TimestampMixin, Base):
    __tablename__ = "alternative_admission_pathways"
    __table_args__ = (UniqueConstraint("program_version_id", "pathway_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("admission_evidence.id"),
        nullable=False,
        index=True,
    )
    pathway_code: Mapped[str] = mapped_column(String(80), nullable=False)
    pathway_type: Mapped[str] = mapped_column(String(48), nullable=False)
    official_compensation: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    duration_months: Mapped[int | None] = mapped_column(Integer)
    tuition_amount: Mapped[float | None] = mapped_column(Float)
    tuition_currency: Mapped[str | None] = mapped_column(String(3))
    progression_conditions: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    applicable_intakes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    program_version: Mapped[ProgramVersion] = relationship(
        back_populates="alternative_admission_pathways"
    )
    evidence: Mapped[AdmissionEvidence] = relationship(
        back_populates="alternative_pathways"
    )


class Specialisation(TimestampMixin, Base):
    __tablename__ = "specialisations"
    __table_args__ = (
        UniqueConstraint("program_version_id", "code"),
        CheckConstraint(
            "required_credits >= 0",
            name="non_negative_required_credits",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    required_credits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    program_version: Mapped[ProgramVersion] = relationship(
        back_populates="specialisations"
    )
    requirement_groups: Mapped[list["RequirementGroup"]] = relationship(
        back_populates="specialisation"
    )


class Course(TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("university_id", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    university_id: Mapped[int] = mapped_column(
        ForeignKey("universities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False)

    university: Mapped[University] = relationship(back_populates="courses")
    versions: Mapped[list["CourseVersion"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )


class CourseVersion(TimestampMixin, Base):
    """Year-scoped authoritative facts for one canonical course."""
    __tablename__ = "course_versions"
    __table_args__ = (
        UniqueConstraint("course_id", "handbook_year"),
        CheckConstraint(
            "credit_points > 0",
            name="positive_credit_points",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    handbook_year: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    credit_points: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    source_url: Mapped[str | None] = mapped_column(String(512))
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    course: Mapped[Course] = relationship(back_populates="versions")
    offerings: Mapped[list["CourseOffering"]] = relationship(
        back_populates="course_version",
        cascade="all, delete-orphan",
    )


class CourseOffering(TimestampMixin, Base):
    """A teaching period attached to an exact Handbook course version.

    The year comes from `CourseVersion`; duplicating it here would permit
    contradictory offering/year combinations.
    """
    __tablename__ = "course_offerings"
    __table_args__ = (
        UniqueConstraint(
            "course_version_id",
            "teaching_period",
            name="uq_course_offerings_version_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_version_id: Mapped[int] = mapped_column(
        ForeignKey("course_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    teaching_period: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    course_version: Mapped[CourseVersion] = relationship(
        back_populates="offerings"
    )


class RequirementGroup(TimestampMixin, Base):
    """Program-wide or specialisation-scoped degree requirement bucket."""
    __tablename__ = "requirement_groups"
    __table_args__ = (
        UniqueConstraint(
            "program_version_id",
            "specialisation_id",
            "code",
        ),
        CheckConstraint(
            "min_credits >= 0",
            name="non_negative_min_credits",
        ),
        CheckConstraint(
            "max_credits IS NULL OR max_credits >= min_credits",
            name="valid_credit_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("specialisations.id", ondelete="CASCADE"),
        index=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope: Mapped[RequirementScope] = mapped_column(
        enum_column(RequirementScope),
        nullable=False,
    )
    group_type: Mapped[RequirementGroupType] = mapped_column(
        enum_column(RequirementGroupType),
        nullable=False,
    )
    min_credits: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    max_credits: Mapped[int | None] = mapped_column(Integer)
    allow_shared_credit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    program_version: Mapped[ProgramVersion] = relationship(
        back_populates="requirement_groups"
    )
    specialisation: Mapped[Specialisation | None] = relationship(
        back_populates="requirement_groups"
    )
    course_links: Mapped[list["RequirementGroupCourse"]] = relationship(
        back_populates="requirement_group",
        cascade="all, delete-orphan",
    )


class RequirementGroupCourse(TimestampMixin, Base):
    __tablename__ = "requirement_group_courses"
    __table_args__ = (UniqueConstraint("requirement_group_id", "course_version_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_group_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_version_id: Mapped[int] = mapped_column(
        ForeignKey("course_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[CourseRole] = mapped_column(
        enum_column(CourseRole),
        nullable=False,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    requirement_group: Mapped[RequirementGroup] = relationship(
        back_populates="course_links"
    )
    course_version: Mapped[CourseVersion] = relationship()


class PrerequisiteGroup(TimestampMixin, Base):
    __tablename__ = "prerequisite_groups"
    __table_args__ = (
        UniqueConstraint(
            "program_version_id",
            "specialisation_id",
            "course_id",
            "group_index",
        ),
        CheckConstraint(
            "minimum_satisfied > 0",
            name="positive_minimum_satisfied",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("specialisations.id", ondelete="CASCADE"),
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    group_index: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_satisfied: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    course: Mapped[Course] = relationship(
        foreign_keys=[course_id],
    )
    options: Mapped[list["PrerequisiteOption"]] = relationship(
        back_populates="prerequisite_group",
        cascade="all, delete-orphan",
    )


class PrerequisiteOption(TimestampMixin, Base):
    __tablename__ = "prerequisite_options"
    __table_args__ = (
        UniqueConstraint(
            "prerequisite_group_id",
            "prerequisite_course_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prerequisite_group_id: Mapped[int] = mapped_column(
        ForeignKey("prerequisite_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prerequisite_course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    prerequisite_group: Mapped[PrerequisiteGroup] = relationship(
        back_populates="options"
    )
    prerequisite_course: Mapped[Course] = relationship()


class CourseExclusion(TimestampMixin, Base):
    __tablename__ = "course_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "program_version_id",
            "specialisation_id",
            "course_id",
            "excluded_course_id",
        ),
        CheckConstraint(
            "course_id <> excluded_course_id",
            name="different_excluded_course",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialisation_id: Mapped[int | None] = mapped_column(
        ForeignKey("specialisations.id", ondelete="CASCADE"),
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    excluded_course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    course: Mapped[Course] = relationship(foreign_keys=[course_id])
    excluded_course: Mapped[Course] = relationship(foreign_keys=[excluded_course_id])


class StudentProfile(TimestampMixin, Base):
    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_ref: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        unique=True,
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    program_version_id: Mapped[int] = mapped_column(
        ForeignKey("program_versions.id"),
        nullable=False,
        index=True,
    )
    specialisation_id: Mapped[int] = mapped_column(
        ForeignKey("specialisations.id"),
        nullable=False,
        index=True,
    )

    program_version: Mapped[ProgramVersion] = relationship()
    specialisation: Mapped[Specialisation] = relationship()
    course_records: Mapped[list["StudentCourseRecord"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )
    study_plans: Mapped[list["StudyPlan"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )


class StudentCourseRecord(TimestampMixin, Base):
    __tablename__ = "student_course_records"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", "attempt_number"),
        CheckConstraint(
            "attempt_number > 0",
            name="positive_attempt_number",
        ),
        CheckConstraint(
            "credit_points_awarded IS NULL OR credit_points_awarded >= 0",
            name="non_negative_awarded_credits",
        ),
        CheckConstraint(
            (
                "status NOT IN ('EXEMPTED', 'TRANSFERRED') "
                "OR credit_points_awarded IS NOT NULL"
            ),
            name="explicit_adjusted_credits",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"),
        nullable=False,
        index=True,
    )
    status: Mapped[CourseRecordStatus] = mapped_column(
        enum_column(CourseRecordStatus),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    term_code: Mapped[str | None] = mapped_column(String(32))
    grade: Mapped[str | None] = mapped_column(String(16))
    credit_points_awarded: Mapped[int | None] = mapped_column(Integer)
    source_note: Mapped[str | None] = mapped_column(String(255))

    student: Mapped[StudentProfile] = relationship(back_populates="course_records")
    course: Mapped[Course] = relationship()


class StudyPlan(TimestampMixin, Base):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[StudyPlanStatus] = mapped_column(
        enum_column(StudyPlanStatus),
        nullable=False,
        default=StudyPlanStatus.DRAFT,
    )
    objective: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    student: Mapped[StudentProfile] = relationship(back_populates="study_plans")
    terms: Mapped[list["StudyPlanTerm"]] = relationship(
        back_populates="study_plan",
        cascade="all, delete-orphan",
        order_by="StudyPlanTerm.sequence_number",
    )


class StudyPlanTerm(TimestampMixin, Base):
    __tablename__ = "study_plan_terms"
    __table_args__ = (
        UniqueConstraint(
            "study_plan_id",
            "sequence_number",
            name="uq_study_plan_terms_plan_sequence",
        ),
        UniqueConstraint(
            "study_plan_id",
            "term_code",
            name="uq_study_plan_terms_plan_term",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="positive_sequence_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_plan_id: Mapped[int] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    term_code: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    max_credits: Mapped[int | None] = mapped_column(Integer)

    study_plan: Mapped[StudyPlan] = relationship(back_populates="terms")
    courses: Mapped[list["StudyPlanCourse"]] = relationship(
        back_populates="term",
        cascade="all, delete-orphan",
    )


class StudyPlanCourse(TimestampMixin, Base):
    __tablename__ = "study_plan_courses"
    __table_args__ = (UniqueConstraint("study_plan_term_id", "course_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    study_plan_term_id: Mapped[int] = mapped_column(
        ForeignKey("study_plan_terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"),
        nullable=False,
        index=True,
    )
    preferred_role: Mapped[CourseRole | None] = mapped_column(enum_column(CourseRole))
    notes: Mapped[str | None] = mapped_column(Text)

    term: Mapped[StudyPlanTerm] = relationship(back_populates="courses")
    course: Mapped[Course] = relationship()


Index(
    "ix_requirement_groups_version_scope",
    RequirementGroup.program_version_id,
    RequirementGroup.specialisation_id,
    RequirementGroup.scope,
)
Index(
    "ix_student_records_student_status",
    StudentCourseRecord.student_id,
    StudentCourseRecord.status,
)
Index(
    "ix_prerequisite_groups_scope_course",
    PrerequisiteGroup.program_version_id,
    PrerequisiteGroup.specialisation_id,
    PrerequisiteGroup.course_id,
)
Index(
    "uq_requirement_groups_program_rule",
    RequirementGroup.program_version_id,
    RequirementGroup.code,
    unique=True,
    postgresql_where=RequirementGroup.specialisation_id.is_(None),
    sqlite_where=RequirementGroup.specialisation_id.is_(None),
).ddl_if(dialect=("postgresql", "sqlite"))
Index(
    "uq_prerequisite_groups_program_rule",
    PrerequisiteGroup.program_version_id,
    PrerequisiteGroup.course_id,
    PrerequisiteGroup.group_index,
    unique=True,
    postgresql_where=PrerequisiteGroup.specialisation_id.is_(None),
    sqlite_where=PrerequisiteGroup.specialisation_id.is_(None),
).ddl_if(dialect=("postgresql", "sqlite"))
Index(
    "uq_course_exclusions_program_rule",
    CourseExclusion.program_version_id,
    CourseExclusion.course_id,
    CourseExclusion.excluded_course_id,
    unique=True,
    postgresql_where=CourseExclusion.specialisation_id.is_(None),
    sqlite_where=CourseExclusion.specialisation_id.is_(None),
).ddl_if(dialect=("postgresql", "sqlite"))
