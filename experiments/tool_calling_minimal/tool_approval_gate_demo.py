from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.approval_gate import ToolApprovalGate


def main() -> None:
    gate = ToolApprovalGate()
    search = gate.evaluate("search_rag", {"query": "课程有哪些阶段？"})
    draft = gate.evaluate(
        "create_email_draft",
        {"subject": "课程通知", "body": "明天开课"},
    )
    bulk_send = gate.evaluate(
        "send_email",
        {
            "recipients": ["all-students@example.com"],
            "subject": "课程通知",
        },
    )
    changed_send = gate.evaluate(
        "send_email",
        {
            "recipients": ["external-list@example.com"],
            "subject": "课程通知",
        },
    )
    delete_database = gate.evaluate("delete_database", {})

    print(
        json.dumps(
            {
                "只读检索": {
                    **asdict(search),
                    "approved": gate.is_approved(search),
                },
                "创建草稿": {
                    **asdict(draft),
                    "approved": gate.is_approved(draft),
                },
                "批量发送": {
                    **asdict(bulk_send),
                    "approved_before_human": gate.is_approved(bulk_send),
                    "approved_after_human": gate.is_approved(
                        bulk_send,
                        approved_action_digest=bulk_send.action_digest,
                    ),
                },
                "审批后修改收件人": {
                    **asdict(changed_send),
                    "approved_with_old_digest": gate.is_approved(
                        changed_send,
                        approved_action_digest=bulk_send.action_digest,
                    ),
                },
                "删除数据库": {
                    **asdict(delete_database),
                    "approved": gate.is_approved(delete_database),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
