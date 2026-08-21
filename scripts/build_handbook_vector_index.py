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

from agent_runtime.handbook_vector import (
    CampusPilotMilvusStore,
    build_ready_corpus,
    create_dense_embedder,
    read_chunks,
    validate_milvus_chunks,
    write_chunks,
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("batch size must be greater than zero")
    started = time.monotonic()
    if args.chunks_path is not None:
        chunks = read_chunks(args.chunks_path)
        chunk_count = len(chunks)
        corpus_source = str(args.chunks_path)
    else:
        chunks = build_ready_corpus()
        chunk_count = write_chunks(chunks)
        corpus_source = "raw_official_sources"
    validate_milvus_chunks(chunks)
    chunk_elapsed = time.monotonic() - started

    index_started = time.monotonic()
    embedder = create_dense_embedder(args.embedder, args.model_path)
    store = CampusPilotMilvusStore(
        uri=args.milvus_uri,
        collection_name=args.collection,
        embedder=embedder,
    )
    if args.resume and args.resume_offset:
        raise ValueError("use either --resume or --resume-offset, not both")
    resume_offset = store.row_count() if args.resume else args.resume_offset
    if resume_offset:
        current_count = store.row_count()
        if current_count != resume_offset:
            raise RuntimeError(
                "resume offset does not match Milvus row count: "
                f"{resume_offset} != {current_count}"
            )
        expected_ids = {
            chunk.chunk_id for chunk in chunks[:resume_offset]
        }
        actual_ids = store.chunk_ids(limit=resume_offset)
        if actual_ids != expected_ids:
            raise RuntimeError(
                "existing Milvus chunk IDs do not match the "
                "current corpus prefix"
            )
    else:
        store.recreate_collection()

    def report_progress(inserted: int, pending: int) -> None:
        print(
            json.dumps(
                {
                    "event": "index_progress",
                    "indexed_entities": resume_offset + inserted,
                    "total_entities": len(chunks),
                    "completed_this_run": inserted,
                    "pending_this_run": pending,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    inserted = store.ingest(
        chunks[resume_offset:],
        batch_size=args.batch_size,
        progress_callback=report_progress,
    )
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
                "child_chunks": chunk_count,
                "resume_offset": resume_offset,
                "inserted_this_run": inserted,
                "indexed_entities": resume_offset + inserted,
                "chunk_seconds": round(chunk_elapsed, 3),
                "embedding_and_index_seconds": round(
                    total_elapsed - (index_started - started),
                    3,
                ),
                "total_seconds": round(total_elapsed, 3),
                "next_action": "run_hybrid_retrieval_smoke_test",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
