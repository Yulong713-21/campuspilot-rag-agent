from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUSINESS_CATALOG = (
    REPO_ROOT / "data/admissions/go8_business_catalog_2026.json"
)


class BusinessProgramCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=3)
    university_id: str = Field(min_length=2)
    program_code: str | None = None
    name: str = Field(min_length=3)
    display_name_zh: str | None = None
    discipline_id: Literal["business"] = "business"
    coursework_master: Literal[True] = True
    handbook_year: int = Field(ge=2024, le=2100)
    duration_months: list[int] = Field(default_factory=list)
    duration_label: str | None = None
    credit_value: str | None = None
    intakes: list[str] = Field(default_factory=list)
    delivery_mode: str | None = None
    campus: str | None = None
    specialisations: list[str] = Field(default_factory=list)
    official_url: HttpUrl
    source_type: Literal["OFFICIAL"] = "OFFICIAL"
    source_checked_at: date
    release_stage: Literal["FIRST_STAGE_AVAILABLE"] = "FIRST_STAGE_AVAILABLE"
    evaluation_ready: Literal[False] = False
    catalog_scope: Literal["go8_business_common_programs_v1"] = (
        "go8_business_common_programs_v1"
    )

    @model_validator(mode="after")
    def reject_research_degrees(self) -> "BusinessProgramCatalogItem":
        normalized = self.name.lower()
        forbidden = ("doctor", "phd", "research degree", "master of philosophy")
        if any(term in normalized for term in forbidden):
            raise ValueError("business catalog only accepts coursework master programs")
        return self


class BusinessProgramCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str
    applicable_year: int
    retrieved_at: date
    coverage_notice: str
    programs: list[BusinessProgramCatalogItem]

    @model_validator(mode="after")
    def validate_unique_program_ids(self) -> "BusinessProgramCatalog":
        program_ids = [item.program_id for item in self.programs]
        if len(program_ids) != len(set(program_ids)):
            raise ValueError("program_id must be unique in business catalog")
        return self

    def programs_for(self, university_id: str) -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in self.programs
            if item.university_id == university_id
        ]

    def coverage(self) -> dict[str, object]:
        universities = sorted({item.university_id for item in self.programs})
        return {
            "catalog_version": self.catalog_version,
            "external_program_count": len(self.programs),
            "external_university_count": len(universities),
            "university_ids": universities,
            "evaluation_ready_count": sum(
                item.evaluation_ready for item in self.programs
            ),
        }


def load_business_program_catalog(
    path: str | Path = DEFAULT_BUSINESS_CATALOG,
) -> BusinessProgramCatalog:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BusinessProgramCatalog.model_validate(payload)
