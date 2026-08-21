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
    CampusPilotHybridRetriever,
    CampusPilotMilvusStore,
    SentenceTransformerReranker,
    create_dense_embedder,
    read_chunks,
)


DEFAULT_MODEL = Path(r"D:\agentdev\models\all-MiniLM-L6-v2")
DEFAULT_RERANKER = Path(r"D:\agentdev\models\ms-marco-MiniLM-L6-v2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the CampusPilot Handbook hybrid index."
    )
    parser.add_argument("query")
    parser.add_argument(
        "--chunks-path",
        type=Path,
        help="Published JSONL chunk corpus used by the BM25 channel.",
    )
    parser.add_argument("--handbook-year", type=int, default=2026)
    parser.add_argument("--university-id")
    parser.add_argument("--discipline-id")
    parser.add_argument("--program-code")
    parser.add_argument("-k", type=int, default=3)
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
        "--reranker-path",
        type=Path,
        default=Path(
            os.environ.get(
                "CAMPUSPILOT_RERANKER_MODEL_PATH",
                DEFAULT_RERANKER,
            )
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started = time.monotonic()
    embedder = create_dense_embedder(args.embedder, args.model_path)
    reranker = SentenceTransformerReranker(args.reranker_path)
    chunks = (
        read_chunks(args.chunks_path)
        if args.chunks_path
        else read_chunks()
    )
    retriever = CampusPilotHybridRetriever(
        chunks=chunks,
        vector_store=CampusPilotMilvusStore(
            uri=args.milvus_uri,
            collection_name=args.collection,
            embedder=embedder,
        ),
        reranker=reranker,
    )
    results = retriever.search(
        args.query,
        handbook_year=args.handbook_year,
        university_id=args.university_id,
        discipline_id=args.discipline_id,
        program_code=args.program_code,
        k=args.k,
    )
    print(
        json.dumps(
            {
                "query": args.query,
                "document_count": len(results),
                "answer_source": "handbook_hybrid_retrieval",
                "confidence": "high" if results else "low",
                "next_action": (
                    "generate_grounded_answer"
                    if results
                    else "ask_clarification"
                ),
                "trace_tools": [
                    "bm25_search",
                    "milvus_dense_search",
                    "rrf_fusion",
                    "cross_encoder_rerank",
                    "parent_deduplication",
                ],
                "retrieval_diagnostics": retriever.last_search_diagnostics,
                "elapsed_seconds": round(
                    time.monotonic() - started,
                    3,
                ),
                "documents": [
                    {
                        "document_id": item["document_id"],
                        "source_id": item["source_id"],
                        "title": item["title"],
                        "heading": item["heading"],
                        "source_url": item["source_url"],
                        "retrieval_channels": item[
                            "retrieval_channels"
                        ],
                        "score": item["score"],
                        "bm25_score": item.get("bm25_score"),
                        "dense_score": item.get("dense_score"),
                        "rerank_score": item.get("rerank_score"),
                        "reranker_rrf_score": item.get(
                            "reranker_rrf_score"
                        ),
                        "content_preview": item["content"][:500],
                    }
                    for item in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
