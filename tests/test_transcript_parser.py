from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.api import create_app  # noqa: E402
from campuspilot_core.transcript_parser import (  # noqa: E402
    LocalPdfTextParser,
    TranscriptParseService,
    TranscriptValidationError,
)


def blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(output)
    return output.getvalue()


class TranscriptParseServiceTest(unittest.TestCase):
    def test_transcript_guide_is_not_accepted_as_a_transcript(self) -> None:
        self.assertTrue(
            LocalPdfTextParser._is_supporting_document(
                "学业成绩表（中文成绩单格式）打印操作指南"
            )
        )

    def test_transcript_explanation_is_not_accepted_as_a_transcript(self) -> None:
        self.assertTrue(
            LocalPdfTextParser._is_supporting_document(
                "华东师范大学本科生成绩单说明\nAcademic Transcript Explanation"
            )
        )

    def test_regular_transcript_text_is_not_mistaken_for_a_guide(self) -> None:
        self.assertFalse(
            LocalPdfTextParser._is_supporting_document(
                "姓名 张三 学号 20260001 课程名称 数据结构 学分 3 成绩 88"
            )
        )

    def test_extracts_structured_fields_from_mock_percentage_transcript(self) -> None:
        profile = LocalPdfTextParser._extract_candidate_profile(
            """学校：华东示范大学
加权平均分：82.35
平均学分绩点：3.45 / 4.0
已获学分：60
CS101 数据结构 3 88 A
MA102 高等数学 4 79 B+
"""
        )

        self.assertEqual(profile["institution"], "华东示范大学")
        self.assertEqual(profile["overall_score"], 82.35)
        self.assertEqual(profile["score_scale"], 100.0)
        self.assertEqual(profile["completed_credits"], 60.0)
        self.assertEqual(len(profile["courses"]), 2)
        self.assertEqual(profile["courses"][0]["course_code"], "CS101")

    def test_uses_gpa_when_percentage_score_is_absent(self) -> None:
        profile = LocalPdfTextParser._extract_candidate_profile(
            """院校：南方示范学院
GPA：3.62 / 4.0
Completed Credits: 72
BUS201 Financial Accounting 3 86 A-
"""
        )

        self.assertEqual(profile["overall_score"], 3.62)
        self.assertEqual(profile["score_scale"], 4.0)
        self.assertEqual(profile["completed_credits"], 72.0)

    def test_extracts_pdf_table_when_each_cell_is_on_its_own_line(self) -> None:
        profile = LocalPdfTextParser._extract_candidate_profile(
            """学校
华东示范大学
课程代码
课程名称
学分
成绩
等级
CS101
程序设计基础
3
88
A
CS201
数据结构
3
86
A
已获学分：6
"""
        )

        self.assertEqual(profile["institution"], "华东示范大学")
        self.assertEqual(len(profile["courses"]), 2)
        self.assertEqual(profile["courses"][1]["course_name"], "数据结构")

    def test_scanned_or_blank_pdf_requests_ocr(self) -> None:
        result = TranscriptParseService().parse(
            filename="transcript.pdf",
            content_type="application/pdf",
            content=blank_pdf(),
            provider="local_pdf",
        )

        self.assertEqual(result["status"], "TRANSCRIPT_IMAGE_OCR_REQUIRED")
        self.assertTrue(result["requires_user_confirmation"])
        self.assertFalse(result["hard_decision_allowed"])

    def test_multimodal_provider_is_replaceable_but_not_fake_enabled(self) -> None:
        result = TranscriptParseService().parse(
            filename="transcript.pdf",
            content_type="application/pdf",
            content=blank_pdf(),
            provider="multimodal_llm",
        )

        self.assertEqual(result["status"], "TRANSCRIPT_PARSER_NOT_CONFIGURED")

    def test_non_pdf_is_rejected(self) -> None:
        with self.assertRaises(TranscriptValidationError):
            TranscriptParseService().parse(
                filename="transcript.txt",
                content_type="text/plain",
                content=b"not a pdf",
                provider="local_pdf",
            )


class TranscriptParseApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.client = TestClient(
            create_app(
                database_path=Path(self.temp_dir.name) / "approval.sqlite3",
                token_to_user={},
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_pdf_upload_returns_review_required_contract(self) -> None:
        response = self.client.post(
            "/api/admissions/transcripts/parse",
            files={"file": ("transcript.pdf", blank_pdf(), "application/pdf")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["requires_user_confirmation"])
        self.assertFalse(payload["hard_decision_allowed"])

    def test_oversized_pdf_is_rejected_before_parser(self) -> None:
        with patch.dict(
            "os.environ",
            {"CAMPUSPILOT_MAX_UPLOAD_BYTES": "8"},
        ):
            with TestClient(
                create_app(
                    database_path=Path(self.temp_dir.name) / "small-upload.sqlite3",
                    token_to_user={},
                )
            ) as client:
                response = client.post(
                    "/api/admissions/transcripts/parse",
                    files={
                        "file": (
                            "transcript.pdf",
                            b"%PDF-1234",
                            "application/pdf",
                        )
                    },
                )

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
