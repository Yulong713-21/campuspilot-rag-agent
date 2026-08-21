from __future__ import annotations

import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run_client() -> dict[str, object]:
    url = os.getenv("EDURAG_MCP_URL", "http://127.0.0.1:8020/mcp")
    async with streamable_http_client(url) as (read_stream, write_stream, session_id):
        async with ClientSession(read_stream, write_stream) as session:
            initialize_result = await session.initialize()
            tools_result = await session.list_tools()

    return {
        "protocol_version": initialize_result.protocolVersion,
        "transport": "streamable-http",
        "url": url,
        "session_id": session_id(),
        "tool_names": [tool.name for tool in tools_result.tools],
        "next_action": "call_read_only_tools",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_client()), ensure_ascii=False, indent=2))
