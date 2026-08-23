from __future__ import annotations

import os
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

from agent_runtime.admin_config import EnvironmentConfigStore  # noqa: E402
from agent_runtime.api import create_app  # noqa: E402


class EnvironmentConfigStoreTest(unittest.TestCase):
    def test_update_preserves_comments_and_never_returns_full_secret(self) -> None:
        with TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "# keep this comment\n"
                "UNRELATED_SETTING=keep-me\n"
                "CAMPUSPILOT_OPENAI_MODEL=old-model\n",
                encoding="utf-8",
            )
            store = EnvironmentConfigStore(env_file)
            with patch.dict(os.environ, {}, clear=True):
                store.update(
                    {"openai_model": "new-model"},
                    api_key="secret-key-1234",
                )
                public = store.public_config()

            content = env_file.read_text(encoding="utf-8")
            self.assertIn("# keep this comment", content)
            self.assertIn("UNRELATED_SETTING=keep-me", content)
            self.assertIn("CAMPUSPILOT_OPENAI_MODEL=new-model", content)
            self.assertTrue(public["api_key_configured"])
            self.assertEqual(public["api_key_hint"], "...1234")
            self.assertNotIn("secret-key-1234", str(public))


class LocalAdminApiTest(unittest.TestCase):
    def _environment(self, env_file: Path) -> dict[str, str]:
        return {
            "CAMPUSPILOT_ADMIN_ENABLED": "1",
            "CAMPUSPILOT_ADMIN_LOCAL_ONLY": "0",
            "CAMPUSPILOT_ADMIN_TOKEN": "admin-test-token",
            "CAMPUSPILOT_ENV_FILE": str(env_file),
            "CAMPUSPILOT_CLOUD_LLM_ENABLED": "1",
            "CAMPUSPILOT_OPENAI_API_KEY": "test-api-key",
            "CAMPUSPILOT_OPENAI_BASE_URL": "https://example.test/v1",
            "CAMPUSPILOT_OPENAI_MODEL": "model-before",
            "CAMPUSPILOT_OPENAI_TIMEOUT_SECONDS": "30",
            "CAMPUSPILOT_VECTOR_SEARCH_ENABLED": "0",
            "CAMPUSPILOT_RETRIEVAL_MODE": "full_bm25",
        }

    def test_admin_page_is_hidden_when_feature_is_disabled(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "CAMPUSPILOT_ADMIN_ENABLED": "0",
                    "CAMPUSPILOT_VECTOR_SEARCH_ENABLED": "0",
                    "CAMPUSPILOT_CLOUD_LLM_ENABLED": "0",
                },
                clear=False,
            ),
            TemporaryDirectory(dir=REPO_ROOT / "logs") as temp_dir,
            TestClient(
                create_app(database_path=Path(temp_dir) / "admin-off.sqlite3")
            ) as client,
        ):
            response = client.get("/admin")

        self.assertEqual(response.status_code, 404)

    def test_config_requires_admin_token_and_does_not_return_key(self) -> None:
        with TemporaryDirectory(dir=REPO_ROOT / "logs") as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("# local test\n", encoding="utf-8")
            with (
                patch.dict(os.environ, self._environment(env_file), clear=False),
                TestClient(
                    create_app(database_path=Path(temp_dir) / "admin.sqlite3")
                ) as client,
            ):
                denied = client.get("/api/admin/config")
                allowed = client.get(
                    "/api/admin/config",
                    headers={"X-CampusPilot-Admin-Token": "admin-test-token"},
                )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(allowed.status_code, 200)
        payload = allowed.json()["config"]
        self.assertTrue(payload["api_key_configured"])
        self.assertNotIn("test-api-key", allowed.text)

    def test_model_update_is_hot_applied_and_persisted(self) -> None:
        with TemporaryDirectory(dir=REPO_ROOT / "logs") as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "CAMPUSPILOT_OPENAI_MODEL=model-before\n",
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, self._environment(env_file), clear=False),
                TestClient(
                    app := create_app(
                        database_path=Path(temp_dir) / "admin-update.sqlite3"
                    )
                ) as client,
            ):
                response = client.put(
                    "/api/admin/config",
                    headers={"X-CampusPilot-Admin-Token": "admin-test-token"},
                    json={
                        "openai_model": "model-after",
                        "openai_timeout_seconds": 45,
                    },
                )
                runtime_model = app.state.cloud_client.model
                saved_env = env_file.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(runtime_model, "model-after")
        self.assertEqual(
            response.json()["hot_applied_fields"],
            ["openai_model", "openai_timeout_seconds"],
        )
        self.assertEqual(response.json()["restart_required_fields"], [])
        self.assertIn(
            "CAMPUSPILOT_OPENAI_MODEL=model-after",
            saved_env,
        )

    def test_llm_test_returns_usage_without_exposing_secret(self) -> None:
        with TemporaryDirectory(dir=REPO_ROOT / "logs") as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text("# test\n", encoding="utf-8")
            calls: list[dict] = []

            def fake_chat(client, messages, **kwargs):
                calls.append({"messages": messages, **kwargs})
                return {
                    "message": {"role": "assistant", "content": "连接正常。"},
                    "model": client.model,
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                }

            with (
                patch.dict(os.environ, self._environment(env_file), clear=False),
                patch(
                    "agent_runtime.api.OpenAICompatibleChatClient.chat",
                    new=fake_chat,
                ),
                TestClient(
                    create_app(
                        database_path=Path(temp_dir) / "admin-test-llm.sqlite3"
                    )
                ) as client,
            ):
                response = client.post(
                    "/api/admin/llm/test",
                    headers={"X-CampusPilot-Admin-Token": "admin-test-token"},
                    json={
                        "prompt": "只回复连接正常",
                        "temperature": 0.3,
                        "max_tokens": 64,
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "连接正常。")
        self.assertEqual(response.json()["usage"]["prompt_tokens"], 10)
        self.assertEqual(calls[0]["temperature"], 0.3)
        self.assertEqual(calls[0]["max_tokens"], 64)
        self.assertNotIn("test-api-key", response.text)


if __name__ == "__main__":
    unittest.main()
