from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_runtime.openai_compatible_client import (  # noqa: E402
    OpenAICompatibleChatClient,
)
from agent_runtime.program_recommendation_interpreter import (  # noqa: E402
    CloudRecommendationProfileInterpreter,
)
from agent_runtime.program_recommendation_narrator import (  # noqa: E402
    ProgramRecommendationNarrator,
)
from campuspilot_core.program_recommendation import (  # noqa: E402
    ProgramRecommendationService,
)


DEFAULT_CASES = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "program_recommendation_naturalness_cases.json"
)
TEMPLATE_PHRASES = (
    "基于目前得到的",
    "我先从已收录的官方项目目录中筛出",
    "推荐用于缩小范围，不代表录取结论",
    "可以先不选专业",
    "我记下了你刚补充的信息",
)
EXPLANATION_MARKERS = (
    "因为",
    "因此",
    "所以",
    "考虑到",
    "结合",
    "意味着",
    "更适合",
    "优先",
    "衔接",
    "关键",
    "核心",
    "本质",
    "差异",
    "差别",
    "相比",
    "比起",
    "契合",
    "匹配",
    "更贴近",
    "综合来看",
    "毕竟",
    "取决于",
)
RISK_BOUNDARY_MARKERS = (
    "核验",
    "时效",
    "不代表",
    "不能",
    "需要结合",
    "仍要",
    "以当前官方信息为准",
)


def evaluate_case(
    service: ProgramRecommendationService,
    case: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = service.recommend(
            {
                "prompt": case["prompt"],
                "allow_agent_direction_recommendation": True,
                "max_results": 3,
            }
        )
        message = str(result.get("message") or "").strip()
        checks = {
            "llm_generated": str(result.get("answer_source", "")).startswith(
                "llm_"
            ),
            "reasonable_length": 80 <= len(message) <= 650,
            "template_free": not any(
                phrase in message for phrase in TEMPLATE_PHRASES
            ),
            "background_used": any(
                anchor in message for anchor in case["anchors"]
            ),
            "has_explanation": any(
                marker in message for marker in EXPLANATION_MARKERS
            ),
            "risk_boundary": (
                case["risk"] != "migration"
                or any(marker in message for marker in RISK_BOUNDARY_MARKERS)
            ),
        }
        natural = all(checks.values())
        return {
            **case,
            "natural": natural,
            "checks": checks,
            "answer_source": result.get("answer_source"),
            "message": message,
            "trace_tools": result.get("trace_tools", []),
        }
    except Exception as exc:
        return {
            **case,
            "natural": False,
            "checks": {},
            "answer_source": "evaluation_error",
            "message": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def write_report(
    path: Path,
    *,
    results: list[dict[str, Any]],
    planned_case_count: int,
    min_natural: int,
    stopped_reason: str | None = None,
) -> dict[str, Any]:
    results = sorted(results, key=lambda item: item["id"])
    natural_count = sum(item["natural"] for item in results)
    completed = len(results) == planned_case_count
    required = min(min_natural, planned_case_count)
    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "planned_case_count": planned_case_count,
        "completed": completed,
        "stopped_reason": stopped_reason,
        "natural_count": natural_count,
        "natural_rate": round(natural_count / max(len(results), 1), 4),
        "required_natural_count": required,
        "passed": completed and natural_count >= required,
        "results": results,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the 50-case CampusPilot recommendation naturalness evaluation."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--category", type=str, default="")
    parser.add_argument("--min-natural", type=int, default=28)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse completed case results from the output checkpoint.",
    )
    parser.add_argument(
        "--continue-on-llm-fallback",
        action="store_true",
        help="Keep evaluating after a case falls back from the cloud LLM.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / ".artifacts" / "recommendation-naturalness.json",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env", override=False)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.category:
        cases = [
            case for case in cases if case["category"] == args.category
        ]
    if args.limit:
        cases = cases[: args.limit]
    client = OpenAICompatibleChatClient.from_environment()
    service = ProgramRecommendationService(
        profile_interpreter=CloudRecommendationProfileInterpreter(client),
        narrator=ProgramRecommendationNarrator(client),
    )

    results_by_id: dict[str, dict[str, Any]] = {}
    if args.resume and args.output.exists():
        checkpoint = json.loads(args.output.read_text(encoding="utf-8"))
        results_by_id = {
            item["id"]: item
            for item in checkpoint.get("results", [])
            if item.get("id")
        }
    pending = [case for case in cases if case["id"] not in results_by_id]
    stopped_reason: str | None = None
    worker_count = max(1, args.workers)
    for offset in range(0, len(pending), worker_count):
        batch = pending[offset : offset + worker_count]
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(evaluate_case, service, case): case["id"]
                for case in batch
            }
            for future in as_completed(futures):
                item = future.result()
                results_by_id[item["id"]] = item
                print(
                    f"{item['id']} natural={item['natural']} "
                    f"source={item['answer_source']}"
                )
                write_report(
                    args.output,
                    results=list(results_by_id.values()),
                    planned_case_count=len(cases),
                    min_natural=args.min_natural,
                )
        batch_has_fallback = any(
            not str(results_by_id[case["id"]].get("answer_source", "")).startswith(
                "llm_"
            )
            for case in batch
        )
        if batch_has_fallback and not args.continue_on_llm_fallback:
            stopped_reason = "llm_fallback_detected"
            break

    summary = write_report(
        args.output,
        results=list(results_by_id.values()),
        planned_case_count=len(cases),
        min_natural=args.min_natural,
        stopped_reason=stopped_reason,
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))
    print(f"output={args.output}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
