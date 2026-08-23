from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .australian_terminology import AustralianTerminologyGlossary
from .handbook_qa import HandbookQuestionAnsweringAgent
from .campuspilot_faq import CampusPilotFaqService
from .recruitment_knowledge import RecruitmentQuestionAnsweringAgent
from .plan_narrator import StudyPlanNarrator
from campuspilot_core.program_recommendation import ProgramRecommendationService

CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "campuspilot_official_sample.json"
)
GO8_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "go8_official_catalog.json"
)
UNIT_DETAILS_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "campuspilot_unit_assessments_2026.json"
)

MANDATORY_RULES = {
    "FOUNDATION_CORE",
    "CORE",
    "RESEARCH_CORE",
    "SPECIALISATION_CORE",
    "CAPSTONE",
}
ELIGIBLE_RULES = MANDATORY_RULES | {
    "PRESCRIBED_ELECTIVE",
    "GENERAL_ELECTIVE",
}


class CampusPilotPlanningState(TypedDict, total=False):
    request: dict[str, Any]
    program: dict[str, Any]
    rules: list[dict[str, Any]]
    completed_courses: list[str]
    completed_credits: int
    remaining_credits: int
    selected_courses: list[str]
    plans: list[dict[str, Any]]
    warnings: list[str]
    trace: list[dict[str, Any]]
    validation: dict[str, Any]
    evidence: list[dict[str, Any]]


