from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from .admission_mvp import AdmissionMvpService


class ProgramRecommendationService:
    """Recommend real catalog programs without making admission decisions."""

    SIGNALS: dict[str, dict[str, Any]] = {
        "analytics": {
            "terms": (
                "数据", "分析", "商业分析", "business analyst", "analytics",
                "data", "统计", "建模", "量化",
                "细致", "严谨", "逻辑性强", "喜欢数字",
            ),
            "program_terms": ("analytics", "data science", "statistics"),
            "label": "数据与分析",
        },
        "computing": {
            "terms": (
                "计算机", "技术", "软件", "编程", "开发", "算法", "人工智能",
                "ai", "computer", "software", "programming", "it",
                "网络安全", "cyber",
            ),
            "program_terms": (
                "information technology", "computer science", "software",
                "data science", "cyber", "computing",
            ),
            "label": "计算机与技术",
        },
        "finance": {
            "terms": (
                "金融", "投行", "投资", "银行", "证券", "finance",
                "banking", "investment", "估值",
            ),
            "program_terms": ("finance", "banking", "financial"),
            "label": "金融与投资",
        },
        "accounting": {
            "terms": (
                "会计", "审计", "税务", "accounting", "audit", "cpa",
                "财务报表", "对账",
            ),
            "program_terms": ("accounting", "professional accounting"),
            "label": "会计与审计",
        },
        "marketing": {
            "terms": (
                "市场", "营销", "品牌", "广告", "内容", "创意", "marketing",
                "brand", "沟通", "表达", "社交",
            ),
            "program_terms": ("marketing",),
            "label": "市场与品牌",
        },
        "management": {
            "terms": (
                "管理", "咨询", "领导", "团队", "组织", "management",
                "consulting", "协调", "战略", "strategy",
            ),
            "program_terms": ("management", "commerce"),
            "label": "管理与咨询",
        },
        "supply_chain": {
            "terms": (
                "供应链", "物流", "运营", "采购", "supply chain",
                "logistics", "operations", "流程",
            ),
            "program_terms": ("supply chain", "logistics", "operations"),
            "label": "供应链与运营",
        },
        "international_business": {
            "terms": (
                "国际商务", "跨国", "海外业务", "international business",
                "global business", "国际化",
            ),
            "program_terms": ("international business", "global business"),
            "label": "国际商务",
        },
    }
    PUBLIC_DIRECTION_RATIONALES = {
        "analytics": "数据分析能力兼具技术门槛和跨行业迁移空间",
        "computing": "技术壁垒通常需要通过编程、系统设计和工程实践逐步建立",
        "finance": "金融路线更强调定量分析、行业知识和高强度实践",
        "accounting": "会计路线依赖规则理解、专业训练和职业资格积累",
        "marketing": "市场路线更看重用户洞察、表达创意和商业判断",
        "management": "管理路线需要结构化分析、协作沟通和业务理解",
        "supply_chain": "供应链路线结合流程优化、数据分析和跨部门协作",
        "international_business": "国际化机会与跨境业务、海外市场和跨文化协作直接相关",
    }
    UNCATALOGUED_DIRECTION_RATIONALES = {
        "healthcare": (
            "医疗健康方向通常包含严格的课程、临床实习和职业注册要求，"
            "适合愿意接受较长训练并从事照护工作的人。"
        ),
        "education": (
            "教育方向需要核对课程认证、教师注册、英语和教学实践要求。"
        ),
        "social_work": (
            "社会工作可作为转专业候选，但需要确认你是否适应高强度沟通、"
            "实习和长期助人工作。"
        ),
        "engineering": (
            "工程方向能够形成专业技术能力，但通常需要核对本科先修、"
            "认证课程和职业评估要求。"
        ),
        "other": "该方向值得作为第一轮候选，但目前只有方向级信息。",
    }
    UNCATALOGUED_VERIFICATION_NOTE = (
        "该方向尚未收录项目详情；需以澳洲内政部职业清单、相关职业评估机构、"
        "州政府提名要求和最新邀请轮次为准。"
    )
    AMBIGUOUS_PROFILE_PHRASES = {
        "computing": ("技术壁垒",),
        "international_business": ("国际化机会",),
    }
    CAREER_MOBILITY_TERMS = (
        "回国",
        "留澳",
        "澳洲就业",
        "大企业",
        "大厂",
        "跨国公司",
        "就业面",
        "职业通用性",
        "国内就业",
        "海外就业",
    )
    EXPLORATION_SIGNALS = ["computing", "analytics", "management"]
    HIGH_COMPENSATION_SIGNALS = ["computing", "analytics", "finance"]
    COMPENSATION_PRIORITY_TERMS = (
        "赚钱",
        "高薪",
        "薪资高",
        "高收入",
        "收入高",
        "高工资",
        "pay well",
        "high salary",
    )
    HIGH_INTENSITY_TOLERANCE_TERMS = (
        "接受加班",
        "能接受加班",
        "可以加班",
        "不怕加班",
        "接受高强度",
        "抗压",
    )
    MIGRATION_PRIORITY_TERMS = (
        "移民",
        "获邀",
        "eoi",
        "州担保",
        "技术移民",
    )
    CAREER_PATHS: dict[str, dict[str, list[str]]] = {
        "computing": {
            "roles": ["软件开发工程师", "后端工程师", "云与平台工程师", "技术产品方向"],
            "preparation": ["补编程与数据结构基础", "完成两到三个可展示项目", "通过实习验证是否喜欢工程工作"],
        },
        "analytics": {
            "roles": ["数据分析师", "商业分析师", "数据产品方向", "初级数据科学岗位"],
            "preparation": ["学习统计、SQL 和 Python", "积累业务分析案例", "练习把分析结论讲清楚"],
        },
        "finance": {
            "roles": ["金融分析", "投融资支持", "银行与风险管理", "企业财务方向"],
            "preparation": ["补会计与公司金融基础", "练习估值和财务建模", "尽早寻找金融相关实习"],
        },
        "accounting": {
            "roles": ["审计", "财务会计", "税务", "企业财务方向"],
            "preparation": ["核对职业认证课程要求", "夯实财务报表基础", "通过实习了解审计与企业财务差异"],
        },
        "marketing": {
            "roles": ["品牌营销", "增长运营", "市场研究", "内容与用户运营"],
            "preparation": ["积累市场调研或运营作品", "学习基础数据分析", "通过项目验证沟通和创意偏好"],
        },
        "management": {
            "roles": ["管理培训生", "项目协调", "咨询支持", "业务运营"],
            "preparation": ["训练结构化分析与表达", "承担团队项目中的协调职责", "用实习缩小行业范围"],
        },
        "supply_chain": {
            "roles": ["供应链分析", "采购", "物流规划", "运营管理"],
            "preparation": ["学习运营与流程分析", "掌握 Excel、SQL 等分析工具", "关注制造、零售或物流实习"],
        },
        "international_business": {
            "roles": ["国际业务运营", "跨境商务", "海外市场", "客户与渠道管理"],
            "preparation": ["强化商业沟通与数据能力", "积累跨文化项目经验", "尽早确认目标行业"],
        },
    }
    GAME_CAREER_PATH = {
        "roles": ["游戏客户端或服务端开发", "技术策划", "游戏系统或数值策划", "游戏产品方向"],
        "preparation": [
            "先用一门编程语言完成小型可玩 Demo",
            "学习游戏机制、系统设计和基础数据分析",
            "通过 Game Jam 或独立项目判断自己更偏开发、策划还是产品",
        ],
    }

    def __init__(
        self,
        admission_service: AdmissionMvpService | None = None,
        profile_interpreter: Any | None = None,
        narrator: Any | None = None,
    ) -> None:
        self.admission_service = admission_service or AdmissionMvpService()
        self.profile_interpreter = profile_interpreter
        self.narrator = narrator

    def recommend(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = str(request.get("prompt") or "").strip()
        conversation_context = str(
            request.get("conversation_context") or ""
        ).strip()
        profile_text = " ".join(
            str(request.get(field) or "")
            for field in (
                "undergraduate_major",
                "career_goal",
                "personality",
                "preferences",
            )
        )
        effective_query = (
            f"{conversation_context} {prompt} {profile_text}".strip().lower()
        )
        signals = self._extract_signals(effective_query)
        mobility_goal = any(
            term in effective_query for term in self.CAREER_MOBILITY_TERMS
        )
        compensation_priority = any(
            term in effective_query
            for term in self.COMPENSATION_PRIORITY_TERMS
        )
        work_intensity_tolerance = (
            "high"
            if any(
                term in effective_query
                for term in self.HIGH_INTENSITY_TOLERANCE_TERMS
            )
            else "unknown"
        )
        migration_priority = any(
            term in effective_query for term in self.MIGRATION_PRIORITY_TERMS
        )
        uncatalogued_directions: list[dict[str, Any]] = []
        profile_source = "deterministic_rules"
        profile_clarification: str | None = None
        profile_evidence: list[str] = []
        interpretation_summary: str | None = None
        profile_trace: dict[str, Any] | None = None
        if (
            self.profile_interpreter is not None
            and (
                request.get("allow_agent_direction_recommendation")
                or request.get("allow_llm_profile_fallback")
            )
        ):
            try:
                interpreted = self.profile_interpreter.extract(effective_query)
                interpreted_signals = [
                    signal
                    for signal in interpreted.get("matched_signals", [])
                    if signal in self.SIGNALS
                ]
                # Deterministic matches are useful candidate labels, but they
                # must not prevent the profile Agent from retaining the user's
                # background, motivation, target market, and intended role.
                signals = list(dict.fromkeys([*signals, *interpreted_signals]))
                mobility_goal = mobility_goal or bool(
                    interpreted.get("career_mobility_goal")
                )
                compensation_priority = compensation_priority or bool(
                    interpreted.get("compensation_priority")
                )
                interpreted_tolerance = interpreted.get(
                    "work_intensity_tolerance", "unknown"
                )
                if work_intensity_tolerance == "unknown":
                    work_intensity_tolerance = interpreted_tolerance
                migration_priority = migration_priority or bool(
                    interpreted.get("migration_priority")
                )
                uncatalogued_directions = (
                    self._normalize_uncatalogued_directions(
                        interpreted.get("uncatalogued_directions", []),
                        effective_query,
                    )
                )
                profile_clarification = interpreted.get(
                    "clarification_question"
                )
                profile_evidence = [
                    str(item).strip()
                    for item in interpreted.get("evidence_phrases", [])
                    if str(item).strip()
                ][:4]
                interpretation_summary = interpreted.get(
                    "interpretation_summary"
                )
                interpretation_summary = self._public_interpretation_summary(
                    interpretation_summary
                )
                profile_source = "cloud_llm_direction_agent"
                profile_trace = {
                    "tool": "recommend_program_directions_with_agent",
                    "ok": bool(signals or uncatalogued_directions),
                    "signals": signals,
                    "uncatalogued_directions": [
                        item["name"] for item in uncatalogued_directions
                    ],
                    "policy_details_sanitized": bool(
                        uncatalogued_directions
                    ),
                    "confidence": interpreted.get("confidence"),
                    "model": interpreted.get("model"),
                }
            except Exception as exc:
                profile_source = "deterministic_rules_after_llm_error"
                profile_trace = {
                    "tool": "recommend_program_directions_with_agent",
                    "ok": False,
                    "error": type(exc).__name__,
                }
        exploration_mode = (mobility_goal or compensation_priority) and not signals
        if uncatalogued_directions and not signals:
            ranking_signals = []
            exploration_reason = "migration_direction_catalog_gap"
        elif compensation_priority and not signals:
            ranking_signals = self.HIGH_COMPENSATION_SIGNALS
            exploration_reason = "compensation_priority"
        elif mobility_goal and not signals:
            ranking_signals = self.EXPLORATION_SIGNALS
            exploration_reason = "career_mobility"
        else:
            ranking_signals = signals
            exploration_reason = None
        interpretation_summary_source: str | None = None
        if interpretation_summary:
            interpretation_summary_source = "direction_agent"
        elif signals and profile_source == "cloud_llm_direction_agent":
            interpretation_summary = self._fallback_public_interpretation_summary(
                prompt=prompt,
                evidence_phrases=profile_evidence,
                signals=ranking_signals,
            )
            interpretation_summary_source = "service_fallback"
        university_query = str(request.get("university") or "").strip()
        candidates = self._candidate_programs(university_query)

        trace = [
            {
                "tool": "extract_recommendation_profile",
                "ok": bool(effective_query),
                "signals": [
                    self.SIGNALS[key]["label"] for key in ranking_signals
                ],
                "career_mobility_goal": mobility_goal,
                "compensation_priority": compensation_priority,
                "work_intensity_tolerance": work_intensity_tolerance,
                "migration_priority": migration_priority,
                "uncatalogued_direction_count": len(
                    uncatalogued_directions
                ),
                "exploration_mode": exploration_mode,
                "exploration_reason": exploration_reason,
                "source": profile_source,
            },
            {
                "tool": "search_verified_program_catalog",
                "ok": bool(candidates),
                "count": len(candidates),
                "university_filter": university_query or None,
            },
        ]
        if profile_trace is not None:
            trace.insert(1, profile_trace)
        if not ranking_signals and not uncatalogued_directions:
            is_follow_up = bool(
                conversation_context
                or request.get("is_recommendation_follow_up")
                or request.get("allow_llm_profile_fallback")
            )
            fallback_message = (
                "我记下了你刚补充的信息。现在还差一步：需要把兴趣落到"
                "你愿意长期做的工作内容上。"
                if is_follow_up
                else (
                    "可以先不选专业。请至少告诉我一个就业方向、擅长的事情，"
                    "或你喜欢和不喜欢的学习方式。"
                )
            )
            questions = [
                profile_clarification
                or "毕业后更想做技术、数据、金融、市场还是管理类工作？",
                "你更喜欢写代码和分析数字，还是沟通、创意与组织协调？",
            ]
            answer_source = "recommendation_profile_clarification"
            clarify = getattr(self.narrator, "clarify", None)
            if callable(clarify):
                narration = clarify(
                    query=effective_query,
                    evidence_phrases=profile_evidence,
                    suggested_question=questions[0],
                    fallback_message=fallback_message,
                )
                fallback_message = narration["message"]
                answer_source = narration["answer_source"]
                trace.extend(narration.get("trace", []))
            return self._result(
                status="RECOMMENDATION_PROFILE_INSUFFICIENT",
                message=fallback_message,
                recommendations=[],
                clarifying_questions=(
                    [] if answer_source.startswith("llm_") else questions
                ),
                trace=trace,
                effective_query=effective_query,
                confidence="low",
                next_action="ask_recommendation_profile",
                answer_source=answer_source,
            )
        if not candidates and not uncatalogued_directions:
            return self._result(
                status="RECOMMENDATION_CATALOG_EMPTY",
                message="当前真实项目目录中没有找到符合学校范围的候选项目。",
                recommendations=[],
                clarifying_questions=["请确认学校名称，或暂时不限制目标学校。"],
                trace=trace,
                effective_query=effective_query,
                confidence="low",
                next_action="clarify_target_university",
            )

        ranked = self._rank(candidates, ranking_signals)
        max_results = min(max(int(request.get("max_results", 3)), 1), 5)
        selected = self._select_diverse(
            ranked,
            max_results,
            preferred_signals=(ranking_signals if exploration_mode else None),
        )
        academic_note = self._academic_note(request)
        recommendations = [
            self._present(
                item,
                rank,
                ranking_signals,
                academic_note,
                exploration_mode=exploration_mode,
            )
            for rank, item in enumerate(selected, start=1)
        ]
        game_interest = "游戏" in effective_query or "game" in effective_query
        if game_interest and "computing" in ranking_signals:
            for recommendation in recommendations:
                if "computing" in recommendation.get("matched_signals", []):
                    recommendation["career_path"] = {
                        **self.GAME_CAREER_PATH,
                        "stage_note": "这是游戏相关的粗略起步路线，具体岗位仍需通过编程或策划项目验证。",
                    }
        trace.append(
            {
                "tool": "rank_program_candidates",
                "ok": True,
                "candidate_count": len(ranked),
                "selected_count": len(recommendations),
                "hard_admission_decision": False,
                "exploration_mode": exploration_mode,
            }
        )
        if interpretation_summary:
            trace.append(
                {
                    "tool": "explain_profile_inference",
                    "ok": True,
                    "evidence_count": len(profile_evidence),
                    "public_summary": interpretation_summary,
                    "summary_source": interpretation_summary_source,
                }
            )
        trace.append(
            {
                "tool": "build_career_path",
                "ok": any(
                    item.get("career_path", {}).get("roles")
                    for item in recommendations
                ),
                "recommendation_count": len(recommendations),
            }
        )
        labels = "、".join(
            self.SIGNALS[key]["label"] for key in ranking_signals
        )
        if uncatalogued_directions and not recommendations:
            direction_names = "、".join(
                item["name"] for item in uncatalogued_directions
            )
            message = (
                f"你当前最看重澳洲移民可行性。现有项目目录尚未覆盖{direction_names}，"
                "但目录缺口不应阻止第一轮方向建议。下面先给出方向级候选和适配理由，"
                "暂不提供具体学校项目；职业清单、职业评估、州担保条件和历史邀请分数"
                "都需要按当前官方信息逐项核验，不能把候选方向理解为保证获邀。"
            )
            clarification = [
                profile_clarification
                or "你是否接受需要额外职业注册、实习或较长培养周期的课程？"
            ]
        elif exploration_reason == "compensation_priority":
            intensity_note = (
                "你也明确表示可以接受较高工作强度。"
                if work_intensity_tolerance == "high"
                else ""
            )
            message = (
                "你给出的不是具体行业，而是一个清晰的决策目标：收入优先。"
                f"{intensity_note}这足够先比较技术工程、数据与量化、金融三条路线。"
                "我不会把某个专业描述成高薪保证；收入还取决于能力、岗位、城市、"
                "实习经历和市场周期。"
            )
            clarification = [
                "为了继续缩小范围，你更愿意长期练编程、补统计与数学，还是学习金融并竞争高强度实习？"
            ]
        elif exploration_mode:
            message = (
                "你给出的核心目标是兼顾回国进入大型企业和留澳发展的可能性。"
                "这足够先做第一轮探索：我为你各选了一条技术、数据商业和"
                "综合商科路线，先比较工作内容与能力要求，再决定专业。"
            )
            clarification = [
                "这三条路线里，你更愿意长期做哪类工作：写代码做技术、分析数据解决业务问题，还是沟通协调与商业管理？"
            ]
        else:
            inference_prefix = ""
            if interpretation_summary:
                inference_prefix = (
                    f"我先说明我的理解：{interpretation_summary}"
                    "这属于待确认的方向推断，不代表你已经明确选择了这个专业。\n\n"
                )
            message = inference_prefix + (
                f"基于目前得到的{labels}候选方向，我先从已收录的官方项目目录中筛出"
                f" {len(recommendations)} 个项目。除了项目名单，我也列出了可探索的"
                "岗位和起步准备；推荐用于缩小范围，不代表录取结论。"
            )
            clarification = (
                [
                    "为了继续缩小范围，你更愿意先尝试写一个小型游戏 Demo，"
                    "还是先做玩法、系统和数值策划？"
                ]
                if game_interest and "computing" in ranking_signals
                else []
            )
        profile = {
            "matched_signals": [
                self.SIGNALS[key]["label"] for key in ranking_signals
            ],
            "career_mobility_goal": mobility_goal,
            "compensation_priority": compensation_priority,
            "work_intensity_tolerance": work_intensity_tolerance,
            "migration_priority": migration_priority,
            "uncatalogued_directions": uncatalogued_directions,
            "exploration_mode": exploration_mode,
            "exploration_reason": exploration_reason,
            "academic_note": academic_note,
            "profile_source": profile_source,
            "evidence_phrases": profile_evidence,
            "interpretation_summary": interpretation_summary,
        }
        answer_source = (
            "catalog_program_recommendation_agent"
            if recommendations
            else "direction_recommendation_without_catalog"
        )
        if self.narrator is not None:
            narration = self.narrator.narrate(
                query=effective_query,
                profile=profile,
                recommendations=recommendations,
                fallback_message=message,
            )
            message = narration["message"]
            answer_source = narration["answer_source"]
            trace.extend(narration.get("trace", []))
            if migration_priority and not any(
                marker in message
                for marker in (
                    "不是按移民",
                    "不代表移民",
                    "最新官方信息核验",
                    "以当前官方信息为准",
                    "具有时效性",
                )
            ):
                message = (
                    f"{message.rstrip()}\n\n需要单独说明：当前项目或方向候选不是按"
                    "留澳或移民可行性排序；职业清单、职业评估、州担保和邀请情况"
                    "需要以当前官方信息为准。"
                )
                trace.append(
                    {
                        "tool": "complete_migration_evidence_boundary",
                        "ok": True,
                        "reason": "generated_answer_omitted_required_boundary",
                    }
                )
        return self._result(
            status="PROGRAM_RECOMMENDATIONS_READY",
            message=message,
            recommendations=recommendations,
            profile=profile,
            uncatalogued_directions=uncatalogued_directions,
            clarifying_questions=clarification,
            trace=trace,
            effective_query=effective_query,
            confidence=(
                "medium"
                if exploration_mode or len(signals) == 1
                else "high"
            ),
            next_action=(
                "select_program_then_evaluate_admission"
                if recommendations
                else "refine_direction_or_expand_catalog"
            ),
            answer_source=answer_source,
        )

    def _candidate_programs(self, university_query: str) -> list[dict[str, Any]]:
        universities = self.admission_service.universities
        if university_query:
            matched = self.admission_service._find_university(university_query)
            universities = [matched] if matched else []
        result: list[dict[str, Any]] = []
        for university in universities:
            response = self.admission_service.find_programs(
                university["university_id"], discipline_id=None
            )
            for program in response.get("programs", []):
                result.append(
                    {
                        **program,
                        "university_id": university["university_id"],
                        "university_name": university["name"],
                        "university_short_name": university["short_name"],
                    }
                )
        return result

    def _extract_signals(self, text: str) -> list[str]:
        scores: dict[str, int] = {}
        for key, config in self.SIGNALS.items():
            signal_text = text
            for phrase in self.AMBIGUOUS_PROFILE_PHRASES.get(key, ()):
                signal_text = signal_text.replace(phrase, "")
            count = sum(
                1 for term in config["terms"] if term in signal_text
            )
            if count:
                scores[key] = count
        return [key for key, _ in sorted(scores.items(), key=lambda item: -item[1])]

    def _normalize_uncatalogued_directions(
        self,
        values: Any,
        effective_query: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                continue
            name = str(value.get("name") or "").strip()[:80]
            category = str(value.get("category") or "other")
            if not name or name in seen:
                continue
            if category not in self.UNCATALOGUED_DIRECTION_RATIONALES:
                category = "other"
            rationale = self.UNCATALOGUED_DIRECTION_RATIONALES[category]
            if category == "education" and "教师资格" in effective_query:
                rationale = (
                    "你已提到教师资格，教育方向值得优先核对原资格能否衔接"
                    "澳洲认证课程、教师注册、英语和教学实践要求。"
                )
            result.append(
                {
                    "name": name,
                    "category": category,
                    "rationale": rationale,
                    "verification_note": self.UNCATALOGUED_VERIFICATION_NOTE,
                    "catalog_status": "not_indexed",
                    "detail_level": "direction_only",
                }
            )
            seen.add(name)
            if len(result) == 4:
                break
        return result

    def _rank(
        self,
        candidates: list[dict[str, Any]],
        signals: list[str],
    ) -> list[dict[str, Any]]:
        ranked = []
        for candidate in candidates:
            name_text = " ".join(
                [
                    str(candidate.get("name") or ""),
                    str(candidate.get("display_name_zh") or ""),
                ]
            ).lower()
            specialisation_text = " ".join(
                candidate.get("specialisations", [])
            ).lower()
            matches: list[str] = []
            score = 0
            for index, signal in enumerate(signals):
                terms = self.SIGNALS[signal]["program_terms"]
                name_match = any(term in name_text for term in terms)
                specialisation_match = any(
                    term in specialisation_text for term in terms
                )
                if name_match or specialisation_match:
                    matches.append(signal)
                    priority_weight = max(4 - index * 2, 1)
                    score += priority_weight * (3 if name_match else 1)
            if candidate.get("discipline_id") == "computing" and "computing" in signals:
                score += 4
            if score:
                ranked.append({**candidate, "recommendation_score": score, "matches": matches})
        return sorted(
            ranked,
            key=lambda item: (
                -item["recommendation_score"],
                item["university_short_name"],
                item["name"],
            ),
        )

    @staticmethod
    def _select_diverse(
        ranked: list[dict[str, Any]],
        max_results: int,
        preferred_signals: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for signal in preferred_signals or []:
            exclusive_match = next(
                (
                    item
                    for item in ranked
                    if item.get("matches") == [signal] and item not in selected
                ),
                None,
            )
            match = exclusive_match or next(
                (
                    item
                    for item in ranked
                    if signal in item.get("matches", []) and item not in selected
                ),
                None,
            )
            if match is not None:
                selected.append(match)
            if len(selected) == max_results:
                return selected
        university_counts: defaultdict[str, int] = defaultdict(int)
        for item in selected:
            university_counts[item["university_id"]] += 1
        for item in ranked:
            if item in selected:
                continue
            if university_counts[item["university_id"]] >= 1 and len(ranked) > max_results:
                continue
            selected.append(item)
            university_counts[item["university_id"]] += 1
            if len(selected) == max_results:
                return selected
        for item in ranked:
            if item not in selected:
                selected.append(item)
                if len(selected) == max_results:
                    break
        return selected

    def _present(
        self,
        item: dict[str, Any],
        rank: int,
        signals: list[str],
        academic_note: dict[str, Any],
        *,
        exploration_mode: bool = False,
    ) -> dict[str, Any]:
        matched = item.get("matches") or signals[:1]
        if exploration_mode:
            route_reasons = {
                "computing": "技术路线：适合愿意持续学习编程、系统与软件工程的人",
                "analytics": "数据商业路线：连接数据分析、业务理解和决策表达",
                "management": "综合商科路线：先保留较宽的商业方向选择空间",
            }
            reasons = [route_reasons[key] for key in matched if key in route_reasons]
        else:
            reasons = [
                f"项目方向与“{self.SIGNALS[key]['label']}”目标相关"
                for key in matched
            ]
        if item.get("specialisations"):
            reasons.append(
                "可关注的细分方向：" + "、".join(item["specialisations"][:4])
            )
        return {
            "rank": rank,
            "program_id": item.get("program_id") or item.get("program_code") or item["name"],
            "program_code": item.get("program_code"),
            "program_name": item["name"],
            "display_name_zh": item.get("display_name_zh"),
            "university_id": item["university_id"],
            "university_name": item["university_name"],
            "discipline_id": item.get("discipline_id"),
            "specialisations": item.get("specialisations", []),
            "duration_months": item.get("duration_months"),
            "recommendation_score": item["recommendation_score"],
            "matched_signals": matched,
            "reasons": reasons,
            "career_path": self._career_path(matched),
            "tradeoff": "课程结构、学费、就业结果和官方录取要求仍需逐项核对。",
            "academic_fit": academic_note,
            "evaluation_ready": bool(item.get("evaluation_ready")),
            "official_url": item.get("official_url"),
        }

    def _career_path(self, matched: list[str]) -> dict[str, Any]:
        roles: list[str] = []
        preparation: list[str] = []
        for signal in matched:
            path = self.CAREER_PATHS.get(signal, {})
            for role in path.get("roles", []):
                if role not in roles:
                    roles.append(role)
            for step in path.get("preparation", []):
                if step not in preparation:
                    preparation.append(step)
        return {
            "roles": roles[:4],
            "preparation": preparation[:3],
            "stage_note": "先把方向当作职业假设，再通过课程、小项目和实习逐步验证。",
        }

    def _public_interpretation_summary(self, value: Any) -> str | None:
        summary = str(value or "").strip()
        if not summary:
            return None
        for signal, config in self.SIGNALS.items():
            summary = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(signal)}(?![A-Za-z0-9_])",
                config["label"],
                summary,
                flags=re.IGNORECASE,
            )
        return summary

    def _fallback_public_interpretation_summary(
        self,
        *,
        prompt: str,
        evidence_phrases: list[str],
        signals: list[str],
    ) -> str:
        evidence = "、".join(evidence_phrases[:3])
        if not evidence:
            evidence = re.sub(r"\s+", " ", prompt).strip()[:100]
        labels = "、".join(self.SIGNALS[key]["label"] for key in signals)
        rationales = "；".join(
            self.PUBLIC_DIRECTION_RATIONALES[key]
            for key in signals
            if key in self.PUBLIC_DIRECTION_RATIONALES
        )
        return (
            f"你提到“{evidence}”，所以我暂时把{labels}作为候选方向。"
            f"具体关联是：{rationales}"
        )

    @staticmethod
    def _academic_note(request: dict[str, Any]) -> dict[str, Any]:
        value = request.get("score_value")
        scale = request.get("score_scale")
        if value is None or scale is None:
            return {
                "status": "SCORE_NOT_PROVIDED",
                "message": "尚未提供成绩，当前只做兴趣与就业方向匹配。",
            }
        return {
            "status": "REQUIRES_PROGRAM_RULE_CHECK",
            "score_value": float(value),
            "score_scale": float(scale),
            "message": (
                "成绩已用于形成申请背景，但未做线性换算，也未改变推荐排序；"
                "选择具体项目后再按官方规则判断门槛。"
            ),
        }

    @staticmethod
    def _result(
        *,
        status: str,
        message: str,
        recommendations: list[dict[str, Any]],
        clarifying_questions: list[str],
        trace: list[dict[str, Any]],
        effective_query: str,
        confidence: str,
        next_action: str,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "error_code": status,
            "message": message,
            "recommendations": recommendations,
            "clarifying_questions": clarifying_questions,
            "trace": trace,
            "trace_tools": [item["tool"] for item in trace],
            "answer_source": "catalog_program_recommendation_agent",
            "confidence": confidence,
            "next_action": next_action,
            "effective_query": effective_query,
            **extra,
        }
