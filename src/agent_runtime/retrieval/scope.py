"""Resolve academic metadata before any lexical or dense retrieval call."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


# Conservative implicit detection avoids misclassifying unit codes such as
# FIT9136 as a program. Less regular institutional codes remain explicit.
PROGRAM_CODE_PATTERN = re.compile(r"\b[A-Z]\d{4}\b")
HANDBOOK_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

DEFAULT_UNIVERSITY_ALIASES = {
    "monash": "monash",
    "monash university": "monash",
    "university of melbourne": "melbourne",
    "unimelb": "melbourne",
    "university of sydney": "sydney",
    "unsw": "unsw",
    "australian national university": "anu",
    "anu": "anu",
    "university of queensland": "uq",
    "uq": "uq",
    "university of western australia": "uwa",
    "uwa": "uwa",
    "adelaide university": "adelaide",
}


@dataclass(frozen=True)
class RetrievalScope:
    """Normalized metadata constraints applied before relevance scoring."""

    university_id: str | None = None
    program_code: str | None = None
    handbook_year: int | None = None
    specialisation_code: str | None = None
    discipline_id: str | None = None
    source_type: str | None = None

    def __post_init__(self) -> None:
        if self.university_id:
            object.__setattr__(
                self,
                "university_id",
                self.university_id.strip().lower(),
            )
        for field in ("program_code", "specialisation_code"):
            value = getattr(self, field)
            if value:
                object.__setattr__(self, field, value.strip().upper())
        if self.discipline_id:
            object.__setattr__(
                self,
                "discipline_id",
                self.discipline_id.strip().lower(),
            )

    def to_search_kwargs(self) -> dict[str, str | int | None]:
        return {
            "university_id": self.university_id,
            "program_code": self.program_code,
            "handbook_year": self.handbook_year,
            "specialisation_code": self.specialisation_code,
            "discipline_id": self.discipline_id,
            "source_type": self.source_type,
        }


class RetrievalScopeResolver:
    """Merge explicit request scope, conversation context, and query hints."""

    def __init__(
        self,
        *,
        university_aliases: Mapping[str, str] | None = None,
        specialisation_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.university_aliases = {
            key.lower(): value.lower()
            for key, value in (
                university_aliases or DEFAULT_UNIVERSITY_ALIASES
            ).items()
        }
        self.specialisation_aliases = {
            key.lower(): value.upper()
            for key, value in (specialisation_aliases or {}).items()
        }

    def resolve(
        self,
        query: str,
        *,
        explicit: RetrievalScope | None = None,
        context: RetrievalScope | None = None,
    ) -> RetrievalScope:
        """Resolve with precedence: explicit fields, context, query hints."""

        explicit = explicit or RetrievalScope()
        context = context or RetrievalScope()
        normalized_query = query.lower()
        detected_university = next(
            (
                university_id
                for alias, university_id in sorted(
                    self.university_aliases.items(),
                    key=lambda item: len(item[0]),
                    reverse=True,
                )
                if alias in normalized_query
            ),
            None,
        )
        detected_specialisation = next(
            (
                code
                for alias, code in self.specialisation_aliases.items()
                if alias in normalized_query
            ),
            None,
        )
        program_match = PROGRAM_CODE_PATTERN.search(query.upper())
        year_match = HANDBOOK_YEAR_PATTERN.search(query)
        return RetrievalScope(
            university_id=(
                explicit.university_id
                or context.university_id
                or detected_university
            ),
            program_code=(
                explicit.program_code
                or context.program_code
                or (program_match.group(0) if program_match else None)
            ),
            handbook_year=(
                explicit.handbook_year
                or context.handbook_year
                or (int(year_match.group(1)) if year_match else None)
            ),
            specialisation_code=(
                explicit.specialisation_code
                or context.specialisation_code
                or detected_specialisation
            ),
            discipline_id=(
                explicit.discipline_id or context.discipline_id
            ),
            source_type=explicit.source_type or context.source_type,
        )
