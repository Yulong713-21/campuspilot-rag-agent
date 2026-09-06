from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import HandbookChunk  # noqa: E402
from agent_runtime.retrieval import (  # noqa: E402
    CampusPilotHybridRetriever,
    EvidenceHit,
    QueryRouter,
    RetrievalPlanExecutor,
    RetrievalScope,
    StructuredResolution,
    reciprocal_rank_fuse,
)


def make_chunk(
    chunk_id: str,
    *,
    parent_id: str | None = None,
    content: str | None = None,
) -> HandbookChunk:
    return HandbookChunk(
        chunk_id=chunk_id,
        parent_id=parent_id or f"{chunk_id}-parent",
        source_id=f"source-{chunk_id}",
        university_id="monash",
        handbook_year=2026,
        program_code="C6001",
        source_type="program_handbook",
        discipline_ids=["computing"],
        title=f"Title {chunk_id}",
        heading="Overview",
        content=content or f"Matched child {chunk_id}",
        parent_content=f"Canonical parent {parent_id or chunk_id}",
        source_url=f"https://example.edu/{chunk_id}",
        source_sha256="hash",
        program_codes=["C6001"],
    )


def hit(chunk_id: str, rank: int, channel: str) -> EvidenceHit:
    return EvidenceHit(
        chunk_id=chunk_id,
        parent_id=f"{chunk_id}-parent",
        source_id=f"source-{chunk_id}",
        rank=rank,
        retrieval_channels=(channel,),
        title=chunk_id,
        heading="Overview",
        content=chunk_id,
        parent_content=chunk_id,
        source_url="https://example.edu",
    )


class StaticChannel:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = list(results or [])
        self.error = error
        self.requested_k: int | None = None

    def search(self, query, **kwargs):
        self.requested_k = kwargs["k"]
        if self.error is not None:
            raise self.error
        return self.results[: kwargs["k"]]


