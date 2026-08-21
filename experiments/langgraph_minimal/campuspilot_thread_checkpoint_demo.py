from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.campuspilot import CampusPilotConversationAgent
from agent_runtime.campuspilot_conversation_graph import CampusPilotConversationGraph


def create_graph(connection: sqlite3.Connection) -> CampusPilotConversationGraph:
    return CampusPilotConversationGraph(
        CampusPilotConversationAgent(),
        checkpointer=SqliteSaver(connection),
    )


def main() -> None:
    database = REPO_ROOT / "logs" / "day60-conversation-checkpoints.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    thread_id = f"checkpoint-demo-{uuid4()}"

    first_connection = sqlite3.connect(database, check_same_thread=False)
    first = create_graph(first_connection).respond(
        {
            "thread_id": thread_id,
            "message": "帮我生成最快毕业方案",
            "program_variant_id": "MONASH-C6001-EL2",
            "handbook_year": 2026,
            "study_stream": "Industry Experience",
            "completed_courses": ["FIT5057", "FIT5058"],
            "max_courses_per_semester": 4,
            "start_semester": "2026-S2",
        }
    )
    first_connection.close()

    second_connection = sqlite3.connect(database, check_same_thread=False)
    try:
        second = create_graph(second_connection).respond(
            {
                "thread_id": thread_id,
                "message": "再均衡一点",
            }
        )
    finally:
        second_connection.close()

    print(
        json.dumps(
            {
                "实验目标": "验证 Graph 重建后仍可按 thread_id 恢复对话状态",
                "数据库": str(database.resolve()),
                "thread_id": thread_id,
                "第一轮": {
                    "route": first["conversation_route"],
                    "intent": first["intent"],
                    "thread_state": first["thread_state"],
                },
                "模拟服务重启": "已关闭连接并重新创建 Graph 与 SQLite 连接",
                "第二轮": {
                    "query": "再均衡一点",
                    "route": second["conversation_route"],
                    "intent": second["intent"],
                    "thread_state": second["thread_state"],
                    "restored_context": second["trace"][0]["restored_context"],
                    "intent_inherited": second["trace"][1]["intent_inherited"],
                    "plan_count": len(second["study_plans"]["plans"]),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
