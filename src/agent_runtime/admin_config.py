from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any


CONFIG_FIELDS: dict[str, tuple[str, str]] = {
    "cloud_llm_enabled": ("CAMPUSPILOT_CLOUD_LLM_ENABLED", "bool"),
    "openai_base_url": ("CAMPUSPILOT_OPENAI_BASE_URL", "str"),
    "openai_model": ("CAMPUSPILOT_OPENAI_MODEL", "str"),
    "openai_timeout_seconds": (
        "CAMPUSPILOT_OPENAI_TIMEOUT_SECONDS",
        "float",
    ),
    "retrieval_mode": ("CAMPUSPILOT_RETRIEVAL_MODE", "str"),
    "vector_search_enabled": ("CAMPUSPILOT_VECTOR_SEARCH_ENABLED", "bool"),
    "reranker_enabled": ("CAMPUSPILOT_RERANKER_ENABLED", "bool"),
    "rate_limit_per_minute": (
        "CAMPUSPILOT_RATE_LIMIT_PER_MINUTE",
        "int",
    ),
    "max_upload_bytes": ("CAMPUSPILOT_MAX_UPLOAD_BYTES", "int"),
}
SECRET_ENV_KEY = "CAMPUSPILOT_OPENAI_API_KEY"


def env_flag(name: str, default: bool = False) -> bool:
    fallback = "1" if default else "0"
    return os.environ.get(name, fallback).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class EnvironmentConfigStore:
    """Read and atomically update an allowlisted CampusPilot env file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def public_config(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field, (env_key, value_type) in CONFIG_FIELDS.items():
            raw = os.environ.get(env_key, self._default_value(field))
            values[field] = self._convert(raw, value_type)
        api_key = os.environ.get(SECRET_ENV_KEY, "")
        values["api_key_configured"] = bool(api_key)
        values["api_key_hint"] = f"...{api_key[-4:]}" if len(api_key) >= 4 else None
        values["env_file"] = str(self.path.resolve())
        return values

    def update(
        self,
        values: dict[str, Any],
        *,
        api_key: str | None = None,
    ) -> dict[str, str]:
        updates: dict[str, str] = {}
        for field, value in values.items():
            if field not in CONFIG_FIELDS or value is None:
                continue
            env_key, value_type = CONFIG_FIELDS[field]
            updates[env_key] = self._serialize(value, value_type)
        if api_key is not None and api_key.strip():
            updates[SECRET_ENV_KEY] = api_key.strip()
        self._write_updates(updates)
        os.environ.update(updates)
        return updates

    def _write_updates(self, updates: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        original = (
            self.path.read_text(encoding="utf-8").splitlines()
            if self.path.exists()
            else []
        )
        remaining = dict(updates)
        output: list[str] = []
        for line in original:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                output.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
            else:
                output.append(line)
        if remaining and output and output[-1] != "":
            output.append("")
        output.extend(f"{key}={value}" for key, value in remaining.items())
        content = "\n".join(output).rstrip() + "\n"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        temporary.replace(self.path)

    @staticmethod
    def _default_value(field: str) -> str:
        return {
            "cloud_llm_enabled": "0",
            "openai_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai_model": "qwen-plus",
            "openai_timeout_seconds": "60",
            "retrieval_mode": "full_bm25",
            "vector_search_enabled": "0",
            "reranker_enabled": "0",
            "rate_limit_per_minute": "0",
            "max_upload_bytes": str(10 * 1024 * 1024),
        }[field]

    @staticmethod
    def _convert(value: str, value_type: str) -> Any:
        if value_type == "bool":
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if value_type == "int":
            return int(value)
        if value_type == "float":
            return float(value)
        return value

    @staticmethod
    def _serialize(value: Any, value_type: str) -> str:
        if value_type == "bool":
            return "1" if bool(value) else "0"
        if value_type == "int":
            return str(int(value))
        if value_type == "float":
            return str(float(value))
        text = str(value).strip()
        if "\n" in text or "\r" in text:
            raise ValueError("environment values must be single-line")
        return text
