#!/usr/bin/env bash
set -u

REPO_DIR="${CAMPUSPILOT_REPO_DIR:-/opt/campuspilot/campuspilot-rag-agent}"
APP_NAME="${CAMPUSPILOT_APP_NAME:-campuspilot}"
BASE_URL="${CAMPUSPILOT_STATUS_URL:-http://127.0.0.1:8010}"

section() {
  printf '\n== %s ==\n' "$1"
}

safe_curl() {
  local path="$1"
  if ! curl --fail --silent --show-error --max-time 10 "$BASE_URL$path"; then
    printf '\nUNAVAILABLE %s\n' "$path"
  else
    printf '\n'
  fi
}

section "timestamp"
date -u +%Y-%m-%dT%H:%M:%SZ

section "git revision"
git -C "$REPO_DIR" rev-parse --short=12 HEAD 2>&1 || true

section "containers"
docker ps --filter "name=^/${APP_NAME}$" 2>&1 || true

section "health live"
safe_curl "/health/live"

section "health ready"
safe_curl "/health/ready"

section "health diagnostics"
safe_curl "/health"

section "memory"
free -h 2>&1 || true

section "root filesystem"
df -h / 2>&1 || true

section "recent application logs"
docker logs --tail 100 "$APP_NAME" 2>&1 || true
