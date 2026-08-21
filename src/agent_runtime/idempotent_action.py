from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DeliveryResult:
    operation_id: str | None
    delivered: bool
    duplicate_suppressed: bool

    def to_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


class SimulatedEmailProvider:
    """Models an external provider that can deduplicate an idempotency key."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_deliveries (
                delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT UNIQUE,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def send_without_idempotency(
        self,
        *,
        recipient: str,
        subject: str,
    ) -> DeliveryResult:
        self._validate(recipient, subject)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO email_deliveries(operation_id, recipient, subject)
                VALUES (NULL, ?, ?)
                """,
                (recipient, subject),
            )
        return DeliveryResult(
            operation_id=None,
            delivered=True,
            duplicate_suppressed=False,
        )

    def send_with_idempotency(
        self,
        *,
        operation_id: str,
        recipient: str,
        subject: str,
    ) -> DeliveryResult:
        if not operation_id.strip():
            raise ValueError("operation_id must not be empty")
        self._validate(recipient, subject)
        try:
            with self.connection:
                self.connection.execute(
                    """
                    INSERT INTO email_deliveries(operation_id, recipient, subject)
                    VALUES (?, ?, ?)
                    """,
                    (operation_id, recipient, subject),
                )
        except sqlite3.IntegrityError:
            existing = self.connection.execute(
                """
                SELECT recipient, subject
                FROM email_deliveries
                WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            if existing != (recipient, subject):
                raise ValueError(
                    "operation_id was reused with a different payload"
                )
            return DeliveryResult(
                operation_id=operation_id,
                delivered=False,
                duplicate_suppressed=True,
            )
        return DeliveryResult(
            operation_id=operation_id,
            delivered=True,
            duplicate_suppressed=False,
        )

    def delivery_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM email_deliveries"
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _validate(recipient: str, subject: str) -> None:
        if not recipient.strip() or not subject.strip():
            raise ValueError("recipient and subject must not be empty")
