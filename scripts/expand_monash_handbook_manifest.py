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
    build_monash_program_sources,
    coverage_summary,
    fetch_monash_course_catalog,
    merge_monash_program_sources,
)


DEFAULT_MANIFEST = REPO_ROOT / "data" / "handbook_source_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Expand the source manifest from Monash's official course search."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2024, 2025, 2026],
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    catalog = fetch_monash_course_catalog()
    generated = build_monash_program_sources(
        catalog,
        handbook_years=args.years,
    )
    expanded = merge_monash_program_sources(manifest, generated)
    if not args.dry_run:
        args.manifest.write_text(
            json.dumps(expanded, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "official_search_results": len(catalog),
                "coverage": coverage_summary(expanded["sources"]),
                "manifest_sources": len(expanded["sources"]),
                "next_action": (
                    "download_monash_program_snapshots"
                    if not args.dry_run
                    else "review_then_write_manifest"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
