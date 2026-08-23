from __future__ import annotations

import logging
import os
from threading import RLock
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .llm_errors import CampusPilotLLMError, normalize_llm_exception
from .runtime_logging import log_event, runtime_logger


LOGGER = runtime_logger("llm")


class OpenAICompatibleChatClient:
    """Minimal OpenAI-compatible client with no SDK dependency."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        retry_delays: tuple[float, ...] = (0.5, 1.5),
        sleep_fn: Any = time.sleep,
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
        if not 0 <= max_retries <= 2:
            raise ValueError("max_retries must be between 0 and 2")
        if max_retries and not retry_delays:
            raise ValueError("retry_delays are required when retries are enabled")
        self.max_retries = max_retries
        self.retry_delays = retry_delays
        self.sleep_fn = sleep_fn
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
        provider = self._provider_name(base_url)
        prompt_chars = sum(
            len(str(message.get("content") or "")) for message in messages
        )
        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            started_at = time.perf_counter()
            log_event(
                LOGGER,
                "llm_request_started",
                provider=provider,
                model=model,
                attempt=attempt,
                prompt_chars=prompt_chars,
                tool_count=len(tools or []),
            )
            try:
                timeout = httpx.Timeout(
                    timeout_seconds,
                    connect=min(timeout_seconds, 10.0),
                )
                with httpx.Client(
                    timeout=timeout,
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
                if not isinstance(body, dict):
                    raise ValueError("OpenAI-compatible response must be an object")
                choices = body.get("choices") or []
                if not choices or not isinstance(choices[0].get("message"), dict):
                    raise ValueError("OpenAI-compatible response has no message")
                result = {
                    "message": choices[0]["message"],
                    "model": body.get("model", model),
                    "usage": body.get("usage", {}),
                }
            except Exception as exc:
                error = normalize_llm_exception(
                    exc,
                    provider=provider,
                    model=model,
                )
                duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
                log_event(
                    LOGGER,
                    "llm_request_failed",
                    level=(
                        logging.WARNING if error.retryable else logging.ERROR
                    ),
                    provider=provider,
                    model=model,
                    attempt=attempt,
                    duration_ms=duration_ms,
                    error_category=error.category.value,
                    error_type=error.detail_type,
                    retryable=error.retryable,
                    upstream_status=error.upstream_status,
                )
                if error.retryable and attempt < attempts:
                    delay = self.retry_delays[min(attempt - 1, len(self.retry_delays) - 1)]
                    log_event(
                        LOGGER,
                        "llm_retry",
                        level=logging.WARNING,
                        provider=provider,
                        model=model,
                        attempt=attempt + 1,
                        reason=error.category.value,
                        backoff_seconds=delay,
                    )
                    self.sleep_fn(delay)
                    continue
                raise error from exc
            duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
            content = result["message"].get("content")
            log_event(
                LOGGER,
                "llm_request_completed",
                provider=provider,
                model=result["model"],
                attempt=attempt,
                duration_ms=duration_ms,
                response_chars=len(content) if isinstance(content, str) else 0,
                token_usage=result["usage"],
            )
            return result
        raise RuntimeError("unreachable LLM retry state")

    @staticmethod
    def _provider_name(base_url: str) -> str:
        hostname = (urlparse(base_url).hostname or "").lower()
        if hostname == "open.bigmodel.cn":
            return "zhipu"
        if hostname.endswith("aliyuncs.com"):
            return "alibaba_cloud"
        if hostname == "api.openai.com":
            return "openai"
        return "openai_compatible"

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
            max_retries=int(
                os.environ.get("CAMPUSPILOT_OPENAI_MAX_RETRIES", "2")
            ),
        )
