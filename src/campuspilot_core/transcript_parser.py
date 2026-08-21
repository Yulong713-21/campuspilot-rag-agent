from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import re
from typing import Any, Protocol


MAX_TRANSCRIPT_BYTES = 10 * 1024 * 1024


class TranscriptParser(Protocol):
    provider_name: str

    def parse(self, content: bytes) -> dict[str, Any]: ...


class TranscriptValidationError(ValueError):
    pass


class LocalPdfTextParser:
    provider_name = "local_pdf"

    SUPPORTING_DOCUMENT_MARKERS = (
        "成绩单说明",
        "成绩单格式导出操作指南",
        "成绩表（中文成绩单格式）打印操作指南",
        "打印操作指南",
        "导出操作指南",
        "transcript explanation",
        "transcript export guide",
    )

    @classmethod
    def _is_supporting_document(cls, text: str) -> bool:
        normalized = " ".join(text.lower().split())
        return any(marker.lower() in normalized for marker in cls.SUPPORTING_DOCUMENT_MARKERS)

    @staticmethod
    def _extract_candidate_profile(text: str) -> dict[str, Any]:
        institution_match = re.search(
            r"(?:学校|院校)\s*[:：]?\s*([^\n]+?(?:大学|学院))",
            text,
        )
        overall_match = re.search(
            r"(?:加权平均分|平均成绩|WAM)[:：]?\s*(\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        gpa_match = re.search(
            r"(?:平均学分绩点|GPA)[:：]?\s*(\d+(?:\.\d+)?)\s*/?\s*(4\.0|5\.0)?",
            text,
            re.IGNORECASE,
        )
        credits_match = re.search(
            r"(?:已获学分|已修学分|Completed Credits)[:：]?\s*(\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        course_pattern = re.compile(
            r"^([A-Z]{2,6}\d{3,4})\s+(.+?)\s+(\d+(?:\.\d+)?)\s+"
            r"(\d+(?:\.\d+)?)\s+([A-F][+-]?|P|F)$",
            re.IGNORECASE,
        )
        courses = []
        for line in text.splitlines():
            match = course_pattern.match(" ".join(line.split()))
            if not match:
                continue
            courses.append(
                {
                    "course_code": match.group(1).upper(),
                    "course_name": match.group(2),
                    "credits": float(match.group(3)),
                    "score": float(match.group(4)),
                    "grade": match.group(5).upper(),
                }
            )
        if not courses:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            try:
                course_start = lines.index("课程代码") + 5
            except ValueError:
                course_start = len(lines)
            index = course_start
            while index + 4 < len(lines):
                code, name, credits, score, grade = lines[index : index + 5]
                if not re.fullmatch(r"[A-Z]{2,6}\d{3,4}", code, re.IGNORECASE):
                    break
                if not re.fullmatch(r"\d+(?:\.\d+)?", credits):
                    break
                if not re.fullmatch(r"\d+(?:\.\d+)?", score):
                    break
                if not re.fullmatch(r"[A-F][+-]?|P|F", grade, re.IGNORECASE):
                    break
                courses.append(
                    {
                        "course_code": code.upper(),
                        "course_name": name,
                        "credits": float(credits),
                        "score": float(score),
                        "grade": grade.upper(),
                    }
                )
                index += 5
        if overall_match:
            overall_score = float(overall_match.group(1))
            score_scale = 100.0
        elif gpa_match:
            overall_score = float(gpa_match.group(1))
            score_scale = float(gpa_match.group(2) or 4.0)
        else:
            overall_score = None
            score_scale = None
        return {
            "institution": (
                institution_match.group(1).strip() if institution_match else None
            ),
            "overall_score": overall_score,
            "score_scale": score_scale,
            "gpa": float(gpa_match.group(1)) if gpa_match else None,
            "gpa_scale": float(gpa_match.group(2) or 4.0) if gpa_match else None,
            "completed_credits": (
                float(credits_match.group(1)) if credits_match else None
            ),
            "courses": courses,
        }

    def parse(self, content: bytes) -> dict[str, Any]:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content))
        page_text = [(page.extract_text() or "").strip() for page in reader.pages]
        text = "\n".join(item for item in page_text if item)
        if not text:
            return {
                "status": "TRANSCRIPT_IMAGE_OCR_REQUIRED",
                "message": "PDF 没有可提取文本，可能是扫描件，需要 OCR 或多模态模型解析。",
                "page_count": len(reader.pages),
                "text_preview": "",
                "next_action": "select_ocr_or_multimodal_parser",
            }
        if self._is_supporting_document(text):
            return {
                "status": "TRANSCRIPT_DOCUMENT_NOT_RECOGNIZED",
                "message": (
                    "PDF 文本可以读取，但内容更像成绩单说明或操作指南，"
                    "不能作为申请评估所需的个人成绩单。"
                ),
                "page_count": len(reader.pages),
                "extracted_character_count": len(text),
                "text_preview": text[:2000],
                "document_type": "transcript_supporting_document",
                "next_action": "upload_actual_transcript",
            }
        candidate_profile = self._extract_candidate_profile(text)
        extracted_field_count = sum(
            value not in {None, ""}
            for key, value in candidate_profile.items()
            if key != "courses"
        ) + len(candidate_profile["courses"])
        return {
            "status": (
                "TRANSCRIPT_FIELDS_EXTRACTED"
                if candidate_profile["courses"]
                else "TRANSCRIPT_TEXT_EXTRACTED"
            ),
            "message": (
                "已提取成绩单候选字段，请核对学校、课程、学分和成绩后再用于评估。"
                if candidate_profile["courses"]
                else "已提取成绩单文本，但尚未识别出课程明细，请人工确认。"
            ),
            "page_count": len(reader.pages),
            "extracted_character_count": len(text),
            "extracted_field_count": extracted_field_count,
            "text_preview": text[:2000],
            "document_type": "transcript_candidate",
            "candidate_profile": candidate_profile,
            "next_action": "confirm_transcript_fields",
        }


