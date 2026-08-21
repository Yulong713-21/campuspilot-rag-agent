from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AdmissionCriterion,
    AdmissionEvidence,
    AdmissionRule,
    Program,
    ProgramCatalogProfile,
    ProgramVersion,
    University,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_INDEX_PATH = REPO_ROOT / "data/official_sources/index.json"
REVIEW_MANIFEST_PATH = REPO_ROOT / "data/admissions/reviewed_rules.json"
ENTRY_SECTION = "## Minimum entry requirements"
ENTRY_PATH_RE = re.compile(
    r"(?ims)^Entry level\s*(?P<level>\d)\s*:\s*"
    r"(?P<body>.*?)(?=^Entry level\s*\d\s*:|\Z)"
)
FRONTMATTER_RE = re.compile(r'^([a-z_]+):\s*"?([^"\n]+)"?$', re.MULTILINE)


@dataclass(frozen=True)
class ExtractedAdmissionCriterion:
    university_code: str
    university_name: str
    program_code: str
    program_name: str
    faculty_name: str | None
    discipline_id: str
    handbook_year: int
    pathway_code: str
    display_name: str
    duration_months: int | None
    credits_to_complete: int | None
    minimum_average_percent: float | None
    criteria_text: str
    requirements: dict[str, Any]
    alternative_pathways: list[dict[str, Any]]
    available_intakes: list[str]
    source_url: str
    source_sha256: str
    captured_at: str | None
    verified_at: str | None
    review_status: str
    hard_decision_allowed: bool
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metadata(markdown: str) -> dict[str, str]:
    head = markdown.split("---", 2)[1] if markdown.startswith("---") else ""
    return {
        match.group(1): match.group(2).strip()
        for match in FRONTMATTER_RE.finditer(head)
    }


def _program_name(markdown: str, program_code: str) -> str:
    match = re.search(r"(?m)^# (.+?)\s+" + re.escape(program_code) + r"\s*$", markdown)
    return match.group(1).strip() if match else program_code


def _section(markdown: str, heading: str) -> str:
    start = markdown.find(heading)
    if start < 0:
        return ""
    content_start = start + len(heading)
    following = re.search(r"(?m)^## ", markdown[content_start:])
    end = content_start + following.start() if following else len(markdown)
    return markdown[content_start:end].strip()


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _duration_months(text: str) -> int | None:
    years = _number(r"Duration\s*:\s*(\d+(?:\.\d+)?)\s*years?", text)
    return round(years * 12) if years is not None else None


def _display_name(duration_months: int | None) -> str:
    if duration_months is None:
        return "学制以录取通知为准"
    years = duration_months / 12
    value = str(int(years)) if years.is_integer() else str(years)
    return f"{value}年制项目"


def _requirements(text: str) -> dict[str, Any]:
    lower = text.lower()
    percentages = sorted(
        {float(value) for value in re.findall(r"(\d+(?:\.\d+)?)%", text)}
    )
    work_years = _number(
        r"(?:minimum of\s+)?(\d+(?:\.\d+)?)\s+years?\s+relevant work experience",
        text,
    )
    subject_keywords = [
        keyword
        for keyword in (
            "mathematics",
            "statistics",
            "programming",
            "algorithms",
            "computer architecture",
            "operating systems",
            "networks",
            "databases",
            "physics",
            "chemistry",
        )
        if keyword in lower
    ]
    supplementary_patterns = (
        (r"\bcandidate statement\b", "Candidate Statement"),
        (r"\bgmat\b", "GMAT"),
        (r"\bgre\b", "GRE"),
        (r"\bportfolio\b", "Portfolio"),
    )
    supplementary = [
        label for pattern, label in supplementary_patterns if re.search(pattern, lower)
    ]
    return {
        "bachelor_degree_required": "bachelor" in lower,
        "cognate_background_required": "cognate" in lower,
        "honours_degree_mentioned": "honours" in lower,
        "work_experience_months": (
            round(work_years * 12) if work_years is not None else None
        ),
        "percentage_thresholds": percentages,
        "subject_keywords": subject_keywords,
        "supplementary_evidence": supplementary,
    }


