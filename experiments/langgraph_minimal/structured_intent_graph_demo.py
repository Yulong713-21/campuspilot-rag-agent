from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot import CampusPilotConversationAgent  # noqa: E402
from agent_runtime.campuspilot_conversation_graph import (  # noqa: E402
    CampusPilotConversationGraph,
)


class ScenarioInterpreter:
    def __init__(self, decision=None, error=None) -> None:
        self.decision = decision
        self.error = error
        self.call_count = 0

    def interpret(self, query, history, planning_context=None):
        self.call_count += 1
        if self.error:
            raise self.error
        return dict(self.decision)


def run_scenario(name: str, query: str, interpreter) -> dict:
    graph = CampusPilotConversationGraph(
        CampusPilotConversationAgent(goal_interpreter=interpreter)
    )
    result = graph.respond({"message": query})
    graph_steps = [
        step
        for step in result["trace"]
        if step["tool"] in {
            "detect_intent_signals",
            "parse_structured_intent",
            "validate_intent_decision",
            "route_conversation_state",
        }
    ]
    return {
        "场景": name,
        "模型调用次数": interpreter.call_count,
        "最终意图": result["intent"],
        "对话路由": result["conversation_route"],
        "下一步": result["next_action"],
        "图节点": graph_steps,
    }


def main() -> None:
    high_confidence = ScenarioInterpreter(
        {
            "intent": "study_plan",
            "goal_summary": "规划下一学年的课程与实习",
            "needs_clarification": False,
            "clarification_question": None,
            "course_code": None,
            "confidence": 0.93,
            "route_reason": "planning_goal",
        }
    )
    low_confidence = ScenarioInterpreter(
        {
            "intent": "capabilities",
            "goal_summary": "不确定",
            "needs_clarification": False,
            "clarification_question": None,
            "course_code": None,
            "confidence": 0.2,
            "route_reason": "uncertain",
        }
    )
    timeout = ScenarioInterpreter(error=TimeoutError("intent model timeout"))

    report = [
        run_scenario(
            "高置信结构化意图",
            "I need advice for next year",
            high_confidence,
        ),
        run_scenario(
            "低置信结果回退确定性信号",
            "create a study plan",
            low_confidence,
        ),
        run_scenario(
            "意图模型超时回退",
            "FIT5120 assessment",
            timeout,
        ),
    ]
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
