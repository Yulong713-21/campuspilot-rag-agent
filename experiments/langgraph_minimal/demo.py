from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.graph_agent import LangGraphEduRAGAgent


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "AI学科课程大纲内容是什么？"
    source_filter = sys.argv[2] if len(sys.argv) > 2 else "ai"

    agent = LangGraphEduRAGAgent()
    result = agent.answer(query, source_filter=source_filter)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
