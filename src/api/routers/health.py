"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(request: Request) -> dict:
    """Return API health status and whether pipeline data is loaded."""
    return {
        "status": "ok",
        "data_loaded": getattr(request.app.state, "data_loaded", False),
    }
