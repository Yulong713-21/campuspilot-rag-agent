from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.api import create_app  # noqa: E402
from campuspilot_core.admission_mvp import AdmissionMvpService  # noqa: E402


class AdmissionMvpServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AdmissionMvpService()

    def test_school_only_returns_prioritized_projects_without_decision(self) -> None:
        result = self.service.find_programs("Monash")

        self.assertEqual(result["status"], "PROJECT_SELECTION_REQUIRED")
        self.assertIsNone(result["hard_decision"])
        self.assertEqual(result["programs"][0]["discipline_id"], "computing")
        self.assertFalse(result["catalog_complete"])
        self.assertEqual(
            result["catalog_scope"],
            "monash_priority_coursework_sample",
        )

    def test_business_program_is_released_but_unreviewed_rule_cannot_decide(
        self,
    ) -> None:
        result = self.service.find_programs("Monash", discipline_id="business")

        self.assertTrue(result["programs"])
        self.assertTrue(
            all(
                item["release_stage"] == "FIRST_STAGE_AVAILABLE"
                for item in result["programs"]
            )
        )
        self.assertTrue(
            all(not item["evaluation_ready"] for item in result["programs"])
        )

    def test_unreviewed_program_cannot_drive_hard_decision(self) -> None:
        result = self.service.evaluate(self._request(program="B6004"))

        self.assertEqual(result["status"], "RELIABLE_REQUIREMENTS_NOT_FOUND")
        self.assertEqual(result["next_action"], "request_rule_review")
        self.assertIsNone(result["hard_decision"])

    def test_melbourne_school_only_returns_incomplete_representative_catalog(
        self,
    ) -> None:
        result = self.service.find_programs("墨尔本大学")

        self.assertEqual(result["status"], "PROJECT_SELECTION_REQUIRED")
        self.assertFalse(result["catalog_complete"])
        self.assertEqual(result["programs"][0]["catalog_scope"], "representative_only")
        self.assertFalse(result["programs"][0]["evaluation_ready"])

    def test_unknown_university_exposes_ordered_fallback(self) -> None:
        result = self.service.find_programs("不存在大学")

        self.assertEqual(result["status"], "UNIVERSITY_NOT_IN_WHITELIST")
        self.assertEqual(
            result["fallback_sequence"][1], "official_website_runtime_search"
        )

    def test_raw_chinese_score_returns_preliminary_reference_comparison(self) -> None:
        result = self.service.evaluate(
            self._request(score_value=78, score_basis="RAW_PERCENT")
        )

        self.assertEqual(
            result["status"],
            "PRELIMINARY_ABOVE_PUBLISHED_REFERENCE",
        )
        self.assertEqual(
            result["next_action"],
            "verify_overseas_qualification_equivalence",
        )
        self.assertEqual(result["score_comparison"]["difference"], 18.0)
        self.assertIsNone(result["hard_decision"])

    def test_raw_chinese_score_below_reference_remains_preliminary(self) -> None:
        result = self.service.evaluate(
            self._request(score_value=58, score_basis="RAW_PERCENT")
        )

        self.assertEqual(
            result["status"],
            "PRELIMINARY_BELOW_PUBLISHED_REFERENCE",
        )
        self.assertEqual(result["score_comparison"]["difference"], -2.0)
        self.assertIsNone(result["hard_decision"])

    def test_four_point_gpa_is_recorded_without_linear_conversion(self) -> None:
        result = self.service.evaluate(
            self._request(score_value=3.4, score_scale=4, score_basis="GPA")
        )

        self.assertEqual(result["status"], "SCORE_SCALE_REQUIRES_EQUIVALENCE")
        self.assertEqual(result["score_comparison"]["applicant_score"], 3.4)
        self.assertEqual(result["score_comparison"]["score_scale"], 4.0)
        self.assertEqual(result["score_comparison"]["position"], "NOT_COMPARABLE")
        self.assertIsNone(result["hard_decision"])

    def test_verified_equivalent_score_meets_general_two_year_path(self) -> None:
        result = self.service.evaluate(self._request())

        self.assertEqual(result["status"], "MEETS_PUBLISHED_MINIMUM")
        self.assertEqual(result["selected_pathway"]["display_name"], "2年制项目")
        self.assertIn("不代表保证录取", result["message"])

    def test_cognate_coursework_can_unlock_shorter_path(self) -> None:
        result = self.service.evaluate(
            self._request(
                prior_coursework=[
                    "programming algorithms computer architecture",
                    "operating systems networks databases",
                ]
            )
        )

        self.assertEqual(result["status"], "MEETS_PUBLISHED_MINIMUM")
        self.assertEqual(result["selected_pathway"]["display_name"], "1.5年制项目")

    def test_below_minimum_does_not_get_changed_by_non_official_cases(self) -> None:
        result = self.service.evaluate(self._request(score_value=59))

        self.assertEqual(result["status"], "DOES_NOT_MEET_NO_ALTERNATIVE")
        self.assertEqual(
            result["hard_decision"],
            "DOES_NOT_MEET_PUBLISHED_MINIMUM",
        )

    def test_explicit_project_without_rules_is_controlled_no_answer(self) -> None:
        result = self.service.evaluate(
            self._request(university="Melbourne", program="Master of IT")
        )

        self.assertEqual(result["status"], "RELIABLE_REQUIREMENTS_NOT_FOUND")
        self.assertFalse(result["runtime_rule_can_persist"])

    def test_research_degree_is_permanently_out_of_mvp_scope(self) -> None:
        result = self.service.evaluate(
            self._request(requested_study_level="RESEARCH_DEGREE")
        )

        self.assertEqual(result["status"], "OUT_OF_SCOPE")

    def test_missing_university_requests_required_applicant_context(self) -> None:
        result = self.service.evaluate(self._request(university=""))

        self.assertEqual(result["status"], "INFORMATION_INSUFFICIENT")
        self.assertEqual(result["missing_fields"], ["university"])

    def test_engineering_is_not_open_in_current_release(self) -> None:
        result = self.service.evaluate(
            self._request(program="E6001", discipline_id="engineering")
        )

        self.assertEqual(result["status"], "OUT_OF_SCOPE")

    def test_remaining_average_uses_credit_weighting(self) -> None:
        result = self.service.calculate_remaining_average(
            {
                "current_average": 75,
                "target_final_average": 78,
                "completed_credits": 120,
                "total_credits": 160,
            }
        )

        self.assertEqual(result["status"], "TARGET_POSSIBLE")
        self.assertEqual(result["required_remaining_average"], 87.0)
        self.assertTrue(result["precise"])

    def test_missing_credit_progress_only_returns_rough_target(self) -> None:
        result = self.service.calculate_remaining_average(
            {"current_average": 75, "target_final_average": 78}
        )

        self.assertEqual(result["status"], "ESTIMATE_ONLY")
        self.assertFalse(result["precise"])

    @staticmethod
    def _request(**overrides):
        request = {
            "university": "Monash",
            "program": "C6001",
            "requested_study_level": "COURSEWORK_MASTER",
            "undergraduate_institution": "Verified example university",
            "undergraduate_major": "Computer Science",
            "score_value": 65,
            "score_scale": 100,
            "score_basis": "OFFICIAL_EQUIVALENT_PERCENT",
            "prior_coursework": [],
        }
        request.update(overrides)
        return request


