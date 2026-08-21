from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.monash_catalog import (
    build_monash_unit_sources,
    merge_monash_unit_sources,
)


DEFAULT_MANIFEST = REPO_ROOT / "data" / "handbook_source_manifest.json"
DEFAULT_REPORT = (
    REPO_ROOT / "data" / "official_sources" / "extraction-report.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Add versioned Monash units referenced by scoped programs."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument(
        "--extraction-report",
        type=Path,
        default=DEFAULT_REPORT,
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = json.loads(
        args.extraction_report.read_text(encoding="utf-8")
    )
    source_by_id = {
        source["source_id"]: source for source in manifest["sources"]
    }
    program_documents = []
    for result in report["results"]:
        source = source_by_id[result["source_id"]]
        if (
            result["status"] == "ready"
            and source.get("university_id") == "monash"
            and source.get("source_type") == "program_handbook"
        ):
            program_documents.append(
                (
                    source,
                    Path(result["output_path"]).read_text(
                        encoding="utf-8"
                    ),
                )
            )
    units = build_monash_unit_sources(program_documents)
    expanded = merge_monash_unit_sources(manifest, units)
    if not args.dry_run:
        args.manifest.write_text(
            json.dumps(expanded, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "program_documents": len(program_documents),
                "unit_year_versions": len(units),
                "unique_unit_codes": len(
                    {
                        source["title"].removeprefix("Monash Unit ")
                        for source in units
                    }
                ),
                "manifest_sources": len(expanded["sources"]),
                "next_action": "download_monash_unit_snapshots",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
