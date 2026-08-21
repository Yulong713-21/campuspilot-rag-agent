from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.source_sync import OfficialSourceSynchronizer
from agent_runtime.unit_guide import MonashUnitGuideParser


CATALOG_PATH = REPO_ROOT / "data" / "campuspilot_official_sample.json"
OUTPUT_ROOT = REPO_ROOT / "data" / "unit_sources"
CURATED_OUTPUT = REPO_ROOT / "data" / "campuspilot_unit_assessments_2026.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect structured Monash assessment facts."
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    course_codes = sorted(
        course["course_code"] for course in catalog["courses"]
    )
    manifest = {
        "manifest_version": f"monash-unit-details-{args.year}-v1",
        "allowed_domains": ["monash.edu"],
        "sources": [
            {
                "source_id": f"monash-{code.lower()}-{args.year}",
                "university_id": "monash",
                "handbook_year": args.year,
                "source_type": "unit_handbook",
                "title": f"{code} official unit page",
                "url": (
                    f"https://handbook.monash.edu/{args.year}/units/"
                    f"{code.lower()}"
                ),
                "course_code": code,
                "expected_content_markers": [code, "Assessment"],
            }
            for code in course_codes
        ],
    }
    report = OfficialSourceSynchronizer(
        timeout_seconds=45.0,
        allowed_domains={"monash.edu"},
    ).sync_manifest(
        manifest=manifest,
        output_directory=OUTPUT_ROOT,
        force_refresh=args.refresh,
        delay_seconds=0.2,
        limit=args.limit,
    )
    state = json.loads(
        (OUTPUT_ROOT / "index.json").read_text(encoding="utf-8")
    )
    parser = MonashUnitGuideParser()
    units = []
    errors = []
    selected = manifest["sources"]
    if args.limit is not None:
        selected = selected[: args.limit]
    for source in selected:
        record = state["sources"].get(source["source_id"])
        if not record:
            errors.append(
                {
                    "course_code": source["course_code"],
                    "error": "snapshot unavailable",
                }
            )
            continue
        try:
            unit = parser.parse(
                Path(record["local_path"]).read_bytes(),
                source_url=source["url"],
                source_sha256=record["content_sha256"],
                captured_at=record["checked_at"],
            )
            unit["source_id"] = source["source_id"]
            units.append(unit)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(
                {
                    "course_code": source["course_code"],
                    "error": str(exc),
                }
            )
    payload = {
        "dataset_version": manifest["manifest_version"],
        "source": "Monash University Handbook",
        "unit_count": len(units),
        "units": sorted(units, key=lambda item: item["course_code"]),
        "errors": errors,
    }
    CURATED_OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "download_summary": report["summary"],
                "parsed_units": len(units),
                "errors": errors,
                "curated_output": str(CURATED_OUTPUT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
