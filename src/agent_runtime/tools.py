from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .schemas import ToolResult, classify_tool_exception


DEFAULT_EDURAG_PROJECT_ROOT = Path(r"D:\agentdev\integrated_qa_system")


def resolve_edurag_project_root() -> Path:
    """Return the original EduRAG project root used by these wrappers."""

    configured = os.getenv("EDURAG_PROJECT_ROOT")
    return Path(configured) if configured else DEFAULT_EDURAG_PROJECT_ROOT


def ensure_edurag_import_path(project_root: Path | None = None) -> Path:
    """Make the original EduRAG project importable without moving its files."""

    root = project_root or resolve_edurag_project_root()
    if not root.exists():
        raise FileNotFoundError(
            f"EduRAG project root does not exist: {root}. "
            "Set EDURAG_PROJECT_ROOT to the integrated_qa_system directory."
        )

    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root


class EduRAGTools:
    """Thin tool wrappers around the existing EduRAG FAQ and RAG capabilities.

    The wrappers intentionally return dictionaries instead of raw project
    objects, so they can later be exposed as LangChain tools, OpenAI tools, or
    MCP tools without changing the business logic again.
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = ensure_edurag_import_path(project_root)
        self._bm25_search = None
        self._vector_store = None

    def _get_bm25_search(self):
        if self._bm25_search is None:
            from mysql_qa import BM25Search, MySQLClient, RedisClient

            redis_client = RedisClient()
            mysql_client = MySQLClient()
            self._bm25_search = BM25Search(redis_client, mysql_client)
        return self._bm25_search

    def _get_vector_store(self):
        if self._vector_store is None:
            from rag_qa import VectorStore

            self._vector_store = VectorStore()
        return self._vector_store

    def search_faq(self, query: str, threshold: float = 0.85) -> dict[str, Any]:
        """Search the MySQL FAQ layer via BM25.

        Returns a stable tool-shaped payload:
        - hit=True means FAQ answered the query.
        - need_rag=True means the caller should continue to RAG.
        """

        try:
            answer, need_rag = self._get_bm25_search().search(query, threshold=threshold)
            return ToolResult(
                tool="search_faq",
                ok=True,
                data={
                    "hit": bool(answer),
                    "answer": answer,
                    "need_rag": bool(need_rag),
                    "source": "faq" if answer else None,
                },
            ).to_dict()
        except Exception as exc:
            error_type, retryable = classify_tool_exception(exc)
            return ToolResult(
                tool="search_faq",
                ok=False,
                data={"hit": False, "answer": None, "need_rag": True},
                error=str(exc),
                error_type=error_type,
                retryable=retryable,
            ).to_dict()

    def search_rag(
        self,
        query: str,
        source_filter: str | None = None,
        k: int | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Search the Milvus RAG layer and return retrieved documents.

        This first tool version only retrieves context. Answer generation stays
        outside the tool so the later Agent can decide how to use the context.
        """

        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be at least 0")

        try:
            vector_store = self._get_vector_store()
            if k is None:
                docs = vector_store.hybrid_search_with_rerank(
                    query,
                    source_filter=source_filter,
                    timeout_seconds=timeout_seconds,
                )
            else:
                docs = vector_store.hybrid_search_with_rerank(
                    query,
                    k=k,
                    source_filter=source_filter,
                    timeout_seconds=timeout_seconds,
                )

            documents = [
                {
                    "content": doc.page_content,
                    "metadata": dict(doc.metadata),
                    "source": doc.metadata.get("source"),
                }
                for doc in docs
            ]
            return ToolResult(
                tool="search_rag",
                ok=True,
                data={
                    "documents": documents,
                    "count": len(documents),
                    "source": "rag",
                },
            ).to_dict()
        except Exception as exc:
            error_type, retryable = classify_tool_exception(exc)
            return ToolResult(
                tool="search_rag",
                ok=False,
                data={"documents": [], "count": 0, "source": "rag"},
                error=str(exc),
                error_type=error_type,
                retryable=retryable,
            ).to_dict()
