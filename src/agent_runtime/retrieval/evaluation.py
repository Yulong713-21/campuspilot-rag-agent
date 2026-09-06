"""Scenario-aware evaluation for lexical, semantic, and hybrid retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping

from .interfaces import EvidenceRetriever, RetrievalRequest
from .scope import RetrievalScope


class RetrievalScenario(str, Enum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    HYBRID_RERANKED = "hybrid_reranked"


@dataclass(frozen=True)
class RetrievalEvaluationCase:
    case_id: str
    scenario: RetrievalScenario
    query: str
    scope: RetrievalScope
    expected_source_ids: tuple[str, ...]
    expected_identifier: str | None = None
    expected_channels: tuple[str, ...] = ()
    k: int = 5


@dataclass(frozen=True)
class RetrievalEvaluationReport:
    """Per-scenario metrics without collapsing different search intents."""

    case_results: tuple[dict[str, Any], ...]
    scenario_metrics: dict[str, dict[str, float]]
    semantic_subset_coverage: dict[str, int | float] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "case_count": len(self.case_results),
            "scenario_metrics": self.scenario_metrics,
            "cases": list(self.case_results),
        }
        if self.semantic_subset_coverage is not None:
            payload["semantic_subset_coverage"] = self.semantic_subset_coverage
        return payload


def load_retrieval_cases(
    path: str | Path,
) -> list[RetrievalEvaluationCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        RetrievalEvaluationCase(
            case_id=item["case_id"],
            scenario=RetrievalScenario(item["scenario"]),
            query=item["query"],
            scope=RetrievalScope(**item.get("scope", {})),
            expected_source_ids=tuple(item["expected_source_ids"]),
            expected_identifier=item.get("expected_identifier"),
            expected_channels=tuple(item.get("expected_channels", [])),
            k=int(item.get("k", 5)),
        )
        for item in payload["cases"]
    ]


class RetrievalScenarioEvaluator:
    """Run each case only against the retriever for its intended scenario."""

    def evaluate(
        self,
        cases: list[RetrievalEvaluationCase],
        retrievers: Mapping[RetrievalScenario, EvidenceRetriever],
        *,
        total_chunks: int | None = None,
        embedded_chunks: int | None = None,
    ) -> RetrievalEvaluationReport:
        results = [
            self._evaluate_case(case, retrievers[case.scenario])
            for case in cases
        ]
        metrics: dict[str, dict[str, float]] = {}
        for scenario in RetrievalScenario:
            selected = [
                result
                for result in results
                if result["scenario"] == scenario.value
            ]
            if not selected:
                continue
            metric_names = sorted(
                {
                    name
                    for result in selected
                    for name in (
                        set(result["checks"]) | set(result["metrics"])
                    )
                }
            )
            metrics[scenario.value] = {
                name: round(
                    sum(
                        (
                            result["metrics"][name]
                            if name in result["metrics"]
                            else result["checks"][name]
                        )
                        for result in selected
                        if name in result["checks"]
                        or name in result["metrics"]
                    )
                    / sum(
                        name in result["checks"]
                        or name in result["metrics"]
                        for result in selected
                    ),
                    4,
                )
                for name in metric_names
            }
        subset_coverage = None
        if total_chunks is not None and embedded_chunks is not None:
            subset_coverage = {
                "embedded_chunks": embedded_chunks,
                "total_chunks": total_chunks,
                "ratio": round(
                    embedded_chunks / total_chunks if total_chunks else 0.0,
                    6,
                ),
            }
        return RetrievalEvaluationReport(
            tuple(results),
            metrics,
            subset_coverage,
        )

    def _evaluate_case(
        self,
        case: RetrievalEvaluationCase,
        retriever: EvidenceRetriever,
    ) -> dict[str, Any]:
        documents = retriever.retrieve(
            RetrievalRequest(case.query, case.scope, case.k)
        )
        matching = [
            item
            for item in documents
            if item.get("source_id") in case.expected_source_ids
        ]
        returned_sources = [item.get("source_id") for item in documents]
        matched_sources = set(returned_sources) & set(case.expected_source_ids)
        expected_ranks = [
            rank
            for rank, source_id in enumerate(returned_sources, start=1)
            if source_id in case.expected_source_ids
        ]
        checks: dict[str, bool] = {
            "expected_source_found": bool(matching),
            "scope_precision": all(
                self._matches_scope(item, case.scope) for item in documents
            ),
        }
        if case.scenario is RetrievalScenario.LEXICAL:
            checks["exact_identifier_ranked"] = bool(
                case.expected_identifier
                and any(
                    case.expected_identifier.upper()
                    in (
                        f"{item.get('source_id', '')} "
                        f"{item.get('title', '')}"
                    ).upper()
                    for item in documents[:3]
                )
            )
        if case.scenario is RetrievalScenario.SEMANTIC:
            checks["semantic_concept_found"] = bool(matching)
        if case.scenario in {
            RetrievalScenario.HYBRID,
            RetrievalScenario.HYBRID_RERANKED,
        }:
            observed_channels = {
                channel
                for item in matching
                for channel in item.get("retrieval_channels", [])
            }
            checks["channel_coverage"] = set(
                case.expected_channels
            ).issubset(observed_channels)
            checks["recovered_from_either_channel"] = bool(
                matching and observed_channels & {"bm25", "dense"}
            )
            checks["promoted_by_fusion"] = bool(
                expected_ranks
                and min(expected_ranks) <= min(case.k, 3)
            )
        return {
            "case_id": case.case_id,
            "scenario": case.scenario.value,
            "checks": checks,
            "metrics": {
                "recall_at_k": round(
                    len(matched_sources) / len(case.expected_source_ids),
                    4,
                ),
                "reciprocal_rank": round(
                    1.0 / min(expected_ranks) if expected_ranks else 0.0,
                    4,
                ),
                "mrr": round(
                    1.0 / min(expected_ranks) if expected_ranks else 0.0,
                    4,
                ),
                "scope_precision": 1.0
                if checks["scope_precision"]
                else 0.0,
            },
            "expected_source_rank": (
                min(expected_ranks) if expected_ranks else None
            ),
            "returned_source_ids": returned_sources,
        }

    @staticmethod
    def _matches_scope(
        document: dict[str, Any],
        scope: RetrievalScope,
    ) -> bool:
        if (
            scope.university_id
            and document.get("university_id") != scope.university_id
        ):
            return False
        if (
            scope.handbook_year is not None
            and document.get("handbook_year") != scope.handbook_year
        ):
            return False
        if scope.program_code:
            codes = document.get("program_codes") or []
            if isinstance(codes, str):
                codes = [item for item in codes.split("|") if item]
            if (
                document.get("program_code") != scope.program_code
                and scope.program_code not in codes
            ):
                return False
        if scope.specialisation_code:
            codes = document.get("specialisation_codes") or []
            if isinstance(codes, str):
                codes = [item for item in codes.split("|") if item]
            if scope.specialisation_code not in codes:
                return False
        return True
