"""Capability maturity model for Australian academic-data coverage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any


DEFAULT_COVERAGE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "academic_coverage.json"
)


class CoverageLevel(str, Enum):
    """Ordered maturity levels for an academic-data scope."""

    CATALOG = "CATALOG"
    STRUCTURED = "STRUCTURED"
    VERIFIED = "VERIFIED"

    @property
    def rank(self) -> int:
        return {
            CoverageLevel.CATALOG: 1,
            CoverageLevel.STRUCTURED: 2,
            CoverageLevel.VERIFIED: 3,
        }[self]


@dataclass(frozen=True)
class CoverageCapabilities:
    """Product capabilities unlocked by one maturity level."""

    catalog_discovery: bool
    evidence_search: bool
    structured_lookup: bool
    deterministic_planning: bool

    @classmethod
    def for_level(cls, level: CoverageLevel) -> CoverageCapabilities:
        return cls(
            catalog_discovery=True,
            evidence_search=True,
            structured_lookup=level.rank >= CoverageLevel.STRUCTURED.rank,
            deterministic_planning=level is CoverageLevel.VERIFIED,
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "catalog_discovery": self.catalog_discovery,
            "evidence_search": self.evidence_search,
            "structured_lookup": self.structured_lookup,
            "deterministic_planning": self.deterministic_planning,
        }


@dataclass(frozen=True)
class AcademicCoverageRecord:
    """Maturity assigned to an institution or a more specific scope."""

    university_id: str
    level: CoverageLevel
    program_code: str | None = None
    handbook_year: int | None = None
    specialisation_code: str | None = None
    source_ids: tuple[str, ...] = ()

    @property
    def specificity(self) -> int:
        return sum(
            value is not None
            for value in (
                self.program_code,
                self.handbook_year,
                self.specialisation_code,
            )
        )

    def matches(
        self,
        *,
        university_id: str,
        program_code: str | None,
        handbook_year: int | None,
        specialisation_code: str | None,
    ) -> bool:
        return (
            self.university_id == university_id.lower()
            and (
                self.program_code is None
                or self.program_code == (program_code or "").upper()
            )
            and (
                self.handbook_year is None
                or self.handbook_year == handbook_year
            )
            and (
                self.specialisation_code is None
                or self.specialisation_code
                == (specialisation_code or "").upper()
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "university_id": self.university_id,
            "program_code": self.program_code,
            "handbook_year": self.handbook_year,
            "specialisation_code": self.specialisation_code,
            "level": self.level.value,
            "capabilities": CoverageCapabilities.for_level(
                self.level
            ).to_dict(),
            "source_ids": list(self.source_ids),
        }


class AcademicCoverageRegistry:
    """Resolve the most specific declared maturity for an academic scope."""

    def __init__(self, records: list[AcademicCoverageRecord]) -> None:
        self.records = records

    @classmethod
    def from_path(
        cls,
        path: str | Path = DEFAULT_COVERAGE_PATH,
    ) -> AcademicCoverageRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        records = [
            AcademicCoverageRecord(
                university_id=item["university_id"].lower(),
                program_code=(
                    str(item["program_code"]).upper()
                    if item.get("program_code")
                    else None
                ),
                handbook_year=item.get("handbook_year"),
                specialisation_code=(
                    str(item["specialisation_code"]).upper()
                    if item.get("specialisation_code")
                    else None
                ),
                level=CoverageLevel(item["level"].upper()),
                source_ids=tuple(item.get("source_ids", [])),
            )
            for item in payload["records"]
        ]
        return cls(records)

    def resolve(
        self,
        *,
        university_id: str,
        program_code: str | None = None,
        handbook_year: int | None = None,
        specialisation_code: str | None = None,
    ) -> AcademicCoverageRecord | None:
        candidates = [
            record
            for record in self.records
            if record.matches(
                university_id=university_id,
                program_code=program_code,
                handbook_year=handbook_year,
                specialisation_code=specialisation_code,
            )
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (item.specificity, item.level.rank),
        )

    def summary(self) -> dict[str, Any]:
        by_level = {level.value: 0 for level in CoverageLevel}
        for record in self.records:
            by_level[record.level.value] += 1
        return {
            "country_code": "AU",
            "model": "CATALOG -> STRUCTURED -> VERIFIED",
            "record_count": len(self.records),
            "by_level": by_level,
        }
