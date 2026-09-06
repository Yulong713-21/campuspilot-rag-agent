"""Structured-first execution for deterministic retrieval plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .interfaces import EvidenceRetriever, RetrievalRequest
from .router import CandidateConstraints, QueryRouter, RetrievalPlan
from .scope import RetrievalScope


@dataclass(frozen=True)
class StructuredResolution:
    """Deterministic result plus candidates safe for evidence retrieval."""

    candidates: CandidateConstraints = field(
        default_factory=CandidateConstraints
    )
    result: dict[str, Any] | None = None


class StructuredCandidateResolver(Protocol):
    """Adapter implemented by a PostgreSQL-backed rule workflow."""

    def resolve(
        self,
        query: str,
        scope: RetrievalScope,
    ) -> StructuredResolution: ...


@dataclass(frozen=True)
class RetrievalExecutionResult:
    plan: RetrievalPlan
    scope: RetrievalScope
    candidates: CandidateConstraints
    structured_result: dict[str, Any] | None
    documents: tuple[dict[str, Any], ...]
    diagnostics: dict[str, Any]


class RetrievalPlanExecutor:
    """Run structured resolution before only the planned evidence channels."""

    def __init__(
        self,
        *,
        router: QueryRouter,
        evidence_retriever: EvidenceRetriever,
        structured_resolver: StructuredCandidateResolver | None = None,
        semantic_available: bool = True,
    ) -> None:
        self.router = router
        self.evidence_retriever = evidence_retriever
        self.structured_resolver = structured_resolver
        self.semantic_available = semantic_available

    def execute(
        self,
        *,
        query: str,
        scope: RetrievalScope,
        k: int = 3,
    ) -> RetrievalExecutionResult:
        """Execute an inspectable plan and preserve truthful degradation."""

        plan = self.router.plan(query, scope)
        resolved_candidates = CandidateConstraints()
        structured_result = None
        structured_used = False
        if plan.use_structured_rules and self.structured_resolver is not None:
            resolution = self.structured_resolver.resolve(query, scope)
            resolved_candidates = resolved_candidates.merge(
                resolution.candidates
            )
            structured_result = resolution.result
            structured_used = True

        effective_plan = plan
        if plan.require_candidate_scope and not resolved_candidates.has_any:
            # A mixed discovery query must not broaden into global semantic
            # retrieval when its deterministic candidate step is unavailable.
            effective_plan = plan.without_semantic(
                "semantic_skipped_without_candidate_scope"
            )
        semantic_capability_unavailable = (
            effective_plan.use_semantic and not self.semantic_available
        )
        if semantic_capability_unavailable:
            effective_plan = effective_plan.without_semantic(
                "semantic_capability_unavailable"
            )

        documents: list[dict[str, Any]] = []
        retrieval_error = None
        if effective_plan.use_lexical or effective_plan.use_semantic:
            try:
                documents = self.evidence_retriever.retrieve(
                    RetrievalRequest(
                        query=query,
                        scope=scope,
                        k=k,
                        candidates=resolved_candidates,
                        plan=effective_plan,
                    )
                )
            except Exception as exc:
                # Structured results remain usable when every optional evidence
                # channel is unavailable. Only the safe error category escapes.
                retrieval_error = type(exc).__name__

        backend = getattr(
            self.evidence_retriever,
            "last_search_diagnostics",
            {},
        )
        lexical_error = backend.get("lexical_error")
        dense_error = backend.get("dense_error")
        if semantic_capability_unavailable and dense_error is None:
            dense_error = "Unavailable"
        degradation_reasons = list(backend.get("degradation_reasons", []))
        for reason in (
            f"lexical:{lexical_error}" if lexical_error else None,
            f"semantic:{dense_error}" if dense_error else None,
            f"retrieval:{retrieval_error}" if retrieval_error else None,
        ):
            if reason and reason not in degradation_reasons:
                degradation_reasons.append(reason)
        lexical_used = (
            backend.get("lexical_count", 0) > 0
            if "lexical_count" in backend
            else effective_plan.use_lexical and retrieval_error is None
        )
        semantic_used = (
            backend.get("semantic_count", 0) > 0
            if "semantic_count" in backend
            else (
                effective_plan.use_semantic
                and dense_error is None
                and retrieval_error is None
            )
        )
        evidence_unavailable = bool(retrieval_error) or (
            not documents
            and (not effective_plan.use_lexical or lexical_error is not None)
            and (not effective_plan.use_semantic or dense_error is not None)
        )
        diagnostics = {
            "planned_route": list(plan.route),
            "route": list(effective_plan.route),
            "effective_route": list(effective_plan.route),
            "structured_used": structured_used,
            "lexical_used": lexical_used,
            "semantic_used": semantic_used,
            "scope": scope.to_search_kwargs(),
            "candidate_count": resolved_candidates.count,
            "router_reason": list(effective_plan.reasons),
            "router_fallback_used": effective_plan.router_fallback_used,
            "lexical_error": lexical_error,
            "semantic_error": dense_error,
            "retrieval_error": retrieval_error,
            "degraded": bool(degradation_reasons),
            "degradation_reasons": degradation_reasons,
            "evidence_degraded": bool(degradation_reasons),
            "evidence_unavailable": evidence_unavailable,
        }
        for field_name in (
            "lexical_count",
            "semantic_count",
            "rrf_candidate_count",
            "rrf_output_count",
            "candidate_pool_size",
            "reranker_requested",
            "reranker_used",
            "reranker_error",
            "reranker_candidate_count",
            "dedup_before_count",
            "dedup_after_count",
            "unresolved_evidence_count",
            "hybrid_attempted",
            "hybrid_contributed",
            "latency_ms",
        ):
            if field_name in backend:
                diagnostics[field_name] = backend[field_name]
        return RetrievalExecutionResult(
            plan=effective_plan,
            scope=scope,
            candidates=resolved_candidates,
            structured_result=structured_result,
            documents=tuple(documents),
            diagnostics=diagnostics,
        )


class PlannedEvidenceRetriever:
    """Compatibility adapter that routes legacy ``search`` call sites.

    Business agents historically consumed a keyword-based ``search`` method.
    Keeping that narrow surface avoids coupling them to ES, Milvus, or the
    execution details while ensuring every user-facing query is planned.
    """

    def __init__(self, executor: RetrievalPlanExecutor) -> None:
        self.executor = executor
        self.last_search_diagnostics: dict[str, Any] = {}

    def retrieve(self, request: RetrievalRequest) -> list[dict[str, Any]]:
        """Execute an already normalized storage-independent request."""

        # Candidate constraints on an inbound compatibility request are
        # intentionally ignored. Only this executor's structured resolver may
        # create the candidate set forwarded to storage backends.
        result = self.executor.execute(
            query=request.query,
            scope=request.scope,
            k=request.k,
        )
        self._record_diagnostics(result.diagnostics)
        return list(result.documents)

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
        """Translate legacy keyword filters into a deterministic plan."""

        return self.retrieve(
            RetrievalRequest(
                query=query,
                scope=RetrievalScope(
                    university_id=university_id,
                    program_code=program_code,
                    handbook_year=handbook_year,
                    specialisation_code=specialisation_code,
                    discipline_id=discipline_id,
                    source_type=source_type,
                ),
                k=k,
            )
        )

    def _record_diagnostics(self, diagnostics: dict[str, Any]) -> None:
        # Preserve the two legacy keys consumed by existing trace emitters.
        self.last_search_diagnostics = {
            **diagnostics,
            "degraded": diagnostics["evidence_degraded"],
            "dense_error": diagnostics["semantic_error"],
        }
