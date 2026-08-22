from __future__ import annotations

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

from agent_runtime.api import create_app


class AgentAPITest(unittest.TestCase):
    def setUp(self) -> None:
        logs_dir = REPO_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = TemporaryDirectory(dir=logs_dir)
        self.database = Path(self.temp_dir.name) / "agent-api.sqlite3"
        self.tokens = {
            "alice-token": "alice",
            "bob-token": "bob",
        }
        self.action = {
            "tool_name": "send_email",
            "arguments": {
                "recipients": ["all-students@example.com"],
                "subject": "课程通知",
            },
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def client(self) -> TestClient:
        return TestClient(
            create_app(
                database_path=self.database,
                token_to_user=self.tokens,
            )
        )

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_requires_valid_bearer_token(self) -> None:
        with self.client() as client:
            missing = client.get("/approval/unknown")
            invalid = client.get(
                "/approval/unknown",
                headers=self.auth("invalid"),
            )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)

    def test_root_serves_user_workspace(self) -> None:
        with self.client() as client:
            response = client.get("/")
            stylesheet = client.get("/static/app.css")
            script = client.get("/static/app.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn("CampusPilot", response.text)
        self.assertIn("Pia 对话", response.text)
        self.assertIn("申请评估", response.text)
        self.assertIn('id="transcriptFile"', response.text)
        self.assertEqual(stylesheet.status_code, 200)
        self.assertIn("/api/agent/chat", script.text)
        self.assertIn("/api/admissions/transcripts/parse", script.text)
        self.assertIn("/api/admissions/evaluate", script.text)
        self.assertNotIn("alice-demo-token", script.text)

    def test_anonymous_session_can_own_approval_thread(self) -> None:
        with self.client() as client:
            session = client.post("/api/session").json()
            headers = self.auth(session["access_token"])
            started = client.post(
                "/approval/anonymous-thread-001/start",
                headers=headers,
                json=self.action,
            )
            inspected = client.get(
                "/approval/anonymous-thread-001",
                headers=headers,
            )

        self.assertEqual(started.status_code, 200)
        self.assertEqual(inspected.status_code, 200)
        self.assertEqual(session["token_type"], "bearer")

    def test_anonymous_session_survives_app_restart(self) -> None:
        with self.client() as client:
            session = client.post("/api/session").json()
        with self.client() as restarted:
            response = restarted.get(
                "/approval/missing-thread-001",
                headers=self.auth(session["access_token"]),
            )

        self.assertEqual(response.status_code, 404)

    def test_expensive_endpoint_rate_limit_is_configurable(self) -> None:
        with patch.dict(
            "os.environ",
            {"CAMPUSPILOT_RATE_LIMIT_PER_MINUTE": "1"},
        ):
            with self.client() as client:
                first = client.post(
                    "/api/agent/chat",
                    json={"message": "what can you do"},
                )
                second = client.post(
                    "/api/agent/chat",
                    json={"message": "what can you do"},
                )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)

    def test_chat_message_has_public_request_size_limit(self) -> None:
        with self.client() as client:
            response = client.post(
                "/api/agent/chat",
                json={"message": "x" * 4001},
            )

        self.assertEqual(response.status_code, 422)

    def test_empty_token_mapping_does_not_enable_demo_tokens(self) -> None:
        app = create_app(
            database_path=self.database,
            token_to_user={},
        )
        with TestClient(app) as client:
            response = client.get(
                "/approval/unknown",
                headers=self.auth("alice-demo-token"),
            )

        self.assertEqual(response.status_code, 401)

    def test_production_environment_disables_default_demo_tokens(self) -> None:
        with patch.dict(
            "os.environ",
            {"CAMPUSPILOT_ENV": "production"},
        ):
            app = create_app(database_path=self.database)
            with TestClient(app) as client:
                response = client.get(
                    "/approval/unknown-thread",
                    headers=self.auth("alice-demo-token"),
                )

        self.assertEqual(response.status_code, 401)

    def test_owner_can_start_inspect_and_resume(self) -> None:
        with self.client() as client:
            started = client.post(
                "/approval/thread-1/start",
                headers=self.auth("alice-token"),
                json=self.action,
            )
            inspected = client.get(
                "/approval/thread-1",
                headers=self.auth("alice-token"),
            )
            resumed = client.post(
                "/approval/thread-1/resume",
                headers=self.auth("alice-token"),
                json={"approved": True},
            )

        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["status"], "pending")
        self.assertTrue(inspected.json()["has_pending_interrupt"])
        self.assertEqual(inspected.json()["action"], self.action)
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["status"], "executed")
        self.assertEqual(resumed.json()["execution_count"], 1)

    def test_other_user_cannot_inspect_or_resume_thread(self) -> None:
        with self.client() as client:
            client.post(
                "/approval/private-thread/start",
                headers=self.auth("alice-token"),
                json=self.action,
            )
            inspected = client.get(
                "/approval/private-thread",
                headers=self.auth("bob-token"),
            )
            resumed = client.post(
                "/approval/private-thread/resume",
                headers=self.auth("bob-token"),
                json={"approved": True},
            )
            owner_view = client.get(
                "/approval/private-thread",
                headers=self.auth("alice-token"),
            )

        self.assertEqual(inspected.status_code, 404)
        self.assertEqual(resumed.status_code, 404)
        self.assertEqual(owner_view.json()["status"], "pending")
        self.assertEqual(owner_view.json()["execution_count"], 0)

    def test_duplicate_start_and_duplicate_resume_are_conflicts(self) -> None:
        with self.client() as client:
            client.post(
                "/approval/thread-conflict/start",
                headers=self.auth("alice-token"),
                json=self.action,
            )
            duplicate_start = client.post(
                "/approval/thread-conflict/start",
                headers=self.auth("alice-token"),
                json=self.action,
            )
            client.post(
                "/approval/thread-conflict/resume",
                headers=self.auth("alice-token"),
                json={"approved": True},
            )
            duplicate_resume = client.post(
                "/approval/thread-conflict/resume",
                headers=self.auth("alice-token"),
                json={"approved": True},
            )

        self.assertEqual(duplicate_start.status_code, 409)
        self.assertEqual(duplicate_resume.status_code, 409)

    def test_new_app_process_resumes_persisted_owner_thread(self) -> None:
        with self.client() as first_client:
            started = first_client.post(
                "/approval/restart-thread/start",
                headers=self.auth("alice-token"),
                json=self.action,
            )
        with self.client() as second_client:
            resumed = second_client.post(
                "/approval/restart-thread/resume",
                headers=self.auth("alice-token"),
                json={"approved": False},
            )

        self.assertEqual(started.json()["status"], "pending")
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
