"""Alert contract — RCA engine output."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .enums import AlertSeverity, AnomalyType


class Alert(BaseModel):
    """Root-cause analysis alert produced by the RCA engine."""

    alert_id: str
    triggered_at: datetime
    severity: AlertSeverity
    affected_service: str
    probable_root_cause: str
    anomaly_type: AnomalyType | None = None
    reason: str
    related_services: list[str] = []
    evidence: dict = {}
