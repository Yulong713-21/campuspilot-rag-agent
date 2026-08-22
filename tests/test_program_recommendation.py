from __future__ import annotations

from pathlib import Path
import json
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

    def test_direction_agent_enriches_profile_even_when_rules_match(self) -> None:
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
                "prompt": "我本科读计算机，希望去澳洲找程序员工作",
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

    def test_existing_computing_signal_keeps_user_background_summary(self) -> None:
        class BackgroundAwareInterpreter:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": ["computing"],
                    "career_mobility_goal": True,
                    "compensation_priority": False,
                    "work_intensity_tolerance": "unknown",
                    "migration_priority": True,
                    "uncatalogued_directions": [],
                    "needs_clarification": False,
                    "clarification_question": "你更看重课程实用性还是就业支持？",
                    "evidence_phrases": [
                        "深圳大学读的计算机",
                        "国内太卷了",
                        "移民澳洲",
                        "找程序员工作",
                    ],
                    "interpretation_summary": (
                        "你已有计算机本科背景，希望换一个发展环境并在澳洲继续软件开发，"
                        "因此项目方向可以延续计算机，但就业和移民条件仍需分别核验。"
                    ),
                    "confidence": 0.9,
                    "model": "background-aware-agent",
                }

        service = ProgramRecommendationService(
            profile_interpreter=BackgroundAwareInterpreter()
        )
        result = service.recommend(
            {
                "prompt": (
                    "我本科在深圳大学读的计算机，国内太卷了，"
                    "想移民澳洲找程序员工作"
                ),
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertTrue(result["profile"]["migration_priority"])
        self.assertIn(
            "深圳大学读的计算机",
            result["profile"]["evidence_phrases"],
        )
        self.assertEqual(len(result["profile"]["evidence_phrases"]), 4)
        self.assertIn(
            "recommend_program_directions_with_agent",
            result["trace_tools"],
        )

    def test_naturalness_fixture_has_fifty_conversation_cases(self) -> None:
        fixture = (
            REPO_ROOT
            / "tests"
            / "fixtures"
            / "program_recommendation_naturalness_cases.json"
        )
        cases = json.loads(fixture.read_text(encoding="utf-8"))

        self.assertEqual(len(cases), 50)
        self.assertEqual(len({case["id"] for case in cases}), 50)
        self.assertTrue(all(18 <= len(case["prompt"]) <= 45 for case in cases))
        self.assertTrue(all(case["anchors"] for case in cases))

    def test_migration_recommendation_completes_missing_evidence_boundary(self) -> None:
        class ComputingProfileInterpreter:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": ["computing"],
                    "career_mobility_goal": True,
                    "migration_priority": True,
                    "uncatalogued_directions": [],
                    "evidence_phrases": ["深圳大学读计算机", "移民澳洲"],
                    "interpretation_summary": "延续计算机背景探索澳洲开发岗位。",
                    "confidence": 0.9,
                    "model": "profile-test",
                }

        class BoundaryOmittingNarrator:
            def narrate(self, **kwargs):
                return {
                    "message": "你的计算机本科背景可以自然衔接软件开发方向。",
                    "answer_source": "llm_program_recommendation_with_catalog",
                    "trace": [],
                }

        service = ProgramRecommendationService(
            profile_interpreter=ComputingProfileInterpreter(),
            narrator=BoundaryOmittingNarrator(),
        )
        result = service.recommend(
            {
                "prompt": "我本科在深圳大学读计算机，想移民澳洲做程序员",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertIn("不是按留澳或移民可行性排序", result["message"])
        self.assertIn(
            "complete_migration_evidence_boundary", result["trace_tools"]
        )

    def test_existing_migration_evidence_boundary_is_not_duplicated(self) -> None:
        class BoundaryNarrator:
            def narrate(self, **kwargs):
                return {
                    "message": (
                        "土木背景可以先沿原方向核对项目。职业清单和职业评估"
                        "都需要按最新官方信息核验。"
                    ),
                    "answer_source": "llm_direction_recommendation_without_catalog",
                    "trace": [],
                }

        service = ProgramRecommendationService(narrator=BoundaryNarrator())
        result = service.recommend(
            {
                "prompt": "我本科是土木，想留在澳洲",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertNotIn(
            "complete_migration_evidence_boundary", result["trace_tools"]
        )
        self.assertEqual(result["message"].count("职业清单"), 1)

    def test_future_stay_in_australia_is_migration_planning_signal(self) -> None:
        result = ProgramRecommendationService().recommend(
            {
                "prompt": "预算有限但希望未来留澳，选专业先看什么？",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertTrue(result["profile"]["migration_priority"])

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
        class MigrationNarrator:
            def __init__(self) -> None:
                self.call_count = 0

            def narrate(self, **kwargs):
                self.call_count += 1
                return {
                    "message": (
                        "你把留澳可行性放在首位，也提到了教师资格。当前先比较教育、"
                        "社工和工程等方向，但这些候选不是按移民难度排序；职业清单、"
                        "职业评估、州担保和邀请情况仍需按最新官方信息核验。"
                    ),
                    "answer_source": "llm_direction_recommendation_without_catalog",
                    "trace": [
                        {
                            "tool": "generate_natural_recommendation",
                            "ok": True,
                            "source": "fake_llm",
                        }
                    ],
                }

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

        narrator = MigrationNarrator()
        service = ProgramRecommendationService(
            profile_interpreter=MigrationDirectionAgent(),
            narrator=narrator,
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
        self.assertGreaterEqual(len(result["uncatalogued_directions"]), 3)
        direction_names = {
            item["name"] for item in result["uncatalogued_directions"]
        }
        self.assertIn("教育与教师培养", direction_names)
        self.assertIn("社会工作", direction_names)
        self.assertEqual(
            result["next_action"],
            "refine_direction_or_expand_catalog",
        )
        education = next(
            item
            for item in result["uncatalogued_directions"]
            if item["name"] == "教育与教师培养"
        )
        self.assertEqual(education["catalog_status"], "direction_indexed")
        self.assertIn("你已提到教师资格", education["rationale"])
        self.assertEqual(narrator.call_count, 1)
        self.assertEqual(
            result["answer_source"],
            "llm_direction_recommendation_without_catalog",
        )
        self.assertIn("最新官方信息核验", result["message"])
        self.assertNotIn("低分必邀", result["message"])

    def test_explicit_civil_background_is_not_redirected_to_indexed_catalog(self) -> None:
        class OverreachingDirectionAgent:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": ["computing", "analytics"],
                    "career_mobility_goal": True,
                    "compensation_priority": False,
                    "work_intensity_tolerance": "unknown",
                    "migration_priority": True,
                    "uncatalogued_directions": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "evidence_phrases": ["本科就是土木", "想移居澳洲"],
                    "interpretation_summary": "可以考虑计算机或数据方向。",
                    "confidence": 0.8,
                    "model": "overreaching-agent",
                }

        service = ProgramRecommendationService(
            profile_interpreter=OverreachingDirectionAgent()
        )
        result = service.recommend(
            {
                "prompt": "我本科就是土木，土木好留澳洲吗？雅思还在考",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertEqual(result["status"], "PROGRAM_RECOMMENDATIONS_READY")
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["profile"]["matched_signals"], [])
        self.assertEqual(result["uncatalogued_directions"][0]["name"], "土木工程")
        self.assertEqual(
            result["uncatalogued_directions"][0]["catalog_status"],
            "direction_indexed",
        )
        self.assertIn(
            "monash.edu",
            result["uncatalogued_directions"][0]["official_url"],
        )
        self.assertNotIn("计算机", result["message"])
        self.assertNotIn("数据分析", result["message"])

    def test_civil_user_who_requests_a_career_change_can_compare_new_directions(self) -> None:
        class CareerChangeAgent:
            def extract(self, profile_text: str) -> dict:
                return {
                    "matched_signals": ["analytics"],
                    "career_mobility_goal": True,
                    "compensation_priority": False,
                    "work_intensity_tolerance": "unknown",
                    "migration_priority": True,
                    "uncatalogued_directions": [],
                    "needs_clarification": False,
                    "clarification_question": None,
                    "evidence_phrases": ["学土木", "不想去工地"],
                    "interpretation_summary": "用户明确希望转向非工地工作。",
                    "confidence": 0.8,
                    "model": "career-change-agent",
                }

        result = ProgramRecommendationService(
            profile_interpreter=CareerChangeAgent()
        ).recommend(
            {
                "prompt": "我学土木但不想去工地，想转专业还能考虑哪些方向？",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertTrue(result["recommendations"])
        self.assertIn("数据与分析", result["profile"]["matched_signals"])
        self.assertEqual(result["uncatalogued_directions"][0]["name"], "土木工程")

    def test_explicit_direction_survives_profile_interpreter_failure(self) -> None:
        class FailingDirectionAgent:
            def extract(self, profile_text: str) -> dict:
                raise ValueError("invalid model response")

        result = ProgramRecommendationService(
            profile_interpreter=FailingDirectionAgent()
        ).recommend(
            {
                "prompt": "我本科就是土木，土木好留澳洲吗？雅思还在考",
                "allow_agent_direction_recommendation": True,
            }
        )

        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["uncatalogued_directions"][0]["name"], "土木工程")
        self.assertEqual(
            result["profile"]["profile_source"],
            "deterministic_rules_after_llm_error",
        )

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
