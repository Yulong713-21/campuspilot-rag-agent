#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${CAMPUSPILOT_REPO_DIR:-/opt/campuspilot/campuspilot-rag-agent}"
SCRIPT_DIR="$REPO_DIR/deploy/production"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$REPO_DIR/.env"
STATE_DIR="${CAMPUSPILOT_STATE_DIR:-/opt/campuspilot/deploy-state}"
STATE_FILE="$STATE_DIR/previous.env"
RUNTIME_DIR="$SCRIPT_DIR/runtime-data"
NGINX_TEMPLATE="$SCRIPT_DIR/nginx.conf"
NGINX_SITE="/etc/nginx/sites-available/campuspilot"
NGINX_ENABLED="/etc/nginx/sites-enabled/campuspilot"
PUBLIC_URL="${CAMPUSPILOT_PUBLIC_URL:-http://43.108.32.225}"
APP_NAME="campuspilot"
CANDIDATE_STARTED=0

diagnostics() {
  echo "--- deployment diagnostics ---" >&2
  docker ps -a >&2 || true
  docker logs --tail 100 "$APP_NAME" >&2 || true
  free -h >&2 || true
  df -h / >&2 || true
}

on_error() {
  local status=$?
  trap - ERR
  echo "ERROR deployment failed with status $status" >&2
  if [[ "$CANDIDATE_STARTED" -eq 1 && -f "$STATE_FILE" ]]; then
    echo "Attempting automatic rollback" >&2
    "$SCRIPT_DIR/rollback.sh" --auto || true
  fi
  diagnostics
  exit "$status"
}
trap on_error ERR

require_env_name() {
  local name="$1"
  if ! grep -qE "^${name}=.+" "$ENV_FILE"; then
    MISSING_ENV+=("$name")
  fi
}

read_env_value() {
  local name="$1"
  sed -n "s/^${name}=//p" "$ENV_FILE" | tail -n 1 | tr -d '\r'
}

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "ERROR deployment requires root" >&2
  exit 1
fi
if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "ERROR repository is missing: $REPO_DIR" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR environment file is missing: $ENV_FILE" >&2
  exit 1
fi

cd "$REPO_DIR"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR repository has uncommitted changes" >&2
  git status --short >&2
  exit 1
fi
if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "ERROR deployment repository must be on main" >&2
  exit 1
fi

MISSING_ENV=()
require_env_name CAMPUSPILOT_CLOUD_LLM_ENABLED
require_env_name CAMPUSPILOT_VECTOR_SEARCH_ENABLED
require_env_name CAMPUSPILOT_RERANKER_ENABLED
if [[ "$(read_env_value CAMPUSPILOT_CLOUD_LLM_ENABLED)" =~ ^(1|true|yes|on)$ ]]; then
  require_env_name CAMPUSPILOT_OPENAI_BASE_URL
  require_env_name CAMPUSPILOT_OPENAI_MODEL
  require_env_name CAMPUSPILOT_OPENAI_API_KEY
fi
if [[ "${#MISSING_ENV[@]}" -gt 0 ]]; then
  printf 'ERROR missing required environment variables:\n' >&2
  printf '  %s\n' "${MISSING_ENV[@]}" >&2
  exit 1
fi

mkdir -p "$STATE_DIR" "$RUNTIME_DIR/logs" "$RUNTIME_DIR/official_sources" \
  "$RUNTIME_DIR/vector" "$RUNTIME_DIR/models"

git fetch origin main --tags
PREVIOUS_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/main)"
if ! git merge-base --is-ancestor "$PREVIOUS_SHA" "$REMOTE_SHA"; then
  echo "ERROR origin/main is not a fast-forward of the deployed revision" >&2
  exit 1
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$STATE_DIR/backups/$TIMESTAMP"
mkdir -p "$BACKUP_DIR/logs"
PREVIOUS_IMAGE=""
if docker inspect "$APP_NAME" >/dev/null 2>&1; then
  CURRENT_IMAGE_ID="$(docker inspect "$APP_NAME" --format '{{.Image}}')"
  PREVIOUS_IMAGE="campuspilot:${PREVIOUS_SHA:0:12}"
  docker tag "$CURRENT_IMAGE_ID" "$PREVIOUS_IMAGE"
  docker cp "$APP_NAME:/app/logs/." "$BACKUP_DIR/logs/" >/dev/null 2>&1 || true
fi

PREVIOUS_NGINX_BACKUP=""
if [[ -f "$NGINX_SITE" ]]; then
  PREVIOUS_NGINX_BACKUP="$BACKUP_DIR/nginx.conf"
  cp -a "$NGINX_SITE" "$PREVIOUS_NGINX_BACKUP"
fi

{
  printf 'PREVIOUS_SHA=%q\n' "$PREVIOUS_SHA"
  printf 'PREVIOUS_IMAGE=%q\n' "$PREVIOUS_IMAGE"
  printf 'PREVIOUS_NGINX_BACKUP=%q\n' "$PREVIOUS_NGINX_BACKUP"
  printf 'BACKUP_DIR=%q\n' "$BACKUP_DIR"
} >"$STATE_FILE"
chmod 0600 "$STATE_FILE"

git merge --ff-only origin/main
CANDIDATE_SHA="$(git rev-parse HEAD)"
CANDIDATE_IMAGE="campuspilot:$CANDIDATE_SHA"

echo "Building $CANDIDATE_IMAGE"
docker build \
  --label "org.opencontainers.image.revision=$CANDIDATE_SHA" \
  --tag "$CANDIDATE_IMAGE" \
  --tag campuspilot:latest \
  .

if docker inspect "$APP_NAME" >/dev/null 2>&1; then
  CANDIDATE_STARTED=1
  docker rm -f "$APP_NAME" >/dev/null
else
  CANDIDATE_STARTED=1
fi

export CAMPUSPILOT_IMAGE="$CANDIDATE_IMAGE"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d agent

for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:8010/health/live >/dev/null; then
    break
  fi
  sleep 2
done

"$SCRIPT_DIR/verify.sh" http://127.0.0.1:8010

install -m 0644 "$NGINX_TEMPLATE" "$NGINX_SITE"
ln -sfn "$NGINX_SITE" "$NGINX_ENABLED"
if ! nginx -t; then
  if [[ -n "$PREVIOUS_NGINX_BACKUP" ]]; then
    install -m 0644 "$PREVIOUS_NGINX_BACKUP" "$NGINX_SITE"
    nginx -t
  fi
  false
fi
systemctl reload nginx

"$SCRIPT_DIR/verify.sh" http://127.0.0.1
if "$SCRIPT_DIR/verify.sh" "$PUBLIC_URL"; then
  echo "PUBLIC PASS $PUBLIC_URL"
else
  echo "WARN application and Nginx are healthy but the public endpoint is unreachable" >&2
  echo "WARN likely cloud firewall/security-group issue" >&2
fi

trap - ERR
CANDIDATE_STARTED=0
echo "DEPLOY PASS sha=$CANDIDATE_SHA image=$CANDIDATE_IMAGE"
if [[ "$(read_env_value CAMPUSPILOT_VECTOR_SEARCH_ENABLED)" =~ ^(1|true|yes|on)$ ]]; then
  echo "VECTOR READY requested and verified"
else
  echo "WARN degraded deployment: vector retrieval disabled"
fi
docker ps --filter "name=^/${APP_NAME}$"
free -h
df -h /

