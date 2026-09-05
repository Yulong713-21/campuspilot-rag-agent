"""Source-hash based incremental indexing shared by retrieval backends."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ..handbook_vector import HandbookChunk


class IncrementalIndex(Protocol):
    """Mutation contract implemented by Elasticsearch and Milvus adapters."""

    def upsert(self, chunks: list[HandbookChunk]) -> int: ...

    def delete(self, chunk_ids: list[str]) -> int: ...


@dataclass(frozen=True)
class SourceIndexState:
    source_sha256: str
    chunk_ids: tuple[str, ...]
    chunk_hashes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "chunk_ids": list(self.chunk_ids),
            "chunk_hashes": dict(sorted(self.chunk_hashes.items())),
        }


@dataclass(frozen=True)
class IndexState:
    """Last successfully published source hashes and chunk identities."""

    sources: dict[str, SourceIndexState]

    @classmethod
    def empty(cls) -> IndexState:
        return cls(sources={})

    @classmethod
    def read(cls, path: str | Path) -> IndexState:
        state_path = Path(path)
        if not state_path.exists():
            return cls.empty()
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        return cls(
            sources={
                source_id: SourceIndexState(
                    source_sha256=item["source_sha256"],
                    chunk_ids=tuple(item["chunk_ids"]),
                    chunk_hashes=dict(item.get("chunk_hashes", {})),
                )
                for source_id, item in payload.get("sources", {}).items()
            }
        )

    def write(self, path: str | Path) -> None:
        """Atomically publish state only after backend mutations succeed."""

        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_suffix(state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sources": {
                        source_id: state.to_dict()
                        for source_id, state in sorted(self.sources.items())
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(state_path)


@dataclass(frozen=True)
class IncrementalIndexPlan:
    """Minimal backend mutations required to publish the current corpus."""

    upsert_chunks: tuple[HandbookChunk, ...]
    delete_chunk_ids: tuple[str, ...]
    changed_sources: tuple[str, ...]
    unchanged_sources: tuple[str, ...]
    removed_sources: tuple[str, ...]
    next_state: IndexState


def _effective_source_hash(chunks: list[HandbookChunk]) -> str:
    declared = {chunk.source_sha256 for chunk in chunks if chunk.source_sha256}
    if len(declared) > 1:
        raise ValueError("one source_id contains multiple source_sha256 values")
    if declared:
        return next(iter(declared))
    # Older fixtures may not carry a source hash. A deterministic aggregate
    # retains incremental behavior without treating an empty hash as stable.
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: item.chunk_id):
        digest.update(
            json.dumps(
                chunk.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        )
    return digest.hexdigest()


def _chunk_hash(chunk: HandbookChunk) -> str:
    """Hash indexable chunk content independently of its source snapshot."""

    payload = chunk.to_dict()
    # The source hash is the coarse invalidation signal. Excluding it here
    # prevents an unrelated source edit from rewriting unchanged chunks.
    payload.pop("source_sha256", None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def plan_incremental_index(
    chunks: Iterable[HandbookChunk],
    previous: IndexState,
) -> IncrementalIndexPlan:
    """Compare source hashes and produce changed-only upserts and deletes."""

    grouped: dict[str, list[HandbookChunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.source_id, []).append(chunk)

    upserts: list[HandbookChunk] = []
    deletes: set[str] = set()
    changed: list[str] = []
    unchanged: list[str] = []
    next_sources: dict[str, SourceIndexState] = {}
    for source_id, source_chunks in sorted(grouped.items()):
        source_hash = _effective_source_hash(source_chunks)
        current_ids = tuple(sorted(chunk.chunk_id for chunk in source_chunks))
        current_hashes = {
            chunk.chunk_id: _chunk_hash(chunk) for chunk in source_chunks
        }
        next_sources[source_id] = SourceIndexState(
            source_hash,
            current_ids,
            current_hashes,
        )
        prior = previous.sources.get(source_id)
        if (
            prior is not None
            and prior.source_sha256 == source_hash
            and prior.chunk_ids == current_ids
        ):
            unchanged.append(source_id)
            continue
        changed.append(source_id)
        # State files written before chunk_hashes existed intentionally fall
        # back to one full-source upsert, then become fine-grained thereafter.
        upserts.extend(
            chunk
            for chunk in source_chunks
            if not prior
            or not prior.chunk_hashes
            or prior.chunk_hashes.get(chunk.chunk_id)
            != current_hashes[chunk.chunk_id]
        )
        if prior is not None:
            deletes.update(set(prior.chunk_ids) - set(current_ids))

    removed = sorted(set(previous.sources) - set(grouped))
    for source_id in removed:
        deletes.update(previous.sources[source_id].chunk_ids)

    return IncrementalIndexPlan(
        upsert_chunks=tuple(upserts),
        delete_chunk_ids=tuple(sorted(deletes)),
        changed_sources=tuple(changed),
        unchanged_sources=tuple(unchanged),
        removed_sources=tuple(removed),
        next_state=IndexState(next_sources),
    )


def apply_incremental_plan(
    index: IncrementalIndex,
    plan: IncrementalIndexPlan,
) -> tuple[int, int]:
    """Apply stale deletes before changed-source upserts."""

    deleted = index.delete(list(plan.delete_chunk_ids))
    upserted = index.upsert(list(plan.upsert_chunks))
    return upserted, deleted
