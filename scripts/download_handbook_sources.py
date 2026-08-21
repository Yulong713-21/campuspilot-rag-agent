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


DEFAULT_MANIFEST = REPO_ROOT / "data" / "handbook_source_manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "official_sources"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download curated CampusPilot official source snapshots."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--university-id",
        help="Download only sources for one university while preserving state.",
    )
    parser.add_argument("--delay-seconds", type=float, default=0.15)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    selected_manifest = manifest
    if args.university_id:
        selected_manifest = {
            **manifest,
            "sources": [
                source
                for source in manifest["sources"]
                if source.get("university_id") == args.university_id
            ],
        }
    synchronizer = OfficialSourceSynchronizer(
        timeout_seconds=45.0,
        allowed_domains=set(manifest["allowed_domains"]),
    )
    report = synchronizer.sync_manifest(
        manifest=selected_manifest,
        output_directory=args.output,
        force_refresh=args.refresh,
        delay_seconds=args.delay_seconds,
        limit=args.limit,
    )
    print(
        json.dumps(
            {
                "manifest_version": report["manifest_version"],
                "output_directory": report["output_directory"],
                "summary": report["summary"],
                "unresolved": [
                    {
                        "source_id": item["source_id"],
                        "status": item["status"],
                        "url": item["url"],
                        "error": item["error"],
                    }
                    for item in report["results"]
                    if item["status"]
                    in {
                        "error",
                        "blocked",
                        "browser_required",
                        "invalid_snapshot",
                    }
                ],
                "next_action": report["next_action"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
