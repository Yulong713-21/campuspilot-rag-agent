from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


MemorySource = Literal["user", "retrieved_content", "model_inference"]
MemoryScope = Literal["current_turn", "thread", "cross_thread"]
MemoryAction = Literal[
    "persist_long_term",
    "keep_in_thread_state",
    "require_user_confirmation",
    "reject",
]


@dataclass(frozen=True)
class MemoryCandidate:
    key: str
    value: str
    source: MemorySource
    scope: MemoryScope
    explicit: bool
    confidence: float = 1.0
    sensitive: bool = False

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.value.strip():
            raise ValueError("memory key and value must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class MemoryWriteDecision:
    action: MemoryAction
    reason: str
    candidate: MemoryCandidate


class MemoryWritePolicy:
    """Decides whether a memory candidate may cross the thread boundary."""

    def decide(self, candidate: MemoryCandidate) -> MemoryWriteDecision:
        if candidate.sensitive:
            return MemoryWriteDecision(
                action="reject",
                reason="sensitive_information_must_not_be_saved",
                candidate=candidate,
            )

        if candidate.source == "retrieved_content":
            return MemoryWriteDecision(
                action="reject",
                reason="retrieved_content_cannot_define_user_memory",
                candidate=candidate,
            )

        if candidate.scope in {"current_turn", "thread"}:
            return MemoryWriteDecision(
                action="keep_in_thread_state",
                reason="temporary_preference_does_not_cross_threads",
                candidate=candidate,
            )

        if candidate.source == "model_inference":
            return MemoryWriteDecision(
                action="require_user_confirmation",
                reason="model_inference_is_not_an_explicit_user_fact",
                candidate=candidate,
            )

        if candidate.source == "user" and candidate.explicit:
            return MemoryWriteDecision(
                action="persist_long_term",
                reason="explicit_user_preference_for_future_threads",
                candidate=candidate,
            )

        return MemoryWriteDecision(
            action="require_user_confirmation",
            reason="cross_thread_memory_requires_explicit_confirmation",
            candidate=candidate,
        )
