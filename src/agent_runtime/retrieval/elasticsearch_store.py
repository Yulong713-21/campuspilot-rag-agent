"""Elasticsearch BM25 index for canonical Handbook lexical evidence."""

from __future__ import annotations

import re
from typing import Any, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..handbook_vector import HandbookChunk


# Strict mappings expose corpus/schema drift during indexing instead of
# silently creating fields with unsuitable analyzers or numeric types.
HANDBOOK_INDEX_MAPPINGS: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "chunk_id": {"type": "keyword"},
        "parent_id": {"type": "keyword"},
        "source_id": {"type": "keyword"},
        "university_id": {"type": "keyword"},
        "handbook_year": {"type": "integer"},
        "program_code": {"type": "keyword"},
        "program_codes": {"type": "keyword"},
        "discipline_ids": {"type": "keyword"},
        "specialisation_codes": {"type": "keyword"},
        "source_type": {"type": "keyword"},
        "identifiers": {"type": "keyword"},
        "title": {
            "type": "text",
            "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
        },
        "heading": {"type": "text"},
        "content": {"type": "text"},
        "parent_content": {"type": "text"},
        "source_url": {"type": "keyword", "ignore_above": 2048},
        "source_sha256": {"type": "keyword"},
    },
}

HANDBOOK_INDEX_SETTINGS: dict[str, Any] = {
    "similarity": {"default": {"type": "BM25"}},
}

# Covers common program/unit codes such as C6001, FIT9136, and COMP9021 while
# avoiding ordinary words and standalone years.
IDENTIFIER_PATTERN = re.compile(r"\b[A-Z]{1,4}\d{4}\b")


