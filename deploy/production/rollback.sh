#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${CAMPUSPILOT_REPO_DIR:-/opt/campuspilot/campuspilot-rag-agent}"
SCRIPT_DIR="$REPO_DIR/deploy/production"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$REPO_DIR/.env"
STATE_DIR="${CAMPUSPILOT_STATE_DIR:-/opt/campuspilot/deploy-state}"
STATE_FILE="$STATE_DIR/previous.env"
NGINX_SITE="/etc/nginx/sites-available/campuspilot"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR rollback requires root" >&2
  exit 1
fi
if [[ ! -f "$STATE_FILE" ]]; then
  echo "ERROR rollback state is missing: $STATE_FILE" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR environment file is missing: $ENV_FILE" >&2
  exit 1
fi

# The state file contains only image/SHA/path metadata written by deploy.sh.
# shellcheck disable=SC1090
source "$STATE_FILE"
: "${PREVIOUS_IMAGE:?previous image is missing from rollback state}"

echo "Rolling back CampusPilot to $PREVIOUS_IMAGE"
cd "$REPO_DIR"
export CAMPUSPILOT_IMAGE="$PREVIOUS_IMAGE"

docker rm -f campuspilot >/dev/null 2>&1 || true
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d agent

for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:8010/health/live >/dev/null; then
    break
  fi
  sleep 2
done

for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:8010/health/ready >/dev/null; then
    break
  fi
  sleep 2
done

if [[ -n "${PREVIOUS_NGINX_BACKUP:-}" && -f "$PREVIOUS_NGINX_BACKUP" ]]; then
  install -m 0644 "$PREVIOUS_NGINX_BACKUP" "$NGINX_SITE"
  nginx -t
  systemctl reload nginx
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
curl -fsS --max-time 10 http://127.0.0.1:8010/health/live \
  -o "$TEMP_DIR/live.json"
curl -fsS --max-time 10 http://127.0.0.1:8010/health/ready \
  -o "$TEMP_DIR/ready.json"
curl -fsS --max-time 10 http://127.0.0.1/ -o "$TEMP_DIR/frontend.html"
curl -fsS --max-time 30 \
  -H "Content-Type: application/json" \
  --data '{"program_variant_id":"MONASH-C6001-EL2","handbook_year":2026,"study_stream":"Industry Experience","completed_courses":["FIT5057"],"max_courses_per_semester":4,"preserve_policy_flexibility":true,"start_semester":"2026-S2"}' \
  http://127.0.0.1:8010/api/plans/generate -o "$TEMP_DIR/planner.json"

# Rollback verification intentionally checks the stable cross-version contract.
# A previous release may not contain the newest frontend marker or evidence fields.
python3 - "$TEMP_DIR" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
live = json.loads((root / "live.json").read_text(encoding="utf-8"))
ready = json.loads((root / "ready.json").read_text(encoding="utf-8"))
planner = json.loads((root / "planner.json").read_text(encoding="utf-8"))
frontend = (root / "frontend.html").read_text(encoding="utf-8")

assert live.get("status") == "alive", live
assert ready.get("status") == "ready", ready
assert frontend.strip(), "rollback frontend is empty"
assert planner.get("plans"), "rollback planner returned no plans"
assert (planner.get("validation") or {}).get("all_valid") is True
PY

echo "ROLLBACK PASS image=$PREVIOUS_IMAGE sha=${PREVIOUS_SHA:-unknown}"
