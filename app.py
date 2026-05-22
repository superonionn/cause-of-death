"""FastAPI web server for Cause of Death."""

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

import analyzer

app = FastAPI(title="Cause of Death")

TEMPLATE_DIR = Path(__file__).parent / "templates"


@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/analyze")
async def api_analyze(log: str, vod: str | None = None, channel: str | None = None, delay: int = 0):
    start = time.monotonic()
    try:
        result = analyzer.analyze(log, vod_url=vod, channel=channel, stream_delay_s=delay)
        result["elapsed_seconds"] = round(time.monotonic() - start, 1)
        return result
    except Exception as e:
        return {"error": str(e)}
