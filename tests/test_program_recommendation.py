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


class ProgramRecommendationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ProgramRecommendationService()

    def test_business_analytics_goal_outranks_weak_personality_signal(self) -> None:
        result = self.service.recommend(
            {
                "prompt": "我喜欢数据分析，性格细致，毕业想做商业分析师",
                "score_value": 82,
                "score_scale": 100,
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertIn("Analytics", result["recommendations"][0]["program_name"])
        self.assertEqual(result["recommendations"][0]["university_id"], "melbourne")

    def test_marketing_profile_returns_marketing_program(self) -> None:
        result = self.service.recommend(
            {"prompt": "我喜欢沟通和创意，希望以后做品牌营销"}
        )

        names = [item["program_name"] for item in result["recommendations"]]
        self.assertTrue(any("Marketing" in name for name in names))

    def test_target_university_limits_candidate_pool(self) -> None:
        result = self.service.recommend(
            {
                "prompt": "我喜欢金融和投资，希望进入银行",
                "university": "The University of Sydney",
            }
        )

        self.assertTrue(result["recommendations"])
        self.assertTrue(
            all(
                item["university_id"] == "sydney"
                for item in result["recommendations"]
            )
        )

    def test_score_is_not_converted_to_admission_decision(self) -> None:
        result = self.service.recommend(
            {
                "prompt": "我想学计算机，以后做软件开发",
                "score_value": 3.2,
                "score_scale": 4,
            }
        )

        academic = result["recommendations"][0]["academic_fit"]
        self.assertEqual(academic["status"], "REQUIRES_PROGRAM_RULE_CHECK")
        self.assertNotIn("MEETS", academic["status"])
        self.assertNotIn("minimum", academic)

    def test_every_recommendation_has_official_catalog_evidence(self) -> None:
        result = self.service.recommend(
            {"prompt": "喜欢供应链和运营，希望做物流管理"}
        )

        self.assertTrue(result["recommendations"])
        for item in result["recommendations"]:
            self.assertTrue(item["official_url"].startswith("https://"))
            self.assertTrue(item["program_name"])

    def test_empty_profile_asks_useful_clarification(self) -> None:
        result = self.service.recommend({"prompt": "我还没想好"})

        self.assertEqual(
            result["status"], "RECOMMENDATION_PROFILE_INSUFFICIENT"
        )
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["next_action"], "ask_recommendation_profile")
        self.assertEqual(len(result["clarifying_questions"]), 2)

    def test_broad_cross_market_goal_returns_three_exploration_routes(self) -> None:
        result = self.service.recommend(
            {"prompt": "未来希望回国进大企业或者留在澳洲，推荐我选什么"}
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertTrue(result["profile"]["exploration_mode"])
        self.assertEqual(len(result["recommendations"]), 3)
        reasons = [item["reasons"][0] for item in result["recommendations"]]
        self.assertTrue(any("技术路线" in reason for reason in reasons))
        self.assertTrue(any("数据商业路线" in reason for reason in reasons))
        self.assertTrue(any("综合商科路线" in reason for reason in reasons))
        self.assertEqual(len(result["clarifying_questions"]), 1)

    def test_short_technical_clarification_is_a_valid_profile_signal(self) -> None:
        result = self.service.recommend(
            {
                "prompt": "想做技术",
                "conversation_context": "根据我的就业目标推荐专业",
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertTrue(result["recommendations"])
        self.assertIn(
            "计算机与技术",
            result["profile"]["matched_signals"],
        )

    def test_direction_agent_runs_only_when_enabled_and_rules_miss(self) -> None:
        class FakeProfileInterpreter:
            def __init__(self) -> None:
                self.call_count = 0

            def extract(self, profile_text: str) -> dict:
                self.call_count += 1
                return {
                    "matched_signals": ["computing"],
                    "career_mobility_goal": False,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "confidence": 0.86,
                    "model": "fake-profile-model",
                }

        interpreter = FakeProfileInterpreter()
        service = ProgramRecommendationService(
            profile_interpreter=interpreter
        )

        first = service.recommend({"prompt": "我还没想好"})
        self.assertEqual(interpreter.call_count, 0)
        second = service.recommend(
            {
                "prompt": "我喜欢解决复杂系统问题",
                "allow_llm_profile_fallback": True,
            }
        )

        self.assertEqual(first["status"], "RECOMMENDATION_PROFILE_INSUFFICIENT")
        self.assertEqual(interpreter.call_count, 1)
        self.assertEqual(second["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertIn(
            "recommend_program_directions_with_agent",
            second["trace_tools"],
        )

    def test_salary_priority_is_recommended_by_agent_then_grounded_in_catalog(self) -> None:
        class SalaryDirectionAgent:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": ["computing", "analytics", "finance"],
                    "career_mobility_goal": False,
                    "compensation_priority": True,
                    "work_intensity_tolerance": "high",
                    "needs_clarification": False,
                    "clarification_question": None,
                    "evidence_phrases": ["薪资高", "能接受加班"],
                    "interpretation_summary": (
                        "你把收入上限放在首位，并能接受较高工作强度，因此建议先比较"
                        "技术工程、数据与量化、金融三类方向，但它们都不保证高薪。"
                    ),
                    "confidence": 0.84,
                    "model": "salary-direction-agent",
                }

        service = ProgramRecommendationService(
            profile_interpreter=SalaryDirectionAgent()
        )
        result = service.recommend(
            {
                "prompt": "我想选择赚钱的，薪资高的行业，能接受加班",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertEqual(
            result["profile"]["profile_source"],
            "cloud_llm_direction_agent",
        )
        self.assertTrue(result["profile"]["compensation_priority"])
        self.assertEqual(result["profile"]["work_intensity_tolerance"], "high")
        self.assertIn(
            "recommend_program_directions_with_agent",
            result["trace_tools"],
        )
        self.assertIn("search_verified_program_catalog", result["trace_tools"])
        self.assertTrue(result["recommendations"])
        self.assertTrue(
            all(item["official_url"] for item in result["recommendations"])
        )

    def test_missing_agent_summary_gets_public_reasoning_fallback(self) -> None:
        class DirectionAgentWithoutSummary:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": ["computing", "international_business"],
                    "career_mobility_goal": False,
                    "compensation_priority": False,
                    "work_intensity_tolerance": "unknown",
                    "needs_clarification": False,
                    "clarification_question": None,
                    "evidence_phrases": ["国际化机会", "技术壁垒"],
                    "interpretation_summary": None,
                    "confidence": 0.79,
                    "model": "direction-agent-without-summary",
                }

        service = ProgramRecommendationService(
            profile_interpreter=DirectionAgentWithoutSummary()
        )
        result = service.recommend(
            {
                "prompt": "我希望能兼顾国际化机会和技术壁垒",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertIn("我先说明我的理解", result["message"])
        self.assertIn("国际化机会", result["message"])
        self.assertIn("技术壁垒", result["message"])
        self.assertIn("跨境业务", result["message"])
        explanation = next(
            item
            for item in result["trace"]
            if item["tool"] == "explain_profile_inference"
        )
        self.assertEqual(explanation["summary_source"], "service_fallback")

    def test_migration_goal_can_return_uncatalogued_directions(self) -> None:
        class ExplodingNarrator:
            def narrate(self, **kwargs):
                raise AssertionError(
                    "migration narration must wait for verified policy evidence"
                )

        class MigrationDirectionAgent:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": [],
                    "career_mobility_goal": True,
                    "compensation_priority": False,
                    "work_intensity_tolerance": "unknown",
                    "migration_priority": True,
                    "uncatalogued_directions": [
                        {
                            "name": "中学教育",
                            "category": "education",
                            "rationale": "已有教师资格，可优先核对资格衔接。",
                            "verification_note": (
                                "需核验当前职业清单、职业评估、州担保和邀请轮次。"
                            ),
                        },
                        {
                            "name": "社会工作",
                            "category": "social_work",
                            "rationale": "可作为转专业方向进一步调查。",
                            "verification_note": (
                                "需核验当前职业清单、职业评估、州担保和邀请轮次。"
                            ),
                        },
                        {
                            "name": "土木工程",
                            "category": "engineering",
                            "rationale": "属于当前目录尚未建设的工程方向。",
                            "verification_note": (
                                "需核验前置课程、职业评估和当前邀请数据。"
                            ),
                        },
                    ],
                    "needs_clarification": False,
                    "clarification_question": "你是否接受额外注册和实习要求？",
                    "evidence_phrases": ["更易获邀", "有教师资格"],
                    "interpretation_summary": (
                        "你把澳洲移民可行性放在首位，并具有教师资格。"
                    ),
                    "confidence": 0.72,
                    "model": "migration-direction-agent",
                }

        service = ProgramRecommendationService(
            profile_interpreter=MigrationDirectionAgent(),
            narrator=ExplodingNarrator(),
        )
        result = service.recommend(
            {
                "prompt": "我更关注澳大利亚更易获邀的方向，我有教师资格",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertEqual(result["recommendations"], [])
        self.assertTrue(result["profile"]["migration_priority"])
        self.assertEqual(len(result["uncatalogued_directions"]), 3)
        self.assertEqual(
            result["uncatalogued_directions"][0]["catalog_status"],
            "not_indexed",
        )
        self.assertEqual(
            result["next_action"],
            "refine_direction_or_expand_catalog",
        )
        self.assertIn(
            "你已提到教师资格",
            result["uncatalogued_directions"][0]["rationale"],
        )
        generation = next(
            item
            for item in result["trace"]
            if item["tool"] == "generate_natural_recommendation"
        )
        self.assertTrue(generation["skipped"])
        self.assertIn("不能把候选方向理解为保证获邀", result["message"])
        self.assertNotIn("低分必邀", result["message"])

    def test_follow_up_clarification_does_not_repeat_first_turn_intro(self) -> None:
        class EmptyProfileInterpreter:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": [],
                    "career_mobility_goal": False,
                    "needs_clarification": True,
                    "clarification_question": "你想参与游戏开发、策划还是运营？",
                    "evidence_phrases": ["喜欢打游戏"],
                    "interpretation_summary": None,
                    "confidence": 0.55,
                    "model": "fake-profile-model",
                }

        service = ProgramRecommendationService(
            profile_interpreter=EmptyProfileInterpreter()
        )
        result = service.recommend(
            {
                "prompt": "我就喜欢打游戏",
                "conversation_context": "根据我的就业目标推荐专业",
                "allow_llm_profile_fallback": True,
            }
        )

        self.assertEqual(result["status"], "RECOMMENDATION_PROFILE_INSUFFICIENT")
        self.assertNotIn("可以先不选专业", result["message"])
        self.assertIn("把兴趣落到", result["message"])
        self.assertEqual(
            result["clarifying_questions"][0],
            "你想参与游戏开发、策划还是运营？",
        )

    def test_inferred_game_direction_explains_basis_and_adds_career_path(self) -> None:
        class GameProfileInterpreter:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": ["computing"],
                    "career_mobility_goal": False,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "evidence_phrases": ["参与游戏的设计和创作", "不太擅长美术"],
                    "interpretation_summary": (
                        "你喜欢参与游戏设计和创作，又不偏美术，所以我暂时把"
                        "computing 和游戏系统策划作为优先探索方向。"
                    ),
                    "confidence": 0.78,
                    "model": "fake-profile-model",
                }

        service = ProgramRecommendationService(
            profile_interpreter=GameProfileInterpreter()
        )
        result = service.recommend(
            {
                "prompt": "我喜欢参与游戏的设计和创作，但是不太擅长美术",
                "conversation_context": "根据就业目标推荐专业 我喜欢打游戏",
                "allow_llm_profile_fallback": True,
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertIn("我先说明我的理解", result["message"])
        self.assertIn("不代表你已经明确选择了这个专业", result["message"])
        self.assertNotIn("computing", result["message"])
        self.assertIn("计算机与技术", result["message"])
        self.assertEqual(
            result["profile"]["evidence_phrases"],
            ["参与游戏的设计和创作", "不太擅长美术"],
        )
        career_path = result["recommendations"][0]["career_path"]
        self.assertIn("游戏系统或数值策划", career_path["roles"])
        self.assertTrue(career_path["preparation"])


if __name__ == "__main__":
    unittest.main()
