from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .business_catalog import (
    DEFAULT_BUSINESS_CATALOG,
    BusinessProgramCatalog,
    load_business_program_catalog,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ADMISSION_CATALOG = REPO_ROOT / "data/admissions/monash_2026.json"
DEFAULT_GO8_CATALOG = REPO_ROOT / "data/go8_official_catalog.json"


class AdmissionMvpService:
    """Deterministic MVP admission routing over verified official rules."""

    DISCIPLINE_PRIORITY = {
        "computing": 0,
        "business": 1,
        "engineering": 2,
        "mathematics_science": 3,
        "other": 4,
    }
    FALLBACK_SEQUENCE = [
        "project_whitelist",
        "official_website_runtime_search",
        "trusted_third_party_reference",
        "controlled_no_answer",
    ]
    OVERSEAS_ASSESSMENT_EVIDENCE = {
        "source_type": "OFFICIAL",
        "source_url": "https://www.monash.edu/admissions/entry-requirements/minimum",
        "excerpt": (
            "Applicants with overseas tertiary qualifications are assessed "
            "on a case-by-case basis."
        ),
        "evidence_grade": "A",
        "hard_decision_allowed": False,
    }

    def __init__(
        self,
        admission_catalog_path: str | Path = DEFAULT_ADMISSION_CATALOG,
        go8_catalog_path: str | Path = DEFAULT_GO8_CATALOG,
        business_catalog_path: str | Path = DEFAULT_BUSINESS_CATALOG,
    ) -> None:
        self.admission_data = json.loads(
            Path(admission_catalog_path).read_text(encoding="utf-8")
        )
        self.go8_data = json.loads(Path(go8_catalog_path).read_text(encoding="utf-8"))
        self.records = self.admission_data["records"]
        self.universities = self.go8_data["universities"]
        self.business_catalog: BusinessProgramCatalog = (
            load_business_program_catalog(business_catalog_path)
        )

    def find_programs(
        self,
        university_query: str,
        *,
        discipline_id: str | None = None,
    ) -> dict[str, Any]:
        university = self._find_university(university_query)
        if university is None:
            return self._result(
                status="UNIVERSITY_NOT_IN_WHITELIST",
                message="当前项目白名单中没有匹配到这所学校。",
                next_action="search_official_website",
                programs=[],
                fallback_sequence=self.FALLBACK_SEQUENCE,
            )
        programs = self._catalog_programs(university, discipline_id)
        return self._result(
            status="PROJECT_SELECTION_REQUIRED",
            message=("已经识别学校，但还需要具体授课型硕士项目才能判断录取条件。"),
            next_action="ask_user_to_select_program",
            university={
                "university_id": university["university_id"],
                "name": university["name"],
            },
            programs=programs,
            catalog_complete=False,
            catalog_scope=self._catalog_scope(university, discipline_id, programs),
            catalog_version=(
                self.business_catalog.catalog_version
                if university["university_id"] != "monash"
                and any(item.get("discipline_id") == "business" for item in programs)
                else self.admission_data.get("catalog_version")
            ),
            hard_decision=None,
        )

    def evaluate(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("requested_study_level") != "COURSEWORK_MASTER":
            return self._result(
                status="OUT_OF_SCOPE",
                message="MVP 只支持本科申请授课型硕士，博士和本科申请本科不在范围内。",
                next_action="explain_product_scope",
            )
        if not str(request.get("university") or "").strip():
            return self._insufficient(["university"])
        if request.get("discipline_id") == "engineering":
            return self._result(
                status="OUT_OF_SCOPE",
                message="工程项目尚未开放，当前版本先支持计算机与信息技术、商科。",
                next_action="explain_product_scope",
            )
        university = self._find_university(request.get("university", ""))
        if university is None:
            return self._result(
                status="UNIVERSITY_NOT_IN_WHITELIST",
                message="当前只处理澳洲八大授课型硕士。",
                next_action="search_official_website",
                fallback_sequence=self.FALLBACK_SEQUENCE,
            )
        project_query = request.get("program", "").strip()
        if not project_query:
            return self.find_programs(
                university["university_id"],
                discipline_id=request.get("discipline_id"),
            )
        program_records = self._find_program_records(
            university["university_id"],
            project_query,
        )
        if not program_records:
            return self._result(
                status="RELIABLE_REQUIREMENTS_NOT_FOUND",
                message="项目描述已经明确，但暂时没有查到可用于硬判断的可靠录取标准。",
                next_action="search_official_website",
                fallback_sequence=self.FALLBACK_SEQUENCE,
                runtime_rule_can_persist=False,
                hard_decision=None,
            )
        verified_records = [
            record
            for record in program_records
            if record.get("hard_decision_allowed") is True
        ]
        if not verified_records:
            return self._result(
                status="RELIABLE_REQUIREMENTS_NOT_FOUND",
                message=(
                    "已找到该项目的官方页面，但结构化规则尚未完成人工核验，"
                    "暂时不能用于录取硬判断。"
                ),
                next_action="request_rule_review",
                runtime_rule_can_persist=False,
                hard_decision=None,
            )
        program_records = verified_records
        missing = [
            field
            for field in (
                "undergraduate_institution",
                "undergraduate_major",
                "score_value",
                "score_scale",
                "score_basis",
            )
            if request.get(field) in (None, "")
        ]
        if missing:
            return self._insufficient(missing)
        if (
            request["score_basis"] == "RAW_PERCENT"
            and float(request["score_scale"]) == 100
        ):
            return self._preliminary_score_comparison(program_records, request)
        if request["score_basis"] == "GPA":
            score = float(request["score_value"])
            scale = float(request["score_scale"])
            return self._result(
                status="SCORE_SCALE_REQUIRES_EQUIVALENCE",
                message=(
                    f"已记录你的成绩为 {score:g}/{scale:g}。该 GPA 不能按线性比例"
                    "直接换算成百分制；需要匹配 Monash 对该本科院校和成绩制度的"
                    "官方等效口径后，才能与项目公开参考线比较。"
                ),
                next_action="match_score_scale_policy",
                missing_fields=["official_score_scale_conversion"],
                hard_decision=None,
                score_comparison={
                    "applicant_score": score,
                    "score_scale": scale,
                    "published_reference": None,
                    "difference": None,
                    "position": "NOT_COMPARABLE",
                    "comparison_only": True,
                },
                evidence=[
                    *self._evidence(program_records),
                    dict(self.OVERSEAS_ASSESSMENT_EVIDENCE),
                ],
            )
        if request["score_basis"] != "OFFICIAL_EQUIVALENT_PERCENT":
            return self._result(
                status="INFORMATION_INSUFFICIENT",
                message=(
                    "当前成绩还没有按该校对具体本科院校的官方口径完成换算，"
                    "因此不能直接与公开门槛比较。"
                ),
                next_action="match_institution_specific_score_policy",
                missing_fields=["official_institution_score_mapping"],
                hard_decision=None,
            )
        if float(request["score_scale"]) != 100:
            return self._result(
                status="INFORMATION_INSUFFICIENT",
                message="当前规则使用百分制等效成绩，其他 GPA 量表需要官方换算规则。",
                next_action="match_score_scale_policy",
                missing_fields=["official_score_scale_conversion"],
                hard_decision=None,
            )

        evaluations = [
            self._evaluate_path(record, request) for record in program_records
        ]
        passed = [item for item in evaluations if item["passed"]]
        if passed:
            selected = min(
                passed,
                key=lambda item: item.get("duration_months") or 999,
            )
            return self._result(
                status="MEETS_PUBLISHED_MINIMUM",
                message=(
                    f"按目前核验的官方要求，你满足{selected['display_name']}"
                    "已公开的最低学术门槛；这不代表保证录取。"
                ),
                next_action="explain_requirement_evidence",
                hard_decision="MEETS_PUBLISHED_MINIMUM",
                selected_pathway=selected,
                pathway_evaluations=evaluations,
                evidence=self._evidence(program_records),
            )
        unknown = [item for item in evaluations if item["status"] == "UNKNOWN"]
        if unknown:
            missing_fields = sorted(
                {field for item in unknown for field in item.get("missing_fields", [])}
            )
            return self._insufficient(
                missing_fields,
                pathway_evaluations=evaluations,
                evidence=self._evidence(program_records),
            )
        official_compensation = self._official_alternatives(
            program_records,
            pathway_type="COMPENSATION",
        )
        if official_compensation:
            status = "DOES_NOT_MEET_WITH_OFFICIAL_COMPENSATION"
            message = "未达到公开最低门槛，但发现官方明确认可的补偿路径。"
        else:
            bridge = self._official_alternatives(
                program_records,
                pathway_type="BRIDGE",
            )
            if bridge:
                status = "DOES_NOT_MEET_WITH_BRIDGE"
                message = "未达到公开最低门槛，但发现官方 Pre-Master 或桥梁项目。"
                official_compensation = bridge
            else:
                status = "DOES_NOT_MEET_NO_ALTERNATIVE"
                message = "未达到目前查到的官方最低门槛，且没有发现官方替代路径。"
        return self._result(
            status=status,
            message=message,
            next_action="show_official_evidence",
            hard_decision="DOES_NOT_MEET_PUBLISHED_MINIMUM",
            alternatives=official_compensation,
            pathway_evaluations=evaluations,
            evidence=self._evidence(program_records),
        )

    def _preliminary_score_comparison(
        self,
        records: list[dict[str, Any]],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = [
            float(record["minimum_average_percent"])
            for record in records
            if record.get("minimum_average_percent") is not None
        ]
        if not thresholds:
            return self._insufficient(
                ["structured_numeric_threshold"],
                evidence=self._evidence(records),
            )
        reference = min(thresholds)
        score = float(request["score_value"])
        difference = round(score - reference, 2)
        above = difference >= 0
        if above:
            status = "PRELIMINARY_ABOVE_PUBLISHED_REFERENCE"
            position_text = f"高 {difference:g} 分"
            summary = "分数层面初步高于公开参考线"
        else:
            status = "PRELIMINARY_BELOW_PUBLISHED_REFERENCE"
            position_text = f"低 {abs(difference):g} 分"
            summary = "分数层面初步低于公开参考线"
        return self._result(
            status=status,
            message=(
                f"你的当前均分为 {score:g}/100，项目公开参考线为 "
                f"{reference:g}%，{position_text}，{summary}。"
                "但 Monash 对海外高等教育资格按个案评估，"
                "该对比不能代替学校的正式等效换算，也不代表保证录取。"
            ),
            next_action="verify_overseas_qualification_equivalence",
            missing_fields=["official_institution_score_mapping"],
            hard_decision=None,
            score_comparison={
                "applicant_score": score,
                "score_scale": 100,
                "published_reference": reference,
                "difference": difference,
                "position": "ABOVE_OR_EQUAL" if above else "BELOW",
                "comparison_only": True,
            },
            evidence=[
                *self._evidence(records),
                dict(self.OVERSEAS_ASSESSMENT_EVIDENCE),
            ],
        )

    def calculate_remaining_average(self, request: dict[str, Any]) -> dict[str, Any]:
        target = request.get("target_final_average")
        current = request.get("current_average")
        if target is None or current is None:
            return self._insufficient(["target_final_average", "current_average"])
        completed = request.get("completed_credits")
        total = request.get("total_credits")
        if completed is None or total is None:
            return self._result(
                status="ESTIMATE_ONLY",
                message=(
                    f"由于缺少已修和剩余学分，当前只能把 {float(target):.2f} "
                    "作为粗略毕业目标，不能精确计算。"
                ),
                next_action="ask_for_credit_progress",
                precise=False,
                rough_target_average=round(float(target), 2),
            )
        completed_value = float(completed)
        total_value = float(total)
        if not 0 < completed_value < total_value:
            raise ValueError("completed_credits must be between 0 and total_credits")
        remaining = total_value - completed_value
        required = (
            float(target) * total_value - float(current) * completed_value
        ) / remaining
        status = "TARGET_POSSIBLE" if required <= 100 else "TARGET_NOT_POSSIBLE"
        return self._result(
            status=status,
            message=(
                f"为了毕业时达到 {float(target):.2f}，剩余 {remaining:g} 学分"
                f"平均需要达到 {required:.2f}。这不是录取保证。"
            ),
            next_action="show_remaining_score_target",
            precise=True,
            remaining_credits=remaining,
            required_remaining_average=round(required, 2),
        )

    def _catalog_programs(
        self,
        university: dict[str, Any],
        discipline_id: str | None,
    ) -> list[dict[str, Any]]:
        if university["university_id"] != "monash":
            business_programs = self.business_catalog.programs_for(
                university["university_id"]
            )
            if discipline_id == "business":
                return sorted(business_programs, key=lambda item: item["name"])
            if discipline_id not in (None, "computing"):
                return []
            representative = university.get("representative_program") or {}
            programs = []
            if representative:
                programs.append(
                    {
                        **representative,
                        "discipline_id": "computing",
                        "evaluation_ready": False,
                        "catalog_scope": "representative_only",
                        "release_stage": "FIRST_STAGE_AVAILABLE",
                    }
                )
            if discipline_id is None:
                programs.extend(business_programs)
            return sorted(
                programs,
                key=lambda item: (
                    self.DISCIPLINE_PRIORITY.get(item["discipline_id"], 99),
                    item["name"],
                ),
            )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in self.records:
            if discipline_id and record.get("discipline_id") != discipline_id:
                continue
            grouped.setdefault(record["program_code"], []).append(record)
        programs = []
        for code, records in grouped.items():
            durations = sorted(
                {
                    item["duration_months"]
                    for item in records
                    if item.get("duration_months") is not None
                }
            )
            programs.append(
                {
                    "program_code": code,
                    "name": records[0]["program_name"],
                    "discipline_id": records[0].get("discipline_id", "other"),
                    "coursework_master": True,
                    "duration_months": durations,
                    "intakes": records[0].get("available_intakes", []),
                    "official_url": records[0]["source_url"],
                    "evaluation_ready": all(
                        item.get("hard_decision_allowed") is True for item in records
                    ),
                    "release_stage": self._release_stage(
                        records[0].get("discipline_id", "other")
                    ),
                }
            )
        return sorted(
            programs,
            key=lambda item: (
                self.DISCIPLINE_PRIORITY.get(item["discipline_id"], 99),
                item["name"],
            ),
        )

    @staticmethod
    def _catalog_scope(
        university: dict[str, Any],
        discipline_id: str | None,
        programs: list[dict[str, Any]],
    ) -> str:
        if university["university_id"] == "monash":
            return "monash_priority_coursework_sample"
        has_business = any(
            item.get("discipline_id") == "business" for item in programs
        )
        if discipline_id == "business" and has_business:
            return "go8_business_common_programs_v1"
        if discipline_id is None and has_business:
            return "go8_priority_programs_v1"
        return "representative_only"

    def _find_program_records(
        self,
        university_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        if university_id != "monash":
            return []
        normalized = self._normalize(query)
        matches = [
            item
            for item in self.records
            if normalized == self._normalize(item["program_code"])
            or normalized == self._normalize(item["program_name"])
        ]
        return matches

    def _find_university(self, query: str) -> dict[str, Any] | None:
        normalized = self._normalize(query)
        aliases = {
            "墨尔本大学": "melbourne",
            "墨大": "melbourne",
            "莫纳什大学": "monash",
            "蒙纳士大学": "monash",
            "悉尼大学": "sydney",
            "新南威尔士大学": "unsw",
            "澳国立": "anu",
            "昆士兰大学": "uq",
            "西澳大学": "uwa",
            "阿德莱德大学": "adelaide",
        }
        target_id = aliases.get(query.strip())
        for university in self.universities:
            candidates = {
                self._normalize(university["university_id"]),
                self._normalize(university["name"]),
                self._normalize(university["short_name"]),
            }
            if target_id == university["university_id"] or normalized in candidates:
                return university
        return None

    def _evaluate_path(
        self,
        record: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        threshold = record.get("minimum_average_percent")
        result = {
            "pathway_code": record["pathway_code"],
            "display_name": record["display_name"],
            "duration_months": record.get("duration_months"),
            "minimum_average_percent": threshold,
            "passed": False,
            "status": "FAIL",
            "reasons": [],
        }
        if threshold is None:
            result.update(
                status="UNKNOWN",
                missing_fields=["structured_numeric_threshold"],
            )
            return result
        if float(request["score_value"]) < float(threshold):
            result["reasons"].append("score_below_published_minimum")
            return result
        requirements = record.get("requirements", {})
        if requirements.get("cognate_background_required"):
            major = request["undergraduate_major"].lower()
            if not self._is_cognate(record.get("discipline_id"), major):
                result["reasons"].append("cognate_background_not_met")
                return result
        subjects = requirements.get("subject_keywords", [])
        if subjects:
            coursework = " ".join(request.get("prior_coursework", [])).lower()
            if not coursework:
                result.update(
                    status="UNKNOWN",
                    missing_fields=["prior_coursework"],
                )
                return result
            missing_subjects = [
                subject for subject in subjects if subject not in coursework
            ]
            if missing_subjects:
                result["reasons"].append("required_subject_background_not_met")
                result["missing_subjects"] = missing_subjects
                return result
        result.update(passed=True, status="PASS")
        return result

    @staticmethod
    def _is_cognate(discipline_id: str | None, major: str) -> bool:
        markers = {
            "computing": (
                "computer",
                "computing",
                "software",
                "information technology",
                "data",
            ),
            "business": (
                "business",
                "commerce",
                "finance",
                "account",
                "economics",
                "management",
            ),
            "engineering": ("engineering",),
            "mathematics_science": ("mathematics", "statistics", "physics", "science"),
        }
        return any(marker in major for marker in markers.get(discipline_id, ()))

    @staticmethod
    def _official_alternatives(
        records: list[dict[str, Any]],
        *,
        pathway_type: str,
    ) -> list[dict[str, Any]]:
        return [
            pathway
            for record in records
            for pathway in record.get("official_alternative_pathways", [])
            if pathway.get("pathway_type") == pathway_type
            and pathway.get("official_compensation") is True
        ]

    @staticmethod
    def _evidence(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "source_type": "OFFICIAL",
                "source_url": record["source_url"],
                "excerpt": record["criteria_text"],
                "applicable_year": record["handbook_year"],
                "captured_at": record.get("captured_at"),
                "verified_at": record.get("verified_at"),
                "evidence_grade": ("A" if record.get("hard_decision_allowed") else "B"),
                "review_status": record.get(
                    "review_status",
                    "REVIEW_REQUIRED",
                ),
                "hard_decision_allowed": bool(
                    record.get("hard_decision_allowed", False)
                ),
            }
            for record in records
        ]

    def _insufficient(self, missing_fields: list[str], **extra: Any) -> dict[str, Any]:
        return self._result(
            status="INFORMATION_INSUFFICIENT",
            message="申请信息不足，暂时不能判断。",
            next_action="ask_for_missing_applicant_fields",
            missing_fields=missing_fields,
            hard_decision=None,
            **extra,
        )

    @staticmethod
    def _release_stage(discipline_id: str) -> str:
        return {
            "computing": "FIRST_STAGE_AVAILABLE",
            "business": "FIRST_STAGE_AVAILABLE",
            "engineering": "LATER_STAGE",
        }.get(discipline_id, "FUTURE_STAGE")

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value.lower())

    @staticmethod
    def _result(
        *, status: str, message: str, next_action: str, **data: Any
    ) -> dict[str, Any]:
        return {
            "status": status,
            "error_code": status,
            "message": message,
            "next_action": next_action,
            "trace_tools": ["admission_scope_router", "admission_rule_engine"],
            **data,
        }
