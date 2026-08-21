from __future__ import annotations

import os
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from .tools import EduRAGTools


class ReadOnlyEduRAGTools(Protocol):
    def search_faq(self, query: str, threshold: float = 0.85) -> dict[str, Any]:
        ...

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        ...


class DemoEduRAGTools:
    """Deterministic provider used by the MCP client experiment."""

    def search_faq(self, query: str, threshold: float = 0.85) -> dict[str, Any]:
        hit = "人工智能课程" in query
        return {
            "tool": "search_faq",
            "ok": True,
            "data": {
                "hit": hit,
                "answer": "人工智能课程包含基础、进阶和项目实战阶段。" if hit else None,
                "need_rag": not hit,
                "source": "faq" if hit else None,
                "threshold": threshold,
            },
            "error": None,
            "error_type": None,
            "retryable": False,
        }

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        document = {
            "content": "课程项目阶段包含 RAG、Tool Calling 和 LangGraph 实践。",
            "metadata": {
                "source": source_filter or "ai",
                "document_id": "demo-course-001",
                "query": query,
            },
            "source": source_filter or "ai",
        }
        return {
            "tool": "search_rag",
            "ok": True,
            "data": {
                "documents": [document],
                "count": 1,
                "source": "rag",
                "k": k,
                "timeout_seconds": timeout_seconds,
            },
            "error": None,
            "error_type": None,
            "retryable": False,
        }


def _validate_query(query: str) -> str:
    normalized = query.strip()
    if not normalized:
        raise ValueError("query must not be empty")
    if len(normalized) > 500:
        raise ValueError("query must be at most 500 characters")
    return normalized


def _validate_source_filter(source_filter: str | None) -> str | None:
    if source_filter is None:
        return None
    normalized = source_filter.strip()
    if not normalized:
        return None
    if len(normalized) > 64:
        raise ValueError("source_filter must be at most 64 characters")
    return normalized


def execute_faq_search(
    tools: ReadOnlyEduRAGTools,
    query: str,
    threshold: float = 0.85,
) -> dict[str, Any]:
    normalized_query = _validate_query(query)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    return tools.search_faq(normalized_query, threshold=threshold)


def execute_rag_search(
    tools: ReadOnlyEduRAGTools,
    query: str,
    source_filter: str | None = None,
    k: int = 5,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    normalized_query = _validate_query(query)
    normalized_source = _validate_source_filter(source_filter)
    if not 1 <= k <= 20:
        raise ValueError("k must be between 1 and 20")
    if not 0.1 <= timeout_seconds <= 30.0:
        raise ValueError("timeout_seconds must be between 0.1 and 30")
    return tools.search_rag(
        normalized_query,
        source_filter=normalized_source,
        k=k,
        timeout_seconds=timeout_seconds,
    )


def create_mcp_server(
    tools: ReadOnlyEduRAGTools | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8020,
) -> FastMCP:
    provider = tools
    if provider is None:
        provider = DemoEduRAGTools() if os.getenv("EDURAG_MCP_DEMO") == "1" else EduRAGTools()

    server = FastMCP(
        name="EduRAG Read-only Tools",
        instructions=(
            "Read-only education FAQ and RAG retrieval tools. "
            "All model-supplied arguments are validated by the application."
        ),
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @server.tool(
        name="search_faq",
        description="Search the low-cost FAQ layer before using vector retrieval.",
    )
    def search_faq(query: str, threshold: float = 0.85) -> dict[str, Any]:
        return execute_faq_search(provider, query, threshold)

    @server.tool(
        name="search_rag",
        description="Retrieve reranked education documents from the RAG layer.",
    )
    def search_rag(
        query: str,
        source_filter: str | None = None,
        k: int = 5,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        return execute_rag_search(
            provider,
            query,
            source_filter=source_filter,
            k=k,
            timeout_seconds=timeout_seconds,
        )

    @server.resource(
        "edurag://capabilities",
        name="EduRAG MCP capabilities",
        description="Machine-readable capabilities and safety limits.",
        mime_type="application/json",
    )
    def capabilities() -> dict[str, Any]:
        return {
            "server": "EduRAG Read-only Tools",
            "mode": "read_only",
            "tools": ["search_faq", "search_rag"],
            "limits": {
                "query_max_characters": 500,
                "source_filter_max_characters": 64,
                "rag_k": {"min": 1, "max": 20},
                "timeout_seconds": {"min": 0.1, "max": 30.0},
            },
            "security": [
                "tool allowlist",
                "application-side argument validation",
                "no write or side-effect tools",
            ],
        }

    return server


mcp = create_mcp_server()


def main() -> None:
    transport = os.getenv("EDURAG_MCP_TRANSPORT", "stdio")
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("EDURAG_MCP_TRANSPORT must be stdio, sse, or streamable-http")
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
