from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot import CampusPilotConversationAgent
from agent_runtime.planning_goal_interpreter import (
    CloudPlanningGoalInterpreter,
)


class FakeChatClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages = []

    def chat(self, messages, **kwargs):
        self.messages = messages
        return {
            "message": {"role": "assistant", "content": self.content},
            "model": "qwen-plus-test",
            "usage": {"total_tokens": 42},
        }


class PlanningGoalInterpreterTest(unittest.TestCase):
    def test_accepts_recruitment_intent_in_typed_schema(self) -> None:
        interpreter = CloudPlanningGoalInterpreter(
            FakeChatClient(
                """
                {
                  "intent": "recruitment_qa",
                  "goal_summary": "查询秋招时间",
                  "needs_clarification": false,
                  "clarification_question": null,
                  "course_code": null,
                  "confidence": 0.91
                }
                """
            )
        )

        result = interpreter.interpret("阿里巴巴秋招什么时候投？")

        self.assertEqual(result["intent"], "recruitment_qa")
        self.assertEqual(result["confidence"], 0.91)

    def test_rejects_fields_outside_the_intent_contract(self) -> None:
        interpreter = CloudPlanningGoalInterpreter(
            FakeChatClient(
                """
                {
                  "intent": "study_plan",
                  "goal_summary": "生成方案",
                  "needs_clarification": false,
                  "clarification_question": null,
                  "course_code": null,
                  "confidence": 0.9,
                  "final_degree_decision": "approved"
                }
                """
            )
        )

        with self.assertRaises(ValueError):
            interpreter.interpret("帮我生成方案")

    def test_uses_history_and_returns_structured_goal(self) -> None:
        client = FakeChatClient(
            """
            {
              "intent": "study_plan",
              "goal_summary": "优先争取实习机会",
              "needs_clarification": true,
              "clarification_question": "你希望从哪学期开始实习？",
              "course_code": null
            }
            """
        )
        interpreter = CloudPlanningGoalInterpreter(client)

        result = interpreter.interpret(
            "第二学期开始",
            [
                {"role": "user", "content": "我想多实习"},
                {
                    "role": "assistant",
                    "content": "你希望从哪学期开始实习？",
                },
            ],
            planning_context={
                "program_variant_id": "MONASH-C6001-EL1",
                "study_stream": "Industry Experience",
            },
        )

        self.assertEqual(result["intent"], "study_plan")
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(client.messages[-2]["role"], "assistant")
        self.assertIn(
            "MONASH-C6001-EL1",
            client.messages[1]["content"],
        )
        self.assertIn(
            "Entry Level",
            client.messages[2]["content"],
        )

    def test_complete_context_suppresses_redundant_cloud_clarification(
        self,
    ) -> None:
        interpreter = CloudPlanningGoalInterpreter(
            FakeChatClient(
                """
                {
                  "intent": "study_plan",
                  "goal_summary": "优先实习",
                  "needs_clarification": true,
                  "clarification_question": "你能接受每学期最多修几门课？",
                  "course_code": null
                }
                """
            )
        )
        agent = CampusPilotConversationAgent(
            goal_interpreter=interpreter
        )

        result = agent.respond(
            {
                "message": "我想多实习",
                "conversation_history": [],
                "program_variant_id": "MONASH-C6001-EL1",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057"],
                "max_courses_per_semester": 3,
                "preserve_policy_flexibility": True,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["next_action"], "review_and_confirm_plan")
        self.assertTrue(result["trace"][0]["clarification_suppressed"])
        self.assertEqual(len(result["study_plans"]["plans"]), 3)
        self.assertEqual(
            result["answer_source"],
            "deterministic_plan_explanation",
        )
        self.assertEqual(result["trace"][0]["source"], "cloud_llm")

    def test_cloud_failure_falls_back_to_deterministic_routing(self) -> None:
        class BrokenInterpreter:
            def interpret(self, query, history, planning_context=None):
                raise TimeoutError("cloud timeout")

        agent = CampusPilotConversationAgent(
            goal_interpreter=BrokenInterpreter()
        )
        result = agent.respond(
            {
                "message": "你好，你可以帮我做什么？",
                "conversation_history": [],
            }
        )

        self.assertEqual(result["intent"], "capabilities")
        self.assertEqual(
            result["answer_source"],
            "deterministic_agent_tools",
        )
        self.assertEqual(
            result["trace"][0]["fallback_reason"],
            "TimeoutError",
        )

    def test_handbook_question_skips_goal_interpreter(self) -> None:
        class CountingInterpreter:
            call_count = 0

            def interpret(self, query, history, planning_context=None):
                self.call_count += 1
                raise AssertionError("Handbook QA must not call this model")

        class FakeHandbookQaAgent:
            def __init__(self) -> None:
                self.program_code = "not-called"

            def answer(self, query, **kwargs):
                self.program_code = kwargs["program_code"]
                return {
                    "message": "FIT5120 使用项目考核。[1]",
                    "evidence": [{"citation_number": 1}],
                    "trace": [{"tool": "search_handbook", "ok": True}],
                    "answer_source": "llm_handbook_grounded_answer",
                    "confidence": "high",
                    "next_action": "review_official_sources",
                }

        interpreter = CountingInterpreter()
        handbook_agent = FakeHandbookQaAgent()
        agent = CampusPilotConversationAgent(
            goal_interpreter=interpreter,
            handbook_qa_agent=handbook_agent,
        )

        result = agent.respond(
            {
                "message": "FIT5120 怎么考核？",
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
            }
        )

        self.assertEqual(result["intent"], "handbook_qa")
        self.assertEqual(interpreter.call_count, 0)
        self.assertIsNone(handbook_agent.program_code)
        self.assertEqual(result["trace"][0]["source"], "deterministic")

    def test_unverified_business_plan_uses_official_handbook_advisory(self) -> None:
        class FakeHandbookQaAgent:
            program_code = None

            def answer(self, query, **kwargs):
                self.program_code = kwargs["program_code"]
                return {
                    "message": "B6022 建议先核对核心课与开课学期。[1]",
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

        handbook_agent = FakeHandbookQaAgent()
        agent = CampusPilotConversationAgent(
            handbook_qa_agent=handbook_agent,
        )

        result = agent.respond(
            {
                "message": "B6022 怎么安排学习路径？",
                # The UI may still carry an older selected program. The
                # explicit program in the user's message must win.
                "program_variant_id": "MONASH-C6001-EL2",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": [],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(result["intent"], "study_plan")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(handbook_agent.program_code, "B6022")
        self.assertIsNone(result["study_plans"])
        self.assertEqual(result["evidence"][0]["citation_number"], 1)
        self.assertIn(
            "route_program_planning_advisory",
            [step["tool"] for step in result["trace"]],
        )

    def test_offline_routing_understands_internship_goal_and_history(
        self,
    ) -> None:
        agent = CampusPilotConversationAgent()
        result = agent.respond(
            {
                "message": "master 第一年",
                "conversation_history": [
                    {
                        "role": "user",
                        "content": "希望多实习，课程不要太满",
                    },
                    {
                        "role": "assistant",
                        "content": "你希望哪个学期开始实习？",
                    },
                ],
                "program_variant_id": "MONASH-C6001-EL1",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057"],
                "max_courses_per_semester": 3,
                "preserve_policy_flexibility": True,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(result["intent"], "study_plan")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["study_plans"]["plans"]), 3)
        self.assertEqual(
            result["study_plans"]["plans"][0]["name"],
            "实习优先",
        )
        self.assertEqual(
            result["study_plans"]["profile"]["max_courses_per_semester"],
            3,
        )
        preference_trace = next(
            item
            for item in result["trace"]
            if item["tool"] == "derive_planning_preferences"
        )
        self.assertEqual(
            preference_trace["planning_goal"],
            "internship_priority",
        )

    def test_understands_academic_and_internship_as_joint_goal(self) -> None:
        agent = CampusPilotConversationAgent()
        result = agent.respond(
            {
                "message": "怎么选课能兼顾学业和实习？",
                "conversation_history": [],
                "program_variant_id": "MONASH-C6001-EL1",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5125"],
                "max_courses_per_semester": 4,
                "preserve_policy_flexibility": False,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(result["intent"], "study_plan")
        self.assertEqual(
            result["study_plans"]["plans"][0]["name"],
            "学业与实习兼顾",
        )
        self.assertEqual(
            result["study_plans"]["profile"]["max_courses_per_semester"],
            4,
        )
        preference_trace = next(
            item
            for item in result["trace"]
            if item["tool"] == "derive_planning_preferences"
        )
        self.assertEqual(
            preference_trace["planning_goals"],
            ["academic_progress", "internship_readiness"],
        )
        self.assertIn("学业进度和实习准备", result["message"])

    def test_workload_balance_keeps_default_four_course_limit(self) -> None:
        agent = CampusPilotConversationAgent()

        result = agent.respond(
            {
                "message": "怎么选课实现负载均衡",
                "program_variant_id": "MONASH-C6001-EL1",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5058"],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(
            result["study_plans"]["profile"]["max_courses_per_semester"],
            4,
        )
        first_plan = result["study_plans"]["plans"][0]
        self.assertEqual(first_plan["name"], "负载均衡优先")
        self.assertEqual(len(first_plan["semesters"][0]["courses"]), 4)

    def test_explicit_two_courses_per_semester_overrides_default(self) -> None:
        agent = CampusPilotConversationAgent()

        result = agent.respond(
            {
                "message": "帮我负载均衡，每学期选两门课",
                "program_variant_id": "MONASH-C6001-EL1",
                "handbook_year": 2026,
                "study_stream": "Industry Experience",
                "completed_courses": ["FIT5057", "FIT5058"],
                "max_courses_per_semester": 4,
                "start_semester": "2026-S2",
            }
        )

        self.assertEqual(
            result["study_plans"]["profile"]["max_courses_per_semester"],
            2,
        )
        self.assertTrue(
            all(
                len(semester["courses"]) <= 2
                for semester in result["study_plans"]["plans"][0]["semesters"]
            )
        )


if __name__ == "__main__":
    unittest.main()
