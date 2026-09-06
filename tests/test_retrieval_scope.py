from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.retrieval import (  # noqa: E402
    LexicalEvidenceRetriever,
    RetrievalRequest,
    RetrievalScope,
    RetrievalScopeResolver,
)


class RetrievalScopeResolverTest(unittest.TestCase):
    def test_resolves_university_program_and_year_before_retrieval(self) -> None:
        scope = RetrievalScopeResolver().resolve(
            "Show Monash C6001 Handbook evidence for 2026"
        )

        self.assertEqual(scope.university_id, "monash")
        self.assertEqual(scope.program_code, "C6001")
        self.assertEqual(scope.handbook_year, 2026)

    def test_unit_identifier_is_not_misclassified_as_program(self) -> None:
        scope = RetrievalScopeResolver().resolve(
            "Can I take FIT9136 in Semester 2?"
        )

        self.assertIsNone(scope.program_code)

    def test_explicit_scope_wins_over_context_and_query_hints(self) -> None:
        resolver = RetrievalScopeResolver(
            specialisation_aliases={"artificial intelligence": "AI"}
        )
        scope = resolver.resolve(
            "UNSW artificial intelligence 2025",
            explicit=RetrievalScope(
                university_id="monash",
                program_code="c6001",
                handbook_year=2026,
                specialisation_code="cyber",
            ),
            context=RetrievalScope(university_id="anu"),
        )

        self.assertEqual(
            scope,
            RetrievalScope("monash", "C6001", 2026, "CYBER"),
        )

    def test_business_adapter_passes_normalized_scope_to_backend(self) -> None:
        class RecordingBackend:
            def search(self, query: str, **kwargs):
                self.query = query
                self.kwargs = kwargs
                return []

        backend = RecordingBackend()
        adapter = LexicalEvidenceRetriever(backend)
        adapter.retrieve(
            RetrievalRequest(
                "AI electives",
                RetrievalScope(
                    university_id="UNSW",
                    program_code="8543",
                    handbook_year=2026,
                    specialisation_code="compls",
                ),
                4,
            )
        )

        self.assertEqual(backend.query, "AI electives")
        self.assertEqual(backend.kwargs["university_id"], "unsw")
        self.assertEqual(backend.kwargs["specialisation_code"], "COMPLS")
        self.assertEqual(backend.kwargs["k"], 4)


if __name__ == "__main__":
    unittest.main()
