from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


TERMINOLOGY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "australian_higher_education_terms.json"
)


class AustralianTerminologyGlossary:
    """Small lexical retriever for high-value Australian study terms."""

    def __init__(self, path: str | Path = TERMINOLOGY_PATH) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.dataset_version = payload["dataset_version"]
        self.terms = payload["terms"]

    def search(self, text: str, *, k: int = 5) -> list[dict[str, Any]]:
        normalized = text.casefold()
        tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", normalized))
        scored = []
        for item in self.terms:
            phrases = [item["term"], *item.get("aliases", [])]
            score = 0
            for phrase in phrases:
                candidate = phrase.casefold()
                if candidate in normalized:
                    score += 4
                candidate_tokens = set(
                    re.findall(
                        r"[a-z0-9]+|[\u4e00-\u9fff]+",
                        candidate,
                    )
                )
                score += len(tokens & candidate_tokens)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["term_id"]))
        return [
            {
                **item,
                "score": score,
                "dataset_version": self.dataset_version,
            }
            for score, item in scored[:k]
        ]

    def prompt_context(self, text: str, *, k: int = 5) -> list[dict[str, str]]:
        return [
            {
                "term": item["term"],
                "definition": item["definition"],
                "common_mistake": item["common_mistake"],
                "planning_implication": item["planning_implication"],
            }
            for item in self.search(text, k=k)
        ]
