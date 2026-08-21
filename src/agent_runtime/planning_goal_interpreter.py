from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .openai_compatible_client import OpenAICompatibleChatClient
from .australian_terminology import AustralianTerminologyGlossary


SYSTEM_PROMPT = """你是 CampusPilot 的用户目标理解模块。
你只负责识别意图和需要澄清的信息，不负责判断课程规则，也不得编造学校事实。
请只返回 JSON，对象字段如下：
- intent: capabilities | degree_progress | study_plan | program_recommendation | course_role | handbook_qa | recruitment_qa | ambiguous
- goal_summary: 对用户明确目标的简短中文概括
- needs_clarification: boolean
- clarification_question: string 或 null
- course_code: string 或 null

规则：
1. 用户想实习、均衡负担、尽快毕业或保留规划弹性，都属于 study_plan。
2. 目标过于宽泛但仍能生成多方案时，不要无意义追问。
3. 只有缺少会显著改变方案的个人偏好时才追问一个问题。
4. 课程代码必须来自用户原文，不得自行补充。
5. 已提供的结构化规划上下文是可信输入，不得再次询问其中已有的信息。
6. 用户是在回答上一轮问题时，要结合最近对话恢复原始目标，不能重复同一问题。
7. 关于项目结构、课程考核、工作量、先修要求或 Handbook 事实的问题属于 handbook_qa。
8. 用户还没有确定专业，希望根据就业目标、成绩、性格、兴趣或偏好推荐专业和硕士项目，属于 program_recommendation。
9. 用户希望根据澳洲移民可行性、获邀目标或州担保方向选择专业，也属于
   program_recommendation；意图节点只负责路由，不得给移民资格或分数结论。

澳洲术语以本轮检索到的术语知识为准。不要用国内“几年级”解释澳洲授课型硕士。
"""


IntentName = Literal[
    "capabilities",
    "degree_progress",
    "study_plan",
    "program_recommendation",
    "course_role",
    "handbook_qa",
    "recruitment_qa",
    "ambiguous",
]


class IntentDecision(BaseModel):
    """Typed language-understanding output; it never carries rule results."""

    model_config = ConfigDict(extra="forbid")

    intent: IntentName
    goal_summary: str = Field(min_length=1, max_length=500)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)
    course_code: str | None = Field(default=None, max_length=20)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    route_reason: str = Field(default="llm_structured_intent", max_length=100)


class CloudPlanningGoalInterpreter:
    """Use an LLM for language understanding, never for rule decisions."""

    def __init__(
        self,
        client: OpenAICompatibleChatClient,
        glossary: AustralianTerminologyGlossary | None = None,
    ) -> None:
        self.client = client
        self.glossary = glossary or AustralianTerminologyGlossary()

    def interpret(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
        planning_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conversation = [
            {
                "role": item["role"],
                "content": item["content"][:2000],
            }
            for item in (history or [])[-6:]
            if item.get("role") in {"user", "assistant"}
            and item.get("content")
        ]
        terminology_query = " ".join(
            [
                query,
                *(item["content"] for item in conversation),
                json.dumps(planning_context or {}, ensure_ascii=False),
            ]
        )
        terminology = self.glossary.prompt_context(terminology_query)
        result = self.client.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "system",
                    "content": (
                        "当前页面已确认的结构化规划上下文："
                        + json.dumps(
                            planning_context or {},
                            ensure_ascii=False,
                        )
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "本轮检索到的澳洲高等教育术语知识："
                        + json.dumps(terminology, ensure_ascii=False)
                    ),
                },
                *conversation,
                {"role": "user", "content": query},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = result["message"].get("content")
        if not isinstance(content, str):
            raise ValueError("goal interpreter returned no text content")
        decision = IntentDecision.model_validate_json(content)
        return {
            **decision.model_dump(),
            "terminology_terms": [
                item["term"] for item in terminology
            ],
            "model": result["model"],
            "usage": result["usage"],
        }
