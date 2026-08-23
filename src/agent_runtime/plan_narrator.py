from __future__ import annotations

import json
import re
from typing import Any

from .openai_compatible_client import OpenAICompatibleChatClient
from .llm_errors import CampusPilotLLMError, normalize_llm_exception
from .runtime_logging import log_event, runtime_logger


LOGGER = runtime_logger("planner")


class StudyPlanNarrator:
    """Explain validated plans naturally without changing rule outputs."""

    def __init__(
        self,
        client: OpenAICompatibleChatClient | None = None,
    ) -> None:
        self.client = client

    def narrate(
        self,
        *,
        query: str,
        preferences: dict[str, Any],
        plans: dict[str, Any],
    ) -> dict[str, Any]:
        fallback = self._fallback_message(preferences, plans)
        if self.client is None:
            return {
                "message": fallback,
                "answer_source": "deterministic_plan_explanation",
                "trace": [
                    {
                        "tool": "generate_plan_explanation",
                        "ok": True,
                        "source": "deterministic_fallback",
                    }
                ],
            }

        facts = self._plan_facts(plans)
        try:
            result = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 CampusPilot 的学习规划说明助手。"
                            "规则引擎已经生成并校验方案，你只能解释给定事实，"
                            "不得新增、删除或移动课程，不得修改学分和学期数。"
                            "负载均衡表示搭配不同难度课程，不等于降低课程数量；"
                            "除非结构化结果确实采用两门上限，否则不得声称每学期两门。"
                            "先回应用户真正关心的取舍，再解释首选方案为什么合适，"
                            "最后提醒用户查看逐学期方案。使用自然、具体的简体中文，"
                            "不要使用客服模板口吻，控制在 180 字以内。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "用户原话": query,
                                "结构化目标": preferences,
                                "规则引擎结果": facts,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0.2,
            )
            content = result["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("plan narrator returned an empty answer")
            self._validate_course_codes(content, facts["course_codes"])
            return {
                "message": content.strip(),
                "answer_source": (
                    "llm_plan_explanation_with_deterministic_tools"
                ),
                "trace": [
                    {
                        "tool": "generate_plan_explanation",
                        "ok": True,
                        "source": "openai_compatible_llm",
                        "model": result.get("model"),
                    }
                ],
            }
        except Exception as exc:
            error = normalize_llm_exception(
                exc,
                provider="openai_compatible",
                model=getattr(self.client, "model", None),
            )
            log_event(
                LOGGER,
                "llm_fallback_activated",
                level=30,
                component="plan_narrator",
                error_category=error.category.value,
                fallback="deterministic_plan_explanation",
            )
            return {
                "message": fallback,
                "answer_source": "deterministic_plan_explanation",
                "degraded": True,
                "degradation": {
                    "component": "llm",
                    "reason": error.category.value,
                },
                "trace": [
                    {
                        "tool": "generate_plan_explanation",
                        "ok": False,
                        "source": "openai_compatible_llm",
                        "error": error.category.value,
                    },
                    {
                        "tool": "fallback_to_plan_summary",
                        "ok": True,
                        "source": "deterministic_fallback",
                    },
                ],
            }

    @staticmethod
    def _plan_facts(plans: dict[str, Any]) -> dict[str, Any]:
        plan_summaries = []
        course_codes: set[str] = set()
        for plan in plans["plans"]:
            semesters = []
            for semester in plan["semesters"]:
                codes = [
                    course["course_code"]
                    for course in semester["courses"]
                ]
                course_codes.update(codes)
                semesters.append(
                    {
                        "semester": semester["semester"],
                        "course_codes": codes,
                        "total_credits": semester["total_credits"],
                    }
                )
            plan_summaries.append(
                {
                    "name": plan["name"],
                    "description": plan["description"],
                    "estimated_semesters": plan["estimated_semesters"],
                    "semesters": semesters,
                }
            )
        return {
            "completed_credits": plans["completed_credits"],
            "remaining_credits": plans["remaining_credits"],
            "all_valid": plans["validation"]["all_valid"],
            "plans": plan_summaries,
            "course_codes": sorted(course_codes),
        }

    @staticmethod
    def _validate_course_codes(
        answer: str,
        allowed_codes: list[str],
    ) -> None:
        mentioned = {
            value.upper()
            for value in re.findall(r"\b[A-Za-z]{2,5}\d{4}\b", answer)
        }
        if not mentioned.issubset(set(allowed_codes)):
            raise ValueError("plan explanation mentions an unknown course")

    @staticmethod
    def _fallback_message(
        preferences: dict[str, Any],
        plans: dict[str, Any],
    ) -> str:
        first = plans["plans"][0]
        goal = preferences["planning_goal"]
        if goal == "study_internship_balance":
            opening = (
                "你希望学业进度和实习准备两边都不耽误，所以我没有把课程"
                "压到最短时间内，而是优先推荐“学业与实习兼顾”方案。"
            )
        elif goal == "internship_priority":
            opening = "你更看重实习机会，因此我优先降低学期负担并安排实践课程。"
        elif goal == "recruitment_readiness":
            target_year = preferences.get("target_recruitment_year")
            target = f"{target_year} 年秋招" if target_year else "目标秋招"
            opening = (
                f"你的目标是参加{target}，因此首选方案会控制每学期负担，"
                "把实践、项目积累、投递和面试准备放进同一条时间线。"
            )
        elif goal == "workload_balance":
            opening = (
                "你希望把课程负载分配得更均匀，因此我优先展示负载均衡方案；"
                "课程数量仍采用你设置的单学期上限。"
            )
        elif goal == "fastest_completion":
            opening = "你更看重完成速度，因此我优先展示最快毕业方案。"
        else:
            opening = "你的目标还没有单一优先级，因此我保留三种节奏供你比较。"
        return (
            f"{opening}当前已计入 {plans['completed_credits']} points，"
            f"还需规划 {plans['remaining_credits']} points；首选方案预计 "
            f"{first['estimated_semesters']} 个学期完成。"
            "你可以展开每个学期查看课程组合和安排原因。"
        )
