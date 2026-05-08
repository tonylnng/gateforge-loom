-- ============================================================
-- Hermes long-term memory schema
-- Initialized once on first Postgres container boot.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---- Episodic memory: what happened on past jobs ----
CREATE TABLE IF NOT EXISTS episodic_memory (
    id           TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL,
    intent       TEXT NOT NULL,
    outcome      TEXT NOT NULL CHECK (outcome IN ('success', 'failed', 'partial', 'success_after_retry')),
    summary      TEXT NOT NULL,
    embedding    vector(1536),
    metadata     JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_episodic_intent  ON episodic_memory (intent);
CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic_memory (created_at DESC);
-- Vector index built once table has data:
-- CREATE INDEX ON episodic_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ---- SOP: distilled procedures ----
CREATE TABLE IF NOT EXISTS sop (
    id            TEXT NOT NULL,
    version       INT  NOT NULL,
    title         TEXT NOT NULL,
    content_md    TEXT NOT NULL,
    embedding     vector(1536),
    applied_count INT  NOT NULL DEFAULT 0,
    success_rate  NUMERIC(4,3),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);

CREATE INDEX IF NOT EXISTS idx_sop_id ON sop (id);

-- ---- Seed: one SOP so /recall returns something on day 1 ----
INSERT INTO sop (id, version, title, content_md, applied_count, success_rate)
VALUES (
    'sop.competitor_research',
    1,
    'Weekly Competitor Research SOP',
    E'# SOP: Competitor Research\n\n1. List target competitors from CRM tag `competitor`.\n2. Fetch public pricing pages; respect robots.txt.\n3. Extract pricing tables; normalize to USD.\n4. Diff against last week''s snapshot.\n5. Surface changes >5% in the report.\n',
    0,
    NULL
) ON CONFLICT DO NOTHING;
