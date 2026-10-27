#!/usr/bin/env python3
"""
api/main.py
FastAPI application for the Job Radar service.
"""

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent

from .models import DescriptionStats, JobResult, ScrapeResponse
from .scraper import run_scrape

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

CACHE_DIR = ROOT / "cache"
CACHE_FILE = CACHE_DIR / "jobs_cache.json"

app = FastAPI(title="Job Radar", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:3000", "http://localhost:8080"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Serve the dashboard from the API origin so existing endpoints need no CORS changes.
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="dashboard")


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Cache directory: %s", CACHE_DIR)


# ── Cache helpers ─────────────────────────────────────────────────────────────
def write_cache(response: ScrapeResponse) -> None:
    CACHE_FILE.write_text(response.model_dump_json(), encoding="utf-8")


def read_cache() -> ScrapeResponse:
    if not CACHE_FILE.exists():
        raise HTTPException(status_code=404, detail="No cached results yet. Call GET /jobs first.")
    raw = CACHE_FILE.read_text(encoding="utf-8")
    return ScrapeResponse.model_validate_json(raw)


# ── Models ────────────────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    timestamp: str


class StatsResponse(BaseModel):
    total_jobs: int
    by_profile: dict[str, int]
    by_source: dict[str, int]
    watchlist_count: int
    scraped_at: str
    description_stats: DescriptionStats


# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc).isoformat())


@app.get("/jobs", response_model=ScrapeResponse)
def jobs():
    log.info("Starting scrape...")
    result = run_scrape()
    write_cache(result)
    log.info("Scrape done — %d jobs cached.", result.total_after_filter)
    return result


@app.get("/jobs/cached", response_model=ScrapeResponse)
def jobs_cached():
    return read_cache()


@app.get("/jobs/stats", response_model=StatsResponse)
def jobs_stats():
    cached = read_cache()
    jobs: list[JobResult] = cached.jobs
    return StatsResponse(
        total_jobs=len(jobs),
        by_profile=dict(Counter(j.profile for j in jobs)),
        by_source=dict(Counter(j.source for j in jobs)),
        watchlist_count=sum(1 for j in jobs if j.in_watchlist),
        scraped_at=cached.scraped_at.isoformat(),
        description_stats=cached.description_stats,
    )


def main() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="0.0.0.0", port=8001, reload=False)


if __name__ == "__main__":
    main()

