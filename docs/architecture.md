# Architecture & Design Decisions

This document explains *why* Gateforge-Loom looks the way it does. Read it
when you're tempted to refactor; the constraints below were chosen on
purpose.

---

## Layering principle

Three concerns dominate every multi-agent system:

1. **Reasoning** — what should we do?
2. **Acting** — make it happen.
3. **Remembering** — get faster next time.

Most "agent" demos collapse all three into one prompt. That works for
demos. In production, you want them in separate processes so you can:

- Swap the LLM without rewriting tools
- Patch the browser tool without redeploying the planner
- Backup memory without coordinating with reasoning code
- Reason about cost per layer

Gateforge-Loom enforces this with one container per concern.

---

## Why a generic loom, not just three agents

Today: Brain, Hands, Memory. Tomorrow you'll want:

- A **Validator** that checks tool outputs against schemas
- A **Critic** that scores plans before execution
- A **Router** that picks specialist executors
- A **Reviewer** for human-in-the-loop steps
- An **Embedder** to keep Hermes' vectors fresh

The loom metaphor — threads woven by an orchestrator — was chosen so you
can keep adding threads without renaming the project or rewriting the
contract.

---

## Why n8n as orchestrator

Considered: Temporal, Airflow, Prefect, custom Python state machine.

Picked n8n because:
- **GUI workflow** — operators can see and tweak the pipeline
- **HTTP-first** — every node is a curl call, easy to debug
- **Cron + Webhook + Manual** triggers all built-in
- **Output sinks** (Notion, Slack, Drive, Discord, …) ship for free
- **Low operational weight** — single container, SQLite-backed by default

What n8n is *not* good at:
- Long-running streaming workflows (use Temporal)
- Strongly typed contracts (we layer JSON Schema on top)
- Multi-DC failover (we accept single-VM scope for the PoC)

---

## Why Redis *and* Postgres

| Data | Lives where | Why |
|---|---|---|
| In-flight job state | Redis | TTL'd, fast, horizontally scalable later |
| Plan + step results | Redis | Hot, accessed by every agent in the run |
| Distributed locks | Redis | `SET NX PX` is the right primitive |
| Episodic memory | Postgres | Durable, queryable, embeddings-friendly |
| SOPs (versioned) | Postgres | Need ACID for version bumps |
| Cost counters | Redis | Reset per-job; never historical |

The temptation is to put everything in Postgres "for simplicity". But Redis
is the right tool for transient, high-frequency, TTL-bound state.

---

## Why pgvector instead of a dedicated vector DB

Considered: Qdrant, Weaviate, Pinecone, Milvus.

Picked pgvector because:
- One DB to backup, one schema to evolve
- SQL joins between memories and other tables (job logs, costs, tenants)
- "Good enough" performance up to 1M+ vectors with ivfflat
- Same operational tooling as the rest of Postgres

Migrate to a dedicated vector DB if you cross 10M+ vectors or need <10 ms
P99 recall. Hermes' API is designed so the storage backend is swappable.

---

## Why DMoE for parametric memory

Considered for the Memory layer: prompt-level RAG only (status quo), full
fine-tuning, single merged LoRA, and **DMoE (Decoupled Mixture-of-Experts)**.

