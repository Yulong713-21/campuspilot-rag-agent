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
            "候选方向": profile.get("matched_signals", []),
            "公开推断说明": profile.get("interpretation_summary"),
            "用户证据短语": profile.get("evidence_phrases", []),
            "收入优先": profile.get("compensation_priority", False),
            "工作强度接受度": profile.get(
                "work_intensity_tolerance", "unknown"
            ),
            "澳洲移民规划优先": profile.get("migration_priority", False),
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
                            "先解释你如何理解用户的目标，再比较候选方向的工作内容、"
                            "能力投入和取舍，给出当前更值得优先探索的方向及原因，最后"
                            "提出一个能推动决策的具体问题。允许提出职业探索建议，但要"
                            "明确它们是阶段性判断，不是就业或薪资保证。不得编造新的"
                            "学校、项目、课程、薪资数字、录取要求和官方事实；无需复述"
                            "具体学校和项目将由后续官方目录卡片展示，不要在正文中"
                            "评价、比较或复述具体学校与项目。不要声称查看了未提供的"
                            "资料，不要使用‘路线1’模板。可以讨论用户的澳洲移民"
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

    @staticmethod
    def _validate(content: str) -> None:
        forbidden_claims = (
            "保证录取",
            "一定录取",
            "保证高薪",
            "一定高薪",
            "保证就业",
            "技术移民",
            "移民通道",
            "移民资格",
            "签证资格",
        )
        if any(claim in content for claim in forbidden_claims):
            raise ValueError("recommendation contains a prohibited guarantee")
        if re.search(
            r"ANZSCO|MLTSSL|STSOL|CSOL|AASW|AITSL|ANMAC|AHPRA|NCAS|"
            r"\b\d{6}\b|获邀分数|EOI分数|邀请分数",
            content,
            flags=re.IGNORECASE,
        ):
            raise ValueError("recommendation contains unverified policy detail")

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