class ElasticsearchHandbookStore:
    """Elasticsearch-backed lexical evidence retrieval for Handbook chunks."""

    def __init__(
        self,
        *,
        url: str,
        index_name: str,
        client: Any | None = None,
        request_timeout: float = 3.0,
    ) -> None:
        if client is None:
            from elasticsearch import Elasticsearch

            client = Elasticsearch(
                url,
                request_timeout=request_timeout,
                max_retries=0,
            )
        self.client = client
        self.index_name = index_name

    def ensure_ready(self) -> None:
        """Verify both the cluster and configured published index."""
        self.client.info()
        if not self.client.indices.exists(index=self.index_name):
            raise RuntimeError(f"Elasticsearch index does not exist: {self.index_name}")

    def recreate_index(self) -> None:
        """Replace the index when publishing a complete chunk corpus."""
        if self.client.indices.exists(index=self.index_name):
            self.client.indices.delete(index=self.index_name)
        self.client.indices.create(
            index=self.index_name,
            settings=HANDBOOK_INDEX_SETTINGS,
            mappings=HANDBOOK_INDEX_MAPPINGS,
        )

    @staticmethod
    def document(chunk: HandbookChunk) -> dict[str, Any]:
        """Convert a shared Handbook chunk into the lexical document schema."""
        source = chunk.to_dict()
        identity_text = " ".join(
            str(source.get(field, ""))
            for field in ("source_id", "program_code", "title", "heading", "content")
        ).upper()
        # Keyword identifiers let exact codes outrank analyzed prose without
        # depending on analyzer-specific token behavior.
        source["identifiers"] = sorted(
            set(IDENTIFIER_PATTERN.findall(identity_text))
        )
        return source

    def bulk_actions(
        self,
        chunks: Iterable[HandbookChunk],
    ) -> Iterable[dict[str, Any]]:
        """Yield idempotent bulk actions keyed by the shared chunk ID."""
        for chunk in chunks:
            yield {
                "_op_type": "index",
                "_index": self.index_name,
                "_id": chunk.chunk_id,
                "_source": self.document(chunk),
            }

    def ingest(
        self,
        chunks: Iterable[HandbookChunk],
        *,
        chunk_size: int = 500,
        refresh: bool = True,
    ) -> int:
        """Bulk-index chunks and return the accepted document count."""
        from elasticsearch.helpers import bulk

        succeeded, _ = bulk(
            self.client,
            self.bulk_actions(chunks),
            chunk_size=chunk_size,
            refresh=refresh,
        )
        return int(succeeded)

    def upsert(self, chunks: list[HandbookChunk]) -> int:
        """Upsert changed chunks using their stable chunk IDs."""

        if not chunks:
            return 0
        return self.ingest(chunks)

    def delete(self, chunk_ids: list[str]) -> int:
        """Delete chunks removed by changed or retired sources."""

        if not chunk_ids:
            return 0
        from elasticsearch.helpers import bulk

        succeeded, _ = bulk(
            self.client,
            (
                {
                    "_op_type": "delete",
                    "_index": self.index_name,
                    "_id": chunk_id,
                }
                for chunk_id in chunk_ids
            ),
            refresh=True,
            raise_on_error=True,
        )
        return int(succeeded)

    def search(
        self,
        query: str,
        *,
        handbook_year: int | None = None,
        university_id: str | None = None,
        discipline_id: str | None = None,
        program_code: str | None = None,
        specialisation_code: str | None = None,
        candidate_course_codes: tuple[str, ...] = (),
        candidate_program_codes: tuple[str, ...] = (),
        candidate_specialisation_codes: tuple[str, ...] = (),
        source_type: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]:
        # Scope clauses are filters rather than scoring terms: they select the
        # catalogue slice without distorting BM25 relevance.
        filters: list[dict[str, Any]] = []
        for field, value in (
            ("handbook_year", handbook_year),
            ("university_id", university_id),
            ("discipline_ids", discipline_id),
            ("source_type", source_type),
            ("specialisation_codes", specialisation_code),
        ):
            if value is not None:
                filters.append({"term": {field: value}})
        if program_code:
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"program_code": program_code.upper()}},
                            {"term": {"program_codes": program_code.upper()}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        if candidate_course_codes:
            filters.append(
                {"terms": {"identifiers": list(candidate_course_codes)}}
            )
        if candidate_program_codes:
            filters.append(
                {
                    "bool": {
                        "should": [
                            {
                                "terms": {
                                    "program_code": list(
                                        candidate_program_codes
                                    )
                                }
                            },
                            {
                                "terms": {
                                    "program_codes": list(
                                        candidate_program_codes
                                    )
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        if candidate_specialisation_codes:
            filters.append(
                {
                    "terms": {
                        "specialisation_codes": list(
                            candidate_specialisation_codes
                        )
                    }
                }
            )

        # Exact identifiers are strongest, followed by title, heading, child
        # content, and finally the broader parent context.
        should: list[dict[str, Any]] = []
        identifiers = sorted(set(IDENTIFIER_PATTERN.findall(query.upper())))
        for identifier in identifiers:
            should.append(
                {
                    "term": {
                        "identifiers": {
                            "value": identifier,
                            "boost": 15.0,
                        }
                    }
                }
            )
        should.append(
            {
                "multi_match": {
                    "query": query,
                    "fields": [
                        "title^6",
                        "heading^3",
                        "content",
                        "parent_content^0.5",
                    ],
                    "type": "best_fields",
                }
            }
        )
        response = self.client.search(
            index=self.index_name,
            size=k,
            query={
                "bool": {
                    "filter": filters,
                    "should": should,
                    "minimum_should_match": 1,
                }
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        results: list[dict[str, Any]] = []
        for hit in hits:
            source = dict(hit.get("_source", {}))
            source.pop("identifiers", None)
            discipline_ids = source.get("discipline_ids", [])
            if isinstance(discipline_ids, list):
                source["discipline_ids"] = "|".join(discipline_ids)
            source["document_id"] = source.get("chunk_id", hit.get("_id"))
            source["bm25_score"] = round(float(hit.get("_score") or 0.0), 6)
            results.append(source)
        return results
