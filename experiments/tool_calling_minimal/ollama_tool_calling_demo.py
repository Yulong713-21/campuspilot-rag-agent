from __future__ import annotations

import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.llm_tool_agent import LLMToolCallingAgent
from agent_runtime.ollama_client import OllamaChatClient


def main() -> int:
    os.environ.setdefault("EDURAG_PROJECT_ROOT", r"D:\agentdev\integrated_qa_system")
    os.environ.setdefault("EDURAG_LIGHT_EMBEDDING", "1")

    query = sys.argv[1] if len(sys.argv) > 1 else "人工智能就业课有哪些阶段？"
    source_filter = sys.argv[2] if len(sys.argv) > 2 else "ai"
    model_name = os.getenv("EDURAG_OLLAMA_MODEL", "qwen3:1.7b")

    agent = LLMToolCallingAgent(
        model=OllamaChatClient(model=model_name),
    )
    result = agent.answer(query, source_filter=source_filter)
    summary = {
        "model": model_name,
        "answer": result["answer"],
        "answer_source": result["answer_source"],
        "confidence": result["confidence"],
        "next_action": result["next_action"],
        "tool_round_count": result["tool_round_count"],
        "trace_tools": result["trace_tools"],
        "route_reason": result["route_reason"],
        "route_trace": result["route_trace"],
        "document_count": len(result["documents"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
