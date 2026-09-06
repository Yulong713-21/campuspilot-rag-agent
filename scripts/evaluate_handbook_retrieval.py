"""Run lexical, semantic, hybrid, and reranked evaluation separately."""

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

from agent_runtime.handbook_vector import read_chunks  # noqa: E402
from agent_runtime.retrieval import (  # noqa: E402
    CampusPilotHybridRetriever,
    CampusPilotMilvusStore,
    ElasticsearchHandbookStore,
    InMemoryBM25Retriever,
    LexicalEvidenceRetriever,
    RetrievalScenario,
    RetrievalScenarioEvaluator,
    SemanticEvidenceRetriever,
    SentenceTransformerReranker,
    should_embed,
    create_dense_embedder,
    load_retrieval_cases,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Handbook retrieval by search scenario."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=REPO_ROOT / "eval" / "handbook_retrieval_cases.json",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=[item.value for item in RetrievalScenario],
        default=[RetrievalScenario.LEXICAL.value],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requested = {RetrievalScenario(item) for item in args.scenarios}
    chunks = read_chunks()
    lexical_backend = InMemoryBM25Retriever(chunks)
    if os.environ.get("ELASTICSEARCH_URL"):
        lexical_backend = ElasticsearchHandbookStore(
            url=os.environ["ELASTICSEARCH_URL"],
            index_name=os.environ.get(
                "ELASTICSEARCH_INDEX",
                "campuspilot-handbook-v1",
            ),
        )
        lexical_backend.ensure_ready()

    retrievers = {
        RetrievalScenario.LEXICAL: LexicalEvidenceRetriever(
            lexical_backend
        )
    }
    hybrid_scenarios = {
        RetrievalScenario.SEMANTIC,
        RetrievalScenario.HYBRID,
        RetrievalScenario.HYBRID_RERANKED,
    }
    if requested & hybrid_scenarios:
        model_path = os.environ.get("CAMPUSPILOT_EMBEDDING_MODEL_PATH")
        if not model_path:
            raise RuntimeError(
                "CAMPUSPILOT_EMBEDDING_MODEL_PATH is required for semantic "
                "and hybrid evaluation"
            )
        embedder = create_dense_embedder(
            os.environ.get(
                "CAMPUSPILOT_EMBEDDING_BACKEND",
                "sentence-transformer",
            ),
            model_path,
        )
        dense_backend = CampusPilotMilvusStore(
            uri=os.environ.get(
                "CAMPUSPILOT_MILVUS_URI",
                "http://127.0.0.1:19530",
            ),
            collection_name=os.environ.get(
                "CAMPUSPILOT_MILVUS_COLLECTION",
                "campuspilot_handbook_v2",
            ),
            embedder=embedder,
            canonical_chunks=chunks,
        )
        retrievers[RetrievalScenario.SEMANTIC] = SemanticEvidenceRetriever(
            dense_backend
        )
        retrievers[RetrievalScenario.HYBRID] = CampusPilotHybridRetriever(
            chunks=chunks,
            vector_store=dense_backend,
            lexical_retriever=lexical_backend,
        )
        if RetrievalScenario.HYBRID_RERANKED in requested:
            reranker_path = os.environ.get(
                "CAMPUSPILOT_RERANKER_MODEL_PATH"
            )
            if not reranker_path:
                raise RuntimeError(
                    "CAMPUSPILOT_RERANKER_MODEL_PATH is required for "
                    "hybrid_reranked evaluation"
                )
            retrievers[
                RetrievalScenario.HYBRID_RERANKED
            ] = CampusPilotHybridRetriever(
                chunks=chunks,
                vector_store=dense_backend,
                reranker=SentenceTransformerReranker(reranker_path),
                lexical_retriever=lexical_backend,
            )

    cases = [
        case
        for case in load_retrieval_cases(args.cases)
        if case.scenario in requested
    ]
    report = RetrievalScenarioEvaluator().evaluate(
        cases,
        retrievers,
        total_chunks=len(chunks),
        embedded_chunks=sum(should_embed(chunk) for chunk in chunks),
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
