"""Fail when private learning or career-preparation files are tracked.

This check intentionally validates Git paths rather than file contents. Product
data may legitimately mention interviews or resumes as admission/recruitment
requirements, while personal preparation material must remain outside the
public repository.
"""

from __future__ import annotations

import re
import subprocess
import sys


FORBIDDEN_PATHS = (
    re.compile(r"(^|/)(notes|private|career-prep)/", re.IGNORECASE),
    re.compile(r"(^|/).*interview.*$", re.IGNORECASE),
    re.compile(r"(^|/).*resume.*$", re.IGNORECASE),
    re.compile(r"(^|/).*mentor.*$", re.IGNORECASE),
    re.compile(r"(^|/)AI_AGENT_LEARNING_ROADMAP_AND_MOD_PLAN\.md$", re.IGNORECASE),
    re.compile(r"(^|/)CAMPUSPILOT_7_DAY_DEEP_DIVE\.md$", re.IGNORECASE),
    re.compile(r"(^|/)PROJECT_STATUS_AND_RESUME\.md$", re.IGNORECASE),
    re.compile(r"(^|/)ROADMAP_8_WEEKS\.md$", re.IGNORECASE),
)


def tracked_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path
    ]


def main() -> int:
    forbidden = sorted(
        path
        for path in tracked_paths()
        if any(pattern.search(path) for pattern in FORBIDDEN_PATHS)
    )
    if forbidden:
        print("Public repository check failed; remove these tracked paths:")
        for path in forbidden:
            print(f"- {path}")
        return 1
    print("Public repository check passed: no private preparation paths are tracked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
