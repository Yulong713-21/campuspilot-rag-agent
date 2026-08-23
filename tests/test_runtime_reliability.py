from __future__ import annotations

from io import StringIO
import json
import logging
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.api import RUNTIME_LOGGER, create_app  # noqa: E402
from agent_runtime.runtime_logging import JsonLineFormatter  # noqa: E402


class RuntimeReliabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        logs_dir = REPO_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = TemporaryDirectory(dir=logs_dir)
        database = Path(self.temp_dir.name) / "runtime-reliability.sqlite3"
        self.client_context = TestClient(create_app(database_path=database))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_generates_and_returns_request_id(self) -> None:
        response = self.client.get("/health/live")

        request_id = response.headers["X-Request-ID"]
        self.assertRegex(request_id, r"^[0-9a-f]{32}$")

    def test_reuses_valid_request_id_and_replaces_invalid_value(self) -> None:
        accepted = self.client.get(
            "/health/live",
            headers={"X-Request-ID": "demo-request_2026.08:23"},
        )
        replaced = self.client.get(
            "/health/live",
            headers={"X-Request-ID": "invalid request id with spaces"},
        )

        self.assertEqual(
            accepted.headers["X-Request-ID"],
            "demo-request_2026.08:23",
        )
        self.assertNotEqual(
            replaced.headers["X-Request-ID"],
            "invalid request id with spaces",
        )
        self.assertRegex(replaced.headers["X-Request-ID"], r"^[0-9a-f]{32}$")

    def test_request_logs_share_id_without_sensitive_headers(self) -> None:
        output = StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(JsonLineFormatter())
        RUNTIME_LOGGER.addHandler(handler)
        try:
            response = self.client.get(
                "/health/live",
                headers={
                    "X-Request-ID": "trace-safe-001",
                    "Authorization": "Bearer sk-test-secret-should-not-appear",
                    "Cookie": "session=private-test-cookie",
                },
            )
        finally:
            RUNTIME_LOGGER.removeHandler(handler)

        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [event["event"] for event in events],
            ["request_started", "request_completed"],
        )
        self.assertTrue(
            all(event["request_id"] == "trace-safe-001" for event in events)
        )
        rendered = output.getvalue()
        self.assertNotIn("sk-test-secret-should-not-appear", rendered)
        self.assertNotIn("private-test-cookie", rendered)
        self.assertNotIn("Authorization", rendered)


if __name__ == "__main__":
    unittest.main()
