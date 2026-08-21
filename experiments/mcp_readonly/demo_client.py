from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def _result_payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    return [block.model_dump() for block in result.content]


async def run_demo() -> dict[str, Any]:
    env = dict(os.environ)
    env["EDURAG_MCP_DEMO"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in [str(SRC_ROOT), env.get("PYTHONPATH", "")] if item
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agent_runtime.mcp_server"],
        env=env,
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialize_result = await session.initialize()
            tools_result = await session.list_tools()
            faq_result = await session.call_tool(
                "search_faq",
                {"query": "人工智能课程有哪些阶段？", "threshold": 0.85},
            )
            rag_result = await session.call_tool(
                "search_rag",
                {
                    "query": "项目阶段学什么？",
                    "source_filter": "ai",
                    "k": 3,
                    "timeout_seconds": 2.0,
                },
            )

    return {
        "protocol_version": initialize_result.protocolVersion,
        "transport": "stdio",
        "tool_names": [tool.name for tool in tools_result.tools],
        "trace_tools": ["search_faq", "search_rag"],
        "faq_result": _result_payload(faq_result),
        "rag_result": _result_payload(rag_result),
        "security": {
            "read_only": True,
            "argument_validation": True,
            "tool_allowlist": ["search_faq", "search_rag"],
        },
        "next_action": "connect_real_edurag_services",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), ensure_ascii=False, indent=2))
