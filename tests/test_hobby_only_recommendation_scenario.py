from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.program_recommendation import (  # noqa: E402
    ProgramRecommendationService,
)


class HobbyOnlyProfileInterpreter:
    """Deterministic stand-in for the structured LLM profile node."""

    def __init__(self) -> None:
        self.call_count = 0

    def extract(self, profile_text: str) -> dict:
        self.call_count += 1
        if "数值平衡" not in profile_text or "关卡机制" not in profile_text:
            return {
                "matched_signals": [],
                "career_mobility_goal": False,
                "needs_clarification": True,
                "clarification_question": (
                    "玩游戏时，你更喜欢研究玩法系统、技术实现、剧情美术，"
                    "还是玩家运营？"
                ),
                "evidence_phrases": ["爱好就是打游戏"],
                "interpretation_summary": None,
                "confidence": 0.5,
                "model": "hobby-profile-fixture",
            }
        return {
            "matched_signals": ["computing", "analytics"],
            "career_mobility_goal": False,
            "needs_clarification": False,
            "clarification_question": None,
            "evidence_phrases": [
                "研究技能组合",
                "数值平衡",
                "关卡机制",
                "把规则做成能运行的东西",
            ],
            "interpretation_summary": (
                "你享受研究数值、机制和可运行规则，因此暂时把计算机与技术、"
                "数据与分析作为候选方向，并优先探索游戏系统与技术策划。"
            ),
            "confidence": 0.82,
            "model": "hobby-profile-fixture",
        }


class HobbyOnlyRecommendationScenarioTest(unittest.TestCase):
    def test_hobbies_are_clarified_before_grounded_recommendation(self) -> None:
        interpreter = HobbyOnlyProfileInterpreter()
        service = ProgramRecommendationService(profile_interpreter=interpreter)

        first = service.recommend(
            {"prompt": "我平时最大的爱好就是打游戏。"}
        )
        second = service.recommend(
            {
                "prompt": (
                    "玩的时候最喜欢研究技能组合、数值平衡和关卡机制。"
                    "比起画画，我更喜欢把规则做成能运行的东西。"
                ),
                "conversation_context": "我平时最大的爱好就是打游戏。",
                "allow_llm_profile_fallback": True,
            }
        )

        self.assertEqual(first["status"], "RECOMMENDATION_PROFILE_INSUFFICIENT")
        self.assertEqual(first["recommendations"], [])
        self.assertEqual(interpreter.call_count, 1)

        self.assertEqual(second["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertIn("待确认的方向推断", second["message"])
        self.assertEqual(
            second["profile"]["evidence_phrases"],
            ["研究技能组合", "数值平衡", "关卡机制", "把规则做成能运行的东西"],
        )
        self.assertIn("计算机与技术", second["profile"]["matched_signals"])
        self.assertIn("数据与分析", second["profile"]["matched_signals"])
        self.assertTrue(second["recommendations"])
        self.assertTrue(
            any(
                "游戏系统或数值策划"
                in item.get("career_path", {}).get("roles", [])
                for item in second["recommendations"]
            )
        )
        self.assertIn("search_verified_program_catalog", second["trace_tools"])
        self.assertIn("build_career_path", second["trace_tools"])
        self.assertEqual(second["next_action"], "select_program_then_evaluate_admission")


if __name__ == "__main__":
    unittest.main()
