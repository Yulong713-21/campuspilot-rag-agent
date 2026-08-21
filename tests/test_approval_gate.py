from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.approval_gate import ToolApprovalGate


class ToolApprovalGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = ToolApprovalGate()

    def test_automatically_approves_read_only_search(self) -> None:
        decision = self.gate.evaluate(
            "search_rag",
            {"query": "课程有哪些阶段？", "source_filter": "ai"},
        )

        self.assertEqual(decision.mode, "automatic")
        self.assertTrue(self.gate.is_approved(decision))

    def test_requires_human_approval_for_sending_email(self) -> None:
        decision = self.gate.evaluate(
            "send_email",
            {
                "recipients": ["student@example.com"],
                "subject": "课程通知",
            },
        )

        self.assertEqual(decision.mode, "human_required")
        self.assertFalse(self.gate.is_approved(decision))
        self.assertTrue(
            self.gate.is_approved(
                decision,
                approved_action_digest=decision.action_digest,
            )
        )

    def test_changed_arguments_invalidate_previous_approval(self) -> None:
        original = self.gate.evaluate(
            "send_email",
            {
                "recipients": ["student@example.com"],
                "subject": "课程通知",
            },
        )
        changed = self.gate.evaluate(
            "send_email",
            {
                "recipients": ["all-students@example.com"],
                "subject": "课程通知",
            },
        )

        self.assertNotEqual(original.action_digest, changed.action_digest)
        self.assertFalse(
            self.gate.is_approved(
                changed,
                approved_action_digest=original.action_digest,
            )
        )

    def test_denies_dangerous_and_unknown_tools(self) -> None:
        dangerous = self.gate.evaluate("delete_database", {})
        unknown = self.gate.evaluate("run_any_command", {"command": "whoami"})

        self.assertEqual(dangerous.mode, "denied")
        self.assertEqual(unknown.mode, "denied")
        self.assertFalse(self.gate.is_approved(dangerous))
        self.assertFalse(self.gate.is_approved(unknown))


if __name__ == "__main__":
    unittest.main()
