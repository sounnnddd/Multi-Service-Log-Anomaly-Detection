"""Normalised log events endpoint — paginated, filterable."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["Events"])


@router.get("/events")
async def list_events(
    request: Request,
    service: str | None = Query(None, description="Filter by service_name"),
    log_level: str | None = Query(None, description="Filter by log_level (DEBUG, INFO, WARN, ERROR, FATAL)"),
    limit: int = Query(100, ge=1, le=1000, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
) -> dict:
    """Return paginated normalised log events with optional filters."""
    data: list[dict] = getattr(request.app.state, "events", [])

    # Apply filters
    if service:
        data = [e for e in data if e.get("service_name") == service]
    if log_level:
        data = [e for e in data if e.get("log_level", "").upper() == log_level.upper()]

    total = len(data)
    page = data[offset : offset + limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "count": len(page),
        "events": page,
    }
