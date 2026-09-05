from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import (  # noqa: E402
    CampusPilotMilvusStore,
    build_ready_corpus,
    create_dense_embedder,
    read_chunks,
    validate_milvus_chunks,
    write_chunks,
)
from agent_runtime.retrieval import (  # noqa: E402
    IndexState,
    SEMANTIC_POLICY_VERSION,
    classify_semantic_eligibility,
    plan_incremental_index,
)


DEFAULT_MODEL = Path(r"D:\agentdev\models\all-MiniLM-L6-v2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the CampusPilot versioned Handbook vector index."
    )
    parser.add_argument(
        "--chunks-path",
        type=Path,
        help=(
            "Read an already published JSONL chunk corpus instead of "
            "rebuilding it from raw source documents."
        ),
    )
    parser.add_argument(
        "--milvus-uri",
        default=os.environ.get(
            "CAMPUSPILOT_MILVUS_URI",
            "http://192.168.150.101:19530",
        ),
    )
    parser.add_argument(
        "--collection",
        default=os.environ.get(
            "CAMPUSPILOT_MILVUS_COLLECTION",
            "campuspilot_handbook_v2",
        ),
    )
    parser.add_argument(
        "--embedder",
        choices=("sentence-transformer", "bge-m3"),
        default=os.environ.get(
            "CAMPUSPILOT_EMBEDDING_BACKEND",
            "sentence-transformer",
        ),
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path(
            os.environ.get("CAMPUSPILOT_EMBEDDING_MODEL_PATH", DEFAULT_MODEL)
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Number of chunks encoded and inserted per Milvus batch.",
    )
    parser.add_argument(
        "--resume-offset",
        type=int,
        default=0,
        help="Continue after this many verified existing entities.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue from the verified current Milvus row count.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the collection before publishing the current corpus.",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=REPO_ROOT / "logs" / "handbook-vector-index-state.json",
        help="Last successfully published source hashes and chunk IDs.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Measure semantic eligibility without loading a model or Milvus.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch size must be greater than zero")
    started = time.monotonic()
    if args.report_only and args.chunks_path is None:
        chunks = read_chunks()
        chunk_count = len(chunks)
        corpus_source = "published_chunk_corpus"
    elif args.chunks_path is not None:
        chunks = read_chunks(args.chunks_path)
        chunk_count = len(chunks)
        corpus_source = str(args.chunks_path)
    else:
        chunks = build_ready_corpus()
        chunk_count = write_chunks(chunks)
        corpus_source = "raw_official_sources"
    classifications = [classify_semantic_eligibility(chunk) for chunk in chunks]
    eligible_chunks = [
        chunk
        for chunk, result in zip(chunks, classifications, strict=True)
        if result.eligible
    ]
    category_counts = Counter(
        result.category.value
        for result in classifications
        if result.category is not None
    )
    skip_counts = Counter(
        result.skip_reason
        for result in classifications
        if result.skip_reason is not None
    )
    validate_milvus_chunks(eligible_chunks)
    chunk_elapsed = time.monotonic() - started
    subset_summary = {
        "semantic_policy_version": SEMANTIC_POLICY_VERSION,
        "total_chunks": chunk_count,
        "eligible_chunks": len(eligible_chunks),
        "skipped_chunks": chunk_count - len(eligible_chunks),
        "eligibility_ratio": round(
            len(eligible_chunks) / chunk_count if chunk_count else 0.0,
            6,
        ),
        "counts_by_semantic_category": dict(
            sorted(category_counts.items())
        ),
        "counts_by_skip_reason": dict(sorted(skip_counts.items())),
    }
    if args.report_only:
        print(
            json.dumps(
                {
                    **subset_summary,
                    "embedded_or_upserted": 0,
                    "deleted": 0,
                    "unchanged": len(eligible_chunks),
                    "elapsed_time": round(chunk_elapsed, 3),
                    "mode": "report_only",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    index_started = time.monotonic()
    embedder = create_dense_embedder(args.embedder, args.model_path)
    store = CampusPilotMilvusStore(
        uri=args.milvus_uri,
        collection_name=args.collection,
        embedder=embedder,
    )
    collection_exists = store.has_collection()
    before_indexed_chunks = store.row_count() if collection_exists else 0
    if args.recreate and (args.resume or args.resume_offset):
        raise ValueError("--recreate cannot be combined with resume options")
    if args.resume and args.resume_offset:
        raise ValueError("use either --resume or --resume-offset, not both")
    resume_offset = store.row_count() if args.resume else args.resume_offset
    changed_sources: list[str] = []
    unchanged_source_count = 0
    removed_sources: list[str] = []
    deleted = 0
    unchanged_chunks = 0
    collection_recreated = False
    if resume_offset:
        current_count = store.row_count()
        if current_count != resume_offset:
            raise RuntimeError(
                "resume offset does not match Milvus row count: "
                f"{resume_offset} != {current_count}"
            )
        expected_ids = {
            chunk.chunk_id for chunk in eligible_chunks[:resume_offset]
        }
        actual_ids = store.chunk_ids(limit=resume_offset)
        if actual_ids != expected_ids:
            raise RuntimeError(
                "existing Milvus chunk IDs do not match the "
                "current corpus prefix"
            )
    elif args.recreate or not collection_exists:
        store.recreate_collection()
        collection_recreated = True

    def report_progress(inserted: int, pending: int) -> None:
        print(
            json.dumps(
                {
                    "event": "index_progress",
                    "indexed_entities": resume_offset + inserted,
                    "total_entities": len(eligible_chunks),
                    "completed_this_run": inserted,
                    "pending_this_run": pending,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    if resume_offset:
        inserted = store.ingest(
            eligible_chunks[resume_offset:],
            batch_size=args.batch_size,
            progress_callback=report_progress,
        )
        plan_incremental_index(
            eligible_chunks,
            IndexState.empty(),
        ).next_state.write(args.state_path)
        unchanged_chunks = resume_offset
    else:
        previous = (
            IndexState.empty()
            if collection_recreated
            else IndexState.read(args.state_path)
        )
        plan = plan_incremental_index(eligible_chunks, previous)
        deleted = store.delete(list(plan.delete_chunk_ids))
        inserted = store.upsert(
            list(plan.upsert_chunks),
            batch_size=args.batch_size,
        )
        plan.next_state.write(args.state_path)
        changed_sources = list(plan.changed_sources)
        unchanged_source_count = len(plan.unchanged_sources)
        removed_sources = list(plan.removed_sources)
        unchanged_chunks = len(eligible_chunks) - len(plan.upsert_chunks)
    total_elapsed = time.monotonic() - started
    print(
        json.dumps(
            {
                "collection": args.collection,
                "milvus_uri": args.milvus_uri,
                "embedding_backend": args.embedder,
                "embedding_dimension": embedder.dimension,
                "corpus_source": corpus_source,
                "ready_sources": len({chunk.source_id for chunk in chunks}),
                "parent_chunks": len(
                    {chunk.parent_id for chunk in chunks}
                ),
                **subset_summary,
                "resume_offset": resume_offset,
                "embedded_or_upserted": inserted,
                "deleted": deleted,
                "unchanged": unchanged_chunks,
                "changed_sources": changed_sources,
                "unchanged_source_count": unchanged_source_count,
                "removed_sources": removed_sources,
                "before_indexed_chunks": before_indexed_chunks,
                "after_indexed_chunks": store.row_count(),
                "chunk_seconds": round(chunk_elapsed, 3),
                "embedding_and_index_seconds": round(
                    total_elapsed - (index_started - started),
                    3,
                ),
                "elapsed_time": round(total_elapsed, 3),
                "next_action": "run_hybrid_retrieval_smoke_test",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
