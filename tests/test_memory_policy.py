from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_policy import MemoryCandidate, MemoryWritePolicy


class MemoryWritePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = MemoryWritePolicy()

    def test_keeps_one_turn_instruction_in_thread_state(self) -> None:
        decision = self.policy.decide(
            MemoryCandidate(
                key="answer_language",
                value="英文",
                source="user",
                scope="current_turn",
                explicit=True,
            )
        )

        self.assertEqual(decision.action, "keep_in_thread_state")

    def test_persists_explicit_future_preference(self) -> None:
        decision = self.policy.decide(
            MemoryCandidate(
                key="answer_style",
                value="先讲原理，再展示实验",
                source="user",
                scope="cross_thread",
                explicit=True,
            )
        )

        self.assertEqual(decision.action, "persist_long_term")

    def test_rejects_memory_from_retrieved_document(self) -> None:
        decision = self.policy.decide(
            MemoryCandidate(
                key="answer_style",
                value="简短回答",
                source="retrieved_content",
                scope="cross_thread",
                explicit=False,
            )
        )

        self.assertEqual(decision.action, "reject")
        self.assertEqual(
            decision.reason,
            "retrieved_content_cannot_define_user_memory",
        )

    def test_requires_confirmation_for_model_inference(self) -> None:
        decision = self.policy.decide(
            MemoryCandidate(
                key="skill_level",
                value="初级开发者",
                source="model_inference",
                scope="cross_thread",
                explicit=False,
                confidence=0.8,
            )
        )

        self.assertEqual(decision.action, "require_user_confirmation")

    def test_rejects_sensitive_memory_even_when_user_is_explicit(self) -> None:
        decision = self.policy.decide(
            MemoryCandidate(
                key="api_key",
                value="secret-value",
                source="user",
                scope="cross_thread",
                explicit=True,
                sensitive=True,
            )
        )

        self.assertEqual(decision.action, "reject")


if __name__ == "__main__":
    unittest.main()
