from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import HandbookChunk  # noqa: E402
from agent_runtime.retrieval import (  # noqa: E402
    CampusPilotMilvusStore,
    RetrievalRequest,
    RetrievalScope,
)


TEST_MILVUS_URI = os.environ.get("CAMPUSPILOT_TEST_MILVUS_URI")


@unittest.skipUnless(
    TEST_MILVUS_URI,
    "set CAMPUSPILOT_TEST_MILVUS_URI to run real Milvus integration",
)
class MilvusSemanticIntegrationTest(unittest.TestCase):
    """Exercise the real client only against an explicitly selected endpoint."""

    def test_lightweight_upsert_and_scoped_search(self) -> None:
        class Embedder:
            dimension = 3

            def encode(self, texts):
                return [[1.0, 0.0, 0.0] for _ in texts]

        chunk = HandbookChunk(
            chunk_id="semantic-integration-chunk",
            parent_id="semantic-integration-parent",
            source_id="monash-c6001-2026",
            university_id="monash",
            handbook_year=2026,
            program_code="C6001",
            source_type="program_handbook",
            discipline_ids=["computing"],
            title="Master of Information Technology",
            heading="Learning outcomes",
            content=(
                "Graduates apply advanced computing knowledge to complex "
                "problems and communicate practical recommendations across "
                "professional technology contexts."
            ),
            parent_content="Canonical learning-outcome evidence.",
            source_url="https://example.edu/c6001",
            source_sha256="integration",
            program_codes=["C6001"],
            specialisation_codes=["AI"],
        )
        collection = f"campuspilot_semantic_test_{uuid4().hex}"
        store = CampusPilotMilvusStore(
            uri=str(TEST_MILVUS_URI),
            collection_name=collection,
            embedder=Embedder(),
            canonical_chunks=[chunk],
        )
        try:
            store.recreate_collection()
            self.assertEqual(store.upsert([chunk]), 1)

            results = store.retrieve(
                RetrievalRequest(
                    "skills for complex professional computing problems",
                    RetrievalScope(
                        university_id="monash",
                        handbook_year=2026,
                        program_code="C6001",
                        specialisation_code="AI",
                    ),
                    3,
                )
            )

            self.assertEqual(results[0]["chunk_id"], chunk.chunk_id)
            self.assertEqual(results[0]["content"], chunk.content)
            self.assertEqual(results[0]["rank"], 1)
        finally:
            if store.has_collection():
                store.client.drop_collection(collection)


if __name__ == "__main__":
    unittest.main()
