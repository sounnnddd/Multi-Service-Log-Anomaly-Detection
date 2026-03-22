"""FastAPI application — serves pre-computed pipeline results.

Start with:
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from src.api.routers import health, events, features, anomalies, alerts

DATA_DIR = Path("data")
RESULTS_DIR = DATA_DIR / "results"
FEATURES_DIR = DATA_DIR / "features"
NORMALIZED_DIR = DATA_DIR / "normalized"


def _load_json(path: Path) -> list | dict:
    """Load a JSON file, returning an empty list/dict on failure."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load pipeline results into app.state at startup."""
    app.state.anomalies = _load_json(RESULTS_DIR / "anomalies.json")
    app.state.alerts = _load_json(RESULTS_DIR / "alerts.json")
    app.state.metrics = _load_json(RESULTS_DIR / "metrics.json")

    # Load normalised events
    norm_files = sorted(NORMALIZED_DIR.glob("*.json")) if NORMALIZED_DIR.exists() else []
    all_events: list[dict] = []
    for nf in norm_files:
        doc = _load_json(nf)
        if isinstance(doc, dict):
            all_events.extend(doc.get("events", []))
        elif isinstance(doc, list):
            all_events.extend(doc)
    app.state.events = all_events

    # Load feature CSVs into a single DataFrame
    csv_files = sorted(FEATURES_DIR.glob("*.csv")) if FEATURES_DIR.exists() else []
    frames = [pd.read_csv(cf) for cf in csv_files]
    app.state.features_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    data_loaded = bool(app.state.anomalies or app.state.alerts or not app.state.features_df.empty)
    app.state.data_loaded = data_loaded

    n_events = len(app.state.events)
    n_anomalies = len(app.state.anomalies)
    n_alerts = len(app.state.alerts)
    n_features = len(app.state.features_df)
    print(
        f"[api] Data loaded — events={n_events:,}  features={n_features:,}  "
        f"anomalies={n_anomalies:,}  alerts={n_alerts:,}"
    )
    yield


app = FastAPI(
    title="Log Anomaly Detection API",
    description=(
        "REST API for the Multi-Service Log Anomaly Detection platform. "
        "Serves pre-computed pipeline results: normalised events, feature windows, "
        "anomaly scores, root-cause alerts, and evaluation metrics."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ------------------------------------------------------------------
# CORS — allow the Streamlit dashboard (port 8501) to call the API
# ------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# Routers
# ------------------------------------------------------------------
app.include_router(health.router)
app.include_router(events.router)
app.include_router(features.router)
app.include_router(anomalies.router)
app.include_router(alerts.router)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect root to Swagger docs."""
    return RedirectResponse(url="/docs")
