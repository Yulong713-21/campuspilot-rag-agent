from __future__ import annotations

from email.message import EmailMessage
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_extract import HandbookExtractor


class HandbookExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = HandbookExtractor()

    def test_manifest_marks_official_404_as_unavailable(self) -> None:
        with TemporaryDirectory() as directory:
            report = self.extractor.extract_manifest(
                manifest={
                    "manifest_version": "test",
                    "sources": [{"source_id": "missing-unit"}],
                },
                source_index={
                    "sources": {
                        "missing-unit": {
                            "http_status": 404,
                            "error": "HTTP 404",
                        }
                    }
                },
                output_directory=directory,
            )

        self.assertEqual(report["summary"], {"unavailable": 1})
        self.assertEqual(report["results"][0]["output_path"], None)

    def test_extracts_main_html_and_removes_navigation_and_scripts(
        self,
    ) -> None:
        html = b"""
        <html><body>
          <nav>Unrelated navigation</nav>
          <main>
            <h1>Master of Computing</h1>
            <p>Complete 96 units.</p>
            <ul><li>Core course COMP9001</li></ul>
            <script>malicious_instruction()</script>
          </main>
        </body></html>
        """

        text = self.extractor.extract_html(html)

        self.assertIn("# Master of Computing", text)
        self.assertIn("Complete 96 units.", text)
        self.assertIn("- Core course COMP9001", text)
        self.assertNotIn("Unrelated navigation", text)
        self.assertNotIn("malicious_instruction", text)

    def test_extracts_html_part_from_mhtml_snapshot(self) -> None:
        message = EmailMessage()
        message.set_content("plain fallback")
        message.add_alternative(
            "<main><h1>2026 Handbook</h1><p>Program rules</p></main>",
            subtype="html",
        )

        text = self.extractor.extract_mhtml(message.as_bytes())

        self.assertIn("# 2026 Handbook", text)
        self.assertIn("Program rules", text)
        self.assertNotIn("plain fallback", text)

    def test_extracts_monash_course_from_next_data(self) -> None:
        page_content = {
            "code": "B6004",
            "title": "Master of Banking and Finance",
            "implementation_year": "2026",
            "contentTypeLabel": "Course",
            "type_ref": {"value": "Masters degree (Coursework)"},
            "credit_points": "96",
            "school": {"value": "Faculty of Business and Economics"},
            "full_time_duration": [
                {"duration_display": "2 Years"}
            ],
            "modes": [
                {"mode": "On campus", "locations": ["Caulfield"]}
            ],
            "international_students": "true",
            "cricos_code": "079580M",
            "overview": "<p>Banking and finance overview.</p>",
            "structure": "<p>Three-part course structure.</p>",
            "requirements": (
                "<p>Complete 96 credit points.</p>"
                "<ul><li>BFF5925 Financial management theory</li></ul>"
            ),
            "minimum_entry_requirements": (
                "<p>Entry level 1 requires a bachelor degree.</p>"
            ),
        }
        payload = {
            "props": {
                "pageProps": {
                    "pageContent": page_content,
                }
            }
        }
        html = (
            "<html><body><main><h1>client shell</h1></main>"
            '<script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(payload)}"
            "</script></body></html>"
        )

        text = self.extractor.extract_html(html)

        self.assertIn("# B6004 - Master of Banking and Finance", text)
        self.assertIn("- Credit points: 96", text)
        self.assertIn("- Study modes and locations: On campus - Caulfield", text)
        self.assertIn("## Requirements", text)
        self.assertIn("- BFF5925 Financial management theory", text)
        self.assertNotIn("client shell", text)

    def test_extracts_monash_unit_rules_and_assessments(self) -> None:
        page_content = {
            "code": "FIT9131",
            "title": "Programming foundations in Java",
            "implementation_year": "2026",
            "contentTypeLabel": "Unit",
            "credit_points": "6",
            "level": {"label": "Level 5"},
            "academic_org": {"value": "Faculty of IT"},
            "handbook_synopsis": "<p>Programming foundations.</p>",
            "workload_requirements": "<p>144 hours per semester.</p>",
            "work_integrated_learning": [{"value": "None"}],
            "unit_learning_outcomes": [
                {"description": "<p>Design Java programs.</p>"}
            ],
            "requisites": [
                {
                    "requisite_type": {"label": "Prerequisite"},
                    "container": [
                        {
                            "relationships": [
                                {"academic_item_code": "FIT9130"}
                            ]
                        }
                    ],
                }
            ],
            "assessments": [
                {
                    "assessment_name": "Final examination",
                    "weight": "40",
                    "hurdle_type": {"label": "Exam hurdle"},
                }
            ],
            "unit_offering": [
                {
                    "teaching_period": {"value": "First semester"},
                    "location": {"value": "Clayton"},
                    "attendance_mode": {"value": "On campus"},
                }
            ],
            "learning_activities_grouped": [
                {
                    "activity_type": "Laboratories",
                    "activities": [{"duration_display": "24 hours"}],
                }
            ],
        }
        payload = {"props": {"pageProps": {"pageContent": page_content}}}
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(payload)}"
            "</script>"
        )

        text = self.extractor.extract_html(html)

        self.assertIn("## Synopsis", text)
        self.assertIn("- Prerequisite: FIT9130", text)
        self.assertIn(
            "- Final examination | 40% | Hurdle: Exam hurdle",
            text,
        )
        self.assertIn("- First semester | Clayton | On campus", text)
        self.assertIn("- Laboratories: 24 hours", text)

    def test_extracts_docx_paragraphs_without_office_runtime(self) -> None:
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <w:document
          xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:body>
            <w:p><w:r><w:t>2024 and 2025 comparison</w:t></w:r></w:p>
            <w:p><w:r><w:t>Course code CITS5508</w:t></w:r></w:p>
          </w:body>
        </w:document>
        """
        with TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.docx"
            with ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)

            text = self.extractor.extract_docx(path)

        self.assertIn("2024 and 2025 comparison", text)
        self.assertIn("Course code CITS5508", text)


if __name__ == "__main__":
    unittest.main()
