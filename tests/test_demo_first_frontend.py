from __future__ import annotations

from pathlib import Path
import sys
import unittest

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = REPO_ROOT / "static"
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.api import create_app  # noqa: E402


class DemoFirstFrontendTest(unittest.TestCase):
    def test_homepage_prioritizes_c6001_planner(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("C6001 Planner Demo", response.text)
        self.assertIn("id=\"planForm\"", response.text)
        self.assertIn("id=\"evidenceGrid\"", response.text)
        self.assertNotIn("id=\"chatForm\"", response.text)
        self.assertNotIn("id=\"admissionForm\"", response.text)

    def test_frontend_uses_es_modules_without_monolithic_app(self) -> None:
        index = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((STATIC_ROOT / "js").rglob("*.js"))
        )

        self.assertIn('type="module"', index)
        self.assertIn("/static/js/planner-page.js", index)
        self.assertFalse((STATIC_ROOT / "app.js").exists())
        self.assertNotIn("function setBusy", javascript)
        self.assertNotIn('document.querySelectorAll("button")', javascript)
        self.assertIn("runButtonTask", javascript)

    def test_evidence_is_a_first_class_card_surface(self) -> None:
        index = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        evidence = (
            STATIC_ROOT / "js" / "planner" / "evidence.js"
        ).read_text(encoding="utf-8")

        self.assertIn("OFFICIAL EVIDENCE", index)
        self.assertIn("evidence-card", evidence)
        self.assertIn("打开官方原文", evidence)


if __name__ == "__main__":
    unittest.main()
