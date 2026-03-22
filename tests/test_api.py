"""API endpoint tests using FastAPI TestClient.

No pipeline run needed — tests inject fixture data into app.state.
"""

from __future__ import annotations

import pytest
import pandas as pd
from fastapi.testclient import TestClient

from src.api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
SAMPLE_ANOMALY = {
    "window_start": "2026-03-16T20:00:00+00:00",
    "window_end": "2026-03-16T20:01:00+00:00",
    "service_name": "db-service",
    "anomaly_score": -0.12,
    "is_anomaly": True,
    "confidence": 0.85,
    "feature_snapshot": {"error_rate": 0.45, "latency_p95": 320.5},
    "ground_truth_anomaly": True,
    "ground_truth_type": "error_storm",
}

SAMPLE_NORMAL = {
    "window_start": "2026-03-16T20:01:00+00:00",
    "window_end": "2026-03-16T20:02:00+00:00",
    "service_name": "auth-service",
    "anomaly_score": 0.35,
    "is_anomaly": False,
    "confidence": 0.12,
    "feature_snapshot": {"error_rate": 0.01},
    "ground_truth_anomaly": False,
    "ground_truth_type": None,
}

SAMPLE_ALERT = {
    "alert_id": "alert-abc12345",
    "triggered_at": "2026-03-16T20:00:00+00:00",
    "severity": "critical",
    "affected_service": "payment-service",
    "probable_root_cause": "db-service",
    "anomaly_type": "error_storm",
    "reason": "Anomaly in payment-service likely caused by upstream failure in db-service",
    "related_services": ["inventory-service"],
    "evidence": {"error_rate": 0.45},
}

SAMPLE_METRICS = {
    "meta": {
        "total_events": 306360,
        "feature_windows": 366,
        "normal_windows": 236,
        "anomalies_detected": 130,
        "alerts_generated": 12,
    },
    "evaluation": {
        "true_positives": 35,
        "false_positives": 9,
        "false_negatives": 1,
        "true_negatives": 321,
        "precision": 0.7955,
        "recall": 0.9722,
        "f1_score": 0.875,
        "total_windows": 366,
    },
    "model": {
        "type": "IsolationForest",
        "contamination": 0.1,
    },
}

SAMPLE_EVENT = {
    "trace_id": "abc123",
    "span_id": "span-001",
    "timestamp": "2026-03-16T20:00:01+00:00",
    "service_name": "db-service",
    "log_level": "ERROR",
    "status_code": 500,
    "latency_ms": 320.5,
    "event_type": "upstream_failure",
    "message": "failed",
}

SAMPLE_FEATURE_ROW = {
    "window_start": "2026-03-16T20:00:00+00:00",
    "window_end": "2026-03-16T20:01:00+00:00",
    "service_name": "db-service",
    "total_requests": 120,
    "error_count": 54,
    "warn_count": 10,
    "info_count": 56,
    "client_error_count": 3,
    "timeout_count": 5,
    "db_failure_count": 40,
    "auth_failure_count": 0,
    "unique_event_types": 6,
    "latency_mean": 180.0,
    "latency_p50": 150.0,
    "latency_p95": 320.5,
    "latency_p99": 400.0,
    "latency_std": 90.0,
    "error_rate": 0.45,
    "requests_per_second": 2.0,
    "status_2xx_ratio": 0.50,
    "status_4xx_ratio": 0.025,
    "status_5xx_ratio": 0.45,
    "has_anomaly": True,
    "dominant_anomaly_type": "error_storm",
}


@pytest.fixture(autouse=True)
def _inject_fixture_data():
    """Inject test data into app.state before each test."""
    app.state.anomalies = [SAMPLE_ANOMALY, SAMPLE_NORMAL]
    app.state.alerts = [SAMPLE_ALERT]
    app.state.metrics = SAMPLE_METRICS
    app.state.events = [SAMPLE_EVENT]
    app.state.features_df = pd.DataFrame([SAMPLE_FEATURE_ROW])
    app.state.data_loaded = True
    yield


client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class TestHealth:
    def test_health_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["data_loaded"] is True


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class TestEvents:
    def test_list_events(self):
        r = client.get("/events")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["events"]) == 1

    def test_filter_by_service(self):
        r = client.get("/events", params={"service": "db-service"})
        assert r.json()["total"] == 1

        r = client.get("/events", params={"service": "nonexistent"})
        assert r.json()["total"] == 0

    def test_filter_by_log_level(self):
        r = client.get("/events", params={"log_level": "ERROR"})
        assert r.json()["total"] == 1

        r = client.get("/events", params={"log_level": "INFO"})
        assert r.json()["total"] == 0

    def test_pagination(self):
        r = client.get("/events", params={"limit": 1, "offset": 0})
        assert r.json()["count"] == 1

        r = client.get("/events", params={"limit": 1, "offset": 10})
        assert r.json()["count"] == 0


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
class TestFeatures:
    def test_list_features(self):
        r = client.get("/features")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_filter_by_service(self):
        r = client.get("/features", params={"service": "db-service"})
        assert r.json()["total"] == 1

        r = client.get("/features", params={"service": "auth-service"})
        assert r.json()["total"] == 0

    def test_anomaly_only(self):
        r = client.get("/features", params={"anomaly_only": "true"})
        assert r.json()["total"] == 1


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------
class TestAnomalies:
    def test_list_anomalies_default_anomaly_only(self):
        r = client.get("/anomalies")
        assert r.status_code == 200
        body = r.json()
        # default anomaly_only=true → only the anomalous one
        assert body["total"] == 1
        assert body["anomalies"][0]["service_name"] == "db-service"

    def test_list_all_anomalies(self):
        r = client.get("/anomalies", params={"anomaly_only": "false"})
        assert r.json()["total"] == 2

    def test_filter_by_service(self):
        r = client.get("/anomalies", params={"service": "db-service", "anomaly_only": "false"})
        assert r.json()["total"] == 1

    def test_filter_by_confidence(self):
        r = client.get("/anomalies", params={"min_confidence": 0.5, "anomaly_only": "false"})
        assert r.json()["total"] == 1  # only the 0.85 one

    def test_summary(self):
        r = client.get("/anomalies/summary")
        assert r.status_code == 200
        body = r.json()
        assert body["total_windows"] == 2
        assert body["anomaly_count"] == 1
        assert "db-service" in body["per_service"]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
class TestAlerts:
    def test_list_alerts(self):
        r = client.get("/alerts")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_filter_by_severity(self):
        r = client.get("/alerts", params={"severity": "critical"})
        assert r.json()["total"] == 1

        r = client.get("/alerts", params={"severity": "info"})
        assert r.json()["total"] == 0

    def test_filter_by_service(self):
        r = client.get("/alerts", params={"service": "db-service"})
        assert r.json()["total"] == 1  # db-service is the root cause

    def test_get_alert_by_id(self):
        r = client.get("/alerts/alert-abc12345")
        assert r.status_code == 200
        assert r.json()["alert_id"] == "alert-abc12345"

    def test_get_alert_not_found(self):
        r = client.get("/alerts/nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
class TestMetrics:
    def test_get_metrics(self):
        r = client.get("/metrics")
        assert r.status_code == 200
        body = r.json()
        assert "evaluation" in body
        assert body["evaluation"]["precision"] == 0.7955

    def test_metrics_not_available(self):
        app.state.metrics = {}
        r = client.get("/metrics")
        assert r.status_code == 404
