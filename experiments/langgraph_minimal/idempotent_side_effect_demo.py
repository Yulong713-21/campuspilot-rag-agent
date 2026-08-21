from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.idempotent_action import SimulatedEmailProvider


def run_without_idempotency() -> dict:
    provider = SimulatedEmailProvider(sqlite3.connect(":memory:"))
    attempts = [
        provider.send_without_idempotency(
            recipient="student@example.com",
            subject="课程通知",
        )
        for _ in range(2)
    ]
    return {
        "agent_node_attempts": len(attempts),
        "provider_delivery_count": provider.delivery_count(),
        "attempt_results": [attempt.to_dict() for attempt in attempts],
    }


def run_with_idempotency() -> dict:
    provider = SimulatedEmailProvider(sqlite3.connect(":memory:"))
    operation_id = "email:course-notice:student-001"
    attempts = [
        provider.send_with_idempotency(
            operation_id=operation_id,
            recipient="student@example.com",
            subject="课程通知",
        )
        for _ in range(2)
    ]
    return {
        "operation_id": operation_id,
        "agent_node_attempts": len(attempts),
        "provider_delivery_count": provider.delivery_count(),
        "attempt_results": [attempt.to_dict() for attempt in attempts],
    }


def main() -> None:
    output = {
        "故障场景": (
            "第一次外部调用成功后，Agent 在写入完成 checkpoint 前崩溃；"
            "恢复后同一节点再次执行。"
        ),
        "没有幂等键": run_without_idempotency(),
        "使用相同幂等键": run_with_idempotency(),
        "结论": (
            "Checkpoint 允许节点重跑；外部服务必须识别稳定 operation_id，"
            "才能把重复调用压成一次业务副作用。"
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
