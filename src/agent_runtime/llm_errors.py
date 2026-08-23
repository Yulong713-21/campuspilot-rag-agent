from __future__ import annotations

from enum import Enum
from typing import Any

import httpx


class LLMErrorCategory(str, Enum):
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    TIMEOUT = "timeout"
    UPSTREAM_5XX = "upstream_5xx"
    AUTH_ERROR = "auth_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


PUBLIC_ERROR_CODES = {
    LLMErrorCategory.RATE_LIMITED: "LLM_RATE_LIMITED",
    LLMErrorCategory.QUOTA_EXHAUSTED: "LLM_QUOTA_EXHAUSTED",
    LLMErrorCategory.TIMEOUT: "LLM_TIMEOUT",
    LLMErrorCategory.INVALID_REQUEST: "LLM_INVALID_REQUEST",
}


class CampusPilotLLMError(Exception):
    def __init__(
        self,
        category: LLMErrorCategory,
        *,
        provider: str | None = None,
        model: str | None = None,
        retryable: bool = False,
        upstream_status: int | None = None,
        detail_type: str | None = None,
    ) -> None:
        super().__init__(category.value)
        self.category = category
        self.provider = provider
        self.model = model
        self.retryable = retryable
        self.upstream_status = upstream_status
        self.detail_type = detail_type

    @property
    def public_code(self) -> str:
        return PUBLIC_ERROR_CODES.get(self.category, "LLM_UNAVAILABLE")

    @property
    def public_message(self) -> str:
        if self.category == LLMErrorCategory.RATE_LIMITED:
            return "AI assistant is temporarily rate limited."
        if self.category == LLMErrorCategory.INVALID_REQUEST:
            return "AI assistant could not process this request."
        return (
            "AI assistant is temporarily unavailable. "
            "Deterministic planning and university data services remain available."
        )


def _provider_error_fields(response: httpx.Response) -> tuple[str, str]:
    try:
        body: Any = response.json()
    except ValueError:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    error = body.get("error", body)
    if not isinstance(error, dict):
        return "", ""
    code = str(error.get("code") or body.get("code") or "").strip().lower()
    message = str(
        error.get("message") or body.get("message") or ""
    ).strip().lower()
    return code, message


def _is_quota_error(response: httpx.Response) -> bool:
    code, message = _provider_error_fields(response)
    quota_codes = {
        "insufficient_quota",
        "quota_exceeded",
        "quota_exhausted",
        "billing_quota_exceeded",
    }
    quota_phrases = (
        "insufficient quota",
        "quota exhausted",
        "quota exceeded",
        "billing quota",
        "额度不足",
        "余额不足",
    )
    return code in quota_codes or any(phrase in message for phrase in quota_phrases)


def normalize_llm_exception(
    exc: Exception,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> CampusPilotLLMError:
    if isinstance(exc, CampusPilotLLMError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return CampusPilotLLMError(
            LLMErrorCategory.TIMEOUT,
            provider=provider,
            model=model,
            retryable=True,
            detail_type=type(exc).__name__,
        )
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status_code = response.status_code
        if status_code == 429:
            category = (
                LLMErrorCategory.QUOTA_EXHAUSTED
                if _is_quota_error(response)
                else LLMErrorCategory.RATE_LIMITED
            )
            return CampusPilotLLMError(
                category,
                provider=provider,
                model=model,
                retryable=category == LLMErrorCategory.RATE_LIMITED,
                upstream_status=status_code,
                detail_type=type(exc).__name__,
            )
        if status_code in {500, 502, 503, 504}:
            return CampusPilotLLMError(
                LLMErrorCategory.UPSTREAM_5XX,
                provider=provider,
                model=model,
                retryable=True,
                upstream_status=status_code,
                detail_type=type(exc).__name__,
            )
        if status_code in {401, 403}:
            return CampusPilotLLMError(
                LLMErrorCategory.AUTH_ERROR,
                provider=provider,
                model=model,
                upstream_status=status_code,
                detail_type=type(exc).__name__,
            )
        code, _ = _provider_error_fields(response)
        if status_code == 404 and code in {"model_not_found", "model_unavailable"}:
            category = LLMErrorCategory.MODEL_UNAVAILABLE
        else:
            category = LLMErrorCategory.INVALID_REQUEST
        return CampusPilotLLMError(
            category,
            provider=provider,
            model=model,
            upstream_status=status_code,
            detail_type=type(exc).__name__,
        )
    if isinstance(exc, httpx.RequestError):
        return CampusPilotLLMError(
            LLMErrorCategory.NETWORK_ERROR,
            provider=provider,
            model=model,
            retryable=True,
            detail_type=type(exc).__name__,
        )
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return CampusPilotLLMError(
            LLMErrorCategory.INVALID_RESPONSE,
            provider=provider,
            model=model,
            detail_type=type(exc).__name__,
        )
    return CampusPilotLLMError(
        LLMErrorCategory.UNKNOWN,
        provider=provider,
        model=model,
        detail_type=type(exc).__name__,
    )


def llm_error_http_status(error: CampusPilotLLMError) -> int:
    if error.category == LLMErrorCategory.RATE_LIMITED:
        return 429
    if error.category == LLMErrorCategory.INVALID_REQUEST:
        return 422
    return 503
