from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from langgraph.checkpoint.sqlite import SqliteSaver


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.approval_workflow import LangGraphApprovalWorkflow


class SqliteCheckpointRecoveryTest(unittest.TestCase):
    def test_new_workflow_instance_resumes_pending_approval(self) -> None:
        action = {
            "tool_name": "send_email",
            "arguments": {
                "recipients": ["all-students@example.com"],
                "subject": "课程通知",
            },
        }

        with TemporaryDirectory() as temp_dir:
            database = str(Path(temp_dir) / "checkpoints.sqlite3")

            with SqliteSaver.from_conn_string(database) as first_saver:
                first_process = LangGraphApprovalWorkflow(
                    checkpointer=first_saver
                )
                paused = first_process.start("persistent-thread", action)
                self.assertEqual(paused["status"], "pending")
                self.assertEqual(paused["next_nodes"], ["review_action"])

            with SqliteSaver.from_conn_string(database) as second_saver:
                second_process = LangGraphApprovalWorkflow(
                    checkpointer=second_saver
                )
                resumed = second_process.resume(
                    "persistent-thread",
                    approved=True,
                )

            self.assertEqual(resumed["status"], "executed")
            self.assertEqual(resumed["execution_count"], 1)
            self.assertEqual(resumed["next_nodes"], [])
            self.assertEqual(
                [step["stage"] for step in resumed["trace"]],
                ["human_review", "execute_action"],
            )


if __name__ == "__main__":
    unittest.main()
