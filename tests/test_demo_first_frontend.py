from __future__ import annotations

from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPO_ROOT / "frontend"
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.api import create_app  # noqa: E402


class PiaFirstFrontendTest(unittest.TestCase):
    def test_homepage_is_pia_workspace_with_embedded_verified_workflow(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("CampusPilot · AI Workspace", response.text)
        self.assertIn('id="chatForm"', response.text)
        self.assertIn('id="verifiedWorkflow"', response.text)
        self.assertIn('id="runVerifiedButton"', response.text)
        self.assertIn("试试 C6001 规划", response.text)
        self.assertIn("Verified", response.text)
        self.assertIn("id=\"planForm\"", response.text)
        self.assertIn("id=\"evidenceGrid\"", response.text)
        self.assertNotIn("id=\"admissionForm\"", response.text)
        self.assertNotIn("C6001 Planner Demo", response.text)
        self.assertNotIn("运行推荐演示", response.text)

    def test_frontend_uses_es_modules_without_monolithic_app(self) -> None:
        index = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((FRONTEND_ROOT / "js").rglob("*.js"))
        )

        self.assertIn('type="module"', index)
        self.assertIn("/static/js/workspace-page.js", index)
        self.assertFalse((FRONTEND_ROOT / "app.js").exists())
        self.assertFalse((FRONTEND_ROOT / "js" / "planner-page.js").exists())
        self.assertNotIn("function setBusy", javascript)
        self.assertNotIn('document.querySelectorAll("button")', javascript)
        self.assertIn("runButtonTask", javascript)
        self.assertIn('/api/agent/chat', javascript)
        self.assertIn('/api/plans/generate', javascript)

    def test_workspace_exposes_accessible_navigation_and_scoped_surfaces(self) -> None:
        index = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
        workflow = (
            FRONTEND_ROOT / "js" / "workflows" / "c6001.js"
        ).read_text(encoding="utf-8")

        self.assertIn('aria-label="CampusPilot 功能导航"', index)
        self.assertIn('role="log"', index)
        self.assertIn('aria-controls="planResults"', index)
        self.assertIn('for="chatInput"', index)
        self.assertIn('id="planningOutput"', index)
        self.assertIn("我想尽快毕业，帮我规划一下", workflow)

    def test_evidence_is_a_first_class_card_surface(self) -> None:
        index = (FRONTEND_ROOT / "index.html").read_text(encoding="utf-8")
        evidence = (
            FRONTEND_ROOT / "js" / "planner" / "evidence.js"
        ).read_text(encoding="utf-8")

        self.assertIn("OFFICIAL EVIDENCE", index)
        self.assertIn("evidence-card", evidence)
        self.assertIn("打开官方原文", evidence)


if __name__ == "__main__":
    unittest.main()
