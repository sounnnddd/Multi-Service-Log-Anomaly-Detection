"""Shared enums aligned with OpenTelemetry conventions."""

from enum import Enum


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


class AnomalyType(str, Enum):
    LATENCY_SPIKE = "latency_spike"
    ERROR_STORM = "error_storm"
    TRAFFIC_DROP = "traffic_drop"
    MIXED = "mixed"


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class Environment(str, Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


# OpenTelemetry-aligned severity number mapping
SEVERITY_MAP = {
    LogLevel.DEBUG: 5,
    LogLevel.INFO: 9,
    LogLevel.WARN: 13,
    LogLevel.ERROR: 17,
    LogLevel.FATAL: 21,
}
