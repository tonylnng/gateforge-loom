# API Contract

Every inter-service call is a JSON-over-HTTP POST. Schemas below are
authoritative — if the code disagrees, the code is wrong.

## Common

- All requests carry `Content-Type: application/json`.
- All requests *may* carry `Authorization: Bearer ${INTERNAL_API_TOKEN}`.
  When the env var is unset, auth is bypassed (dev only).
- All responses include the original `job_id` for traceability.
- Errors use HTTP status codes + a JSON body: `{ "detail": "<reason>" }`.

---

## Brain — `claude-gateway` (port 8001)

### `GET /health`
```json
{
  "status": "ok",
  "service": "claude-gateway",
  "stub_mode": true,
  "model": "claude-sonnet-4-20250514",
  "ts": "2026-05-08T10:00:00+00:00"
}
```

### `POST /plan`

Request:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "user_intent": "Generate weekly competitor analysis report",
  "context": {
    "user_id": "tony",
    "constraints": ["public sources only"],
    "deadline_iso": "2026-05-09T18:00:00+08:00"
  },
  "memory_hits": []
}
```

Response:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "plan_version": 1,
  "rationale": "Three competitors identified...",
  "steps": [
    {
      "step_id": "s1",
      "agent": "openclaw",
      "tool": "web.fetch",
      "input": {"url": "https://example.com"},
      "depends_on": [],
      "expected_output_schema": "ref:schemas/web_fetch_output.json",
      "timeout_sec": 30,
      "max_retries": 2
    }
  ],
  "estimated_cost_usd": 0.05
}
```

### `POST /merge`

Request: `{ job_id, draft_plan, memory_hits[] }`
Response: same shape as `/plan`, with `plan_version` incremented and
`rationale` extended with applied SOP IDs.

### `POST /synthesize`

Request:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "step_results": [
    {"step_id": "s1", "output": {...}, "artifacts": ["s3://..."]}
  ],
  "output_format": "markdown",
  "language": "en"
}
```

Response:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "artifact_uri": "s3://artifacts/job_2026_05_08_a3f7/report.md",
  "summary": "...",
  "tokens_in": 8421,
  "tokens_out": 2104
}
```

---

## Hands — `openclaw` (port 8002)

### `GET /health`
```json
{ "status": "ok", "service": "openclaw", "stub_mode": true, "tools_loaded": 4, "ts": "..." }
```

### `GET /tools`
Returns the catalogue Claude reads at planning time.
```json
{
  "tools": [
    {"name": "web.fetch",      "side_effects": "none",       "avg_latency_ms": 800,  "input_schema": "ref:schemas/web_fetch_input.json"},
    {"name": "browser.action", "side_effects": "network",    "avg_latency_ms": 8000, "input_schema": "ref:schemas/browser_action_input.json"},
    {"name": "shell.run",      "side_effects": "filesystem", "avg_latency_ms": 2000, "input_schema": "ref:schemas/shell_run_input.json"},
    {"name": "api.call",       "side_effects": "external",   "avg_latency_ms": 1500, "input_schema": "ref:schemas/api_call_input.json"}
  ]
}
```

### `POST /execute`

Request:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "step_id": "s2",
  "tool": "browser.action",
  "input": { "actions": [...] },
  "context_keys": ["job_2026_05_08_a3f7:s1"],
  "timeout_sec": 180
}
```

Response (success):
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "step_id": "s2",
  "status": "success",
  "output": { ... },
  "artifacts": [{"uri": "s3://...", "kind": "screenshot"}],
  "execution_time_ms": 12450,
  "tool_version": "openclaw-stub-0.1.0"
}
```

Response (failure):
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "step_id": "s2",
  "status": "error",
  "error": {
    "code": "SELECTOR_TIMEOUT",
    "message": ".price-table not found within 30s",
    "retryable": true,
    "diagnostic_artifact": "s3://..."
  },
  "execution_time_ms": 30100
}
```

---

## Memory — `hermes` (port 8003)

### `GET /health`
```json
{ "status": "ok", "service": "hermes", "stub_mode": true, "db": "ok", "ts": "..." }
```

### `POST /recall`

Request:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "query": "weekly competitor analysis",
  "kinds": ["sop", "episodic"],
  "top_k": 5,
  "filters": {"min_score": 0.75, "max_age_days": 90}
}
```

Response:
```json
{
  "hits": [
    {
      "id": "sop.competitor_research",
      "kind": "sop",
      "score": 0.91,
      "content_md": "# SOP...",
      "applied_count": 14,
      "success_rate": 0.93
    }
  ]
}
```

### `POST /write`

Request:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "outcome": "success",
  "duration_ms": 184500,
  "episode": {
    "intent": "weekly competitor analysis",
    "plan_version": 2,
    "step_summaries": [
      {"step_id": "s1", "status": "success", "duration_ms": 1200}
    ],
    "lessons": ["Selector .price-table changed to .pricing-grid; update SOP."]
  },
  "sop_updates": [
    {"id": "sop.competitor_research", "patch": "Step 2 selector: prefer .pricing-grid"}
  ]
}
```

Response:
```json
{ "stored": { "episodic_id": "ep_...", "sop_versions_bumped": ["sop.competitor_research.v2"] } }
```

---

## Error codes

| Code | Service | Meaning | Retryable |
|---|---|---|---|
| `UNKNOWN_TOOL` | OpenClaw | Tool not in catalogue | no |
| `SELECTOR_TIMEOUT` | OpenClaw | Browser couldn't find element | yes |
| `UPSTREAM_TIMEOUT` | any | LLM / API slow | yes |
| `SCHEMA_INVALID` | n8n validator | Output didn't match expected schema | once with `repair=true` |
| `BUDGET_EXCEEDED` | Claude Gateway | Per-job token budget hit | no |
| `DB_UNAVAILABLE` | Hermes | Postgres down | no — degrade gracefully |
