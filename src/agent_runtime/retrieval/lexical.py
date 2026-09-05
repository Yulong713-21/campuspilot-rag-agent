from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from .interfaces import LexicalRetriever

if TYPE_CHECKING:
    from ..handbook_vector import HandbookChunk


class InMemoryBM25Retriever:
    """Small-corpus BM25 used for tests and local evidence fallback.

    Elasticsearch is the production lexical backend. This implementation is
    retained for local development and temporary Elasticsearch outages.
    """

    def __init__(self, chunks: list[HandbookChunk]) -> None:
        from rank_bm25 import BM25Okapi

        self.chunks = chunks
        self._tokenized = [
            self.tokenize(chunk.embedding_text) for chunk in chunks
        ]
        self._bm25 = BM25Okapi(self._tokenized)

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
    ) -> list[dict[str, Any]]:
        query_tokens = self.tokenize(query)
        # Exact metadata filters should not influence text relevance; otherwise
        # a repeated program code can dominate the BM25 score.
        filter_tokens = {
            item.lower()
            for item in (
                university_id,
                program_code,
                str(handbook_year) if handbook_year is not None else None,
            )
            if item
        }
        query_tokens = [
            token for token in query_tokens if token not in filter_tokens
        ]
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        matches: list[tuple[float, HandbookChunk]] = []
        for chunk, score in zip(self.chunks, scores, strict=True):
            if score <= 0 or not self.matches(
                chunk,
                handbook_year=handbook_year,
                university_id=university_id,
                discipline_id=discipline_id,
                program_code=program_code,
                specialisation_code=specialisation_code,
                source_type=source_type,
            ):
                continue
            matches.append((float(score), chunk))
        matches.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                **chunk.to_dict(),
                "discipline_ids": "|".join(chunk.discipline_ids),
                "document_id": chunk.chunk_id,
                "bm25_score": round(score, 6),
            }
            for score, chunk in matches[:k]
        ]

    @staticmethod
    def matches(
        chunk: HandbookChunk,
        *,
        handbook_year: int | None,
        university_id: str | None,
        discipline_id: str | None,
        program_code: str | None,
        specialisation_code: str | None = None,
        source_type: str | None = None,
    ) -> bool:
        return all(
            (
                handbook_year is None
                or chunk.handbook_year == handbook_year,
                university_id is None
                or chunk.university_id == university_id,
                discipline_id is None
                or discipline_id in chunk.discipline_ids,
                program_code is None
                or program_code in chunk.program_codes
                or chunk.program_code == program_code,
                specialisation_code is None
                or specialisation_code in chunk.specialisation_codes,
                source_type is None or chunk.source_type == source_type,
            )
        )

    @staticmethod
    def tokenize(text: str) -> list[str]:
        normalized = text.lower()
        words = re.findall(r"[a-z0-9]+", normalized)
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
        chinese_tokens = [
            run[index : index + 2]
            for run in chinese_runs
            for index in range(max(len(run) - 1, 1))
        ]
        return words + chinese_tokens


class FallbackLexicalRetriever:
    """Use a secondary lexical index when the primary backend raises.

    `last_error` stores only the exception class so health diagnostics do not
    leak connection strings or infrastructure details.
    """

    def __init__(
        self,
        primary: LexicalRetriever,
        fallback: LexicalRetriever,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.last_error: str | None = None

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
    ) -> list[dict[str, Any]]:
        try:
            results = self.primary.search(
                query,
                handbook_year=handbook_year,
                university_id=university_id,
                discipline_id=discipline_id,
                program_code=program_code,
                specialisation_code=specialisation_code,
                source_type=source_type,
                k=k,
            )
            self.last_error = None
            return results
        except Exception as exc:
            # Evidence retrieval is optional to deterministic planning, so a
            # primary outage should reduce recall rather than fail the request.
            self.last_error = type(exc).__name__
            return self.fallback.search(
                query,
                handbook_year=handbook_year,
                university_id=university_id,
                discipline_id=discipline_id,
                program_code=program_code,
                specialisation_code=specialisation_code,
                source_type=source_type,
                k=k,
            )
