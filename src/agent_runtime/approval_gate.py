from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal


ApprovalMode = Literal["automatic", "human_required", "denied"]


@dataclass(frozen=True)
class ApprovalDecision:
    tool_name: str
    mode: ApprovalMode
    reason: str
    action_digest: str


class ToolApprovalGate:
    """Classifies tool actions outside the model and binds approval to arguments."""

    _AUTOMATIC_TOOLS = {
        "search_faq",
        "search_rag",
        "create_email_draft",
    }
    _HUMAN_REQUIRED_TOOLS = {
        "send_email",
        "delete_document",
    }
    _DENIED_TOOLS = {
        "delete_database",
    }

    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ApprovalDecision:
        action_digest = self._action_digest(tool_name, arguments)

        if tool_name in self._AUTOMATIC_TOOLS:
            return ApprovalDecision(
                tool_name=tool_name,
                mode="automatic",
                reason="read_only_or_reversible_action",
                action_digest=action_digest,
            )

        if tool_name in self._HUMAN_REQUIRED_TOOLS:
            return ApprovalDecision(
                tool_name=tool_name,
                mode="human_required",
                reason="external_or_destructive_side_effect",
                action_digest=action_digest,
            )

        reason = (
            "explicitly_denied_tool"
            if tool_name in self._DENIED_TOOLS
            else "unclassified_tool_defaults_to_denied"
        )
        return ApprovalDecision(
            tool_name=tool_name,
            mode="denied",
            reason=reason,
            action_digest=action_digest,
        )

    def is_approved(
        self,
        decision: ApprovalDecision,
        approved_action_digest: str | None = None,
    ) -> bool:
        if decision.mode == "automatic":
            return True
        if decision.mode == "human_required":
            return approved_action_digest == decision.action_digest
        return False

    def _action_digest(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        try:
            canonical_action = json.dumps(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except TypeError as exc:
            raise ValueError("tool arguments must be JSON serializable") from exc
        return hashlib.sha256(canonical_action.encode("utf-8")).hexdigest()
