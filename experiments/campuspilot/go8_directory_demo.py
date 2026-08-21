from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agent_runtime.campuspilot import CampusPilotCatalog


def main() -> None:
    catalog = CampusPilotCatalog()
    scenarios = {}
    for discipline in catalog.go8_data["disciplines"]:
        result = catalog.list_go8_universities(
            discipline["discipline_id"]
        )
        scenarios[discipline["name"]] = {
            "university_count": result["count"],
            "planning_verified_count": result[
                "planning_verified_count"
            ],
            "universities": [
                {
                    "name": university["short_name"],
                    "status": university["coverage_status"],
                    **(
                        {
                            "representative_program": university[
                                "representative_program"
                            ]["name"]
                        }
                        if discipline["discipline_id"] == "computing"
                        else {}
                    ),
                }
                for university in result["universities"]
            ],
        }

    output = {
        "answer_source": "go8_official_catalog",
        "confidence": "high",
        "next_action": "select_university_and_program",
        "trace_tools": [
            "load_go8_membership",
            "filter_common_disciplines",
            "report_coverage_maturity",
        ],
        "catalog_version": catalog.go8_data["catalog_version"],
        "membership_source": catalog.go8_data["membership_source"],
        "scenarios": scenarios,
        "coverage_notice": catalog.go8_data["coverage_notice"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
