#!/usr/bin/env bash
# End-to-end smoke test: plan -> recall -> merge -> execute -> write -> synthesize
# Requires `jq`. Run after `make up` and `make health`.
set -euo pipefail

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi

CG="http://localhost:${CLAUDE_GATEWAY_PORT:-8001}"
OC="http://localhost:${OPENCLAW_PORT:-8002}"
HM="http://localhost:${HERMES_PORT:-8003}"
TOKEN="${INTERNAL_API_TOKEN:-}"
AUTH=(-H "Authorization: Bearer ${TOKEN}")

JOB_ID="job_$(date +%Y%m%d_%H%M%S)_$RANDOM"
echo ">> JOB_ID=$JOB_ID"
echo

echo "[1/6] POST $CG/plan"
PLAN=$(curl -fsS -X POST "$CG/plan" "${AUTH[@]}" -H "Content-Type: application/json" -d "{
  \"job_id\": \"$JOB_ID\",
  \"user_intent\": \"weekly competitor analysis\",
  \"context\": {\"user_id\": \"tony\", \"constraints\": [\"public sources only\"]}
}")
echo "$PLAN" | jq '.steps | length' | xargs -I{} echo "    plan has {} steps"

echo "[2/6] POST $HM/recall"
RECALL=$(curl -fsS -X POST "$HM/recall" "${AUTH[@]}" -H "Content-Type: application/json" -d "{
  \"job_id\": \"$JOB_ID\",
  \"query\": \"weekly competitor analysis\",
  \"kinds\": [\"sop\", \"episodic\"],
  \"top_k\": 5
}")
HITS=$(echo "$RECALL" | jq '.hits | length')
echo "    recall returned $HITS hit(s)"

echo "[3/6] POST $CG/merge"
MERGED=$(curl -fsS -X POST "$CG/merge" "${AUTH[@]}" -H "Content-Type: application/json" -d "{
  \"job_id\": \"$JOB_ID\",
  \"draft_plan\": $PLAN,
  \"memory_hits\": $(echo "$RECALL" | jq '.hits')
}")
echo "    merged plan_version=$(echo "$MERGED" | jq -r '.plan_version')"

echo "[4/6] POST $OC/execute (one step)"
EXEC=$(curl -fsS -X POST "$OC/execute" "${AUTH[@]}" -H "Content-Type: application/json" -d "{
  \"job_id\": \"$JOB_ID\",
  \"step_id\": \"s1\",
  \"tool\": \"web.fetch\",
  \"input\": {\"url\": \"https://example.com\"}
}")
echo "    execute status=$(echo "$EXEC" | jq -r '.status') time_ms=$(echo "$EXEC" | jq -r '.execution_time_ms')"

echo "[5/6] POST $HM/write"
WRITE=$(curl -fsS -X POST "$HM/write" "${AUTH[@]}" -H "Content-Type: application/json" -d "{
  \"job_id\": \"$JOB_ID\",
  \"outcome\": \"success\",
  \"duration_ms\": 12345,
  \"episode\": {
    \"intent\": \"weekly competitor analysis\",
    \"plan_version\": 2,
    \"step_summaries\": [{\"step_id\": \"s1\", \"status\": \"success\", \"duration_ms\": 1200}],
    \"lessons\": [\"smoke test ok\"]
  },
  \"sop_updates\": []
}")
echo "    wrote episode=$(echo "$WRITE" | jq -r '.stored.episodic_id')"

echo "[6/6] POST $CG/synthesize"
SYNTH=$(curl -fsS -X POST "$CG/synthesize" "${AUTH[@]}" -H "Content-Type: application/json" -d "{
  \"job_id\": \"$JOB_ID\",
  \"step_results\": [{\"step_id\": \"s1\", \"output\": $(echo "$EXEC" | jq '.output')}]
}")
echo "    artifact=$(echo "$SYNTH" | jq -r '.artifact_uri')"

echo
echo "Smoke test passed."
