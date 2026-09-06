from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.coverage import (  # noqa: E402
    AcademicCoverageRegistry,
    CoverageLevel,
)


class AcademicCoverageRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = AcademicCoverageRegistry.from_path()

    def test_all_declared_australian_institutions_have_catalog_coverage(self) -> None:
        summary = self.registry.summary()

        self.assertEqual(summary["country_code"], "AU")
        self.assertEqual(summary["model"], "CATALOG -> STRUCTURED -> VERIFIED")
        self.assertGreaterEqual(summary["record_count"], 9)

    def test_resolution_prefers_program_year_over_institution_default(self) -> None:
        institution = self.registry.resolve(university_id="monash")
        program = self.registry.resolve(
            university_id="monash",
            program_code="c6001",
            handbook_year=2026,
        )

        self.assertEqual(institution.level, CoverageLevel.STRUCTURED)
        self.assertEqual(program.level, CoverageLevel.VERIFIED)
        self.assertTrue(
            program.to_dict()["capabilities"]["deterministic_planning"]
        )

    def test_catalog_scope_supports_discovery_without_overstating_maturity(self) -> None:
        record = self.registry.resolve(
            university_id="unsw",
            program_code="8543",
            handbook_year=2026,
        )

        self.assertEqual(record.level, CoverageLevel.CATALOG)
        capabilities = record.to_dict()["capabilities"]
        self.assertTrue(capabilities["catalog_discovery"])
        self.assertFalse(capabilities["structured_lookup"])


if __name__ == "__main__":
    unittest.main()