The existing `hermes` layer is **prompt-level**: it retrieves SOP/episodic
text and the Brain reads it as context. That is flexible and fully auditable,
but the knowledge never enters the model's parameter space — exactly the
shallow-injection limitation that
[DMoE (arXiv:2606.14243)](https://arxiv.org/abs/2606.14243) was designed to fix
(local copy: [`references/DMoE-2606.14243v1.pdf`](references/DMoE-2606.14243v1.pdf)).

Picked DMoE as an **optional sibling** (`hermes-dmoe`), not a replacement,
because:

- **Parameter-level depth, RAG-level updatability.** Each knowledge unit is an
  independent LoRA expert (`Δθ_i`). Add/update/remove one expert without
  retraining the base or disturbing the others — the same "new thread, no
  rewiring" property the loom already has, now inside the model.
- **Decoupled router.** A training-free BM25 index over each expert's text
  surrogate. Adding knowledge = inserting one index entry; no neural router to
  retrain, no re-coupling to the backbone.
- **Uncertainty-gated.** Experts fire only when token-entropy
  `TU = -Σ p log p > τ` (default `τ = 2.0`), so confident decoding pays zero
  extra cost.
- **KV-cache safe.** Experts attach only to the final-layer FFN, so cached
  key/value states from earlier layers stay valid (`θ_eff = θ + Σ Δθ_i`).

What DMoE is **not** good for here:

- **The Brain.** Claude via Anthropic/Vercel is a closed API — no weight
  access, so DMoE cannot touch it. `hermes-dmoe` therefore runs its own
  **self-hosted open base** (Llama-3.2-1B / Qwen2.5-1.5B in the paper).
- **Regulated data.** Knowledge baked into weights is harder to audit and
  redact than a retrievable row. Keep PHI / compliance-sensitive corpora in
  `hermes` (prompt-level, redactable); reserve `hermes-dmoe` experts for
  non-sensitive engineering and domain knowledge.
- **Tiny corpora.** If a few documents change hourly, plain `hermes` recall is
  simpler. DMoE pays off when the corpus is large, stable, and
  reasoning-heavy.

`hermes` and `hermes-dmoe` are complementary: fast auditable recall vs. deep
self-hosted injection. The orchestrator decides per step which to call.

---

## Stub mode

Every agent ships with `STUB_MODE=1` as the default. This is non-negotiable
because:

- You can wire the entire pipeline (n8n nodes + connections + auth) before
  paying for a single LLM token
- New contributors can run `make up` without API keys
- CI can run end-to-end smoke tests without spending money or hitting rate
  limits

Going live is a single env-var flip per service.

---

## Auth model

PoC: shared `INTERNAL_API_TOKEN`. Every agent checks
`Authorization: Bearer ${INTERNAL_API_TOKEN}`.

Production: per-service tokens issued by a small KMS, or mTLS via service
mesh. Whichever you pick, the agent code only needs to swap one dependency
function (`require_token`) — the contracts don't change.

---

## Error handling philosophy

Three rules:

1. **Agents fail loudly.** No silent swallows. Every error returns a
   structured JSON body with `code`, `message`, `retryable`.
2. **n8n owns retry policy.** Agents do not self-retry. The orchestrator
   has the global view (max retries, exponential backoff, dead-lettering).
3. **Memory is degradable.** If Hermes is down, the run *continues* with
   empty hits. Memory makes the system smarter, but is never on the
   critical path.

---

## Observability

Each container emits structured logs to stdout. Add later, in this order:

1. Aggregation — Loki / CloudWatch / Papertrail
2. Tracing — OpenTelemetry with `job_id` as trace ID, exported to
   Tempo / Honeycomb
3. Metrics — Prometheus scrapes `/metrics` (not yet implemented; FastAPI +
   `prometheus-fastapi-instrumentator` is a 3-line add)
4. Alerting — PagerDuty / OpsGenie / Discord webhook on healthcheck
   failures

---

## Cost guardrails

The Claude Gateway reads a per-job token budget from
`job:{id}:budget` in Redis. n8n initialises the counter at job creation.
The gateway decrements on every LLM call. Exceeding the budget returns
`402 Payment Required` and the job is marked `Failed`.

This isn't optional in production. One runaway loop on a $20/M-token model
can cost more than your VM bill for the month.

---

## Things explicitly out of scope for the PoC

- Multi-tenancy (`tenant_id` is sketched in the docs but not enforced)
- Authentication of *end users* (only inter-service auth)
- HA / multi-region
- A separate vector DB
- A UI other than n8n
- Streaming responses

All of these are valid extensions; none are needed to validate the
architecture.
