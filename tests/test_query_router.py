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
    CandidateConstraints,
    CampusPilotHybridRetriever,
    InMemoryBM25Retriever,
    PlannedEvidenceRetriever,
    QueryRouter,
    RetrievalPlanExecutor,
    RetrievalScope,
    StructuredResolution,
)


class QueryRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def assert_route(
        self,
        query: str,
        expected: tuple[str, ...],
        *,
        scope: RetrievalScope | None = None,
    ) -> None:
        plan = self.router.plan(query, scope or RetrievalScope())
        self.assertEqual(plan.route, expected)

    def test_prerequisite_question_routes_structured_then_lexical(self) -> None:
        self.assert_route(
            "What prerequisites does COMP9021 have?",
            ("structured", "lexical"),
        )

    def test_teaching_period_routes_structured_then_lexical(self) -> None:
        self.assert_route(
            "Is FIT9136 offered in Semester 2?",
            ("structured", "lexical"),
        )

    def test_credit_requirement_routes_structured_then_lexical(self) -> None:
        self.assert_route(
            "How many credit points do I need?",
            ("structured", "lexical"),
        )

    def test_exact_handbook_policy_routes_lexical_only(self) -> None:
        self.assert_route(
            "Show me the official handbook wording for C6001.",
            ("lexical",),
        )

    def test_career_fit_routes_lexical_and_semantic(self) -> None:
        self.assert_route(
            "Which program is the best fit for a cybersecurity career?",
            ("lexical", "semantic"),
        )

    def test_vague_course_recommendation_routes_lexical_and_semantic(self) -> None:
        self.assert_route(
            "Which course is suitable if I want to learn NLP?",
            ("lexical", "semantic"),
        )

    def test_mixed_eligibility_and_preference_uses_all_capabilities(self) -> None:
        plan = self.router.plan(
            "Which AI electives can I take that fit my interest in NLP?",
            RetrievalScope(program_code="C6001"),
        )

        self.assertEqual(
            plan.route,
            ("structured", "lexical", "semantic"),
        )
        self.assertTrue(plan.require_candidate_scope)

    def test_late_withdrawal_meaning_uses_lexical_and_semantic(self) -> None:
        self.assert_route(
            "What does late withdrawal mean?",
            ("lexical", "semantic"),
        )


