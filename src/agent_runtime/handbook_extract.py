from __future__ import annotations

from dataclasses import asdict, dataclass
from email import policy
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

from bs4 import BeautifulSoup, Tag


@dataclass(frozen=True)
class ExtractionResult:
    source_id: str
    status: str
    input_path: str
    output_path: str | None
    text_sha256: str | None
    character_count: int
    error: str | None = None


class HandbookExtractor:
    """Converts verified source snapshots into reviewable Markdown."""

    def extract_path(self, path: str | Path) -> str:
        source_path = Path(path)
        suffix = source_path.suffix.lower()
        if suffix in {".html", ".htm"}:
            return self.extract_html(source_path.read_bytes())
        if suffix in {".mhtml", ".mht"}:
            return self.extract_mhtml(source_path.read_bytes())
        if suffix in {".txt", ".md"}:
            return self._normalise_lines(
                source_path.read_text(encoding="utf-8").splitlines()
            )
        if suffix == ".docx":
            return self.extract_docx(source_path)
        raise ValueError(f"unsupported source format: {suffix}")

    @staticmethod
    def _normalise_lines(lines: list[str]) -> str:
        result: list[str] = []
        previous = ""
        for raw_line in lines:
            line = re.sub(r"[ \t]+", " ", raw_line).strip()
            if not line or line == previous:
                continue
            result.append(line)
            previous = line
        return "\n\n".join(result)

    def extract_html(self, content: bytes | str) -> str:
        soup = BeautifulSoup(content, "html.parser")
        monash_text = self._extract_monash_next_data(soup)
        if monash_text:
            return monash_text
        for tag in soup.select(
            "script, style, noscript, svg, nav, header, footer, form, button"
        ):
            tag.decompose()
        root = (
            soup.find("main")
            or soup.find("article")
            or soup.find(attrs={"role": "main"})
            or soup.body
            or soup
        )
        lines: list[str] = []
        for element in root.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "dt", "dd"]
        ):
            if not isinstance(element, Tag):
                continue
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            if element.name and element.name.startswith("h"):
                level = int(element.name[1])
                lines.append(f"{'#' * level} {text}")
            elif element.name == "li":
                lines.append(f"- {text}")
            elif element.name == "tr":
                cells = [
                    cell.get_text(" ", strip=True)
                    for cell in element.find_all(["th", "td"], recursive=False)
                ]
                lines.append(" | ".join(cell for cell in cells if cell))
            else:
                lines.append(text)
        if not lines:
            lines = root.get_text("\n", strip=True).splitlines()
        return self._normalise_lines(lines)

    def _extract_monash_next_data(
        self,
        soup: BeautifulSoup,
    ) -> str | None:
        node = soup.find("script", id="__NEXT_DATA__")
        if not isinstance(node, Tag):
            return None
        raw_payload = node.string or node.get_text()
        if not raw_payload:
            return None
        try:
            payload = json.loads(raw_payload)
            page_content = payload["props"]["pageProps"]["pageContent"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
        if not isinstance(page_content, dict):
            return None
        code = str(
            page_content.get("code")
            or page_content.get("course_code")
            or ""
        ).strip()
        title = str(
            page_content.get("title")
            or page_content.get("search_title")
            or ""
        ).strip()
        if not code or not title:
            return None

        lines = [f"# {code} - {title}", "", "## Handbook facts"]
        facts = [
            ("Handbook year", page_content.get("implementation_year")),
            ("Academic item type", page_content.get("contentTypeLabel")),
            ("Course type", self._label_value(page_content.get("type_ref"))),
            ("Credit points", page_content.get("credit_points")),
            ("Faculty", self._label_value(page_content.get("school"))),
            (
                "Full-time duration",
                self._duration_summary(
                    page_content.get("full_time_duration")
                ),
            ),
            (
                "Part-time duration",
                self._duration_summary(
                    page_content.get("part_time_duration")
                ),
            ),
            (
                "Study modes and locations",
                self._mode_summary(page_content.get("modes")),
            ),
            (
                "International students",
                page_content.get("international_students"),
            ),
            ("CRICOS code", page_content.get("cricos_code")),
            ("Academic level", self._label_value(page_content.get("level"))),
            (
                "Academic organisation",
                self._label_value(page_content.get("academic_org")),
            ),
            (
                "Work integrated learning",
                self._simple_list_values(
                    page_content.get("work_integrated_learning")
                ),
            ),
        ]
        for label, value in facts:
            if value not in (None, "", [], {}):
                lines.append(f"- {label}: {value}")

        sections = (
            ("Overview", "overview"),
            ("Synopsis", "handbook_synopsis"),
            ("Course duration notes", "course_duration_notes"),
            ("International availability", "international_availability_clarification"),
            ("Course offering notes", "course_offering_notes"),
            ("Special notes", "Special_notes_to_students"),
            ("Structure", "structure"),
            ("Requirements", "requirements"),
            ("Minimum entry requirements", "minimum_entry_requirements"),
            ("English language requirements", "english_language"),
            ("Expected workload", "workload_requirements"),
            ("Learning outcomes", "outcomes"),
            ("Professional recognition", "professional_recognition"),
            ("Alternative exits", "alternative_exits"),
            (
                "Progression to further studies",
                "progression_to_further_studies",
            ),
        )
        for heading, key in sections:
            text = self._fragment_text(page_content.get(key))
            if text:
                lines.extend(("", f"## {heading}", "", text))

        if not self._fragment_text(page_content.get("outcomes")):
            outcomes = []
            raw_outcomes = (
                page_content.get("learning_outcomes")
                or page_content.get("unit_learning_outcomes")
                or []
            )
            for outcome in raw_outcomes:
                description = self._fragment_text(
                    outcome.get("description")
                    if isinstance(outcome, dict)
                    else None
                )
                if description:
                    outcomes.append(description)
            if outcomes:
                lines.extend(
                    ("", "## Learning outcomes", "", "\n\n".join(outcomes))
                )

        requisites = self._requisite_summary(
            page_content.get("requisites")
        )
        if requisites:
            lines.extend(("", "## Requisites", "", requisites))
        assessments = self._assessment_summary(
            page_content.get("assessments")
        )
        if assessments:
            lines.extend(("", "## Assessments", "", assessments))
        offerings = self._offering_summary(
            page_content.get("unit_offering")
        )
        if offerings:
            lines.extend(("", "## Offerings", "", offerings))
        activities = self._activity_summary(
            page_content.get("learning_activities_grouped")
        )
        if activities:
            lines.extend(("", "## Learning activities", "", activities))
        return self._normalise_lines(lines)

    @staticmethod
    def _label_value(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("value") or value.get("label") or "").strip()
        return str(value or "").strip()

    @staticmethod
    def _duration_summary(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        return ", ".join(
            str(item.get("duration_display") or "").strip()
            for item in value
            if isinstance(item, dict) and item.get("duration_display")
        )

    @staticmethod
    def _mode_summary(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        summaries: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            mode = str(item.get("mode") or "").strip()
            locations = ", ".join(
                str(location).strip()
                for location in item.get("locations") or []
                if location
            )
            summary = " - ".join(part for part in (mode, locations) if part)
            if summary:
                summaries.append(summary)
        return "; ".join(summaries)

    @staticmethod
    def _simple_list_values(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        return ", ".join(
            HandbookExtractor._label_value(item)
            for item in value
            if HandbookExtractor._label_value(item)
        )

    @staticmethod
    def _requisite_summary(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        lines: list[str] = []
        for requisite in value:
            if not isinstance(requisite, dict):
                continue
            requisite_type = HandbookExtractor._label_value(
                requisite.get("requisite_type")
            )
            codes = sorted(
                {
                    str(relationship.get("academic_item_code")).strip()
                    for container in requisite.get("container") or []
                    if isinstance(container, dict)
                    for relationship in container.get("relationships") or []
                    if isinstance(relationship, dict)
                    and relationship.get("academic_item_code")
                }
            )
            description = HandbookExtractor._fragment_text(
                requisite.get("description")
            )
            detail = ", ".join(codes) or description or "See official rule"
            lines.append(f"- {requisite_type or 'Requisite'}: {detail}")
        return "\n".join(lines)

    @staticmethod
    def _assessment_summary(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        lines: list[str] = []
        for assessment in value:
            if not isinstance(assessment, dict):
                continue
            name = str(
                assessment.get("assessment_name")
                or assessment.get("name")
                or "Assessment"
            ).strip()
            weight = str(assessment.get("weight") or "").strip()
            hurdle = HandbookExtractor._label_value(
                assessment.get("hurdle_type")
            )
            details = [name]
            if weight:
                details.append(f"{weight}%")
            if hurdle:
                details.append(f"Hurdle: {hurdle}")
            lines.append("- " + " | ".join(details))
        return "\n".join(lines)

    @staticmethod
    def _offering_summary(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        lines: list[str] = []
        for offering in value:
            if not isinstance(offering, dict):
                continue
            period = HandbookExtractor._label_value(
                offering.get("teaching_period")
            )
            location = HandbookExtractor._label_value(
                offering.get("location")
            )
            mode = HandbookExtractor._label_value(
                offering.get("attendance_mode")
            )
            detail = " | ".join(
                part for part in (period, location, mode) if part
            )
            if detail:
                lines.append(f"- {detail}")
        return "\n".join(dict.fromkeys(lines))

    @staticmethod
    def _activity_summary(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        lines: list[str] = []
        for group in value:
            if not isinstance(group, dict):
                continue
            activity_type = str(
                group.get("activity_type") or "Learning activity"
            ).strip()
            durations = [
                str(activity.get("duration_display")).strip()
                for activity in group.get("activities") or []
                if isinstance(activity, dict)
                and activity.get("duration_display")
            ]
            detail = ", ".join(durations)
            lines.append(
                f"- {activity_type}: {detail}"
                if detail
                else f"- {activity_type}"
            )
        return "\n".join(lines)

    @staticmethod
    def _fragment_text(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get("value") or value.get("label")
        if not isinstance(value, str) or not value.strip():
            return ""
        fragment = BeautifulSoup(value, "html.parser")
        lines: list[str] = []
        for element in fragment.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]
        ):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            if element.name == "li":
                lines.append(f"- {text}")
            else:
                lines.append(text)
        if not lines:
            lines = fragment.get_text("\n", strip=True).splitlines()
        return HandbookExtractor._normalise_lines(lines)

    def extract_mhtml(self, content: bytes) -> str:
        message = BytesParser(policy=policy.default).parsebytes(content)
        candidates: list[str] = []
        for part in message.walk():
            if part.get_content_type() != "text/html":
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                body = part.get_content()
                candidates.append(self.extract_html(body))
            else:
                charset = part.get_content_charset() or "utf-8"
                candidates.append(
                    self.extract_html(
                        payload.decode(charset, errors="replace")
                    )
                )
        if not candidates:
            raise ValueError("MHTML snapshot contains no text/html part")
        return max(candidates, key=len)

    def extract_docx(self, path: str | Path) -> str:
        with ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(document_xml)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        lines = [
            "".join(
                node.text or ""
                for node in paragraph.iter(f"{namespace}t")
            )
            for paragraph in root.iter(f"{namespace}p")
        ]
        return self._normalise_lines(lines)

    def extract_manifest(
        self,
        *,
        manifest: dict[str, Any],
        source_index: dict[str, Any],
        output_directory: str | Path,
        minimum_characters: int = 300,
    ) -> dict[str, Any]:
        output_root = Path(output_directory)
        source_records = source_index.get("sources", {})
        results: list[ExtractionResult] = []

        for source in manifest.get("sources", []):
            source_id = source["source_id"]
            record = source_records.get(source_id)
            if not record:
                results.append(
                    ExtractionResult(
                        source_id=source_id,
                        status="missing_snapshot",
                        input_path="",
                        output_path=None,
                        text_sha256=None,
                        character_count=0,
                        error="source is not present in the snapshot index",
                    )
                )
                continue
            if not record.get("local_path"):
                unavailable = record.get("http_status") == 404
                results.append(
                    ExtractionResult(
                        source_id=source_id,
                        status=(
                            "unavailable" if unavailable else "missing_snapshot"
                        ),
                        input_path="",
                        output_path=None,
                        text_sha256=None,
                        character_count=0,
                        error=(
                            "official source returned HTTP 404"
                            if unavailable
                            else "snapshot index has no local file"
                        ),
                    )
                )
                continue
            input_path = Path(record["local_path"])
            try:
                text = self.extract_path(input_path)
                missing_markers = [
                    marker
                    for marker in source.get("expected_content_markers", [])
                    if marker.lower() not in text.lower()
                ]
                status = (
                    "discovery_only"
                    if source.get("source_type") == "catalog_root"
                    else "low_text"
                    if len(text) < minimum_characters
                    else "marker_missing"
                    if missing_markers
                    else "ready"
                )
                year = str(source.get("handbook_year") or "cross-year")
                target = (
                    output_root
                    / source.get("university_id", "policy")
                    / year
                    / f"{source_id}.md"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                metadata = {
                    "source_id": source_id,
                    "university_id": source.get("university_id"),
                    "handbook_year": source.get("handbook_year"),
                    "program_code": source.get("program_code"),
                    "source_type": source.get("source_type"),
                    "source_url": source.get("url"),
                    "source_sha256": record.get("content_sha256"),
                    "capture_method": record.get("capture_method", "http"),
                }
                frontmatter = "\n".join(
                    f"{key}: {json.dumps(value, ensure_ascii=False)}"
                    for key, value in metadata.items()
                )
                target.write_text(
                    f"---\n{frontmatter}\n---\n\n"
                    f"# {source.get('title', source_id)}\n\n{text}\n",
                    encoding="utf-8",
                )
                digest = hashlib.sha256(
                    text.encode("utf-8")
                ).hexdigest()
                error = (
                    "missing expected markers: " + ", ".join(missing_markers)
                    if missing_markers
                    else None
                )
                results.append(
                    ExtractionResult(
                        source_id=source_id,
                        status=status,
                        input_path=str(input_path),
                        output_path=str(target.resolve()),
                        text_sha256=digest,
                        character_count=len(text),
                        error=error,
                    )
                )
            except (OSError, KeyError, ValueError) as exc:
                results.append(
                    ExtractionResult(
                        source_id=source_id,
                        status="error",
                        input_path=str(input_path),
                        output_path=None,
                        text_sha256=None,
                        character_count=0,
                        error=str(exc),
                    )
                )

        summary: dict[str, int] = {}
        for result in results:
            summary[result.status] = summary.get(result.status, 0) + 1
        return {
            "manifest_version": manifest.get("manifest_version"),
            "summary": summary,
            "results": [asdict(result) for result in results],
            "next_action": "review_non_ready_documents_before_chunking",
        }
