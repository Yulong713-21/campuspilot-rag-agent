from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.approval_workflow import LangGraphApprovalWorkflow


DEFAULT_ACTION = {
    "tool_name": "send_email",
    "arguments": {
        "recipients": ["all-students@example.com"],
        "subject": "课程通知",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SQLite 跨进程 Checkpoint 恢复实验")
    parser.add_argument("command", choices=["start", "resume"])
    parser.add_argument(
        "--db",
        type=Path,
        default=REPO_ROOT / "logs" / "day34-checkpoints.sqlite3",
    )
    parser.add_argument("--thread-id", default="approval-sqlite-001")
    parser.add_argument(
        "--approved",
        choices=["true", "false"],
        default="true",
        help="resume 时的人工审批结果",
    )
    return parser.parse_args()


def snapshot_summary(workflow: LangGraphApprovalWorkflow, thread_id: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = workflow.graph.get_state(config)
    return {
        "status": snapshot.values.get("status"),
        "execution_count": snapshot.values.get("execution_count", 0),
        "next_nodes": list(snapshot.next),
        "has_pending_interrupt": any(task.interrupts for task in snapshot.tasks),
    }


def checkpoint_count(saver: SqliteSaver, thread_id: str) -> int:
    config = {"configurable": {"thread_id": thread_id}}
    return sum(1 for _ in saver.list(config))


def main() -> None:
    args = parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)

    with SqliteSaver.from_conn_string(str(args.db)) as saver:
        workflow = LangGraphApprovalWorkflow(checkpointer=saver)
        before = snapshot_summary(workflow, args.thread_id)
        checkpoints_before = checkpoint_count(saver, args.thread_id)

        if args.command == "start":
            result = workflow.start(args.thread_id, DEFAULT_ACTION)
        else:
            result = workflow.resume(
                args.thread_id,
                approved=args.approved == "true",
            )

        after = snapshot_summary(workflow, args.thread_id)
        output = {
            "command": args.command,
            "process_id": os.getpid(),
            "database": str(args.db.resolve()),
            "thread_id": args.thread_id,
            "checkpoint_count_before": checkpoints_before,
            "checkpoint_count_after": checkpoint_count(saver, args.thread_id),
            "state_before_command": before,
            "state_after_command": after,
            "result": result,
        }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
