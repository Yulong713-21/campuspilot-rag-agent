from __future__ import annotations

import os
from typing import Any

import httpx


class DifyWorkflowClient:
    """Optional server-side adapter for a published Dify Workflow app."""

    def __init__(
        self,
        *,
        api_base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_base_url.strip() or not api_key.strip():
            raise ValueError("Dify API base URL and API key are required")
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @classmethod
    def from_env(cls) -> "DifyWorkflowClient":
        return cls(
            api_base_url=os.environ.get(
                "CAMPUSPILOT_DIFY_API_BASE_URL",
                "",
            ),
            api_key=os.environ.get("CAMPUSPILOT_DIFY_API_KEY", ""),
            timeout_seconds=float(
                os.environ.get("CAMPUSPILOT_DIFY_TIMEOUT_SECONDS", "30")
            ),
        )

    def run_workflow(
        self,
        *,
        inputs: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        if not user_id.strip():
            raise ValueError("Dify user_id must not be empty")
        with httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.post(
                f"{self.api_base_url}/workflows/run",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": inputs,
                    "response_mode": "blocking",
                    "user": user_id,
                },
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", {})
        return {
            "workflow_run_id": payload.get("workflow_run_id"),
            "status": data.get("status"),
            "outputs": data.get("outputs", {}),
            "elapsed_time": data.get("elapsed_time"),
            "total_tokens": data.get("total_tokens"),
        }