def _alternatives(text: str) -> list[dict[str, Any]]:
    parts = [part.strip() for part in re.split(r"(?im)^\s*OR\s*$", text)]
    if len(parts) <= 1:
        return []
    return [
        {"sequence": index, "criteria_text": part}
        for index, part in enumerate(parts, start=1)
        if part
    ]


def extract_monash_criteria(path: str | Path) -> list[ExtractedAdmissionCriterion]:
    source_path = Path(path)
    markdown = source_path.read_text(encoding="utf-8")
    metadata = _metadata(markdown)
    program_code = metadata.get("program_code", "").upper()
    section = _section(markdown, ENTRY_SECTION)
    if not program_code or not section:
        return []
    source_hash = (
        metadata.get("source_sha256")
        or hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    )
    snapshot_index = json.loads(SNAPSHOT_INDEX_PATH.read_text(encoding="utf-8"))
    review_manifest = json.loads(REVIEW_MANIFEST_PATH.read_text(encoding="utf-8"))
    snapshot = snapshot_index.get("sources", {}).get(
        metadata.get("source_id", ""),
        {},
    )
    handbook_facts = _section(markdown, "## Handbook facts")
    faculty_match = re.search(r"(?m)^- Faculty:\s*(.+)$", handbook_facts)
    default_credits = _number(r"Credit points:\s*(\d+)", handbook_facts)
    default_years = _number(
        r"Full-time duration:\s*(\d+(?:\.\d+)?)\s*Years?",
        handbook_facts,
    )
    common = {
        "university_code": metadata.get("university_id", "monash").upper(),
        "university_name": "Monash University",
        "program_code": program_code,
        "program_name": _program_name(markdown, program_code),
        "faculty_name": faculty_match.group(1).strip() if faculty_match else None,
        "discipline_id": {
            "B": "business",
            "C": "computing",
            "E": "engineering",
            "S": "mathematics_science",
        }.get(program_code[:1], "other"),
        "handbook_year": int(metadata.get("handbook_year", "2026")),
        "available_intakes": [],
        "source_url": metadata.get("source_url", ""),
        "source_sha256": source_hash,
        "captured_at": snapshot.get("checked_at"),
    }
    matches = list(ENTRY_PATH_RE.finditer(section))
    if not matches:
        matches = [None]
    records: list[ExtractedAdmissionCriterion] = []
    review = review_manifest.get("reviewed_programs", {}).get(
        f"MONASH:{program_code}:{common['handbook_year']}",
        {},
    )
    for match in matches:
        body = match.group("body").strip() if match else section
        level = match.group("level") if match else None
        credits = _number(r"(\d+)\s*points?\s+to complete", body)
        if credits is None:
            credits = default_credits
        duration = _duration_months(body)
        if duration is None and default_years is not None:
            duration = round(default_years * 12)
        requirements = _requirements(body)
        first_threshold = _number(r"(\d+(?:\.\d+)?)%", body)
        records.append(
            ExtractedAdmissionCriterion(
                **common,
                pathway_code=f"ENTRY_LEVEL_{level}" if level else "STANDARD",
                display_name=_display_name(duration),
                duration_months=duration,
                credits_to_complete=int(credits) if credits is not None else None,
                minimum_average_percent=first_threshold,
                criteria_text=body,
                requirements=requirements,
                alternative_pathways=_alternatives(body),
                verified_at=review.get("verified_at"),
                review_status=review.get("review_status", "REVIEW_REQUIRED"),
                hard_decision_allowed=bool(review.get("hard_decision_allowed", False)),
                evidence={
                    "source_type": "official_handbook",
                    "heading": "Minimum entry requirements",
                    "local_source": str(source_path.resolve()),
                },
            )
        )
    return records


def extract_directory(directory: str | Path) -> list[ExtractedAdmissionCriterion]:
    records: list[ExtractedAdmissionCriterion] = []
    for path in sorted(Path(directory).glob("monash-*-2026.md")):
        if "-unit-" not in path.name:
            records.extend(extract_monash_criteria(path))
    return records