@dataclass
class TranscriptParseService:
    parsers: dict[str, TranscriptParser] | None = None

    def __post_init__(self) -> None:
        if self.parsers is None:
            local_parser = LocalPdfTextParser()
            self.parsers = {local_parser.provider_name: local_parser}

    def parse(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        provider: str,
    ) -> dict[str, Any]:
        if not filename.lower().endswith(".pdf"):
            raise TranscriptValidationError("only PDF transcripts are accepted")
        if content_type not in {None, "", "application/pdf"}:
            raise TranscriptValidationError("content type must be application/pdf")
        if not content or not content.startswith(b"%PDF-"):
            raise TranscriptValidationError("file content is not a valid PDF")
        if len(content) > MAX_TRANSCRIPT_BYTES:
            raise TranscriptValidationError("PDF transcript exceeds 10 MB")
        parser = (self.parsers or {}).get(provider)
        if parser is None:
            return self._result(
                status="TRANSCRIPT_PARSER_NOT_CONFIGURED",
                message=f"解析器 {provider} 尚未配置。",
                parser_provider=provider,
                next_action="configure_transcript_parser",
                file_sha256=hashlib.sha256(content).hexdigest(),
            )
        parsed = parser.parse(content)
        return self._result(
            **parsed,
            parser_provider=provider,
            file_sha256=hashlib.sha256(content).hexdigest(),
        )

    @staticmethod
    def _result(**data: Any) -> dict[str, Any]:
        status = data["status"]
        candidate_profile = data.pop(
            "candidate_profile",
            {
                "institution": None,
                "overall_score": None,
                "score_scale": None,
                "completed_credits": None,
                "courses": [],
            },
        )
        return {
            "error_code": status,
            "requires_user_confirmation": True,
            "hard_decision_allowed": False,
            "candidate_profile": candidate_profile,
            "trace_tools": ["validate_transcript", "parse_transcript"],
            **data,
        }
