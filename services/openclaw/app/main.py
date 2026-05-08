"""OpenClaw — Hands layer.

Endpoints (per docs/api-contract.md §4):
  POST /execute   run one plan step
  GET  /tools     return tool catalog (consumed by Claude planner)
  GET  /health    liveness probe
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
STUB_MODE = os.getenv("STUB_MODE", "1") == "1"
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("openclaw")

app = FastAPI(title="OpenClaw Executor", version="0.1.0")


# ---------- Auth dependency ----------
def require_token(authorization: str | None = Header(default=None)) -> None:
    if not INTERNAL_TOKEN:
        return
    if authorization != f"Bearer {INTERNAL_TOKEN}":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bearer token")


# ---------- Tool catalog ----------
TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "web.fetch",
        "description": "GET a URL, return body and headers.",
        "input_schema": "ref:schemas/web_fetch_input.json",
        "side_effects": "none",
        "avg_latency_ms": 800,
    },
    {
        "name": "browser.action",
        "description": "Headful browser via Playwright; navigate, click, type, extract.",
        "input_schema": "ref:schemas/browser_action_input.json",
        "side_effects": "network",
        "avg_latency_ms": 8000,
    },
    {
        "name": "shell.run",
        "description": "Run an allow-listed shell command in a sandbox.",
        "input_schema": "ref:schemas/shell_run_input.json",
        "side_effects": "filesystem",
        "avg_latency_ms": 2000,
    },
    {
        "name": "api.call",
        "description": "Authenticated REST call to an allow-listed endpoint.",
        "input_schema": "ref:schemas/api_call_input.json",
        "side_effects": "external",
        "avg_latency_ms": 1500,
    },
]


# ---------- Schemas ----------
class ExecuteRequest(BaseModel):
    job_id: str
    step_id: str
    tool: str
    input: dict[str, Any]
    context_keys: list[str] = Field(default_factory=list)
    timeout_sec: int = 60


class ExecuteError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    diagnostic_artifact: str | None = None


class ExecuteResponse(BaseModel):
    job_id: str
    step_id: str
    status: str  # "success" | "error"
    output: dict[str, Any] | None = None
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    error: ExecuteError | None = None
    execution_time_ms: int = 0
    tool_version: str = "openclaw-stub-0.1.0"


# ---------- Endpoints ----------
@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "openclaw",
        "stub_mode": STUB_MODE,
        "tools_loaded": len(TOOL_CATALOG),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/tools")
def tools(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    return {"tools": TOOL_CATALOG}


@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest, authorization: str | None = Header(default=None)) -> ExecuteResponse:
    require_token(authorization)
    started = time.time()
    log.info("execute job_id=%s step_id=%s tool=%s", req.job_id, req.step_id, req.tool)

    known_tools = {t["name"] for t in TOOL_CATALOG}
    if req.tool not in known_tools:
        elapsed = int((time.time() - started) * 1000)
        return ExecuteResponse(
            job_id=req.job_id,
            step_id=req.step_id,
            status="error",
            error=ExecuteError(
                code="UNKNOWN_TOOL",
                message=f"Tool '{req.tool}' not in catalog",
                retryable=False,
            ),
            execution_time_ms=elapsed,
        )

    if not STUB_MODE:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "live mode not wired yet")

    # Stub: return canned outputs per tool name
    if req.tool == "web.fetch":
        output = {
            "status_code": 200,
            "headers": {"content-type": "text/html"},
            "body_preview": "<html>stub fetch ok</html>",
            "url": req.input.get("url"),
        }
    elif req.tool == "browser.action":
        output = {
            "actions_completed": len(req.input.get("actions", [])),
            "extracted": [["row1", "value1"], ["row2", "value2"]],
        }
    elif req.tool == "shell.run":
        output = {
            "stdout": "stub stdout output",
            "stderr": "",
            "exit_code": 0,
        }
    elif req.tool == "api.call":
        output = {
            "status_code": 200,
            "json": {"ok": True, "echo": req.input},
        }
    else:
        output = {"note": "stub output"}

    elapsed = int((time.time() - started) * 1000)
    return ExecuteResponse(
        job_id=req.job_id,
        step_id=req.step_id,
        status="success",
        output=output,
        artifacts=[
            {
                "uri": f"s3://artifacts/{req.job_id}/{req.step_id}.json",
                "kind": "json",
            }
        ],
        execution_time_ms=elapsed,
    )
