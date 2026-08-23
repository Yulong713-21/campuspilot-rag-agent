from __future__ import annotations

from io import StringIO
import json
import logging
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.api import RUNTIME_LOGGER, create_app  # noqa: E402
from agent_runtime.runtime_logging import JsonLineFormatter  # noqa: E402
from agent_runtime.llm_errors import (  # noqa: E402
    CampusPilotLLMError,
    LLMErrorCategory,
)


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

    def test_chat_planner_degrades_when_cloud_quota_is_exhausted(self) -> None:
        class QuotaExhaustedClient:
            base_url = "https://open.bigmodel.cn/api/paas/v4"
            model = "test-model"

            def chat(self, *args, **kwargs):
                raise CampusPilotLLMError(
                    LLMErrorCategory.QUOTA_EXHAUSTED,
                    provider="zhipu",
                    model=self.model,
                )

        database = Path(self.temp_dir.name) / "quota-degraded.sqlite3"
        with (
            patch.dict(
                "os.environ",
                {"CAMPUSPILOT_CLOUD_LLM_ENABLED": "1"},
            ),
            patch(
                "agent_runtime.api.OpenAICompatibleChatClient.from_environment",
                return_value=QuotaExhaustedClient(),
            ),
            TestClient(create_app(database_path=database)) as client,
        ):
            response = client.post(
                "/api/agent/chat",
                headers={"X-Request-ID": "planner-quota-001"},
                json={
                    "message": "Please generate a study plan",
                    "program_variant_id": "MONASH-C6001-EL2",
                    "study_stream": "Industry Experience",
                },
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["study_plans"]["plans"])
        self.assertTrue(payload["study_plans"]["validation"]["all_valid"])
        self.assertTrue(payload["degraded"])
        self.assertEqual(
            payload["degradation"],
            {"component": "llm", "reason": "quota_exhausted"},
        )
        self.assertEqual(response.headers["X-Request-ID"], "planner-quota-001")

    def test_unhandled_llm_failure_has_stable_error_and_request_id(self) -> None:
        class FailingSemesterAdvisor:
            def explain(self, **facts):
                raise CampusPilotLLMError(
                    LLMErrorCategory.TIMEOUT,
                    provider="openai_compatible",
                    model="test-model",
                    retryable=True,
                    detail_type="ReadTimeout",
                )

        database = Path(self.temp_dir.name) / "llm-error-response.sqlite3"
        with TestClient(
            create_app(
                database_path=database,
                semester_advisor=FailingSemesterAdvisor(),
            )
        ) as client:
            response = client.post(
                "/api/plans/semesters/explain",
                headers={"X-Request-ID": "llm-timeout-001"},
                json={
                    "program_variant_id": "MONASH-C6001-EL2",
                    "handbook_year": 2026,
                    "study_stream": "Industry Experience",
                    "completed_courses": ["FIT5057"],
                    "plan_id": "fastest",
                    "semester": "2026 S2",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "LLM_TIMEOUT",
                    "message": (
                        "AI assistant is temporarily unavailable. "
                        "Deterministic planning and university data services remain available."
                    ),
                    "request_id": "llm-timeout-001",
                }
            },
        )
        self.assertEqual(response.headers["X-Request-ID"], "llm-timeout-001")

    def test_generic_chat_llm_failure_has_stable_public_error(self) -> None:
        failure = CampusPilotLLMError(
            LLMErrorCategory.MODEL_UNAVAILABLE,
            provider="openai_compatible",
            model="test-model",
            retryable=True,
        )
        database = Path(self.temp_dir.name) / "generic-chat-error.sqlite3"
        with (
            patch(
                "agent_runtime.api.CampusPilotConversationGraph.respond",
                side_effect=failure,
            ),
            TestClient(create_app(database_path=database)) as client,
        ):
            response = client.post(
                "/api/agent/chat",
                headers={"X-Request-ID": "generic-chat-failure-001"},
                json={"message": "Help me choose a program"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {
                "error": {
                    "code": "LLM_UNAVAILABLE",
                    "message": (
                        "AI assistant is temporarily unavailable. "
                        "Deterministic planning and university data services remain available."
                    ),
                    "request_id": "generic-chat-failure-001",
                }
            },
        )
        self.assertEqual(
            response.headers["X-Request-ID"],
            "generic-chat-failure-001",
        )

    def test_health_exposes_safe_runtime_metadata(self) -> None:
        database = Path(self.temp_dir.name) / "health-metadata.sqlite3"
        with (
            patch.dict(
                "os.environ",
                {
                    "CAMPUSPILOT_GIT_SHA": "abc123def4567890",
                    "CAMPUSPILOT_ENV": "test",
                },
            ),
            TestClient(create_app(database_path=database)) as client,
        ):
            payload = client.get("/health").json()

        self.assertEqual(payload["commit"], "abc123def456")
        self.assertEqual(payload["environment"], "test")
        self.assertIn("version", payload)
        self.assertIn("uptime_seconds", payload)
        self.assertNotIn("base_url", payload)
        self.assertNotIn("api_key", payload)


if __name__ == "__main__":
    unittest.main()
