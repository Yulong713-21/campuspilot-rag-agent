from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot import (
    CampusPilotCatalog,
    CampusPilotEvidenceRetriever,
    CampusPilotPlanningAgent,
)


class CampusPilotCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = CampusPilotCatalog()

    def test_same_course_has_different_role_by_stream_context(self) -> None:
        industry_role = self.catalog.classify_course_role(
            program_variant_id="MONASH-C6001-EL2",
            handbook_year=2026,
            study_stream="Industry Experience",
            course_code="FIT5120",
        )
        research_role = self.catalog.classify_course_role(
            program_variant_id="MONASH-C6001-EL2",
            handbook_year=2026,
            study_stream="Research",
            course_code="FIT5120",
        )
        foundation_role = self.catalog.classify_course_role(
            program_variant_id="MONASH-C6001-EL1",
            handbook_year=2026,
            study_stream="Industry Experience",
            course_code="FIT9131",
        )

        self.assertEqual(industry_role["rule_type"], "CAPSTONE")
        self.assertEqual(research_role["rule_type"], "NOT_ELIGIBLE")
        self.assertEqual(foundation_role["rule_type"], "FOUNDATION_CORE")

    def test_program_comparison_exposes_duration_and_credit_difference(self) -> None:
        result = self.catalog.compare_programs(
            "MONASH-C6001-EL1",
            "MONASH-C6001-EL2",
            2026,
            "Industry Experience",
        )

        self.assertEqual(result["differences"]["duration_years"], -0.5)
        self.assertEqual(result["differences"]["credits_to_complete"], -24)
        self.assertEqual(result["data_mode"], "official_public_sample")

    def test_official_document_retrieval_returns_fit5120_evidence(self) -> None:
        retriever = CampusPilotEvidenceRetriever(
            self.catalog.data["official_documents"]
        )

        documents = retriever.search(
            "FIT5120 capstone final semester",
            handbook_year=2026,
        )

        self.assertEqual(documents[0]["document_id"], "DOC-FIT5120-2026")
        self.assertGreater(documents[0]["score"], 0)
        self.assertEqual(
            documents[0]["source_url"],
            "https://handbook.monash.edu/2026/units/FIT5120",
        )

    def test_go8_directory_has_eight_current_members(self) -> None:
        result = self.catalog.list_go8_universities("computing")

        self.assertEqual(result["count"], 8)
        self.assertEqual(result["planning_verified_count"], 1)
        self.assertIn(
            "Adelaide University",
            [item["name"] for item in result["universities"]],
        )

    def test_go8_directory_rejects_unknown_discipline(self) -> None:
        with self.assertRaisesRegex(ValueError, "discipline not found"):
            self.catalog.list_go8_universities("medicine")


class CampusPilotPlanningAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = CampusPilotPlanningAgent()
        self.request = {
            "program_variant_id": "MONASH-C6001-EL2",
            "handbook_year": 2026,
            "study_stream": "Industry Experience",
            "completed_courses": ["FIT5057"],
            "max_courses_per_semester": 4,
            "preserve_policy_flexibility": True,
            "start_semester": "2026-S2",
        }

    def test_generates_three_valid_plans_with_observable_trace(self) -> None:
        result = self.agent.plan(self.request)

        self.assertEqual(len(result["plans"]), 3)
        self.assertTrue(result["validation"]["all_valid"])
        self.assertEqual(result["completed_credits"], 6)
        self.assertEqual(result["remaining_credits"], 66)
        self.assertEqual(
            result["trace_tools"],
            [
                "search_official_evidence",
                "get_program_rules",
                "calculate_credit_progress",
                "generate_study_plan",
                "validate_study_plan",
            ],
        )
        self.assertGreater(len(result["evidence"]), 0)
        self.assertEqual(result["next_action"], "review_and_confirm_plan")

    def test_every_scheduled_course_respects_prerequisite_order(self) -> None:
        result = self.agent.plan(self.request)
        course_catalog = self.agent.catalog.courses

        for plan in result["plans"]:
            completed = set(self.request["completed_courses"])
            for semester in plan["semesters"]:
                semester_codes = {
                    course["course_code"]
                    for course in semester["courses"]
                }
                for code in semester_codes:
                    self.assertLessEqual(
                        set(course_catalog[code]["prerequisites"]),
                        completed,
                    )
                completed.update(semester_codes)

    def test_ineligible_completed_course_is_not_counted(self) -> None:
        request = {
            **self.request,
            "program_variant_id": "MONASH-C6001-EL2",
            "study_stream": "Research",
            "completed_courses": ["FIT5120"],
        }

        result = self.agent.plan(request)

        self.assertEqual(result["completed_credits"], 0)
        self.assertIn("FIT5120", result["warnings"][0])

    def test_custom_semester_limits_allow_skip_and_variable_load(self) -> None:
        request = {
            **self.request,
            "semester_course_limits": {
                "2026-S2": 2,
                "2027-S1": 0,
                "2027-S2": 4,
                "2028-S1": 3,
                "2028-S2": 3,
                "2029-S1": 2,
            },
        }

        result = self.agent.plan(request)

        self.assertEqual(len(result["plans"]), 1)
        plan = result["plans"][0]
        self.assertEqual(plan["plan_id"], "custom")
        self.assertNotIn(
            "2027 S1",
            [semester["semester"] for semester in plan["semesters"]],
        )
        limits = request["semester_course_limits"]
        for semester in plan["semesters"]:
            key = semester["semester"].replace(" ", "-")
            self.assertLessEqual(len(semester["courses"]), limits[key])

    def test_internship_goal_changes_strategy_order_and_course_priority(
        self,
    ) -> None:
        result = self.agent.plan(
            {
                **self.request,
                "planning_goal": "internship_priority",
                "max_courses_per_semester": 3,
            }
        )

        self.assertEqual(result["plans"][0]["plan_id"], "balanced")
        self.assertEqual(result["plans"][0]["name"], "实习优先")
        self.assertEqual(
            [plan["plan_id"] for plan in result["plans"]],
            ["balanced", "flexible", "fastest"],
        )
        generation_trace = next(
            item
            for item in result["trace"]
            if item["tool"] == "generate_study_plan"
        )
        self.assertEqual(
            generation_trace["planning_goal"],
            "internship_priority",
        )

    def test_course_indicators_are_explicit_when_unit_guide_is_missing(
        self,
    ) -> None:
        result = self.agent.plan(self.request)
        course = result["plans"][0]["semesters"][0]["courses"][0]

        self.assertEqual(course["attendance_status"], "UNKNOWN")
        self.assertIn("Unit Guide", course["attendance_note"])
        self.assertGreaterEqual(len(course["assessment_tags"]), 1)

    def test_merges_collected_official_assessment_details(self) -> None:
        course = self.agent.catalog.courses["FIT9131"]

        self.assertEqual(course["exam_weight_percent"], 45)
        self.assertTrue(course["final_exam"])
        self.assertEqual(course["hurdle_status"], "YES")
        self.assertEqual(
            course["assessment_tags"],
            ["考核门槛", "考试合计 45%"],
        )
        self.assertIn(
            "monash-fit9131-2026",
            course["source_ids"],
        )


if __name__ == "__main__":
    unittest.main()
