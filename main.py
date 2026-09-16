"""
GreenQueue backend — FastAPI app.

Endpoints:
  GET  /snapshot   -> GreenQueueSnapshot (the frontend's one and only contract)
  POST /jobs       -> submit a new job, returns the created Job
  GET  /health     -> plain health check for uptime monitors / hosting platform

A background asyncio task re-runs the scheduling pass every few seconds
so the grid/jobs keep evolving even with no incoming requests — matching
"the environment stays alive" requirement from the frontend brief.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import state
from app.carbon import build_trend, clean_window_eta_minutes, current_carbon_intensity
from app.internal import InternalJob
from app.models import GreenQueueSnapshot, GridState, ImpactMetrics, Job, JobCreateRequest
from app.scheduler import run_scheduling_pass

SCHEDULING_INTERVAL_SECONDS = 5


async def _background_scheduling_loop() -> None:
    while True:
        try:
            run_scheduling_pass(state.jobs, state.nodes, state.impact, state.threshold)
        except Exception as exc:  # noqa: BLE001 — never let the loop die from one bad tick
            print(f"[scheduler loop] error: {exc}")
        await asyncio.sleep(SCHEDULING_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_background_scheduling_loop())
    yield
    task.cancel()


app = FastAPI(title="GreenQueue API", lifespan=lifespan)

# Configure via env var so the deployed frontend origin isn't hardcoded.
# Comma-separated list, e.g. "https://greenqueue.vercel.app,http://localhost:5173"
_origins_env = os.environ.get("CORS_ORIGINS", "https://greenqueue.vercel.app,http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/snapshot", response_model=GreenQueueSnapshot)
def get_snapshot() -> GreenQueueSnapshot:
    now = datetime.utcnow()
    carbon_now = current_carbon_intensity(now)

    grid = GridState(
        carbonIntensity=carbon_now,
        threshold=state.threshold,
        cleanWindowEta=clean_window_eta_minutes(now, state.threshold),
        estimatedCost=round((carbon_now / 420) * 0.18, 3),
        trend=build_trend(now, state.threshold),
    )

    impact = ImpactMetrics(
        carbonAvoidedTons=round(state.impact.carbon_avoided_grams / 1_000_000, 3),
        costSavedUsd=round(state.impact.cost_saved_usd, 2),
        jobsOptimized=state.impact.jobs_optimized,
        flexibleComputeHours=round(state.impact.flexible_minutes / 60, 1),
    )

    return GreenQueueSnapshot(
        jobs=[j.to_public_job() for j in state.jobs],
        grid=grid,
        impact=impact,
        demoMode=False,
    )


@app.post("/jobs", response_model=Job)
def create_job(payload: JobCreateRequest) -> Job:
    if payload.durationMin <= 0 or payload.durationMin > 240:
        raise HTTPException(status_code=400, detail="durationMin must be between 1 and 240")

    now = datetime.utcnow()
    carbon_now = current_carbon_intensity(now)

    job = InternalJob(
        id=str(uuid.uuid4())[:8],
        name=payload.name or f"{payload.type}-{len(state.jobs) + 1}",
        type=payload.type,
        urgency=payload.urgency,
        status="waiting",
        duration_min=payload.durationMin,
        submitted_at=now,
        slot=len(state.jobs) % 8,
        carbon_baseline=carbon_now,
        reason="Just submitted — awaiting scheduling pass.",
    )
    state.jobs.insert(0, job)

    # Evaluate immediately so an urgent job doesn't wait for the next
    # background tick to visibly dispatch.
    run_scheduling_pass(state.jobs, state.nodes, state.impact, state.threshold)

    return job.to_public_job()
