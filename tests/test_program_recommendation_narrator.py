from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.program_recommendation_narrator import (
    ProgramRecommendationNarrator,
)


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages, **kwargs):
        return {
            "message": {"content": self.content},
            "model": "qwen-test",
            "usage": {},
        }


class SequenceClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.call_count = 0

    def chat(self, messages, **kwargs):
        content = self.contents[self.call_count]
        self.call_count += 1
        return {
            "message": {"content": content},
            "model": "qwen-test",
            "usage": {},
        }


class ProgramRecommendationNarratorTest(unittest.TestCase):
    def test_agent_can_freely_explain_grounded_directions(self) -> None:
        narrator = ProgramRecommendationNarrator(
            FakeClient(
                "你同时看重国际化机会和技术壁垒。计算机方向更适合通过工程"
                "能力形成长期壁垒，国际商务则更直接连接跨境协作，但技术深度"
                "通常较弱。现阶段建议优先探索技术路线，再用跨境项目验证国际化"
                "偏好。你更愿意长期训练编程，还是更享受跨文化沟通？"
            )
        )

        result = narrator.narrate(
            query="我希望兼顾国际化机会和技术壁垒",
            profile={
                "matched_signals": ["计算机与技术", "国际商务"],
                "interpretation_summary": "先比较两个候选方向。",
                "evidence_phrases": ["国际化机会", "技术壁垒"],
            },
            recommendations=[],
            fallback_message="固定模板",
        )

        self.assertEqual(
            result["answer_source"],
            "llm_direction_recommendation_without_catalog",
        )
        self.assertIn("工程能力", result["message"])
        self.assertNotEqual(result["message"], "固定模板")

    def test_prohibited_guarantee_falls_back_to_grounded_template(self) -> None:
        narrator = ProgramRecommendationNarrator(
            FakeClient("选择这个方向保证高薪。")
        )

        result = narrator.narrate(
            query="想要高薪",
            profile={},
            recommendations=[],
            fallback_message="这是阶段性候选，不保证就业结果。",
        )

        self.assertEqual(
            result["answer_source"],
            "catalog_program_recommendation_agent",
        )
        self.assertEqual(
            result["message"],
            "这是阶段性候选，不保证就业结果。",
        )
        self.assertEqual(
            result["trace"][-1]["source"],
            "deterministic_fallback",
        )

    def test_high_risk_claim_is_rewritten_once(self) -> None:
        client = SequenceClient(
            [
                "护理对应 ANZSCO 123456，历史邀请分数是七十分。",
                (
                    "你看重技术壁垒和国际化协作，可以先探索计算机方向，"
                    "再通过跨文化项目验证自己是否适应国际团队。这个判断仍需"
                    "结合你的编程体验继续确认。"
                ),
            ]
        )
        narrator = ProgramRecommendationNarrator(client)

        result = narrator.narrate(
            query="希望兼顾国际化机会和技术壁垒",
            profile={"matched_signals": ["计算机与技术"]},
            recommendations=[],
            fallback_message="固定模板",
        )

        self.assertEqual(client.call_count, 2)
        self.assertNotIn("移民", result["message"])
        self.assertEqual(result["trace"][0]["retry_count"], 1)


if __name__ == "__main__":
    unittest.main()
