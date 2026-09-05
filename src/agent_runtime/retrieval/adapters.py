"""Business-facing adapters over storage-specific retrieval channels."""

from __future__ import annotations

from typing import Any

from .interfaces import DenseRetriever, LexicalRetriever, RetrievalRequest


class LexicalEvidenceRetriever:
    """Expose a lexical backend through the common evidence interface."""

    def __init__(self, backend: LexicalRetriever) -> None:
        self.backend = backend

    def retrieve(self, request: RetrievalRequest) -> list[dict[str, Any]]:
        return self.backend.search(
            request.query,
            **request.scope.to_search_kwargs(),
            k=request.k,
        )


class SemanticEvidenceRetriever:
    """Expose a dense backend through the common evidence interface."""

    def __init__(self, backend: DenseRetriever) -> None:
        self.backend = backend

    def retrieve(self, request: RetrievalRequest) -> list[dict[str, Any]]:
        return self.backend.search(
            request.query,
            **request.scope.to_search_kwargs(),
            k=request.k,
        )
