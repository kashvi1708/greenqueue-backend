"""
GreenQueue backend — application state.

In-memory, single-process. This is intentional for a hackathon demo —
see README.md for what would need to change for multi-instance/production
use (a real datastore instead of a Python list in a module global).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.carbon import THRESHOLD_DEFAULT, current_carbon_intensity
from app.internal import ClusterNode, ImpactTotals, InternalJob

jobs: list[InternalJob] = []
nodes: list[ClusterNode] = [ClusterNode(node_id=f"node-{i:02d}") for i in range(1, 7)]
impact = ImpactTotals()
threshold: float = THRESHOLD_DEFAULT


def _seed_jobs() -> None:
    """A few starting jobs so the dashboard isn't empty the moment the
    server boots — mirrors the seeding approach used in the Streamlit
    prototype's mock_data.generate_initial_state()."""
    now = datetime.utcnow()
    carbon_now = current_carbon_intensity(now)

    seed_specs = [
        ("infer-204", "infer", "urgent", "running", 10, 2),
        ("embed-042", "embed", "flexible", "waiting", 15, 8),
        ("train-091", "train", "flexible", "waiting", 30, 14),
        ("batch-118", "batch", "flexible", "completed", 20, 90),
    ]

    for i, (name, jtype, urgency, status, duration, minutes_ago) in enumerate(seed_specs):
        submitted_at = now - timedelta(minutes=minutes_ago)
        job = InternalJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            type=jtype,  # type: ignore[arg-type]
            urgency=urgency,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            duration_min=duration,
            submitted_at=submitted_at,
            slot=i,
        )
        if status in ("running", "completed"):
            job.carbon_at_run = carbon_now - 40
            job.carbon_baseline = carbon_now + 60
            job.reason = "Dispatched during an earlier pass."
            if status == "running":
                # Just started, so it stays visibly "running" for a
                # realistic while after boot rather than completing
                # almost instantly on the first scheduling tick.
                job.started_at = now - timedelta(seconds=3)
            else:
                job.started_at = submitted_at + timedelta(minutes=1)
        if status == "completed":
            job.completed_at = job.started_at + timedelta(minutes=duration)
            impact.jobs_optimized += 1
            impact.carbon_avoided_grams += 60 * 0.5 * (duration / 60)
            impact.cost_saved_usd += 60 * 0.0004 * (duration / 60)
            impact.flexible_minutes += duration
        if status == "waiting":
            job.carbon_baseline = carbon_now
            job.reason = "Waiting for a cleaner grid window."
        if status == "running":
            for node in nodes:
                if len(node.job_ids) < node.max_capacity:
                    node.job_ids.append(job.id)
                    node.status = "busy"
                    job.assigned_node = node.node_id
                    break
        jobs.append(job)


_seed_jobs()
