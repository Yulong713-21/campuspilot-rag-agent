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

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": len(self.case_results),
            "scenario_metrics": self.scenario_metrics,
            "cases": list(self.case_results),
        }


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
                    for name in result["checks"]
                }
            )
            metrics[scenario.value] = {
                name: round(
                    sum(
                        result["checks"][name]
                        for result in selected
                        if name in result["checks"]
                    )
                    / sum(name in result["checks"] for result in selected),
                    4,
                )
                for name in metric_names
            }
        return RetrievalEvaluationReport(tuple(results), metrics)

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
        if case.scenario is RetrievalScenario.HYBRID:
            observed_channels = {
                channel
                for item in matching
                for channel in item.get("retrieval_channels", [])
            }
            checks["channel_coverage"] = set(
                case.expected_channels
            ).issubset(observed_channels)
        return {
            "case_id": case.case_id,
            "scenario": case.scenario.value,
            "checks": checks,
            "returned_source_ids": [
                item.get("source_id") for item in documents
            ],
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
