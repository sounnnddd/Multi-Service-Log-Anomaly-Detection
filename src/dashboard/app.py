"""Streamlit dashboard — visual explorer for anomaly detection results.

Launch:
    streamlit run src/dashboard/app.py --server.port 8501

Requires the API to be running on port 8000 (falls back to direct file reads).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE = "http://localhost:8000"
DATA_DIR = Path("data")

st.set_page_config(
    page_title="Log Anomaly Detection Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Data helpers — call API, fallback to file reads
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def fetch_json(endpoint: str, params: dict | None = None) -> dict | list:
    """GET from the API; fallback to local file if API is down."""
    try:
        r = httpx.get(f"{API_BASE}{endpoint}", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return _fallback(endpoint)


def _fallback(endpoint: str) -> dict | list:
    """Read data directly from local files when the API is unavailable."""
    mapping = {
        "/metrics": DATA_DIR / "results" / "metrics.json",
        "/anomalies": DATA_DIR / "results" / "anomalies.json",
        "/alerts": DATA_DIR / "results" / "alerts.json",
    }
    path = mapping.get(endpoint)
    if path and path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Wrap lists to match API shape
        if isinstance(data, list):
            key = endpoint.strip("/")
            return {"total": len(data), key: data}
        return data
    return {}


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
metrics_data = fetch_json("/metrics")
anomalies_resp = fetch_json("/anomalies", {"anomaly_only": "false"})
alerts_resp = fetch_json("/alerts")
features_resp = fetch_json("/features")

anomalies_list = anomalies_resp.get("anomalies", []) if isinstance(anomalies_resp, dict) else []
alerts_list = alerts_resp.get("alerts", []) if isinstance(alerts_resp, dict) else []
features_list = features_resp.get("features", []) if isinstance(features_resp, dict) else []

df_anomalies = pd.DataFrame(anomalies_list) if anomalies_list else pd.DataFrame()
df_alerts = pd.DataFrame(alerts_list) if alerts_list else pd.DataFrame()
df_features = pd.DataFrame(features_list) if features_list else pd.DataFrame()

# Parse datetime columns
for df in [df_anomalies, df_features]:
    if not df.empty:
        for col in ["window_start", "window_end"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("🔍 Anomaly Detection")
st.sidebar.markdown("---")

services = sorted(df_anomalies["service_name"].unique().tolist()) if not df_anomalies.empty else []
selected_service = st.sidebar.selectbox(
    "Filter by Service",
    options=["All Services"] + services,
    index=0,
)

severity_options = ["All"] + sorted(df_alerts["severity"].unique().tolist()) if not df_alerts.empty else ["All"]
selected_severity = st.sidebar.selectbox("Alert Severity", options=severity_options, index=0)

st.sidebar.markdown("---")
st.sidebar.caption("Data refreshes every 30 seconds.")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("📊 Log Anomaly Detection Dashboard")
st.markdown("Real-time insights from the multi-service anomaly detection pipeline.")
st.markdown("---")

# ---------------------------------------------------------------------------
# KPI Cards
# ---------------------------------------------------------------------------
meta = metrics_data.get("meta", {}) if isinstance(metrics_data, dict) else {}
evaluation = metrics_data.get("evaluation", {}) if isinstance(metrics_data, dict) else {}

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Events", f"{meta.get('total_events', 0):,}")
with col2:
    st.metric("Feature Windows", f"{meta.get('feature_windows', 0):,}")
with col3:
    st.metric("Anomalies Detected", f"{meta.get('anomalies_detected', 0):,}")
with col4:
    st.metric("Alerts Generated", f"{meta.get('alerts_generated', 0):,}")
with col5:
    f1 = evaluation.get("f1_score", 0)
    st.metric("F1 Score", f"{f1:.3f}" if isinstance(f1, (int, float)) else "N/A")

st.markdown("---")

# ---------------------------------------------------------------------------
# Precision / Recall / F1 summary
# ---------------------------------------------------------------------------
if evaluation:
    pcol1, pcol2, pcol3, pcol4 = st.columns(4)
    with pcol1:
        st.metric("Precision", f"{evaluation.get('precision', 0):.3f}")
    with pcol2:
        st.metric("Recall", f"{evaluation.get('recall', 0):.3f}")
    with pcol3:
        st.metric("True Positives", evaluation.get("true_positives", 0))
    with pcol4:
        st.metric("False Positives", evaluation.get("false_positives", 0))
    st.markdown("---")

# ---------------------------------------------------------------------------
# 1. Anomaly Timeline
# ---------------------------------------------------------------------------
st.subheader("🕐 Anomaly Score Timeline")

if not df_anomalies.empty:
    df_plot = df_anomalies.copy()
    if selected_service != "All Services":
        df_plot = df_plot[df_plot["service_name"] == selected_service]

    if not df_plot.empty:
        fig_timeline = px.line(
            df_plot,
            x="window_start",
            y="anomaly_score",
            color="service_name",
            markers=True,
            labels={
                "window_start": "Time",
                "anomaly_score": "Anomaly Score",
                "service_name": "Service",
            },
        )
        # Threshold line — scores below 0 are anomalous in Isolation Forest
        fig_timeline.add_hline(
            y=0, line_dash="dash", line_color="red",
            annotation_text="Anomaly Threshold",
            annotation_position="top right",
        )
        fig_timeline.update_layout(
            height=450,
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_timeline, use_container_width=True)
    else:
        st.info("No anomaly data for the selected service.")
else:
    st.info("No anomaly data available. Run the pipeline first.")

st.markdown("---")

# ---------------------------------------------------------------------------
# 2. Service Heatmap
# ---------------------------------------------------------------------------
st.subheader("🗺️ Service × Time Anomaly Heatmap")

if not df_anomalies.empty:
    # Pivot: service_name as rows, window_start as columns, confidence as values
    df_heat = df_anomalies.copy()
    df_heat["time_label"] = df_heat["window_start"].dt.strftime("%H:%M")
    pivot = df_heat.pivot_table(
        values="confidence", index="service_name", columns="time_label", aggfunc="max"
    )
    if not pivot.empty:
        fig_heatmap = px.imshow(
            pivot.values,
            x=pivot.columns.tolist(),
            y=pivot.index.tolist(),
            color_continuous_scale="YlOrRd",
            labels={"color": "Confidence", "x": "Time Window", "y": "Service"},
            aspect="auto",
        )
        fig_heatmap.update_layout(
            height=350,
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_heatmap, use_container_width=True)
    else:
        st.info("Not enough data for heatmap.")
else:
    st.info("No anomaly data available.")

st.markdown("---")

# ---------------------------------------------------------------------------
# 3. Alert Table
# ---------------------------------------------------------------------------
st.subheader("🚨 Root Cause Alerts")

if not df_alerts.empty:
    df_alert_display = df_alerts.copy()

    if selected_severity != "All":
        df_alert_display = df_alert_display[df_alert_display["severity"] == selected_severity]

    if selected_service != "All Services":
        df_alert_display = df_alert_display[
            (df_alert_display["affected_service"] == selected_service)
            | (df_alert_display["probable_root_cause"] == selected_service)
        ]

    if not df_alert_display.empty:
        display_cols = [
            "alert_id", "severity", "affected_service", "probable_root_cause",
            "anomaly_type", "reason",
        ]
        available_cols = [c for c in display_cols if c in df_alert_display.columns]
        st.dataframe(
            df_alert_display[available_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "severity": st.column_config.TextColumn("Severity", width="small"),
                "alert_id": st.column_config.TextColumn("Alert ID", width="medium"),
                "affected_service": st.column_config.TextColumn("Affected Service"),
                "probable_root_cause": st.column_config.TextColumn("Root Cause"),
                "anomaly_type": st.column_config.TextColumn("Type"),
                "reason": st.column_config.TextColumn("Reason", width="large"),
            },
        )
    else:
        st.info("No alerts match the current filters.")
else:
    st.info("No alerts available. Run the pipeline first.")

st.markdown("---")

# ---------------------------------------------------------------------------
# 4. Feature Explorer
# ---------------------------------------------------------------------------
st.subheader("📈 Feature Explorer")

if not df_features.empty:
    feature_cols = [
        "latency_p95", "error_rate", "requests_per_second", "latency_mean",
        "latency_p99", "error_count", "total_requests", "status_5xx_ratio",
    ]
    available_features = [c for c in feature_cols if c in df_features.columns]

    fcol1, fcol2 = st.columns(2)
    with fcol1:
        feat_service = st.selectbox(
            "Service",
            options=services if services else ["No services"],
            key="feature_service",
        )
    with fcol2:
        feat_metric = st.selectbox("Metric", options=available_features, key="feature_metric")

    df_feat_plot = df_features[df_features["service_name"] == feat_service].copy()

    if not df_feat_plot.empty and feat_metric:
        fig_feat = go.Figure()

        fig_feat.add_trace(go.Scatter(
            x=df_feat_plot["window_start"],
            y=df_feat_plot[feat_metric],
            mode="lines+markers",
            name=feat_metric,
            line=dict(color="#636EFA"),
        ))

        # Shade anomaly windows
        if "has_anomaly" in df_feat_plot.columns:
            anom_windows = df_feat_plot[df_feat_plot["has_anomaly"] == True]
            for _, row in anom_windows.iterrows():
                fig_feat.add_vrect(
                    x0=row["window_start"], x1=row["window_end"],
                    fillcolor="red", opacity=0.1, line_width=0,
                )

        fig_feat.update_layout(
            title=f"{feat_metric} — {feat_service}",
            xaxis_title="Time",
            yaxis_title=feat_metric,
            height=400,
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_feat, use_container_width=True)
    else:
        st.info("No feature data for the selected service.")
else:
    st.info("No feature data available. Run the pipeline first.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "Multi-Service Log Anomaly Detection Platform · "
    "Phase 3 · FastAPI + Streamlit · Isolation Forest"
)
