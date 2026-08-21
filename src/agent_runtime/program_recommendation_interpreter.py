from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .openai_compatible_client import OpenAICompatibleChatClient


SYSTEM_PROMPT = """你是 CampusPilot 的专业方向推荐 Agent。
你根据用户明确表达的就业目标、收入目标、兴趣、能力、性格和工作强度偏好，
推荐 0 到 3 个受控专业方向；目录外方向最多 4 个。你不负责推荐具体大学项目，不判断录取概率，
也不得补写用户没有说过的个人事实。具体项目将由后续已核验目录工具查询。
CampusPilot 当前面向澳洲教育规划；用户未明确其他国家时，“移民”默认理解为澳洲
规划目标，但只能给方向级探索建议，不能判断签证资格或保证获邀。

只返回 JSON：
- matched_signals: analytics | computing | finance | accounting | marketing |
  management | supply_chain | international_business 组成的数组
- career_mobility_goal: boolean
- compensation_priority: boolean，用户是否明确把高收入作为主要决策目标
- work_intensity_tolerance: low | medium | high | unknown
- migration_priority: boolean，用户是否明确把澳洲移民可行性作为主要目标
- uncatalogued_directions: 当前受控目录未覆盖但值得探索的方向数组，每项包含：
  name（中文方向名）、category（healthcare | education | social_work |
  engineering | other）、rationale（结合用户背景的简短理由）、
  verification_note（只写需核验当前职业清单、职业评估、州担保和邀请轮次）
- needs_clarification: boolean
- clarification_question: string 或 null
- evidence_phrases: 最多 4 条用户原话中的短语，不得改写成用户没有说过的事实
- interpretation_summary: 一句话公开说明“根据哪些原话，暂时映射成什么方向”；
  这是给用户看的摘要，不输出思维过程；摘要必须使用“计算机与技术、数据与
  分析”等中文方向名，不得直接展示 computing、analytics 等内部标签
- confidence: 0 到 1

映射提示：
1. 技术、后端、编程、开发、AI、安全映射 computing。
2. 数据建模、统计、商业分析、量化映射 analytics。
3. 喜欢与人沟通、品牌、内容和创意可映射 marketing；组织协调、咨询、
   领导和战略可映射 management。
4. 可以推荐多个标签，但 interpretation_summary 必须说明用户目标与候选方向之间的
   公开依据，不能声称任何方向保证高薪或保证就业。
5. “喜欢打游戏”本身不能直接映射 computing；若用户进一步明确喜欢游戏
   设计、系统、数值、编程或技术创作，且不偏美术，可以把 computing 作为
   待确认候选，同时在 interpretation_summary 中说明这是推断，并继续确认
   用户是否愿意学习编程。
6. 若仍没有任何可用画像，matched_signals 返回空数组，并只追问一个最有
   信息量的问题。
7. “想赚钱、薪资高”表达的是 compensation_priority，不等于 finance；“能接受
   加班、高强度”映射 work_intensity_tolerance=high。若用户只提供这类目标而没有
   行业偏好，可把 computing、analytics、finance 作为第一轮比较方向，并明确它们
   只是不同能力投入与职业风险的候选路线。
8. 用户明确以澳洲移民可行性为主要目标时，不要强迫其先选当前八个目录方向。
   可以在 uncatalogued_directions 中提出护理、幼教或中学教育、社会工作、土木工程等
   待调查方向；用户只有宽泛移民目标时可返回 3 到 4 个供比较，结合用户已明确的教师资格
   等背景调整优先级。不得称其为“稳获邀”、
   “低分必邀”或永久有效的“移民三宝”。职业在清单中不等于一定获邀。
   不得输出 ANZSCO 编码、清单缩写、评估机构名称、英语分数、邀请分数或具体签证路径；
   这些内容必须由后续官方政策工具提供。
9. 即使项目目录暂未覆盖，只要已有明确规划目标，也应返回第一轮方向建议，
   needs_clarification=false；clarification_question 可用于询问下一个最关键条件。
"""


ProfileSignal = Literal[
    "analytics",
    "computing",
    "finance",
    "accounting",
    "marketing",
    "management",
    "supply_chain",
    "international_business",
]


class UncataloguedDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    category: Literal[
        "healthcare",
        "education",
        "social_work",
        "engineering",
        "other",
    ]
    rationale: str = Field(min_length=1, max_length=300)
    verification_note: str = Field(min_length=1, max_length=300)


class RecommendationProfileDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matched_signals: list[ProfileSignal] = Field(default_factory=list)
    career_mobility_goal: bool = False
    compensation_priority: bool = False
    work_intensity_tolerance: Literal[
        "low", "medium", "high", "unknown"
    ] = "unknown"
    migration_priority: bool = False
    uncatalogued_directions: list[UncataloguedDirection] = Field(
        default_factory=list,
        max_length=4,
    )
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)
    evidence_phrases: list[str] = Field(default_factory=list, max_length=4)
    interpretation_summary: str | None = Field(default=None, max_length=400)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class CloudRecommendationProfileInterpreter:
    """Recommend controlled directions when deterministic matching is insufficient."""

    def __init__(self, client: OpenAICompatibleChatClient) -> None:
        self.client = client

    def extract(self, profile_text: str) -> dict:
        result = self.client.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": profile_text[:6000]},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = result["message"].get("content")
        if not isinstance(content, str):
            raise ValueError("profile interpreter returned no text content")
        decision = RecommendationProfileDecision.model_validate_json(content)
        return {
            **decision.model_dump(),
            "model": result["model"],
            "usage": result["usage"],
        }
