"""
GreenQueue backend — scheduling engine.

The real workflow: submit -> priority check -> carbon check ->
dispatch or wait -> assign cluster node -> run -> complete -> release
node -> accumulate impact. This is the one place that decision actually
happens; app/main.py and app/state.py only call into this.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.carbon import THRESHOLD_DEFAULT, clean_window_eta_minutes, current_carbon_intensity
from app.internal import DEMO_DURATION_SECONDS_PER_SIM_MINUTE, MAX_DELAY_MINUTES, ClusterNode, ImpactTotals, InternalJob


def evaluate_job(job: InternalJob, current_carbon: float, threshold: float) -> tuple[bool, str, str | None]:
    """Returns (should_dispatch, reason, recommended_window)."""
    if job.urgency == "urgent":
        return True, "Urgent priority — dispatched immediately, no carbon check applied.", None

    waited_min = (datetime.utcnow() - job.submitted_at).total_seconds() / 60

    if current_carbon <= threshold:
        return True, (
            f"Grid carbon {current_carbon:.0f} gCO2/kWh is at/below the "
            f"{threshold:.0f} threshold — dispatching now."
        ), None

    if waited_min >= MAX_DELAY_MINUTES:
        return True, (
            f"Max wait of {MAX_DELAY_MINUTES} min reached — force-dispatched by the safety valve."
        ), None

    eta = clean_window_eta_minutes(threshold=threshold)
    window_label = None
    if eta is not None:
        window_label = (datetime.utcnow() + timedelta(minutes=eta)).strftime("%H:%M")

    return False, (
        f"Grid carbon {current_carbon:.0f} gCO2/kWh is above the {threshold:.0f} "
        f"threshold — waiting for a cleaner window."
    ), window_label


def find_available_node(nodes: list[ClusterNode]) -> ClusterNode | None:
    candidates = [n for n in nodes if n.status != "offline" and len(n.job_ids) < n.max_capacity]
    if not candidates:
        return None
    candidates.sort(key=lambda n: len(n.job_ids))
    return candidates[0]


def assign_job_to_node(job: InternalJob, nodes: list[ClusterNode]) -> ClusterNode | None:
    node = find_available_node(nodes)
    if node is None:
        return None
    node.job_ids.append(job.id)
    node.status = "busy"
    job.assigned_node = node.node_id
    return node


def release_job_from_node(job: InternalJob, nodes: list[ClusterNode]) -> None:
    if not job.assigned_node:
        return
    for node in nodes:
        if node.node_id == job.assigned_node and job.id in node.job_ids:
            node.job_ids.remove(job.id)
            node.status = "idle" if not node.job_ids else "busy"
            break


def run_scheduling_pass(
    jobs: list[InternalJob],
    nodes: list[ClusterNode],
    impact: ImpactTotals,
    threshold: float = THRESHOLD_DEFAULT,
) -> None:
    now = datetime.utcnow()
    current_carbon = current_carbon_intensity(now)

    # 1. Completion pass — advance running jobs whose demo-scaled duration elapsed.
    for job in jobs:
        if job.status == "running" and job.started_at:
            elapsed_sec = (now - job.started_at).total_seconds()
            demo_duration_sec = job.duration_min * DEMO_DURATION_SECONDS_PER_SIM_MINUTE
            if elapsed_sec >= demo_duration_sec:
                job.status = "completed"
                job.completed_at = now
                job.reason = "Completed on the compute cluster."
                release_job_from_node(job, nodes)

                if job.urgency == "flexible" and job.carbon_baseline is not None and job.carbon_at_run is not None:
                    saved = max(0.0, job.carbon_baseline - job.carbon_at_run)
                    if saved > 0:
                        # grams CO2 avoided ~ saved gCO2/kWh * assumed 0.5 kWh per job-hour * duration
                        impact.carbon_avoided_grams += saved * 0.5 * (job.duration_min / 60)
                        impact.cost_saved_usd += saved * 0.0004 * (job.duration_min / 60)
                        impact.jobs_optimized += 1
                        impact.flexible_minutes += job.duration_min

    # 2. Dispatch pass — evaluate every waiting/scheduled job.
    for job in jobs:
        if job.status not in ("waiting", "scheduled"):
            continue

        should_dispatch, reason, window = evaluate_job(job, current_carbon, threshold)
        job.reason = reason
        job.recommended_window = window

        if not should_dispatch:
            job.status = "waiting"
            continue

        node = assign_job_to_node(job, nodes)
        if node is None:
            job.status = "waiting"
            job.reason = reason + " Cluster is at capacity — queued until a node frees up."
            continue

        job.status = "running"
        job.started_at = now
        job.carbon_at_run = current_carbon
