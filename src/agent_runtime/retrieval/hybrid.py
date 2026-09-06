"""Rank fusion and optional cross-encoder reranking for Handbook evidence."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, TYPE_CHECKING

from .fusion import (
    build_evidence_package,
    deduplicate_parents,
    normalize_evidence_hits,
    reciprocal_rank_fuse,
)
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
        candidate_pool_multiplier: int = 4,
        minimum_candidate_pool: int = 20,
        maximum_candidate_pool: int = 100,
        reranker_candidate_limit: int = 30,
        reranker_requested: bool | None = None,
        reranker_initialization_error: str | None = None,
    ) -> None:
        self.chunks = chunks
        self.vector_store = vector_store
        self.reranker = reranker
        self.reranker_requested = (
            reranker is not None
            if reranker_requested is None
            else reranker_requested
        )
        self.reranker_initialization_error = reranker_initialization_error
        self.rrf_constant = rrf_constant
        self.candidate_pool_multiplier = max(candidate_pool_multiplier, 1)
        self.minimum_candidate_pool = max(minimum_candidate_pool, 1)
        self.maximum_candidate_pool = max(
            maximum_candidate_pool,
            self.minimum_candidate_pool,
        )
        self.reranker_candidate_limit = min(
            max(reranker_candidate_limit, 1),
            50,
        )
        self.canonical_chunks = {chunk.chunk_id: chunk for chunk in chunks}
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
        started = perf_counter()
        semantic_requested = (
            self.vector_store is not None
            if use_semantic is None
            else use_semantic
        )
        candidate_k = min(
            max(k * self.candidate_pool_multiplier, self.minimum_candidate_pool),
            self.maximum_candidate_pool,
        )
        lexical_started = perf_counter()
        lexical: list[dict[str, Any]] = []
        lexical_error = None
        if use_lexical:
            try:
                lexical = self._lexical_search(
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
                lexical_error = getattr(
                    self.lexical_retriever,
                    "last_error",
                    None,
                )
            except Exception as exc:
                lexical_error = type(exc).__name__
        lexical_latency = self._elapsed_ms(lexical_started)

        dense_error = (
            "Unavailable"
            if semantic_requested and self.vector_store is None
            else None
        )
        dense: list[dict[str, Any]] = []
        semantic_started = perf_counter()
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
        semantic_latency = self._elapsed_ms(semantic_started)

        resolution_started = perf_counter()
        normalized_lexical, lexical_unresolved = normalize_evidence_hits(
            lexical,
            channel="bm25",
            canonical_chunks=self.canonical_chunks,
        )
        normalized_dense, dense_unresolved = normalize_evidence_hits(
            dense,
            channel="dense",
            canonical_chunks=self.canonical_chunks,
        )
        resolution_latency = self._elapsed_ms(resolution_started)

        # Only ranked evidence channels enter RRF. Structured PostgreSQL facts
        # remain in RetrievalExecutionResult.structured_result.
        fusion_started = perf_counter()
        ranked = reciprocal_rank_fuse(
            (
                ("bm25", normalized_lexical),
                ("dense", normalized_dense),
            ),
            rrf_constant=self.rrf_constant,
        )
        fusion_latency = self._elapsed_ms(fusion_started)

        rrf_order = [item["chunk_id"] for item in ranked]
        reranker_error = self.reranker_initialization_error
        reranker_used = False
        reranker_started = perf_counter()
        if self.reranker is not None and ranked:
            try:
                ranked = self._rerank_bounded(
                    query,
                    ranked,
                    limit=self.reranker_candidate_limit,
                )
                reranker_used = True
            except Exception as exc:
                reranker_error = type(exc).__name__
                # Preserve the exact pre-reranker RRF order on degradation.
                ranked.sort(key=lambda item: rrf_order.index(item["chunk_id"]))
        reranker_latency = self._elapsed_ms(reranker_started)

        dedup_before_count = len(ranked)
        deduplicated = deduplicate_parents(ranked)
        dedup_after_count = len(deduplicated)
        packages = [
            build_evidence_package(item) for item in deduplicated[:k]
        ]

        unresolved_count = lexical_unresolved + dense_unresolved
        degradation_reasons = [
            reason
            for reason in (
                f"lexical:{lexical_error}" if lexical_error else None,
                f"semantic:{dense_error}" if dense_error else None,
                f"reranker:{reranker_error}" if reranker_error else None,
                (
                    f"evidence_resolution:{unresolved_count}"
                    if unresolved_count
                    else None
                ),
            )
            if reason is not None
        ]
        self.last_search_diagnostics = {
            "lexical_count": len(normalized_lexical),
            "semantic_count": len(normalized_dense),
            "bm25_count": len(normalized_lexical),
            "dense_count": len(normalized_dense),
            "lexical_error": lexical_error,
            "dense_error": dense_error,
            "rrf_candidate_count": (
                len(normalized_lexical) + len(normalized_dense)
            ),
            "rrf_output_count": len(ranked),
            "candidate_pool_size": candidate_k,
            "reranker_requested": self.reranker_requested,
            "reranker_used": reranker_used,
            "reranker_active": self.reranker is not None,
            "reranker_error": reranker_error,
            "reranker_candidate_count": min(
                len(ranked) if self.reranker_requested else 0,
                self.reranker_candidate_limit,
            ),
            "dedup_before_count": dedup_before_count,
            "dedup_after_count": dedup_after_count,
            "unresolved_evidence_count": unresolved_count,
            "lexical_requested": use_lexical,
            "semantic_requested": semantic_requested,
            "hybrid_attempted": use_lexical and semantic_requested,
            "hybrid_contributed": bool(
                normalized_lexical and normalized_dense
            ),
            "degraded": bool(degradation_reasons),
            "degradation_reasons": degradation_reasons,
            "latency_ms": {
                "lexical": lexical_latency,
                "semantic": semantic_latency,
                "fusion": fusion_latency,
                "reranker": reranker_latency,
                "evidence_resolution": resolution_latency,
                "total": self._elapsed_ms(started),
            },
        }
        return packages

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

    def _rerank_bounded(
        self,
        query: str,
        ranked: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fully reorder only the bounded RRF prefix using the cross-encoder."""

        candidates = [{**item} for item in ranked[:limit]]
        reranked = self.reranker.rerank(query, candidates)
        original_by_id = {item["chunk_id"]: item for item in candidates}
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for returned in reranked:
            chunk_id = str(returned.get("chunk_id") or "")
            if chunk_id not in original_by_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            ordered.append({**original_by_id[chunk_id], **returned})
        if not ordered:
            raise ValueError("reranker returned no stable chunk identities")
        ordered.extend(item for item in candidates if item["chunk_id"] not in seen)
        for rerank_rank, item in enumerate(ordered, start=1):
            item["rerank_rank"] = rerank_rank
        return [*ordered, *ranked[limit:]]

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((perf_counter() - started) * 1000, 3)

    @staticmethod
    def _is_program_scope_query(query: str) -> bool:
        """Retain the legacy intent helper for compatibility callers."""

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
