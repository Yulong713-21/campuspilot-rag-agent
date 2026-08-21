from __future__ import annotations

from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import unittest

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.source_sync import OfficialSourceSynchronizer


class OfficialSourceSynchronizerTest(unittest.TestCase):
    def test_detects_new_unchanged_and_changed_content(self) -> None:
        content = b"official handbook version"
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=content,
                headers={"content-type": "text/html"},
            )
        )
        synchronizer = OfficialSourceSynchronizer(transport=transport)
        source = {"source_id": "handbook", "url": "https://example.edu"}

        new_check, _ = synchronizer.check(source, None)
        unchanged_check, _ = synchronizer.check(
            source,
            new_check.content_sha256,
        )
        changed_check, _ = synchronizer.check(source, "old-hash")

        self.assertEqual(new_check.status, "new")
        self.assertEqual(unchanged_check.status, "unchanged")
        self.assertEqual(changed_check.status, "changed")

    def test_stages_changed_source_without_publishing_it(self) -> None:
        synchronizer = OfficialSourceSynchronizer()
        check = synchronizer.check(
            {"source_id": "no-url", "url": None},
            None,
        )[0]
        self.assertEqual(check.status, "skipped")

        with TemporaryDirectory() as directory:
            staged = synchronizer.stage(
                directory=directory,
                check=check.__class__(
                    source_id="course-map",
                    url="https://example.edu/map.pdf",
                    status="changed",
                    content_sha256="hash",
                    previous_sha256="old",
                    content_type="application/pdf",
                ),
                content=b"%PDF-demo",
            )
            self.assertTrue(staged.exists())
            self.assertEqual(staged.suffix, ".pdf")

    def test_rejects_non_official_source_host(self) -> None:
        synchronizer = OfficialSourceSynchronizer(
            allowed_domains={"monash.edu"}
        )

        check, content = synchronizer.check(
            {
                "source_id": "untrusted",
                "url": "https://example.com/injected-handbook",
            },
            None,
        )

        self.assertEqual(check.status, "error")
        self.assertIn("allowlist", check.error or "")
        self.assertIsNone(content)

    def test_rejects_access_challenge_disguised_as_http_200(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"<title>Pardon Our Interruption</title>",
                headers={"content-type": "text/html"},
                request=request,
            )
        )
        synchronizer = OfficialSourceSynchronizer(
            transport=transport,
            allowed_domains={"unimelb.edu.au"},
        )

        check, content = synchronizer.check(
            {
                "source_id": "melbourne",
                "url": "https://handbook.unimelb.edu.au/2026/courses/mc-it",
            },
            None,
        )

        self.assertEqual(check.status, "blocked")
        self.assertIn("access-challenge", check.error or "")
        self.assertIsNone(content)

    def test_sync_manifest_stages_metadata_and_reuses_local_snapshot(
        self,
    ) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                content=b"versioned handbook",
                headers={
                    "content-type": "text/html; charset=utf-8",
                    "etag": '"handbook-v1"',
                },
                request=request,
            )

        synchronizer = OfficialSourceSynchronizer(
            transport=httpx.MockTransport(handler),
            allowed_domains={"monash.edu"},
        )
        manifest = {
            "manifest_version": "test-v1",
            "sources": [
                {
                    "source_id": "monash-c6001-2026",
                    "university_id": "monash",
                    "handbook_year": 2026,
                    "url": "https://handbook.monash.edu/2026/courses/C6001",
                }
            ],
        }

        with TemporaryDirectory() as directory:
            first = synchronizer.sync_manifest(
                manifest=manifest,
                output_directory=directory,
            )
            second = synchronizer.sync_manifest(
                manifest=manifest,
                output_directory=directory,
            )
            state = json.loads(
                (Path(directory) / "index.json").read_text(encoding="utf-8")
            )

            self.assertEqual(first["summary"], {"new": 1})
            self.assertEqual(second["summary"], {"cached": 1})
            self.assertEqual(calls, 1)
            record = state["sources"]["monash-c6001-2026"]
            self.assertTrue(Path(record["local_path"]).exists())
            self.assertEqual(record["etag"], '"handbook-v1"')

    def test_indexes_browser_snapshot_without_http_request(self) -> None:
        synchronizer = OfficialSourceSynchronizer(
            transport=httpx.MockTransport(
                lambda request: self.fail("HTTP must not be called")
            )
        )
        manifest = {
            "manifest_version": "browser-test-v1",
            "sources": [
                {
                    "source_id": "melbourne-mc-it-2026",
                    "university_id": "melbourne",
                    "handbook_year": 2026,
                    "url": "https://handbook.unimelb.edu.au/2026/courses/mc-it",
                    "browser_snapshot_path": (
                        "raw/melbourne/2026/melbourne-mc-it-2026.mhtml"
                    ),
                    "expected_content_markers": [
                        "Master of Information Technology",
                        "2026",
                    ],
                }
            ],
        }

        with TemporaryDirectory() as directory:
            snapshot = (
                Path(directory)
                / "raw"
                / "melbourne"
                / "2026"
                / "melbourne-mc-it-2026.mhtml"
            )
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text(
                "Master of Information Technology - 2026",
                encoding="utf-8",
            )

            report = synchronizer.sync_manifest(
                manifest=manifest,
                output_directory=directory,
            )

            self.assertEqual(report["summary"], {"browser_cached": 1})
            self.assertEqual(
                report["results"][0]["capture_method"],
                "browser_mhtml",
            )


if __name__ == "__main__":
    unittest.main()
