from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.institution_catalog import InstitutionCatalog  # noqa: E402


class InstitutionCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = InstitutionCatalog()

    def test_catalog_contains_official_china_undergraduate_count(self) -> None:
        self.assertEqual(self.catalog.data["counts"]["CN"], 1412)

    def test_chinese_alias_finds_official_institution(self) -> None:
        result = self.catalog.search("北大", country_code="CN")

        self.assertEqual(result["matches"][0]["official_name"], "北京大学")
        self.assertEqual(result["matches"][0]["match_type"], "exact_or_alias")
        self.assertEqual(len(result["matches"]), 1)

    def test_australian_abbreviation_finds_official_institution(self) -> None:
        result = self.catalog.search("UNSW", country_code="AU")

        self.assertEqual(
            result["matches"][0]["official_name"],
            "University of New South Wales",
        )

    def test_historical_name_is_searchable_but_not_active(self) -> None:
        result = self.catalog.search("University of South Australia")

        self.assertEqual(result["matches"][0]["active"], False)
        self.assertEqual(
            result["matches"][0]["superseded_by"],
            "Adelaide University",
        )

    def test_unknown_name_returns_controlled_custom_entry_path(self) -> None:
        result = self.catalog.search("不存在的大学xyz")

        self.assertEqual(result["matches"], [])
        self.assertTrue(result["allow_custom_entry"])
        self.assertEqual(
            result["next_action"],
            "accept_custom_institution_for_manual_verification",
        )


if __name__ == "__main__":
    unittest.main()
