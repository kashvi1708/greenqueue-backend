"""
GreenQueue backend — carbon intensity.

This is a SIMULATION for the hackathon demo, structured so swapping in a
real grid API (electricityMap, WattTime, etc.) later means rewriting only
this file — nothing else references how carbon data is produced.

Deliberately stateless: every call computes from the current wall-clock
time, so multiple server instances (or a restart) never disagree with
each other the way a stored-and-drifted value could.
"""

from __future__ import annotations

import math
import random
from datetime import datetime

from app.models import GridTrendPoint

THRESHOLD_DEFAULT = 350.0


def _hour_fraction(dt: datetime) -> float:
    return dt.hour + dt.minute / 60.0


def _base_curve(hour: float) -> float:
    """A believable daily carbon-intensity curve: dirtier in the
    evening peak (~19:00), cleaner overnight/early morning (~04:00)."""
    return 350 + 170 * math.sin((hour - 13) / 24 * 2 * math.pi)


def current_carbon_intensity(now: datetime | None = None) -> float:
    now = now or datetime.utcnow()
    hour = _hour_fraction(now)
    # Deterministic-but-varying noise seeded by the minute, so it doesn't
    # jump erratically between requests a few seconds apart.
    rng = random.Random(int(now.timestamp() // 30))
    noise = rng.uniform(-18, 18)
    return round(max(90.0, _base_curve(hour) + noise), 1)


def build_trend(now: datetime | None = None, threshold: float = THRESHOLD_DEFAULT) -> list[GridTrendPoint]:
    now = now or datetime.utcnow()
    points: list[GridTrendPoint] = []
    for t in range(-60, 65, 10):
        sample_time = now.timestamp() + t * 60
        sample_dt = datetime.utcfromtimestamp(sample_time)
        hour = _hour_fraction(sample_dt)
        rng = random.Random(int(sample_time // 30))
        noise = rng.uniform(-15, 15) if t != 0 else 0
        value = max(90.0, _base_curve(hour) + noise)
        points.append(GridTrendPoint(t=t, carbonIntensity=round(value, 1)))
    return points


def clean_window_eta_minutes(now: datetime | None = None, threshold: float = THRESHOLD_DEFAULT) -> int | None:
    """Minutes until the trend forecast next dips at/below threshold, or
    None if the grid is already clean right now."""
    now = now or datetime.utcnow()
    if current_carbon_intensity(now) <= threshold:
        return None
    for t in range(10, 121, 10):
        sample_time = now.timestamp() + t * 60
        sample_dt = datetime.utcfromtimestamp(sample_time)
        hour = _hour_fraction(sample_dt)
        rng = random.Random(int(sample_time // 30))
        noise = rng.uniform(-15, 15)
        value = max(90.0, _base_curve(hour) + noise)
        if value <= threshold:
            return t
    return None
