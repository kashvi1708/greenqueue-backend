"""
GreenQueue backend — data models.

IMPORTANT: field names here are deliberately camelCase (not the usual
Python snake_case) because they must serialize to JSON that exactly
matches src/types/greenqueue.ts on the frontend — the frontend does a
raw `payload as GreenQueueSnapshot` cast with no case-conversion layer.
This is a deliberate cross-language contract decision, not an oversight.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

Urgency = Literal["urgent", "flexible"]
JobStatus = Literal["waiting", "scheduled", "running", "completed"]
JobType = Literal["embed", "train", "infer", "batch"]


class SchedulingDecision(BaseModel):
    runNow: bool
    reason: str
    expectedCarbon: float
    expectedCost: float
    recommendedWindow: Optional[str] = None


class Job(BaseModel):
    id: str
    type: JobType
    urgency: Urgency
    status: JobStatus
    carbonIntensity: float
    estimatedCost: float
    decision: SchedulingDecision
    submittedAt: int  # epoch milliseconds, matches JS `Date.now()`
    slot: int

    # --- internal-only fields, not part of the frontend contract ---
    # (excluded from the response model; see internal.py for the
    #  full internal job record that carries these)


class GridTrendPoint(BaseModel):
    t: int  # minutes from now; negative = past, positive = forecast
    carbonIntensity: float


class GridState(BaseModel):
    carbonIntensity: float
    threshold: float
    cleanWindowEta: Optional[int] = None
    estimatedCost: float
    trend: list[GridTrendPoint]


class ImpactMetrics(BaseModel):
    carbonAvoidedTons: float
    costSavedUsd: float
    jobsOptimized: int
    flexibleComputeHours: float


class GreenQueueSnapshot(BaseModel):
    jobs: list[Job]
    grid: GridState
    impact: ImpactMetrics
    demoMode: bool


class JobCreateRequest(BaseModel):
    name: Optional[str] = None
    type: JobType = "batch"
    urgency: Urgency = "flexible"
    durationMin: int = 15
