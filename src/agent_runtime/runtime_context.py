from __future__ import annotations

from contextvars import ContextVar, Token


request_id_context: ContextVar[str | None] = ContextVar(
    "campuspilot_request_id",
    default=None,
)


def current_request_id() -> str | None:
    return request_id_context.get()


def bind_request_id(request_id: str) -> Token[str | None]:
    return request_id_context.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    request_id_context.reset(token)
