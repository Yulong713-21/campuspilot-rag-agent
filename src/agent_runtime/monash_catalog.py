from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from datetime import date
import re
from typing import Any

import httpx


MONASH_SEARCH_URL = (
    "https://handbook.monash.edu/api/search/search-all"
)
MONASH_SITE_ID = "monash-prod-pres"

# Curated for the first single-university corpus. The scope intentionally
# excludes research degrees, most double degrees, and unrelated disciplines.
MONASH_PROGRAM_SCOPE: dict[str, tuple[str, ...]] = {
    "business": (
        "B6004",
        "B6005",
        "B6007",
        "B6008",
        "B6011",
        "B6014",
        "B6022",
        "B6025",
        "B6027",
        "B6028",
        "B6030",
        "B6033",
        "B6035",
        "B6036",
        "B6037",
        "B6038",
        "B6039",
        "B6040",
        "B6041",
        "B6042",
        "B6059",
    ),
    "computing": (
        "C6001",
        "C6002",
        "C6003",
        "C6004",
        "C6007",
        "C6008",
    ),
    "engineering": (
        "E6005",
        "E6006",
        "E6009",
        "E6011",
        "E6012",
        "E6013",
        "E6014",
        "E6016",
        "E6017",
    ),
    "mathematics": (
        "S6001",
        "S6003",
    ),
    "physics": ("S6000",),
}


