from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.mcp_server import (
    DemoEduRAGTools,
    create_mcp_server,
    execute_faq_search,
    execute_rag_search,
)


class McpToolBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = DemoEduRAGTools()

    def test_faq_normalizes_query_and_returns_structured_result(self) -> None:
        result = execute_faq_search(self.tools, "  人工智能课程有哪些阶段？  ")

        self.assertTrue(result["ok"])
        self.assertTrue(result["data"]["hit"])
        self.assertEqual(result["tool"], "search_faq")

    def test_faq_rejects_invalid_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "threshold"):
            execute_faq_search(self.tools, "question", threshold=1.1)

    def test_rag_binds_limits_before_calling_provider(self) -> None:
        result = execute_rag_search(
            self.tools,
            "项目阶段学什么？",
            source_filter=" ai ",
            k=3,
            timeout_seconds=2.0,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["documents"][0]["source"], "ai")

    def test_rag_rejects_unbounded_k(self) -> None:
        with self.assertRaisesRegex(ValueError, "k"):
            execute_rag_search(self.tools, "question", k=100)

    def test_rag_rejects_excessive_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeout_seconds"):
            execute_rag_search(self.tools, "question", timeout_seconds=60.0)


class McpServerRegistrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_server_exposes_only_read_only_tools(self) -> None:
        server = create_mcp_server(DemoEduRAGTools())

        tools = await server.list_tools()

        self.assertEqual([tool.name for tool in tools], ["search_faq", "search_rag"])
        self.assertTrue(all(tool.description for tool in tools))


if __name__ == "__main__":
    unittest.main()
