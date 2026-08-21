from __future__ import annotations

from dataclasses import dataclass
import re

from .context_budget import ContextDocument


@dataclass(frozen=True)
class InjectionFinding:
    document_id: str
    signals: list[str]


@dataclass(frozen=True)
class ContentGuardResult:
    accepted: list[ContextDocument]
    quarantined: list[ContextDocument]
    findings: list[InjectionFinding]


class RetrievedContentGuard:
    """Baseline detector that quarantines obvious instruction-like RAG content."""

    _SIGNAL_PATTERNS = {
        "instruction_override": (
            re.compile(
                r"ignore\s+(all\s+)?(previous|prior|system)\s+instructions?",
                re.IGNORECASE,
            ),
            re.compile(r"忽略.{0,12}(之前|以上|系统).{0,8}(指令|提示)"),
        ),
        "tool_coercion": (
            re.compile(r"(call|invoke|execute).{0,20}(tool|function)", re.IGNORECASE),
            re.compile(r"(调用|执行).{0,12}(工具|函数)"),
        ),
        "sensitive_exfiltration": (
            re.compile(
                r"(reveal|print|send|output).{0,24}(password|secret|api[ _-]?key)",
                re.IGNORECASE,
            ),
            re.compile(r"(输出|泄露|显示).{0,12}(密码|密钥|系统提示)"),
        ),
    }

    def inspect(self, documents: list[ContextDocument]) -> ContentGuardResult:
        accepted: list[ContextDocument] = []
        quarantined: list[ContextDocument] = []
        findings: list[InjectionFinding] = []

        for document in documents:
            signals = self._detect_signals(document.content)
            if signals:
                quarantined.append(document)
                findings.append(
                    InjectionFinding(
                        document_id=document.document_id,
                        signals=signals,
                    )
                )
            else:
                accepted.append(document)

        return ContentGuardResult(
            accepted=accepted,
            quarantined=quarantined,
            findings=findings,
        )

    def _detect_signals(self, content: str) -> list[str]:
        return [
            signal
            for signal, patterns in self._SIGNAL_PATTERNS.items()
            if any(pattern.search(content) for pattern in patterns)
        ]
