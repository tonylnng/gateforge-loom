"""Claude Gateway — Brain layer.

Endpoints (per docs/api-contract.md §3):
  POST /plan         decompose task into executable plan
  POST /merge        merge memory hits into final plan
  POST /synthesize   generate final report from step results
  GET  /health       liveness probe
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
STUB_MODE = os.getenv("STUB_MODE", "1") == "1"
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("claude-gateway")

app = FastAPI(title="Claude Gateway", version="0.1.0")


# ---------- Auth dependency ----------
def require_token(authorization: str | None = Header(default=None)) -> None:
    if not INTERNAL_TOKEN:  # auth disabled in dev if blank
        return
    if authorization != f"Bearer {INTERNAL_TOKEN}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")


# ---------- Schemas ----------
class PlanContext(BaseModel):
    user_id: str | None = None
    constraints: list[str] = Field(default_factory=list)
    deadline_iso: str | None = None


class PlanRequest(BaseModel):
    job_id: str
    user_intent: str
    context: PlanContext = Field(default_factory=PlanContext)
    memory_hits: list[dict[str, Any]] = Field(default_factory=list)


class PlanStep(BaseModel):
    step_id: str
    agent: str  # "openclaw" | "claude"
    tool: str
    input: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    expected_output_schema: str | None = None
    timeout_sec: int = 60
    max_retries: int = 1


class PlanResponse(BaseModel):
    job_id: str
    plan_version: int = 1
    rationale: str
    steps: list[PlanStep]
    estimated_cost_usd: float = 0.0


class MergeRequest(BaseModel):
    job_id: str
    draft_plan: dict[str, Any]
    memory_hits: list[dict[str, Any]] = Field(default_factory=list)


class StepResult(BaseModel):
    step_id: str
    output: dict[str, Any] | None = None
    artifacts: list[str] = Field(default_factory=list)


class SynthesizeRequest(BaseModel):
    job_id: str
    step_results: list[StepResult]
    output_format: str = "markdown"
    language: str = "en"


class SynthesizeResponse(BaseModel):
    job_id: str
    artifact_uri: str
    summary: str
    tokens_in: int
    tokens_out: int


# ---------- Endpoints ----------
@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "claude-gateway",
        "stub_mode": STUB_MODE,
        "model": CLAUDE_MODEL,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/plan", response_model=PlanResponse, dependencies=[])
def plan(req: PlanRequest, authorization: str | None = Header(default=None)) -> PlanResponse:
    require_token(authorization)
    log.info("plan request job_id=%s intent=%r", req.job_id, req.user_intent[:80])

    if not STUB_MODE:
        # TODO: call Anthropic API and parse a structured plan
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "live mode not wired yet")

    # Stub: deterministic 3-step plan good for end-to-end wiring
    return PlanResponse(
        job_id=req.job_id,
        plan_version=1,
        rationale=f"Stub plan for intent: {req.user_intent[:100]}",
        steps=[
            PlanStep(
                step_id="s1",
                agent="openclaw",
                tool="web.fetch",
                input={"url": "https://example.com", "method": "GET"},
                expected_output_schema="ref:schemas/web_fetch_output.json",
                timeout_sec=30,
                max_retries=2,
            ),
            PlanStep(
                step_id="s2",
                agent="openclaw",
                tool="shell.run",
                input={"cmd": "echo processed"},
                depends_on=["s1"],
                timeout_sec=15,
            ),
            PlanStep(
                step_id="s3",
                agent="claude",
                tool="synthesize",
                input={"template": "default_report"},
                depends_on=["s1", "s2"],
                timeout_sec=60,
            ),
        ],
        estimated_cost_usd=0.05,
    )


@app.post("/merge", response_model=PlanResponse)
def merge(req: MergeRequest, authorization: str | None = Header(default=None)) -> PlanResponse:
    require_token(authorization)
    log.info("merge request job_id=%s hits=%d", req.job_id, len(req.memory_hits))

    if not STUB_MODE:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "live mode not wired yet")

    # Stub: bump plan_version and prepend a rationale note about applied SOPs
    draft = req.draft_plan or {}
    sop_ids = [h.get("id") for h in req.memory_hits if h.get("kind") == "sop"]
    rationale = (
        f"Applied {len(sop_ids)} SOP(s): {sop_ids}. "
        f"Original rationale: {draft.get('rationale', 'n/a')}"
    )
    steps = draft.get("steps") or [
        PlanStep(step_id="s1", agent="openclaw", tool="web.fetch",
                 input={"url": "https://example.com"}).model_dump()
    ]
    return PlanResponse(
        job_id=req.job_id,
        plan_version=int(draft.get("plan_version", 1)) + 1,
        rationale=rationale,
        steps=[PlanStep(**s) for s in steps],
        estimated_cost_usd=float(draft.get("estimated_cost_usd", 0.0)),
    )


@app.post("/synthesize", response_model=SynthesizeResponse)
def synthesize(req: SynthesizeRequest, authorization: str | None = Header(default=None)) -> SynthesizeResponse:
    require_token(authorization)
    log.info("synthesize job_id=%s steps=%d", req.job_id, len(req.step_results))

    if not STUB_MODE:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "live mode not wired yet")

    artifact_id = uuid.uuid4().hex[:12]
    return SynthesizeResponse(
        job_id=req.job_id,
        artifact_uri=f"s3://artifacts/{req.job_id}/report-{artifact_id}.md",
        summary=f"Stub report assembled from {len(req.step_results)} step results.",
        tokens_in=1234,
        tokens_out=567,
    )
