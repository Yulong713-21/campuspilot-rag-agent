from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from campuspilot_core.coverage import AcademicCoverageRegistry


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_coverage_report(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    data = root / "data"
    official = data / "official_sources"

    manifest = _read_json(data / "handbook_source_manifest.json")
    extraction = _read_json(official / "extraction-report.json")
    institutions = _read_json(
        data / "admissions" / "institution_catalog_2026.json"
    )
    business = _read_json(
        data / "admissions" / "go8_business_catalog_2026.json"
    )
    reviewed = _read_json(data / "admissions" / "reviewed_rules.json")
    academic_coverage = AcademicCoverageRegistry.from_path(
        data / "academic_coverage.json"
    )
    faq = _read_json(data / "campuspilot_faq.json")
    assessments = _read_json(data / "campuspilot_unit_assessments_2026.json")

    source_counts = Counter(
        source.get("university_id", "unknown")
        for source in manifest.get("sources", [])
    )
    source_type_counts = Counter(
        source.get("source_type", "unknown")
        for source in manifest.get("sources", [])
    )
    chunk_counts: Counter[str] = Counter()
    parent_ids: set[str] = set()
    invalid_chunk_lines: list[int] = []
    chunk_path = official / "handbook-chunks.jsonl"
    with chunk_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                invalid_chunk_lines.append(line_number)
                continue
            chunk_counts[chunk.get("university_id", "unknown")] += 1
            parent_ids.add(chunk["parent_id"])

    vector_docs = list(
        (data / "admissions" / "vector_docs").rglob("*.md")
    )
    reviewed_programs = reviewed.get("reviewed_programs", {})
    return {
        "report_version": "1.0",
        "handbook": {
            "manifest_sources": len(manifest.get("sources", [])),
            "sources_by_owner": dict(source_counts.most_common()),
            "sources_by_type": dict(source_type_counts.most_common()),
            "extraction": extraction.get("summary", {}),
            "child_chunks": sum(chunk_counts.values()),
            "parent_chunks": len(parent_ids),
            "chunks_by_owner": dict(chunk_counts.most_common()),
            "invalid_chunk_lines": invalid_chunk_lines,
        },
        "admissions": {
            "vector_documents": len(vector_docs),
            "reviewed_programs": len(reviewed_programs),
            "reviewed_program_ids": sorted(reviewed_programs),
            "business_catalog_programs_outside_monash": len(
                business.get("programs", [])
            ),
        },
        "institutions": institutions.get("counts", {}),
        "academic_coverage": academic_coverage.summary(),
        "faq_entries": len(faq.get("entries", [])),
        "unit_assessments": len(assessments.get("units", [])),
        "quality_gate": {
            "chunk_json_valid": not invalid_chunk_lines,
            "hard_decision_scope_limited": len(reviewed_programs)
            < len(vector_docs),
        },
    }
