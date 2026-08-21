from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.coverage_report import build_coverage_report


if __name__ == "__main__":
    print(
        json.dumps(
            build_coverage_report(REPO_ROOT),
            ensure_ascii=False,
            indent=2,
        )
    )
