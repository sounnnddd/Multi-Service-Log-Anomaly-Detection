"""Feature windows endpoint — filterable by service and anomaly status."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["Features"])


@router.get("/features")
async def list_features(
    request: Request,
    service: str | None = Query(None, description="Filter by service_name"),
    anomaly_only: bool = Query(False, description="Return only windows with ground-truth anomalies"),
) -> dict:
    """Return feature window records from the pipeline."""
    import pandas as pd

    df: pd.DataFrame = getattr(request.app.state, "features_df", pd.DataFrame())

    if df.empty:
        return {"total": 0, "features": []}

    if service:
        df = df[df["service_name"] == service]
    if anomaly_only:
        df = df[df["has_anomaly"] == True]

    records = df.to_dict(orient="records")

    return {
        "total": len(records),
        "features": records,
    }
