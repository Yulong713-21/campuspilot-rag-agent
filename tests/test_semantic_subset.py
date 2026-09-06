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
    CampusPilotMilvusStore,
    IndexState,
    RetrievalRequest,
    RetrievalScope,
    SemanticCategory,
    classify_semantic_eligibility,
    plan_incremental_index,
    semantic_embedding_text,
    should_embed,
)


def make_chunk(
    *,
    chunk_id: str = "chunk-1",
    heading: str = "Program overview",
    content: str = (
        "This program develops advanced computing knowledge and practical "
        "skills for solving complex technology problems across industries. "
        "Students learn to evaluate solutions and communicate their advice."
    ),
    source_hash: str = "source-v1",
    source_type: str = "program_handbook",
) -> HandbookChunk:
    return HandbookChunk(
        chunk_id=chunk_id,
        parent_id="parent-1",
        source_id="monash-c6001-2026",
        university_id="monash",
        handbook_year=2026,
        program_code="C6001",
        source_type=source_type,
        discipline_ids=["computing"],
        title="Master of Information Technology",
        heading=heading,
        content=content,
        parent_content=f"Canonical parent: {content}",
        source_url="https://example.edu/c6001",
        source_sha256=source_hash,
        program_codes=["C6001"],
        specialisation_codes=["AI"],
    )


class SemanticEligibilityTest(unittest.TestCase):
    def test_includes_narrative_semantic_categories(self) -> None:
        examples = [
            ("Learning outcomes", "program_handbook", SemanticCategory.LEARNING_OUTCOMES),
            ("Career options", "program_handbook", SemanticCategory.CAREER_OUTCOMES),
            ("Academic advice", "program_handbook", SemanticCategory.ACADEMIC_ADVICE),
            ("Program overview", "program_handbook", SemanticCategory.PROGRAM_DESCRIPTION),
            ("Course synopsis", "unit_handbook", SemanticCategory.COURSE_DESCRIPTION),
            ("Admission guidance", "program_handbook", SemanticCategory.ELIGIBILITY_GUIDANCE),
            ("AI specialisation", "program_handbook", SemanticCategory.SPECIALISATION_DESCRIPTION),
            ("Visa conditions", "visa_policy", SemanticCategory.POLICY_GUIDANCE),
            ("Frequently asked questions", "faq", SemanticCategory.FAQ_EXPLANATION),
        ]

        for heading, source_type, expected in examples:
            with self.subTest(heading=heading):
                result = classify_semantic_eligibility(
                    make_chunk(heading=heading, source_type=source_type)
                )
                self.assertTrue(result.eligible)
                self.assertEqual(result.category, expected)

    def test_excludes_exact_or_low_semantic_value_content(self) -> None:
        examples = [
            ("Requirements", "FIT9136", "short_metadata_only"),
            (
                "Handbook",
                "View full page and select the relevant year of handbook information.",
                "navigation_boilerplate",
            ),
            (
                "Course table",
                "Unit | Credit points | Period | Prerequisite\n"
                "FIT9136 | 6 | S2 | FIT9132\nFIT5145 | 6 | S1 | FIT9136",
                "structured_table",
            ),
            (
                "Prerequisites",
                "Students must complete FIT9132, FIT9136 and FIT5145 before "
                "enrolling in FIT5211. These exact course codes define the "
                "prerequisite list for this unit and are maintained as rules.",
                "prerequisite_code_list",
            ),
            (
                "Teaching period availability",
                "This unit is listed for Semester 1, Semester 2 and the summer "
                "teaching period. The authoritative offering table records the "
                "exact campus and year for every scheduled delivery.",
                "teaching_period_table",
            ),
            (
                "Credit requirements",
                "Students complete 96 credit points: 24 foundation points, 48 "
                "core points, 12 capstone points and 12 elective points for the "
                "award. These numeric totals are exact program requirements.",
                "exact_numeric_requirement",
            ),
        ]

        for heading, content, expected_reason in examples:
            with self.subTest(reason=expected_reason):
                result = classify_semantic_eligibility(
                    make_chunk(content=content, heading=heading)
                )
                self.assertFalse(result.eligible)
                self.assertEqual(result.skip_reason, expected_reason)

    def test_embedding_text_is_stable_deduplicated_and_metadata_free(self) -> None:
        chunk = make_chunk(
            heading="Master of Information Technology",
            content="  Students   develop practical computing skills.  ",
        )

        text = semantic_embedding_text(chunk)

        self.assertEqual(
            text,
            "Master of Information Technology\n"
            "Students develop practical computing skills.",
        )
        self.assertNotIn(chunk.source_url, text)
        self.assertEqual(chunk.embedding_text, text)

    def test_incremental_plan_handles_all_eligibility_transitions(self) -> None:
        old = [
            make_chunk(chunk_id="unchanged"),
            make_chunk(chunk_id="edited", content="Before. " * 30),
            make_chunk(chunk_id="excluded-now", content="Useful advice. " * 20),
            make_chunk(chunk_id="included-now", content="FIT9136"),
        ]
        previous = plan_incremental_index(
            [chunk for chunk in old if should_embed(chunk)],
            IndexState.empty(),
        ).next_state
        current = [
            make_chunk(chunk_id="unchanged", source_hash="source-v2"),
            make_chunk(
                chunk_id="edited",
                content="After changed guidance. " * 20,
                source_hash="source-v2",
            ),
            make_chunk(
                chunk_id="excluded-now",
                content="FIT9136",
                source_hash="source-v2",
            ),
            make_chunk(
                chunk_id="included-now",
                content="New explanatory guidance for students. " * 12,
                source_hash="source-v2",
            ),
        ]

        plan = plan_incremental_index(
            [chunk for chunk in current if should_embed(chunk)],
            previous,
        )

        self.assertEqual(
            {chunk.chunk_id for chunk in plan.upsert_chunks},
            {"edited", "included-now"},
        )
        self.assertEqual(plan.delete_chunk_ids, ("excluded-now",))


