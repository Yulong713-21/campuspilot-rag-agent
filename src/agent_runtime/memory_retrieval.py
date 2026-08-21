from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    content: str
    estimated_tokens: int
    relevance: float
    importance: float
    confidence: float
    recency: float
    scope_active: bool = True
    trusted: bool = True
    sensitive: bool = False

    def __post_init__(self) -> None:
        if not self.memory_id.strip() or not self.content.strip():
            raise ValueError("memory_id and content must not be empty")
        if self.estimated_tokens <= 0:
            raise ValueError("estimated_tokens must be greater than 0")
        for field_name in ("relevance", "importance", "confidence", "recency"):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0 and 1")


@dataclass(frozen=True)
class RankedMemory:
    record: MemoryRecord
    score: float


@dataclass(frozen=True)
class DroppedMemory:
    memory_id: str
    reason: str


@dataclass(frozen=True)
class MemoryRetrievalResult:
    selected: list[RankedMemory]
    dropped: list[DroppedMemory]
    token_budget: int
    used_tokens: int
    remaining_tokens: int


class MemoryRetriever:
    """Filters, ranks, and packs long-term memories for the current request."""

    def __init__(self, minimum_relevance: float = 0.2) -> None:
        if not 0.0 <= minimum_relevance <= 1.0:
            raise ValueError("minimum_relevance must be between 0 and 1")
        self.minimum_relevance = minimum_relevance

    def retrieve(
        self,
        memories: list[MemoryRecord],
        token_budget: int,
    ) -> MemoryRetrievalResult:
        if token_budget < 0:
            raise ValueError("token_budget must be at least 0")

        eligible: list[RankedMemory] = []
        dropped: list[DroppedMemory] = []

        for memory in memories:
            rejection_reason = self._rejection_reason(memory)
            if rejection_reason:
                dropped.append(
                    DroppedMemory(
                        memory_id=memory.memory_id,
                        reason=rejection_reason,
                    )
                )
                continue
            eligible.append(
                RankedMemory(
                    record=memory,
                    score=self._score(memory),
                )
            )

        ranked = sorted(
            enumerate(eligible),
            key=lambda item: (-item[1].score, item[0]),
        )
        selected: list[RankedMemory] = []
        used_tokens = 0

        for _, memory in ranked:
            if used_tokens + memory.record.estimated_tokens <= token_budget:
                selected.append(memory)
                used_tokens += memory.record.estimated_tokens
            else:
                dropped.append(
                    DroppedMemory(
                        memory_id=memory.record.memory_id,
                        reason="token_budget_exceeded",
                    )
                )

        return MemoryRetrievalResult(
            selected=selected,
            dropped=dropped,
            token_budget=token_budget,
            used_tokens=used_tokens,
            remaining_tokens=token_budget - used_tokens,
        )

    def _rejection_reason(self, memory: MemoryRecord) -> str | None:
        if not memory.scope_active:
            return "scope_expired"
        if not memory.trusted:
            return "untrusted_source"
        if memory.sensitive:
            return "sensitive_memory"
        if memory.relevance < self.minimum_relevance:
            return "below_relevance_threshold"
        return None

    def _score(self, memory: MemoryRecord) -> float:
        score = (
            0.6 * memory.relevance
            + 0.2 * memory.importance
            + 0.1 * memory.confidence
            + 0.1 * memory.recency
        )
        return round(score, 4)
