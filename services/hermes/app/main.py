"""Hermes — Memory layer.

Endpoints (per docs/api-contract.md §5):
  POST /recall    retrieve relevant memories (SOP + episodic)
  POST /write     persist memory after a job completes
  GET  /health    liveness probe + DB ping
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
STUB_MODE = os.getenv("STUB_MODE", "1") == "1"
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("hermes")

app = FastAPI(title="Hermes Memory", version="0.1.0")


# ---------- Auth dependency ----------
def require_token(authorization: str | None = Header(default=None)) -> None:
    if not INTERNAL_TOKEN:
        return
    if authorization != f"Bearer {INTERNAL_TOKEN}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")


def db_conn() -> psycopg.Connection:
    if not DATABASE_URL:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "DATABASE_URL not set")
    return psycopg.connect(DATABASE_URL, autocommit=True)


# ---------- Schemas ----------
class RecallFilters(BaseModel):
    min_score: float = 0.7
    max_age_days: int | None = None


class RecallRequest(BaseModel):
    job_id: str
    query: str
    kinds: list[str] = Field(default_factory=lambda: ["sop", "episodic"])
    top_k: int = 5
    filters: RecallFilters = Field(default_factory=RecallFilters)


class MemoryHit(BaseModel):
    id: str
    kind: str
    score: float
    content_md: str | None = None
    summary: str | None = None
    applied_count: int | None = None
    success_rate: float | None = None
    outcome: str | None = None


class RecallResponse(BaseModel):
    hits: list[MemoryHit]


class StepSummary(BaseModel):
    step_id: str
    status: str
    duration_ms: int
    note: str | None = None


class Episode(BaseModel):
    intent: str
    plan_version: int = 1
    step_summaries: list[StepSummary] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)


class SOPUpdate(BaseModel):
    id: str
    patch: str


class WriteRequest(BaseModel):
    job_id: str
    outcome: str
    duration_ms: int
    episode: Episode
    sop_updates: list[SOPUpdate] = Field(default_factory=list)


class WriteResponse(BaseModel):
    stored: dict[str, Any]


# ---------- Endpoints ----------
@app.get("/health")
def health() -> dict[str, Any]:
    db_status = "unknown"
    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            db_status = "ok"
    except Exception as e:  # noqa: BLE001
        db_status = f"error: {e.__class__.__name__}"
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "service": "hermes",
        "stub_mode": STUB_MODE,
        "db": db_status,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/recall", response_model=RecallResponse)
def recall(req: RecallRequest, authorization: str | None = Header(default=None)) -> RecallResponse:
    require_token(authorization)
    log.info("recall job_id=%s query=%r kinds=%s", req.job_id, req.query[:80], req.kinds)

    hits: list[MemoryHit] = []
    try:
        with db_conn() as conn, conn.cursor() as cur:
            if "sop" in req.kinds:
                cur.execute(
                    """
                    SELECT DISTINCT ON (id) id, version, title, content_md,
                                            applied_count, success_rate
                    FROM sop
                    ORDER BY id, version DESC
                    LIMIT %s
                    """,
                    (req.top_k,),
                )
                for row in cur.fetchall():
                    sop_id, _ver, _title, content_md, applied, sr = row
                    hits.append(
                        MemoryHit(
                            id=sop_id,
                            kind="sop",
                            score=0.85,  # stub similarity
                            content_md=content_md,
                            applied_count=applied,
                            success_rate=float(sr) if sr is not None else None,
                        )
                    )
            if "episodic" in req.kinds:
                cur.execute(
                    """
                    SELECT id, summary, outcome
                    FROM episodic_memory
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (req.top_k,),
                )
                for row in cur.fetchall():
                    ep_id, summary, outcome = row
                    hits.append(
                        MemoryHit(
                            id=ep_id,
                            kind="episodic",
                            score=0.78,
                            summary=summary,
                            outcome=outcome,
                        )
                    )
    except Exception as e:  # noqa: BLE001
        log.warning("recall db error: %s — returning empty hits (degradable)", e)
        return RecallResponse(hits=[])

    return RecallResponse(hits=hits[: req.top_k])


@app.post("/write", response_model=WriteResponse)
def write(req: WriteRequest, authorization: str | None = Header(default=None)) -> WriteResponse:
    require_token(authorization)
    log.info("write job_id=%s outcome=%s sop_updates=%d", req.job_id, req.outcome, len(req.sop_updates))

    episodic_id = f"ep_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
    bumped: list[str] = []

    summary = (
        f"intent={req.episode.intent}; outcome={req.outcome}; "
        f"steps={len(req.episode.step_summaries)}; "
        f"lessons={'|'.join(req.episode.lessons)[:200]}"
    )
    metadata = {
        "duration_ms": req.duration_ms,
        "plan_version": req.episode.plan_version,
        "step_summaries": [s.model_dump() for s in req.episode.step_summaries],
    }

    try:
        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO episodic_memory
                    (id, job_id, intent, outcome, summary, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    episodic_id,
                    req.job_id,
                    req.episode.intent,
                    req.outcome,
                    summary,
                    json.dumps(metadata),
                ),
            )

            for upd in req.sop_updates:
                cur.execute(
                    "SELECT MAX(version) FROM sop WHERE id = %s",
                    (upd.id,),
                )
                row = cur.fetchone()
                next_version = (row[0] or 0) + 1 if row else 1
                cur.execute(
                    """
                    INSERT INTO sop (id, version, title, content_md, applied_count)
                    VALUES (%s, %s, %s, %s, 0)
                    """,
                    (
                        upd.id,
                        next_version,
                        f"{upd.id} v{next_version}",
                        upd.patch,
                    ),
                )
                bumped.append(f"{upd.id}.v{next_version}")
    except Exception as e:  # noqa: BLE001
        log.error("write db error: %s", e)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"db error: {e}")

    return WriteResponse(stored={"episodic_id": episodic_id, "sop_versions_bumped": bumped})