class DenseResultContractTest(unittest.TestCase):
    def test_scope_is_propagated_and_result_is_resolved_from_canonical_chunk(
        self,
    ) -> None:
        canonical = make_chunk()

        class Embedder:
            dimension = 3

            def encode(self, texts):
                return [[0.1, 0.2, 0.3] for _ in texts]

        class Client:
            def search(self, **kwargs):
                self.kwargs = kwargs
                return [[{
                    "distance": 0.87,
                    "entity": {
                        "chunk_id": canonical.chunk_id,
                        "parent_id": canonical.parent_id,
                        "source_id": canonical.source_id,
                        "university_id": "monash",
                        "handbook_year": 2026,
                        "program_code": "C6001",
                        "program_codes": "|C6001|",
                        "specialisation_codes": "|AI|",
                        "discipline_ids": "computing",
                        "source_type": "program_handbook",
                        "semantic_category": "program_description",
                    },
                }]]

        client = Client()
        store = CampusPilotMilvusStore(
            uri="http://milvus:19530",
            collection_name="semantic",
            embedder=Embedder(),
            client=client,
            canonical_chunks=[canonical],
        )

        result = store.retrieve(
            RetrievalRequest(
                "career-ready technology degree",
                RetrievalScope(
                    university_id="monash",
                    handbook_year=2026,
                    program_code="C6001",
                    specialisation_code="AI",
                ),
                3,
            )
        )

        self.assertIn('university_id == "monash"', client.kwargs["filter"])
        self.assertIn('%|AI|%', client.kwargs["filter"])
        self.assertEqual(result[0]["rank"], 1)
        self.assertEqual(result[0]["dense_score"], 0.87)
        self.assertEqual(result[0]["content"], canonical.content)
        self.assertEqual(result[0]["program_codes"], ["C6001"])

    def test_milvus_failure_degrades_to_lexical_without_dense_evidence(self) -> None:
        chunk = make_chunk()

        class UnavailableMilvus:
            def search(self, query, **kwargs):
                raise ConnectionError("milvus unavailable")

        retriever = CampusPilotHybridRetriever(
            chunks=[chunk],
            vector_store=UnavailableMilvus(),
        )
        lexical_result = {
            **chunk.to_dict(),
            "document_id": chunk.chunk_id,
            "bm25_score": 1.0,
        }
        retriever._lexical_search = (  # type: ignore[method-assign]
            lambda *args, **kwargs: [lexical_result]
        )
        results = retriever.search("advanced computing knowledge", k=1)

        self.assertEqual(results[0]["retrieval_channels"], ["bm25"])
        self.assertNotIn("dense_score", results[0])
        self.assertTrue(retriever.last_search_diagnostics["degraded"])
        self.assertEqual(
            retriever.last_search_diagnostics["dense_error"],
            "ConnectionError",
        )


if __name__ == "__main__":
    unittest.main()
