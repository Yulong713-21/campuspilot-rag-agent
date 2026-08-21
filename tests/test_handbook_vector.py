from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import (
    CampusPilotHybridRetriever,
    CampusPilotMilvusStore,
    HandbookChunk,
    HandbookChunker,
    SentenceTransformerReranker,
    build_ready_corpus,
    validate_milvus_chunks,
)


class FakeEmbedder:
    dimension = 3

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.5] for text in texts]


class FakeMilvusClient:
    def __init__(self) -> None:
        self.last_search: dict | None = None
        self.inserted_rows: list[dict] = []

    def search(self, **kwargs):
        self.last_search = kwargs
        return [
            [
                {
                    "distance": 0.91,
                    "entity": {
                        "chunk_id": "chunk-1",
                        "parent_id": "parent-1",
                        "source_id": "monash-c6001-2026",
                        "university_id": "monash",
                        "handbook_year": 2026,
                        "program_code": "C6001",
                        "source_type": "program_handbook",
                        "discipline_ids": "computing",
                        "title": "Master of Information Technology",
                        "heading": "Requirements",
                        "content": "Complete 96 credit points.",
                        "parent_content": "Requirements: 96 credit points.",
                        "source_url": "https://handbook.monash.edu",
                    },
                }
            ]
        ]

    def insert(self, **kwargs) -> None:
        self.inserted_rows.extend(kwargs["data"])

    def flush(self, collection_name: str) -> None:
        return None


