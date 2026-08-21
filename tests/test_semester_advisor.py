from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.openai_compatible_client import (  # noqa: E402
    OpenAICompatibleChatClient,
)
from agent_runtime.semester_advisor import (  # noqa: E402
    OpenAICompatibleSemesterChatClient,
    ResilientSemesterAdviceAgent,
    SemesterAdviceAgent,
    create_semester_advice_agent_with_cloud,
)


class FakeOllamaClient:
    model = "qwen3.5:0.8b"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return {
            "content": json.dumps(
                {
                    "summary": "先打基础，再进入项目课程。",
                    "arrangement_reason": "先修顺序和开课学期均已校验。",
                    "study_strategy": ["每周完成实验", "建立错题记录"],
                    "internship_advice": "同步整理课程项目到作品集。",
                    "risk_notes": ["考试形式需要核对官方课程大纲。"],
                    "evidence_ids": ["SOURCE-1"],
                },
                ensure_ascii=False,
            )
        }


class SemesterAdviceAgentTest(unittest.TestCase):
    @staticmethod
    def _input() -> dict:
        return {
            "program": {
                "program_name": "Master of Information Technology",
                "entry_level": "ENTRY_LEVEL_1",
                "credits_to_complete": 96,
            },
            "plan": {
                "plan_id": "fastest",
                "name": "最快完成",
                "description": "按容量安排",
                "estimated_semesters": 4,
            },
            "semester": {
                "semester": "2026 S2",
                "total_credits": 24,
                "courses": [
                    {
                        "course_code": "FIT9131",
                        "course_name": "Programming foundations in Java",
                        "workload_level": "LOW",
                        "exam_status": "UNKNOWN",
                    }
                ],
            },
            "completed_courses": [],
            "evidence": [{"document_id": "SOURCE-1"}],
        }

    def test_adapts_openai_compatible_client_to_semester_contract(self) -> None:
        def handler(request):
            import httpx

            body = json.loads(request.content)
            self.assertEqual(body["response_format"], {"type": "json_object"})
            content = {
                "summary": "本学期先完成基础课程。",
                "arrangement_reason": "顺序和学分已经校验。",
                "study_strategy": ["每周完成实验", "每周整理笔记"],
                "internship_advice": "持续整理课程项目。",
                "risk_notes": ["考试信息需要核对官方课程大纲。"],
                "evidence_ids": [],
            }
            return httpx.Response(
                200,
                json={
                    "model": "qwen-test",
                    "choices": [{"message": {"content": json.dumps(content)}}],
                },
            )

        import httpx

        cloud = OpenAICompatibleChatClient(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="qwen-test",
            transport=httpx.MockTransport(handler),
        )
        agent = SemesterAdviceAgent(
            client=OpenAICompatibleSemesterChatClient(cloud)
        )

        result = agent.explain(**self._input())

        self.assertEqual(
            result["answer_source"],
            "cloud_openai_compatible_semester_advisor",
        )
        self.assertEqual(result["trace"][0]["source"], "cloud_openai_compatible")

    def test_cloud_factory_falls_back_to_rules_when_model_output_fails(self) -> None:
        class BrokenCloudClient:
            model = "broken-cloud"

            def chat(self, *args, **kwargs):
                raise TimeoutError("cloud timed out")

        with patch.dict(os.environ, {"CAMPUSPILOT_LLM_TIMEOUT_SECONDS": "1"}):
            agent = create_semester_advice_agent_with_cloud(BrokenCloudClient())

        self.assertIsInstance(agent, ResilientSemesterAdviceAgent)
        result = agent.explain(**self._input())

        self.assertEqual(result["answer_source"], "structured_rules_semester_fallback")
        self.assertEqual(result["trace"][0]["error"], "TimeoutError")
        self.assertIn("generate_rule_based_semester_advice", result["trace_tools"])

    def test_factory_uses_rule_fallback_when_all_llms_are_disabled(self) -> None:
        with patch.dict(
            os.environ,
            {"CAMPUSPILOT_LLM_ENABLED": "0"},
        ):
            agent = create_semester_advice_agent_with_cloud()

        result = agent.explain(**self._input())

        self.assertEqual(result["model"], "deterministic-rule-fallback")
        self.assertEqual(result["confidence"], "low")

    def test_uses_structured_output_and_preserves_grounded_facts(self) -> None:
        client = FakeOllamaClient()
        agent = SemesterAdviceAgent(client=client, timeout_seconds=12)

        result = agent.explain(
            program={
                "program_name": "Master of Information Technology",
                "entry_level": "ENTRY_LEVEL_2",
                "credits_to_complete": 72,
            },
            plan={
                "plan_id": "fastest",
                "name": "最快完成",
                "description": "按容量安排",
                "estimated_semesters": 3,
            },
            semester={
                "semester": "2026 S2",
                "total_credits": 24,
                "courses": [
                    {
                        "course_code": "FIT5137",
                        "course_name": "Advanced database technology",
                    }
                ],
            },
            completed_courses=["FIT5057"],
            evidence=[
                {
                    "document_id": "SOURCE-1",
                    "title": "Official handbook",
                    "content": "FIT5137 is offered in semester 2.",
                }
            ],
        )

        self.assertEqual(result["answer_source"], "ollama_semester_advisor")
        self.assertEqual(result["model"], "qwen3.5:0.8b")
        self.assertEqual(
            result["trace_tools"],
            ["generate_semester_advice", "validate_semester_advice"],
        )
        self.assertEqual(client.calls[0]["timeout_seconds"], 12)
        schema = client.calls[0]["format_schema"]
        self.assertIn("arrangement_reason", schema["properties"])
        prompt = client.calls[0]["messages"][1]["content"]
        self.assertIn("FIT5137", prompt)
        self.assertIn("SOURCE-1", prompt)
        self.assertEqual(result["evidence_ids"], ["SOURCE-1"])

    def test_allows_handbook_year_but_backend_replaces_model_evidence(
        self,
    ) -> None:
        class HandbookYearClient(FakeOllamaClient):
            def chat(self, messages, **kwargs):
                self.calls.append({"messages": messages, **kwargs})
                return {
                    "content": json.dumps(
                        {
                            "summary": "按 2026 Handbook 规则安排本学期。",
                            "arrangement_reason": "先修和开课学期已校验。",
                            "study_strategy": ["每周完成实验", "每周整理笔记"],
                            "internship_advice": "整理课程项目。",
                            "risk_notes": ["考核形式需要核对官方课程大纲。"],
                            "evidence_ids": ["MODEL-MADE-UP-ID"],
                        },
                        ensure_ascii=False,
                    )
                }

        agent = SemesterAdviceAgent(client=HandbookYearClient())
        result = agent.explain(
            program={
                "program_name": "MIT",
                "entry_level": "ENTRY_LEVEL_2",
                "credits_to_complete": 72,
            },
            plan={
                "name": "最快完成",
                "description": "按容量安排",
                "estimated_semesters": 3,
            },
            semester={
                "semester": "2027 S1",
                "total_credits": 6,
                "courses": [
                    {
                        "course_code": "FIT5137",
                        "course_name": "Advanced database technology",
                        "workload_level": "MEDIUM",
                        "exam_status": "UNKNOWN",
                    }
                ],
            },
            completed_courses=[],
            evidence=[
                {
                    "document_id": "SOURCE-1",
                    "title": "2026 Official handbook",
                    "content": "FIT5137 is offered in semester 1.",
                }
            ],
        )

        self.assertEqual(result["evidence_ids"], ["SOURCE-1"])
        self.assertEqual(result["trace"][0]["attempts"], 1)

    def test_retries_when_answer_names_a_different_full_semester(
        self,
    ) -> None:
        class WrongSemesterClient(FakeOllamaClient):
            def chat(self, messages, **kwargs):
                self.calls.append({"messages": messages, **kwargs})
                semester = "2028 S2" if len(self.calls) == 1 else "2027 S1"
                return {
                    "content": json.dumps(
                        {
                            "summary": f"当前安排是 {semester}。",
                            "arrangement_reason": "规则已校验。",
                            "study_strategy": ["每周复盘", "按时完成实验"],
                            "internship_advice": "整理项目。",
                            "risk_notes": [],
                            "evidence_ids": [],
                        },
                        ensure_ascii=False,
                    )
                }

        client = WrongSemesterClient()
        agent = SemesterAdviceAgent(client=client)
        result = agent.explain(
            program={
                "program_name": "MIT",
                "entry_level": "ENTRY_LEVEL_2",
                "credits_to_complete": 72,
            },
            plan={
                "name": "最快完成",
                "description": "按容量安排",
                "estimated_semesters": 3,
            },
            semester={
                "semester": "2027 S1",
                "total_credits": 6,
                "courses": [
                    {
                        "course_code": "FIT5137",
                        "course_name": "Advanced database technology",
                        "workload_level": "MEDIUM",
                    }
                ],
            },
            completed_courses=[],
            evidence=[],
        )

        self.assertEqual(len(client.calls), 2)
        self.assertIn("2027 S1", result["summary"])

    def test_retries_when_advice_invents_precise_schedule_or_platform(self) -> None:
        class InventedDetailClient(FakeOllamaClient):
            def chat(self, messages, **kwargs):
                self.calls.append({"messages": messages, **kwargs})
                if len(self.calls) == 1:
                    strategy = [
                        "每周学习 6 小时并查看 Moodle。",
                        "练习历年题。",
                    ]
                    internship = "8 月底完成作品集，9 月开始投递。"
                else:
                    strategy = ["每周完成实验", "按周维护项目记录"]
                    internship = "持续整理课程项目到作品集。"
                return {
                    "content": json.dumps(
                        {
                            "summary": "本学期完成基础课程。",
                            "arrangement_reason": "课程顺序已经校验。",
                            "study_strategy": strategy,
                            "internship_advice": internship,
                            "risk_notes": ["考试信息需核对官方课程大纲。"],
                            "evidence_ids": [],
                        },
                        ensure_ascii=False,
                    )
                }

        client = InventedDetailClient()
        result = SemesterAdviceAgent(client=client).explain(**self._input())

        self.assertEqual(len(client.calls), 2)
        self.assertNotIn("Moodle", json.dumps(result, ensure_ascii=False))
        retry_prompt = client.calls[1]["messages"][-1]["content"]
        self.assertIn("输入事实以外的细节", retry_prompt)

    def test_rejects_unstructured_model_output(self) -> None:
        class InvalidClient(FakeOllamaClient):
            def chat(self, messages, **kwargs):
                return {"content": "随便安排一下就可以。"}

        agent = SemesterAdviceAgent(client=InvalidClient())

        with self.assertRaises(ValueError):
            agent.explain(
                program={
                    "program_name": "MIT",
                    "entry_level": "ENTRY_LEVEL_2",
                    "credits_to_complete": 72,
                },
                plan={
                    "name": "最快完成",
                    "description": "按容量安排",
                    "estimated_semesters": 3,
                },
                semester={
                    "semester": "2026 S2",
                    "total_credits": 0,
                    "courses": [],
                },
                completed_courses=[],
                evidence=[],
            )

    def test_retries_once_when_first_answer_mentions_outside_course(
        self,
    ) -> None:
        class RetryClient(FakeOllamaClient):
            def chat(self, messages, **kwargs):
                self.calls.append({"messages": messages, **kwargs})
                course = (
                    "FIT9999"
                    if len(self.calls) == 1
                    else "Advanced database technology"
                )
                return {
                    "content": json.dumps(
                        {
                            "summary": f"本学期重点学习 {course}。",
                            "arrangement_reason": "课程顺序已经规则校验。",
                            "study_strategy": ["每周完成实验", "整理项目记录"],
                            "internship_advice": "更新简历和作品集。",
                            "risk_notes": [],
                            "evidence_ids": [],
                        },
                        ensure_ascii=False,
                    )
                }

        client = RetryClient()
        agent = SemesterAdviceAgent(client=client)
        result = agent.explain(
            program={
                "program_name": "MIT",
                "entry_level": "ENTRY_LEVEL_2",
                "credits_to_complete": 72,
            },
            plan={
                "name": "最快完成",
                "description": "按容量安排",
                "estimated_semesters": 3,
            },
            semester={
                "semester": "2026 S2",
                "total_credits": 6,
                "courses": [
                    {
                        "course_code": "FIT5137",
                        "course_name": "Advanced database technology",
                        "workload_level": "MEDIUM",
                    }
                ],
            },
            completed_courses=[],
            evidence=[],
        )

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result["trace"][0]["attempts"], 2)
        self.assertNotIn("FIT9999", result["summary"])


if __name__ == "__main__":
    unittest.main()
