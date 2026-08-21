from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.recruitment_knowledge import (
    ChinaRecruitmentKnowledgeBase,
    RecruitmentQuestionAnsweringAgent,
)


class ChinaRecruitmentKnowledgeBaseTest(unittest.TestCase):
    def test_searches_company_and_graduation_cohort(self) -> None:
        results = ChinaRecruitmentKnowledgeBase().search(
            "阿里巴巴2027届秋招什么时候投？"
        )

        self.assertEqual(results[0]["source_id"], "alibaba-campus-2027")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "current")
        self.assertIn("2026-11 至 2027-10", results[0]["graduation_window"])

    def test_distinguishes_current_and_historical_batches(self) -> None:
        results = ChinaRecruitmentKnowledgeBase().search(
            "字节跳动2026届校招什么时候结束？"
        )

        self.assertEqual(results[0]["source_id"], "bytedance-campus-2026")
        self.assertEqual(results[0]["status"], "historical")

    def test_unknown_company_returns_controlled_no_answer(self) -> None:
        result = RecruitmentQuestionAnsweringAgent(
            ChinaRecruitmentKnowledgeBase()
        ).answer("不存在公司2028届秋招什么时候？")

        self.assertEqual(result["answer_source"], "recruitment_no_evidence")
        self.assertEqual(result["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
