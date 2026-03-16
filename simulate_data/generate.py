"""
Simulated microservice log generator.

Output filename format:
    MMDDYYYY_<unixtime>.json

Usage:
    python simulate_data/generate.py
    python simulate_data/generate.py --services 6 --minutes 120 --anomaly-rate 0.08 --seed 42

Output JSON shape:
{
  "meta": {...},
  "anomaly_windows": [...],
  "events": [...]
}
"""

import argparse
import json
import random
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

# OpenTelemetry-aligned severity numbers
SEVERITY_MAP = {"DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17, "FATAL": 21}

ANOMALY_TYPES = ["latency_spike", "error_storm", "traffic_drop", "mixed"]

ENDPOINT_METHODS = {
    "/login": "GET", "/search": "GET", "/home": "GET",
    "/auth/verify": "GET", "/db/read": "GET", "/db/query": "GET",
    "/inventory/check": "GET", "/auth/logout": "POST",
}


def load_config(config_path: str = "configs/services.yaml") -> dict:
    """Load service topology and anomaly profiles from YAML config."""
    path = Path(config_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return None


def _get_services(config: dict | None) -> list[dict]:
    """Get service list from config or use built-in defaults."""
    if config and "services" in config:
        return config["services"]
    return [
        {
            "name": "frontend-service",
            "endpoints": ["/home", "/search", "/checkout", "/login"],
            "baseline_rps": 25,
            "baseline_latency_mean": 60,
            "baseline_latency_std": 20,
            "baseline_error_rate": 0.01,
            "dependencies": ["auth-service", "payment-service", "inventory-service"],
            "host_count": 3,
        },
        {
            "name": "auth-service",
            "endpoints": ["/auth/login", "/auth/logout", "/auth/refresh", "/auth/verify"],
            "baseline_rps": 20,
            "baseline_latency_mean": 45,
            "baseline_latency_std": 15,
            "baseline_error_rate": 0.01,
            "dependencies": [],
            "host_count": 2,
        },
        {
            "name": "payment-service",
            "endpoints": ["/api/v1/charge", "/api/v1/refund", "/api/v1/status"],
            "baseline_rps": 12,
            "baseline_latency_mean": 85,
            "baseline_latency_std": 30,
            "baseline_error_rate": 0.02,
            "dependencies": ["db-service"],
            "host_count": 2,
        },
        {
            "name": "inventory-service",
            "endpoints": ["/inventory/check", "/inventory/reserve", "/inventory/release"],
            "baseline_rps": 8,
            "baseline_latency_mean": 120,
            "baseline_latency_std": 40,
            "baseline_error_rate": 0.03,
            "dependencies": ["db-service"],
            "host_count": 2,
        },
        {
            "name": "notification-service",
            "endpoints": ["/notify/email", "/notify/sms", "/notify/push"],
            "baseline_rps": 5,
            "baseline_latency_mean": 200,
            "baseline_latency_std": 80,
            "baseline_error_rate": 0.04,
            "dependencies": [],
            "host_count": 1,
        },
        {
            "name": "db-service",
            "endpoints": ["/db/query", "/db/write", "/db/read"],
            "baseline_rps": 18,
            "baseline_latency_mean": 35,
            "baseline_latency_std": 10,
            "baseline_error_rate": 0.005,
            "dependencies": [],
            "host_count": 3,
        },
    ]


def _get_anomaly_profiles(config: dict | None) -> dict:
    """Get anomaly profiles from config or use built-in defaults."""
    if config and "anomaly_profiles" in config:
        return config["anomaly_profiles"]
    return {
        "latency_spike": {
            "latency_multiplier": 8.0,
            "error_rate": 0.05,
            "rps_multiplier": 1.0,
            "status_500_rate": 0.04,
            "description": "Dependency slowdown causing response latency inflation",
        },
        "error_storm": {
            "latency_multiplier": 2.5,
            "error_rate": 0.45,
            "rps_multiplier": 1.2,
            "status_500_rate": 0.42,
            "description": "Upstream or downstream failure causing sustained 5xx burst",
        },
        "traffic_drop": {
            "latency_multiplier": 1.1,
            "error_rate": 0.02,
            "rps_multiplier": 0.1,
            "status_500_rate": 0.01,
            "description": "Service traffic collapse due to crash, unhealthy instance, or load balancer removal",
        },
        "mixed": {
            "latency_multiplier": 5.0,
            "error_rate": 0.30,
            "rps_multiplier": 0.7,
            "status_500_rate": 0.28,
            "description": "Resource exhaustion scenario causing latency, failures, and throughput degradation",
        },
    }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def make_trace_id() -> str:
    return uuid.uuid4().hex[:24]


def make_span_id() -> str:
    return f"span-{uuid.uuid4().hex[:10]}"


def make_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:12]}"