class HandbookChunkerTest(unittest.TestCase):
    def test_preserves_heading_path_and_parent_child_relationship(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "handbook.md"
            path.write_text(
                """---
source_id: "monash-demo"
source_sha256: "abc"
---

# Master of Demo

## Requirements

Complete 96 credit points.

### Core studies

Complete the core courses listed below.
""",
                encoding="utf-8",
            )
            chunks = HandbookChunker(
                parent_size=80,
                child_size=50,
                child_overlap=10,
            ).chunk_document(
                path=path,
                source={
                    "source_id": "monash-demo",
                    "university_id": "monash",
                    "handbook_year": 2026,
                    "program_code": "D6001",
                    "source_type": "program_handbook",
                    "title": "Master of Demo",
                    "url": "https://example.edu/demo",
                    "discipline_ids": ["computing"],
                },
            )

        headings = {chunk.heading for chunk in chunks}
        self.assertIn("Master of Demo > Requirements", headings)
        self.assertIn(
            "Master of Demo > Requirements > Core studies",
            headings,
        )
        self.assertTrue(all(chunk.parent_id for chunk in chunks))
        self.assertTrue(all(len(chunk.content) <= 50 for chunk in chunks))
        self.assertTrue(
            all("Master of Demo" in chunk.embedding_text for chunk in chunks)
        )

    def test_overlong_markdown_heading_is_treated_as_body_text(self) -> None:
        long_rule = "Admission rule " + ("must be satisfied. " * 30)
        markdown = (
            "# Program\n\n"
            "## Rules\n\n"
            f"###### {long_rule}\n\n"
            "## Course structure\n\n"
            "Complete 96 credit points."
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "program.md"
            path.write_text(markdown, encoding="utf-8")
            chunks = HandbookChunker().chunk_document(
                path=path,
                source={
                    "source_id": "test-program-2026",
                    "university_id": "test",
                    "handbook_year": 2026,
                    "program_code": "T100",
                    "source_type": "program_handbook",
                    "discipline_ids": ["computing"],
                    "title": "Test Program",
                    "url": "https://example.edu/program",
                },
            )

        rule_chunk = next(
            chunk
            for chunk in chunks
            if "Admission rule" in chunk.parent_content
        )
        self.assertEqual(rule_chunk.heading, "Program > Rules")

    def test_milvus_schema_validation_runs_before_embedding(self) -> None:
        chunk = HandbookChunk(
            chunk_id="bad-heading",
            parent_id="parent-1",
            source_id="test-program-2026",
            university_id="test",
            handbook_year=2026,
            program_code="T100",
            source_type="program_handbook",
            discipline_ids=["computing"],
            title="Test Program",
            heading="x" * 2049,
            content="valid content",
            parent_content="valid parent content",
            source_url="https://example.edu/program",
            source_sha256="abc",
        )

        with self.assertRaisesRegex(
            ValueError,
            "field heading has length 2049",
        ):
            validate_milvus_chunks([chunk])

    def test_build_ready_corpus_excludes_discovery_sources(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ready_path = root / "ready.md"
            discovery_path = root / "discovery.md"
            ready_path.write_text("# Program\n\nReal rules.", encoding="utf-8")
            discovery_path.write_text(
                "# Search\n\nCatalog only.",
                encoding="utf-8",
            )
            manifest_path = root / "manifest.json"
            report_path = root / "report.json"
            sources = [
                {
                    "source_id": "ready",
                    "university_id": "monash",
                    "handbook_year": 2026,
                    "source_type": "program_handbook",
                    "title": "Ready",
                    "url": "https://example.edu/ready",
                    "discipline_ids": ["computing"],
                },
                {
                    "source_id": "catalog",
                    "university_id": "monash",
                    "handbook_year": 2026,
                    "source_type": "catalog_root",
                    "title": "Catalog",
                    "url": "https://example.edu/catalog",
                    "discipline_ids": ["computing"],
                },
            ]
            manifest_path.write_text(
                json.dumps({"sources": sources}),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "source_id": "ready",
                                "status": "ready",
                                "output_path": str(ready_path),
                            },
                            {
                                "source_id": "catalog",
                                "status": "discovery_only",
                                "output_path": str(discovery_path),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            chunks = build_ready_corpus(
                manifest_path=manifest_path,
                extraction_report_path=report_path,
            )

        self.assertEqual({chunk.source_id for chunk in chunks}, {"ready"})


class CampusPilotMilvusStoreTest(unittest.TestCase):
    def test_reranker_scores_child_content_before_parent_expansion(self) -> None:
        class FakeCrossEncoder:
            def __init__(self) -> None:
                self.pairs: list[tuple[str, str]] = []

            def predict(self, pairs, **kwargs):
                self.pairs = list(pairs)
                return [0.5]

        model = FakeCrossEncoder()
        reranker = SentenceTransformerReranker.__new__(
            SentenceTransformerReranker
        )
        reranker.model = model

        result = reranker.rerank(
            "credit requirements",
            [
                {
                    "content": "Matched child requirement.",
                    "parent_content": "Expanded parent section.",
                }
            ],
        )

        self.assertEqual(
            model.pairs,
            [("credit requirements", "Matched child requirement.")],
        )
        self.assertEqual(result[0]["rerank_score"], 0.5)

    def test_reranker_rank_is_blended_without_overriding_hybrid_consensus(
        self,
    ) -> None:
        reranked = [
            {"chunk_id": "weak", "rrf_score": 0.02, "rerank_score": 0.9},
            {"chunk_id": "strong", "rrf_score": 0.04, "rerank_score": 0.2},
        ]

        blended = CampusPilotHybridRetriever._blend_reranker_rank(
            reranked,
            rrf_constant=60,
        )

        self.assertEqual(blended[0]["chunk_id"], "strong")
        self.assertGreater(
            blended[0]["rrf_score"],
            blended[1]["rrf_score"],
        )

    def test_bm25_only_search_uses_full_chunks_without_vector_store(self) -> None:
        class FakeReranker:
            def rerank(self, query, documents):
                return [
                    {**item, "rerank_score": 0.91}
                    for item in documents
                ]

        business = HandbookChunk(
                chunk_id="business-1",
                parent_id="business-parent",
                source_id="monash-b6022-2026",
                university_id="monash",
                handbook_year=2026,
                program_code="B6022",
                source_type="program_handbook",
                discipline_ids=["business"],
                title="Master of Business Analytics",
                heading="Course structure",
                content="B6022 requires business analytics core units.",
                parent_content="Official B6022 business analytics structure.",
                source_url="https://example.edu/b6022",
                source_sha256="abc",
                program_codes=["B6022"],
            )
        chunks = [
            business,
            HandbookChunk(
                **{
                    **business.to_dict(),
                    "chunk_id": "computing-1",
                    "parent_id": "computing-parent",
                    "source_id": "monash-c6001-2026",
                    "program_code": "C6001",
                    "discipline_ids": ["computing"],
                    "title": "Master of Information Technology",
                    "content": "C6001 information technology degree.",
                    "parent_content": "Official C6001 structure.",
                    "program_codes": ["C6001"],
                }
            ),
            HandbookChunk(
                **{
                    **business.to_dict(),
                    "chunk_id": "engineering-1",
                    "parent_id": "engineering-parent",
                    "source_id": "monash-e6001-2026",
                    "program_code": "E6001",
                    "discipline_ids": ["engineering"],
                    "title": "Master of Engineering",
                    "content": "E6001 engineering degree requirements.",
                    "parent_content": "Official E6001 structure.",
                    "program_codes": ["E6001"],
                }
            ),
        ]
        retriever = CampusPilotHybridRetriever(
            chunks=chunks,
            vector_store=None,
            reranker=FakeReranker(),
        )

        result = retriever.search(
            "B6022 business analytics course structure",
            university_id="monash",
            discipline_id="business",
            program_code="B6022",
            handbook_year=2026,
        )

        self.assertEqual(result[0]["source_id"], "monash-b6022-2026")
        self.assertEqual(result[0]["retrieval_channels"], ["bm25"])
        self.assertEqual(result[0]["rerank_score"], 0.91)
        self.assertFalse(retriever.last_search_diagnostics["degraded"])
        self.assertTrue(retriever.last_search_diagnostics["reranker_active"])

    def test_ingest_reports_completed_batches(self) -> None:
        client = FakeMilvusClient()
        store = CampusPilotMilvusStore(
            uri="http://milvus:19530",
            collection_name="handbook",
            embedder=FakeEmbedder(),
            client=client,
        )
        chunks = [
            HandbookChunk(
                chunk_id=f"chunk-{index}",
                parent_id=f"parent-{index}",
                source_id="monash-c6001-2026",
                university_id="monash",
                handbook_year=2026,
                program_code="C6001",
                source_type="program_handbook",
                discipline_ids=["computing"],
                title="Master of Information Technology",
                heading="Requirements",
                content=f"Requirement {index}",
                parent_content=f"Requirement {index}",
                source_url="https://example.edu/c6001",
                source_sha256="abc",
            )
            for index in range(3)
        ]
        progress: list[tuple[int, int]] = []

        inserted = store.ingest(
            chunks,
            batch_size=2,
            progress_callback=lambda completed, pending: progress.append(
                (completed, pending)
            ),
        )

        self.assertEqual(inserted, 3)
        self.assertEqual(progress, [(2, 1), (3, 0)])
        self.assertEqual(len(client.inserted_rows), 3)

    def test_program_scope_query_is_detected_without_matching_unit_query(self) -> None:
        self.assertTrue(
            CampusPilotHybridRetriever._is_program_scope_query(
                "Banking and Finance course structure requirements"
            )
        )
        self.assertFalse(
            CampusPilotHybridRetriever._is_program_scope_query(
                "ACF5130 assessment and expected workload"
            )
        )

    def test_unit_code_query_keeps_unit_scope(self) -> None:
        self.assertFalse(
            CampusPilotHybridRetriever._is_program_scope_query(
                "MTH3011 assessment and workload"
            )
        )

    def test_search_applies_version_and_scope_filters(self) -> None:
        client = FakeMilvusClient()
        store = CampusPilotMilvusStore(
            uri="http://milvus:19530",
            collection_name="handbook",
            embedder=FakeEmbedder(),
            client=client,
        )

        result = store.search(
            "C6001 credit requirements",
            handbook_year=2026,
            university_id="monash",
            discipline_id="computing",
            program_code="C6001",
            k=5,
        )

        self.assertEqual(result[0]["document_id"], "chunk-1")
        self.assertEqual(result[0]["dense_score"], 0.91)
        self.assertEqual(
            client.last_search["filter"],
            (
                'handbook_year == 2026 and university_id == "monash" '
                'and program_codes like "%|C6001|%" '
                'and discipline_ids like "%computing%"'
            ),
        )
        self.assertEqual(client.last_search["limit"], 5)

    def test_hybrid_search_fuses_channels_and_deduplicates_parents(
        self,
    ) -> None:
        chunks = [
            HandbookChunk(
                chunk_id="chunk-1",
                parent_id="parent-1",
                source_id="monash-c6001-2026",
                university_id="monash",
                handbook_year=2026,
                program_code="C6001",
                source_type="program_handbook",
                discipline_ids=["computing"],
                title="Master of Information Technology",
                heading="Requirements",
                content="C6001 requires 96 credit points.",
                parent_content="Complete 96 credit points for C6001.",
                source_url="https://example.edu/c6001",
                source_sha256="abc",
            ),
            HandbookChunk(
                chunk_id="chunk-2",
                parent_id="parent-2",
                source_id="monash-c6001-2026",
                university_id="monash",
                handbook_year=2026,
                program_code="C6001",
                source_type="program_handbook",
                discipline_ids=["computing"],
                title="Master of Information Technology",
                heading="Overview",
                content="Information technology overview.",
                parent_content="Program overview.",
                source_url="https://example.edu/c6001",
                source_sha256="abc",
            ),
            HandbookChunk(
                chunk_id="chunk-3",
                parent_id="parent-3",
                source_id="unsw-8404-2026",
                university_id="unsw",
                handbook_year=2026,
                program_code="8404",
                source_type="program_handbook",
                discipline_ids=["business"],
                title="Master of Commerce",
                heading="Overview",
                content="Commerce program overview.",
                parent_content="Commerce program overview.",
                source_url="https://example.edu/8404",
                source_sha256="def",
            ),
        ]

        class FakeVectorStore:
            def search(self, query: str, **kwargs):
                return [
                    {
                        **chunks[0].to_dict(),
                        "discipline_ids": "computing",
                        "document_id": "chunk-1",
                        "dense_score": 0.88,
                    }
                ]

        retriever = CampusPilotHybridRetriever(
            chunks=chunks,
            vector_store=FakeVectorStore(),
        )
        results = retriever.search(
            "C6001 96 credit points",
            handbook_year=2026,
            program_code="C6001",
            k=2,
        )

        self.assertEqual(results[0]["document_id"], "chunk-1")
        self.assertEqual(
            set(results[0]["retrieval_channels"]),
            {"bm25", "dense"},
        )
        self.assertEqual(
            results[0]["content"],
            "Complete 96 credit points for C6001.",
        )

    def test_bm25_ignores_program_code_already_used_as_filter(
        self,
    ) -> None:
        chunk = HandbookChunk(
            chunk_id="chunk-1",
            parent_id="parent-1",
            source_id="monash-c6001-2026",
            university_id="monash",
            handbook_year=2026,
            program_code="C6001",
            source_type="program_handbook",
            discipline_ids=["computing"],
            title="Master of Information Technology C6001",
            heading="Overview",
            content="General overview.",
            parent_content="General overview.",
            source_url="https://example.edu/c6001",
            source_sha256="abc",
        )

        class EmptyVectorStore:
            def search(self, query: str, **kwargs):
                return []

        retriever = CampusPilotHybridRetriever(
            chunks=[chunk],
            vector_store=EmptyVectorStore(),
        )
        results = retriever._lexical_search(
            "C6001",
            handbook_year=2026,
            university_id="monash",
            discipline_id="computing",
            program_code="C6001",
            k=3,
        )

        self.assertEqual(results, [])

    def test_hybrid_retrieval_falls_back_to_bm25_when_milvus_recovers(
        self,
    ) -> None:
        chunk = HandbookChunk(
            chunk_id="chunk-recovery",
            parent_id="parent-recovery",
            source_id="monash-c6001-2026",
            university_id="monash",
            handbook_year=2026,
            program_code="C6001",
            source_type="program_handbook",
            discipline_ids=["computing"],
            title="Master of Information Technology",
            heading="Requirements",
            content="The program requires 96 credit points.",
            parent_content="Complete 96 credit points for the program.",
            source_url="https://example.edu/c6001",
            source_sha256="abc",
        )

        class RecoveringVectorStore:
            def search(self, query: str, **kwargs):
                raise RuntimeError("collection is recovering")

        retriever = CampusPilotHybridRetriever(
            chunks=[chunk],
            vector_store=RecoveringVectorStore(),
        )
        lexical_result = {
            **chunk.to_dict(),
            "document_id": chunk.chunk_id,
            "bm25_score": 1.0,
        }
        retriever._lexical_search = (  # type: ignore[method-assign]
            lambda *args, **kwargs: [lexical_result]
        )

        results = retriever.search("program 96 credit points", k=1)

        self.assertEqual(results[0]["document_id"], "chunk-recovery")
        self.assertEqual(results[0]["retrieval_channels"], ["bm25"])
        self.assertTrue(retriever.last_search_diagnostics["degraded"])
        self.assertEqual(
            retriever.last_search_diagnostics["dense_error"],
            "RuntimeError",
        )


if __name__ == "__main__":
    unittest.main()
