from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True)
class SourceCheck:
    source_id: str
    url: str
    status: str
    content_sha256: str | None
    previous_sha256: str | None
    content_type: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    content_length: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


class OfficialSourceSynchronizer:
    """Detects official-source drift without automatically publishing it."""

    BLOCK_PAGE_MARKERS = (
        b"pardon our interruption",
        b"access denied",
        b"cf-chl-",
        b"captcha challenge",
    )

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        allowed_domains: set[str] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.allowed_domains = {
            domain.lower().lstrip(".") for domain in (allowed_domains or set())
        }

    def _is_allowed_url(self, url: str) -> bool:
        if not self.allowed_domains:
            return True
        hostname = (urlparse(url).hostname or "").lower()
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in self.allowed_domains
        )

    @classmethod
    def _blocked_reason(cls, content: bytes) -> str | None:
        sample = content[:64_000].lower()
        for marker in cls.BLOCK_PAGE_MARKERS:
            if marker in sample:
                return marker.decode("ascii", errors="replace")
        return None

    def check(
        self,
        source: dict[str, Any],
        previous_sha256: str | None,
    ) -> tuple[SourceCheck, bytes | None]:
        source_id = source["source_id"]
        url = source.get("url")
        if not url:
            return (
                SourceCheck(
                    source_id=source_id,
                    url="",
                    status="skipped",
                    content_sha256=None,
                    previous_sha256=previous_sha256,
                    error="source has no URL",
                ),
                None,
            )
        if not self._is_allowed_url(url):
            return (
                SourceCheck(
                    source_id=source_id,
                    url=url,
                    status="error",
                    content_sha256=None,
                    previous_sha256=previous_sha256,
                    error="source host is not in the official allowlist",
                ),
                None,
            )
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(
                    url,
                    headers={
                        "User-Agent": (
                            "CampusPilotSourceMonitor/0.1 "
                            "(local portfolio project)"
                        )
                    },
                )
                response.raise_for_status()
                final_url = str(response.url)
                if not self._is_allowed_url(final_url):
                    return (
                        SourceCheck(
                            source_id=source_id,
                            url=url,
                            status="error",
                            content_sha256=None,
                            previous_sha256=previous_sha256,
                            final_url=final_url,
                            http_status=response.status_code,
                            error=(
                                "redirect target is not in the official "
                                "allowlist"
                            ),
                        ),
                        None,
                    )
                content = response.content
                blocked_reason = self._blocked_reason(content)
                if blocked_reason:
                    return (
                        SourceCheck(
                            source_id=source_id,
                            url=url,
                            status="blocked",
                            content_sha256=None,
                            previous_sha256=previous_sha256,
                            content_type=response.headers.get("content-type"),
                            final_url=final_url,
                            http_status=response.status_code,
                            content_length=len(content),
                            error=(
                                "source returned an access-challenge page: "
                                f"{blocked_reason}"
                            ),
                        ),
                        None,
                    )
                digest = hashlib.sha256(content).hexdigest()
                status = (
                    "new"
                    if previous_sha256 is None
                    else "unchanged"
                    if previous_sha256 == digest
                    else "changed"
                )
                return (
                    SourceCheck(
                        source_id=source_id,
                        url=url,
                        status=status,
                        content_sha256=digest,
                        previous_sha256=previous_sha256,
                        content_type=response.headers.get("content-type"),
                        final_url=final_url,
                        http_status=response.status_code,
                        content_length=len(content),
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                    ),
                    content,
                )
        except httpx.HTTPError as exc:
            return (
                SourceCheck(
                    source_id=source_id,
                    url=url,
                    status="error",
                    content_sha256=None,
                    previous_sha256=previous_sha256,
                    error=str(exc),
                ),
                None,
            )

    @staticmethod
    def stage(
        *,
        directory: str | Path,
        check: SourceCheck,
        content: bytes,
    ) -> Path:
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        content_type = (check.content_type or "").lower()
        if "pdf" in content_type:
            suffix = ".pdf"
        elif "wordprocessingml" in content_type:
            suffix = ".docx"
        elif "json" in content_type:
            suffix = ".json"
        else:
            suffix = ".html"
        safe_source_id = re.sub(r"[^a-zA-Z0-9_.-]+", "-", check.source_id)
        target = target_dir / f"{safe_source_id}{suffix}"
        target.write_bytes(content)
        return target

    @staticmethod
    def _load_state(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"sources": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for attempt in range(3):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def sync_manifest(
        self,
        *,
        manifest: dict[str, Any],
        output_directory: str | Path,
        force_refresh: bool = False,
        delay_seconds: float = 0.0,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Download curated sources and retain a resumable local index."""

        output_root = Path(output_directory)
        state_path = output_root / "index.json"
        previous_state = self._load_state(state_path)
        next_sources = dict(previous_state.get("sources", {}))
        results: list[dict[str, Any]] = []
        selected_sources = manifest.get("sources", [])
        if limit is not None:
            selected_sources = selected_sources[:limit]

        for position, source in enumerate(selected_sources):
            source_id = source["source_id"]
            browser_snapshot_path = source.get("browser_snapshot_path")
            if browser_snapshot_path:
                snapshot_path = output_root / browser_snapshot_path
                checked_at = datetime.now(timezone.utc).isoformat()
                if not snapshot_path.exists():
                    results.append(
                        {
                            **source,
                            "status": "browser_required",
                            "checked_at": checked_at,
                            "local_path": str(snapshot_path.resolve()),
                            "error": "browser snapshot has not been captured",
                        }
                    )
                    continue
                snapshot_content = snapshot_path.read_bytes()
                lowered = snapshot_content.lower()
                missing_markers = [
                    marker
                    for marker in source.get("expected_content_markers", [])
                    if marker.lower().encode("utf-8") not in lowered
                ]
                if missing_markers:
                    results.append(
                        {
                            **source,
                            "status": "invalid_snapshot",
                            "checked_at": checked_at,
                            "local_path": str(snapshot_path.resolve()),
                            "error": (
                                "browser snapshot is missing expected markers: "
                                + ", ".join(missing_markers)
                            ),
                        }
                    )
                    continue
                digest = hashlib.sha256(snapshot_content).hexdigest()
                snapshot_suffix = snapshot_path.suffix.lower()
                if snapshot_suffix in {".mhtml", ".mht"}:
                    snapshot_content_type = "multipart/related; type=text/html"
                    capture_method = "browser_mhtml"
                elif snapshot_suffix in {".html", ".htm"}:
                    snapshot_content_type = "text/html; rendered=true"
                    capture_method = "browser_rendered_dom"
                else:
                    snapshot_content_type = "text/plain; rendered=true"
                    capture_method = "browser_visible_text"
                record = {
                    "content_sha256": digest,
                    "content_type": snapshot_content_type,
                    "content_length": len(snapshot_content),
                    "final_url": source["url"],
                    "http_status": 200,
                    "etag": None,
                    "last_modified": None,
                    "checked_at": checked_at,
                    "local_path": str(snapshot_path.resolve()),
                    "capture_method": capture_method,
                }
                next_sources[source_id] = record
                results.append(
                    {
                        **source,
                        **record,
                        "status": "browser_cached",
                        "error": None,
                    }
                )
                continue

            previous = previous_state.get("sources", {}).get(source_id, {})
            previous_path = previous.get("local_path")
            if previous_path and Path(previous_path).exists():
                cached_content = Path(previous_path).read_bytes()
                if self._blocked_reason(cached_content):
                    Path(previous_path).unlink()
                    next_sources.pop(source_id, None)
                    previous = {}
                    previous_path = None
            if (
                not force_refresh
                and previous.get("content_sha256")
                and previous_path
                and Path(previous_path).exists()
            ):
                results.append(
                    {
                        **source,
                        **previous,
                        "status": "cached",
                        "error": None,
                    }
                )
                continue

            check, content = self.check(
                source,
                previous.get("content_sha256"),
            )
            checked_at = datetime.now(timezone.utc).isoformat()
            item = {
                **source,
                **check.__dict__,
                "checked_at": checked_at,
                "local_path": previous_path,
            }
            if content is not None and check.status in {
                "new",
                "changed",
                "unchanged",
            }:
                year = str(source.get("handbook_year") or "cross-year")
                staged_path = self.stage(
                    directory=(
                        output_root
                        / "raw"
                        / source.get("university_id", "policy")
                        / year
                    ),
                    check=check,
                    content=content,
                )
                item["local_path"] = str(staged_path.resolve())

            results.append(item)
            if check.content_sha256 and item["local_path"]:
                next_sources[source_id] = {
                    "content_sha256": check.content_sha256,
                    "content_type": check.content_type,
                    "content_length": check.content_length,
                    "final_url": check.final_url,
                    "http_status": check.http_status,
                    "etag": check.etag,
                    "last_modified": check.last_modified,
                    "checked_at": checked_at,
                    "local_path": item["local_path"],
                }
            if delay_seconds > 0 and position < len(selected_sources) - 1:
                time.sleep(delay_seconds)

        summary: dict[str, int] = {}
        for item in results:
            status = item["status"]
            summary[status] = summary.get(status, 0) + 1
        completed_at = datetime.now(timezone.utc).isoformat()
        next_state = {
            "manifest_version": manifest.get("manifest_version"),
            "completed_at": completed_at,
            "sources": next_sources,
        }
        self._write_json(state_path, next_state)
        report = {
            "manifest_version": manifest.get("manifest_version"),
            "completed_at": completed_at,
            "output_directory": str(output_root.resolve()),
            "force_refresh": force_refresh,
            "summary": summary,
            "results": results,
            "next_action": (
                "review_unresolved_sources_then_parse_local_snapshots"
            ),
        }
        self._write_json(output_root / "latest-report.json", report)
        return report