class CampusPilotEvidenceRetriever:
    """Lightweight BM25 retrieval over versioned official-source excerpts."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.tokenized = [
            self._tokenize(
                " ".join(
                    [
                        document["title"],
                        document["content"],
                        *document.get("tags", []),
                    ]
                )
            )
            for document in documents
        ]
        self.average_length = sum(len(tokens) for tokens in self.tokenized) / max(
            len(self.tokenized), 1
        )

    def search(
        self,
        query: str,
        *,
        handbook_year: int | None = None,
        university_id: str | None = None,
        discipline_id: str | None = None,
        program_code: str | None = None,
        k: int = 3,
    ) -> list[dict[str, Any]]:
        query_tokens = set(self._tokenize(query))
        scores: list[tuple[float, dict[str, Any]]] = []
        for index, document in enumerate(self.documents):
            if handbook_year is not None and document["handbook_year"] != handbook_year:
                continue
            searchable = " ".join(
                [
                    document["title"],
                    document["content"],
                    *document.get("tags", []),
                ]
            ).lower()
            if program_code is not None and program_code.lower() not in searchable:
                continue
            tokens = self.tokenized[index]
            score = sum(self._bm25_term_score(term, tokens) for term in query_tokens)
            if score > 0:
                scores.append((score, document))
        scores.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                **document,
                "score": round(score, 4),
            }
            for score, document in scores[:k]
        ]

    def _bm25_term_score(self, term: str, tokens: list[str]) -> float:
        frequency = tokens.count(term)
        if frequency == 0:
            return 0.0
        document_frequency = sum(1 for candidate in self.tokenized if term in candidate)
        total = len(self.documents)
        inverse_frequency = math.log(
            1 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
        )
        length_ratio = len(tokens) / max(self.average_length, 1)
        denominator = frequency + 1.5 * (0.25 + 0.75 * length_ratio)
        return inverse_frequency * (frequency * 2.5) / denominator

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        normalized = text.lower()
        words = re.findall(r"[a-z0-9]+", normalized)
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
        chinese_tokens = [
            run[index : index + 2]
            for run in chinese_runs
            for index in range(max(len(run) - 1, 1))
        ]
        return words + chinese_tokens


class CampusPilotCatalog:
    """Versioned structured rules derived from official public sources."""

    def __init__(
        self,
        catalog_path: str | Path = CATALOG_PATH,
        go8_catalog_path: str | Path = GO8_CATALOG_PATH,
        unit_details_path: str | Path | None = UNIT_DETAILS_PATH,
    ) -> None:
        with Path(catalog_path).open(encoding="utf-8") as file:
            self.data: dict[str, Any] = json.load(file)
        with Path(go8_catalog_path).open(encoding="utf-8") as file:
            self.go8_data: dict[str, Any] = json.load(file)
        source_urls = {
            item["source_id"]: item.get("url")
            for item in self.data.get("sources", [])
            if item.get("source_id") and item.get("url")
        }
        for document in self.data.get("official_documents", []):
            source_url = source_urls.get(document.get("source_id"))
            if source_url:
                document.setdefault("source_url", source_url)
        self.programs = {
            item["program_variant_id"]: item for item in self.data["programs"]
        }
        self.courses = {item["course_code"]: item for item in self.data["courses"]}
        if unit_details_path and Path(unit_details_path).exists():
            with Path(unit_details_path).open(encoding="utf-8") as file:
                unit_details = json.load(file)
            for details in unit_details.get("units", []):
                course = self.courses.get(details["course_code"])
                if course is None:
                    continue
                course.update(
                    {
                        "attendance_status": details["attendance_status"],
                        "attendance_note": details["attendance_note"],
                        "assessment_tags": details["assessment_tags"],
                        "assessments": details["assessments"],
                        "assessment_summary": details["assessment_summary"],
                        "exam_weight_percent": details["exam_weight_percent"],
                        "final_exam": details["final_exam"],
                        "hurdle_status": details["hurdle_status"],
                        "unit_detail_source_url": details["source_url"],
                        "unit_detail_captured_at": details["captured_at"],
                    }
                )
                course["source_ids"] = list(
                    dict.fromkeys(
                        source_id
                        for source_id in [
                            *course.get("source_ids", []),
                            details.get("source_id"),
                        ]
                        if source_id
                    )
                )

    def public_catalog(self) -> dict[str, Any]:
        return {
            "catalog_version": self.data["catalog_version"],
            "data_mode": self.data["data_mode"],
            "retrieved_at": self.data["retrieved_at"],
            "disclaimer": self.data["disclaimer"],
            "programs": list(self.programs.values()),
            "courses": list(self.courses.values()),
            "sources": self.data["sources"],
            "official_document_count": len(self.data.get("official_documents", [])),
            "go8_catalog_version": self.go8_data["catalog_version"],
            "go8_coverage_notice": self.go8_data["coverage_notice"],
            "disciplines": self.go8_data["disciplines"],
            "universities": self.go8_data["universities"],
        }

    def list_go8_universities(
        self,
        discipline_id: str | None = None,
    ) -> dict[str, Any]:
        valid_disciplines = {
            item["discipline_id"] for item in self.go8_data["disciplines"]
        }
        if discipline_id is not None and discipline_id not in valid_disciplines:
            raise ValueError("discipline not found")
        universities = [
            university
            for university in self.go8_data["universities"]
            if discipline_id is None or discipline_id in university["discipline_ids"]
        ]
        return {
            "catalog_version": self.go8_data["catalog_version"],
            "retrieved_at": self.go8_data["retrieved_at"],
            "membership_source": self.go8_data["membership_source"],
            "coverage_notice": self.go8_data["coverage_notice"],
            "discipline_id": discipline_id,
            "disciplines": self.go8_data["disciplines"],
            "universities": universities,
            "count": len(universities),
            "planning_verified_count": sum(
                1
                for university in universities
                if university["coverage_status"] == "planning_verified"
            ),
        }

    def get_program(
        self,
        program_variant_id: str,
        handbook_year: int,
    ) -> dict[str, Any]:
        program = self.programs.get(program_variant_id)
        if program is None or program["handbook_year"] != handbook_year:
            raise ValueError("program entry level or handbook version not found")
        return program

    def get_rules(
        self,
        program_variant_id: str,
        handbook_year: int,
        study_stream: str,
    ) -> list[dict[str, Any]]:
        program = self.get_program(program_variant_id, handbook_year)
        if study_stream not in program["study_streams"]:
            raise ValueError("study stream is not available for this entry level")
        return [
            rule
            for rule in self.data["program_course_rules"]
            if rule["program_variant_id"] == program_variant_id
            and rule["handbook_year"] == handbook_year
            and rule["study_stream"] in {None, study_stream}
        ]

    def classify_course_role(
        self,
        *,
        program_variant_id: str,
        handbook_year: int,
        study_stream: str,
        course_code: str,
    ) -> dict[str, Any]:
        self.get_program(program_variant_id, handbook_year)
        course = self.courses.get(course_code)
        if course is None:
            raise ValueError("course not found")
        rules = self.get_rules(
            program_variant_id,
            handbook_year,
            study_stream,
        )
        matching = [rule for rule in rules if rule["course_code"] == course_code]
        if not matching:
            role = "NOT_ELIGIBLE"
            credit_group = None
        else:
            role = matching[0]["rule_type"]
            credit_group = matching[0]["credit_group"]
        return {
            "program_variant_id": program_variant_id,
            "handbook_year": handbook_year,
            "study_stream": study_stream,
            "course": course,
            "rule_type": role,
            "credit_group": credit_group,
            "credits_counted": (
                course["credit_points"] if role != "NOT_ELIGIBLE" else 0
            ),
            "source_ids": [
                "MONASH-C6001-HANDBOOK-2026",
                *course.get("source_ids", []),
            ],
        }

    def compare_programs(
        self,
        first_program_variant_id: str,
        second_program_variant_id: str,
        handbook_year: int,
        study_stream: str,
    ) -> dict[str, Any]:
        first = self.get_program(first_program_variant_id, handbook_year)
        second = self.get_program(second_program_variant_id, handbook_year)
        first_rules = self.get_rules(
            first_program_variant_id,
            handbook_year,
            study_stream,
        )
        second_rules = self.get_rules(
            second_program_variant_id,
            handbook_year,
            study_stream,
        )

        def summarize(
            program: dict[str, Any],
            rules: list[dict[str, Any]],
        ) -> dict[str, Any]:
            mandatory_credits = sum(
                self.courses[rule["course_code"]]["credit_points"]
                for rule in rules
                if rule["rule_type"] in MANDATORY_RULES
            )
            return {
                **program,
                "mandatory_credits": mandatory_credits,
                "elective_credits": (
                    program["credits_to_complete"] - mandatory_credits
                ),
                "course_rule_count": len(rules),
            }

        return {
            "programs": [
                summarize(first, first_rules),
                summarize(second, second_rules),
            ],
            "differences": {
                "duration_years": (second["duration_years"] - first["duration_years"]),
                "credits_to_complete": (
                    second["credits_to_complete"] - first["credits_to_complete"]
                ),
                "entry_level_explanation": [
                    "Entry level 1 完成 96 学分，包含 24 学分 Foundation studies。",
                    "Entry level 2 完成 72 学分，从 Core studies 进入。",
                    "Entry level 由既往学历和学校录取评估决定，不是学生任意选择。",
                ],
            },
            "risk_notice": (
                "课程时长可以作为个人规划约束，但系统不判断签证或毕业工签"
                "资格；应以申请时的 Home Affairs 官方政策为准。"
            ),
            "source_ids": [
                "MONASH-C6001-HANDBOOK-2026",
                "MONASH-C6001-INTL-2026",
                "HOME-AFFAIRS-485-2026",
            ],
            "data_mode": self.data["data_mode"],
            "retrieved_at": self.data["retrieved_at"],
        }


class CampusPilotPlanningAgent:
    """LangGraph planning slice combining rules, sources, and validation."""

    def __init__(
        self,
        catalog: CampusPilotCatalog | None = None,
        evidence_retriever: Any | None = None,
    ) -> None:
        self.catalog = catalog or CampusPilotCatalog()
        self.evidence_retriever = evidence_retriever or CampusPilotEvidenceRetriever(
            self.catalog.data.get("official_documents", [])
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(CampusPilotPlanningState)
        workflow.add_node("load_program_rules", self._load_program_rules)
        workflow.add_node("calculate_credit_progress", self._calculate_progress)
        workflow.add_node("generate_study_plans", self._generate_plans)
        workflow.add_node("validate_study_plans", self._validate_plans)
        workflow.set_entry_point("load_program_rules")
        workflow.add_edge("load_program_rules", "calculate_credit_progress")
        workflow.add_edge("calculate_credit_progress", "generate_study_plans")
        workflow.add_edge("generate_study_plans", "validate_study_plans")
        workflow.add_edge("validate_study_plans", END)
        return workflow.compile()

    def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        result = self.graph.invoke(
            {
                "request": request,
                "trace": [],
                "warnings": [],
            }
        )
        return {
            "program": result["program"],
            "profile": request,
            "completed_credits": result["completed_credits"],
            "remaining_credits": result["remaining_credits"],
            "plans": result["plans"],
            "warnings": result["warnings"],
            "validation": result["validation"],
            "trace": result["trace"],
            "trace_tools": [item["tool"] for item in result["trace"]],
            "answer_source": "official_rag_and_structured_rules",
            "confidence": (
                "high"
                if result["validation"]["all_valid"] and result["evidence"]
                else "low"
            ),
            "next_action": (
                "review_and_confirm_plan"
                if result["validation"]["all_valid"]
                else "adjust_constraints"
            ),
            "source_ids": [
                "MONASH-C6001-HANDBOOK-2026",
                "MONASH-C6001-COURSE-MAP-2026",
                "MONASH-FIT5120-2026",
                "HOME-AFFAIRS-485-2026",
            ],
            "evidence": result["evidence"],
            "data_mode": self.catalog.data["data_mode"],
            "retrieved_at": self.catalog.data["retrieved_at"],
            "disclaimer": self.catalog.data["disclaimer"],
        }

    def calculate_progress(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        program = self.catalog.get_program(
            request["program_variant_id"],
            request["handbook_year"],
        )
        rules = self.catalog.get_rules(
            request["program_variant_id"],
            request["handbook_year"],
            request["study_stream"],
        )
        rule_by_course = {rule["course_code"]: rule for rule in rules}
        requested_courses = [
            code.strip().upper()
            for code in request.get("completed_courses", [])
            if code.strip()
        ]
        requested_courses = list(dict.fromkeys(requested_courses))
        counted_courses = [
            code
            for code in requested_courses
            if code in rule_by_course
            and rule_by_course[code]["rule_type"] in ELIGIBLE_RULES
        ]
        ignored_courses = sorted(set(requested_courses) - set(counted_courses))
        mandatory_rules = [
            rule for rule in rules if rule["rule_type"] in MANDATORY_RULES
        ]
        required_by_group: dict[str, int] = {}
        missing_by_group: dict[str, list[str]] = {}
        for rule in mandatory_rules:
            group = rule["credit_group"]
            credits = self.catalog.courses[rule["course_code"]]["credit_points"]
            required_by_group[group] = required_by_group.get(group, 0) + credits
            if rule["course_code"] not in counted_courses:
                missing_by_group.setdefault(group, []).append(rule["course_code"])

        fixed_required = sum(required_by_group.values())
        elective_required = max(
            program["credits_to_complete"] - fixed_required,
            0,
        )
        if elective_required:
            required_by_group["elective"] = elective_required

        earned_by_group: dict[str, int] = {}
        for course_code in counted_courses:
            group = rule_by_course[course_code]["credit_group"]
            credits = self.catalog.courses[course_code]["credit_points"]
            earned_by_group[group] = earned_by_group.get(group, 0) + credits

        group_progress = []
        for group, required_credits in required_by_group.items():
            earned_credits = min(
                earned_by_group.get(group, 0),
                required_credits,
            )
            missing_courses = missing_by_group.get(group, [])
            group_progress.append(
                {
                    "group": group,
                    "earned_credits": earned_credits,
                    "required_credits": required_credits,
                    "passed": (
                        earned_credits >= required_credits and not missing_courses
                    ),
                    "missing_courses": missing_courses,
                }
            )

        completed_credits = sum(
            self.catalog.courses[code]["credit_points"] for code in counted_courses
        )
        completed_credits = min(
            completed_credits,
            program["credits_to_complete"],
        )
        remaining_credits = max(
            program["credits_to_complete"] - completed_credits,
            0,
        )
        violations = []
        if remaining_credits:
            violations.append(
                {
                    "error_code": "TOTAL_CREDITS_NOT_MET",
                    "message": (
                        f"当前计入 {completed_credits} 学分，"
                        f"还需要 {remaining_credits} 学分。"
                    ),
                    "evidence": program["source_ids"],
                }
            )
        for group in group_progress:
            if group["missing_courses"]:
                violations.append(
                    {
                        "error_code": "REQUIRED_COURSES_MISSING",
                        "message": (
                            f"{group['group']} 尚缺少："
                            + "、".join(group["missing_courses"])
                        ),
                        "evidence": [
                            "MONASH-C6001-COURSE-MAP-2026",
                        ],
                    }
                )

        return {
            "program_variant_id": program["program_variant_id"],
            "handbook_year": program["handbook_year"],
            "study_stream": request["study_stream"],
            "counted_courses": counted_courses,
            "ignored_courses": ignored_courses,
            "completed_credits": completed_credits,
            "remaining_credits": remaining_credits,
            "required_total_credits": program["credits_to_complete"],
            "completion_ratio": round(
                completed_credits / program["credits_to_complete"],
                4,
            ),
            "group_progress": group_progress,
            "violations": violations,
            "trace": [
                {
                    "tool": "get_program_rules",
                    "ok": True,
                    "rule_count": len(rules),
                },
                {
                    "tool": "calculate_degree_progress",
                    "ok": True,
                    "counted_course_count": len(counted_courses),
                    "ignored_courses": ignored_courses,
                },
            ],
            "trace_tools": [
                "get_program_rules",
                "calculate_degree_progress",
            ],
            "answer_source": "structured_degree_rules",
            "confidence": "high",
            "next_action": (
                "degree_requirements_met"
                if remaining_credits == 0 and not violations
                else "select_remaining_courses"
            ),
            "evidence": program["source_ids"],
            "retrieved_at": self.catalog.data["retrieved_at"],
            "disclaimer": self.catalog.data["disclaimer"],
        }

    def _load_program_rules(
        self,
        state: CampusPilotPlanningState,
    ) -> CampusPilotPlanningState:
        request = state["request"]
        program = self.catalog.get_program(
            request["program_variant_id"],
            request["handbook_year"],
        )
        rules = self.catalog.get_rules(
            request["program_variant_id"],
            request["handbook_year"],
            request["study_stream"],
        )
        evidence_query = " ".join(
            [
                program["program_code"],
                f"Entry Level {program['entry_level']}",
                request["study_stream"],
                str(request["handbook_year"]),
                "credit course map capstone",
            ]
        )
        evidence = self.evidence_retriever.search(
            evidence_query,
            handbook_year=request["handbook_year"],
            program_code=program["program_code"],
            k=3,
        )
        retrieval_diagnostics = getattr(
            self.evidence_retriever,
            "last_search_diagnostics",
            {},
        )
        return {
            "program": program,
            "rules": rules,
            "evidence": evidence,
            "trace": [
                *state["trace"],
                {
                    "tool": "search_official_evidence",
                    "ok": bool(evidence),
                    "count": len(evidence),
                    "document_ids": [item["document_id"] for item in evidence],
                    "degraded": retrieval_diagnostics.get("degraded", False),
                    "dense_error": retrieval_diagnostics.get("dense_error"),
                },
                {
                    "tool": "get_program_rules",
                    "ok": True,
                    "program_variant_id": program["program_variant_id"],
                    "handbook_year": program["handbook_year"],
                    "rule_count": len(rules),
                },
            ],
        }

    def _calculate_progress(
        self,
        state: CampusPilotPlanningState,
    ) -> CampusPilotPlanningState:
        rule_by_course = {rule["course_code"]: rule for rule in state["rules"]}
        requested_completed = list(
            dict.fromkeys(state["request"].get("completed_courses", []))
        )
        eligible_completed = [
            code
            for code in requested_completed
            if code in rule_by_course
            and rule_by_course[code]["rule_type"] in ELIGIBLE_RULES
        ]
        ignored = sorted(set(requested_completed) - set(eligible_completed))
        completed_credits = sum(
            self.catalog.courses[code]["credit_points"] for code in eligible_completed
        )
        remaining_credits = max(
            state["program"]["credits_to_complete"] - completed_credits,
            0,
        )
        warnings = list(state["warnings"])
        if ignored:
            warnings.append(
                "以下课程未计入当前 entry level 与 stream：" + "、".join(ignored)
            )
        if state["request"].get("preserve_policy_flexibility"):
            warnings.append("已把课程时长作为规划约束；系统不判断签证或毕业工签资格。")
        warnings.append("课程 map 属于建议路径，实际开课与选课资格应在选课前再次核对。")
        return {
            "completed_courses": eligible_completed,
            "completed_credits": completed_credits,
            "remaining_credits": remaining_credits,
            "warnings": warnings,
            "trace": [
                *state["trace"],
                {
                    "tool": "calculate_credit_progress",
                    "ok": True,
                    "completed_credits": completed_credits,
                    "remaining_credits": remaining_credits,
                    "ignored_courses": ignored,
                },
            ],
        }

    def _generate_plans(
        self,
        state: CampusPilotPlanningState,
    ) -> CampusPilotPlanningState:
        selected_courses = self._select_remaining_courses(state)
        request = state["request"]
        planning_goal = request.get("planning_goal", "compare_options")
        if planning_goal in {
            "internship_priority",
            "study_internship_balance",
            "recruitment_readiness",
        }:
            selected_courses = self._prioritize_practice_courses(selected_courses)
        fastest = {
            "id": "fastest",
            "name": "最快完成",
            "description": "按较高单学期负荷安排，优先缩短完成时间。",
            "capacity": request["max_courses_per_semester"],
        }
        balanced = {
            "id": "balanced",
            "name": "负荷均衡",
            "description": "每学期最多三门，为项目和求职保留时间。",
            "capacity": min(3, request["max_courses_per_semester"]),
            "balance_workload": True,
        }
        flexible = {
            "id": "flexible",
            "name": "保留弹性",
            "description": "每学期最多两门，降低课程变更与挂科的连锁影响。",
            "capacity": min(2, request["max_courses_per_semester"]),
        }
        strategies = [fastest, balanced, flexible]
        if planning_goal == "internship_priority":
            balanced = {
                **balanced,
                "name": "实习优先",
                "description": (
                    "控制每学期课程数量，优先安排职业实践相关课程，"
                    "为投递、面试和实习预留时间。"
                ),
            }
            strategies = [balanced, flexible, fastest]
        elif planning_goal == "study_internship_balance":
            balanced = {
                **balanced,
                "name": "学业与实习兼顾",
                "description": (
                    "每学期最多三门，在保持学业进度的同时，"
                    "为项目积累、投递和面试留出稳定时间。"
                ),
            }
            strategies = [balanced, fastest, flexible]
        elif planning_goal == "recruitment_readiness":
            target_year = request.get("target_recruitment_year")
            target_label = f"{target_year} 年秋招" if target_year else "目标秋招"
            balanced = {
                **balanced,
                "name": "秋招准备优先",
                "description": (
                    f"围绕{target_label}控制每学期课程数量，优先安排职业实践相关课程，"
                    "为项目积累、实习、投递和面试预留稳定时间。"
                ),
            }
            strategies = [balanced, fastest, flexible]
        elif planning_goal == "workload_balance":
            balanced = {
                **balanced,
                "name": "负载均衡优先",
                "capacity": request["max_courses_per_semester"],
                "description": (
                    "按你设置的单学期课程上限安排，并尽量搭配高、中、低负载课程；"
                    "只有明确指定每学期课程数时才调整数量。"
                ),
            }
            strategies = [balanced, fastest, flexible]
        elif planning_goal == "policy_flexibility":
            flexible = {
                **flexible,
                "name": "规划弹性优先",
                "description": (
                    "采用较低负荷并保留更多调整窗口；政策结论仍需以最新官方信息为准。"
                ),
            }
            strategies = [flexible, balanced, fastest]
        elif planning_goal == "fastest_completion":
            strategies = [fastest, balanced, flexible]
        semester_course_limits = request.get(
            "semester_course_limits",
            {},
        )
        if semester_course_limits:
            strategies = [
                {
                    "id": "custom",
                    "name": "自定义节奏",
                    "description": (
                        "按你为每个学期设置的课程数量安排；0 门表示主动跳过该学期。"
                    ),
                    "capacity": request["max_courses_per_semester"],
                    "semester_course_limits": semester_course_limits,
                }
            ]
        role_by_course = {
            rule["course_code"]: rule["rule_type"] for rule in state["rules"]
        }
        plans = [
            self._schedule_courses(
                selected_courses,
                completed=set(state["completed_courses"]),
                initial_program_credits=(
                    state["program"]["entry_credit_points"] + state["completed_credits"]
                ),
                start_semester=request["start_semester"],
                strategy=strategy,
                role_by_course=role_by_course,
            )
            for strategy in strategies
        ]
        return {
            "selected_courses": selected_courses,
            "plans": plans,
            "trace": [
                *state["trace"],
                {
                    "tool": "generate_study_plan",
                    "ok": True,
                    "plan_count": len(plans),
                    "selected_courses": selected_courses,
                    "planning_goal": planning_goal,
                    "strategy_order": [strategy["id"] for strategy in strategies],
                },
            ],
        }

    def _validate_plans(
        self,
        state: CampusPilotPlanningState,
    ) -> CampusPilotPlanningState:
        validated = []
        for plan in state["plans"]:
            scheduled = [
                course["course_code"]
                for semester in plan["semesters"]
                for course in semester["courses"]
            ]
            missing = sorted(set(state["selected_courses"]) - set(scheduled))
            plan["validation"] = {
                "valid": not missing and not plan["scheduling_errors"],
                "missing_courses": missing,
                "errors": plan["scheduling_errors"],
            }
            validated.append(plan)
        all_valid = all(plan["validation"]["valid"] for plan in validated)
        valid_plan_count = sum(1 for plan in validated if plan["validation"]["valid"])
        return {
            "plans": validated,
            "validation": {
                "all_valid": all_valid,
                "valid_plan_count": valid_plan_count,
                "checked_rules": [
                    "credit_completion",
                    "prerequisite_order",
                    "semester_offering",
                    "semester_capacity",
                    "capstone_final_semester",
                ],
            },
            "trace": [
                *state["trace"],
                {
                    "tool": "validate_study_plan",
                    "ok": all_valid,
                    "valid_plan_count": valid_plan_count,
                },
            ],
        }

    def _select_remaining_courses(
        self,
        state: CampusPilotPlanningState,
    ) -> list[str]:
        completed = set(state["completed_courses"])
        mandatory = [
            rule["course_code"]
            for rule in state["rules"]
            if rule["rule_type"] in MANDATORY_RULES
            and rule["course_code"] not in completed
        ]
        electives = [
            rule["course_code"]
            for rule in state["rules"]
            if rule["rule_type"] in {"PRESCRIBED_ELECTIVE", "GENERAL_ELECTIVE"}
            and rule["course_code"] not in completed
        ]
        selected = list(dict.fromkeys(mandatory))
        selected_credits = sum(
            self.catalog.courses[code]["credit_points"] for code in selected
        )
        for code in dict.fromkeys(electives):
            if selected_credits >= state["remaining_credits"]:
                break
            selected.append(code)
            selected_credits += self.catalog.courses[code]["credit_points"]
        if selected_credits < state["remaining_credits"]:
            raise ValueError("official sample lacks enough eligible electives")
        return selected

    def _prioritize_practice_courses(
        self,
        course_codes: list[str],
    ) -> list[str]:
        practice_terms = (
            "professional practice",
            "industry",
            "project management",
            "studio project",
        )
        indexed = list(enumerate(course_codes))
        indexed.sort(
            key=lambda item: (
                0
                if any(
                    term in self.catalog.courses[item[1]]["course_name"].lower()
                    for term in practice_terms
                )
                else 1,
                item[0],
            )
        )
        return [course_code for _, course_code in indexed]

    def _schedule_courses(
        self,
        course_codes: list[str],
        *,
        completed: set[str],
        initial_program_credits: int,
        start_semester: str,
        strategy: dict[str, Any],
        role_by_course: dict[str, str],
    ) -> dict[str, Any]:
        pending = list(course_codes)
        semesters = []
        errors: list[str] = []
        year, semester_number = self._parse_semester(start_semester)
        program_credits = initial_program_credits
        attempts = 0
        while pending and attempts < 12:
            semester_code = f"S{semester_number}"
            semester_name = f"{year} S{semester_number}"
            semester_key = f"{year}-S{semester_number}"
            semester_limits = strategy.get("semester_course_limits")
            capacity = (
                semester_limits.get(semester_key, 0)
                if semester_limits is not None
                else strategy["capacity"]
            )
            if capacity == 0:
                year, semester_number = self._next_semester(
                    year,
                    semester_number,
                )
                attempts += 1
                continue
            eligible = []
            for code in pending:
                course = self.catalog.courses[code]
                if semester_code not in course["offerings"]:
                    continue
                if not set(course["prerequisites"]) <= completed:
                    continue
                if not self._capstone_is_eligible(
                    code,
                    course,
                    pending,
                    capacity,
                    program_credits,
                    semester_code,
                ):
                    continue
                eligible.append(code)
            selected = (
                self._select_balanced_courses(
                    eligible,
                    capacity,
                    role_by_course,
                )
                if strategy.get("balance_workload")
                else eligible[:capacity]
            )
            if selected:
                semesters.append(
                    {
                        "semester": semester_name,
                        "total_credits": sum(
                            self.catalog.courses[code]["credit_points"]
                            for code in selected
                        ),
                        "courses": [
                            {
                                **self.catalog.courses[code],
                                "rule_type": role_by_course[code],
                                **self._course_planning_indicators(
                                    self.catalog.courses[code],
                                    role_by_course[code],
                                ),
                            }
                            for code in selected
                        ],
                    }
                )
                earned = sum(
                    self.catalog.courses[code]["credit_points"] for code in selected
                )
                program_credits += earned
                pending = [code for code in pending if code not in selected]
                completed.update(selected)
            year, semester_number = self._next_semester(
                year,
                semester_number,
            )
            attempts += 1
        if pending:
            errors.append("在 12 个学期窗口内无法安排：" + "、".join(pending))
        return {
            "plan_id": strategy["id"],
            "name": strategy["name"],
            "description": strategy["description"],
            "semesters": semesters,
            "estimated_semesters": len(semesters),
            "scheduled_credits": sum(
                semester["total_credits"] for semester in semesters
            ),
            "scheduling_errors": errors,
        }

    def _select_balanced_courses(
        self,
        eligible: list[str],
        capacity: int,
        role_by_course: dict[str, str],
    ) -> list[str]:
        buckets = {"HIGH": [], "MEDIUM": [], "LOW": []}
        for code in eligible:
            indicators = self._course_planning_indicators(
                self.catalog.courses[code],
                role_by_course[code],
            )
            buckets[indicators["workload_level"]].append(code)

        selected: list[str] = []
        pattern = ("MEDIUM", "LOW", "HIGH", "LOW")
        while len(selected) < capacity and any(buckets.values()):
            added = False
            for level in pattern:
                if len(selected) >= capacity:
                    break
                if buckets[level]:
                    selected.append(buckets[level].pop(0))
                    added = True
            if not added:
                break
        return selected

    @staticmethod
    def _course_planning_indicators(
        course: dict[str, Any],
        rule_type: str,
    ) -> dict[str, Any]:
        if course["credit_points"] >= 12 or rule_type in {
            "CAPSTONE",
            "RESEARCH_CORE",
        }:
            workload_level = "HIGH"
            workload_reason = "12 学分项目课或研究/毕业课程，需要预留连续时间。"
        elif (
            course.get("prerequisites")
            or course.get("assumed_knowledge")
            or rule_type in {"CORE", "SPECIALISATION_CORE"}
        ):
            workload_level = "MEDIUM"
            workload_reason = "包含先修/预备知识要求或属于项目核心课程。"
        else:
            workload_level = "LOW"
            workload_reason = "当前结构化规则未显示额外先修或高学分约束。"
        final_exam = course.get("final_exam")
        exam_status = (
            "YES" if final_exam is True else "NO" if final_exam is False else "UNKNOWN"
        )
        return {
            "workload_level": workload_level,
            "workload_reason": workload_reason,
            "exam_status": exam_status,
            "exam_note": (
                "来自课程官方考核信息。"
                if exam_status != "UNKNOWN"
                else "当前官方样本未收录考核形式，请在选课前核对课程大纲。"
            ),
            "attendance_status": course.get(
                "attendance_status",
                "UNKNOWN",
            ),
            "attendance_note": course.get(
                "attendance_note",
                "当前 Handbook 未提供本学期出勤计分或出勤门槛，请以 Unit Guide 为准。",
            ),
            "assessment_tags": (
                course.get("assessment_tags")
                or (["期末考试"] if final_exam is True else ["考核待核实"])
            )[:2],
        }

    @staticmethod
    def _capstone_is_eligible(
        course_code: str,
        course: dict[str, Any],
        pending: list[str],
        capacity: int,
        program_credits: int,
        semester_code: str,
    ) -> bool:
        if course_code != "FIT5120":
            return True
        thresholds = course.get(
            "minimum_program_credits_by_semester",
            {"S1": 72, "S2": 66},
        )
        if program_credits < thresholds[semester_code]:
            return False
        other_pending = [code for code in pending if code != course_code]
        return len(other_pending) <= capacity - 1

    @staticmethod
    def _parse_semester(value: str) -> tuple[int, int]:
        try:
            year_text, semester_text = value.upper().split(
                "-S",
                maxsplit=1,
            )
            year = int(year_text)
            semester_number = int(semester_text)
        except (TypeError, ValueError) as exc:
            raise ValueError("start_semester must look like 2026-S1") from exc
        if semester_number not in {1, 2}:
            raise ValueError("semester must be S1 or S2")
        return year, semester_number

    @staticmethod
    def _next_semester(year: int, semester_number: int) -> tuple[int, int]:
        if semester_number == 2:
            return year + 1, 1
        return year, 2


class CampusPilotConversationAgent:
    """Deterministic conversation layer over verified planning tools."""

    PLAN_TERMS = (
        "规划",
        "方案",
        "最快",
        "尽快",
        "怎么选课",
        "如何选课",
        "怎么安排",
        "如何安排",
        "安排课程",
        "负载均衡",
        "负荷均衡",
        "实习",
        "行业实践",
        "industry experience",
        "internship",
        "placement",
        "wil",
        "study plan",
        "graduate fast",
    )
    PROGRESS_TERMS = (
        "进度",
        "还差",
        "多少学分",
        "毕业了吗",
        "能否毕业",
        "degree progress",
        "credits remaining",
    )
    COURSE_ROLE_TERMS = (
        "什么课",
        "算什么",
        "必修",
        "选修",
        "capstone",
        "course role",
    )
    ROLE_LABELS = {
        "FOUNDATION_CORE": "基础必修课",
        "CORE": "项目必修课",
        "RESEARCH_CORE": "研究必修课",
        "SPECIALISATION_CORE": "方向必修课",
        "PRESCRIBED_ELECTIVE": "限定选修课",
        "GENERAL_ELECTIVE": "普通选修课",
        "CAPSTONE": "毕业项目课",
        "NOT_ELIGIBLE": "不计入毕业学分",
    }
    CAPABILITY_TERMS = (
        "你好",
        "您好",
        "你是谁",
        "能做什么",
        "可以做什么",
        "怎么用",
        "hello",
        "hi ",
        "help",
    )
    RECRUITMENT_TERMS = (
        "春招",
        "秋招",
        "校招",
        "校园招聘",
        "招聘时间",
        "什么时候投",
        "网申时间",
        "招聘对象",
        "应届生招聘",
        "campus recruitment",
    )
    PROGRAM_RECOMMENDATION_TERMS = (
        "推荐专业",
        "适合什么专业",
        "适合哪个专业",
        "选什么专业",
        "专业没想好",
        "还没选专业",
        "根据性格",
        "根据兴趣",
        "根据就业",
        "适合读什么",
        "适合学什么",
        "哪个方向适合",
        "推荐方向",
        "推荐我选什么",
        "推荐选什么",
        "能移民",
        "移民专业",
        "移民方向",
        "移民分数",
        "更易获邀",
        "容易获邀",
        "州担保专业",
        "recommend a major",
        "recommend a program",
        "which major",
    )

    def __init__(
        self,
        catalog: CampusPilotCatalog | None = None,
        planning_agent: CampusPilotPlanningAgent | None = None,
        goal_interpreter: Any | None = None,
        terminology: AustralianTerminologyGlossary | None = None,
        handbook_qa_agent: HandbookQuestionAnsweringAgent | None = None,
        plan_narrator: StudyPlanNarrator | None = None,
        faq_service: CampusPilotFaqService | None = None,
        recruitment_agent: RecruitmentQuestionAnsweringAgent | None = None,
        program_recommendation_service: ProgramRecommendationService | None = None,
    ) -> None:
        self.catalog = catalog or CampusPilotCatalog()
        self.planning_agent = planning_agent or CampusPilotPlanningAgent(self.catalog)
        self.goal_interpreter = goal_interpreter
        self.terminology = terminology or AustralianTerminologyGlossary()
        self.handbook_qa_agent = handbook_qa_agent
        self.plan_narrator = plan_narrator or StudyPlanNarrator()
        self.faq_service = faq_service or CampusPilotFaqService()
        self.recruitment_agent = recruitment_agent
        self.program_recommendation_service = (
            program_recommendation_service or ProgramRecommendationService()
        )

    def respond(self, request: dict[str, Any]) -> dict[str, Any]:
        query = request["message"].strip()
        intent_locked = bool(request.get("_intent_locked"))
        intent = request.get("_resolved_intent")
        course_code = request.get("_resolved_course_code")
        if not intent:
            intent, course_code = self._detect_intent(
                query,
                request.get("conversation_history", []),
            )
        interpretation = request.get("_intent_interpretation")
        goal_summary = (
            interpretation.get("goal_summary", query)
            if interpretation
            else query
        )
        interpretation_source = request.get(
            "_intent_source",
            "deterministic",
        )
        interpretation_error = None
        interpretation_attempted = bool(
            request.get("_goal_interpretation_attempted")
        )
        # Direct callers still receive cloud understanding. The outer
        # conversation graph passes its typed decision here so the same turn
        # never spends a second LLM request on intent parsing.
        if (
            not interpretation_attempted
            and self.goal_interpreter is not None
            and intent not in {
            "handbook_qa",
            "recruitment_qa",
            }
        ):
            try:
                interpretation = self.goal_interpreter.interpret(
                    query,
                    request.get("conversation_history", []),
                    planning_context={
                        "program_variant_id": request.get("program_variant_id"),
                        "handbook_year": request.get("handbook_year"),
                        "study_stream": request.get("study_stream"),
                        "completed_courses": request.get(
                            "completed_courses",
                            [],
                        ),
                        "max_courses_per_semester": request.get(
                            "max_courses_per_semester"
                        ),
                        "start_semester": request.get("start_semester"),
                        "preserve_policy_flexibility": request.get(
                            "preserve_policy_flexibility"
                        ),
                    },
                )
                if not intent_locked:
                    intent = interpretation["intent"]
                goal_summary = interpretation["goal_summary"]
                course_code = interpretation.get("course_code") or course_code
                interpretation_source = "cloud_llm"
            except Exception as exc:
                interpretation_error = type(exc).__name__
        trace = [
            {
                "tool": "understand_user_intent",
                "ok": interpretation_error is None,
                "intent": intent,
                "course_code": course_code,
                "source": interpretation_source,
                "fallback_reason": interpretation_error,
                "terminology_terms": (
                    interpretation.get("terminology_terms", [])
                    if interpretation
                    else []
                ),
            }
        ]
        if intent == "ambiguous":
            question = (
                interpretation.get("clarification_question")
                if interpretation
                else None
            ) or "我还不能确定你要查课程事实、毕业进度，还是生成学习方案。请补充具体目标。"
            return self._response(
                query=query,
                intent=intent,
                status="needs_clarification",
                message=question,
                suggestions=[
                    "查询一门课的考核方式",
                    "计算当前毕业进度",
                    "生成个性化学习方案",
                ],
                trace=trace,
                next_action="ask_intent_clarification",
                confidence="low",
                effective_query=goal_summary,
                answer_source="structured_intent_clarification",
            )
        terminology_text = " ".join(
            [
                *(
                    item.get("content", "")
                    for item in request.get(
                        "conversation_history",
                        [],
                    )[-4:]
                ),
                query,
            ]
        )
        terminology_hits = self.terminology.search(terminology_text)
        if terminology_hits:
            trace.append(
                {
                    "tool": "search_australian_terminology",
                    "ok": True,
                    "count": len(terminology_hits),
                    "term_ids": [item["term_id"] for item in terminology_hits],
                    "source": "official_australian_glossary",
                }
            )

        if intent == "recruitment_qa":
            if self.recruitment_agent is None:
                return self._response(
                    query=query,
                    intent=intent,
                    status="unavailable",
                    message="国内企业招聘知识库尚未启用。",
                    suggestions=["补充企业名称和毕业届次"],
                    trace=trace,
                    next_action="enable_recruitment_knowledge_base",
                    confidence="low",
                    answer_source="recruitment_agent_unavailable",
                )
            answer = self.recruitment_agent.answer(query)
            trace.extend(answer["trace"])
            return self._response(
                query=query,
                intent=intent,
                status=(
                    "needs_clarification"
                    if answer["answer_source"] == "recruitment_no_evidence"
                    else "completed"
                ),
                message=answer["message"],
                suggestions=["查看企业官方招聘页", "补充毕业届次"],
                trace=trace,
                next_action=answer["next_action"],
                confidence=answer["confidence"],
                evidence=answer["evidence"],
                answer_source=answer["answer_source"],
            )

        if intent == "program_recommendation":
            conversation_context = self._recommendation_context(
                request.get("conversation_history", [])
            )
            recommendation = self.program_recommendation_service.recommend(
                {
                    "prompt": query,
                    "conversation_context": conversation_context,
                    "university": request.get("target_university"),
                    "undergraduate_major": request.get("undergraduate_major"),
                    "career_goal": request.get("career_goal"),
                    "personality": request.get("personality"),
                    "preferences": request.get("preferences"),
                    "score_value": request.get("score_value"),
                    "score_scale": request.get("score_scale"),
                    # Explicit keyword matches stay deterministic. When no
                    # direction matches, the recommendation Agent decides the
                    # academic directions before catalog grounding.
                    "allow_agent_direction_recommendation": True,
                    "is_recommendation_follow_up": (
                        "recommendation_profile"
                        in request.get("_pending_fields", [])
                    ),
                }
            )
            trace.extend(recommendation["trace"])
            questions = recommendation["clarifying_questions"]
            message = recommendation["message"]
            if questions:
                message = f"{message}\n\n{questions[0]}"
            if recommendation.get("uncatalogued_directions"):
                suggestions = [
                    "我接受注册课程和实习要求",
                    "优先结合我的已有学历背景",
                    "继续核验最新官方政策",
                ]
            elif recommendation.get("profile", {}).get("exploration_mode"):
                suggestions = [
                    "我更偏技术开发和编程",
                    "我更偏数据分析和业务问题",
                    "我更偏沟通协调和商业管理",
                ]
            elif not recommendation["recommendations"]:
                suggestions = [
                    "我喜欢写代码和技术",
                    "我喜欢数据分析和商业",
                    "我喜欢沟通、创意和管理",
                ]
            else:
                suggestions = ["选择一个候选项目", "继续检查公开录取门槛"]
            has_recommendation_output = bool(
                recommendation["recommendations"]
                or recommendation.get("uncatalogued_directions")
            )
            return self._response(
                query=query,
                intent=intent,
                status=(
                    "completed"
                    if has_recommendation_output
                    else "needs_clarification"
                ),
                message=message,
                missing_fields=(
                    []
                    if has_recommendation_output
                    else ["recommendation_profile"]
                ),
                suggestions=suggestions,
                trace=trace,
                next_action=recommendation["next_action"],
                confidence=recommendation["confidence"],
                effective_query=recommendation["effective_query"],
                answer_source=recommendation["answer_source"],
                program_recommendations=recommendation,
            )

        planning_preferences = self._derive_planning_preferences(
            f"{terminology_text} {goal_summary}"
        )
        if intent == "study_plan":
            trace.append(
                {
                    "tool": "derive_planning_preferences",
                    "ok": True,
                    **planning_preferences,
                }
            )

            # Only C6001 currently has a complete structured planning model.
            # Other programs still receive useful planning advice, grounded in
            # their official Handbook pages, instead of being forced through
            # the C6001 rule engine or rejected as "not verified".
            requested_program_code = (
                self._program_code_from_query(query)
                or self._program_code_from_request(request)
            )
            if requested_program_code and requested_program_code != "C6001":
                return self._answer_program_planning_advisory(
                    query=query,
                    effective_query=goal_summary,
                    request=request,
                    program_code=requested_program_code,
                    trace=trace,
                )

        missing = self._missing_fields(
            request,
            require_course=intent == "course_role",
            course_code=course_code,
        )
        if intent in {"degree_progress", "study_plan", "course_role"} and missing:
            labels = {
                "program_variant_id": "入学层级",
                "study_stream": "学习路径",
                "course_code": "课程代码",
            }
            readable = "、".join(labels[field] for field in missing)
            trace.append(
                {
                    "tool": "check_required_context",
                    "ok": False,
                    "missing_fields": missing,
                }
            )
            return self._response(
                query=query,
                intent=intent,
                status="needs_clarification",
                message=f"继续之前还需要确认：{readable}。",
                missing_fields=missing,
                suggestions=["先补充上述信息，再继续规划"],
                trace=trace,
                next_action="ask_clarification",
                confidence="low",
                effective_query=goal_summary,
                answer_source=self._answer_source(interpretation_source),
            )

        suppress_optional_clarification = (
            intent == "study_plan"
            and bool(request.get("program_variant_id"))
            and bool(request.get("study_stream"))
        )
        if (
            interpretation
            and interpretation["needs_clarification"]
            and not suppress_optional_clarification
        ):
            question = (
                interpretation.get("clarification_question")
                or "为了给出更合适的方案，你最优先考虑什么？"
            )
            return self._response(
                query=query,
                effective_query=goal_summary,
                intent=intent,
                status="needs_clarification",
                message=question,
                suggestions=["优先实习机会", "优先尽快毕业", "优先均衡负担"],
                trace=trace,
                next_action="ask_goal_clarification",
                confidence="medium",
                answer_source="cloud_goal_interpretation",
            )
        if (
            interpretation
            and interpretation["needs_clarification"]
            and suppress_optional_clarification
        ):
            trace[0]["clarification_suppressed"] = True

        if intent == "capabilities":
            return self._response(
                query=query,
                intent=intent,
                status="ready",
                message=(
                    "你可以直接问我：还差多少学分、怎样尽快毕业，"
                    "或者某门课在当前培养方案中算什么类型。"
                ),
                suggestions=[
                    "我还差多少学分？",
                    "帮我生成最快毕业方案",
                    "FIT5120 在当前路径中算什么课？",
                ],
                trace=trace,
                next_action="wait_for_user_goal",
                confidence="high",
                effective_query=goal_summary,
                answer_source=self._answer_source(interpretation_source),
            )

        if intent == "handbook_qa":
            # FAQ matching uses the user's original wording. Goal interpretation
            # may paraphrase it, which is useful for RAG but would break exact FAQ
            # aliases and waste an unnecessary retrieval/model call.
            faq_result = self.faq_service.search(query)
            trace.append(faq_result)
            if faq_result["hit"]:
                faq_data = faq_result["data"]
                return self._response(
                    query=query,
                    intent=intent,
                    status="completed",
                    message=faq_data["answer"],
                    suggestions=["查看官方来源", "继续询问具体项目或课程"],
                    trace=trace,
                    next_action="answer_user",
                    confidence="high",
                    evidence=[
                        {
                            "citation_number": 1,
                            "document_id": faq_data["faq_id"],
                            "source_id": faq_data["faq_id"],
                            "title": faq_data["source_title"],
                            "heading": "FAQ",
                            "handbook_year": request.get("handbook_year"),
                            "source_type": "verified_faq",
                            "source_url": faq_data["source_url"],
                            "content": faq_data["answer"],
                            "retrieval_channels": ["faq_exact"],
                            "score": faq_data["score"],
                        }
                    ],
                    effective_query=goal_summary,
                    answer_source="campuspilot_faq",
                )
            if self.handbook_qa_agent is None:
                return self._response(
                    query=query,
                    intent=intent,
                    status="unavailable",
                    message="Handbook 问答 Agent 尚未启用。",
                    suggestions=["稍后重试"],
                    trace=trace,
                    next_action="enable_handbook_retrieval",
                    confidence="low",
                    effective_query=goal_summary,
                    answer_source="handbook_agent_unavailable",
                )
            # An explicit unit code should remain searchable even when the UI
            # currently has another program selected. Program-level questions
            # still retain the selected program as a retrieval boundary.
            program_code = (
                None if course_code else self._program_code_from_request(request)
            )
            answer = self.handbook_qa_agent.answer(
                goal_summary,
                handbook_year=request.get("handbook_year", 2026),
                university_id="monash",
                program_code=program_code,
            )
            trace.extend(answer["trace"])
            return self._response(
                query=query,
                intent=intent,
                status=(
                    "needs_clarification"
                    if answer["answer_source"] == "handbook_no_evidence"
                    else "completed"
                ),
                message=answer["message"],
                suggestions=["查看官方来源", "继续询问具体课程代码"],
                trace=trace,
                next_action=answer["next_action"],
                confidence=answer["confidence"],
                evidence=answer["evidence"],
                effective_query=goal_summary,
                answer_source=answer["answer_source"],
                retry_count=answer.get("retry_count", 0),
            )

        trace.append(
            {
                "tool": "check_required_context",
                "ok": True,
                "missing_fields": [],
            }
        )
        if intent == "degree_progress":
            progress = self.planning_agent.calculate_progress(request)
            trace.extend(progress["trace"])
            return self._response(
                query=query,
                intent=intent,
                status="completed",
                message=(
                    f"当前已计入 {progress['completed_credits']} 学分，"
                    f"距离项目要求还差 {progress['remaining_credits']} 学分。"
                ),
                suggestions=["查看详细学分分组", "继续生成三套学习方案"],
                trace=trace,
                next_action=progress["next_action"],
                confidence=progress["confidence"],
                progress=progress,
                effective_query=goal_summary,
                answer_source=self._answer_source(interpretation_source),
            )

        if intent == "study_plan":
            planning_request = {
                **request,
                "planning_goal": planning_preferences["planning_goal"],
                "planning_goals": planning_preferences["planning_goals"],
                "target_recruitment_year": planning_preferences.get(
                    "target_recruitment_year"
                ),
            }
            if planning_preferences["max_courses_override"] is not None:
                planning_request["max_courses_per_semester"] = min(
                    request["max_courses_per_semester"],
                    planning_preferences["max_courses_override"],
                )
            plans = self.planning_agent.plan(planning_request)
            trace.extend(plans["trace"])
            narration = self.plan_narrator.narrate(
                query=query,
                preferences=planning_preferences,
                plans=plans,
            )
            trace.extend(narration["trace"])
            return self._response(
                query=query,
                intent=intent,
                status="completed",
                message=narration["message"],
                suggestions=["查看并对比三套方案", "把每学期负荷改成 3 门"],
                trace=trace,
                next_action=plans["next_action"],
                confidence=plans["confidence"],
                study_plans=plans,
                effective_query=goal_summary,
                answer_source=narration["answer_source"],
            )

        role = self.catalog.classify_course_role(
            program_variant_id=request["program_variant_id"],
            handbook_year=request["handbook_year"],
            study_stream=request["study_stream"],
            course_code=course_code,
        )
        trace.append(
            {
                "tool": "classify_course_role",
                "ok": True,
                "course_code": course_code,
                "rule_type": role["rule_type"],
            }
        )
        return self._response(
            query=query,
            intent=intent,
            status="completed",
            message=(
                f"{course_code} 在当前培养方案中属于 "
                f"{self.ROLE_LABELS.get(role['rule_type'], role['rule_type'])}，"
                f"计入 {role['credits_counted']} 学分。"
            ),
            suggestions=["查看课程规则证据", "继续检查毕业进度"],
            trace=trace,
            next_action="show_course_role_evidence",
            confidence="high",
            course_role=role,
            effective_query=goal_summary,
            answer_source=self._answer_source(interpretation_source),
        )

    def _answer_program_planning_advisory(
        self,
        *,
        query: str,
        effective_query: str,
        request: dict[str, Any],
        program_code: str,
        trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trace.append(
            {
                "tool": "route_program_planning_advisory",
                "ok": True,
                "program_code": program_code,
                "reason": "structured_rules_unavailable_use_official_sources",
            }
        )
        if self.handbook_qa_agent is None:
            return self._response(
                query=query,
                intent="study_plan",
                status="unavailable",
                message="官方 Handbook 建议服务暂不可用，请稍后重试。",
                suggestions=["稍后重试"],
                trace=trace,
                next_action="enable_handbook_retrieval",
                confidence="low",
                effective_query=effective_query,
                answer_source="handbook_agent_unavailable",
            )

        answer = self.handbook_qa_agent.answer(
            effective_query,
            handbook_year=request.get("handbook_year", 2026),
            university_id="monash",
            program_code=program_code,
        )
        trace.extend(answer["trace"])
        return self._response(
            query=query,
            intent="study_plan",
            status=(
                "needs_clarification"
                if answer["answer_source"] == "handbook_no_evidence"
                else "completed"
            ),
            message=answer["message"],
            suggestions=["查看官方来源", "继续补充你的学习目标和时间限制"],
            trace=trace,
            next_action=answer["next_action"],
            confidence=answer["confidence"],
            evidence=answer["evidence"],
            effective_query=effective_query,
            answer_source=answer["answer_source"],
            retry_count=answer.get("retry_count", 0),
        )

    @staticmethod
    def _derive_planning_preferences(text: str) -> dict[str, Any]:
        normalized = text.lower()
        explicit_course_limit = CampusPilotConversationAgent._course_limit_from_text(
            normalized
        )
        recruitment_year_match = re.search(
            r"(20\d{2})\s*年?(?:届)?(?:秋招|校招)",
            normalized,
        )
        recruitment_terms = ("秋招", "校招", "校园招聘")
        internship_terms = (
            "实习",
            "internship",
            "placement",
            "wil",
            "industry experience",
            "求职",
        )
        workload_balance_terms = (
            "负载均衡",
            "负荷均衡",
            "均衡负载",
            "均衡负荷",
            "不要太满",
            "别太满",
            "轻松",
            "低负荷",
            "workload balance",
        )
        fastest_terms = (
            "最快",
            "尽快",
            "早点毕业",
            "graduate fast",
        )
        flexibility_terms = (
            "保留弹性",
            "工签",
            "政策变化",
            "flexibility",
        )
        balance_terms = (
            "兼顾",
            "平衡",
            "两边",
            "同时保证",
            "both",
        )
        has_internship = any(term in normalized for term in internship_terms)
        if any(term in normalized for term in recruitment_terms):
            target_year = (
                int(recruitment_year_match.group(1))
                if recruitment_year_match
                else None
            )
            return {
                "planning_goal": "recruitment_readiness",
                "planning_goals": [
                    "academic_progress",
                    "recruitment_readiness",
                ],
                "max_courses_override": explicit_course_limit,
                "target_recruitment_year": target_year,
                "reason": (
                    f"用户希望围绕 {target_year} 年秋招安排学业和求职准备"
                    if target_year
                    else "用户希望围绕目标秋招安排学业和求职准备"
                ),
            }
        if has_internship and any(term in normalized for term in balance_terms):
            return {
                "planning_goal": "study_internship_balance",
                "planning_goals": [
                    "academic_progress",
                    "internship_readiness",
                ],
                "max_courses_override": explicit_course_limit,
                "reason": "用户要求同时保持学业进度并为实习留出时间",
            }
        if has_internship:
            return {
                "planning_goal": "internship_priority",
                "planning_goals": ["internship_readiness"],
                "max_courses_override": explicit_course_limit,
                "reason": "用户明确表达实习或求职优先目标",
            }
        if any(term in normalized for term in workload_balance_terms):
            return {
                "planning_goal": "workload_balance",
                "planning_goals": ["workload_balance"],
                "max_courses_override": explicit_course_limit,
                "reason": "用户要求均衡课程负载，但未自动降低每学期课程数",
            }
        if any(term in normalized for term in fastest_terms):
            return {
                "planning_goal": "fastest_completion",
                "planning_goals": ["fastest_completion"],
                "max_courses_override": explicit_course_limit,
                "reason": "用户明确要求缩短完成时间",
            }
        if any(term in normalized for term in flexibility_terms):
            return {
                "planning_goal": "policy_flexibility",
                "planning_goals": ["policy_flexibility"],
                "max_courses_override": explicit_course_limit,
                "reason": "用户明确要求保留政策或时间弹性",
            }
        return {
            "planning_goal": "compare_options",
            "planning_goals": ["compare_options"],
            "max_courses_override": explicit_course_limit,
            "reason": "未识别到单一优先目标，保留多方案比较",
        }

    @staticmethod
    def _course_limit_from_text(text: str) -> int | None:
        chinese_match = re.search(
            r"(?:每(?:个)?学期|一学期)[^。,.，]{0,10}?"
            r"(?:选|修|上|安排)?\s*([一二两三四1-4])\s*门",
            text,
        )
        if chinese_match:
            values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4}
            raw = chinese_match.group(1)
            return values.get(raw, int(raw) if raw.isdigit() else None)
        english_match = re.search(
            r"([1-4])\s*(?:courses?|units?)\s*(?:per|each)\s*semester",
            text,
        )
        return int(english_match.group(1)) if english_match else None

    @staticmethod
    def _answer_source(interpretation_source: str) -> str:
        if interpretation_source == "cloud_llm":
            return "cloud_goal_interpretation_and_deterministic_tools"
        return "deterministic_agent_tools"

    def _detect_intent(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, str | None]:
        current_intent, course_code = self._detect_explicit_intent(query)
        if current_intent is not None:
            return current_intent, course_code

        for item in reversed(history or []):
            if item.get("role") != "user":
                continue
            inherited_intent, inherited_course = self._detect_explicit_intent(
                item.get("content", "")
            )
            if inherited_intent is not None:
                return inherited_intent, inherited_course
        return "handbook_qa", course_code

    def _detect_explicit_intent(
        self,
        text: str,
    ) -> tuple[str | None, str | None]:
        normalized = text.lower()
        course_match = re.search(
            r"\b[A-Za-z]{2,5}\d{4}\b",
            text,
        )
        course_code = course_match.group(0).upper() if course_match else None
        has_recruitment_intent = any(
            term in normalized for term in self.RECRUITMENT_TERMS
        )
        has_program_recommendation_intent = any(
            term in normalized for term in self.PROGRAM_RECOMMENDATION_TERMS
        )
        has_migration_career_goal = (
            any(term in normalized for term in ("移民", "留澳"))
            and any(
                term in normalized
                for term in (
                    "专业",
                    "工作",
                    "职业",
                    "就业",
                    "程序员",
                    "读研",
                    "硕士",
                )
            )
        )
        has_planning_intent = any(term in normalized for term in self.PLAN_TERMS)
        if has_program_recommendation_intent or has_migration_career_goal:
            return "program_recommendation", course_code
        if has_recruitment_intent and has_planning_intent:
            return "study_plan", course_code
        if has_recruitment_intent:
            return "recruitment_qa", course_code
        if course_code and any(term in normalized for term in self.COURSE_ROLE_TERMS):
            return "course_role", course_code
        if has_planning_intent:
            return "study_plan", course_code
        if any(term in normalized for term in self.PROGRESS_TERMS):
            return "degree_progress", course_code
        if any(term in normalized for term in self.CAPABILITY_TERMS):
            return "capabilities", course_code
        if course_code:
            return "handbook_qa", course_code
        return None, None

    @staticmethod
    def _program_code_from_request(request: dict[str, Any]) -> str | None:
        variant = str(request.get("program_variant_id") or "")
        match = re.search(r"\b([A-Z]\d{4})\b", variant.upper())
        return match.group(1) if match else None

    @staticmethod
    def _program_code_from_query(query: str) -> str | None:
        match = re.search(r"\b([A-Za-z]\d{4})\b", query)
        return match.group(1).upper() if match else None

    def _recommendation_context(
        self,
        history: list[dict[str, str]],
    ) -> str:
        """Collect user profile turns back to the latest recommendation request."""
        collected: list[str] = []
        for item in reversed(history[-8:]):
            if item.get("role") != "user":
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            collected.append(content)
            intent, _ = self._detect_explicit_intent(content)
            if intent == "program_recommendation":
                break
        return " ".join(reversed(collected))

    @staticmethod
    def _missing_fields(
        request: dict[str, Any],
        *,
        require_course: bool,
        course_code: str | None,
    ) -> list[str]:
        missing = [
            field
            for field in ("program_variant_id", "study_stream")
            if not request.get(field)
        ]
        if require_course and not course_code:
            missing.append("course_code")
        return missing

    @staticmethod
    def _response(
        *,
        query: str,
        intent: str,
        status: str,
        message: str,
        suggestions: list[str],
        trace: list[dict[str, Any]],
        next_action: str,
        confidence: str,
        missing_fields: list[str] | None = None,
        progress: dict[str, Any] | None = None,
        study_plans: dict[str, Any] | None = None,
        course_role: dict[str, Any] | None = None,
        program_recommendations: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        effective_query: str | None = None,
        answer_source: str = "deterministic_agent_tools",
        retry_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "message": message,
            "intent": intent,
            "status": status,
            "missing_fields": missing_fields or [],
            "suggestions": suggestions,
            "progress": progress,
            "study_plans": study_plans,
            "course_role": course_role,
            "program_recommendations": program_recommendations,
            "evidence": evidence or [],
            "trace": trace,
            "trace_tools": [item["tool"] for item in trace],
            "answer_source": answer_source,
            "confidence": confidence,
            "next_action": next_action,
            "original_query": query,
            "effective_query": effective_query or query,
            "retry_count": retry_count,
        }
