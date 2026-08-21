from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.cache_policy import CacheFreshnessPolicy, CacheRule


def main() -> None:
    policy = CacheFreshnessPolicy(
        {
            "course_intro": CacheRule(
                fresh_ttl_seconds=6 * 60 * 60,
                max_stale_seconds=72 * 60 * 60,
                allow_stale=True,
            ),
            "tuition": CacheRule(
                fresh_ttl_seconds=5 * 60,
                max_stale_seconds=5 * 60,
                allow_stale=False,
            ),
        }
    )

    scenarios = {
        "24 小时课程介绍": policy.decide(
            "course_intro",
            cache_age_seconds=24 * 60 * 60,
        ),
        "2 分钟学费": policy.decide(
            "tuition",
            cache_age_seconds=2 * 60,
        ),
        "24 小时学费": policy.decide(
            "tuition",
            cache_age_seconds=24 * 60 * 60,
        ),
    }

    print(
        json.dumps(
            {
                name: asdict(decision)
                for name, decision in scenarios.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
