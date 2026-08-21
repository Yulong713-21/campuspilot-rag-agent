from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.australian_terminology import (
    AustralianTerminologyGlossary,
)


class AustralianTerminologyGlossaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.glossary = AustralianTerminologyGlossary()

    def test_entry_level_is_not_treated_as_year_level(self) -> None:
        results = self.glossary.search(
            "我是 master 第一年，页面选择 Entry Level 1"
        )

        self.assertEqual(results[0]["term_id"], "entry-level")
        self.assertIn("不是硕士一年级", results[0]["common_mistake"])

    def test_internship_retrieves_wil_and_industry_pathway(self) -> None:
        results = self.glossary.search(
            "Industry Experience pathway 能保证 internship 吗？"
        )
        term_ids = [item["term_id"] for item in results]

        self.assertIn("wil", term_ids)
        self.assertIn("industry-experience-pathway", term_ids)


if __name__ == "__main__":
    unittest.main()