def make_host_id(service_name: str, host_count: int) -> str:
    pod_num = random.randint(1, max(1, host_count))
    return f"{service_name}-pod-{pod_num}"


def choose_dependency(service: dict) -> str | None:
    deps = service.get("dependencies", [])
    return random.choice(deps) if deps else None


def choose_method(endpoint: str) -> str:
    return ENDPOINT_METHODS.get(endpoint, random.choice(["GET", "POST", "PUT", "DELETE"]))


def pick_status_code(error_rate: float, status_500_rate: float) -> int:
    r = random.random()
    if r < status_500_rate:
        return random.choice([500, 502, 503, 504])
    if r < status_500_rate + (error_rate * 0.4):
        return random.choice([400, 401, 403, 404, 429])
    return random.choice([200, 200, 200, 200, 201, 204])


def pick_log_level(status_code: int, latency_ms: float, baseline_latency_mean: float) -> str:
    if status_code >= 500:
        return "ERROR"
    if status_code >= 400:
        return random.choice(["WARN", "WARN", "ERROR"])
    if latency_ms > baseline_latency_mean * 3:
        return "WARN"
    return "INFO"


def infer_event_type(status_code: int, anomaly_type: str | None, dependency: str | None, endpoint: str) -> str:
    if anomaly_type == "latency_spike":
        return "slow_response"
    if anomaly_type == "error_storm":
        if dependency == "db-service":
            return "db_refused"
        if "auth" in endpoint:
            return "auth_failure"
        return "upstream_failure"
    if anomaly_type == "traffic_drop":
        return "traffic_drop"
    if anomaly_type == "mixed":
        return random.choice(["resource_exhaustion", "timeout", "upstream_failure"])

    if status_code >= 500:
        return "server_error"
    if status_code >= 400:
        return "client_error"
    if "search" in endpoint:
        return "search_request"
    if "login" in endpoint:
        return "login_request"
    if "charge" in endpoint:
        return "payment_request"
    return "request_ok"


def pick_message(
    service_name: str,
    level: str,
    status_code: int,
    endpoint: str,
    latency_ms: float,
    anomaly_type: str | None,
    dependency: str | None,
) -> str:
    if anomaly_type == "latency_spike":
        return random.choice([
            f"slow response {latency_ms:.0f}ms on {endpoint}",
            f"dependency latency elevated for {dependency or service_name}",
            f"request queue delay observed on {endpoint}",
        ])
    if anomaly_type == "error_storm":
        return random.choice([
            "upstream timeout: connection refused",
            "database query failed: deadlock detected",
            "circuit breaker OPEN: too many failures",
            "redis unavailable: connection pool exhausted",
            f"handler {endpoint} returned repeated 5xx errors",
        ])
    if anomaly_type == "traffic_drop":
        return random.choice([
            f"traffic volume dropped sharply for {endpoint}",
            "instance count reduced; service handling less traffic",
            "load balancer marked backend unhealthy",
        ])
    if anomaly_type == "mixed":
        return random.choice([
            "resource exhaustion detected: CPU throttling and timeout burst",
            "OOM-like degradation pattern observed",
            f"combined latency and 5xx increase on {endpoint}",
        ])
    if level == "ERROR" and status_code >= 500:
        return random.choice([
            "upstream timeout from dependency",
            "database connection refused",
            "handler panicked during request execution",
        ])
    if level == "WARN":
        return random.choice([
            f"slow response {latency_ms:.0f}ms on {endpoint}",
            "retry attempt triggered",
            "cache miss, falling back to database",
            "rate limit approaching",
        ])
    return f"request completed {endpoint} {status_code} {latency_ms:.0f}ms"