class EvidenceFusionTest(unittest.TestCase):
    def test_same_chunk_is_fused_once_and_cross_channel_agreement_wins(self) -> None:
        ranked = reciprocal_rank_fuse(
            (
                ("bm25", [hit("a", 1, "bm25"), hit("b", 2, "bm25")]),
                ("dense", [hit("b", 1, "dense"), hit("c", 2, "dense")]),
            ),
            rrf_constant=60,
        )

        self.assertEqual([item["chunk_id"] for item in ranked], ["b", "a", "c"])
        self.assertEqual(len(ranked), 3)
        self.assertEqual(set(ranked[0]["retrieval_channels"]), {"bm25", "dense"})

    def test_single_channel_paths_preserve_rank_order(self) -> None:
        lexical = reciprocal_rank_fuse(
            (("bm25", [hit("a", 1, "bm25"), hit("b", 2, "bm25")]),),
            rrf_constant=60,
        )
        semantic = reciprocal_rank_fuse(
            (("dense", [hit("c", 1, "dense"), hit("d", 2, "dense")]),),
            rrf_constant=60,
        )

        self.assertEqual([item["chunk_id"] for item in lexical], ["a", "b"])
        self.assertEqual([item["chunk_id"] for item in semantic], ["c", "d"])

    def test_one_backend_failure_keeps_other_channel_and_diagnostics(self) -> None:
        chunk = make_chunk("lexical")
        lexical = StaticChannel([{**chunk.to_dict(), "bm25_score": 8.0}])
        dense = StaticChannel(error=ConnectionError("offline"))
        retriever = CampusPilotHybridRetriever(
            chunks=[chunk],
            vector_store=dense,
            lexical_retriever=lexical,
        )

        results = retriever.search("career fit", k=1)

        self.assertEqual(results[0]["chunk_id"], "lexical")
        self.assertEqual(results[0]["retrieval_channels"], ["bm25"])
        diagnostics = retriever.last_search_diagnostics
        self.assertEqual(diagnostics["lexical_count"], 1)
        self.assertEqual(diagnostics["semantic_count"], 0)
        self.assertEqual(diagnostics["dense_error"], "ConnectionError")
        self.assertTrue(diagnostics["degraded"])
        self.assertIn("semantic:ConnectionError", diagnostics["degradation_reasons"])

    def test_reranker_failure_preserves_exact_rrf_order(self) -> None:
        chunks = [make_chunk("a"), make_chunk("b")]
        lexical = StaticChannel(
            [{**item.to_dict(), "bm25_score": 2 - index} for index, item in enumerate(chunks)]
        )

        class UnavailableReranker:
            def rerank(self, query, documents):
                raise RuntimeError("model unavailable")

        baseline = CampusPilotHybridRetriever(
            chunks=chunks,
            vector_store=None,
            lexical_retriever=lexical,
        ).search("official wording", use_semantic=False, k=2)
        degraded = CampusPilotHybridRetriever(
            chunks=chunks,
            vector_store=None,
            lexical_retriever=lexical,
            reranker=UnavailableReranker(),
        )

        results = degraded.search("official wording", use_semantic=False, k=2)

        self.assertEqual(
            [item["chunk_id"] for item in results],
            [item["chunk_id"] for item in baseline],
        )
        self.assertTrue(degraded.last_search_diagnostics["reranker_requested"])
        self.assertFalse(degraded.last_search_diagnostics["reranker_used"])
        self.assertEqual(degraded.last_search_diagnostics["reranker_error"], "RuntimeError")

    def test_parent_dedup_keeps_strongest_child_and_merges_provenance(self) -> None:
        first = make_chunk("a", parent_id="shared")
        sibling = make_chunk("b", parent_id="shared")
        other = make_chunk("c")
        lexical = StaticChannel(
            [{**first.to_dict(), "bm25_score": 2.0}, {**other.to_dict(), "bm25_score": 1.0}]
        )
        dense = StaticChannel([{**sibling.to_dict(), "dense_score": 0.9}])
        retriever = CampusPilotHybridRetriever(
            chunks=[first, sibling, other],
            vector_store=dense,
            lexical_retriever=lexical,
        )

        results = retriever.search("shared topic", k=3)

        shared = next(item for item in results if item["parent_id"] == "shared")
        self.assertEqual(shared["chunk_id"], "a")
        self.assertEqual(set(shared["retrieval_channels"]), {"bm25", "dense"})
        self.assertEqual(retriever.last_search_diagnostics["dedup_before_count"], 3)
        self.assertEqual(retriever.last_search_diagnostics["dedup_after_count"], 2)

    def test_unresolved_dense_hit_is_skipped_without_fabricating_text(self) -> None:
        dense = StaticChannel(
            [
                {
                    "chunk_id": "missing",
                    "parent_id": "missing-parent",
                    "source_id": "missing-source",
                    "dense_score": 0.9,
                }
            ]
        )
        retriever = CampusPilotHybridRetriever(
            chunks=[],
            vector_store=dense,
            lexical_retriever=StaticChannel(),
        )

        results = retriever.search(
            "semantic concept",
            use_lexical=False,
            use_semantic=True,
        )

        self.assertEqual(results, [])
        self.assertEqual(
            retriever.last_search_diagnostics["unresolved_evidence_count"],
            1,
        )
        self.assertTrue(retriever.last_search_diagnostics["degraded"])

    def test_candidate_pool_is_wider_bounded_and_output_schema_is_stable(self) -> None:
        chunks = [make_chunk(f"chunk-{index}") for index in range(40)]
        lexical = StaticChannel(
            [{**item.to_dict(), "bm25_score": 40 - index} for index, item in enumerate(chunks)]
        )
        retriever = CampusPilotHybridRetriever(
            chunks=chunks,
            vector_store=None,
            lexical_retriever=lexical,
            maximum_candidate_pool=24,
        )

        results = retriever.search("official evidence", use_semantic=False, k=5)

        self.assertEqual(lexical.requested_k, 20)
        self.assertEqual(len(results), 5)
        self.assertTrue(
            {
                "chunk_id",
                "source_id",
                "title",
                "heading",
                "content",
                "source_url",
                "retrieval_channels",
                "fusion_rank",
                "rerank_rank",
                "metadata",
            }.issubset(results[0])
        )
        self.assertEqual(
            set(retriever.last_search_diagnostics["latency_ms"]),
            {"lexical", "semantic", "fusion", "reranker", "evidence_resolution", "total"},
        )

    def test_reranker_receives_only_its_bounded_rrf_prefix(self) -> None:
        chunks = [make_chunk(f"chunk-{index:02d}") for index in range(35)]
        lexical = StaticChannel(
            [{**item.to_dict(), "bm25_score": 35 - index} for index, item in enumerate(chunks)]
        )

        class RecordingReranker:
            def __init__(self) -> None:
                self.received: list[dict] = []

            def rerank(self, query, documents):
                self.received = list(documents)
                return list(reversed(documents))

        reranker = RecordingReranker()
        retriever = CampusPilotHybridRetriever(
            chunks=chunks,
            vector_store=None,
            lexical_retriever=lexical,
            reranker=reranker,
            reranker_candidate_limit=20,
        )

        results = retriever.search("official evidence", use_semantic=False, k=5)

        self.assertEqual(len(reranker.received), 20)
        self.assertEqual(results[0]["chunk_id"], "chunk-19")
        self.assertEqual(results[0]["rerank_rank"], 1)
        self.assertEqual(
            retriever.last_search_diagnostics["reranker_candidate_count"],
            20,
        )

    def test_structured_result_remains_outside_rrf_candidate_count(self) -> None:
        chunk = make_chunk("evidence")
        lexical = StaticChannel([{**chunk.to_dict(), "bm25_score": 1.0}])
        hybrid = CampusPilotHybridRetriever(
            chunks=[chunk],
            vector_store=None,
            lexical_retriever=lexical,
        )

        class Resolver:
            def resolve(self, query, scope):
                return StructuredResolution(result={"is_offered": True})

        result = RetrievalPlanExecutor(
            router=QueryRouter(),
            evidence_retriever=hybrid,
            structured_resolver=Resolver(),
            semantic_available=False,
        ).execute(
            query="Can I take FIT9136 in Semester 2?",
            scope=RetrievalScope(university_id="monash", handbook_year=2026),
        )

        self.assertEqual(result.structured_result, {"is_offered": True})
        self.assertEqual(result.diagnostics["rrf_candidate_count"], 1)
        self.assertEqual(result.documents[0]["chunk_id"], "evidence")


if __name__ == "__main__":
    unittest.main()
