"""Deterministic capability planning for academic evidence queries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from .scope import RetrievalScope


class RouteCapability(str, Enum):
    """Independent capabilities that may participate in one query plan."""

    STRUCTURED = "structured"
    LEXICAL = "lexical"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class CandidateConstraints:
    """Structured-first candidate identifiers passed into evidence search."""

    course_codes: tuple[str, ...] = ()
    program_codes: tuple[str, ...] = ()
    specialisation_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "course_codes",
            "program_codes",
            "specialisation_codes",
        ):
            normalized = tuple(
                dict.fromkeys(
                    str(value).strip().upper()
                    for value in getattr(self, field_name)
                    if str(value).strip()
                )
            )
            object.__setattr__(self, field_name, normalized)

    @property
    def count(self) -> int:
        return sum(
            len(values)
            for values in (
                self.course_codes,
                self.program_codes,
                self.specialisation_codes,
            )
        )

    @property
    def has_any(self) -> bool:
        return self.count > 0

    def to_search_kwargs(self) -> dict[str, tuple[str, ...]]:
        return {
            "candidate_course_codes": self.course_codes,
            "candidate_program_codes": self.program_codes,
            "candidate_specialisation_codes": self.specialisation_codes,
        }

    def merge(self, other: CandidateConstraints) -> CandidateConstraints:
        """Combine upstream and newly resolved candidates without duplicates."""

        return CandidateConstraints(
            course_codes=self.course_codes + other.course_codes,
            program_codes=self.program_codes + other.program_codes,
            specialisation_codes=(
                self.specialisation_codes + other.specialisation_codes
            ),
        )


@dataclass(frozen=True)
class RetrievalPlan:
    """Inspectable execution decision produced without network dependencies."""

    use_structured_rules: bool
    use_lexical: bool
    use_semantic: bool
    require_candidate_scope: bool
    reasons: tuple[str, ...]
    router_fallback_used: bool = False

    @property
    def route(self) -> tuple[str, ...]:
        return tuple(
            capability.value
            for capability, enabled in (
                (RouteCapability.STRUCTURED, self.use_structured_rules),
                (RouteCapability.LEXICAL, self.use_lexical),
                (RouteCapability.SEMANTIC, self.use_semantic),
            )
            if enabled
        )

    def without_semantic(self, reason: str) -> RetrievalPlan:
        """Return a degraded plan while retaining structured and lexical work."""

        return RetrievalPlan(
            use_structured_rules=self.use_structured_rules,
            use_lexical=self.use_lexical,
            use_semantic=False,
            require_candidate_scope=self.require_candidate_scope,
            reasons=(*self.reasons, reason),
            router_fallback_used=self.router_fallback_used,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "route": list(self.route),
            "use_structured_rules": self.use_structured_rules,
            "use_lexical": self.use_lexical,
            "use_semantic": self.use_semantic,
            "require_candidate_scope": self.require_candidate_scope,
            "reasons": list(self.reasons),
            "router_fallback_used": self.router_fallback_used,
        }


class QueryRouter:
    """Plan retrieval capabilities using auditable multilingual heuristics."""

    IDENTIFIER_PATTERN = re.compile(r"\b[A-Z]{2,5}\d{3,5}[A-Z]?\b")
    STRUCTURED_MARKERS = (
        "prerequisite",
        "prerequisites",
        "corequisite",
        "incompatib",
        "exclusion",
        "can i take",
        "eligible to take",
        "eligibility to take",
        "study plan valid",
        "plan valid",
        "required course",
        "required unit",
        "completion requirement",
        "specialisation requirement",
        "specialization requirement",
        "先修",
        "能不能选",
        "可以选",
        "培养方案",
        "毕业要求",
        "必修",
        "冲突课程",
    )
    OFFERING_MARKERS = (
        "offered in",
        "course offered",
        "unit offered",
        "teaching period",
        "semester 1",
        "semester 2",
        "trimester 1",
        "trimester 2",
        "trimester 3",
        " t1",
        " t2",
        " t3",
        "开课",
        "学期",
    )
    CREDIT_MARKERS = (
        "credit point",
        "credit requirement",
        "units of credit",
        "how many credits",
        "学分",
    )
    POLICY_MARKERS = (
        "handbook",
        "official wording",
        "official requirement",
        "citation",
        "cite",
        "policy",
        "late withdrawal",
        "官方",
        "原文",
        "政策",
    )
    SEMANTIC_MARKERS = (
        "career",
        "interested in",
        "interest in",
        "suitable",
        "best fit",
        " fit ",
        " fits ",
        "recommend",
        "which course",
        "which unit",
        "which program",
        "which specialisation",
        "which specialization",
        "want to learn",
        "learning outcome",
        "description",
        "without a computing background",
        "what does",
        "what is the meaning",
        "compare the fit",
        "职业",
        "兴趣",
        "适合",
        "推荐",
        "想学",
        "学习成果",
        "什么意思",
    )
    CANDIDATE_DISCOVERY_MARKERS = (
        "which course",
        "which unit",
        "which elective",
        "courses can i take",
        "units can i take",
        "electives",
        "选哪些",
        "哪些课",
        "选修课",
    )

    def plan(self, query: str, scope: RetrievalScope) -> RetrievalPlan:
        """Resolve capability needs after academic scope has been normalized."""

        compact_query = re.sub(r"\s+", " ", query).casefold().strip()
        normalized = f" {compact_query} "
        reasons: list[str] = []
        structured = False
        lexical = False
        semantic = False

        if any(marker in normalized for marker in self.STRUCTURED_MARKERS):
            structured = True
            reasons.append("deterministic_rule_intent")
        if any(marker in normalized for marker in self.OFFERING_MARKERS):
            structured = True
            reasons.append("teaching_period_intent")
        if any(marker in normalized for marker in self.CREDIT_MARKERS):
            structured = True
            reasons.append("credit_requirement_intent")

        if self.IDENTIFIER_PATTERN.search(query.upper()):
            lexical = True
            reasons.append("exact_identifier")
        if any(marker in normalized for marker in self.POLICY_MARKERS):
            lexical = True
            reasons.append("official_wording_or_policy")
        if any(marker in normalized for marker in self.SEMANTIC_MARKERS):
            semantic = True
            lexical = True
            reasons.append("descriptive_or_similarity_intent")

        candidate_discovery = any(
            marker in normalized
            for marker in self.CANDIDATE_DISCOVERY_MARKERS
        )
        if semantic and candidate_discovery and scope.program_code:
            structured = True
            reasons.append("program_scoped_candidate_validation")

        # Rule answers should be accompanied by exact official evidence, while
        # exact identifier lookups should not pay the semantic retrieval cost.
        if structured:
            lexical = True
        if not lexical and not semantic:
            lexical = True
            reasons.append("default_lexical_evidence")

        require_candidates = structured and semantic and candidate_discovery
        return RetrievalPlan(
            use_structured_rules=structured,
            use_lexical=lexical,
            use_semantic=semantic,
            require_candidate_scope=require_candidates,
            reasons=tuple(dict.fromkeys(reasons)),
        )
