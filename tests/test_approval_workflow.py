from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.approval_workflow import LangGraphApprovalWorkflow


class LangGraphApprovalWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = LangGraphApprovalWorkflow()
        self.action = {
            "tool_name": "send_email",
            "arguments": {
                "recipients": ["all-students@example.com"],
                "subject": "课程通知",
            },
        }

    def test_pauses_before_executing_side_effect(self) -> None:
        paused = self.workflow.start("approval-1", self.action)

        self.assertEqual(paused["status"], "pending")
        self.assertEqual(paused["execution_count"], 0)
        self.assertEqual(paused["next_nodes"], ["review_action"])
        self.assertEqual(paused["interrupts"][0]["action"], self.action)
        self.assertEqual(paused["trace"], [])

    def test_resumes_same_thread_and_executes_after_approval(self) -> None:
        self.workflow.start("approval-2", self.action)

        resumed = self.workflow.resume("approval-2", approved=True)

        self.assertEqual(resumed["status"], "executed")
        self.assertTrue(resumed["approved"])
        self.assertEqual(resumed["execution_count"], 1)
        self.assertEqual(resumed["next_nodes"], [])
        self.assertEqual(
            [step["stage"] for step in resumed["trace"]],
            ["human_review", "execute_action"],
        )

    def test_rejection_finishes_without_execution(self) -> None:
        self.workflow.start("approval-3", self.action)

        resumed = self.workflow.resume("approval-3", approved=False)

        self.assertEqual(resumed["status"], "rejected")
        self.assertFalse(resumed["approved"])
        self.assertEqual(resumed["execution_count"], 0)
        self.assertEqual(
            [step["stage"] for step in resumed["trace"]],
            ["human_review", "reject_action"],
        )

    def test_wrong_or_completed_thread_cannot_resume(self) -> None:
        with self.assertRaisesRegex(ValueError, "no pending approval"):
            self.workflow.resume("unknown-thread", approved=True)

        self.workflow.start("approval-4", self.action)
        self.workflow.resume("approval-4", approved=True)

        with self.assertRaisesRegex(ValueError, "no pending approval"):
            self.workflow.resume("approval-4", approved=True)


if __name__ == "__main__":
    unittest.main()
