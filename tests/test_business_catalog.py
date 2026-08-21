from __future__ import annotations

from pathlib import Path
import sys
import unittest

from pydantic import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.admission_mvp import AdmissionMvpService  # noqa: E402
from campuspilot_core.business_catalog import (  # noqa: E402
    BusinessProgramCatalogItem,
    load_business_program_catalog,
)


GO8_IDS = {
    "monash",
    "melbourne",
    "sydney",
    "unsw",
    "anu",
    "uq",
    "uwa",
    "adelaide",
}


class BusinessProgramCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_business_program_catalog()
        self.service = AdmissionMvpService()

    def test_external_catalog_has_twenty_official_programs(self) -> None:
        coverage = self.catalog.coverage()

        self.assertEqual(coverage["external_program_count"], 20)
        self.assertEqual(coverage["external_university_count"], 7)
        self.assertEqual(coverage["evaluation_ready_count"], 0)

    def test_all_go8_universities_expose_business_programs(self) -> None:
        counts = {
            university_id: len(
                self.service.find_programs(
                    university_id,
                    discipline_id="business",
                )["programs"]
            )
            for university_id in GO8_IDS
        }

        self.assertTrue(all(count > 0 for count in counts.values()))
        self.assertEqual(sum(counts.values()), 41)
        self.assertEqual(counts["monash"], 21)

    def test_business_filter_never_returns_computing_representative(self) -> None:
        result = self.service.find_programs(
            "The University of Melbourne",
            discipline_id="business",
        )

        self.assertEqual(result["catalog_scope"], "go8_business_common_programs_v1")
        self.assertTrue(result["programs"])
        self.assertTrue(
            all(item["discipline_id"] == "business" for item in result["programs"])
        )
        self.assertTrue(
            all(not item["evaluation_ready"] for item in result["programs"])
        )

    def test_catalog_rejects_research_degree(self) -> None:
        source = self.catalog.programs[0].model_dump(mode="json")
        source.update(
            program_id="invalid-phd",
            name="Doctor of Philosophy in Business",
        )

        with self.assertRaises(ValidationError):
            BusinessProgramCatalogItem.model_validate(source)


if __name__ == "__main__":
    unittest.main()
