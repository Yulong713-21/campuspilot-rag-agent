from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.tool_calling_minimal.reserve_percentile_comparison import (
    evaluate_reserve,
)


class ReservePercentileComparisonTest(unittest.TestCase):
    def test_p95_reserve_removes_wasted_rag_work_in_fixed_workload(self) -> None:
        mean_strategy = evaluate_reserve(1.1)
        p95_strategy = evaluate_reserve(2.0)
        p99_strategy = evaluate_reserve(3.8)

        self.assertEqual(
            mean_strategy["complete_answer_rate"],
            p95_strategy["complete_answer_rate"],
        )
        self.assertEqual(mean_strategy["wasted_rag_seconds"], 6.0)
        self.assertEqual(p95_strategy["wasted_rag_seconds"], 0.0)
        self.assertEqual(p99_strategy["complete_answers"], 0)
        self.assertEqual(p99_strategy["cache_fallbacks"], 20)


if __name__ == "__main__":
    unittest.main()
