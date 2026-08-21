from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot import CampusPilotCatalog
from agent_runtime.source_sync import OfficialSourceSynchronizer


DEFAULT_MANIFEST = REPO_ROOT / "data" / "campuspilot_source_manifest.json"
DEFAULT_STAGE_DIR = REPO_ROOT / "logs" / "campuspilot-source-staging"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check official CampusPilot sources for content changes."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--stage-changed", action="store_true")
    parser.add_argument("--accept-baseline", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = (
        json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.manifest.exists()
        else {"sources": {}}
    )
    catalog = CampusPilotCatalog()
    synchronizer = OfficialSourceSynchronizer()
    results = []
    next_hashes = dict(manifest.get("sources", {}))

    for source in catalog.data["sources"]:
        previous_hash = manifest.get("sources", {}).get(source["source_id"])
        check, content = synchronizer.check(source, previous_hash)
        item = asdict(check)
        if (
            args.stage_changed
            and content is not None
            and check.status in {"new", "changed"}
        ):
            item["staged_path"] = str(
                synchronizer.stage(
                    directory=DEFAULT_STAGE_DIR,
                    check=check,
                    content=content,
                )
            )
        if args.accept_baseline and check.content_sha256 is not None:
            next_hashes[source["source_id"]] = check.content_sha256
        results.append(item)

    if args.accept_baseline:
        args.manifest.write_text(
            json.dumps(
                {
                    "catalog_version": catalog.data["catalog_version"],
                    "accepted_at": catalog.data["retrieved_at"],
                    "sources": next_hashes,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "catalog_version": catalog.data["catalog_version"],
                "auto_publish": False,
                "results": results,
                "next_action": (
                    "review_changed_sources_then_reingest_and_run_regression"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