class PlannedExecutionTest(unittest.TestCase):
    def test_legacy_search_call_is_routed_before_backend_execution(self) -> None:
        class Retriever:
            last_search_diagnostics = {
                "lexical_error": None,
                "dense_error": None,
            }

            def retrieve(self, request):
                self.request = request
                return []

        backend = Retriever()
        planned = PlannedEvidenceRetriever(
            RetrievalPlanExecutor(
                router=QueryRouter(),
                evidence_retriever=backend,
            )
        )

        planned.search(
            "Show the official wording for FIT9136.",
            university_id="monash",
            handbook_year=2026,
        )

        self.assertEqual(backend.request.plan.route, ("lexical",))
        self.assertEqual(backend.request.scope.university_id, "monash")
        self.assertEqual(
            planned.last_search_diagnostics["route"],
            ["lexical"],
        )

    def test_structured_resolution_runs_first_and_constrains_retrieval(self) -> None:
        events: list[str] = []

        class Resolver:
            def resolve(self, query, scope):
                events.append("structured")
                return StructuredResolution(
                    candidates=CandidateConstraints(
                        course_codes=("FIT9136", "FIT5145")
                    ),
                    result={"eligible_course_codes": ["FIT9136", "FIT5145"]},
                )

        class Retriever:
            last_search_diagnostics = {
                "lexical_error": None,
                "dense_error": None,
            }

            def retrieve(self, request):
                events.append("evidence")
                self.request = request
                return [{"chunk_id": "fit9136", "source_id": "official"}]

        retriever = Retriever()
        scope = RetrievalScope(
            university_id="monash",
            program_code="C6001",
            handbook_year=2026,
            specialisation_code="AI",
        )
        result = RetrievalPlanExecutor(
            router=QueryRouter(),
            evidence_retriever=retriever,
            structured_resolver=Resolver(),
        ).execute(
            query=(
                "Which AI electives can I take that fit my interest in NLP?"
            ),
            scope=scope,
        )

        self.assertEqual(events, ["structured", "evidence"])
        self.assertEqual(retriever.request.scope, scope)
        self.assertEqual(
            retriever.request.candidates.course_codes,
            ("FIT9136", "FIT5145"),
        )
        self.assertEqual(result.diagnostics["candidate_count"], 2)
        self.assertTrue(result.diagnostics["structured_used"])

    def test_missing_candidate_scope_skips_global_semantic_retrieval(self) -> None:
        class Retriever:
            last_search_diagnostics = {
                "lexical_error": None,
                "dense_error": None,
            }

            def retrieve(self, request):
                self.request = request
                return []

        retriever = Retriever()
        result = RetrievalPlanExecutor(
            router=QueryRouter(),
            evidence_retriever=retriever,
        ).execute(
            query="Which AI electives fit someone interested in NLP?",
            scope=RetrievalScope(program_code="C6001"),
        )

        self.assertEqual(result.plan.route, ("structured", "lexical"))
        self.assertIn(
            "semantic_skipped_without_candidate_scope",
            result.plan.reasons,
        )
        self.assertFalse(retriever.request.plan.use_semantic)

    def test_candidate_course_codes_restrict_local_retrieval(self) -> None:
        fit9136 = self._chunk("fit9136", "FIT9136 Python programming")
        fit5145 = self._chunk("fit5145", "FIT5145 data science")
        fit5120 = self._chunk("fit5120", "FIT5120 industry studio")
        retriever = InMemoryBM25Retriever([fit9136, fit5145, fit5120])

        results = retriever.search(
            "programming data",
            candidate_course_codes=("FIT9136",),
            k=5,
        )

        self.assertEqual([item["chunk_id"] for item in results], ["fit9136"])

    def test_milvus_unavailable_degrades_to_structured_and_lexical(self) -> None:
        chunk = self._chunk(
            "career",
            "Cybersecurity careers and professional security practice",
        )

        class UnavailableMilvus:
            def search(self, query, **kwargs):
                raise ConnectionError("milvus unavailable")

        hybrid = CampusPilotHybridRetriever(
            chunks=[chunk],
            vector_store=UnavailableMilvus(),
        )
        hybrid._lexical_search = (  # type: ignore[method-assign]
            lambda *args, **kwargs: [
                {
                    **chunk.to_dict(),
                    "document_id": chunk.chunk_id,
                    "bm25_score": 1.0,
                }
            ]
        )
        result = RetrievalPlanExecutor(
            router=QueryRouter(),
            evidence_retriever=hybrid,
        ).execute(
            query="Which program is suitable for a cybersecurity career?",
            scope=RetrievalScope(),
        )

        self.assertTrue(result.diagnostics["lexical_used"])
        self.assertFalse(result.diagnostics["semantic_used"])
        self.assertEqual(
            result.diagnostics["semantic_error"],
            "ConnectionError",
        )
        self.assertEqual(result.documents[0]["retrieval_channels"], ["bm25"])

    def test_all_evidence_failure_preserves_structured_result(self) -> None:
        class Resolver:
            def resolve(self, query, scope):
                return StructuredResolution(
                    result={"is_offered": True, "prerequisites": []}
                )

        class UnavailableEvidence:
            def retrieve(self, request):
                raise ConnectionError("elasticsearch unavailable")

        result = RetrievalPlanExecutor(
            router=QueryRouter(),
            evidence_retriever=UnavailableEvidence(),
            structured_resolver=Resolver(),
        ).execute(
            query="Can I take FIT9136 in Semester 2?",
            scope=RetrievalScope(university_id="monash", handbook_year=2026),
        )

        self.assertEqual(
            result.structured_result,
            {"is_offered": True, "prerequisites": []},
        )
        self.assertEqual(result.documents, ())
        self.assertTrue(result.diagnostics["evidence_unavailable"])
        self.assertEqual(
            result.diagnostics["retrieval_error"],
            "ConnectionError",
        )

    @staticmethod
    def _chunk(chunk_id: str, content: str) -> HandbookChunk:
        return HandbookChunk(
            chunk_id=chunk_id,
            parent_id=f"{chunk_id}-parent",
            source_id=f"monash-{chunk_id}-2026",
            university_id="monash",
            handbook_year=2026,
            program_code="C6001",
            source_type="unit_handbook",
            discipline_ids=["computing"],
            title=content,
            heading="Course description",
            content=content,
            parent_content=content,
            source_url="https://example.edu",
            source_sha256="hash",
            program_codes=["C6001"],
        )


if __name__ == "__main__":
    unittest.main()
