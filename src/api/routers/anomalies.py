"""Anomaly events endpoint — filterable by service, confidence, anomaly status."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["Anomalies"])


@router.get("/anomalies")
async def list_anomalies(
    request: Request,
    service: str | None = Query(None, description="Filter by service_name"),
    anomaly_only: bool = Query(True, description="Return only flagged anomalies (is_anomaly=true)"),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0, description="Minimum confidence threshold"),
) -> dict:
    """Return anomaly events scored by the Isolation Forest detector."""
    data: list[dict] = getattr(request.app.state, "anomalies", [])

    if service:
        data = [a for a in data if a.get("service_name") == service]
    if anomaly_only:
        data = [a for a in data if a.get("is_anomaly")]
    if min_confidence is not None:
        data = [a for a in data if (a.get("confidence") or 0) >= min_confidence]

    return {
        "total": len(data),
        "anomalies": data,
    }


@router.get("/anomalies/summary")
async def anomaly_summary(request: Request) -> dict:
    """Return aggregated anomaly statistics."""
    data: list[dict] = getattr(request.app.state, "anomalies", [])

    total_windows = len(data)
    anomaly_count = sum(1 for a in data if a.get("is_anomaly"))

    # Per-service breakdown
    per_service: dict[str, dict] = {}
    for a in data:
        svc = a.get("service_name", "unknown")
        if svc not in per_service:
            per_service[svc] = {"total_windows": 0, "anomaly_count": 0, "avg_confidence": 0.0}
        per_service[svc]["total_windows"] += 1
        if a.get("is_anomaly"):
            per_service[svc]["anomaly_count"] += 1
            per_service[svc]["avg_confidence"] += a.get("confidence", 0)

    for svc, stats in per_service.items():
        if stats["anomaly_count"] > 0:
            stats["avg_confidence"] = round(stats["avg_confidence"] / stats["anomaly_count"], 4)

    return {
        "total_windows": total_windows,
        "anomaly_count": anomaly_count,
        "normal_count": total_windows - anomaly_count,
        "per_service": per_service,
    }
