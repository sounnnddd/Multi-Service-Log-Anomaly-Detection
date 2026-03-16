"""AnomalyEvent contract — detector output."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .enums import AnomalyType


class AnomalyEvent(BaseModel):
    """Output of the anomaly detector for a single feature window."""

    window_start: datetime
    window_end: datetime
    service_name: str
    anomaly_score: float
    is_anomaly: bool
    confidence: float
    feature_snapshot: dict
    ground_truth_anomaly: bool = False
    ground_truth_type: AnomalyType | None = None
