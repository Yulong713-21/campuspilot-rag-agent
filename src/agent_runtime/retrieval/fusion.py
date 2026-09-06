"""Backend-neutral evidence normalization and rank-only fusion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from ..handbook_vector import HandbookChunk


CHANNEL_SCORE_FIELDS = {
    "bm25": ("lexical_score", "bm25_score"),
    "dense": ("dense_score",),
}
CORE_FIELDS = {
    "chunk_id",
    "document_id",
    "parent_id",
    "source_id",
    "rank",
    "retrieval_channels",
    "lexical_score",
    "bm25_score",
    "dense_score",
    "title",
    "heading",
    "content",
    "parent_content",
    "source_url",
}


@dataclass(frozen=True)
class EvidenceHit:
    """One resolved evidence hit independent of ES or Milvus SDK types."""

    chunk_id: str
    parent_id: str
    source_id: str
    rank: int
    retrieval_channels: tuple[str, ...]
    title: str
    heading: str
    content: str
    parent_content: str
    source_url: str
    lexical_score: float | None = None
    dense_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable internal representation used by fusion."""

        result = {
            **self.metadata,
            "chunk_id": self.chunk_id,
            "document_id": self.chunk_id,
            "parent_id": self.parent_id,
            "source_id": self.source_id,
            "rank": self.rank,
            "retrieval_channels": list(self.retrieval_channels),
            "title": self.title,
            "heading": self.heading,
            "content": self.content,
            "parent_content": self.parent_content,
            "source_url": self.source_url,
            "metadata": dict(self.metadata),
        }
        if self.lexical_score is not None:
            result["lexical_score"] = self.lexical_score
            result["bm25_score"] = self.lexical_score
        if self.dense_score is not None:
            result["dense_score"] = self.dense_score
        return result


def normalize_evidence_hits(
    hits: Iterable[Mapping[str, Any]],
    *,
    channel: str,
    canonical_chunks: Mapping[str, HandbookChunk],
) -> tuple[list[EvidenceHit], int]:
    """Resolve raw channel hits and discard incomplete evidence safely.

    Dense storage intentionally contains no canonical Handbook text, so every
    dense hit must resolve through the canonical chunk corpus. Lexical hits may
    already be canonical documents returned by Elasticsearch.
    """

    normalized: list[EvidenceHit] = []
    unresolved = 0
    for rank, raw_hit in enumerate(hits, start=1):
        item = dict(raw_hit)
        chunk_id = str(item.get("chunk_id") or item.get("document_id") or "")
        canonical = canonical_chunks.get(chunk_id)
        if channel == "dense" and canonical is None:
            unresolved += 1
            continue
        canonical_document = canonical.to_dict() if canonical is not None else {}
        document = {**item, **canonical_document}
        if not all(
            (
                chunk_id,
                document.get("parent_id"),
                document.get("source_id"),
                document.get("content"),
            )
        ):
            unresolved += 1
            continue
        score = None
        for name in CHANNEL_SCORE_FIELDS[channel]:
            if item.get(name) is None:
                continue
            try:
                score = float(item[name])
            except (TypeError, ValueError):
                # Raw scores are optional observability fields; rank fusion
                # must not fail because a backend omitted or malformed one.
                continue
            break
        metadata = {
            key: value
            for key, value in document.items()
            if key not in CORE_FIELDS
        }
        normalized.append(
            EvidenceHit(
                chunk_id=chunk_id,
                parent_id=str(document["parent_id"]),
                source_id=str(document["source_id"]),
                rank=rank,
                retrieval_channels=(channel,),
                lexical_score=score if channel == "bm25" else None,
                dense_score=score if channel == "dense" else None,
                title=str(document.get("title") or ""),
                heading=str(document.get("heading") or ""),
                content=str(document["content"]),
                parent_content=str(
                    document.get("parent_content") or document["content"]
                ),
                source_url=str(document.get("source_url") or ""),
                metadata=metadata,
            )
        )
    return normalized, unresolved


def reciprocal_rank_fuse(
    channel_results: Iterable[tuple[str, list[EvidenceHit]]],
    *,
    rrf_constant: int,
) -> list[dict[str, Any]]:
    """Fuse evidence using channel rank positions and no raw-score mixing."""

    fused: dict[str, dict[str, Any]] = {}
    for channel, results in channel_results:
        for hit in results:
            record = fused.setdefault(
                hit.chunk_id,
                {
                    **hit.to_dict(),
                    "retrieval_channels": [],
                    "channel_ranks": {},
                    "rrf_score": 0.0,
                },
            )
            record["retrieval_channels"].append(channel)
            record["channel_ranks"][channel] = hit.rank
            record["rrf_score"] += 1 / (rrf_constant + hit.rank)
            if hit.lexical_score is not None:
                record["lexical_score"] = hit.lexical_score
                record["bm25_score"] = hit.lexical_score
            if hit.dense_score is not None:
                record["dense_score"] = hit.dense_score

    ranked = sorted(
        fused.values(),
        key=lambda item: (
            -item["rrf_score"],
            min(item["channel_ranks"].values()),
            item["chunk_id"],
        ),
    )
    for fusion_rank, item in enumerate(ranked, start=1):
        item["fusion_rank"] = fusion_rank
    return ranked


def deduplicate_parents(
    ranked: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the strongest child and merge sibling channel provenance."""

    selected: list[dict[str, Any]] = []
    by_parent: dict[str, dict[str, Any]] = {}
    for item in ranked:
        parent_id = str(item.get("parent_id") or item["chunk_id"])
        representative = by_parent.get(parent_id)
        if representative is None:
            representative = {**item}
            representative["retrieval_channels"] = list(
                item["retrieval_channels"]
            )
            by_parent[parent_id] = representative
            selected.append(representative)
            continue
        representative["retrieval_channels"] = list(
            dict.fromkeys(
                [
                    *representative["retrieval_channels"],
                    *item["retrieval_channels"],
                ]
            )
        )
    return selected


def build_evidence_package(item: Mapping[str, Any]) -> dict[str, Any]:
    """Build the backend-neutral evidence contract consumed by agents."""

    package = dict(item)
    package["document_id"] = package["chunk_id"]
    package["matched_content"] = package["content"]
    package["content"] = package.get("parent_content") or package["content"]
    package["score"] = round(float(package["rrf_score"]), 6)
    package.setdefault("rerank_rank", None)
    return package
