"""FeatureWindow contract — one row per (service, time_window)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .enums import AnomalyType


class FeatureWindow(BaseModel):
    """Aggregated features for a single service over one time window."""

    window_start: datetime
    window_end: datetime
    service_name: str

    # Counts
    total_requests: int
    error_count: int
    warn_count: int
    info_count: int
    client_error_count: int
    timeout_count: int
    db_failure_count: int
    auth_failure_count: int
    unique_event_types: int

    # Latency
    latency_mean: float
    latency_p50: float
    latency_p95: float
    latency_p99: float
    latency_std: float

    # Rates
    error_rate: float
    requests_per_second: float

    # Status code distribution
    status_2xx_ratio: float
    status_4xx_ratio: float
    status_5xx_ratio: float

    # Ground truth (for evaluation only — never used as features)
    has_anomaly: bool = False
    dominant_anomaly_type: AnomalyType | None = None
