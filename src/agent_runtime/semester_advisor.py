from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from .ollama_client import OllamaChatClient
from .openai_compatible_client import OpenAICompatibleChatClient


class SemesterChatClient(Protocol):
    model: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]: ...


class OpenAICompatibleSemesterChatClient:
    """Adapt the shared cloud client to the semester advisor contract."""

    provider_name = "cloud_openai_compatible"

    def __init__(self, client: OpenAICompatibleChatClient) -> None:
        self.client = client
        self.model = client.model

    def chat(
        self,
        messages: list[dict[str, Any]],
        **_: Any,
    ) -> dict[str, Any]:
        result = self.client.chat(
            messages,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = result.get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError("cloud semester advisor returned no text content")
        return {"content": content}


class SemesterAdvice(BaseModel):
    summary: str = Field(
        min_length=1,
        max_length=180,
        description="只概括当前学期的课程组合与学习重点",
    )
    arrangement_reason: str = Field(
        min_length=1,
        max_length=400,
        description="只根据开课、先修、负载和方案目标解释当前学期",
    )
    study_strategy: list[str] = Field(
        min_length=2,
        max_length=4,
        description="每周学习、实验、项目协作等可执行动作",
    )
    internship_advice: str = Field(
        min_length=1,
        max_length=300,
        description="只给简历、作品集和投递时间等准备动作",
    )
    risk_notes: list[str] = Field(default_factory=list, max_length=4)
    evidence_ids: list[str] = Field(default_factory=list)


class SemesterAdviceAgent:
    """Generate grounded semester advice without changing the validated plan."""

    def __init__(
        self,
        client: SemesterChatClient | None = None,
        *,
        timeout_seconds: float = 90.0,
    ) -> None:
        self.client = client or OllamaChatClient(
            model=os.environ.get(
                "CAMPUSPILOT_OLLAMA_MODEL",
                "qwen3.5:2b-q4_K_M",
            ),
            base_url=os.environ.get(
                "CAMPUSPILOT_OLLAMA_URL",
                "http://127.0.0.1:11434",
            ),
            timeout_seconds=int(timeout_seconds),
            num_predict=320,
            num_ctx=4096,
            temperature=0.0,
        )
        self.timeout_seconds = timeout_seconds
        self.provider_name = getattr(self.client, "provider_name", "ollama")

    def explain(
        self,
        *,
        program: dict[str, Any],
        plan: dict[str, Any],
        semester: dict[str, Any],
        completed_courses: list[str],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        course_codes = {
            course["course_code"] for course in semester["courses"]
        }
        source_ids = {
            item.get("document_id") or item.get("source_id")
            for item in evidence
            if item.get("document_id") or item.get("source_id")
        }
        facts = {
            "program": {
                "name": program["program_name"],
                "entry_level": program["entry_level"],
                "credits_to_complete": program["credits_to_complete"],
            },
            "plan": {
                "name": plan["name"],
                "description": plan["description"],
                "estimated_semesters": plan["estimated_semesters"],
            },
            "semester": {
                "name": semester["semester"],
                "total_credits": semester["total_credits"],
                "courses": semester["courses"],
            },
            "source_ids": sorted(source_ids),
        }
        schema = SemesterAdvice.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 CampusPilot 的学期规划解释 Agent。"
                    "只允许使用输入事实，不得补充常识或猜测。"
                    "只能讨论 semester.courses 中列出的课程，不能提到其他课程代码。"
                    "输出中不要书写任何课程代码，只使用课程名称。"
                    "只能讨论输入中的当前学期，不得提及其他年份或把课程移到其他学期。"
                    "不得判断签证、移民、课程资格或录用结果。"
                    "不得自行给出每周学习小时数、具体月份投递时间、平台名称、"
                    "成绩代码或历年题等输入中没有的细节。"
                    "不得改变课程和学分。考试状态为 UNKNOWN 时，必须在 risk_notes "
                    "提醒核对官方课程大纲。"
                    "实习建议只描述准备动作。每个字段使用完整、简洁的中文句子。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "解释当前这一个学期，不要总结整个学位。\n"
                    f"唯一可信事实：{json.dumps(facts, ensure_ascii=False)}\n"
                    f"严格输出此 JSON Schema："
                    f"{json.dumps(schema, ensure_ascii=False)}"
                ),
            },
        ]
        validation_issues: list[str] = []
        for attempt in range(2):
            message = self.client.chat(
                messages,
                timeout_seconds=self.timeout_seconds,
                format_schema=schema,
            )
            advice = SemesterAdvice.model_validate_json(
                message.get("content", "")
            )
            advice = self._normalize_course_references(
                advice,
                semester["courses"],
            )
            # Evidence IDs are owned by the backend. Model output must never
            # decide which sources are attached to the final response.
            advice.evidence_ids = sorted(source_ids)
            validation_issues = self._grounding_issues(
                advice,
                course_codes=course_codes,
                semester_year=int(semester["semester"].split()[0]),
                semester_code=semester["semester"].split()[1],
                workload_levels={
                    course.get("workload_level")
                    for course in semester["courses"]
                },
                requires_exam_notice=any(
                    course.get("exam_status") == "UNKNOWN"
                    for course in semester["courses"]
                ),
            )
            if not validation_issues:
                advice.evidence_ids = sorted(source_ids)
                break
            if attempt == 0:
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "content": message.get("content", ""),
                        },
                        {
                            "role": "user",
                            "content": (
                                "上一版未通过事实校验："
                                + "；".join(validation_issues)
                                + "。请删除所有无依据内容并重新输出。"
                            ),
                        },
                    ]
                )
        else:
            raise ValueError(
                "semester advice failed grounding validation: "
                + "; ".join(validation_issues)
            )
        return {
            **advice.model_dump(),
            "answer_source": f"{self.provider_name}_semester_advisor",
            "model": self.client.model,
            "confidence": "medium",
            "next_action": "review_semester_advice",
            "trace": [
                {
                    "tool": "generate_semester_advice",
                    "ok": True,
                    "source": self.provider_name,
                    "model": self.client.model,
                    "attempts": attempt + 1,
                },
                {
                    "tool": "validate_semester_advice",
                    "ok": True,
                    "unsupported_course_codes": [],
                }
            ],
            "trace_tools": [
                "generate_semester_advice",
                "validate_semester_advice",
            ],
            "disclaimer": (
                "课程顺序来自规则引擎；学习与实习建议由语言模型生成，"
                "请结合课程官方教学大纲和个人情况核对。"
            ),
        }

    @staticmethod
    def _normalize_course_references(
        advice: SemesterAdvice,
        courses: list[dict[str, Any]],
    ) -> SemesterAdvice:
        names_by_code = {
            course["course_code"]: course["course_name"]
            for course in courses
        }

        def normalize(value: Any) -> Any:
            if isinstance(value, str):
                normalized = re.sub(
                    r"FIT\d{4}\s*(?:-|至|到)\s*FIT\d{4}",
                    "本学期课程组合",
                    value,
                    flags=re.I,
                )
                for code, name in names_by_code.items():
                    normalized = re.sub(
                        rf"\b{re.escape(code)}\b",
                        name,
                        normalized,
                        flags=re.I,
                    )
                return normalized
            if isinstance(value, list):
                normalized_items = [normalize(item) for item in value]
                return [
                    item
                    for item in normalized_items
                    if not isinstance(item, str) or item.strip()
                ]
            if isinstance(value, dict):
                return {
                    key: normalize(item)
                    for key, item in value.items()
                }
            return value

        return SemesterAdvice.model_validate(normalize(advice.model_dump()))

    @staticmethod
    def _grounding_issues(
        advice: SemesterAdvice,
        *,
        course_codes: set[str],
        semester_year: int,
        semester_code: str,
        workload_levels: set[str | None],
        requires_exam_notice: bool,
    ) -> list[str]:
        payload = advice.model_dump()
        text = json.dumps(payload, ensure_ascii=False)
        mentioned_codes = set(re.findall(r"\bFIT\d{4}\b", text.upper()))
        unsupported_codes = sorted(mentioned_codes - course_codes)
        issues = []
        if unsupported_codes:
            issues.append(
                "出现本学期以外课程：" + "、".join(unsupported_codes)
            )
        mentioned_semesters = {
            (int(year), f"S{number}")
            for year, number in re.findall(
                r"\b(20\d{2})\s*(?:年\s*)?S([12])\b",
                text.upper(),
            )
        }
        unsupported_semesters = sorted(
            mentioned_semesters - {(semester_year, semester_code)}
        )
        if unsupported_semesters:
            issues.append(
                "出现当前学期以外学期："
                + "、".join(
                    f"{year} {code}"
                    for year, code in unsupported_semesters
                )
            )
        if re.search(
            r"FIT\d{4}\s*(?:-|至|到)\s*FIT\d{4}",
            text.upper(),
        ):
            issues.append("使用课程代码范围，无法确认中间课程")
        forbidden = [
            phrase
            for phrase in ["MIG", "签证资格", "移民资格", "保证录用"]
            if phrase.lower() in text.lower()
        ]
        if forbidden:
            issues.append("出现禁止结论：" + "、".join(forbidden))
        unsupported_precision = [
            label
            for pattern, label in [
                (r"每周.{0,8}\d+(?:\.\d+)?\s*小时", "无依据的每周学习时长"),
                (r"\d{1,2}\s*月(?:底|前|起|开始)", "无依据的具体月份"),
                (r"\b(?:MOODLE|NH)\b", "无依据的平台或成绩代码"),
                (r"历年(?:题|试卷)", "无依据的历年试题"),
            ]
            if re.search(pattern, text, flags=re.I)
        ]
        if unsupported_precision:
            issues.append("出现输入事实以外的细节：" + "、".join(unsupported_precision))
        if workload_levels == {"LOW"} and "高难度" in text:
            issues.append("课程负载描述与规则结果冲突")
        if any(
            marker in item
            for item in advice.study_strategy
            for marker in ["//", "],", "\n    "]
        ):
            issues.append("学习建议包含格式污染")
        if (
            requires_exam_notice
            and not any("考试" in note or "考核" in note for note in advice.risk_notes)
        ):
            issues.append("缺少考试信息待核实提示")
        return issues


