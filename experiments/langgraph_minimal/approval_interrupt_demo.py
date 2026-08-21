from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.approval_workflow import LangGraphApprovalWorkflow


def main() -> None:
    workflow = LangGraphApprovalWorkflow()
    action = {
        "tool_name": "send_email",
        "arguments": {
            "recipients": ["all-students@example.com"],
            "subject": "课程通知",
        },
    }

    paused = workflow.start("approval-demo-approved", action)
    approved = workflow.resume("approval-demo-approved", approved=True)

    rejected_pause = workflow.start("approval-demo-rejected", action)
    rejected = workflow.resume("approval-demo-rejected", approved=False)

    print(
        json.dumps(
            {
                "批准流程": {
                    "暂停时": paused,
                    "恢复后": approved,
                },
                "拒绝流程": {
                    "暂停时": rejected_pause,
                    "恢复后": rejected,
                },
                "关键观察": (
                    "暂停时 execution_count=0；只有使用同一 thread_id "
                    "恢复并批准后，执行节点才运行一次。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
