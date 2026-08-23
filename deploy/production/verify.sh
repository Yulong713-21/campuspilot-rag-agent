#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${1:-http://127.0.0.1:8010}"
BASE_URL="${BASE_URL%/}"
TIMEOUT_SECONDS="${CAMPUSPILOT_VERIFY_TIMEOUT_SECONDS:-30}"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

request_json() {
  local method="$1"
  local path="$2"
  local output="$3"
  local body="${4:-}"
  local args=(
    --fail
    --silent
    --show-error
    --connect-timeout 10
    --max-time "$TIMEOUT_SECONDS"
    --request "$method"
    --output "$output"
    "${BASE_URL}${path}"
  )
  if [[ -n "$body" ]]; then
    args+=(--header 'Content-Type: application/json' --data-binary "@$body")
  fi
  curl "${args[@]}"
}

request_json GET /health/live "$TEMP_DIR/live.json"
request_json GET /health/ready "$TEMP_DIR/ready.json"
request_json GET /health "$TEMP_DIR/health.json"
request_json GET / "$TEMP_DIR/frontend.html"

cat >"$TEMP_DIR/planner-request.json" <<'JSON'
{
  "program_variant_id": "MONASH-C6001-EL2",
  "handbook_year": 2026,
  "study_stream": "Industry Experience",
  "completed_courses": ["FIT5057"],
  "max_courses_per_semester": 4,
  "preserve_policy_flexibility": true,
  "start_semester": "2026-S2"
}
JSON

request_json POST /api/plans/generate "$TEMP_DIR/planner.json" "$TEMP_DIR/planner-request.json"

python3 - "$TEMP_DIR" "$BASE_URL" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
base_url = sys.argv[2]

live = json.loads((root / "live.json").read_text(encoding="utf-8"))
ready = json.loads((root / "ready.json").read_text(encoding="utf-8"))
health = json.loads((root / "health.json").read_text(encoding="utf-8"))
planner = json.loads((root / "planner.json").read_text(encoding="utf-8"))
frontend = (root / "frontend.html").read_text(encoding="utf-8")

assert live.get("status") == "alive", live
assert ready.get("status") == "ready", ready
assert health.get("status") == "ok", health
assert "C6001 Planner Demo" in frontend, "Demo-first frontend marker missing"

plans = planner.get("plans") or []
validation = planner.get("validation") or {}
evidence = planner.get("evidence") or []
official_links = [
    item for item in evidence if item.get("source_url") or item.get("url")
]
assert len(plans) == 3, f"expected three plans, got {len(plans)}"
assert validation and validation.get("all_valid") is True, validation
assert evidence, "planner evidence is missing"
assert official_links, "planner official evidence links are missing"

vector_enabled = bool(ready.get("vector_search_enabled"))
retrieval_mode = str(health.get("retrieval_mode") or "")
if vector_enabled:
    assert "milvus" in retrieval_mode.lower(), retrieval_mode
    vector_status = "READY"
    vector_note = retrieval_mode
else:
    vector_status = "DISABLED"
    vector_note = "WARN vector retrieval disabled"

print(f"PASS base_url={base_url}")
print("PASS health/live")
print("PASS health/ready")
print("PASS health")
print("PASS frontend")
print(
    "PASS planner "
    f"plans={len(plans)} all_valid={validation.get('all_valid')} "
    f"evidence={len(evidence)} official_links={len(official_links)}"
)
print(f"VECTOR_STATUS={vector_status} {vector_note}")
PY