# ---------------------------------------------------------------------------
# Anomaly window planning
# ---------------------------------------------------------------------------

def plan_anomaly_windows(
    services: list[dict],
    start_ts: float,
    end_ts: float,
    anomaly_rate: float,
    anomaly_profiles: dict,
) -> list[dict]:
    windows: list[dict] = []
    for svc in services:
        cursor = start_ts + random.uniform(60, 240)
        while cursor < end_ts:
            if random.random() > anomaly_rate * 3:
                cursor += random.uniform(120, 360)
                continue
            duration = random.uniform(180, 480)
            window_end = min(cursor + duration, end_ts)
            anomaly_type = random.choice(ANOMALY_TYPES)
            windows.append({
                "service_name": svc["name"],
                "window_start": round(cursor, 3),
                "window_end": round(window_end, 3),
                "anomaly_type": anomaly_type,
                "profile": anomaly_profiles[anomaly_type],
            })
            cursor = window_end + random.uniform(300, 600)
    return windows


def build_anomaly_index(windows: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = defaultdict(list)
    for w in windows:
        idx[w["service_name"]].append(w)
    return idx


def active_anomaly_profile(ts: float, service_name: str, index: dict[str, list[dict]]) -> tuple[str | None, dict | None]:
    for w in index.get(service_name, []):
        if w["window_start"] <= ts <= w["window_end"]:
            return w["anomaly_type"], w["profile"]
    return None, None


def _profile_val(profile: dict | None, key: str, default: float) -> float:
    return profile.get(key, default) if profile else default


# ---------------------------------------------------------------------------
# Event generation
# ---------------------------------------------------------------------------

def make_log_event(service: dict, ts: float, trace_id: str, anomaly_type: str | None, anomaly_profile: dict | None) -> dict:
    dependency = choose_dependency(service)
    endpoint = random.choice(service["endpoints"])
    method = choose_method(endpoint)

    latency_multiplier = _profile_val(anomaly_profile, "latency_multiplier", 1.0)
    effective_error_rate = _profile_val(anomaly_profile, "error_rate", service["baseline_error_rate"])
    status_500_rate = _profile_val(anomaly_profile, "status_500_rate", service["baseline_error_rate"] * 0.5)

    latency_mean = service["baseline_latency_mean"] * latency_multiplier
    latency_std = max(1.0, service["baseline_latency_std"] * latency_multiplier)
    latency_ms = max(1.0, random.gauss(latency_mean, latency_std))

    status_code = pick_status_code(effective_error_rate, status_500_rate)
    log_level = pick_log_level(status_code, latency_ms, service["baseline_latency_mean"])
    event_type = infer_event_type(status_code, anomaly_type, dependency, endpoint)
    message = pick_message(
        service_name=service["name"],
        level=log_level,
        status_code=status_code,
        endpoint=endpoint,
        latency_ms=latency_ms,
        anomaly_type=anomaly_type,
        dependency=dependency,
    )

    timestamp_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    host_count = service.get("host_count", 2)

    return {
        "trace_id": trace_id,
        "span_id": make_span_id(),
        "timestamp_iso": timestamp_dt.isoformat(),
        "timestamp_unix": round(ts, 3),
        "service_name": service["name"],
        "host_id": make_host_id(service["name"], host_count),
        "environment": "production",
        "endpoint": endpoint,
        "method": method,
        "log_level": log_level,
        "severity_number": SEVERITY_MAP.get(log_level, 9),
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "request_id": make_request_id(),
        "dependency": dependency,
        "event_type": event_type,
        "message": message,
        "is_synthetic_anomaly": anomaly_profile is not None,
        "anomaly_type": anomaly_type,
    }


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate(
    n_services: int = 6,
    duration_minutes: int = 60,
    anomaly_rate: float = 0.08,
    output_dir: str = "data/raw",
    seed: int = 42,
    config_path: str = "configs/services.yaml",
) -> str:
    random.seed(seed)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    config = load_config(config_path)
    all_services = _get_services(config)
    anomaly_profiles = _get_anomaly_profiles(config)

    now = time.time()
    start_ts = now - (duration_minutes * 60)
    end_ts = now

    services = all_services[: min(n_services, len(all_services))]
    anomaly_windows = plan_anomaly_windows(services, start_ts, end_ts, anomaly_rate, anomaly_profiles)
    anomaly_index = build_anomaly_index(anomaly_windows)

    events: list[dict] = []

    for service in services:
        ts = start_ts
        while ts < end_ts:
            anomaly_type, anomaly_profile = active_anomaly_profile(ts, service["name"], anomaly_index)
            rps_multiplier = _profile_val(anomaly_profile, "rps_multiplier", 1.0)
            effective_rps = max(0.3, service["baseline_rps"] * rps_multiplier)

            interval = random.expovariate(effective_rps)
            ts += interval

            if ts >= end_ts:
                break

            trace_id = make_trace_id()
            event = make_log_event(service, ts, trace_id, anomaly_type, anomaly_profile)
            events.append(event)

    events.sort(key=lambda x: x["timestamp_unix"])

    anomaly_count = sum(e["is_synthetic_anomaly"] for e in events)

    doc = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "simulation_start": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat(),
            "simulation_end": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat(),
            "duration_minutes": duration_minutes,
            "n_services": len(services),
            "anomaly_rate_target": anomaly_rate,
            "seed": seed,
            "total_events": len(events),
            "anomaly_events": anomaly_count,
            "normal_events": len(events) - anomaly_count,
        },
        "anomaly_windows": [
            {
                "service_name": w["service_name"],
                "window_start_iso": datetime.fromtimestamp(w["window_start"], tz=timezone.utc).isoformat(),
                "window_end_iso": datetime.fromtimestamp(w["window_end"], tz=timezone.utc).isoformat(),
                "window_start_unix": w["window_start"],
                "window_end_unix": w["window_end"],
                "anomaly_type": w["anomaly_type"],
                "description": w["profile"]["description"],
            }
            for w in anomaly_windows
        ],
        "events": events,
    }

    date_str = datetime.now().strftime("%m%d%Y")
    unix_str = str(int(now))
    filepath = output / f"{date_str}_{unix_str}.json"
    filepath.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    anomaly_pct = (
        doc["meta"]["anomaly_events"] / max(doc["meta"]["total_events"], 1)
    ) * 100.0

    window_lines = "\n".join(
        f"  [{w['service_name']}] {w['anomaly_type']} {w['window_start_iso']} -> {w['window_end_iso']}"
        for w in doc["anomaly_windows"]
    )
    print(
        f"Generated: {filepath}\n"
        f"Total events: {doc['meta']['total_events']:,}\n"
        f"Normal events: {doc['meta']['normal_events']:,}\n"
        f"Anomaly events: {doc['meta']['anomaly_events']:,} ({anomaly_pct:.1f}%)\n"
        f"Anomaly windows:\n{window_lines}"
    )

    return str(filepath)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate simulated microservice logs")
    parser.add_argument("--services", type=int, default=6, help="Number of services to include")
    parser.add_argument("--minutes", type=int, default=60, help="Simulation duration in minutes")
    parser.add_argument("--anomaly-rate", type=float, default=0.08, help="Target anomaly frequency")
    parser.add_argument("--output-dir", type=str, default="data/raw", help="Directory to save JSON output")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--config", type=str, default="configs/services.yaml", help="Path to service config YAML")
    args = parser.parse_args()

    generate(
        n_services=args.services,
        duration_minutes=args.minutes,
        anomaly_rate=args.anomaly_rate,
        output_dir=args.output_dir,
        seed=args.seed,
        config_path=args.config,
    )
