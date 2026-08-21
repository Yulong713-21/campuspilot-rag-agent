from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.idempotent_action import SimulatedEmailProvider


class IdempotentActionTest(unittest.TestCase):
    def test_repeated_send_without_key_delivers_twice(self) -> None:
        provider = SimulatedEmailProvider(sqlite3.connect(":memory:"))

        first = provider.send_without_idempotency(
            recipient="student@example.com",
            subject="课程通知",
        )
        second = provider.send_without_idempotency(
            recipient="student@example.com",
            subject="课程通知",
        )

        self.assertTrue(first.delivered)
        self.assertTrue(second.delivered)
        self.assertEqual(provider.delivery_count(), 2)

    def test_repeated_send_with_same_key_delivers_once(self) -> None:
        provider = SimulatedEmailProvider(sqlite3.connect(":memory:"))

        first = provider.send_with_idempotency(
            operation_id="email:course-notice:student-001",
            recipient="student@example.com",
            subject="课程通知",
        )
        second = provider.send_with_idempotency(
            operation_id="email:course-notice:student-001",
            recipient="student@example.com",
            subject="课程通知",
        )

        self.assertTrue(first.delivered)
        self.assertFalse(first.duplicate_suppressed)
        self.assertFalse(second.delivered)
        self.assertTrue(second.duplicate_suppressed)
        self.assertEqual(provider.delivery_count(), 1)

    def test_same_key_with_different_recipient_is_rejected(self) -> None:
        provider = SimulatedEmailProvider(sqlite3.connect(":memory:"))
        provider.send_with_idempotency(
            operation_id="email:course-notice:student-001",
            recipient="student-001@example.com",
            subject="课程通知",
        )

        with self.assertRaisesRegex(ValueError, "different payload"):
            provider.send_with_idempotency(
                operation_id="email:course-notice:student-001",
                recipient="student-002@example.com",
                subject="课程通知",
            )

        self.assertEqual(provider.delivery_count(), 1)


if __name__ == "__main__":
    unittest.main()
