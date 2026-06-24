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

## Knowledge — `hermes-dmoe` (port 8004)

> **Optional service.** `hermes-dmoe` is the parameter-level knowledge
> sibling of `hermes`. It self-hosts a small open-weight base model
> (Llama-3.2-1B / Qwen2.5-1.5B) with a bank of per-knowledge-unit LoRA
> experts, and injects domain knowledge *into the weights* at decode time
> via Decoupled Mixture-of-Experts (DMoE). It is **not** on the default
> critical path — Brain/Hands/Memory work without it. See
> [`docs/references/README.md`](references/README.md) for the source paper.

### `GET /health`
```json
{
  "status": "ok",
  "service": "hermes-dmoe",
  "stub_mode": true,
  "base_model": "Qwen2.5-1.5B",
  "experts_loaded": 27613,
  "bank_size_gib": 13.08,
  "router": "bm25",
  "tau": 2.0,
  "top_k": 3,
  "ts": "..."
}
```

### `GET /experts`
Returns a summary of the LoRA expert bank (the router's surrogate index).
```json
{
  "count": 27613,
  "base_model": "Qwen2.5-1.5B",
  "lora": { "rank": 4, "alpha": 16, "target": "final_ffn" },
  "avg_expert_kib": 481,
  "experts": [
    {
      "id": "kb.hk_pdpo_s2",
      "surrogate_text": "HK PDPO Data Protection Principle 2 — accuracy & retention...",
      "tokens": 412,
      "updated_at": "2026-06-20T08:00:00+00:00"
    }
  ]
}
```

### `POST /inject`

Generate an answer with on-demand parametric knowledge injection. The base
model decodes normally; at each step the token entropy
`TU_t = -Σ p_t(v) log p_t(v)` is measured, and **only when `TU_t > tau`** does
the BM25 router select the Top-k experts for the current query span and merge
their LoRA deltas into the effective weights (`θ_eff = θ + Σ Δθ_i`).

Request:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "prompt": "What retention limit applies to patient records under HK PDPO?",
  "max_tokens": 512,
  "tau": 2.0,
  "top_k": 3
}
```
`tau` and `top_k` are optional per-request overrides of the service defaults.

Response:
```json
{
  "job_id": "job_2026_05_08_a3f7",
  "answer": "Under HK PDPO DPP2, personal data must not be kept longer than...",
  "experts_used": ["kb.hk_pdpo_s2", "kb.hk_pdpo_dpp2", "kb.med_record_retention"],
  "trigger_count": 4,
  "tokens_in": 38,
  "tokens_out": 121
}
```
`trigger_count` is how many decode steps exceeded `tau` and fired the router;
`experts_used` is the union of experts merged across all triggers.

### `POST /experts/upsert`

Add or replace a knowledge expert. The base model stays frozen; only a new
LoRA adapter is trained (rank 4, α=16, lr 1e-5, 1 epoch, final-layer FFN) and
the router's BM25 index is updated incrementally — no full re-index, no
base-model retraining.

Request:
```json
{
  "id": "kb.hk_pdpo_s2",
  "source_text": "<canonical passage>",
  "surrogate_text": "HK PDPO Data Protection Principle 2 — accuracy & retention...",
  "qa_pairs": [
    {"q": "How long may records be kept?", "a": "No longer than necessary..."}
  ]
}
```
If `qa_pairs` is omitted the service synthesises 1 paraphrase + 3 Q&A pairs
(PRAG recipe) before training the adapter.

Response:
```json
{
  "stored": { "id": "kb.hk_pdpo_s2", "expert_kib": 481, "reindexed": true }
}
```

### `DELETE /experts/{id}`

Remove an expert adapter and drop it from the router index. Because experts
are decoupled from the frozen base, deletion is instant and leaves the base
model and all other experts untouched.
```json
{ "deleted": "kb.hk_pdpo_s2", "reindexed": true }
```

> **PHI / regulated data:** do **not** bake patient-identifiable or otherwise
> regulated data into experts — once trained into a LoRA delta it is not
> cleanly retrievable or redactable. Keep that class of data in `hermes`
> (`/recall` + `/write`), which supports targeted deletion and redaction.

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
| `EXPERT_NOT_FOUND` | hermes-dmoe | No expert with that `id` | no |
| `BANK_OOM` | hermes-dmoe | Expert bank exceeded GPU/host memory | no — evict or shard |
| `ROUTER_EMPTY` | hermes-dmoe | BM25 index has no experts to select | no — upsert experts first |
| `BASE_MODEL_UNAVAILABLE` | hermes-dmoe | Self-hosted base model not loaded | no — degrade to `hermes` RAG |
