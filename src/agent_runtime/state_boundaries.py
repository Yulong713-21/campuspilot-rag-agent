from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StateProjections:
    checkpoint: dict[str, Any]
    prompt_context: dict[str, Any]
    trace_record: dict[str, Any]
    long_term_memory_writes: list[dict[str, Any]]


class AgentStateProjector:
    """Projects one execution state into explicitly scoped data planes."""

    _CHECKPOINT_FIELDS = (
        "request_id",
        "user_id",
        "thread_id",
        "original_query",
        "effective_query",
        "source_filter",
        "retry_count",
        "documents",
        "selected_memories",
        "memory_policy",
        "answer",
        "answer_source",
        "confidence",
        "evaluation",
        "next_action",
        "route_reason",
    )

    def project(self, state: Mapping[str, Any]) -> StateProjections:
        self._validate_identity(state)
        return StateProjections(
            checkpoint={
                field: state[field]
                for field in self._CHECKPOINT_FIELDS
                if field in state
            },
            prompt_context=self._project_prompt_context(state),
            trace_record=self._project_trace(state),
            # Execution state alone never authorizes a cross-thread memory write.
            long_term_memory_writes=[],
        )

    @staticmethod
    def _validate_identity(state: Mapping[str, Any]) -> None:
        for field in ("request_id", "user_id", "thread_id"):
            value = state.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")

    @staticmethod
    def _project_prompt_context(state: Mapping[str, Any]) -> dict[str, Any]:
        documents = [
            {
                "content": document.get("content", ""),
                "source": document.get("source"),
            }
            for document in state.get("documents", [])
        ]
        memories = []
        for memory in state.get("selected_memories", []):
            if memory.get("status", "active") != "active":
                continue
            if "key" in memory or "value" in memory:
                memories.append(
                    {
                        "key": memory.get("key"),
                        "value": memory.get("value"),
                    }
                )
            else:
                memories.append(
                    {
                        "memory_id": memory.get("memory_id"),
                        "content": memory.get("content"),
                    }
                )
        return {
            "query": state.get("effective_query") or state.get("original_query"),
            "documents": documents,
            "memories": memories,
        }

    @staticmethod
    def _project_trace(state: Mapping[str, Any]) -> dict[str, Any]:
        tool_events = []
        for event in state.get("trace", []):
            data = event.get("data", {})
            tool_events.append(
                {
                    "tool": event.get("tool"),
                    "ok": event.get("ok"),
                    "error_type": event.get("error_type"),
                    "retryable": event.get("retryable", False),
                    "hit": data.get("hit"),
                    "count": data.get("count"),
                }
            )

        return {
            "request_id": state["request_id"],
            "thread_id": state["thread_id"],
            "route_reason": state.get("route_reason"),
            "answer_source": state.get("answer_source"),
            "confidence": state.get("confidence"),
            "retry_count": state.get("retry_count", 0),
            "next_action": state.get("next_action"),
            "tool_events": tool_events,
        }
