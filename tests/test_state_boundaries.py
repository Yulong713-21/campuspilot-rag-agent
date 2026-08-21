from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.state_boundaries import AgentStateProjector


def execution_state() -> dict:
    return {
        "request_id": "request-1",
        "user_id": "user-1",
        "thread_id": "thread-1",
        "original_query": "课程有哪些阶段？",
        "effective_query": "人工智能课程有哪些阶段？",
        "source_filter": "ai",
        "retry_count": 1,
        "documents": [
            {
                "content": "课程包括基础、项目和就业阶段。",
                "source": "course.md",
            }
        ],
        "selected_memories": [
            {
                "key": "answer_style",
                "value": "先讲原理，再展示实验",
                "status": "active",
            },
            {
                "key": "primary_stack",
                "value": "Java",
                "status": "superseded",
            },
        ],
        "eligible_memories": [
            {
                "memory_id": "not-selected",
                "content": "仅用于二次装箱的内部候选",
            }
        ],
        "faq_result": {"data": {"answer": "internal FAQ answer"}},
        "rag_result": {"data": {"documents": ["raw internal document"]}},
        "answer": "完整答案",
        "answer_source": "rag_generated",
        "confidence": "medium",
        "evaluation": {"supported": True},
        "next_action": "answer_user",
        "route_reason": "rag_answer_supported_after_rewrite",
        "trace": [
            {
                "tool": "search_faq",
                "ok": True,
                "data": {"hit": False, "answer": None},
                "error": None,
            },
            {
                "tool": "search_rag",
                "ok": True,
                "data": {
                    "count": 1,
                    "documents": [{"content": "must not enter trace"}],
                },
                "error": None,
            },
        ],
    }


class AgentStateProjectorTest(unittest.TestCase):
    def test_checkpoint_keeps_resume_state_but_excludes_raw_tool_payloads(self) -> None:
        result = AgentStateProjector().project(execution_state())

        self.assertEqual(result.checkpoint["retry_count"], 1)
        self.assertIn("documents", result.checkpoint)
        self.assertNotIn("trace", result.checkpoint)
        self.assertNotIn("faq_result", result.checkpoint)
        self.assertNotIn("rag_result", result.checkpoint)
        self.assertNotIn("eligible_memories", result.checkpoint)

    def test_prompt_receives_only_selected_documents_and_active_memories(self) -> None:
        result = AgentStateProjector().project(execution_state())

        self.assertEqual(
            result.prompt_context["memories"],
            [{"key": "answer_style", "value": "先讲原理，再展示实验"}],
        )
        self.assertNotIn("trace", result.prompt_context)
        self.assertNotIn("answer", result.prompt_context)
        self.assertNotIn("仅用于二次装箱", str(result.prompt_context))

    def test_trace_is_observable_without_document_or_answer_content(self) -> None:
        result = AgentStateProjector().project(execution_state())

        self.assertEqual(
            [event["tool"] for event in result.trace_record["tool_events"]],
            ["search_faq", "search_rag"],
        )
        self.assertEqual(result.trace_record["tool_events"][1]["count"], 1)
        self.assertNotIn("documents", str(result.trace_record))
        self.assertNotIn("完整答案", str(result.trace_record))

    def test_execution_state_does_not_implicitly_write_long_term_memory(self) -> None:
        result = AgentStateProjector().project(execution_state())

        self.assertEqual(result.long_term_memory_writes, [])

    def test_identity_is_required_before_projection(self) -> None:
        state = execution_state()
        state["user_id"] = ""

        with self.assertRaisesRegex(ValueError, "user_id"):
            AgentStateProjector().project(state)


if __name__ == "__main__":
    unittest.main()
