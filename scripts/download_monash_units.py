from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "data" / "handbook_source_manifest.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "official_sources"


class StartRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self.interval = 1.0 / requests_per_second
        self.next_start = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            now = monotonic()
            delay = max(0.0, self.next_start - now)
            if delay:
                await asyncio.sleep(delay)
            self.next_start = max(monotonic(), self.next_start) + self.interval


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download versioned Monash unit pages with a rate limit."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--requests-per-second",
        type=float,
        default=3.0,
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--max-items",
        type=int,
        help="Limit new network requests for a controlled crawl batch.",
    )
    return parser.parse_args()


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def allowed_url(url: str, allowed_domains: set[str]) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in allowed_domains
    )


def stage_html(
    output: Path,
    source: dict[str, Any],
    content: bytes,
) -> Path:
    target = (
        output
        / "raw"
        / "monash"
        / str(source["handbook_year"])
        / f"{re.sub(r'[^a-zA-Z0-9_.-]+', '-', source['source_id'])}.html"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def unit_snapshot_path(
    output: Path,
    source: dict[str, Any],
) -> Path:
    return (
        output
        / "raw"
        / "monash"
        / str(source["handbook_year"])
        / f"{re.sub(r'[^a-zA-Z0-9_.-]+', '-', source['source_id'])}.html"
    )


def recovered_record(
    source: dict[str, Any],
    snapshot: Path,
) -> dict[str, Any] | None:
    content = snapshot.read_bytes()
    lowered = content.lower()
    markers = source.get("expected_content_markers") or []
    if not content or any(
        marker.lower().encode("utf-8") not in lowered
        for marker in markers
    ):
        return None
    return {
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_type": "text/html",
        "content_length": len(content),
        "final_url": source["url"],
        "http_status": 200,
        "etag": None,
        "last_modified": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "local_path": str(snapshot.resolve()),
        "capture_method": "http_next_data_recovered",
    }


async def fetch_source(
    *,
    client: httpx.AsyncClient,
    source: dict[str, Any],
    limiter: StartRateLimiter,
    allowed_domains: set[str],
    output: Path,
    previous: dict[str, Any],
) -> dict[str, Any]:
    url = source["url"]
    if not allowed_url(url, allowed_domains):
        return {
            **source,
            "status": "error",
            "error": "source host is not in the official allowlist",
        }

    response: httpx.Response | None = None
    error: str | None = None
    for attempt in range(2):
        await limiter.wait()
        try:
            response = await asyncio.wait_for(
                client.get(url),
                timeout=30.0,
            )
            break
        except (
            asyncio.TimeoutError,
            httpx.ConnectError,
            httpx.ReadTimeout,
        ) as exc:
            error = str(exc)
            if attempt == 0:
                await asyncio.sleep(0.5)
    if response is None:
        return {**source, "status": "error", "error": error}
    if response.status_code >= 400:
        return {
            **source,
            "status": "error",
            "http_status": response.status_code,
            "error": f"HTTP {response.status_code}",
        }
    final_url = str(response.url)
    if not allowed_url(final_url, allowed_domains):
        return {
            **source,
            "status": "error",
            "http_status": response.status_code,
            "error": "redirect target is not in the official allowlist",
        }
    content = response.content
    lowered = content[:64_000].lower()
    if any(
        marker in lowered
        for marker in (
            b"access denied",
            b"captcha challenge",
            b"cf-chl-",
        )
    ):
        return {
            **source,
            "status": "blocked",
            "http_status": response.status_code,
            "error": "official source returned an access challenge",
        }

    digest = hashlib.sha256(content).hexdigest()
    local_path = stage_html(output, source, content)
    previous_digest = previous.get("content_sha256")
    return {
        **source,
        "status": (
            "new"
            if previous_digest is None
            else "unchanged"
            if previous_digest == digest
            else "changed"
        ),
        "content_sha256": digest,
        "content_type": response.headers.get("content-type"),
        "content_length": len(content),
        "final_url": final_url,
        "http_status": response.status_code,
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "local_path": str(local_path.resolve()),
        "capture_method": "http_next_data",
        "error": None,
    }


async def main_async(args: argparse.Namespace) -> None:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    state_path = args.output / "index.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"sources": {}}
    )
    next_sources = dict(state.get("sources", {}))
    selected = [
        source
        for source in manifest["sources"]
        if source.get("university_id") == "monash"
        and source.get("source_type") == "unit_handbook"
    ]
    pending = []
    cached_results = []
    for source in selected:
        previous = next_sources.get(source["source_id"], {})
        previous_path = previous.get("local_path")
        if (
            not args.refresh
            and previous.get("content_sha256")
            and previous_path
            and Path(previous_path).exists()
        ):
            cached_results.append(
                {**source, **previous, "status": "cached", "error": None}
            )
        elif not args.refresh and previous.get("http_status") == 404:
            cached_results.append(
                {
                    **source,
                    **previous,
                    "status": "unavailable",
                    "error": "official page returned HTTP 404",
                }
            )
        else:
            snapshot = unit_snapshot_path(args.output, source)
            recovered = (
                recovered_record(source, snapshot)
                if snapshot.exists() and not args.refresh
                else None
            )
            if recovered:
                next_sources[source["source_id"]] = recovered
                cached_results.append(
                    {
                        **source,
                        **recovered,
                        "status": "recovered",
                        "error": None,
                    }
                )
            else:
                pending.append((source, previous))

    if args.max_items is not None:
        if args.max_items < 1:
            raise ValueError("max-items must be at least 1")
        pending = pending[: args.max_items]

    limiter = StartRateLimiter(args.requests_per_second)
    limits = httpx.Limits(
        max_connections=args.workers,
        max_keepalive_connections=args.workers,
    )
    semaphore = asyncio.Semaphore(args.workers)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=45.0,
        limits=limits,
        headers={
            "User-Agent": (
                "CampusPilotUnitCollector/0.1 "
                "(local education research project)"
            )
        },
    ) as client:
        async def guarded(
            source: dict[str, Any],
            previous: dict[str, Any],
        ) -> dict[str, Any]:
            async with semaphore:
                return await fetch_source(
                    client=client,
                    source=source,
                    limiter=limiter,
                    allowed_domains={
                        domain.lower().lstrip(".")
                        for domain in manifest["allowed_domains"]
                    },
                    output=args.output,
                    previous=previous,
                )

        tasks = [
            asyncio.create_task(guarded(source, previous))
            for source, previous in pending
        ]
        downloaded_results = []
        for completed, task in enumerate(
            asyncio.as_completed(tasks),
            start=1,
        ):
            result = await task
            downloaded_results.append(result)
            if result.get("content_sha256") and result.get("local_path"):
                next_sources[result["source_id"]] = {
                    key: result.get(key)
                    for key in (
                        "content_sha256",
                        "content_type",
                        "content_length",
                        "final_url",
                        "http_status",
                        "etag",
                        "last_modified",
                        "checked_at",
                        "local_path",
                        "capture_method",
                    )
                }
            elif result.get("http_status") == 404:
                next_sources[result["source_id"]] = {
                    "http_status": 404,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "error": result.get("error"),
                }
            if completed % 100 == 0 or completed == len(tasks):
                print(
                    json.dumps(
                        {
                            "completed": completed,
                            "pending_total": len(tasks),
                            "last_status": result["status"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if completed % 50 == 0:
                atomic_json_write(
                    state_path,
                    {
                        "manifest_version": manifest["manifest_version"],
                        "completed_at": (
                            datetime.now(timezone.utc).isoformat()
                        ),
                        "sources": next_sources,
                    },
                )
            if result.get("http_status") in {403, 429}:
                for pending_task in tasks:
                    if not pending_task.done():
                        pending_task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                print(
                    json.dumps(
                        {
                            "event": "crawl_circuit_open",
                            "http_status": result.get("http_status"),
                            "completed": completed,
                            "reason": "official_source_rate_limited",
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                break

    results = cached_results + downloaded_results
    summary: dict[str, int] = {}
    for result in results:
        summary[result["status"]] = (
            summary.get(result["status"], 0) + 1
        )
    completed_at = datetime.now(timezone.utc).isoformat()
    atomic_json_write(
        state_path,
        {
            "manifest_version": manifest["manifest_version"],
            "completed_at": completed_at,
            "sources": next_sources,
        },
    )
    report = {
        "manifest_version": manifest["manifest_version"],
        "completed_at": completed_at,
        "summary": summary,
        "results": results,
        "unresolved": [
            {
                "source_id": result["source_id"],
                "status": result["status"],
                "http_status": result.get("http_status"),
                "error": result.get("error"),
            }
            for result in results
            if result["status"] in {"error", "blocked"}
        ],
    }
    atomic_json_write(
        args.output / "monash-unit-download-report.json",
        report,
    )
    print(
        json.dumps(
            {
                "selected": len(selected),
                "cached": len(cached_results),
                "downloaded": len(downloaded_results),
                "summary": summary,
                "unresolved": report["unresolved"],
                "next_action": "extract_monash_unit_snapshots",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("workers must be at least 1")
    if args.requests_per_second <= 0:
        raise ValueError("requests-per-second must be positive")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
