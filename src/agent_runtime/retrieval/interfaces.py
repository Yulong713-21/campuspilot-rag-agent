"""Storage-neutral contracts shared by the retrieval implementations.

The orchestration layer can swap local test adapters for Elasticsearch or
Milvus without changing API callers.
"""

from __future__ import annotations

from typing import Any, Protocol


class LexicalRetriever(Protocol):
    """Contract for metadata-aware lexical Handbook retrieval."""

    def search(
        self,
        query: str,
        *,
        handbook_year: int | None = None,
        university_id: str | None = None,
        discipline_id: str | None = None,
        program_code: str | None = None,
        source_type: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]: ...


class DenseRetriever(Protocol):
    """Contract for metadata-aware dense Handbook retrieval."""

    def search(
        self,
        query: str,
        *,
        handbook_year: int | None = None,
        university_id: str | None = None,
        discipline_id: str | None = None,
        program_code: str | None = None,
        source_type: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]: ...