def write_catalog(
    records: Iterable[ExtractedAdmissionCriterion],
    path: str | Path,
) -> int:
    items = [record.to_dict() for record in records]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"schema_version": 1, "records": items},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(items)


def write_vector_documents(
    records: Iterable[ExtractedAdmissionCriterion],
    output_directory: str | Path,
) -> list[Path]:
    grouped: dict[tuple[str, int, str], list[ExtractedAdmissionCriterion]] = {}
    for record in records:
        key = (record.university_code, record.handbook_year, record.program_code)
        grouped.setdefault(key, []).append(record)
    output_root = Path(output_directory)
    output_root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for (_, year, program_code), items in sorted(grouped.items()):
        first = items[0]
        sections = []
        for item in items:
            requirements = item.requirements
            sections.append(
                "\n".join(
                    (
                        f"## {item.display_name}",
                        f"- 内部路径代码: {item.pathway_code}",
                        f"- 需完成学分: {item.credits_to_complete or '以官方录取结果为准'}",
                        f"- 最低均分线: {item.minimum_average_percent if item.minimum_average_percent is not None else '未给出统一数值'}",
                        f"- 相关专业背景要求: {'是' if requirements['cognate_background_required'] else '未明确要求'}",
                        f"- 相关工作经验: {requirements['work_experience_months'] or '未明确要求'}",
                        "",
                        item.criteria_text,
                    )
                )
            )
        target = output_root / f"monash-{program_code.lower()}-admission-{year}.md"
        target.write_text(
            "\n".join(
                (
                    "---",
                    f'source_id: "monash-{program_code.lower()}-admission-{year}"',
                    'university_id: "monash"',
                    f"handbook_year: {year}",
                    f'program_code: "{program_code}"',
                    'source_type: "admission_criteria"',
                    f'source_url: "{first.source_url}"',
                    f'source_sha256: "{first.source_sha256}"',
                    "---",
                    "",
                    f"# {first.program_name} {year} 录取与学制要求",
                    "",
                    "以下内容由 CampusPilot 从学校官方 Handbook 的 Minimum entry requirements 提取。学制是标准路径；个人获批学分减免后，实际就读时间可能更短。",
                    "",
                    *sections,
                    "",
                    "## 使用边界",
                    "是否录取由学校最终审核决定。本资料用于申请规划，不代表录取承诺。",
                    "",
                )
            ),
            encoding="utf-8",
        )
        outputs.append(target)
    return outputs


