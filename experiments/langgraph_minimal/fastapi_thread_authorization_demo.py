from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FastAPI 线程授权边界实验")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--thread-id", default="day35-http-001")
    return parser.parse_args()


def call(
    *,
    method: str,
    url: str,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None
            else None
        ),
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {"status_code": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return {"status_code": exc.code, "body": body}


def main() -> None:
    args = parse_args()
    approval_url = f"{args.base_url.rstrip('/')}/approval/{args.thread_id}"
    action = {
        "tool_name": "send_email",
        "arguments": {
            "recipients": ["all-students@example.com"],
            "subject": "课程通知",
        },
    }
    output = {
        "thread_id": args.thread_id,
        "未认证读取": call(method="GET", url=approval_url),
        "Alice 创建": call(
            method="POST",
            url=f"{approval_url}/start",
            token="alice-demo-token",
            payload=action,
        ),
        "Bob 越权读取": call(
            method="GET",
            url=approval_url,
            token="bob-demo-token",
        ),
        "Bob 越权恢复": call(
            method="POST",
            url=f"{approval_url}/resume",
            token="bob-demo-token",
            payload={"approved": True},
        ),
        "Alice 读取": call(
            method="GET",
            url=approval_url,
            token="alice-demo-token",
        ),
        "Alice 恢复": call(
            method="POST",
            url=f"{approval_url}/resume",
            token="alice-demo-token",
            payload={"approved": True},
        ),
        "Alice 重复恢复": call(
            method="POST",
            url=f"{approval_url}/resume",
            token="alice-demo-token",
            payload={"approved": True},
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
