from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot_faq import CampusPilotFaqService  # noqa: E402


class CampusPilotFaqServiceTest(unittest.TestCase):
    def test_catalog_contains_about_one_hundred_general_questions(self) -> None:
        service = CampusPilotFaqService()

        self.assertGreaterEqual(service.question_count, 95)
        self.assertLessEqual(service.question_count, 120)
        self.assertGreaterEqual(service.entry_count, 30)

    def test_at_least_eighty_percent_of_canonical_topics_prefer_agent(self) -> None:
        service = CampusPilotFaqService()

        direct_answer_ratio = len(service.DIRECT_ANSWER_FAQ_IDS) / service.entry_count

        self.assertLessEqual(direct_answer_ratio, 0.20)

    def test_exact_alias_ignores_spaces_and_punctuation(self) -> None:
        result = CampusPilotFaqService().search("Entry Level 1 是 Master 第一年吗？")

        self.assertTrue(result["hit"])
        self.assertEqual(result["data"]["faq_id"], "monash-entry-level")
        self.assertIn("不是“硕士第几年”", result["data"]["answer"])

    def test_personal_planning_question_does_not_fuzzy_match(self) -> None:
        result = CampusPilotFaqService().search(
            "我读 Entry Level 1，怎样选课才能兼顾实习？"
        )

        self.assertFalse(result["hit"])

    def test_non_allowlisted_exact_question_prefers_agent(self) -> None:
        result = CampusPilotFaqService().search("支持哪些学校")

        self.assertFalse(result["hit"])
        self.assertEqual(
            result["data"]["route_reason"],
            "exact_match_requires_agent",
        )
        self.assertEqual(
            result["data"]["exact_candidate"],
            "supported-universities",
        )


if __name__ == "__main__":
    unittest.main()