class AdmissionMvpApiTest(unittest.TestCase):
    def setUp(self) -> None:
        logs_dir = REPO_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = TemporaryDirectory(dir=logs_dir)
        database = Path(self.temp_dir.name) / "admission-api.sqlite3"
        self.client_context = TestClient(create_app(database_path=database))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_school_search_api_does_not_emit_eligibility(self) -> None:
        response = self.client.get(
            "/api/admissions/programs",
            params={"university": "墨尔本大学"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "PROJECT_SELECTION_REQUIRED")
        self.assertIsNone(response.json()["hard_decision"])

    def test_business_catalog_api_returns_official_sydney_programs(self) -> None:
        response = self.client.get(
            "/api/admissions/programs",
            params={"university": "Sydney", "discipline_id": "business"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["catalog_scope"], "go8_business_common_programs_v1")
        self.assertEqual(len(payload["programs"]), 5)
        self.assertTrue(
            all(item["source_type"] == "OFFICIAL" for item in payload["programs"])
        )
        self.assertTrue(
            all(not item["evaluation_ready"] for item in payload["programs"])
        )

    def test_evaluation_api_returns_grounded_hard_result(self) -> None:
        response = self.client.post(
            "/api/admissions/evaluate",
            json=AdmissionMvpServiceTest._request(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "MEETS_PUBLISHED_MINIMUM")
        self.assertTrue(payload["evidence"])
        self.assertTrue(payload["evidence"][0]["hard_decision_allowed"])

    def test_invalid_credit_progress_returns_422(self) -> None:
        response = self.client.post(
            "/api/admissions/remaining-average",
            json={
                "current_average": 75,
                "target_final_average": 78,
                "completed_credits": 160,
                "total_credits": 160,
            },
        )

        self.assertEqual(response.status_code, 422)


class AdmissionDecisionFlowContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = (
            REPO_ROOT / "docs" / "ADMISSION_GPA_DECISION_FLOW.md"
        ).read_text(encoding="utf-8")

    def test_computing_and_business_are_first_release_scope(self) -> None:
        self.assertIn("计算机与商科均属于第一版", self.spec)
        self.assertNotIn("商科第二阶段开放", self.spec)

    def test_runtime_rules_require_review_before_hard_decision(self) -> None:
        self.assertIn("人工核验通过后才能进入正式规则库", self.spec)
        self.assertNotIn("允许直接入库", self.spec)

    def test_internal_review_state_is_not_public_eligibility_result(self) -> None:
        self.assertIn("内部审核状态", self.spec)
        self.assertNotIn("`MEETS_OFFICIAL_ALTERNATIVE_PATH`", self.spec)


if __name__ == "__main__":
    unittest.main()
