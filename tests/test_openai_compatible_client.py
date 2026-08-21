from __future__ import annotations

from pathlib import Path
import sys
import unittest

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.openai_compatible_client import OpenAICompatibleChatClient


class OpenAICompatibleChatClientTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

