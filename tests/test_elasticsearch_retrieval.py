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
    ElasticsearchHandbookStore,
    FallbackLexicalRetriever,
    HANDBOOK_INDEX_MAPPINGS,
    HANDBOOK_INDEX_SETTINGS,
    InMemoryBM25Retriever,
)


def handbook_chunk() -> HandbookChunk:
    return HandbookChunk(
        chunk_id="fit9136-chunk",
        parent_id="fit9136-parent",
        source_id="MONASH-FIT9136-2026",
        university_id="monash",
        handbook_year=2026,
        program_code="C6001",
        program_codes=["C6001"],
        source_type="unit_handbook",
        discipline_ids=["computing"],
        title="FIT9136 Introduction to Python programming",
        heading="Availability and prerequisites",
        content="FIT9136 is offered in Semester 1 and Semester 2.",
        parent_content="Official Handbook evidence for FIT9136.",
        source_url="https://handbook.monash.edu/2026/units/FIT9136",
        source_sha256="abc",
    )


def fallback_corpus() -> list[HandbookChunk]:
    target = handbook_chunk()
    return [
        target,
        HandbookChunk(
            **{
                **target.to_dict(),
                "chunk_id": "unrelated-one",
                "parent_id": "unrelated-parent-one",
                "source_id": "MONASH-OTHER1000-2026",
                "title": "Database systems",
                "content": "Relational algebra and transactions.",
            }
        ),
        HandbookChunk(
            **{
                **target.to_dict(),
                "chunk_id": "unrelated-two",
                "parent_id": "unrelated-parent-two",
                "source_id": "MONASH-OTHER2000-2026",
                "title": "Computer networks",
                "content": "Routing and network protocols.",
            }
        ),
    ]


class FakeIndices:
    def __init__(self) -> None:
        self.created: dict | None = None
        self.deleted = False

    def exists(self, *, index: str) -> bool:
        return self.created is not None

    def delete(self, *, index: str) -> None:
        self.deleted = True
        self.created = None

    def create(self, **kwargs) -> None:
        self.created = kwargs


class FakeElasticsearchClient:
    def __init__(self) -> None:
        self.indices = FakeIndices()
        self.search_request: dict | None = None

    def info(self) -> dict:
        return {"version": {"number": "9.0.0"}}

    def search(self, **kwargs) -> dict:
        self.search_request = kwargs
        source = ElasticsearchHandbookStore.document(handbook_chunk())
        return {"hits": {"hits": [{"_id": "fit9136-chunk", "_score": 8.25, "_source": source}]}}


class ElasticsearchRetrievalTest(unittest.TestCase):
    def test_mapping_uses_text_for_bm25_and_keywords_for_filters(self) -> None:
        properties = HANDBOOK_INDEX_MAPPINGS["properties"]
        self.assertEqual(properties["content"]["type"], "text")
        self.assertEqual(properties["handbook_year"]["type"], "integer")
        self.assertEqual(properties["program_codes"]["type"], "keyword")
        self.assertEqual(properties["identifiers"]["type"], "keyword")

    def test_recreate_index_applies_strict_handbook_mapping(self) -> None:
        client = FakeElasticsearchClient()
        store = ElasticsearchHandbookStore(
            url="http://unused",
            index_name="handbook-test",
            client=client,
        )

        store.recreate_index()

        self.assertEqual(client.indices.created["index"], "handbook-test")
        self.assertEqual(
            client.indices.created["mappings"],
            HANDBOOK_INDEX_MAPPINGS,
        )
        self.assertEqual(
            client.indices.created["settings"],
            HANDBOOK_INDEX_SETTINGS,
        )

    def test_search_boosts_exact_unit_code_and_applies_metadata_filters(self) -> None:
        client = FakeElasticsearchClient()
        client.indices.created = {"index": "handbook-test"}
        store = ElasticsearchHandbookStore(
            url="http://unused",
            index_name="handbook-test",
            client=client,
        )

        results = store.search(
            "Can I take FIT9136 in Semester 2?",
            handbook_year=2026,
            university_id="monash",
            discipline_id="computing",
            program_code="C6001",
            candidate_course_codes=("FIT9136",),
            candidate_program_codes=("C6001",),
            candidate_specialisation_codes=("AI",),
            source_type="unit_handbook",
            k=3,
        )

        bool_query = client.search_request["query"]["bool"]
        exact_code_clause = bool_query["should"][0]
        self.assertEqual(
            exact_code_clause,
            {"term": {"identifiers": {"value": "FIT9136", "boost": 15.0}}},
        )
        self.assertIn({"term": {"handbook_year": 2026}}, bool_query["filter"])
        self.assertIn(
            {"term": {"source_type": "unit_handbook"}},
            bool_query["filter"],
        )
        self.assertIn(
            {"terms": {"identifiers": ["FIT9136"]}},
            bool_query["filter"],
        )
        self.assertIn(
            {"terms": {"specialisation_codes": ["AI"]}},
            bool_query["filter"],
        )
        self.assertEqual(results[0]["document_id"], "fit9136-chunk")
        self.assertEqual(results[0]["bm25_score"], 8.25)
        self.assertEqual(results[0]["discipline_ids"], "computing")

    def test_request_time_elasticsearch_failure_falls_back_to_memory(self) -> None:
        class FailingRetriever:
            def search(self, query: str, **kwargs):
                raise ConnectionError("elasticsearch unavailable")

        retriever = FallbackLexicalRetriever(
            FailingRetriever(),
            InMemoryBM25Retriever(fallback_corpus()),
        )

        results = retriever.search("FIT9136 Semester 2", k=3)

        self.assertEqual(results[0]["chunk_id"], "fit9136-chunk")
        self.assertEqual(retriever.last_error, "ConnectionError")


if __name__ == "__main__":
    unittest.main()
