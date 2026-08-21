from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.tool_agent import RuleBasedToolAgent


class NoopTools:
    pass


def main() -> int:
    jitter_fractions = [0.9, 0.2, 0.7, 0.4, 0.6]
    rows = []

    for retry_count, fraction in enumerate(jitter_fractions):
        agent = RuleBasedToolAgent(  # type: ignore[arg-type]
            tools=NoopTools(),
            backoff_base_seconds=0.5,
            max_backoff_seconds=2.0,
            jitter=lambda upper_bound, value=fraction: upper_bound * value,
        )
        rows.append(
            {
                "retry_count": retry_count,
                "backoff_cap_seconds": agent._backoff_cap_seconds(retry_count),
                "jitter_fraction": fraction,
                "actual_backoff_seconds": agent._backoff_seconds(retry_count),
            }
        )

    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
