from __future__ import annotations

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.openai_compatible_client import OpenAICompatibleChatClient


def main() -> None:
    client = OpenAICompatibleChatClient.from_environment()
    result = client.chat(
        [
            {
                "role": "user",
                "content": "只回复：CampusPilot cloud ready",
            }
        ],
        temperature=0.0,
    )
    print(
        {
            "status": "ok",
            "model": result["model"],
            "content": result["message"].get("content"),
            "usage": result["usage"],
        }
    )


if __name__ == "__main__":
    main()
