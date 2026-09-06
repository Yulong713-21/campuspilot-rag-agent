from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.retrieval import (  # noqa: E402
    RetrievalScenario,
    RetrievalScenarioEvaluator,
    load_retrieval_cases,
    should_embed,
)
from agent_runtime.handbook_vector import read_chunks  # noqa: E402


class RetrievalEvaluationTest(unittest.TestCase):
    def test_dataset_references_sources_in_the_published_corpus(self) -> None:
        cases = load_retrieval_cases(
            REPO_ROOT / "eval" / "handbook_retrieval_cases.json"
        )
        source_ids = {
            json.loads(line)["source_id"]
            for line in (
                REPO_ROOT
                / "data"
                / "official_sources"
                / "handbook-chunks.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

        self.assertEqual(
            {case.scenario for case in cases},
            set(RetrievalScenario),
        )
        for case in cases:
            self.assertTrue(set(case.expected_source_ids) <= source_ids)

        eligible_source_ids = {
            chunk.source_id for chunk in read_chunks() if should_embed(chunk)
        }
        for case in cases:
            if case.scenario is RetrievalScenario.SEMANTIC:
                self.assertTrue(
                    set(case.expected_source_ids) & eligible_source_ids
                )

    def test_reports_metrics_separately_for_each_retrieval_scenario(self) -> None:
        cases = load_retrieval_cases(
            REPO_ROOT / "eval" / "handbook_retrieval_cases.json"
        )

        class ExpectedRetriever:
            def __init__(self, scenario):
                self.scenario = scenario

            def retrieve(self, request):
                case = next(item for item in cases if item.query == request.query)
                channels = (
                    ["bm25", "dense"]
                    if self.scenario
                    in {
                        RetrievalScenario.HYBRID,
                        RetrievalScenario.HYBRID_RERANKED,
                    }
                    else [self.scenario.value]
                )
                return [
                    {
                        "source_id": case.expected_source_ids[0],
                        "title": case.expected_identifier or "Official program",
                        "university_id": request.scope.university_id,
                        "program_code": request.scope.program_code,
                        "program_codes": [request.scope.program_code],
                        "handbook_year": request.scope.handbook_year,
                        "retrieval_channels": channels,
                    }
                ]

        report = RetrievalScenarioEvaluator().evaluate(
            cases,
            {
                scenario: ExpectedRetriever(scenario)
                for scenario in RetrievalScenario
            },
            total_chunks=100,
            embedded_chunks=40,
        )

        self.assertEqual(
            set(report.scenario_metrics),
            {"lexical", "semantic", "hybrid", "hybrid_reranked"},
        )
        self.assertEqual(
            report.scenario_metrics["lexical"]["exact_identifier_ranked"],
            1.0,
        )
        self.assertEqual(
            report.scenario_metrics["semantic"]["semantic_concept_found"],
            1.0,
        )
        self.assertEqual(
            report.scenario_metrics["hybrid"]["channel_coverage"],
            1.0,
        )
        self.assertEqual(
            report.scenario_metrics["hybrid_reranked"][
                "promoted_by_fusion"
            ],
            1.0,
        )
        self.assertEqual(
            report.scenario_metrics["semantic"]["recall_at_k"],
            1.0,
        )
        self.assertEqual(
            report.scenario_metrics["semantic"]["reciprocal_rank"],
            1.0,
        )
        self.assertEqual(
            report.scenario_metrics["semantic"]["mrr"],
            1.0,
        )
        self.assertEqual(
            report.semantic_subset_coverage,
            {"embedded_chunks": 40, "total_chunks": 100, "ratio": 0.4},
        )


if __name__ == "__main__":
    unittest.main()
