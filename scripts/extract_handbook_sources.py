from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_extract import HandbookExtractor


MANIFEST_PATH = REPO_ROOT / "data" / "handbook_source_manifest.json"
SOURCE_ROOT = REPO_ROOT / "data" / "official_sources"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    source_index = json.loads(
        (SOURCE_ROOT / "index.json").read_text(encoding="utf-8")
    )
    report = HandbookExtractor().extract_manifest(
        manifest=manifest,
        source_index=source_index,
        output_directory=SOURCE_ROOT / "clean",
    )
    (SOURCE_ROOT / "extraction-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest_version": report["manifest_version"],
                "summary": report["summary"],
                "needs_review": [
                    {
                        "source_id": item["source_id"],
                        "status": item["status"],
                        "characters": item["character_count"],
                        "error": item["error"],
                    }
                    for item in report["results"]
                    if item["status"] not in {"ready", "discovery_only"}
                ],
                "next_action": report["next_action"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
