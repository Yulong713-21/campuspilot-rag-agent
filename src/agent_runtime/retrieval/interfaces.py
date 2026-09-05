"""Storage-neutral contracts shared by the retrieval implementations.

The orchestration layer can swap local test adapters for Elasticsearch or
Milvus without changing API callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .scope import RetrievalScope


@dataclass(frozen=True)
class RetrievalRequest:
    """Storage-independent evidence request passed by business code."""

    query: str
    scope: RetrievalScope = field(default_factory=RetrievalScope)
    k: int = 3


class EvidenceRetriever(Protocol):
    """Business-facing retrieval contract independent of ES and Milvus."""

    def retrieve(self, request: RetrievalRequest) -> list[dict[str, Any]]: ...


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
        specialisation_code: str | None = None,
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
        specialisation_code: str | None = None,
        source_type: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]: ...
