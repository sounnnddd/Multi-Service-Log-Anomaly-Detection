"""RawLogEvent and NormalizedLogEvent contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import AnomalyType, Environment, HttpMethod, LogLevel


class RawLogEvent(BaseModel):
    """Schema for raw log events produced by the generator."""

    trace_id: str
    span_id: str
    timestamp_iso: str
    timestamp_unix: float
    service_name: str
    host_id: str
    environment: str = "production"
    endpoint: str
    method: str
    log_level: str
    severity_number: int = 0
    status_code: int
    latency_ms: float
    request_id: str
    dependency: str | None = None
    event_type: str
    message: str
    is_synthetic_anomaly: bool = False
    anomaly_type: str | None = None


class NormalizedLogEvent(BaseModel):
    """Schema for validated, typed log events consumed by the feature extractor."""

    trace_id: str
    span_id: str
    timestamp: datetime
    timestamp_unix: float
    service_name: str
    host_id: str
    environment: Environment = Environment.PRODUCTION
    endpoint: str
    method: HttpMethod
    log_level: LogLevel
    severity_number: int
    status_code: int = Field(ge=100, le=599)
    latency_ms: float = Field(ge=0)
    request_id: str
    dependency: str | None = None
    event_type: str
    message: str
    is_synthetic_anomaly: bool = False
    anomaly_type: AnomalyType | None = None
