"""Detection flags: `new` and `spike` (spec 5.6 defaults; no suppression/budget in Stage 1)."""

from datetime import datetime, timedelta

from app.config import Settings


def floor_hour(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def spike_periods(anchor: datetime, lookback_hours: int) -> tuple[datetime, datetime, datetime]:
    """(current_start, baseline_start, baseline_end).

    current = the last 60 minutes up to `anchor` (the newest record of the run window).
    baseline = the `lookback_hours` whole hours before that.
    """
    current_start = anchor - timedelta(minutes=60)
    baseline_end = floor_hour(current_start)
    return current_start, baseline_end - timedelta(hours=lookback_hours), baseline_end


def is_spike(current: int, baseline_total: int, s: Settings) -> bool:
    baseline_avg = baseline_total / s.spike_lookback_hours
    return current > max(s.spike_multiplier * baseline_avg, s.spike_min_count)
