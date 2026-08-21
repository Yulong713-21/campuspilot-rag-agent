from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_workflow import LangGraphMemoryWorkflow


class LangGraphMemoryWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = LangGraphMemoryWorkflow()
        self.workflow.save_preference(
            "user-1",
            "answer_style",
            "先讲原理，再展示实验",
        )

    def test_same_thread_retains_short_term_messages(self) -> None:
        first = self.workflow.invoke("thread-a", "user-1", "Deadline 是什么？")
        second = self.workflow.invoke("thread-a", "user-1", "它和 Timeout 有什么区别？")

        self.assertEqual(first["thread_message_count"], 1)
        self.assertEqual(second["thread_message_count"], 2)
        self.assertEqual(
            second["thread_messages"],
            ["Deadline 是什么？", "它和 Timeout 有什么区别？"],
        )

    def test_new_thread_has_new_history_but_same_user_preference(self) -> None:
        self.workflow.invoke("thread-a", "user-1", "Deadline 是什么？")

        new_thread = self.workflow.invoke("thread-b", "user-1", "继续学习")

        self.assertEqual(new_thread["thread_message_count"], 1)
        self.assertEqual(
            new_thread["remembered_preference"],
            "先讲原理，再展示实验",
        )

    def test_different_user_does_not_receive_preference(self) -> None:
        result = self.workflow.invoke("thread-c", "user-2", "继续学习")

        self.assertIsNone(result["remembered_preference"])
        self.assertEqual(result["response"], "当前没有保存的回答偏好。")

    def test_thread_cannot_be_reused_by_another_user(self) -> None:
        self.workflow.invoke("thread-secure", "user-1", "用户一的问题")

        with self.assertRaisesRegex(PermissionError, "another user"):
            self.workflow.invoke("thread-secure", "user-2", "用户二的问题")


if __name__ == "__main__":
    unittest.main()
