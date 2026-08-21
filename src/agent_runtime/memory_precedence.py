from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PreferenceSource = Literal[
    "current_turn",
    "thread",
    "long_term_memory",
    "product_default",
]


@dataclass(frozen=True)
class PreferenceCandidate:
    key: str
    value: str
    source: PreferenceSource

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.value.strip():
            raise ValueError("preference key and value must not be empty")


@dataclass(frozen=True)
class PreferenceResolution:
    selected: PreferenceCandidate
    ignored: list[PreferenceCandidate]


class MemoryPreferenceResolver:
    """Resolves preferences below non-overridable system and permission rules."""

    _PRIORITY = {
        "current_turn": 4,
        "thread": 3,
        "long_term_memory": 2,
        "product_default": 1,
    }

    def resolve(
        self,
        key: str,
        candidates: list[PreferenceCandidate],
    ) -> PreferenceResolution:
        matching = [candidate for candidate in candidates if candidate.key == key]
        if not matching:
            raise ValueError(f"no preference candidate found for key: {key}")

        ranked = sorted(
            enumerate(matching),
            key=lambda item: (-self._PRIORITY[item[1].source], item[0]),
        )
        selected = ranked[0][1]
        ignored = [candidate for _, candidate in ranked[1:]]
        return PreferenceResolution(
            selected=selected,
            ignored=ignored,
        )
