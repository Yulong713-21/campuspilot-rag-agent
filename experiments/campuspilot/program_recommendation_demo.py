from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from campuspilot_core.program_recommendation import (  # noqa: E402
    ProgramRecommendationService,
)


def main() -> None:
    service = ProgramRecommendationService()
    scenarios = {
        "数据与商业分析": {
            "prompt": "我喜欢数据分析，性格细致，毕业想做商业分析师",
            "score_value": 82,
            "score_scale": 100,
        },
        "品牌与市场": {
            "prompt": "我擅长沟通和表达，喜欢创意，希望做品牌营销",
        },
        "软件开发": {
            "prompt": "我逻辑性强，喜欢编程，毕业想做软件开发或人工智能",
            "university": "Monash University",
        },
        "回国大企业或留澳": {
            "prompt": "未来希望回国进大企业或者留在澳洲，推荐我选什么",
        },
        "信息不足": {"prompt": "我还没想好"},
    }
    output = {}
    for name, request in scenarios.items():
        result = service.recommend(request)
        output[name] = {
            "status": result["status"],
            "message": result["message"],
            "recommendations": [
                {
                    "rank": item["rank"],
                    "university": item["university_name"],
                    "program": item["program_name"],
                    "reasons": item["reasons"],
                }
                for item in result["recommendations"]
            ],
            "clarifying_questions": result["clarifying_questions"],
            "trace_tools": result["trace_tools"],
            "answer_source": result["answer_source"],
            "confidence": result["confidence"],
            "next_action": result["next_action"],
        }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
