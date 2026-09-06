"""Publish the canonical Handbook chunk corpus to Elasticsearch BM25."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import read_chunks  # noqa: E402
from agent_runtime.retrieval import ElasticsearchHandbookStore  # noqa: E402
from agent_runtime.retrieval import (  # noqa: E402
    IndexState,
    plan_incremental_index,
)


def parse_args() -> argparse.Namespace:
    """Read CLI overrides while keeping environment-based defaults."""
    parser = argparse.ArgumentParser(
        description="Build the CampusPilot Elasticsearch Handbook index."
    )
    parser.add_argument(
        "--chunks-path",
        type=Path,
        help="Published Handbook JSONL corpus; defaults to the canonical corpus.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
    )
    parser.add_argument(
        "--index",
        default=os.environ.get(
            "ELASTICSEARCH_INDEX",
            "campuspilot-handbook-v1",
        ),
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--state-path",
        type=Path,
        default=REPO_ROOT / "logs" / "handbook-lexical-index-state.json",
        help="Last successfully published source hashes and chunk IDs.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Delete and recreate the target index before indexing.",
    )
    return parser.parse_args()


def main() -> None:
    """Publish the corpus and print machine-readable indexing statistics."""
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch size must be greater than zero")
    started = time.monotonic()
    chunks = read_chunks(args.chunks_path) if args.chunks_path else read_chunks()
    store = ElasticsearchHandbookStore(url=args.url, index_name=args.index)
    if args.recreate:
        store.recreate_index()
        previous = IndexState.empty()
    else:
        store.ensure_ready()
        previous = IndexState.read(args.state_path)
    plan = plan_incremental_index(chunks, previous)
    deleted = store.delete(list(plan.delete_chunk_ids))
    indexed = store.ingest(
        plan.upsert_chunks,
        chunk_size=args.batch_size,
    )
    plan.next_state.write(args.state_path)
    print(
        json.dumps(
            {
                "index": args.index,
                "elasticsearch_url": args.url,
                "indexed_chunks": indexed,
                "deleted_chunks": deleted,
                "changed_sources": list(plan.changed_sources),
                "unchanged_source_count": len(plan.unchanged_sources),
                "removed_sources": list(plan.removed_sources),
                "source_count": len({chunk.source_id for chunk in chunks}),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