def sync_catalog(
    session: Session, records: Iterable[ExtractedAdmissionCriterion]
) -> int:
    items = list(records)
    if not items:
        return 0
    university = session.scalar(
        select(University).where(University.code == items[0].university_code)
    )
    if university is None:
        university = University(
            code=items[0].university_code,
            name=items[0].university_name,
            country_code="AU",
            official_url="https://www.monash.edu/",
        )
        session.add(university)
        session.flush()
    synced = 0
    for item in items:
        program = session.scalar(
            select(Program).where(
                Program.university_id == university.id,
                Program.code == item.program_code,
            )
        )
        if program is None:
            program = Program(
                university_id=university.id,
                code=item.program_code,
                name=item.program_name,
                award_type="Masters degree",
            )
            session.add(program)
            session.flush()
        version = session.scalar(
            select(ProgramVersion).where(
                ProgramVersion.program_id == program.id,
                ProgramVersion.handbook_year == item.handbook_year,
            )
        )
        if version is None:
            sibling_credits = [
                candidate.credits_to_complete or 0
                for candidate in items
                if candidate.program_code == item.program_code
                and candidate.handbook_year == item.handbook_year
            ]
            version = ProgramVersion(
                program_id=program.id,
                handbook_year=item.handbook_year,
                total_credits=max(sibling_credits),
                source_url=item.source_url,
                evidence=item.evidence,
            )
            session.add(version)
            session.flush()
        sibling_durations = [
            candidate.duration_months
            for candidate in items
            if candidate.program_code == item.program_code
            and candidate.handbook_year == item.handbook_year
            and candidate.duration_months is not None
        ]
        profile = session.scalar(
            select(ProgramCatalogProfile).where(
                ProgramCatalogProfile.program_version_id == version.id
            )
        )
        profile_values = {
            "faculty_name": item.faculty_name,
            "discipline_id": item.discipline_id,
            "coursework_master": True,
            "duration_months_min": min(sibling_durations),
            "duration_months_max": max(sibling_durations),
            "available_intakes": item.available_intakes,
            "official_url": item.source_url,
            "release_stage": {
                "computing": "FIRST_STAGE_AVAILABLE",
                "business": "FIRST_STAGE_AVAILABLE",
                "engineering": "LATER_STAGE",
            }.get(item.discipline_id, "FUTURE_STAGE"),
        }
        if profile is None:
            session.add(
                ProgramCatalogProfile(
                    program_version_id=version.id,
                    **profile_values,
                )
            )
        else:
            for key, value in profile_values.items():
                setattr(profile, key, value)
        criterion = session.scalar(
            select(AdmissionCriterion).where(
                AdmissionCriterion.program_version_id == version.id,
                AdmissionCriterion.pathway_code == item.pathway_code,
            )
        )
        values = {
            "display_name": item.display_name,
            "duration_months": item.duration_months,
            "credits_to_complete": item.credits_to_complete,
            "minimum_average_percent": item.minimum_average_percent,
            "criteria_text": item.criteria_text,
            "requirements": item.requirements,
            "alternative_pathways": item.alternative_pathways,
            "available_intakes": item.available_intakes,
            "source_url": item.source_url,
            "source_sha256": item.source_sha256,
            "evidence": item.evidence,
        }
        if criterion is None:
            criterion = AdmissionCriterion(
                program_version_id=version.id,
                pathway_code=item.pathway_code,
                **values,
            )
            session.add(criterion)
            session.flush()
        else:
            for key, value in values.items():
                setattr(criterion, key, value)
        source_key = (
            f"monash-{item.program_code.lower()}-{item.handbook_year}-"
            f"{item.pathway_code.lower()}"
        )
        evidence = session.scalar(
            select(AdmissionEvidence).where(AdmissionEvidence.source_key == source_key)
        )

        def parse_datetime(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value).replace(tzinfo=None) if value else None

        captured_at = parse_datetime(item.captured_at)
        verified_at = parse_datetime(item.verified_at)
        evidence_values = {
            "source_type": "OFFICIAL",
            "title": (
                f"{item.program_name} {item.handbook_year} "
                f"{item.display_name} admission requirements"
            ),
            "source_url": item.source_url,
            "excerpt": item.criteria_text,
            "applicable_year": item.handbook_year,
            "captured_at": captured_at,
            "verified_at": verified_at,
            "evidence_grade": "A" if item.hard_decision_allowed else "B",
            "review_status": item.review_status,
            "hard_decision_allowed": item.hard_decision_allowed,
            "source_sha256": item.source_sha256,
        }
        if evidence is None:
            evidence = AdmissionEvidence(
                source_key=source_key,
                **evidence_values,
            )
            session.add(evidence)
            session.flush()
        else:
            for key, value in evidence_values.items():
                setattr(evidence, key, value)
        rule = session.scalar(
            select(AdmissionRule).where(
                AdmissionRule.criterion_id == criterion.id,
                AdmissionRule.rule_code == "PUBLISHED_MINIMUM",
            )
        )
        rule_values = {
            "evidence_id": evidence.id,
            "applicant_condition": item.requirements,
            "metric_type": (
                "PERCENTAGE_AVERAGE"
                if item.minimum_average_percent is not None
                else "QUALITATIVE"
            ),
            "minimum_value": item.minimum_average_percent,
            "scale_max": (100.0 if item.minimum_average_percent is not None else None),
            "applicable_intakes": item.available_intakes,
            "priority": item.duration_months or 999,
        }
        if rule is None:
            session.add(
                AdmissionRule(
                    criterion_id=criterion.id,
                    rule_code="PUBLISHED_MINIMUM",
                    **rule_values,
                )
            )
        else:
            for key, value in rule_values.items():
                setattr(rule, key, value)
        synced += 1
    session.commit()
    return synced
