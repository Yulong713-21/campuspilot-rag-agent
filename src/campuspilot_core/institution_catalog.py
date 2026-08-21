from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import unicodedata
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INSTITUTION_CATALOG = (
    REPO_ROOT / "data/admissions/institution_catalog_2026.json"
)


class InstitutionCatalog:
    """Versioned institution master data with deterministic alias search."""

    def __init__(
        self,
        catalog_path: str | Path = DEFAULT_INSTITUTION_CATALOG,
    ) -> None:
        self.data = json.loads(
            Path(catalog_path).read_text(encoding="utf-8")
        )
        self.institutions: list[dict[str, Any]] = self.data["institutions"]

    def search(
        self,
        query: str,
        *,
        country_code: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized_query = self._normalize(query)
        country = country_code.upper() if country_code else None
        if country not in {None, "CN", "AU"}:
            raise ValueError("country_code must be CN or AU")
        if not normalized_query:
            return self._result(query, country, [], limit)

        scored: list[tuple[float, int, dict[str, Any], str]] = []
        for institution in self.institutions:
            if country and institution["country_code"] != country:
                continue
            match = self._score(institution, normalized_query)
            if match is None:
                continue
            score, match_type = match
            scored.append(
                (
                    score,
                    1 if institution.get("active") else 0,
                    institution,
                    match_type,
                )
            )
        scored.sort(
            key=lambda item: (
                item[0],
                item[1],
                -len(item[2]["official_name"]),
            ),
            reverse=True,
        )
        if scored and scored[0][0] == 1.0:
            scored = [item for item in scored if item[0] >= 0.9]
        matches = [
            {
                **institution,
                "match_type": match_type,
                "match_score": round(score, 4),
            }
            for score, _, institution, match_type in scored[:limit]
        ]
        return self._result(query, country, matches, limit)

    def _result(
        self,
        query: str,
        country: str | None,
        matches: list[dict[str, Any]],
        limit: int,
    ) -> dict[str, Any]:
        return {
            "query": query,
            "country_code": country,
            "matches": matches,
            "count": len(matches),
            "limit": limit,
            "catalog_version": self.data["catalog_version"],
            "as_of_date": self.data["as_of_date"],
            "coverage": self.data["coverage"],
            "catalog_counts": self.data["counts"],
            "allow_custom_entry": True,
            "next_action": (
                "select_verified_institution"
                if matches
                else "accept_custom_institution_for_manual_verification"
            ),
        }

    def _score(
        self,
        institution: dict[str, Any],
        query: str,
    ) -> tuple[float, str] | None:
        names = [
            institution.get("official_name"),
            institution.get("display_name"),
            institution.get("english_name"),
            *institution.get("aliases", []),
        ]
        normalized_names = {
            self._normalize(name)
            for name in names
            if isinstance(name, str) and name.strip()
        }
        if query in normalized_names:
            return 1.0, "exact_or_alias"
        if any(name.startswith(query) for name in normalized_names):
            return 0.93, "prefix"
        if any(query in name for name in normalized_names):
            return 0.86, "contains"
        if len(query) < 3:
            return None
        ratio = max(
            SequenceMatcher(None, query, name).ratio()
            for name in normalized_names
        )
        threshold = 0.68 if re.search(r"[\u4e00-\u9fff]", query) else 0.62
        if ratio >= threshold:
            return ratio * 0.8, "fuzzy"
        return None

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(value)).casefold()
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalized)
