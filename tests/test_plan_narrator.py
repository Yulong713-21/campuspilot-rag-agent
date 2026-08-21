from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.plan_narrator import StudyPlanNarrator


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages, **kwargs):
        return {
            "message": {"content": self.content},
            "model": "qwen-test",
            "usage": {},
        }


def plan_result() -> dict:
    return {
        "completed_credits": 12,
        "remaining_credits": 60,
        "validation": {"all_valid": True},
        "plans": [
            {
                "name": "学业与实习兼顾",
                "description": "每学期最多三门。",
                "estimated_semesters": 4,
                "semesters": [
                    {
                        "semester": "2026 S2",
                        "total_credits": 18,
                        "courses": [
                            {"course_code": "FIT5122"},
                            {"course_code": "FIT9131"},
                        ],
                    }
                ],
            }
        ],
    }


class StudyPlanNarratorTest(unittest.TestCase):
    def test_narrates_validated_plan_naturally(self) -> None:
        narrator = StudyPlanNarrator(
            FakeClient(
                "你想兼顾学习和实习，可以先按三门课的节奏推进，"
                "并用 FIT5122 积累求职素材。"
            )
        )

        result = narrator.narrate(
            query="怎么选课能兼顾学业和实习？",
            preferences={
                "planning_goal": "study_internship_balance",
                "planning_goals": [
                    "academic_progress",
                    "internship_readiness",
                ],
            },
            plans=plan_result(),
        )

        self.assertEqual(
            result["answer_source"],
            "llm_plan_explanation_with_deterministic_tools",
        )
        self.assertIn("兼顾", result["message"])

    def test_unknown_course_in_narration_uses_safe_fallback(self) -> None:
        result = StudyPlanNarrator(
            FakeClient("建议第一学期选择 ABC9999。")
        ).narrate(
            query="兼顾学业和实习",
            preferences={
                "planning_goal": "study_internship_balance",
                "planning_goals": [],
            },
            plans=plan_result(),
        )

        self.assertEqual(
            result["answer_source"],
            "deterministic_plan_explanation",
        )
        self.assertIn("学业进度和实习准备", result["message"])
        self.assertEqual(result["trace"][-1]["tool"], "fallback_to_plan_summary")
