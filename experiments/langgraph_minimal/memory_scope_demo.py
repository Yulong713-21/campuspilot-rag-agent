from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.memory_workflow import LangGraphMemoryWorkflow


def summary(state: dict) -> dict:
    return {
        "thread_message_count": state["thread_message_count"],
        "thread_messages": state["thread_messages"],
        "remembered_preference": state["remembered_preference"],
        "response": state["response"],
    }


def main() -> None:
    workflow = LangGraphMemoryWorkflow()
    workflow.save_preference(
        "user-1",
        "answer_style",
        "先讲原理，再展示实验",
    )

    thread_a_first = workflow.invoke(
        "thread-a",
        "user-1",
        "Deadline 是什么？",
    )
    thread_a_second = workflow.invoke(
        "thread-a",
        "user-1",
        "它和 Timeout 有什么区别？",
    )
    thread_b = workflow.invoke(
        "thread-b",
        "user-1",
        "继续学习",
    )
    user_2 = workflow.invoke(
        "thread-c",
        "user-2",
        "继续学习",
    )

    print(
        json.dumps(
            {
                "同一线程第一次": summary(thread_a_first),
                "同一线程第二次": summary(thread_a_second),
                "同一用户新线程": summary(thread_b),
                "不同用户新线程": summary(user_2),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
