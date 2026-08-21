from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextDocument:
    document_id: str
    content: str
    relevance_score: float
    estimated_tokens: int
    source: str | None = None

    def __post_init__(self) -> None:
        if self.estimated_tokens <= 0:
            raise ValueError("estimated_tokens must be greater than 0")


@dataclass(frozen=True)
class ContextPackingResult:
    selected: list[ContextDocument]
    dropped: list[ContextDocument]
    token_budget: int
    used_tokens: int
    remaining_tokens: int


class ContextBudgetPacker:
    """Greedily packs reranked documents without splitting document boundaries."""

    def pack(
        self,
        documents: list[ContextDocument],
        token_budget: int,
    ) -> ContextPackingResult:
        if token_budget < 0:
            raise ValueError("token_budget must be at least 0")

        ranked_documents = sorted(
            enumerate(documents),
            key=lambda item: (-item[1].relevance_score, item[0]),
        )
        selected: list[ContextDocument] = []
        dropped: list[ContextDocument] = []
        used_tokens = 0

        for _, document in ranked_documents:
            if used_tokens + document.estimated_tokens <= token_budget:
                selected.append(document)
                used_tokens += document.estimated_tokens
            else:
                dropped.append(document)

        return ContextPackingResult(
            selected=selected,
            dropped=dropped,
            token_budget=token_budget,
            used_tokens=used_tokens,
            remaining_tokens=token_budget - used_tokens,
        )
