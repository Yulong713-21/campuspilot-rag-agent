from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import (  # noqa: E402
    CampusPilotMilvusStore,
    HandbookChunker,
    create_dense_embedder,
    validate_milvus_chunks,
    write_chunks,
)


DEFAULT_MODEL = Path(r"D:\agentdev\models\all-MiniLM-L6-v2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the dedicated CampusPilot admission criteria index."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=REPO_ROOT / "data/admissions/monash_2026.json",
    )
    parser.add_argument(
        "--document-directory",
        type=Path,
        default=REPO_ROOT / "data/admissions/vector_docs/monash/2026",
    )
    parser.add_argument(
        "--chunk-output",
        type=Path,
        default=REPO_ROOT / "data/admissions/admission-chunks.jsonl",
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
            "CAMPUSPILOT_ADMISSION_COLLECTION",
            "campuspilot_admissions_v1",
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
        default=Path(os.environ.get("CAMPUSPILOT_EMBEDDING_MODEL_PATH", DEFAULT_MODEL)),
    )
    parser.add_argument("--chunks-only", action="store_true")
    return parser.parse_args()


def discipline_for(program_code: str) -> str:
    return {
        "B": "business",
        "C": "computing",
        "E": "engineering",
        "S": "science-mathematics",
    }.get(program_code[:1], "other")


def main() -> None:
    args = parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    records = catalog["records"]
    by_program = {}
    for record in records:
        by_program.setdefault(record["program_code"], record)
    chunker = HandbookChunker(parent_size=2400, child_size=900, child_overlap=120)
    chunks = []
    for program_code, record in sorted(by_program.items()):
        source_id = f"monash-{program_code.lower()}-admission-2026"
        path = args.document_directory / f"{source_id}.md"
        chunks.extend(
            chunker.chunk_document(
                path=path,
                source={
                    "source_id": source_id,
                    "university_id": "monash",
                    "handbook_year": record["handbook_year"],
                    "program_code": program_code,
                    "source_type": "admission_criteria",
                    "discipline_ids": [discipline_for(program_code)],
                    "title": (
                        f"{record['program_name']} {record['handbook_year']} "
                        "录取与学制要求"
                    ),
                    "url": record["source_url"],
                },
            )
        )
    validate_milvus_chunks(chunks)
    write_chunks(chunks, args.chunk_output)
    indexed = 0
    if not args.chunks_only:
        embedder = create_dense_embedder(args.embedder, args.model_path)
        store = CampusPilotMilvusStore(
            uri=args.milvus_uri,
            collection_name=args.collection,
            embedder=embedder,
        )
        store.recreate_collection()
        indexed = store.ingest(chunks)
    print(
        json.dumps(
            {
                "collection": args.collection,
                "program_documents": len(by_program),
                "child_chunks": len(chunks),
                "indexed_entities": indexed,
                "source_type": "admission_criteria",
                "next_action": "run_admission_retrieval_acceptance",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
