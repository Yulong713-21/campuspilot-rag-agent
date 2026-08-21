from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


DEFAULT_FAQ_PATH = Path(__file__).resolve().parents[2] / "data" / "campuspilot_faq.json"


class CampusPilotFaqService:
    """High-precision FAQ matching for stable CampusPilot terminology."""

    DIRECT_ANSWER_FAQ_IDS = {
        "monash-entry-level",
        "unit-vs-course",
        "handbook-year",
        "go8-definition",
        "credit-points",
        "prerequisite",
    }

    def __init__(self, path: str | Path = DEFAULT_FAQ_PATH) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.entries = payload["entries"]
        self._aliases = {
            self._normalize(alias): entry
            for entry in self.entries
            for alias in entry["aliases"]
        }
        self.entry_count = len(self.entries)
        self.question_count = len(self._aliases)

    def search(self, query: str) -> dict[str, Any]:
        entry = self._aliases.get(self._normalize(query))
        if entry is None or entry["faq_id"] not in self.DIRECT_ANSWER_FAQ_IDS:
            return {
                "tool": "search_faq",
                "ok": True,
                "hit": False,
                "data": {
                    "hit": False,
                    "exact_candidate": entry["faq_id"] if entry else None,
                    "route_reason": (
                        "exact_match_requires_agent" if entry else "no_exact_match"
                    ),
                },
                "error": None,
            }
        return {
            "tool": "search_faq",
            "ok": True,
            "hit": True,
            "data": {
                "hit": True,
                "faq_id": entry["faq_id"],
                "answer": entry["answer"],
                "source_title": entry["source_title"],
                "source_url": entry["source_url"],
                "score": 1.0,
            },
            "error": None,
        }

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())
