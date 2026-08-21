from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

from .tools import EduRAGTools


class RuleBasedToolAgent:
    """Minimal stepping stone before real LLM tool calling.

    This still uses deterministic routing, but it establishes the same tool
    boundary we will later expose to LLM tool calling, LangChain, LangGraph, and
    MCP.
    """

    def _route_after_faq(self, faq_result: dict[str, Any]) -> dict[str, str]:
        faq_data = faq_result.get("data", {})
        if not faq_result.get("ok"):
            return {"route": "rag_search", "reason": "faq_error"}
        if faq_data.get("hit"):
            return {"route": "faq_answer", "reason": "faq_hit"}
        return {"route": "rag_search", "reason": "faq_miss"}

    def _should_call_rag(self, faq_result: dict[str, Any]) -> bool:
        return self._route_after_faq(faq_result)["route"] == "rag_search"

    def _route_after_rag(self, rag_result: dict[str, Any]) -> dict[str, str]:
        if not rag_result.get("ok"):
            if rag_result.get("retryable"):
                return {"route": "retry_rag", "reason": "rag_retryable_error"}
            return {"route": "handle_tool_error", "reason": "rag_non_retryable_error"}
        documents = rag_result.get("data", {}).get("documents", [])
        if documents:
            return {"route": "generate_answer", "reason": "rag_documents_found"}
        return {"route": "ask_clarification", "reason": "rag_empty"}

    def __init__(
        self,
        tools: EduRAGTools | None = None,
        max_rag_retries: int = 1,
        backoff_base_seconds: float = 0.2,
        max_backoff_seconds: float = 5.0,
        sleeper: Callable[[float], None] | None = None,
        jitter: Callable[[float], float] | None = None,
        clock: Callable[[], float] | None = None,
        minimum_retry_call_budget_seconds: float = 0.0,
    ) -> None:
        if max_rag_retries < 0:
            raise ValueError("max_rag_retries must be at least 0")
        if backoff_base_seconds < 0:
            raise ValueError("backoff_base_seconds must be at least 0")
        if max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds must be at least 0")
        if minimum_retry_call_budget_seconds < 0:
            raise ValueError("minimum_retry_call_budget_seconds must be at least 0")
        self.tools = tools or EduRAGTools()
        self.max_rag_retries = max_rag_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.sleeper = sleeper or time.sleep
        self.jitter = jitter or (lambda upper_bound: random.uniform(0.0, upper_bound))
        self.clock = clock or time.monotonic
        self.minimum_retry_call_budget_seconds = minimum_retry_call_budget_seconds

    def _backoff_cap_seconds(self, retry_count: int) -> float:
        exponential_delay = self.backoff_base_seconds * (2**retry_count)
        return min(exponential_delay, self.max_backoff_seconds)

    def _backoff_seconds(self, retry_count: int) -> float:
        upper_bound = self._backoff_cap_seconds(retry_count)
        jittered_delay = self.jitter(upper_bound)
        return min(max(jittered_delay, 0.0), upper_bound)

    def _time_budget(self, started_at: float, timeout_seconds: float | None) -> dict[str, Any]:
        elapsed_seconds = max(self.clock() - started_at, 0.0)
        remaining_seconds = (
            None
            if timeout_seconds is None
            else max(timeout_seconds - elapsed_seconds, 0.0)
        )
        return {
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "remaining_seconds": (
                None if remaining_seconds is None else round(remaining_seconds, 3)
            ),
        }

    def _call_rag(
        self,
        query: str,
        source_filter: str | None,
        deadline: float | None,
    ) -> dict[str, Any]:
        remaining_seconds = (
            None if deadline is None else max(deadline - self.clock(), 0.0)
        )
        if remaining_seconds is None:
            result = self.tools.search_rag(query, source_filter=source_filter)
        else:
            result = self.tools.search_rag(
                query,
                source_filter=source_filter,
                timeout_seconds=remaining_seconds,
            )
        result["timeout_seconds"] = (
            None if remaining_seconds is None else round(remaining_seconds, 3)
        )
        return result

    def answer(
        self,
        query: str,
        source_filter: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be at least 0")

        started_at = self.clock()
        deadline = None if timeout_seconds is None else started_at + timeout_seconds
        trace: list[dict[str, Any]] = []

        faq_result = self.tools.search_faq(query)
        trace.append(faq_result)
        route = self._route_after_faq(faq_result)
        route_trace: list[dict[str, Any]] = [{"stage": "after_faq", **route}]

        if route["route"] == "faq_answer":
            faq_data = faq_result.get("data", {})
            return {
                "answer": faq_data.get("answer"),
                "answer_source": "faq",
                "documents": [],
                "confidence": "high",
                "next_action": "answer_user",
                "original_query": query,
                "effective_query": query,
                "retry_count": 0,
                "trace": trace,
                "trace_tools": [step["tool"] for step in trace],
                "route_reason": route["reason"],
                "route_trace": route_trace,
                "time_budget": self._time_budget(started_at, timeout_seconds),
            }

        rag_result = self._call_rag(query, source_filter, deadline)
        trace.append(rag_result)

        retry_count = 0
        route = self._route_after_rag(rag_result)
        route_trace.append({"stage": "after_rag", **route})

        while route["route"] == "retry_rag" and retry_count < self.max_rag_retries:
            backoff_cap_seconds = self._backoff_cap_seconds(retry_count)
            backoff_seconds = self._backoff_seconds(retry_count)
            remaining_seconds = (
                None if deadline is None else max(deadline - self.clock(), 0.0)
            )
            required_seconds = backoff_seconds + self.minimum_retry_call_budget_seconds

            if remaining_seconds is not None and remaining_seconds <= required_seconds:
                route = {
                    "route": "handle_deadline_exhausted",
                    "reason": "rag_deadline_exhausted",
                }
                route_trace.append(
                    {
                        "stage": "before_rag_retry",
                        **route,
                        "retry_attempt": retry_count + 1,
                        "remaining_seconds": round(remaining_seconds, 3),
                        "required_seconds": round(required_seconds, 3),
                    }
                )
                break

            route_trace.append(
                {
                    "stage": "before_rag_retry",
                    "route": "wait_and_retry",
                    "reason": "rag_retry_scheduled",
                    "retry_attempt": retry_count + 1,
                    "backoff_cap_seconds": backoff_cap_seconds,
                    "backoff_seconds": backoff_seconds,
                    "remaining_seconds": (
                        None if remaining_seconds is None else round(remaining_seconds, 3)
                    ),
                    "required_seconds": round(required_seconds, 3),
                }
            )
            self.sleeper(backoff_seconds)

            if deadline is not None and self.clock() >= deadline:
                route = {
                    "route": "handle_deadline_exhausted",
                    "reason": "rag_deadline_exhausted",
                }
                route_trace.append(
                    {
                        "stage": "after_rag_backoff",
                        **route,
                        "retry_attempt": retry_count + 1,
                    }
                )
                break

            retry_count += 1

            rag_result = self._call_rag(query, source_filter, deadline)
            trace.append(rag_result)
            route = self._route_after_rag(rag_result)
            route_trace.append(
                {
                    "stage": "after_rag_retry",
                    **route,
                    "retry_attempt": retry_count,
                }
            )

        if route["route"] == "retry_rag":
            route = {"route": "handle_retry_exhausted", "reason": "rag_retry_exhausted"}
            route_trace.append({"stage": "after_retry_budget", **route})

        documents = rag_result.get("data", {}).get("documents", [])

        if route["route"] == "generate_answer":
            answer_source = "rag_context"
            confidence = "medium"
            next_action = "generate_answer_from_context"
        elif route["route"] == "ask_clarification":
            answer_source = "no_answer"
            confidence = "low"
            next_action = "ask_clarification_or_create_ticket"
        else:
            answer_source = "tool_error"
            confidence = "low"
            next_action = (
                "create_ticket_after_retry_exhausted"
                if route["route"] == "handle_retry_exhausted"
                else (
                    "fallback_after_deadline_exhausted"
                    if route["route"] == "handle_deadline_exhausted"
                    else "create_ticket_or_fix_request"
                )
            )

        return {
            "answer": None,
            "answer_source": answer_source,
            "documents": documents,
            "confidence": confidence,
            "next_action": next_action,
            "original_query": query,
            "effective_query": query,
            "retry_count": retry_count,
            "trace": trace,
            "trace_tools": [step["tool"] for step in trace],
            "route_reason": route["reason"],
            "route_trace": route_trace,
            "time_budget": self._time_budget(started_at, timeout_seconds),
        }
