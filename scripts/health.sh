#!/usr/bin/env bash
# Hit /health on every agent service and print a summary.
set -u

# Load .env so we know which host ports are mapped
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi

CG_PORT="${CLAUDE_GATEWAY_PORT:-8001}"
OC_PORT="${OPENCLAW_PORT:-8002}"
HM_PORT="${HERMES_PORT:-8003}"

check() {
  local name="$1" url="$2"
  printf "  %-18s " "$name"
  if body=$(curl -fsS --max-time 5 "$url" 2>/dev/null); then
    printf "OK  %s\n" "$body"
  else
    printf "FAIL  %s\n" "$url"
    return 1
  fi
}

echo "Gateforge-Loom — health checks"
echo "================================"
fail=0
check "claude-gateway" "http://localhost:${CG_PORT}/health"  || fail=1
check "openclaw"       "http://localhost:${OC_PORT}/health"  || fail=1
check "hermes"         "http://localhost:${HM_PORT}/health"  || fail=1
echo "================================"
if [ "$fail" -eq 0 ]; then
  echo "All services healthy."
else
  echo "One or more services unhealthy."
  exit 1
fi
