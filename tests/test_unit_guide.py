from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.unit_guide import MonashUnitGuideParser


class MonashUnitGuideParserTest(unittest.TestCase):
    def test_extracts_assessment_weights_hurdles_and_source(self) -> None:
        page = {
            "props": {
                "pageProps": {
                    "pageContent": {
                        "code": "FIT9131",
                        "title": "Programming foundations in Java",
                        "implementation_year": "2026",
                        "attendance_requirements": None,
                        "handbook_assessment_summary": (
                            "<p>This unit has threshold mark hurdles.</p>"
                        ),
                        "assessments": [
                            {
                                "number": "1",
                                "name": "Assignment",
                                "weight": "55",
                                "assessment_type": {
                                    "label": "Written",
                                    "value": "written",
                                },
                                "hurdle_type": {
                                    "label": "Threshold",
                                    "value": "threshold",
                                },
                            },
                            {
                                "number": "2",
                                "name": "Scheduled final assessment",
                                "weight": "45",
                                "assessment_type": {
                                    "label": "Examination",
                                    "value": "examination",
                                },
                                "hurdle_type": {
                                    "label": "Threshold",
                                    "value": "threshold",
                                },
                            },
                        ],
                    }
                }
            }
        }
        html = (
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(page)
            + "</script>"
        ).encode()

        result = MonashUnitGuideParser().parse(
            html,
            source_url="https://handbook.monash.edu/2026/units/fit9131",
        )

        self.assertEqual(result["course_code"], "FIT9131")
        self.assertEqual(result["exam_weight_percent"], 45)
        self.assertTrue(result["final_exam"])
        self.assertEqual(result["hurdle_status"], "YES")
        self.assertEqual(
            result["assessment_tags"],
            ["考核门槛", "考试合计 45%"],
        )
        self.assertEqual(result["attendance_status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()

