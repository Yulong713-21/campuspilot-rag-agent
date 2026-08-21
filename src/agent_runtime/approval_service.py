from __future__ import annotations

import sqlite3
from threading import RLock
from typing import Any

from .approval_workflow import LangGraphApprovalWorkflow


class ThreadNotFoundError(LookupError):
    pass


class ThreadConflictError(RuntimeError):
    pass


class ThreadOwnershipRepository:
    """Durable ownership boundary between authenticated users and threads."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._lock = RLock()
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_owners (
                    thread_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def claim_new(self, thread_id: str, user_id: str) -> None:
        self._validate(thread_id, user_id)
        with self._lock:
            try:
                with self.connection:
                    self.connection.execute(
                        """
                        INSERT INTO thread_owners(thread_id, user_id)
                        VALUES (?, ?)
                        """,
                        (thread_id, user_id),
                    )
            except sqlite3.IntegrityError as exc:
                raise ThreadConflictError("thread_id already exists") from exc

    def require_owner(self, thread_id: str, user_id: str) -> None:
        self._validate(thread_id, user_id)
        with self._lock:
            row = self.connection.execute(
                "SELECT user_id FROM thread_owners WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None or row[0] != user_id:
            raise ThreadNotFoundError("thread not found")

    def release(self, thread_id: str, user_id: str) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """
                DELETE FROM thread_owners
                WHERE thread_id = ? AND user_id = ?
                """,
                (thread_id, user_id),
            )

    @staticmethod
    def _validate(thread_id: str, user_id: str) -> None:
        if not thread_id.strip() or not user_id.strip():
            raise ValueError("thread_id and user_id must not be empty")


class ApprovalService:
    """Coordinates durable ownership checks and the approval workflow."""

    def __init__(
        self,
        workflow: LangGraphApprovalWorkflow,
        owners: ThreadOwnershipRepository,
    ) -> None:
        self.workflow = workflow
        self.owners = owners
        self._lock = RLock()

    def start(
        self,
        *,
        thread_id: str,
        user_id: str,
        action: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            self.owners.claim_new(thread_id, user_id)
            try:
                return self.workflow.start(thread_id, action)
            except Exception:
                self.owners.release(thread_id, user_id)
                raise

    def get(self, *, thread_id: str, user_id: str) -> dict[str, Any]:
        self.owners.require_owner(thread_id, user_id)
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = self.workflow.graph.get_state(config)
        if not snapshot.values.get("action"):
            raise ThreadNotFoundError("thread not found")
        return {
            "thread_id": thread_id,
            "status": snapshot.values.get("status"),
            "action": snapshot.values.get("action"),
            "execution_count": snapshot.values.get("execution_count", 0),
            "next_nodes": list(snapshot.next),
            "has_pending_interrupt": any(
                task.interrupts for task in snapshot.tasks
            ),
            "trace": snapshot.values.get("trace", []),
        }

    def resume(
        self,
        *,
        thread_id: str,
        user_id: str,
        approved: bool,
    ) -> dict[str, Any]:
        with self._lock:
            self.owners.require_owner(thread_id, user_id)
            try:
                return self.workflow.resume(thread_id, approved)
            except ValueError as exc:
                raise ThreadConflictError(str(exc)) from exc
