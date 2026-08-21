from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_store
from langgraph.graph import END, StateGraph
from langgraph.store.memory import InMemoryStore


class MemoryWorkflowState(TypedDict, total=False):
    current_message: str
    thread_messages: list[str]
    remembered_preference: str | None
    thread_message_count: int
    response: str


class LangGraphMemoryWorkflow:
    """Demonstrates thread-scoped state and user-scoped long-term memory."""

    def __init__(
        self,
        checkpointer: Any | None = None,
        store: Any | None = None,
    ) -> None:
        self.checkpointer = checkpointer or MemorySaver()
        self.store = store or InMemoryStore()
        self._thread_owners: dict[str, str] = {}
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(MemoryWorkflowState)
        workflow.add_node("respond_with_memory", self._respond_with_memory)
        workflow.set_entry_point("respond_with_memory")
        workflow.add_edge("respond_with_memory", END)
        return workflow.compile(
            checkpointer=self.checkpointer,
            store=self.store,
        )

    def save_preference(
        self,
        user_id: str,
        preference_key: str,
        value: str,
    ) -> None:
        if not user_id.strip() or not preference_key.strip() or not value.strip():
            raise ValueError("user_id, preference_key and value must not be empty")
        self.store.put(
            (user_id, "preferences"),
            preference_key,
            {"value": value},
        )

    def invoke(
        self,
        thread_id: str,
        user_id: str,
        message: str,
    ) -> dict[str, Any]:
        if not thread_id.strip() or not user_id.strip() or not message.strip():
            raise ValueError("thread_id, user_id and message must not be empty")
        self._bind_thread_owner(thread_id, user_id)
        return self.graph.invoke(
            {"current_message": message},
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "user_id": user_id,
                }
            },
        )

    def _bind_thread_owner(self, thread_id: str, user_id: str) -> None:
        existing_owner = self._thread_owners.get(thread_id)
        if existing_owner is not None and existing_owner != user_id:
            raise PermissionError("thread_id belongs to another user")
        self._thread_owners[thread_id] = user_id

    def _respond_with_memory(
        self,
        state: MemoryWorkflowState,
        config: dict[str, Any],
    ) -> MemoryWorkflowState:
        user_id = str(config["configurable"]["user_id"])
        store = get_store()
        preference_item = store.get(
            (user_id, "preferences"),
            "answer_style",
        )
        preference = (
            None
            if preference_item is None
            else str(preference_item.value.get("value", "")).strip() or None
        )
        messages = [
            *state.get("thread_messages", []),
            state["current_message"],
        ]
        return {
            "thread_messages": messages,
            "remembered_preference": preference,
            "thread_message_count": len(messages),
            "response": (
                f"已按偏好“{preference}”处理当前问题。"
                if preference
                else "当前没有保存的回答偏好。"
            ),
        }
