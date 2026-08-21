from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="验证 CampusPilot 2–3 个项目版本的对比契约。"
    )
    parser.add_argument(
        "version_ids",
        nargs="+",
        type=int,
        help="数据库中的 program_version.id，数量必须为 2 或 3。",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8090/programs/compare",
        help="tj-campus 直连地址或 Gateway /cps/programs/compare 地址。",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="使用内置契约样例运行观察逻辑，不要求服务已启动。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 2 <= len(args.version_ids) <= 3:
        raise SystemExit("version_ids 必须包含 2 或 3 个项目版本 ID")
    if args.sample:
        payload = sample_payload(args.version_ids)
    else:
        request = Request(
            args.url,
            data=json.dumps({"programVersionIds": args.version_ids}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except (HTTPError, URLError) as exc:
            raise SystemExit(f"对比接口调用失败: {exc}") from exc

    result = payload.get("data", payload)
    programs = result.get("programs", [])
    differences = result.get("differences", [])
    evaluation = {
        "selection_count_valid": len(programs) == len(args.version_ids),
        "differences_exposed": bool(differences),
        "official_sources_complete": all(
            item.get("sourceUrl") for item in programs
        ),
    }
    observation = {
        "trace_tools": ["load_program_versions", "compare_program_versions"],
        "answer_source": "versioned_official_catalog",
        "confidence": "high" if all(evaluation.values()) else "low",
        "evaluation": evaluation,
        "next_action": "review_highlighted_differences",
        "programs": programs,
        "differences": differences,
        "disclaimer": result.get("disclaimer"),
    }
    print(json.dumps(observation, ensure_ascii=False, indent=2))
    return 0 if all(evaluation.values()) else 1


def sample_payload(version_ids: list[int]) -> dict[str, object]:
    durations = [24, 18, 12]
    credits = [96, 72, 48]
    programs = [
        {
            "programVersionId": version_id,
            "universityName": "Monash University",
            "programCode": "C6001",
            "entryLevel": f"ENTRY_LEVEL_{index + 1}",
            "durationMonths": durations[index],
            "totalCredits": credits[index],
            "sourceUrl": "https://handbook.monash.edu/current/courses/C6001",
        }
        for index, version_id in enumerate(version_ids)
    ]
    return {
        "programs": programs,
        "differences": [
            {
                "field": "durationMonths",
                "label": "学制（月）",
                "values": durations[: len(version_ids)],
                "different": True,
            }
        ],
        "disclaimer": "内置样例仅验证观察契约，不代表实时项目数据。",
    }


if __name__ == "__main__":
    raise SystemExit(main())
