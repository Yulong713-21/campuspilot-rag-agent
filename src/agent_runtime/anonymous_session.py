from __future__ import annotations

import hashlib
import secrets
import sqlite3
from threading import RLock
import time
import uuid


class AnonymousSessionRepository:
    """Issues restart-safe bearer tokens for the public demo workspace."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        ttl_seconds: int = 86_400,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.connection = connection
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS anonymous_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def issue(self) -> dict[str, str | int]:
        token = secrets.token_urlsafe(32)
        user_id = f"anonymous-{uuid.uuid4()}"
        expires_at = int(time.time()) + self.ttl_seconds
        with self._lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO anonymous_sessions(token_hash, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (self._hash(token), user_id, expires_at),
            )
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": self.ttl_seconds,
        }

    def resolve(self, token: str) -> str | None:
        if not token:
            return None
        now = int(time.time())
        with self._lock:
            row = self.connection.execute(
                """
                SELECT user_id, expires_at
                FROM anonymous_sessions
                WHERE token_hash = ?
                """,
                (self._hash(token),),
            ).fetchone()
            if row is None:
                return None
            if int(row[1]) <= now:
                with self.connection:
                    self.connection.execute(
                        "DELETE FROM anonymous_sessions WHERE token_hash = ?",
                        (self._hash(token),),
                    )
                return None
        return str(row[0])

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
