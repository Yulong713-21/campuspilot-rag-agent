from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
TEST_ROOT = REPO_ROOT / "tests"
for path in (SRC_ROOT, TEST_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from campuspilot_core.program_recommendation import (  # noqa: E402
    ProgramRecommendationService,
)
from test_hobby_only_recommendation_scenario import (  # noqa: E402
    HobbyOnlyProfileInterpreter,
)


def summarize_turn(user_input: str, result: dict) -> dict:
    return {
        "用户输入": user_input,
        "状态": result["status"],
        "Pia回答": result["message"],
        "用户原话依据": result.get("profile", {}).get("evidence_phrases", []),
        "候选方向": result.get("profile", {}).get("matched_signals", []),
        "候选项目": [
            {
                "学校": item["university_name"],
                "项目": item["program_name"],
                "推荐理由": item["reasons"],
                "可探索岗位": item["career_path"]["roles"],
                "起步建议": item["career_path"]["preparation"],
            }
            for item in result["recommendations"]
        ],
        "处理链路": result["trace_tools"],
        "下一步": result["next_action"],
    }


def main() -> None:
    interpreter = HobbyOnlyProfileInterpreter()
    service = ProgramRecommendationService(profile_interpreter=interpreter)
    first_input = "我平时最大的爱好就是打游戏。"
    second_input = (
        "玩的时候最喜欢研究技能组合、数值平衡和关卡机制。"
        "比起画画，我更喜欢把规则做成能运行的东西。"
    )

    first = service.recommend({"prompt": first_input})
    second = service.recommend(
        {
            "prompt": second_input,
            "conversation_context": first_input,
            "allow_llm_profile_fallback": True,
        }
    )
    output = {
        "实验名称": "只聊爱好的专业推荐",
        "约束": "用户不提供专业名称、岗位名称、成绩或目标学校",
        "第一轮": summarize_turn(first_input, first),
        "第二轮": summarize_turn(second_input, second),
        "观察结论": {
            "第一轮直接推荐": bool(first["recommendations"]),
            "第二轮是否进入已核验目录": (
                "search_verified_program_catalog" in second["trace_tools"]
            ),
            "是否给出职业探索路径": any(
                item.get("career_path", {}).get("roles")
                for item in second["recommendations"]
            ),
            "模拟画像模型调用次数": interpreter.call_count,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
