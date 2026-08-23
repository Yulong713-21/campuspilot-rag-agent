from __future__ import annotations

from pathlib import Path
from io import StringIO
import logging
import sys
import unittest

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.openai_compatible_client import OpenAICompatibleChatClient
from agent_runtime.llm_errors import (  # noqa: E402
    CampusPilotLLMError,
    LLMErrorCategory,
)
from agent_runtime.runtime_logging import JsonLineFormatter  # noqa: E402


class OpenAICompatibleChatClientTest(unittest.TestCase):
    @staticmethod
    def client_for(
        handler,
        *,
        max_retries: int = 0,
        sleep_fn=lambda _: None,
    ) -> OpenAICompatibleChatClient:
        return OpenAICompatibleChatClient(
            api_key="sk-test-secret-should-not-appear",
            base_url="https://workspace.example/compatible-mode/v1",
            model="test-model",
            max_retries=max_retries,
            retry_delays=(0.0, 0.0),
            sleep_fn=sleep_fn,
            transport=httpx.MockTransport(handler),
        )

    def test_sends_bearer_token_without_exposing_it_in_result(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                request.headers["authorization"],
                "Bearer local-test-key",
            )
            self.assertEqual(
                str(request.url),
                "https://workspace.example/compatible-mode/v1/chat/completions",
            )
            return httpx.Response(
                200,
                request=request,
                json={
                    "model": "qwen-plus",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "ok",
                            }
                        }
                    ],
                    "usage": {"total_tokens": 12},
                },
            )

        client = OpenAICompatibleChatClient(
            api_key="local-test-key",
            base_url="https://workspace.example/compatible-mode/v1",
            model="qwen-plus",
            transport=httpx.MockTransport(handler),
        )
        result = client.chat([{"role": "user", "content": "hello"}])

        self.assertEqual(result["message"]["content"], "ok")
        self.assertNotIn("local-test-key", str(result))

    def test_normalizes_provider_failures(self) -> None:
        cases = [
            (
                429,
                {"error": {"code": "rate_limit", "message": "too many requests"}},
                LLMErrorCategory.RATE_LIMITED,
                True,
            ),
            (
                429,
                {
                    "error": {
                        "code": "insufficient_quota",
                        "message": "quota exhausted",
                    }
                },
                LLMErrorCategory.QUOTA_EXHAUSTED,
                False,
            ),
            (500, {"error": {"message": "failed"}}, LLMErrorCategory.UPSTREAM_5XX, True),
            (503, {"error": {"message": "busy"}}, LLMErrorCategory.UPSTREAM_5XX, True),
            (401, {"error": {"message": "bad key"}}, LLMErrorCategory.AUTH_ERROR, False),
        ]
        for status_code, body, category, retryable in cases:
            with self.subTest(status_code=status_code, category=category):
                def handler(request: httpx.Request, status=status_code, payload=body):
                    return httpx.Response(status, request=request, json=payload)

                client = self.client_for(handler)
                with self.assertRaises(CampusPilotLLMError) as raised:
                    client.chat([{"role": "user", "content": "safe test"}])

                self.assertEqual(raised.exception.category, category)
                self.assertEqual(raised.exception.retryable, retryable)

    def test_normalizes_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("provider read timeout", request=request)

        with self.assertRaises(CampusPilotLLMError) as raised:
            self.client_for(handler).chat(
                [{"role": "user", "content": "safe test"}]
            )

        self.assertEqual(raised.exception.category, LLMErrorCategory.TIMEOUT)
        self.assertTrue(raised.exception.retryable)

    def test_retries_503_but_not_401(self) -> None:
        transient_calls = 0
        delays: list[float] = []

        def transient_handler(request: httpx.Request) -> httpx.Response:
            nonlocal transient_calls
            transient_calls += 1
            if transient_calls < 3:
                return httpx.Response(503, request=request, json={"error": {}})
            return httpx.Response(
                200,
                request=request,
                json={
                    "model": "test-model",
                    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                },
            )

        result = self.client_for(
            transient_handler,
            max_retries=2,
            sleep_fn=delays.append,
        ).chat([{"role": "user", "content": "safe test"}])

        self.assertEqual(result["message"]["content"], "ok")
        self.assertEqual(transient_calls, 3)
        self.assertEqual(delays, [0.0, 0.0])

        auth_calls = 0

        def auth_handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_calls
            auth_calls += 1
            return httpx.Response(401, request=request, json={"error": {}})

        with self.assertRaises(CampusPilotLLMError):
            self.client_for(auth_handler, max_retries=2).chat(
                [{"role": "user", "content": "safe test"}]
            )
        self.assertEqual(auth_calls, 1)

    def test_logs_safe_summaries_without_key_or_prompt(self) -> None:
        output = StringIO()
        logger = logging.getLogger("campuspilot.runtime.llm")
        handler = logging.StreamHandler(output)
        handler.setFormatter(JsonLineFormatter())
        logger.addHandler(handler)
        try:
            def failing_handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(401, request=request, json={"error": {}})

            with self.assertRaises(CampusPilotLLMError):
                self.client_for(failing_handler).chat(
                    [
                        {
                            "role": "user",
                            "content": "private prompt should not appear",
                        }
                    ]
                )
        finally:
            logger.removeHandler(handler)

        rendered = output.getvalue()
        self.assertIn('"event":"llm_request_failed"', rendered)
        self.assertIn('"prompt_chars":32', rendered)
        self.assertNotIn("sk-test-secret-should-not-appear", rendered)
        self.assertNotIn("private prompt should not appear", rendered)


if __name__ == "__main__":
    unittest.main()
