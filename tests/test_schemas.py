from __future__ import annotations

from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.schemas import classify_tool_exception


class ToolErrorPolicyTest(unittest.TestCase):
    def test_classifies_retryable_and_non_retryable_errors(self) -> None:
        cases = [
            (TimeoutError("timeout"), ("timeout", True)),
            (ConnectionError("offline"), ("connection_error", True)),
            (PermissionError("denied"), ("permission_error", False)),
            (ValueError("bad input"), ("invalid_request", False)),
            (RuntimeError("unknown"), ("unknown_error", False)),
        ]

        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(classify_tool_exception(error), expected)


if __name__ == "__main__":
    unittest.main()
