"""Alerts and metrics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["Alerts"])


@router.get("/alerts")
async def list_alerts(
    request: Request,
    severity: str | None = Query(None, description="Filter by severity (critical, warning, info)"),
    service: str | None = Query(None, description="Filter by affected_service"),
) -> dict:
    """Return root-cause analysis alerts."""
    data: list[dict] = getattr(request.app.state, "alerts", [])

    if severity:
        data = [a for a in data if a.get("severity", "").lower() == severity.lower()]
    if service:
        data = [
            a for a in data
            if a.get("affected_service") == service or a.get("probable_root_cause") == service
        ]

    return {
        "total": len(data),
        "alerts": data,
    }


@router.get("/alerts/{alert_id}")
async def get_alert(alert_id: str, request: Request) -> dict:
    """Return a single alert by its ID."""
    data: list[dict] = getattr(request.app.state, "alerts", [])
    for alert in data:
        if alert.get("alert_id") == alert_id:
            return alert
    raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")


@router.get("/metrics")
async def get_metrics(request: Request) -> dict:
    """Return pipeline evaluation metrics (precision, recall, F1, totals)."""
    metrics = getattr(request.app.state, "metrics", {})
    if not metrics:
        raise HTTPException(status_code=404, detail="No metrics available. Run the pipeline first.")
    return metrics
