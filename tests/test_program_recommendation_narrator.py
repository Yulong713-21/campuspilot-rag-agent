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
    def test_agent_naturally_clarifies_an_ambiguous_tradeoff(self) -> None:
        content = (
            "你担心选错方向浪费两年，说明现在最需要的不是立刻定专业，而是先确定"
            "你愿意长期投入的工作方式。为了排除明显不合适的方向，你更享受独立"
            "分析和动手解决问题，还是与人沟通并推动团队完成目标？"
        )
        narrator = ProgramRecommendationNarrator(FakeClient(content))

        result = narrator.clarify(
            query="我担心选错专业浪费两年，能不能先帮我缩小范围",
            evidence_phrases=["选错专业", "浪费两年"],
            suggested_question="你更喜欢哪类工作方式？",
            fallback_message="固定澄清模板",
        )

        self.assertEqual(
            result["answer_source"], "llm_recommendation_clarification"
        )
        self.assertIn("浪费两年", result["message"])
        self.assertNotIn("可以先不选专业", result["message"])

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

    def test_unverified_assessment_agency_and_experience_rule_are_rewritten(self) -> None:
        client = SequenceClient(
            [
                "需要通过 ACS 评估，并补足要求的1年相关工作经验。",
                (
                    "你已有计算机背景，可以继续探索软件开发方向。项目候选不是按"
                    "移民可行性排序，职业评估和工作经验条件仍需用当前官方资料核验。"
                ),
            ]
        )
        narrator = ProgramRecommendationNarrator(client)

        result = narrator.narrate(
            query="想去澳洲做程序员并规划长期发展",
            profile={"migration_priority": True},
            recommendations=[{"career_path": {}}],
            fallback_message="固定模板",
        )

        self.assertEqual(client.call_count, 2)
        self.assertNotIn("ACS", result["message"])
        self.assertNotIn("1年", result["message"])

    def test_second_invalid_answer_keeps_natural_grounded_sentences(self) -> None:
        content = (
            "你已有计算机本科背景，希望换一个环境继续做开发，这个方向衔接是自然的。"
            "软件开发和后端岗位都能延续你的工程能力，可以先通过真实项目比较工作内容。"
            "具体需要通过 ACS 评估并补足要求的1年工作经验。"
            "你更享受设计接口，还是排查复杂系统问题？"
        )
        narrator = ProgramRecommendationNarrator(FakeClient(content))

        result = narrator.narrate(
            query="想去澳洲继续做程序员",
            profile={"migration_priority": True},
            recommendations=[{"career_path": {}}],
            fallback_message="固定模板",
        )

        self.assertEqual(
            result["answer_source"],
            "llm_program_recommendation_with_catalog",
        )
        self.assertIn("计算机本科背景", result["message"])
        self.assertNotIn("ACS", result["message"])
        self.assertNotIn("1年工作经验", result["message"])
        self.assertTrue(result["trace"][0]["policy_details_removed"])

    def test_neutral_migration_planning_language_is_not_rejected(self) -> None:
        content = (
            "你已有计算机本科背景，也明确希望换一个发展环境，并在澳洲继续做程序员。"
            "因此优先比较计算机项目是连贯的，但下面的项目卡只是课程方向候选，并没有"
            "按留澳就业或技术移民可行性排序。后两项仍要结合毕业工签、职业评估和当期"
            "政策证据单独核验。你更看重课程的工程实践，还是学校提供的就业支持？"
        )
        narrator = ProgramRecommendationNarrator(FakeClient(content))

        result = narrator.narrate(
            query="我本科在深圳大学读计算机，想移民澳洲找程序员工作",
            profile={
                "matched_signals": ["计算机与技术"],
                "migration_priority": True,
                "evidence_phrases": ["深圳大学读计算机", "移民澳洲"],
            },
            recommendations=[{"career_path": {}}],
            fallback_message="固定模板",
        )

        self.assertEqual(
            result["answer_source"],
            "llm_program_recommendation_with_catalog",
        )
        self.assertIn("技术移民可行性", result["message"])
        self.assertNotEqual(result["message"], "固定模板")

    def test_negated_migration_guarantee_is_a_valid_boundary(self) -> None:
        content = (
            "你可以先比较与现有背景衔接的方向，但这些候选不能保证移民，"
            "也不能据此判断是否符合移民资格。相关条件仍需按最新官方信息核验。"
        )
        narrator = ProgramRecommendationNarrator(FakeClient(content))

        result = narrator.narrate(
            query="我只关心能不能留在澳洲",
            profile={"migration_priority": True},
            recommendations=[],
            fallback_message="固定模板",
        )

        self.assertEqual(
            result["answer_source"],
            "llm_direction_recommendation_without_catalog",
        )
        self.assertIn("不能保证移民", result["message"])


if __name__ == "__main__":
    unittest.main()
