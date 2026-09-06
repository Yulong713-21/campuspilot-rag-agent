"""Rank fusion and optional cross-encoder reranking for Handbook evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .interfaces import DenseRetriever, LexicalRetriever, RetrievalRequest
from .lexical import InMemoryBM25Retriever

if TYPE_CHECKING:
    from ..handbook_vector import HandbookChunk


class SentenceTransformerReranker:
    """Cross-encoder adapter applied only to the fused candidate set."""
    def __init__(self, model_path: str | Path) -> None:
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(str(model_path), device="cpu")

    def rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not documents:
            return []
        scores = self.model.predict(
            [
                (
                    query,
                    str(
                        item.get("content")
                        or item.get("parent_content")
                        or ""
                    ),
                )
                for item in documents
            ],
            show_progress_bar=False,
        )
        reranked = [
            {**item, "rerank_score": round(float(score), 6)}
            for item, score in zip(documents, scores, strict=True)
        ]
        reranked.sort(key=lambda item: item["rerank_score"], reverse=True)
        return reranked


class CampusPilotHybridRetriever:
    """Fuses lexical and dense retrieval with reciprocal ranks."""

    def __init__(
        self,
        *,
        chunks: list[HandbookChunk],
        vector_store: DenseRetriever | None,
        reranker: Any | None = None,
        rrf_constant: int = 60,
        lexical_retriever: LexicalRetriever | None = None,
    ) -> None:
        self.chunks = chunks
        self.vector_store = vector_store
        self.reranker = reranker
        self.rrf_constant = rrf_constant
        self.last_search_diagnostics: dict[str, Any] = {}
        self.lexical_retriever = (
            lexical_retriever or InMemoryBM25Retriever(chunks)
        )

        # Preserve the attributes exposed by the original implementation.
        self._tokenized = getattr(self.lexical_retriever, "_tokenized", [])
        self._bm25 = getattr(self.lexical_retriever, "_bm25", None)

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
        use_lexical: bool = True,
        use_semantic: bool | None = None,
        k: int = 3,
    ) -> list[dict[str, Any]]:
        semantic_requested = (
            self.vector_store is not None
            if use_semantic is None
            else use_semantic
        )
        # Over-fetch so RRF and parent deduplication can still return a diverse
        # final set after adjacent child chunks collapse to one parent.
        candidate_k = max(k * 4, 12)
        lexical = (
            self._lexical_search(
                query,
                handbook_year=handbook_year,
                university_id=university_id,
                discipline_id=discipline_id,
                program_code=program_code,
                specialisation_code=specialisation_code,
                candidate_course_codes=candidate_course_codes,
                candidate_program_codes=candidate_program_codes,
                candidate_specialisation_codes=(
                    candidate_specialisation_codes
                ),
                source_type=source_type,
                k=candidate_k,
            )
            if use_lexical
            else []
        )
        lexical_error = (
            getattr(self.lexical_retriever, "last_error", None)
            if use_lexical
            else None
        )
        dense_error = (
            "Unavailable"
            if semantic_requested and self.vector_store is None
            else None
        )
        dense: list[dict[str, Any]] = []
        if semantic_requested and self.vector_store is not None:
            try:
                dense = self.vector_store.search(
                    query,
                    handbook_year=handbook_year,
                    university_id=university_id,
                    discipline_id=discipline_id,
                    program_code=program_code,
                    specialisation_code=specialisation_code,
                    candidate_course_codes=candidate_course_codes,
                    candidate_program_codes=candidate_program_codes,
                    candidate_specialisation_codes=(
                        candidate_specialisation_codes
                    ),
                    source_type=source_type,
                    k=candidate_k,
                )
            except Exception as exc:
                dense_error = type(exc).__name__
        self.last_search_diagnostics = {
            "bm25_count": len(lexical),
            "dense_count": len(dense),
            "dense_error": dense_error,
            "lexical_error": lexical_error,
            "degraded": (
                lexical_error is not None
                or (
                    semantic_requested and dense_error is not None
                )
            ),
            "lexical_requested": use_lexical,
            "semantic_requested": semantic_requested,
        }
        # PostgreSQL facts never enter RRF. This map combines evidence rankings
        # only: lexical BM25 and optional dense semantic retrieval.
        fused: dict[str, dict[str, Any]] = {}
        program_scope_query = self._is_program_scope_query(query)
        query_identifiers = set(
            re.findall(r"\b[A-Z]{3}\d{4}\b", query.upper())
        )
        for channel, results in (("bm25", lexical), ("dense", dense)):
            for rank, item in enumerate(results, start=1):
                chunk_id = item["chunk_id"]
                record = fused.setdefault(
                    chunk_id,
                    {
                        **item,
                        "retrieval_channels": [],
                        "rrf_score": 0.0,
                    },
                )
                record["retrieval_channels"].append(channel)
                record["rrf_score"] += 1 / (self.rrf_constant + rank)
                if "bm25_score" in item:
                    record["bm25_score"] = item["bm25_score"]
                if "dense_score" in item:
                    record["dense_score"] = item["dense_score"]

        if program_scope_query:
            for record in fused.values():
                if record.get("source_type") == "program_handbook":
                    record["scope_bonus"] = 0.01
                    record["rrf_score"] += record["scope_bonus"]
        if query_identifiers:
            for record in fused.values():
                searchable_identity = (
                    f"{record.get('source_id', '')} "
                    f"{record.get('title', '')}"
                ).upper()
                if any(
                    identifier in searchable_identity
                    for identifier in query_identifiers
                ):
                    record["identifier_bonus"] = 0.02
                    record["rrf_score"] += record["identifier_bonus"]

        ranked = sorted(
            fused.values(),
            key=lambda item: (
                item["rrf_score"],
                item.get("dense_score", float("-inf")),
            ),
            reverse=True,
        )
        reranker_error = None
        if self.reranker is not None:
            try:
                ranked = self._blend_reranker_rank(
                    self.reranker.rerank(query, ranked),
                    rrf_constant=self.rrf_constant,
                )
            except Exception as exc:
                reranker_error = type(exc).__name__
        self.last_search_diagnostics["reranker_active"] = (
            self.reranker is not None
        )
        self.last_search_diagnostics["reranker_error"] = reranker_error
        self.last_search_diagnostics["degraded"] = (
            self.last_search_diagnostics["degraded"]
            or reranker_error is not None
        )
        # Child chunks improve recall, but only one result per parent is useful
        # to the explanation layer and evidence UI.
        selected: list[dict[str, Any]] = []
        seen_parents: set[str] = set()
        for item in ranked:
            parent_id = item["parent_id"]
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            selected.append(
                {
                    **item,
                    "document_id": item["chunk_id"],
                    "score": round(item["rrf_score"], 6),
                    "content": item["parent_content"],
                }
            )
            if len(selected) >= k:
                break
        return selected

    def retrieve(self, request: RetrievalRequest) -> list[dict[str, Any]]:
        """Execute a storage-independent request after scope resolution."""

        return self.search(
            request.query,
            **request.to_search_kwargs(),
            use_lexical=(
                request.plan.use_lexical if request.plan else True
            ),
            use_semantic=(
                request.plan.use_semantic if request.plan else True
            ),
            k=request.k,
        )

    def _lexical_search(
        self,
        query: str,
        *,
        handbook_year: int | None,
        university_id: str | None,
        discipline_id: str | None,
        program_code: str | None,
        specialisation_code: str | None = None,
        candidate_course_codes: tuple[str, ...] = (),
        candidate_program_codes: tuple[str, ...] = (),
        candidate_specialisation_codes: tuple[str, ...] = (),
        source_type: str | None = None,
        k: int,
    ) -> list[dict[str, Any]]:
        return self.lexical_retriever.search(
            query,
            handbook_year=handbook_year,
            university_id=university_id,
            discipline_id=discipline_id,
            program_code=program_code,
            specialisation_code=specialisation_code,
            candidate_course_codes=candidate_course_codes,
            candidate_program_codes=candidate_program_codes,
            candidate_specialisation_codes=(
                candidate_specialisation_codes
            ),
            source_type=source_type,
            k=k,
        )

    @staticmethod
    def _blend_reranker_rank(
        reranked: list[dict[str, Any]],
        *,
        rrf_constant: int,
    ) -> list[dict[str, Any]]:
        for rank, item in enumerate(reranked, start=1):
            item["reranker_rrf_score"] = 1 / (rrf_constant + rank)
            item["rrf_score"] += item["reranker_rrf_score"]
        return sorted(
            reranked,
            key=lambda item: (
                item["rrf_score"],
                item.get("rerank_score", float("-inf")),
            ),
            reverse=True,
        )

    @staticmethod
    def _is_program_scope_query(query: str) -> bool:
        normalized = query.lower()
        return any(
            marker in normalized
            for marker in (
                "course structure",
                "program structure",
                "degree requirement",
                "credit requirement",
                "specialisation",
                "specialization",
                "项目结构",
                "培养方案",
                "毕业要求",
                "专业方向",
            )
        )

    @staticmethod
    def _matches(
        chunk: HandbookChunk,
        *,
        handbook_year: int | None,
        university_id: str | None,
        discipline_id: str | None,
        program_code: str | None,
        specialisation_code: str | None = None,
        candidate_course_codes: tuple[str, ...] = (),
        candidate_program_codes: tuple[str, ...] = (),
        candidate_specialisation_codes: tuple[str, ...] = (),
        source_type: str | None = None,
    ) -> bool:
        return InMemoryBM25Retriever.matches(
            chunk,
            handbook_year=handbook_year,
            university_id=university_id,
            discipline_id=discipline_id,
            program_code=program_code,
            specialisation_code=specialisation_code,
            candidate_course_codes=candidate_course_codes,
            candidate_program_codes=candidate_program_codes,
            candidate_specialisation_codes=(
                candidate_specialisation_codes
            ),
            source_type=source_type,
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return InMemoryBM25Retriever.tokenize(text)
