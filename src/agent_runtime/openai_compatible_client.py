from __future__ import annotations

import os
from threading import RLock
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
        self._config_lock = RLock()

    def reconfigure(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        next_api_key = api_key if api_key is not None else self.api_key
        next_base_url = base_url if base_url is not None else self.base_url
        next_model = model if model is not None else self.model
        next_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.timeout_seconds
        )
        if not next_api_key:
            raise ValueError("API key is required")
        if not next_base_url.startswith("https://"):
            raise ValueError("base_url must use HTTPS")
        if not next_model.strip():
            raise ValueError("model is required")
        if not 1 <= float(next_timeout) <= 300:
            raise ValueError("timeout_seconds must be between 1 and 300")
        with self._config_lock:
            self.api_key = next_api_key
            self.base_url = next_base_url.rstrip("/")
            self.model = next_model.strip()
            self.timeout_seconds = float(next_timeout)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        with self._config_lock:
            api_key = self.api_key
            base_url = self.base_url
            model = self.model
            timeout_seconds = self.timeout_seconds
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if response_format:
            payload["response_format"] = response_format
        with httpx.Client(
            timeout=timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
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
            "model": body.get("model", model),
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
