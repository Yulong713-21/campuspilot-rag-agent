from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot import CampusPilotConversationAgent  # noqa: E402
from agent_runtime.campuspilot_conversation_graph import (  # noqa: E402
    CampusPilotConversationGraph,
)
from campuspilot_core.program_recommendation import (  # noqa: E402
    ProgramRecommendationService,
)


class FakeIntentInterpreter:
    def __init__(self, decision=None, error=None) -> None:
        self.decision = decision
        self.error = error
        self.call_count = 0

    def interpret(self, query, history, planning_context=None):
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return dict(self.decision)


class CampusPilotConversationGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = CampusPilotConversationGraph(CampusPilotConversationAgent())

    def test_combined_recruitment_goal_uses_locked_structured_route(self) -> None:
        result = self.graph.respond(
            {
                "message": "我想 2028 年秋招就业，推荐我怎么安排",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5058"],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(result["conversation_route"], "structured")
        self.assertEqual(result["intent"], "study_plan")
        self.assertEqual(result["study_plans"]["plans"][0]["name"], "秋招准备优先")
        self.assertEqual(
            result["trace_tools"][:6],
            [
                "normalize_conversation_input",
                "detect_intent_signals",
                "parse_structured_intent",
                "validate_intent_decision",
                "route_conversation_state",
                "execute_conversation_route",
            ],
        )

    def test_business_study_plan_uses_handbook_advisory_inside_graph(self) -> None:
        class FakeHandbookQaAgent:
            def answer(self, query, **kwargs):
                return {
                    "message": "B6022 has core and elective study groups.[1]",
                    "evidence": [
                        {
                            "citation_number": 1,
                            "source_url": "https://example.edu/b6022",
                        }
                    ],
                    "trace": [{"tool": "search_handbook", "ok": True}],
                    "answer_source": "llm_handbook_grounded_answer",
                    "confidence": "medium",
                    "next_action": "review_official_sources",
                }

        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(
                handbook_qa_agent=FakeHandbookQaAgent(),
            )
        )

        result = graph.respond(
            {
                "message": "B6022 study plan",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(result["intent"], "study_plan")
        self.assertEqual(result["conversation_route"], "structured")
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["study_plans"])
        self.assertEqual(result["evidence"][0]["citation_number"], 1)
        self.assertIn(
            "route_program_planning_advisory",
            result["trace_tools"],
        )

    def test_program_recommendation_does_not_require_selected_program(self) -> None:
        result = self.graph.respond(
            {
                "message": "我还没选专业，喜欢数据分析，想做商业分析师，请推荐专业",
            }
        )

        self.assertEqual(result["conversation_route"], "structured")
        self.assertEqual(result["intent"], "program_recommendation")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["program_recommendations"]["recommendations"])
        self.assertIn("rank_program_candidates", result["trace_tools"])

    def test_recommendation_clarification_inherits_intent_without_faq(self) -> None:
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(),
            checkpointer=InMemorySaver(),
        )
        first = graph.respond(
            {
                "thread_id": "recommendation-thread-001",
                "message": "根据我的就业目标推荐专业",
            }
        )
        second = graph.respond(
            {
                "thread_id": "recommendation-thread-001",
                "message": "想做技术",
            }
        )

        self.assertEqual(first["status"], "needs_clarification")
        self.assertEqual(
            first["thread_state"]["pending_fields"],
            ["recommendation_profile"],
        )
        self.assertEqual(second["intent"], "program_recommendation")
        self.assertEqual(second["status"], "completed")
        self.assertTrue(second["program_recommendations"]["recommendations"])
        signal_trace = next(
            item
            for item in second["trace"]
            if item["tool"] == "detect_intent_signals"
        )
        self.assertTrue(signal_trace["intent_inherited"])
        self.assertFalse(signal_trace["exact_faq_candidate"])

    def test_game_interest_follow_ups_explain_inference_and_career_path(self) -> None:
        class GameProfileInterpreter:
            def extract(self, profile_text: str) -> dict:
                if "设计和创作" not in profile_text:
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
                return {
                    "matched_signals": ["computing"],
                    "career_mobility_goal": False,
                    "needs_clarification": False,
                    "clarification_question": None,
                    "evidence_phrases": ["参与游戏的设计和创作", "不太擅长美术"],
                    "interpretation_summary": (
                        "你喜欢参与游戏设计和创作，又不偏美术，所以我暂时把"
                        "游戏技术、系统策划和产品设计作为优先探索方向。"
                    ),
                    "confidence": 0.78,
                    "model": "fake-profile-model",
                }

        service = ProgramRecommendationService(
            profile_interpreter=GameProfileInterpreter()
        )
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(
                program_recommendation_service=service
            ),
            checkpointer=InMemorySaver(),
        )
        thread_id = "game-interest-recommendation-001"

        first = graph.respond(
            {"thread_id": thread_id, "message": "根据我的就业目标推荐专业"}
        )
        second = graph.respond(
            {"thread_id": thread_id, "message": "我就喜欢打游戏"}
        )
        third = graph.respond(
            {
                "thread_id": thread_id,
                "message": "我喜欢参与游戏的设计和创作，但是不太擅长美术",
            }
        )

        self.assertEqual(first["status"], "needs_clarification")
        self.assertEqual(second["status"], "needs_clarification")
        self.assertNotIn("可以先不选专业", second["message"])
        self.assertEqual(third["status"], "completed")
        self.assertIn("我先说明我的理解", third["message"])
        recommendation = third["program_recommendations"]["recommendations"][0]
        self.assertIn("游戏系统或数值策划", recommendation["career_path"]["roles"])

    def test_salary_goal_is_delegated_to_direction_agent_then_catalog(self) -> None:
        class SalaryDirectionAgent:
            def __init__(self) -> None:
                self.call_count = 0

            def extract(self, profile_text: str) -> dict:
                self.call_count += 1
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

        direction_agent = SalaryDirectionAgent()
        service = ProgramRecommendationService(
            profile_interpreter=direction_agent
        )
        intent_agent = FakeIntentInterpreter(
            {
                "intent": "program_recommendation",
                "goal_summary": "以高收入为优先目标探索专业方向",
                "needs_clarification": False,
                "clarification_question": None,
                "course_code": None,
                "confidence": 0.91,
                "route_reason": "career_priority",
            }
        )
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(
                program_recommendation_service=service,
                goal_interpreter=intent_agent,
            )
        )

        result = graph.respond(
            {"message": "我想选择赚钱的，薪资高的行业，能接受加班"}
        )

        self.assertEqual(direction_agent.call_count, 1)
        self.assertEqual(result["intent"], "program_recommendation")
        self.assertEqual(result["status"], "completed")
        self.assertIn(
            "recommend_program_directions_with_agent",
            result["trace_tools"],
        )
        self.assertIn("search_verified_program_catalog", result["trace_tools"])
        self.assertTrue(result["program_recommendations"]["recommendations"])

    def test_uncatalogued_migration_directions_are_completed_output(self) -> None:
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
                            "name": "护理",
                            "category": "healthcare",
                            "rationale": "模型生成的政策细节不会直接透传。",
                            "verification_note": "需要核验。",
                        },
                        {
                            "name": "土木工程",
                            "category": "engineering",
                            "rationale": "模型生成的政策细节不会直接透传。",
                            "verification_note": "需要核验。",
                        },
                    ],
                    "needs_clarification": False,
                    "clarification_question": "是否接受注册和实习要求？",
                    "evidence_phrases": ["能移民的就行"],
                    "interpretation_summary": "先做澳洲移民方向级探索。",
                    "confidence": 0.7,
                    "model": "migration-direction-agent",
                }

        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(
                program_recommendation_service=ProgramRecommendationService(
                    profile_interpreter=MigrationDirectionAgent()
                )
            )
        )

        result = graph.respond({"message": "能移民的就行"})

        self.assertEqual(result["intent"], "program_recommendation")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["missing_fields"], [])
        self.assertEqual(
            len(
                result["program_recommendations"][
                    "uncatalogued_directions"
                ]
            ),
            2,
        )
        self.assertEqual(
            result["next_action"],
            "refine_direction_or_expand_catalog",
        )

    def test_natural_profile_question_routes_to_program_recommendation(self) -> None:
        result = self.graph.respond(
            {
                "message": "我 GPA 78，性格内向，喜欢编程，未来想做软件开发，适合读什么？",
            }
        )

        self.assertEqual(result["intent"], "program_recommendation")
        self.assertTrue(result["program_recommendations"]["recommendations"])

    def test_broad_employment_goal_returns_routes_and_answer_choices(self) -> None:
        result = self.graph.respond(
            {
                "message": "未来希望回国进大企业或者留在澳洲，推荐我选什么",
            }
        )

        self.assertEqual(result["intent"], "program_recommendation")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            len(result["program_recommendations"]["recommendations"]), 3
        )
        self.assertIn("这三条路线里", result["message"])
        self.assertEqual(
            result["suggestions"],
            [
                "我更偏技术开发和编程",
                "我更偏数据分析和业务问题",
                "我更偏沟通协调和商业管理",
            ],
        )

    def test_structured_llm_intent_is_used_once_by_the_graph(self) -> None:
        interpreter = FakeIntentInterpreter(
            {
                "intent": "study_plan",
                "goal_summary": "兼顾课程和实习",
                "needs_clarification": False,
                "clarification_question": None,
                "course_code": None,
                "confidence": 0.92,
                "route_reason": "planning_goal",
            }
        )
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(goal_interpreter=interpreter)
        )

        result = graph.respond({"message": "I need advice for next year"})

        self.assertEqual(interpreter.call_count, 1)
        self.assertEqual(result["intent"], "study_plan")
        self.assertEqual(result["conversation_route"], "structured")
        validation = next(
            item for item in result["trace"]
            if item["tool"] == "validate_intent_decision"
        )
        self.assertEqual(validation["source"], "cloud_llm")

    def test_parser_failure_falls_back_to_deterministic_signal(self) -> None:
        interpreter = FakeIntentInterpreter(error=TimeoutError("timeout"))
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(goal_interpreter=interpreter)
        )

        result = graph.respond({"message": "FIT5120 assessment"})

        self.assertEqual(interpreter.call_count, 1)
        self.assertEqual(result["intent"], "handbook_qa")
        validation = next(
            item for item in result["trace"]
            if item["tool"] == "validate_intent_decision"
        )
        self.assertEqual(validation["source"], "deterministic_fallback")
        self.assertEqual(validation["validation_error"], "TimeoutError")

    def test_low_confidence_llm_cannot_override_explicit_signal(self) -> None:
        interpreter = FakeIntentInterpreter(
            {
                "intent": "capabilities",
                "goal_summary": "uncertain",
                "needs_clarification": False,
                "clarification_question": None,
                "course_code": None,
                "confidence": 0.2,
            }
        )
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(goal_interpreter=interpreter)
        )

        result = graph.respond({"message": "create a study plan"})

        self.assertEqual(result["intent"], "study_plan")
        self.assertEqual(result["conversation_route"], "structured")

    def test_invented_course_code_is_rejected(self) -> None:
        interpreter = FakeIntentInterpreter(
            {
                "intent": "course_role",
                "goal_summary": "判断课程角色",
                "needs_clarification": False,
                "clarification_question": None,
                "course_code": "FIT9999",
                "confidence": 0.95,
            }
        )
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(goal_interpreter=interpreter)
        )

        result = graph.respond({"message": "这门课算核心课吗？"})

        self.assertIn("course_code", result["missing_fields"])
        validation = next(
            item for item in result["trace"]
            if item["tool"] == "validate_intent_decision"
        )
        self.assertEqual(
            validation["validation_error"],
            "course_code_not_in_user_query",
        )

    def test_company_deadline_uses_grounded_qa_route(self) -> None:
        result = self.graph.respond({"message": "阿里巴巴 2027 届秋招什么时候投？"})

        self.assertEqual(result["conversation_route"], "grounded_qa")
        self.assertEqual(result["intent"], "recruitment_qa")

    def test_ambiguous_request_remains_available_for_context_interpretation(self) -> None:
        result = self.graph.respond({"message": "继续"})

        self.assertEqual(result["conversation_route"], "ambiguous")
        self.assertIn("route_conversation_state", result["trace_tools"])

    def test_same_thread_restores_planning_context_for_follow_up(self) -> None:
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(),
            checkpointer=InMemorySaver(),
        )
        first = graph.respond(
            {
                "thread_id": "student-thread-001",
                "message": "帮我生成最快毕业方案",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5058"],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            }
        )
        second = graph.respond(
            {
                "thread_id": "student-thread-001",
                "message": "再均衡一点",
            }
        )

        self.assertEqual(first["thread_state"]["turn_count"], 1)
        self.assertEqual(second["thread_state"]["turn_count"], 2)
        self.assertEqual(second["conversation_route"], "structured")
        self.assertEqual(second["intent"], "study_plan")
        self.assertTrue(second["study_plans"]["plans"])
        normalize_trace = next(
            item
            for item in second["trace"]
            if item["tool"] == "normalize_conversation_input"
        )
        self.assertTrue(normalize_trace["restored_context"])
        route_trace = next(
            item for item in second["trace"] if item["tool"] == "route_conversation_state"
        )
        self.assertTrue(route_trace["intent_inherited"])

    def test_different_thread_does_not_inherit_previous_intent(self) -> None:
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(),
            checkpointer=InMemorySaver(),
        )
        graph.respond(
            {
                "thread_id": "student-thread-001",
                "message": "帮我生成最快毕业方案",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": [],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            }
        )
        result = graph.respond(
            {
                "thread_id": "student-thread-002",
                "message": "再均衡一点",
            }
        )

        self.assertEqual(result["thread_state"]["turn_count"], 1)
        self.assertEqual(result["conversation_route"], "ambiguous")

    def test_sqlite_checkpoint_restores_state_after_graph_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "conversation.sqlite3"
            first_connection = sqlite3.connect(database, check_same_thread=False)
            first_graph = CampusPilotConversationGraph(
                CampusPilotConversationAgent(),
                checkpointer=SqliteSaver(first_connection),
            )
            first_graph.respond(
                {
                    "thread_id": "durable-thread-001",
                    "message": "帮我生成最快毕业方案",
                    "program_variant_id": "MONASH-C6001-EL2",
                    "handbook_year": 2026,
                    "study_stream": "Industry Experience",
                    "completed_courses": ["FIT5057", "FIT5058"],
                    "max_courses_per_semester": 4,
                    "start_semester": "2026-S2",
                }
            )
            first_connection.close()

            second_connection = sqlite3.connect(database, check_same_thread=False)
            try:
                recreated_graph = CampusPilotConversationGraph(
                    CampusPilotConversationAgent(),
                    checkpointer=SqliteSaver(second_connection),
                )
                result = recreated_graph.respond(
                    {
                        "thread_id": "durable-thread-001",
                        "message": "再均衡一点",
                    }
                )
            finally:
                second_connection.close()

        self.assertEqual(result["thread_state"]["turn_count"], 2)
        self.assertEqual(result["intent"], "study_plan")
        self.assertTrue(result["study_plans"]["plans"])

    def test_missing_fields_do_not_force_unrelated_next_turn_into_old_route(self) -> None:
        graph = CampusPilotConversationGraph(
            CampusPilotConversationAgent(),
            checkpointer=InMemorySaver(),
        )
        first = graph.respond(
            {
                "thread_id": "topic-switch-thread-001",
                "message": "帮我生成最快毕业方案",
            }
        )
        second = graph.respond(
            {
                "thread_id": "topic-switch-thread-001",
                "message": "今天天气怎么样",
            }
        )

        self.assertTrue(first["thread_state"]["pending_fields"])
        route_trace = next(
            item for item in second["trace"] if item["tool"] == "route_conversation_state"
        )
        self.assertFalse(route_trace["intent_inherited"])
        self.assertEqual(second["conversation_route"], "ambiguous")


if __name__ == "__main__":
    unittest.main()
