from __future__ import annotations

import os
from typing import Any

import httpx


class OpenAICompatibleChatClient:
    """Minimal OpenAI-compatible client with no SDK dependency."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("API key is required")
        if not base_url.startswith("https://"):
            raise ValueError("base_url must use HTTPS")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if response_format:
            payload["response_format"] = response_format
        with httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0].get("message"), dict):
            raise ValueError("OpenAI-compatible response has no message")
        return {
            "message": choices[0]["message"],
            "model": body.get("model", self.model),
            "usage": body.get("usage", {}),
        }

    @classmethod
    def from_environment(cls) -> OpenAICompatibleChatClient:
        return cls(
            api_key=(
                os.environ.get("CAMPUSPILOT_OPENAI_API_KEY")
                or os.environ.get("DASHSCOPE_API_KEY", "")
            ),
            base_url=os.environ.get(
                "CAMPUSPILOT_OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            model=os.environ.get(
                "CAMPUSPILOT_OPENAI_MODEL",
                "qwen-plus",
            ),
            timeout_seconds=float(
                os.environ.get("CAMPUSPILOT_OPENAI_TIMEOUT_SECONDS", "60")
            ),
        )

