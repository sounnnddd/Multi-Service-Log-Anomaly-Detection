"""Feature extractor module.

Groups normalized log events into time windows per service and computes
aggregate features for anomaly detection.

Usage:
    python -m src.feature_extractor data/normalized data/features
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.schemas import AnomalyType, FeatureWindow, NormalizedLogEvent


def _bucket_key(ts_unix: float, window_seconds: int) -> float:
    """Return the start of the time bucket this timestamp falls into."""
    return (ts_unix // window_seconds) * window_seconds


def extract_features(
    events: list[NormalizedLogEvent],
    window_seconds: int = 60,
    anomaly_windows: list[dict] | None = None,
) -> list[FeatureWindow]:
    """Aggregate normalized events into FeatureWindow rows.

    One FeatureWindow per (service_name, time_bucket).
    """
    # Group events by (service, bucket)
    buckets: dict[tuple[str, float], list[NormalizedLogEvent]] = defaultdict(list)
    for event in events:
        key = (event.service_name, _bucket_key(event.timestamp_unix, window_seconds))
        buckets[key].append(event)

    # Build anomaly lookup for ground truth
    def _has_anomaly(service: str, w_start: float, w_end: float) -> tuple[bool, AnomalyType | None]:
        if not anomaly_windows:
            return False, None
        for aw in anomaly_windows:
            aw_start = aw.get("window_start_unix", 0)
            aw_end = aw.get("window_end_unix", 0)
            if aw.get("service_name") == service and aw_start <= w_end and aw_end >= w_start:
                try:
                    return True, AnomalyType(aw["anomaly_type"])
                except ValueError:
                    return True, None
        return False, None

    results: list[FeatureWindow] = []

    for (service, bucket_start), bucket_events in sorted(buckets.items()):
        bucket_end = bucket_start + window_seconds
        total = len(bucket_events)
        if total == 0:
            continue

        latencies = [e.latency_ms for e in bucket_events]
        lat_arr = np.array(latencies)

        error_count = sum(1 for e in bucket_events if e.status_code >= 500)
        client_error_count = sum(1 for e in bucket_events if 400 <= e.status_code < 500)
        warn_count = sum(1 for e in bucket_events if e.log_level.value == "WARN")
        info_count = sum(1 for e in bucket_events if e.log_level.value == "INFO")
        timeout_count = sum(1 for e in bucket_events if e.event_type in ("timeout", "slow_response"))
        db_failure_count = sum(1 for e in bucket_events if e.event_type == "db_refused")
        auth_failure_count = sum(1 for e in bucket_events if e.event_type == "auth_failure")
        unique_event_types = len({e.event_type for e in bucket_events})

        status_2xx = sum(1 for e in bucket_events if 200 <= e.status_code < 300)
        status_4xx = client_error_count
        status_5xx = error_count

        has_anom, anom_type = _has_anomaly(service, bucket_start, bucket_end)

        results.append(FeatureWindow(
            window_start=datetime.fromtimestamp(bucket_start, tz=timezone.utc),
            window_end=datetime.fromtimestamp(bucket_end, tz=timezone.utc),
            service_name=service,
            total_requests=total,
            error_count=error_count,
            warn_count=warn_count,
            info_count=info_count,
            client_error_count=client_error_count,
            timeout_count=timeout_count,
            db_failure_count=db_failure_count,
            auth_failure_count=auth_failure_count,
            unique_event_types=unique_event_types,
            latency_mean=float(np.mean(lat_arr)),
            latency_p50=float(np.median(lat_arr)),
            latency_p95=float(np.percentile(lat_arr, 95)),
            latency_p99=float(np.percentile(lat_arr, 99)),
            latency_std=float(np.std(lat_arr)) if total > 1 else 0.0,
            error_rate=error_count / total,
            requests_per_second=total / window_seconds,
            status_2xx_ratio=status_2xx / total,
            status_4xx_ratio=status_4xx / total,
            status_5xx_ratio=status_5xx / total,
            has_anomaly=has_anom,
            dominant_anomaly_type=anom_type,
        ))

    return results


def features_to_dataframe(features: list[FeatureWindow]) -> pd.DataFrame:
    """Convert feature windows to a pandas DataFrame."""
    rows = [f.model_dump(mode="json") for f in features]
    return pd.DataFrame(rows)


def extract_from_file(
    input_path: Path,
    output_path: Path,
    window_seconds: int = 60,
) -> int:
    """Extract features from a normalized JSON file, save as CSV.

    Returns the number of feature windows generated.
    """
    with open(input_path, encoding="utf-8") as f:
        doc = json.load(f)

    raw_events = doc.get("events", [])
    anomaly_windows = doc.get("anomaly_windows", [])

    # Parse events into NormalizedLogEvent objects
    normalized = []
    for e in raw_events:
        try:
            normalized.append(NormalizedLogEvent(**e))
        except Exception:
            continue

    features = extract_features(normalized, window_seconds, anomaly_windows)
    df = features_to_dataframe(features)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = output_path.with_suffix(".csv")
    df.to_csv(csv_path, index=False)

    print(f"[feature_extractor] {input_path.name}: {len(features)} windows -> {csv_path}")
    return len(features)


def main(input_dir: str, output_dir: str, window_seconds: int = 60) -> None:
    """Process all normalized JSON files in input_dir."""
    in_path = Path(input_dir)
    out_path = Path(output_dir)

    json_files = sorted(in_path.glob("*.json"))
    if not json_files:
        print(f"[feature_extractor] No JSON files found in {in_path}")
        return

    total = 0
    for jf in json_files:
        out_file = out_path / jf.stem
        total += extract_from_file(jf, out_file, window_seconds)

    print(f"[feature_extractor] Done. Total feature windows: {total:,}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.feature_extractor <input_dir> <output_dir> [window_seconds]")
        sys.exit(1)
    ws = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    main(sys.argv[1], sys.argv[2], ws)
