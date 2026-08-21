from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


MemoryOrigin = Literal["explicit_user", "model_inference"]
MemoryStatus = Literal["active", "superseded"]
ConsolidationAction = Literal[
    "created",
    "superseded",
    "duplicate_ignored",
    "require_confirmation",
]


@dataclass(frozen=True)
class VersionedMemory:
    memory_id: str
    user_id: str
    key: str
    value: str
    origin: MemoryOrigin
    version: int
    status: MemoryStatus = "active"
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("memory_id", "user_id", "key", "value"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.version <= 0:
            raise ValueError("version must be greater than 0")


@dataclass(frozen=True)
class MemoryUpdate:
    memory_id: str
    user_id: str
    key: str
    value: str
    origin: MemoryOrigin


@dataclass(frozen=True)
class ConsolidationResult:
    action: ConsolidationAction
    reason: str
    active_memory: VersionedMemory | None
    memories: list[VersionedMemory]


class MemoryConsolidator:
    """Resolves duplicate or conflicting writes while preserving history."""

    def consolidate(
        self,
        memories: list[VersionedMemory],
        update: MemoryUpdate,
    ) -> ConsolidationResult:
        active = self._find_active(memories, update.user_id, update.key)

        if active is None:
            created = VersionedMemory(
                memory_id=update.memory_id,
                user_id=update.user_id,
                key=update.key,
                value=update.value,
                origin=update.origin,
                version=1,
            )
            return ConsolidationResult(
                action="created",
                reason="no_active_memory_for_key",
                active_memory=created,
                memories=[*memories, created],
            )

        if active.value == update.value:
            return ConsolidationResult(
                action="duplicate_ignored",
                reason="same_value_already_active",
                active_memory=active,
                memories=list(memories),
            )

        if update.origin == "model_inference":
            return ConsolidationResult(
                action="require_confirmation",
                reason="inference_cannot_override_active_memory",
                active_memory=active,
                memories=list(memories),
            )

        replacement = VersionedMemory(
            memory_id=update.memory_id,
            user_id=update.user_id,
            key=update.key,
            value=update.value,
            origin=update.origin,
            version=active.version + 1,
        )
        updated_memories = [
            replace(
                memory,
                status="superseded",
                superseded_by=replacement.memory_id,
            )
            if memory.memory_id == active.memory_id
            else memory
            for memory in memories
        ]
        updated_memories.append(replacement)
        return ConsolidationResult(
            action="superseded",
            reason="new_explicit_user_value_replaces_old_value",
            active_memory=replacement,
            memories=updated_memories,
        )

    @staticmethod
    def _find_active(
        memories: list[VersionedMemory],
        user_id: str,
        key: str,
    ) -> VersionedMemory | None:
        matches = [
            memory
            for memory in memories
            if memory.user_id == user_id
            and memory.key == key
            and memory.status == "active"
        ]
        if len(matches) > 1:
            raise ValueError("multiple active memories found for the same user and key")
        return matches[0] if matches else None
