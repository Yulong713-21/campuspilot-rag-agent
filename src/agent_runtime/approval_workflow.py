from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt


class ApprovalWorkflowState(TypedDict, total=False):
    action: dict[str, Any]
    approved: bool
    status: Literal["pending", "executed", "rejected"]
    execution_count: int
    trace: list[dict[str, Any]]


class LangGraphApprovalWorkflow:
    """Pause/resume workflow for a side-effect action awaiting human approval."""

    def __init__(self, checkpointer: Any | None = None) -> None:
        self.checkpointer = checkpointer or MemorySaver()
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(ApprovalWorkflowState)
        workflow.add_node("review_action", self._review_action)
        workflow.add_node("execute_action", self._execute_action)
        workflow.add_node("reject_action", self._reject_action)
        workflow.set_entry_point("review_action")
        workflow.add_conditional_edges(
            "review_action",
            self._route_after_review,
            {
                "approved": "execute_action",
                "rejected": "reject_action",
            },
        )
        workflow.add_edge("execute_action", END)
        workflow.add_edge("reject_action", END)
        return workflow.compile(checkpointer=self.checkpointer)

    def _review_action(
        self,
        state: ApprovalWorkflowState,
    ) -> ApprovalWorkflowState:
        approved = bool(
            interrupt(
                {
                    "question": "是否批准执行该动作？",
                    "action": state["action"],
                }
            )
        )
        return {
            "approved": approved,
            "trace": [
                *state.get("trace", []),
                {
                    "stage": "human_review",
                    "approved": approved,
                },
            ],
        }

    def _route_after_review(
        self,
        state: ApprovalWorkflowState,
    ) -> Literal["approved", "rejected"]:
        return "approved" if state.get("approved") else "rejected"

    def _execute_action(
        self,
        state: ApprovalWorkflowState,
    ) -> ApprovalWorkflowState:
        return {
            "status": "executed",
            "execution_count": state.get("execution_count", 0) + 1,
            "trace": [
                *state.get("trace", []),
                {
                    "stage": "execute_action",
                    "action": state["action"],
                },
            ],
        }

    def _reject_action(
        self,
        state: ApprovalWorkflowState,
    ) -> ApprovalWorkflowState:
        return {
            "status": "rejected",
            "trace": [
                *state.get("trace", []),
                {
                    "stage": "reject_action",
                    "action": state["action"],
                },
            ],
        }

    def start(
        self,
        thread_id: str,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        config = self._config(thread_id)
        events = list(
            self.graph.stream(
                {
                    "action": action,
                    "status": "pending",
                    "execution_count": 0,
                    "trace": [],
                },
                config=config,
            )
        )
        snapshot = self.graph.get_state(config)
        interrupt_payloads = [
            item.value
            for event in events
            for item in event.get("__interrupt__", ())
        ]
        return {
            "thread_id": thread_id,
            "status": snapshot.values.get("status"),
            "execution_count": snapshot.values.get("execution_count", 0),
            "next_nodes": list(snapshot.next),
            "interrupts": interrupt_payloads,
            "trace": snapshot.values.get("trace", []),
        }

    def resume(self, thread_id: str, approved: bool) -> dict[str, Any]:
        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        has_pending_interrupt = any(
            task.interrupts for task in snapshot.tasks
        )
        if not snapshot.values.get("action") or not has_pending_interrupt:
            raise ValueError("thread has no pending approval")

        state = self.graph.invoke(
            Command(resume=approved),
            config=config,
        )
        return {
            "thread_id": thread_id,
            "status": state.get("status"),
            "approved": state.get("approved"),
            "execution_count": state.get("execution_count", 0),
            "next_nodes": list(self.graph.get_state(config).next),
            "trace": state.get("trace", []),
        }

    def _config(self, thread_id: str) -> dict[str, dict[str, str]]:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty")
        return {"configurable": {"thread_id": thread_id}}
