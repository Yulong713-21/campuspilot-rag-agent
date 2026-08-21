from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.program_recommendation_interpreter import (
    CloudRecommendationProfileInterpreter,
)


class FakeClient:
    def chat(self, messages, **kwargs):
        return {
            "message": {
                "content": json.dumps(
                    {
                        "matched_signals": [],
                        "career_mobility_goal": True,
                        "compensation_priority": False,
                        "work_intensity_tolerance": "unknown",
                        "migration_priority": True,
                        "uncatalogued_directions": [
                            {
                                "name": "中学教育",
                                "category": "education",
                                "rationale": "已有教师资格，可先核对衔接条件。",
                                "verification_note": (
                                    "需核验当前职业清单、职业评估、州担保和邀请轮次。"
                                ),
                            }
                        ],
                        "needs_clarification": False,
                        "clarification_question": "是否愿意继续从事教育？",
                        "evidence_phrases": ["有教师资格", "更易获邀"],
                        "interpretation_summary": (
                            "先把教育作为待核验的方向级候选。"
                        ),
                        "confidence": 0.73,
                    },
                    ensure_ascii=False,
                )
            },
            "model": "qwen-test",
            "usage": {},
        }


class ProgramRecommendationInterpreterTest(unittest.TestCase):
    def test_parses_uncatalogued_migration_direction(self) -> None:
        result = CloudRecommendationProfileInterpreter(FakeClient()).extract(
            "我在澳大利亚更关注移民可行性，并且有教师资格"
        )

        self.assertTrue(result["migration_priority"])
        self.assertEqual(result["matched_signals"], [])
        self.assertEqual(
            result["uncatalogued_directions"][0]["category"],
            "education",
        )
        self.assertIn(
            "职业评估",
            result["uncatalogued_directions"][0]["verification_note"],
        )


if __name__ == "__main__":
    unittest.main()
