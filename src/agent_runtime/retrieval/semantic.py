"""Deterministic selection and text construction for semantic retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..handbook_vector import HandbookChunk


SEMANTIC_POLICY_VERSION = "2026.09.05-v1"


class SemanticCategory(str, Enum):
    """Semantically useful Handbook content families."""

    PROGRAM_DESCRIPTION = "program_description"
    COURSE_DESCRIPTION = "course_description"
    LEARNING_OUTCOMES = "learning_outcomes"
    SPECIALISATION_DESCRIPTION = "specialisation_description"
    POLICY_GUIDANCE = "policy_guidance"
    ELIGIBILITY_GUIDANCE = "eligibility_guidance"
    CAREER_OUTCOMES = "career_outcomes"
    ACADEMIC_ADVICE = "academic_advice"
    FAQ_EXPLANATION = "faq_explanation"
    NARRATIVE_EXPLANATION = "narrative_explanation"


@dataclass(frozen=True)
class SemanticEligibility:
    """Explain whether one canonical chunk belongs in the dense subset."""

    eligible: bool
    category: SemanticCategory | None = None
    skip_reason: str | None = None


WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]*")
COURSE_CODE_PATTERN = re.compile(r"\b[A-Z]{2,5}\d{3,5}[A-Z]?\b")
NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")
NAVIGATION_PHRASES = (
    "view full page",
    "back to top",
    "skip to content",
    "select the relevant year",
    "cookie preferences",
    "breadcrumb",
)


def semantic_embedding_text(chunk: HandbookChunk) -> str:
    """Build stable semantic text without indexing storage metadata noise."""

    values: list[str] = []
    seen: set[str] = set()
    for raw in (chunk.title, chunk.heading, chunk.content):
        value = re.sub(r"\s+", " ", raw or "").strip()
        key = value.casefold()
        if value and key not in seen:
            values.append(value)
            seen.add(key)
    return "\n".join(values)


def classify_semantic_eligibility(
    chunk: HandbookChunk,
) -> SemanticEligibility:
    """Classify a chunk using deterministic, auditable content rules."""

    heading = (chunk.heading or "").casefold()
    content = re.sub(r"\s+", " ", chunk.content or "").strip()
    normalized = content.casefold()
    words = WORD_PATTERN.findall(content)
    codes = COURSE_CODE_PATTERN.findall(content.upper())
    numbers = NUMBER_PATTERN.findall(content)

    if not content:
        return SemanticEligibility(False, skip_reason="empty_content")
    if any(phrase in normalized for phrase in NAVIGATION_PHRASES):
        return SemanticEligibility(False, skip_reason="navigation_boilerplate")
    leaf_heading = heading.rsplit(">", 1)[-1].strip()
    if normalized in {leaf_heading, (chunk.title or "").casefold().strip()}:
        return SemanticEligibility(False, skip_reason="repetitive_heading")
    if content.count("|") >= 4:
        return SemanticEligibility(False, skip_reason="structured_table")
    if len(content) < 120 or len(words) < 15:
        return SemanticEligibility(False, skip_reason="short_metadata_only")
    if leaf_heading in {
        "contact",
        "coordinator",
        "fees",
        "fee information",
        "indicative fees",
        "links to further information",
        "further information",
    }:
        return SemanticEligibility(False, skip_reason="administrative_metadata")

    # Strong narrative headings take precedence over incidental identifiers or
    # numbers that occur naturally in useful explanatory prose.
    if "learning outcome" in heading or "course outcome" in heading:
        return SemanticEligibility(True, SemanticCategory.LEARNING_OUTCOMES)
    if any(term in heading for term in ("career", "employment", "professional outcome")):
        return SemanticEligibility(True, SemanticCategory.CAREER_OUTCOMES)
    if any(term in heading for term in ("academic advice", "study advice", "planning advice")):
        return SemanticEligibility(True, SemanticCategory.ACADEMIC_ADVICE)
    if chunk.source_type in {"visa_policy", "policy", "policy_explanation"}:
        return SemanticEligibility(True, SemanticCategory.POLICY_GUIDANCE)
    if "faq" in chunk.source_type or "frequently asked" in heading:
        return SemanticEligibility(True, SemanticCategory.FAQ_EXPLANATION)
    if any(term in heading for term in ("admission", "eligibility", "inherent requirement")):
        return SemanticEligibility(True, SemanticCategory.ELIGIBILITY_GUIDANCE)
    if any(term in heading for term in ("specialisation", "specialization", "major description")):
        if len(codes) <= 2 and content.count("|") < 4:
            return SemanticEligibility(
                True,
                SemanticCategory.SPECIALISATION_DESCRIPTION,
            )
    if any(term in heading for term in ("synopsis", "description", "overview", "about this")):
        category = (
            SemanticCategory.COURSE_DESCRIPTION
            if chunk.source_type == "unit_handbook"
            else SemanticCategory.PROGRAM_DESCRIPTION
        )
        return SemanticEligibility(True, category)

    # Dense retrieval adds little value to records whose meaning is primarily
    # their exact codes, table cells, periods, or numeric thresholds.
    if (
        "requirement" in heading
        and (len(numbers) >= 4 or len(codes) >= 3)
    ):
        return SemanticEligibility(False, skip_reason="exact_numeric_requirement")
    if "unit of study table" in heading and len(codes) >= 2:
        return SemanticEligibility(False, skip_reason="structured_table")
    if any(term in heading for term in ("prerequisite", "corequisite", "prohibition")) and codes:
        return SemanticEligibility(False, skip_reason="prerequisite_code_list")
    if any(term in heading for term in ("availability", "teaching period", "intake period")):
        return SemanticEligibility(False, skip_reason="teaching_period_table")
    if (
        any(term in normalized for term in ("credit points", "units of credit", " uoc", " units"))
        and len(numbers) >= 2
        and len(words) < 90
    ):
        return SemanticEligibility(False, skip_reason="exact_numeric_requirement")
    if len(codes) >= 3 and len(codes) * 4 >= len(words):
        return SemanticEligibility(False, skip_reason="course_code_list")

    if len(words) >= 30:
        return SemanticEligibility(True, SemanticCategory.NARRATIVE_EXPLANATION)
    return SemanticEligibility(False, skip_reason="low_semantic_density")


def should_embed(chunk: HandbookChunk) -> bool:
    """Compatibility-friendly boolean predicate for semantic publication."""

    return classify_semantic_eligibility(chunk).eligible
