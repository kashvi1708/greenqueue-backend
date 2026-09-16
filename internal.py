"""
GreenQueue backend — internal state records.

Deliberately separate from app/models.py: the frontend's `Job` type is
the PUBLIC contract, but the scheduler needs more bookkeeping (when it
started running, which node it's on, its raw priority) than that
contract exposes. `to_public_job()` is the one place that translates
between them, so the contract never silently grows internal fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.models import Job, JobStatus, JobType, SchedulingDecision, Urgency

MAX_DELAY_MINUTES = 120
DEMO_DURATION_SECONDS_PER_SIM_MINUTE = 2  # compress sim-minutes into real seconds for a live demo


@dataclass
class InternalJob:
    id: str
    name: str
    type: JobType
    urgency: Urgency
    status: JobStatus  # "waiting" | "scheduled" | "running" | "completed"
    duration_min: int
    submitted_at: datetime
    slot: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    carbon_at_run: Optional[float] = None
    carbon_baseline: Optional[float] = None
    reason: str = "Submitted — awaiting scheduling pass."
    recommended_window: Optional[str] = None
    assigned_node: Optional[str] = None

    def to_public_job(self) -> Job:
        return Job(
            id=self.id,
            type=self.type,
            urgency=self.urgency,
            status=self.status,
            carbonIntensity=self.carbon_at_run if self.carbon_at_run is not None else (self.carbon_baseline or 0.0),
            estimatedCost=round(self.duration_min / 60 * 0.7, 2),
            decision=SchedulingDecision(
                runNow=self.status in ("running", "completed"),
                reason=self.reason,
                expectedCarbon=self.carbon_at_run if self.carbon_at_run is not None else (self.carbon_baseline or 0.0),
                expectedCost=round(self.duration_min / 60 * 0.7, 2),
                recommendedWindow=self.recommended_window,
            ),
            submittedAt=int(self.submitted_at.timestamp() * 1000),
            slot=self.slot,
        )


@dataclass
class ClusterNode:
    node_id: str
    job_ids: list[str] = field(default_factory=list)
    max_capacity: int = 3
    status: str = "idle"


@dataclass
class ImpactTotals:
    carbon_avoided_grams: float = 0.0
    cost_saved_usd: float = 0.0
    jobs_optimized: int = 0
    flexible_minutes: float = 0.0
