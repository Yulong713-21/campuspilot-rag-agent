from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.admission_criteria import (  # noqa: E402
    extract_directory,
    extract_monash_criteria,
    sync_catalog,
    write_vector_documents,
)
from campuspilot_core.db import Base  # noqa: E402
from campuspilot_core.models import (  # noqa: E402
    AdmissionCriterion,
    AdmissionEvidence,
    AdmissionRule,
    Program,
    ProgramCatalogProfile,
)


SOURCE_ROOT = REPO_ROOT / "data/official_sources/clean/monash/2026"


class AdmissionCriteriaTest(unittest.TestCase):
    def test_it_pathways_map_internal_levels_to_user_facing_duration(self) -> None:
        records = extract_monash_criteria(SOURCE_ROOT / "monash-c6001-2026.md")

        self.assertEqual(
            [item.pathway_code for item in records],
            [
                "ENTRY_LEVEL_1",
                "ENTRY_LEVEL_2",
            ],
        )
        self.assertEqual(
            [item.display_name for item in records],
            [
                "2年制项目",
                "1.5年制项目",
            ],
        )
        self.assertEqual([item.credits_to_complete for item in records], [96, 72])
        self.assertEqual(records[1].requirements["cognate_background_required"], True)

    def test_business_analytics_keeps_supplementary_evidence(self) -> None:
        records = extract_monash_criteria(SOURCE_ROOT / "monash-b6022-2026.md")

        self.assertEqual(records[0].minimum_average_percent, 65.0)
        self.assertIn(
            "Candidate Statement",
            records[1].requirements["supplementary_evidence"],
        )
        self.assertIn("statistics", records[1].requirements["subject_keywords"])

    def test_degree_text_does_not_create_false_gre_evidence(self) -> None:
        records = extract_monash_criteria(SOURCE_ROOT / "monash-b6004-2026.md")

        for record in records:
            self.assertNotIn(
                "GRE",
                record.requirements["supplementary_evidence"],
            )

    def test_only_manually_reviewed_program_can_drive_hard_decision(self) -> None:
        reviewed = extract_monash_criteria(SOURCE_ROOT / "monash-c6001-2026.md")
        pending = extract_monash_criteria(SOURCE_ROOT / "monash-b6004-2026.md")

        self.assertTrue(all(item.hard_decision_allowed for item in reviewed))
        self.assertTrue(all(item.review_status == "VERIFIED" for item in reviewed))
        self.assertFalse(any(item.hard_decision_allowed for item in pending))
        self.assertTrue(
            all(item.review_status == "REVIEW_REQUIRED" for item in pending)
        )

    def test_non_entry_level_format_still_becomes_a_standard_pathway(self) -> None:
        records = extract_monash_criteria(SOURCE_ROOT / "monash-e6006-2026.md")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].pathway_code, "STANDARD")
        self.assertIsNotNone(records[0].duration_months)
        self.assertIsNotNone(records[0].credits_to_complete)

    def test_all_monash_2026_programs_generate_sql_and_vector_documents(self) -> None:
        records = extract_directory(SOURCE_ROOT)
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with tempfile.TemporaryDirectory() as directory, Session(engine) as session:
            synced = sync_catalog(session, records)
            documents = write_vector_documents(records, directory)
            program_count = session.scalar(select(func.count()).select_from(Program))
            criterion_count = session.scalar(
                select(func.count()).select_from(AdmissionCriterion)
            )
            rule_count = session.scalar(select(func.count()).select_from(AdmissionRule))
            evidence_count = session.scalar(
                select(func.count()).select_from(AdmissionEvidence)
            )
            hard_evidence_count = session.scalar(
                select(func.count())
                .select_from(AdmissionEvidence)
                .where(AdmissionEvidence.hard_decision_allowed.is_(True))
            )
            profile_count = session.scalar(
                select(func.count()).select_from(ProgramCatalogProfile)
            )

            self.assertEqual(len({item.program_code for item in records}), 39)
            self.assertGreater(synced, 39)
            self.assertEqual(criterion_count, synced)
            self.assertEqual(rule_count, synced)
            self.assertEqual(evidence_count, synced)
            self.assertEqual(hard_evidence_count, 2)
            self.assertEqual(profile_count, 39)
            self.assertEqual(program_count, 39)
            self.assertEqual(len(documents), 39)
            self.assertIn("录取与学制要求", documents[0].read_text(encoding="utf-8"))
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
