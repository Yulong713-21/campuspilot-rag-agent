from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.coverage_report import build_coverage_report


class CoverageReportTest(unittest.TestCase):
    def test_current_assets_pass_structural_quality_gates(self) -> None:
        report = build_coverage_report(REPO_ROOT)

        handbook = report["handbook"]
        self.assertEqual(
            handbook["manifest_sources"],
            sum(handbook["sources_by_owner"].values()),
        )
        self.assertEqual(
            handbook["child_chunks"],
            sum(handbook["chunks_by_owner"].values()),
        )
        self.assertTrue(report["quality_gate"]["chunk_json_valid"])
        self.assertGreater(handbook["parent_chunks"], 0)
        self.assertGreater(report["admissions"]["vector_documents"], 0)

    def test_report_keeps_verified_rules_separate_from_extracted_docs(self) -> None:
        report = build_coverage_report(REPO_ROOT)

        admissions = report["admissions"]
        self.assertLess(
            admissions["reviewed_programs"],
            admissions["vector_documents"],
        )
        self.assertTrue(
            report["quality_gate"]["hard_decision_scope_limited"]
        )


if __name__ == "__main__":
    unittest.main()
