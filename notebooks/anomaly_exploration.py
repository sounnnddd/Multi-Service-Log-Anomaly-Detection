"""
Anomaly Exploration — Visual Validation

Loads the generated JSON log data, bins events into 60-second windows per
service, and produces two key charts:

  1. Latency P95 over time (per service) with anomaly windows shaded
  2. Error rate over time   (per service) with anomaly windows shaded

Exit criteria: the shaded regions must visually align with spikes / drops.
If they don't, the generator needs fixing before moving on.

Usage:
    python notebooks/anomaly_exploration.py
    python notebooks/anomaly_exploration.py --input data/raw/<file>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

# ── Colours for anomaly types ────────────────────────────────────────────────
ANOMALY_COLOURS = {
    "latency_spike": "#e74c3c",   # red
    "error_storm":   "#e67e22",   # orange
    "traffic_drop":  "#3498db",   # blue
    "mixed":         "#9b59b6",   # purple
}

SERVICE_COLOURS = {
    "frontend-service":     "#1abc9c",
    "auth-service":         "#2ecc71",
    "payment-service":      "#3498db",
    "inventory-service":    "#e67e22",
    "notification-service": "#9b59b6",
    "db-service":           "#e74c3c",
}


def load_data(filepath: Path) -> tuple[pd.DataFrame, list[dict], dict]:
    """Load JSON and return (events_df, anomaly_windows, meta)."""
    with open(filepath, encoding="utf-8") as f:
        doc = json.load(f)

    meta = doc["meta"]
    anomaly_windows = doc["anomaly_windows"]
    events = doc["events"]

    df = pd.DataFrame(events)
    df["timestamp"] = pd.to_datetime(df["timestamp_iso"], utc=True)
    return df, anomaly_windows, meta


def bin_events(df: pd.DataFrame, window_seconds: int = 60) -> pd.DataFrame:
    """Bin events into time windows per service, computing key metrics."""
    df = df.copy()
    df["window"] = df["timestamp"].dt.floor(f"{window_seconds}s")

    groups = df.groupby(["service_name", "window"])

    agg = groups.agg(
        total_requests=("request_id", "count"),
        error_count=("status_code", lambda x: (x >= 500).sum()),
        latency_mean=("latency_ms", "mean"),
        latency_p95=("latency_ms", lambda x: np.percentile(x, 95)),
        latency_p99=("latency_ms", lambda x: np.percentile(x, 99)),
        anomaly_events=("is_synthetic_anomaly", "sum"),
    ).reset_index()

    agg["error_rate"] = agg["error_count"] / agg["total_requests"]
    agg["is_anomalous"] = agg["anomaly_events"] > 0
    return agg


def _shade_anomaly_windows(ax, anomaly_windows: list[dict], service: str):
    """Add semi-transparent shading for anomaly windows on a subplot."""
    for aw in anomaly_windows:
        if aw["service_name"] != service:
            continue
        start = pd.to_datetime(aw["window_start_iso"], utc=True)
        end = pd.to_datetime(aw["window_end_iso"], utc=True)
        colour = ANOMALY_COLOURS.get(aw["anomaly_type"], "#aaaaaa")
        ax.axvspan(start, end, alpha=0.20, color=colour, label=aw["anomaly_type"])


def plot_latency(binned: pd.DataFrame, anomaly_windows: list[dict], out_dir: Path):
    """Plot latency P95 per service with anomaly windows shaded."""
    services = sorted(binned["service_name"].unique())
    n = len(services)
    fig, axes = plt.subplots(n, 1, figsize=(16, 3.0 * n), sharex=True)
    if n == 1:
        axes = [axes]

    for ax, service in zip(axes, services):
        svc = binned[binned["service_name"] == service].sort_values("window")
        colour = SERVICE_COLOURS.get(service, "#333333")
        ax.plot(svc["window"], svc["latency_p95"], linewidth=1.2,
                color=colour, label=f"{service} (p95)")
        ax.fill_between(svc["window"], 0, svc["latency_p95"], alpha=0.08, color=colour)
        _shade_anomaly_windows(ax, anomaly_windows, service)
        ax.set_ylabel("Latency P95 (ms)")
        ax.set_title(service, fontsize=10, fontweight="bold", loc="left")
        ax.tick_params(axis="x", rotation=30)
        ax.grid(axis="y", alpha=0.3)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.suptitle("Latency P95 Over Time — Anomaly Windows Shaded", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out = out_dir / "latency_p95_by_service.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_error_rate(binned: pd.DataFrame, anomaly_windows: list[dict], out_dir: Path):
    """Plot error rate per service with anomaly windows shaded."""
    services = sorted(binned["service_name"].unique())
    n = len(services)
    fig, axes = plt.subplots(n, 1, figsize=(16, 3.0 * n), sharex=True)
    if n == 1:
        axes = [axes]

    for ax, service in zip(axes, services):
        svc = binned[binned["service_name"] == service].sort_values("window")
        colour = SERVICE_COLOURS.get(service, "#333333")
        ax.plot(svc["window"], svc["error_rate"], linewidth=1.2, color=colour,
                label=f"{service} (error rate)")
        ax.fill_between(svc["window"], 0, svc["error_rate"], alpha=0.08, color=colour)
        _shade_anomaly_windows(ax, anomaly_windows, service)
        ax.set_ylabel("Error Rate")
        ax.set_title(service, fontsize=10, fontweight="bold", loc="left")
        ax.set_ylim(-0.02, 1.0)
        ax.tick_params(axis="x", rotation=30)
        ax.grid(axis="y", alpha=0.3)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.suptitle("Error Rate Over Time — Anomaly Windows Shaded", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out = out_dir / "error_rate_by_service.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out}")


def plot_request_volume(binned: pd.DataFrame, anomaly_windows: list[dict], out_dir: Path):
    """Plot request volume per service with anomaly windows shaded."""
    services = sorted(binned["service_name"].unique())
    n = len(services)
    fig, axes = plt.subplots(n, 1, figsize=(16, 3.0 * n), sharex=True)
    if n == 1:
        axes = [axes]

    for ax, service in zip(axes, services):
        svc = binned[binned["service_name"] == service].sort_values("window")
        colour = SERVICE_COLOURS.get(service, "#333333")
        ax.bar(svc["window"], svc["total_requests"], width=pd.Timedelta(seconds=55),
               color=colour, alpha=0.6, label=service)
        _shade_anomaly_windows(ax, anomaly_windows, service)
        ax.set_ylabel("Requests / Window")
        ax.set_title(service, fontsize=10, fontweight="bold", loc="left")
        ax.tick_params(axis="x", rotation=30)
        ax.grid(axis="y", alpha=0.3)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.suptitle("Request Volume Over Time — Anomaly Windows Shaded", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    out = out_dir / "request_volume_by_service.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out}")


def print_summary(meta: dict, anomaly_windows: list[dict]):
    """Print a summary table of the generated data."""
    print("\n" + "=" * 70)
    print("SIMULATION SUMMARY")
    print("=" * 70)
    print(f"  Duration:        {meta['duration_minutes']} minutes")
    print(f"  Services:        {meta['n_services']}")
    print(f"  Total events:    {meta['total_events']:,}")
    print(f"  Normal events:   {meta['normal_events']:,}")
    print(f"  Anomaly events:  {meta['anomaly_events']:,} ({meta['anomaly_events']/max(meta['total_events'],1)*100:.1f}%)")
    print(f"  Anomaly windows: {len(anomaly_windows)}")
    print()

    print("  ANOMALY WINDOWS:")
    print(f"  {'Service':<25} {'Type':<15} {'Start':>10} {'End':>10} {'Duration':>10}")
    print("  " + "-" * 72)
    for aw in anomaly_windows:
        start = pd.to_datetime(aw["window_start_iso"]).strftime("%H:%M:%S")
        end = pd.to_datetime(aw["window_end_iso"]).strftime("%H:%M:%S")
        dur = pd.to_datetime(aw["window_end_iso"]) - pd.to_datetime(aw["window_start_iso"])
        dur_str = f"{dur.total_seconds():.0f}s"
        print(f"  {aw['service_name']:<25} {aw['anomaly_type']:<15} {start:>10} {end:>10} {dur_str:>10}")


def main(input_path: str | None = None):
    """Run the exploration analysis."""
    # Find the latest generated file
    if input_path:
        filepath = Path(input_path)
    else:
        raw_dir = Path("data/raw")
        json_files = sorted(raw_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not json_files:
            print("No generated data found. Run: python simulate_data/generate.py")
            sys.exit(1)
        filepath = json_files[0]

    print(f"Loading data from: {filepath}")
    df, anomaly_windows, meta = load_data(filepath)

    print_summary(meta, anomaly_windows)

    # Bin events into 60-second windows
    binned = bin_events(df, window_seconds=60)

    # Generate plots
    out_dir = Path("notebooks/figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\nGenerating plots...")
    plot_latency(binned, anomaly_windows, out_dir)
    plot_error_rate(binned, anomaly_windows, out_dir)
    plot_request_volume(binned, anomaly_windows, out_dir)

    print(f"\n[OK] All plots saved to {out_dir}/")
    print("  Open them to visually confirm anomaly windows align with spikes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Anomaly exploration — visual validation")
    parser.add_argument("--input", type=str, default=None, help="Path to generated JSON file")
    args = parser.parse_args()
    main(args.input)
