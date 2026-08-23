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

"$SCRIPT_DIR/verify.sh" http://127.0.0.1:8010
"$SCRIPT_DIR/verify.sh" http://127.0.0.1
echo "ROLLBACK PASS image=$PREVIOUS_IMAGE sha=${PREVIOUS_SHA:-unknown}"
