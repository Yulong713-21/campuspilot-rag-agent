from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.ollama_client import OllamaChatClient


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class OllamaChatClientTest(unittest.TestCase):
    @patch("agent_runtime.ollama_client.urllib.request.urlopen")
    def test_chat_sends_tool_schema_and_returns_tool_calls(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeHTTPResponse(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "search_faq",
                                "arguments": {"query": "课程问题"},
                            },
                        }
                    ],
                }
            }
        )
        client = OllamaChatClient(model="qwen3:1.7b")
        tool_schema = {
            "type": "function",
            "function": {
                "name": "search_faq",
                "description": "查询 FAQ",
                "parameters": {"type": "object", "properties": {}},
            },
        }

        message = client.chat(
            [{"role": "user", "content": "课程问题"}],
            tools=[tool_schema],
            timeout_seconds=3.0,
        )

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["tools"], [tool_schema])
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 3.0)
        self.assertEqual(
            message["tool_calls"][0]["function"]["name"],
            "search_faq",
        )

    @patch("agent_runtime.ollama_client.urllib.request.urlopen")
    def test_chat_sends_structured_output_schema(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeHTTPResponse(
            {
                "message": {
                    "role": "assistant",
                    "content": '{"passed":true}',
                }
            }
        )
        client = OllamaChatClient(model="qwen3.5:0.8b", temperature=0.0)
        schema = {
            "type": "object",
            "properties": {"passed": {"type": "boolean"}},
            "required": ["passed"],
        }

        client.chat(
            [{"role": "user", "content": "判断答案"}],
            format_schema=schema,
        )

        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["format"], schema)
        self.assertEqual(payload["options"]["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()
