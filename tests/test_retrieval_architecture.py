from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime import handbook_vector  # noqa: E402
from agent_runtime.retrieval import (  # noqa: E402
    CampusPilotHybridRetriever,
    CampusPilotMilvusStore,
    DenseRetriever,
    InMemoryBM25Retriever,
    LexicalRetriever,
    SentenceTransformerReranker,
)


class RetrievalArchitectureTest(unittest.TestCase):
    def test_legacy_module_reexports_retrieval_implementations(self) -> None:
        self.assertIs(
            handbook_vector.CampusPilotHybridRetriever,
            CampusPilotHybridRetriever,
        )
        self.assertIs(
            handbook_vector.CampusPilotMilvusStore,
            CampusPilotMilvusStore,
        )
        self.assertIs(
            handbook_vector.SentenceTransformerReranker,
            SentenceTransformerReranker,
        )

    def test_retrieval_protocols_define_metadata_aware_search(self) -> None:
        for protocol in (LexicalRetriever, DenseRetriever):
            annotations = protocol.search.__annotations__
            self.assertIn("handbook_year", annotations)
            self.assertIn("university_id", annotations)
            self.assertIn("discipline_id", annotations)
            self.assertIn("program_code", annotations)
            self.assertIn("source_type", annotations)

    def test_hybrid_retriever_uses_in_memory_bm25_by_default(self) -> None:
        chunk = handbook_vector.HandbookChunk(
            chunk_id="chunk-1",
            parent_id="parent-1",
            source_id="source-1",
            university_id="monash",
            handbook_year=2026,
            program_code="C6001",
            source_type="program_handbook",
            discipline_ids=["computing"],
            title="Master of Information Technology",
            heading="Requirements",
            content="Complete 96 credit points.",
            parent_content="Complete 96 credit points.",
            source_url="https://example.edu/c6001",
            source_sha256="abc",
        )
        retriever = CampusPilotHybridRetriever(
            chunks=[chunk],
            vector_store=None,
        )

        self.assertIsInstance(
            retriever.lexical_retriever,
            InMemoryBM25Retriever,
        )


if __name__ == "__main__":
    unittest.main()
