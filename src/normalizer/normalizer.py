"""Log normalizer module.

Reads raw JSON log files from the generator, validates each event through
the RawLogEvent schema, and emits NormalizedLogEvent instances ready for
feature extraction.

Usage:
    python -m src.normalizer data/raw data/normalized
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.schemas import (
    AnomalyType,
    Environment,
    HttpMethod,
    LogLevel,
    NormalizedLogEvent,
    RawLogEvent,
    SEVERITY_MAP,
)


def normalize_event(raw: dict) -> NormalizedLogEvent | None:
    """Parse and validate a single raw log event dict.

    Returns None if the event cannot be parsed (logs a warning instead
    of crashing the pipeline).
    """
    try:
        raw_event = RawLogEvent(**raw)
    except Exception as exc:
        print(f"[normalizer] SKIP invalid raw event: {exc}")
        return None

    # Parse timestamp
    try:
        timestamp = datetime.fromisoformat(raw_event.timestamp_iso)
    except ValueError:
        timestamp = datetime.fromtimestamp(raw_event.timestamp_unix, tz=timezone.utc)

    # Parse enums with safe fallbacks
    try:
        method = HttpMethod(raw_event.method)
    except ValueError:
        method = HttpMethod.GET

    try:
        log_level = LogLevel(raw_event.log_level)
    except ValueError:
        log_level = LogLevel.INFO

    try:
        environment = Environment(raw_event.environment)
    except ValueError:
        environment = Environment.PRODUCTION

    anomaly_type = None
    if raw_event.anomaly_type:
        try:
            anomaly_type = AnomalyType(raw_event.anomaly_type)
        except ValueError:
            pass

    # Severity number fallback
    severity = raw_event.severity_number
    if severity == 0:
        severity = SEVERITY_MAP.get(log_level, 9)

    return NormalizedLogEvent(
        trace_id=raw_event.trace_id,
        span_id=raw_event.span_id,
        timestamp=timestamp,
        timestamp_unix=raw_event.timestamp_unix,
        service_name=raw_event.service_name,
        host_id=raw_event.host_id,
        environment=environment,
        endpoint=raw_event.endpoint,
        method=method,
        log_level=log_level,
        severity_number=severity,
        status_code=raw_event.status_code,
        latency_ms=raw_event.latency_ms,
        request_id=raw_event.request_id,
        dependency=raw_event.dependency,
        event_type=raw_event.event_type,
        message=raw_event.message,
        is_synthetic_anomaly=raw_event.is_synthetic_anomaly,
        anomaly_type=anomaly_type,
    )


def normalize_events(raw_events: list[dict]) -> list[NormalizedLogEvent]:
    """Normalize a list of raw event dicts, skipping invalid ones."""
    results = []
    for raw in raw_events:
        event = normalize_event(raw)
        if event is not None:
            results.append(event)
    return results


def normalize_file(input_path: Path, output_path: Path) -> int:
    """Normalize a single raw JSON file and write the result.

    Returns the number of successfully normalized events.
    """
    with open(input_path, encoding="utf-8") as f:
        doc = json.load(f)

    raw_events = doc.get("events", [])
    normalized = normalize_events(raw_events)

    output_doc = {
        "meta": doc.get("meta", {}),
        "anomaly_windows": doc.get("anomaly_windows", []),
        "events": [e.model_dump(mode="json") for e in normalized],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_doc, indent=2, default=str), encoding="utf-8")

    print(f"[normalizer] {input_path.name}: {len(normalized)}/{len(raw_events)} events normalized -> {output_path}")
    return len(normalized)


def main(input_dir: str, output_dir: str) -> None:
    """Process all JSON files in input_dir, write to output_dir."""
    in_path = Path(input_dir)
    out_path = Path(output_dir)

    json_files = sorted(in_path.glob("*.json"))
    if not json_files:
        print(f"[normalizer] No JSON files found in {in_path}")
        return

    total = 0
    for jf in json_files:
        out_file = out_path / jf.name
        total += normalize_file(jf, out_file)

    print(f"[normalizer] Done. Total normalized events: {total:,}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.normalizer <input_dir> <output_dir>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
