from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from bs4 import BeautifulSoup


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


class MonashUnitGuideParser:
    """Parse versioned Monash unit facts from the page's Next.js payload."""

    def parse(
        self,
        content: bytes,
        *,
        source_url: str,
        source_sha256: str | None = None,
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        soup = BeautifulSoup(content, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            raise ValueError("Monash page has no __NEXT_DATA__ payload")
        payload = json.loads(script.string)
        page = payload["props"]["pageProps"]["pageContent"]
        course_code = str(page.get("code") or page.get("unit_code") or "")
        if not re.fullmatch(r"[A-Z]{2,5}\d{4}", course_code):
            raise ValueError("Monash page has no valid unit code")

        assessments = [
            self._assessment(item)
            for item in page.get("assessments") or []
        ]
        assessments.sort(key=lambda item: item["number"])
        summary = _plain_text(page.get("handbook_assessment_summary"))
        attendance_note = _plain_text(page.get("attendance_requirements"))
        attendance_status = self._attendance_status(attendance_note)
        exam_weight = sum(
            item["weight_percent"]
            for item in assessments
            if item["type"] == "examination"
        )
        final_exam = any(
            item["type"] == "examination"
            and "final" in item["name"].lower()
            for item in assessments
        )
        has_hurdle = any(item["hurdle"] for item in assessments)
        tags = self._assessment_tags(
            assessments,
            exam_weight=exam_weight,
            has_hurdle=has_hurdle,
        )
        return {
            "course_code": course_code,
            "course_name": page.get("title") or page.get("search_title"),
            "handbook_year": int(
                str(page.get("implementation_year") or source_url.split("/")[3])
                .split(".")[0]
            ),
            "attendance_status": attendance_status,
            "attendance_note": (
                attendance_note
                or (
                    "官方 Handbook 未声明出勤计分或出勤门槛，"
                    "请以开课学期 Unit Guide/Moodle 为准。"
                )
            ),
            "assessment_summary": summary,
            "assessments": assessments,
            "assessment_tags": tags,
            "exam_weight_percent": exam_weight,
            "final_exam": final_exam,
            "hurdle_status": "YES" if has_hurdle else "NO",
            "source_url": source_url,
            "source_sha256": (
                source_sha256 or hashlib.sha256(content).hexdigest()
            ),
            "captured_at": (
                captured_at or datetime.now(timezone.utc).isoformat()
            ),
        }

    @staticmethod
    def _assessment(item: dict[str, Any]) -> dict[str, Any]:
        number_text = str(item.get("number") or "0")
        return {
            "number": int(number_text) if number_text.isdigit() else 0,
            "name": str(item.get("name") or item.get("assessment_name") or ""),
            "type": str(
                (item.get("assessment_type") or {}).get("value") or "other"
            ),
            "type_label": str(
                (item.get("assessment_type") or {}).get("label") or "Other"
            ),
            "weight_percent": int(item.get("weight") or 0),
            "hurdle": bool(item.get("hurdle_type")),
            "hurdle_type": (
                (item.get("hurdle_type") or {}).get("value")
            ),
            "hurdle_note": _plain_text(
                item.get("hurdle_supplementary_assessment")
            ),
        }

    @staticmethod
    def _attendance_status(note: str | None) -> str:
        normalized = (note or "").lower()
        if any(term in normalized for term in ("hurdle", "must attend")):
            return "HURDLE"
        if any(term in normalized for term in ("mark", "assess")):
            return "ASSESSED"
        if any(term in normalized for term in ("required", "compulsory")):
            return "REQUIRED"
        if any(term in normalized for term in ("not required", "optional")):
            return "NOT_REQUIRED"
        return "UNKNOWN"

    @staticmethod
    def _assessment_tags(
        assessments: list[dict[str, Any]],
        *,
        exam_weight: int,
        has_hurdle: bool,
    ) -> list[str]:
        tags: list[str] = []
        if has_hurdle:
            tags.append("考核门槛")
        if exam_weight:
            tags.append(f"考试合计 {exam_weight}%")
        else:
            type_labels = {
                "presentation": "Presentation",
                "project": "项目考核",
                "portfolio": "作品集",
                "written": "作业考核",
            }
            for assessment in assessments:
                label = type_labels.get(assessment["type"])
                if label and label not in tags:
                    tags.append(label)
                if len(tags) == 2:
                    break
        return tags[:2] or ["考核待核实"]

