from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class OllamaChatClient:
    """Small native Ollama chat client for local answer generation."""

    model: str = "qwen3:1.7b"
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 90
    num_predict: int = 350
    num_ctx: int = 2048
    temperature: float = 0.2

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout_seconds: float | None = None,
        format_schema: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        effective_timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        if effective_timeout <= 0:
            raise ValueError("timeout_seconds must be greater than 0")

        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "messages": messages,
            "options": {
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
                "temperature": self.temperature,
            },
        }
        if tools:
            payload["tools"] = tools
        if format_schema is not None:
            payload["format"] = format_schema

        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=effective_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        message = data.get("message")
        if not isinstance(message, dict):
            raise ValueError("Ollama response did not contain a message object")
        return message

    def generate_grounded_answer(
        self,
        query: str,
        context: str,
        timeout_seconds: float | None = None,
    ) -> str:
        message = self.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是一个中文 RAG 问答助手。只基于给定上下文回答，"
                        "不要编造上下文外的信息。回答要简洁，最多 5 条要点。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"问题：{query}\n\n"
                        f"上下文：\n{context}\n\n"
                        "请给出最终答案。如果上下文不足，请明确说依据不足。"
                    ),
                },
            ],
            timeout_seconds=timeout_seconds,
        )
        content = message.get("content", "")
        return self._strip_thinking(content).strip()

    def _strip_thinking(self, text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
