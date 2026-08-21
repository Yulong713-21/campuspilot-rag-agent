from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.tools import EduRAGTools


class FakeDocument:
    def __init__(self) -> None:
        self.page_content = "rag context"
        self.metadata = {"source": "ai"}


class FakeVectorStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def hybrid_search_with_rerank(self, query: str, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return [FakeDocument()]


class EduRAGToolsTest(unittest.TestCase):
    def test_search_rag_forwards_timeout_to_runtime_vector_store(self) -> None:
        vector_store = FakeVectorStore()
        tools = object.__new__(EduRAGTools)
        tools._vector_store = vector_store

        result = tools.search_rag(
            "课程有哪些阶段？",
            source_filter="ai",
            k=3,
            timeout_seconds=2.5,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            vector_store.calls,
            [
                {
                    "query": "课程有哪些阶段？",
                    "k": 3,
                    "source_filter": "ai",
                    "timeout_seconds": 2.5,
                }
            ],
        )

    def test_search_rag_rejects_negative_timeout(self) -> None:
        tools = object.__new__(EduRAGTools)

        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            tools.search_rag("query", timeout_seconds=-0.1)


if __name__ == "__main__":
    unittest.main()
