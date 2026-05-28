"""FastAPI web server for Cause of Death."""

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import analyzer
import session

app = FastAPI(title="Cause of Death")

TEMPLATE_DIR = Path(__file__).parent / "templates"


class SessionCreate(BaseModel):
    log: str
    vod: str | None = None
    channel: str | None = None
    delay: int = 0


@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")


# ── Session-based endpoints (live mode) ─────────────────────────────────────

@app.post("/api/session")
async def create_session(body: SessionCreate):
    start = time.monotonic()
    try:
        result = session.create_session(
            body.log, vod_url=body.vod, channel=body.channel,
            stream_delay_s=body.delay,
        )
        result["elapsed_seconds"] = round(time.monotonic() - start, 1)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/session/{session_id}/refresh")
async def refresh(session_id: str):
    start = time.monotonic()
    try:
        result = session.refresh_session(session_id)
        result["elapsed_seconds"] = round(time.monotonic() - start, 1)
        return result
    except KeyError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    try:
        return session.get_session(session_id)
    except KeyError as e:
        return {"error": str(e)}


# ── Legacy one-shot endpoint (backward compat) ─────────────────────────────

@app.get("/api/analyze")
async def api_analyze(log: str, vod: str | None = None, channel: str | None = None, delay: int = 0):
    start = time.monotonic()
    try:
        result = analyzer.analyze(log, vod_url=vod, channel=channel, stream_delay_s=delay)
        result["elapsed_seconds"] = round(time.monotonic() - start, 1)
        return result
    except Exception as e:
        return {"error": str(e)}
