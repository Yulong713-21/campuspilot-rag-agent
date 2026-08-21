from __future__ import annotations

import sys
from pathlib import Path
import unittest

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.monash_catalog import (
    MONASH_PROGRAM_SCOPE,
    build_monash_program_sources,
    build_monash_unit_sources,
    coverage_summary,
    fetch_monash_course_catalog,
    merge_monash_program_sources,
    merge_monash_unit_sources,
)


class MonashCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            {
                "code": code,
                "title": f"Master for {code}",
                "lines": ["Course", "Postgraduate"],
            }
            for codes in MONASH_PROGRAM_SCOPE.values()
            for code in codes
        ]

    def test_builds_three_years_for_each_scoped_program(self) -> None:
        sources = build_monash_program_sources(self.items)

        expected_programs = sum(
            len(codes) for codes in MONASH_PROGRAM_SCOPE.values()
        )
        self.assertEqual(len(sources), expected_programs * 3)
        self.assertEqual(
            {
                source["handbook_year"]
                for source in sources
                if source["program_code"] == "C6001"
            },
            {2024, 2025, 2026},
        )
        self.assertTrue(
            all(
                source["source_type"] == "program_handbook"
                for source in sources
            )
        )

    def test_rejects_when_an_official_scope_code_is_missing(self) -> None:
        incomplete = [
            item for item in self.items if item["code"] != "C6001"
        ]

        with self.assertRaisesRegex(ValueError, "C6001"):
            build_monash_program_sources(incomplete)

    def test_ignores_non_course_and_unscoped_results(self) -> None:
        items = self.items + [
            {
                "code": "FIT9131",
                "title": "Programming foundations in Java",
                "lines": ["Unit", "Postgraduate"],
            },
            {
                "code": "A6001",
                "title": "Master outside target scope",
                "lines": ["Course", "Postgraduate"],
            },
        ]

        sources = build_monash_program_sources(items)

        self.assertNotIn(
            "FIT9131",
            {source["program_code"] for source in sources},
        )
        self.assertNotIn(
            "A6001",
            {source["program_code"] for source in sources},
        )

    def test_merge_preserves_other_sources_and_reports_coverage(self) -> None:
        manifest = {
            "manifest_version": "old",
            "scope": {"coverage": "old", "notice": "old"},
            "sources": [
                {
                    "source_id": "unsw-catalog-2026",
                    "university_id": "unsw",
                    "source_type": "catalog_root",
                }
            ],
        }
        generated = build_monash_program_sources(self.items)

        merged = merge_monash_program_sources(manifest, generated)
        summary = coverage_summary(merged["sources"])

        self.assertEqual(merged["sources"][0]["university_id"], "unsw")
        self.assertEqual(summary["programs"], 39)
        self.assertEqual(summary["program_versions"], 117)
        self.assertEqual(summary["by_discipline"]["computing"], 6)

    def test_catalog_fetch_falls_back_to_exact_code_search(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            query = request.url.params["query"]
            if query == "Master of":
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "results": [
                                {
                                    "code": "C6001",
                                    "title": "Master of IT",
                                    "lines": ["Course", "Postgraduate"],
                                }
                            ],
                            "total": 1,
                        }
                    },
                )
            self.assertEqual(query, "C6002")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "results": [
                            {
                                "code": "C6002",
                                "title": "Master of Cybersecurity",
                                "lines": ["Course", "Postgraduate"],
                            }
                        ],
                        "total": 1,
                    }
                },
            )

        results = fetch_monash_course_catalog(
            transport=httpx.MockTransport(handler),
            required_codes=["C6001", "C6002"],
        )

        self.assertEqual(
            {item["code"] for item in results},
            {"C6001", "C6002"},
        )

    def test_units_are_deduplicated_and_keep_program_relations(self) -> None:
        program_documents = [
            (
                {
                    "university_id": "monash",
                    "source_type": "program_handbook",
                    "handbook_year": 2026,
                    "program_code": "C6001",
                    "discipline_ids": ["computing"],
                },
                "Complete FIT9131 and FIT5122.",
            ),
            (
                {
                    "university_id": "monash",
                    "source_type": "program_handbook",
                    "handbook_year": 2026,
                    "program_code": "C6004",
                    "discipline_ids": ["computing"],
                },
                "Complete FIT9131 and MAT9004.",
            ),
        ]

        units = build_monash_unit_sources(program_documents)
        fit9131 = next(
            source
            for source in units
            if source["source_id"] == "monash-unit-fit9131-2026"
        )

        self.assertEqual(len(units), 3)
        self.assertEqual(
            fit9131["related_program_codes"],
            ["C6001", "C6004"],
        )
        self.assertEqual(fit9131["discipline_ids"], ["computing"])

    def test_unit_merge_replaces_previous_generated_units(self) -> None:
        manifest = {
            "manifest_version": "old",
            "scope": {},
            "sources": [
                {"source_id": "monash-unit-old1000-2026"},
                {"source_id": "monash-c6001-2026"},
            ],
        }
        generated = [
            {"source_id": "monash-unit-fit9131-2026"}
        ]

        merged = merge_monash_unit_sources(manifest, generated)

        self.assertEqual(
            [source["source_id"] for source in merged["sources"]],
            ["monash-c6001-2026", "monash-unit-fit9131-2026"],
        )


if __name__ == "__main__":
    unittest.main()
