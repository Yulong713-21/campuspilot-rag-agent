from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.dify_adapter import DifyWorkflowClient


class DifyWorkflowClientTest(unittest.TestCase):
    def test_uses_server_side_key_and_blocking_workflow_contract(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "workflow_run_id": "run-1",
                    "data": {
                        "status": "succeeded",
                        "outputs": {"answer": "ok"},
                        "elapsed_time": 1.2,
                        "total_tokens": 88,
                    },
                },
            )

        client = DifyWorkflowClient(
            api_base_url="https://api.dify.example/v1/",
            api_key="server-secret",
            transport=httpx.MockTransport(handler),
        )

        result = client.run_workflow(
            inputs={"query": "compare programs"},
            user_id="user-001",
        )

        self.assertEqual(captured["authorization"], "Bearer server-secret")
        self.assertEqual(
            captured["body"],
            {
                "inputs": {"query": "compare programs"},
                "response_mode": "blocking",
                "user": "user-001",
            },
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["outputs"], {"answer": "ok"})


if __name__ == "__main__":
    unittest.main()
