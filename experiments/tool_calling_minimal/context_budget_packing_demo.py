from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.context_budget import ContextBudgetPacker, ContextDocument


def main() -> None:
    documents = [
        ContextDocument("A", "文档 A", 0.92, 600, "ai"),
        ContextDocument("B", "文档 B", 0.88, 700, "ai"),
        ContextDocument("C", "文档 C", 0.81, 500, "ai"),
        ContextDocument("D", "文档 D", 0.76, 650, "ai"),
        ContextDocument("E", "文档 E", 0.70, 550, "ai"),
    ]
    result = ContextBudgetPacker().pack(documents, token_budget=1896)

    print(
        json.dumps(
            {
                "模型上下文上限": 4096,
                "系统提示与用户问题": 700,
                "历史对话": 500,
                "最终答案预留": 800,
                "安全余量": 200,
                "rag_token_budget": result.token_budget,
                "selected_documents": [
                    item.document_id for item in result.selected
                ],
                "dropped_documents": [
                    item.document_id for item in result.dropped
                ],
                "used_tokens": result.used_tokens,
                "remaining_tokens": result.remaining_tokens,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