class UnavailableSemesterAdviceAgent:
    def explain(self, **_: Any) -> dict[str, Any]:
        return {
            "answer_source": "semester_advisor_unavailable",
            "confidence": "low",
            "next_action": "start_local_ollama_and_retry",
            "trace": [
                {
                    "tool": "generate_semester_advice",
                    "ok": False,
                    "source": "ollama",
                    "error": "semester advisor is disabled",
                }
            ],
            "trace_tools": ["generate_semester_advice"],
            "error_code": "SEMESTER_ADVISOR_DISABLED",
            "message": "本地学期建议 Agent 尚未启用。",
        }


class RuleBasedSemesterAdviceAgent:
    """Return useful grounded advice when no language model is available."""

    @staticmethod
    def explain(
        *,
        program: dict[str, Any],
        plan: dict[str, Any],
        semester: dict[str, Any],
        completed_courses: list[str],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del completed_courses, program
        courses = semester.get("courses", [])
        course_names = [course.get("course_name", "未命名课程") for course in courses]
        high_load = [
            course.get("course_name", "未命名课程")
            for course in courses
            if course.get("workload_level") == "HIGH"
        ]
        unknown_assessment = [
            course.get("course_name", "未命名课程")
            for course in courses
            if course.get("exam_status") == "UNKNOWN"
        ]
        source_ids = sorted(
            {
                item.get("document_id") or item.get("source_id")
                for item in evidence
                if item.get("document_id") or item.get("source_id")
            }
        )
        course_summary = "、".join(course_names) if course_names else "当前课程组合"
        risk_notes = []
        if high_load:
            risk_notes.append(
                "高负载课程需要预留连续时间：" + "、".join(high_load)
            )
        if unknown_assessment:
            risk_notes.append(
                "以下课程的考试或考核信息仍需核对开课学期 Unit Guide："
                + "、".join(unknown_assessment)
            )
        if not risk_notes:
            risk_notes.append("选课前再次核对开课学期 Unit Guide 和时间表。")
        return {
            "summary": (
                f"{semester['semester']} 安排 {len(courses)} 门课、"
                f"共 {semester['total_credits']} points。"
            ),
            "arrangement_reason": (
                f"该组合属于“{plan['name']}”方案，课程为{course_summary}；"
                "课程顺序和学分已经过规则引擎校验。"
            ),
            "study_strategy": [
                "开学第一周核对每门课的考核占比和截止日期。",
                "按周拆分实验、作业和项目里程碑，避免截止日前集中完成。",
            ],
            "internship_advice": (
                "把可展示的课程项目持续整理到简历和作品集中，"
                "并根据本学期实际负载决定投递节奏。"
            ),
            "risk_notes": risk_notes,
            "evidence_ids": source_ids,
            "answer_source": "structured_rules_semester_fallback",
            "model": "deterministic-rule-fallback",
            "confidence": "low",
            "next_action": "review_semester_advice",
            "trace": [
                {
                    "tool": "generate_rule_based_semester_advice",
                    "ok": True,
                    "source": "structured_rules",
                    "model": "deterministic-rule-fallback",
                    "attempts": 1,
                }
            ],
            "trace_tools": ["generate_rule_based_semester_advice"],
            "disclaimer": (
                "当前为无模型降级说明，只使用已校验规则和课程字段；"
                "请结合课程官方教学大纲和个人情况核对。"
            ),
        }


class ResilientSemesterAdviceAgent:
    def __init__(
        self,
        primary: SemesterAdviceAgent,
        fallback: RuleBasedSemesterAdviceAgent | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or RuleBasedSemesterAdviceAgent()

    def explain(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return self.primary.explain(**kwargs)
        except Exception as exc:
            result = self.fallback.explain(**kwargs)
            result["trace"].insert(
                0,
                {
                    "tool": "generate_semester_advice",
                    "ok": False,
                    "source": self.primary.provider_name,
                    "error": type(exc).__name__,
                },
            )
            result["trace_tools"] = [
                "generate_semester_advice",
                "generate_rule_based_semester_advice",
            ]
            return result


def create_semester_advice_agent() -> (
    SemesterAdviceAgent
    | ResilientSemesterAdviceAgent
    | RuleBasedSemesterAdviceAgent
):
    return create_semester_advice_agent_with_cloud()


def create_semester_advice_agent_with_cloud(
    cloud_client: OpenAICompatibleChatClient | None = None,
) -> SemesterAdviceAgent | ResilientSemesterAdviceAgent | RuleBasedSemesterAdviceAgent:
    timeout_seconds = float(
        os.environ.get("CAMPUSPILOT_LLM_TIMEOUT_SECONDS", "90")
    )
    if cloud_client is not None:
        return ResilientSemesterAdviceAgent(
            SemesterAdviceAgent(
                client=OpenAICompatibleSemesterChatClient(cloud_client),
                timeout_seconds=timeout_seconds,
            )
        )
    enabled: Literal["0", "1"] = (
        "1"
        if os.environ.get("CAMPUSPILOT_LLM_ENABLED", "0").lower()
        in {"1", "true", "yes"}
        else "0"
    )
    if enabled == "0":
        return RuleBasedSemesterAdviceAgent()
    return ResilientSemesterAdviceAgent(
        SemesterAdviceAgent(timeout_seconds=timeout_seconds)
    )