def fetch_monash_course_catalog(
    *,
    transport: httpx.BaseTransport | None = None,
    required_codes: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    required = {
        code.upper()
        for code in (
            required_codes
            if required_codes is not None
            else (
                code
                for codes in MONASH_PROGRAM_SCOPE.values()
                for code in codes
            )
        )
    }
    results: list[dict[str, Any]] = []
    with httpx.Client(
        transport=transport,
        timeout=45.0,
        follow_redirects=True,
        headers={
            "Referer": "https://handbook.monash.edu/search",
            "User-Agent": (
                "CampusPilotCatalogCollector/0.1 "
                "(local education research project)"
            ),
        },
    ) as client:
        offset = 0
        total = 1
        while offset < total:
            response = client.get(
                MONASH_SEARCH_URL,
                params={
                    "from": offset,
                    "query": "Master of",
                    "searchType": "advanced",
                    "siteId": MONASH_SITE_ID,
                    "siteYear": "current",
                    "size": 100,
                },
            )
            response.raise_for_status()
            payload = response.json()["data"]
            page = payload["results"]
            results.extend(page)
            total = int(payload["total"])
            if not page:
                break
            offset += len(page)
        returned_codes = {
            str(item.get("code") or "").upper()
            for item in results
            if (item.get("lines") or [None])[0] == "Course"
        }
        for code in sorted(required - returned_codes):
            response = client.get(
                MONASH_SEARCH_URL,
                params={
                    "from": 0,
                    "query": code,
                    "searchType": "advanced",
                    "siteId": MONASH_SITE_ID,
                    "siteYear": "current",
                    "size": 20,
                },
            )
            response.raise_for_status()
            exact = [
                item
                for item in response.json()["data"]["results"]
                if str(item.get("code") or "").upper() == code
                and (item.get("lines") or [None])[0] == "Course"
            ]
            results.extend(exact)
    return results


def build_monash_program_sources(
    catalog_items: Iterable[dict[str, Any]],
    *,
    handbook_years: Iterable[int] = (2024, 2025, 2026),
) -> list[dict[str, Any]]:
    discipline_by_code = {
        code: discipline
        for discipline, codes in MONASH_PROGRAM_SCOPE.items()
        for code in codes
    }
    title_by_code: dict[str, str] = {}
    for item in catalog_items:
        lines = item.get("lines") or []
        code = str(item.get("code") or "").upper()
        if (
            code not in discipline_by_code
            or not lines
            or lines[0] != "Course"
        ):
            continue
        title_by_code.setdefault(code, str(item["title"]).strip())

    missing_codes = sorted(set(discipline_by_code) - set(title_by_code))
    if missing_codes:
        raise ValueError(
            "Monash official search did not return scoped programs: "
            + ", ".join(missing_codes)
        )

    sources: list[dict[str, Any]] = []
    for code in sorted(discipline_by_code):
        title = title_by_code[code]
        for year in handbook_years:
            sources.append(
                {
                    "source_id": f"monash-{code.lower()}-{int(year)}",
                    "university_id": "monash",
                    "handbook_year": int(year),
                    "program_code": code,
                    "source_type": "program_handbook",
                    "title": f"{title} {code}",
                    "url": (
                        f"https://handbook.monash.edu/{int(year)}"
                        f"/courses/{code}"
                    ),
                    "expected_content_markers": [code, title],
                    "discipline_ids": [discipline_by_code[code]],
                }
            )
    return sources


def merge_monash_program_sources(
    manifest: dict[str, Any],
    generated_sources: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    merged = deepcopy(manifest)
    generated = list(generated_sources)
    generated_ids = {source["source_id"] for source in generated}
    retained = [
        source
        for source in merged.get("sources", [])
        if source["source_id"] not in generated_ids
    ]
    merged["sources"] = retained + generated
    merged["manifest_version"] = (
        f"{date.today().isoformat()}-monash-coursework-expansion-v1"
    )
    merged["scope"]["coverage"] = (
        "Monash common coursework programs expanded across five disciplines "
        "and three Handbook years; other universities remain representative "
        "samples."
    )
    merged["scope"]["notice"] = (
        "Program pages are indexed only after download and extraction checks. "
        "A catalog match alone does not count as ready coverage."
    )
    return merged


def coverage_summary(
    sources: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    selected = [
        source
        for source in sources
        if source.get("university_id") == "monash"
        and source.get("source_type") == "program_handbook"
    ]
    return {
        "programs": len(
            {source["program_code"] for source in selected}
        ),
        "program_versions": len(selected),
        "years": sorted(
            {source["handbook_year"] for source in selected}
        ),
        "by_discipline": {
            discipline: len(
                {
                    source["program_code"]
                    for source in selected
                    if discipline in source.get("discipline_ids", [])
                }
            )
            for discipline in MONASH_PROGRAM_SCOPE
        },
    }


def build_monash_unit_sources(
    program_documents: Iterable[tuple[dict[str, Any], str]],
) -> list[dict[str, Any]]:
    references: dict[tuple[int, str], dict[str, set[str]]] = {}
    for source, text in program_documents:
        if (
            source.get("university_id") != "monash"
            or source.get("source_type") != "program_handbook"
        ):
            continue
        year = int(source["handbook_year"])
        program_code = str(source["program_code"]).upper()
        disciplines = set(source.get("discipline_ids") or [])
        for unit_code in set(re.findall(r"\b[A-Z]{3}\d{4}\b", text)):
            record = references.setdefault(
                (year, unit_code),
                {"program_codes": set(), "discipline_ids": set()},
            )
            record["program_codes"].add(program_code)
            record["discipline_ids"].update(disciplines)

    sources: list[dict[str, Any]] = []
    for (year, unit_code), relation in sorted(references.items()):
        sources.append(
            {
                "source_id": (
                    f"monash-unit-{unit_code.lower()}-{year}"
                ),
                "university_id": "monash",
                "handbook_year": year,
                "source_type": "unit_handbook",
                "title": f"Monash Unit {unit_code}",
                "url": (
                    f"https://handbook.monash.edu/{year}"
                    f"/units/{unit_code}"
                ),
                "expected_content_markers": [unit_code],
                "discipline_ids": sorted(
                    relation["discipline_ids"]
                ),
                "related_program_codes": sorted(
                    relation["program_codes"]
                ),
            }
        )
    return sources


def merge_monash_unit_sources(
    manifest: dict[str, Any],
    unit_sources: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    merged = deepcopy(manifest)
    generated = list(unit_sources)
    retained = [
        source
        for source in merged.get("sources", [])
        if not source["source_id"].startswith("monash-unit-")
    ]
    merged["sources"] = retained + generated
    merged["manifest_version"] = (
        f"{date.today().isoformat()}-monash-program-unit-expansion-v1"
    )
    return merged
