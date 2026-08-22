from __future__ import annotations

import json
import re
from typing import Any

from .openai_compatible_client import OpenAICompatibleChatClient


class ProgramRecommendationNarrator:
    """Turn grounded direction and catalog results into a natural Pia reply."""

    def __init__(
        self,
        client: OpenAICompatibleChatClient | None = None,
    ) -> None:
        self.client = client

    def narrate(
        self,
        *,
        query: str,
        profile: dict[str, Any],
        recommendations: list[dict[str, Any]],
        fallback_message: str,
    ) -> dict[str, Any]:
        if self.client is None:
            return self._fallback(fallback_message, reason="llm_disabled")

        facts = {
            "用户当前表达": query,
            "候选方向": profile.get("matched_signals", []),
            "公开推断说明": profile.get("interpretation_summary"),
            "用户证据短语": profile.get("evidence_phrases", []),
            "收入优先": profile.get("compensation_priority", False),
            "工作强度接受度": profile.get(
                "work_intensity_tolerance", "unknown"
            ),
            "澳洲移民规划优先": profile.get("migration_priority", False),
            "回答必须包含的边界": (
                "当前项目或方向候选不是按移民可行性排序；职业清单、职业评估、"
                "州担保和邀请情况必须按最新官方信息核验。"
                if profile.get("migration_priority", False)
                else None
            ),
            "暂未收录的方向候选": profile.get(
                "uncatalogued_directions", []
            ),
            "目录候选数量": len(recommendations),
            "可探索岗位": self._unique_values(
                recommendations, "roles", limit=8
            ),
            "起步准备": self._unique_values(
                recommendations, "preparation", limit=6
            ),
        }
        try:
            messages = [
                    {
                        "role": "system",
                        "content": (
                            "你是 CampusPilot 的留学专业与职业探索 Agent Pia。"
                            "请基于给定事实自由组织一段自然、有判断力的简体中文回复。"
                            "开头先像真实顾问一样回应用户此刻的处境：复述与决策有关的"
                            "本科院校、已有专业、转向动机、目标地区和目标岗位，但不要"
                            "机械罗列字段，也不要把用户感受写成客观市场结论。随后解释"
                            "你如何理解用户的目标，再比较候选方向的工作内容、"
                            "能力投入和取舍，给出当前更值得优先探索的方向及原因，最后"
                            "提出一个能推动决策的具体问题。允许提出职业探索建议，但要"
                            "明确它们是阶段性判断，不是就业或薪资保证。不得编造新的"
                            "学校、项目、课程、薪资数字、录取要求和官方事实；无需复述"
                            "具体学校和项目将由后续官方目录卡片展示，不要在正文中"
                            "评价、比较或复述具体学校与项目。不要声称查看了未提供的"
                            "资料，不要以‘基于目前得到的候选方向’或‘我筛出了几个项目’"
                            "这类系统模板开头，不要使用‘路线1’模板。有目录项目时，项目"
                            "卡片只代表当前目录中的课程方向候选，不代表它们已经按留澳就业"
                            "或移民可行性排序；没有目录项目时，应自然解释当前只能给方向级"
                            "建议，不要假装存在项目卡片。用户以移民规划为目标时，正文必须"
                            "明确职业清单、职业评估、州担保和邀请情况需要按最新官方信息"
                            "核验。可以讨论用户的澳洲移民"
                            "规划目标和需要继续核验的方向，但不得判断签证或移民资格，"
                            "不得声称某方向低分、容易或保证获邀；必须说明职业清单、"
                            "职业评估、州担保和邀请结果具有时效性。没有官方政策证据"
                            "时，不得输出职业代码、清单缩写、评估机构、英语分数或"
                            "邀请分数，也不得按移民难度给方向排序；只能比较学习投入、"
                            "工作内容和用户背景衔接。控制在 260 至 500 个汉字。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"用户对话": query, "可用事实": facts},
                            ensure_ascii=False,
                        ),
                    },
                ]
            result: dict[str, Any] | None = None
            content = ""
            retry_count = 0
            for attempt in range(2):
                result = self.client.chat(messages, temperature=0.55)
                candidate = result["message"].get("content")
                if not isinstance(candidate, str) or not candidate.strip():
                    raise ValueError(
                        "recommendation narrator returned no content"
                    )
                content = candidate.strip()
                try:
                    self._validate(content)
                    break
                except ValueError:
                    if attempt == 1:
                        raise
                    retry_count += 1
                    messages.extend(
                        [
                            {"role": "assistant", "content": content},
                            {
                                "role": "user",
                                "content": (
                                    "上一次回答加入了未提供的高风险事实或结果保证。"
                                    "请删除这些内容，只基于给定方向、职业探索建议和"
                                    "项目目录事实重新回答。"
                                ),
                            },
                        ]
                    )
            assert result is not None
            return {
                "message": content,
                "answer_source": (
                    "llm_program_recommendation_with_catalog"
                    if recommendations
                    else "llm_direction_recommendation_without_catalog"
                ),
                "trace": [
                    {
                        "tool": "generate_natural_recommendation",
                        "ok": True,
                        "source": "openai_compatible_llm",
                        "model": result.get("model"),
                        "retry_count": retry_count,
                    }
                ],
            }
        except Exception as exc:
            return self._fallback(
                fallback_message,
                reason=type(exc).__name__,
            )

    def clarify(
        self,
        *,
        query: str,
        evidence_phrases: list[str],
        suggested_question: str,
        fallback_message: str,
    ) -> dict[str, Any]:
        if self.client is None:
            return self._fallback(fallback_message, reason="llm_disabled")
        try:
            result = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 CampusPilot 的留学规划 Agent Pia。用户现在提供的"
                            "信息还不足以推荐专业。请用自然、克制的简体中文回应：先"
                            "接住用户真正担心或取舍的事情，再说明为什么还需要一个"
                            "关键信息，最后只问一个具体问题。不要说‘可以先不选专业’、"
                            "‘我记下了’、‘现在还差一步’，不要列举一串职业让用户"
                            "机械选择，不得虚构用户背景。控制在 80 至 180 个汉字。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "用户表达": query,
                                "已提取的原话": evidence_phrases,
                                "可参考但必须自然改写的问题": suggested_question,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0.45,
            )
            content = result["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("clarification narrator returned no content")
            return {
                "message": content.strip(),
                "answer_source": "llm_recommendation_clarification",
                "trace": [
                    {
                        "tool": "generate_natural_clarification",
                        "ok": True,
                        "source": "openai_compatible_llm",
                        "model": result.get("model"),
                    }
                ],
            }
        except Exception as exc:
            return self._fallback(
                fallback_message,
                reason=type(exc).__name__,
            )

    @staticmethod
    def _validate(content: str) -> None:
        forbidden_claims = (
            "保证录取",
            "一定录取",
            "保证高薪",
            "一定高薪",
            "保证就业",
            "保证移民",
            "一定能移民",
            "确保获邀",
            "一定获邀",
            "符合移民资格",
            "满足移民资格",
            "符合签证资格",
            "满足签证资格",
        )
        if any(
            ProgramRecommendationNarrator._contains_unqualified_claim(
                content, claim
            )
            for claim in forbidden_claims
        ):
            raise ValueError("recommendation contains a prohibited guarantee")
        if re.search(
            r"ANZSCO|MLTSSL|STSOL|CSOL|AASW|AITSL|ANMAC|AHPRA|NCAS|"
            r"\b\d{6}\b|获邀分数|EOI分数|邀请分数",
            content,
            flags=re.IGNORECASE,
        ):
            raise ValueError("recommendation contains unverified policy detail")

    @staticmethod
    def _contains_unqualified_claim(content: str, claim: str) -> bool:
        boundary_markers = (
            "不能",
            "无法",
            "并非",
            "不代表",
            "不等于",
            "不能据此",
            "不可据此",
            "需核验",
            "需要核验",
            "尚未核验",
            "不得",
        )
        clauses = re.split(r"[。！？；\n]", content)
        return any(
            claim in clause
            and not any(marker in clause for marker in boundary_markers)
            for clause in clauses
        )

    @staticmethod
    def _unique_values(
        recommendations: list[dict[str, Any]],
        field: str,
        *,
        limit: int,
    ) -> list[str]:
        values: list[str] = []
        for item in recommendations:
            for value in item.get("career_path", {}).get(field, []):
                if value not in values:
                    values.append(value)
        return values[:limit]

    @staticmethod
    def _fallback(message: str, *, reason: str) -> dict[str, Any]:
        return {
            "message": message,
            "answer_source": "catalog_program_recommendation_agent",
            "trace": [
                {
                    "tool": "generate_natural_recommendation",
                    "ok": reason == "llm_disabled",
                    "source": "deterministic_fallback",
                    "reason": reason,
                }
            ],
        }
