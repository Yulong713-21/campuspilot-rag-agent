from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.handbook_vector import HandbookChunk  # noqa: E402
from agent_runtime.retrieval import (  # noqa: E402
    IndexState,
    SourceIndexState,
    apply_incremental_plan,
    plan_incremental_index,
)


def chunk(
    source_id: str,
    chunk_id: str,
    source_hash: str,
    *,
    content: str = "Content",
) -> HandbookChunk:
    return HandbookChunk(
        chunk_id=chunk_id,
        parent_id=f"{source_id}-parent",
        source_id=source_id,
        university_id="monash",
        handbook_year=2026,
        program_code="C6001",
        source_type="program_handbook",
        discipline_ids=["computing"],
        title="Title",
        heading="Heading",
        content=content,
        parent_content="Parent content",
        source_url="https://example.edu",
        source_sha256=source_hash,
        program_codes=["C6001"],
    )


class IncrementalIndexingTest(unittest.TestCase):
    def test_plans_changed_only_upserts_and_stale_deletes(self) -> None:
        previous = plan_incremental_index(
            [
                chunk("changed", "keep", "old-hash"),
                chunk("changed", "old-1", "old-hash"),
                chunk("same", "same-1", "same-hash"),
                chunk("removed", "gone-1", "gone-hash"),
            ],
            IndexState.empty(),
        ).next_state
        current = [
            chunk("changed", "keep", "new-hash"),
            chunk("changed", "new-1", "new-hash"),
            chunk("same", "same-1", "same-hash"),
        ]

        plan = plan_incremental_index(current, previous)

        self.assertEqual(plan.changed_sources, ("changed",))
        self.assertEqual(plan.unchanged_sources, ("same",))
        self.assertEqual(plan.removed_sources, ("removed",))
        self.assertEqual(plan.delete_chunk_ids, ("gone-1", "old-1"))
        self.assertEqual(
            {item.chunk_id for item in plan.upsert_chunks},
            {"new-1"},
        )

    def test_upserts_only_a_chunk_whose_content_changed(self) -> None:
        previous = plan_incremental_index(
            [
                chunk("source", "stable", "old-hash"),
                chunk("source", "edited", "old-hash", content="Before"),
            ],
            IndexState.empty(),
        ).next_state

        plan = plan_incremental_index(
            [
                chunk("source", "stable", "new-hash"),
                chunk("source", "edited", "new-hash", content="After"),
            ],
            previous,
        )

        self.assertEqual(
            [item.chunk_id for item in plan.upsert_chunks],
            ["edited"],
        )

    def test_old_state_without_chunk_hashes_gets_one_safe_full_upsert(self) -> None:
        previous = IndexState(
            {"source": SourceIndexState("old-hash", ("one", "two"))}
        )

        plan = plan_incremental_index(
            [
                chunk("source", "one", "new-hash"),
                chunk("source", "two", "new-hash"),
            ],
            previous,
        )

        self.assertEqual(len(plan.upsert_chunks), 2)
        self.assertTrue(plan.next_state.sources["source"].chunk_hashes)

    def test_applies_delete_then_upsert_and_persists_next_state(self) -> None:
        events: list[tuple[str, list[str]]] = []

        class FakeIndex:
            def delete(self, chunk_ids):
                events.append(("delete", chunk_ids))
                return len(chunk_ids)

            def upsert(self, chunks):
                events.append(("upsert", [item.chunk_id for item in chunks]))
                return len(chunks)

        plan = plan_incremental_index(
            [chunk("new", "new-1", "hash")],
            IndexState.empty(),
        )
        upserted, deleted = apply_incremental_plan(FakeIndex(), plan)

        self.assertEqual((upserted, deleted), (1, 0))
        self.assertEqual(events[0][0], "delete")
        self.assertEqual(events[1], ("upsert", ["new-1"]))
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state.json"
            plan.next_state.write(path)
            self.assertEqual(IndexState.read(path), plan.next_state)


if __name__ == "__main__":
    unittest.main()
