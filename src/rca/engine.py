"""Root-cause analysis engine.

Uses the service dependency graph and anomaly timing to infer
the probable upstream failure source when anomalies are detected.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path

import yaml

from src.schemas import Alert, AlertSeverity, AnomalyEvent, AnomalyType


class RCAEngine:
    """Root-cause analysis engine.

    Given anomaly events and a service dependency graph, infers which
    service is the probable root cause and generates alerts.
    """

    def __init__(self, config_path: str = "configs/services.yaml"):
        self.dependency_graph: dict[str, list[str]] = {}
        self.reverse_graph: dict[str, list[str]] = defaultdict(list)
        self._load_dependencies(config_path)

    def _load_dependencies(self, config_path: str) -> None:
        """Build dependency and reverse-dependency graphs from config."""
        path = Path(config_path)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            for svc in config.get("services", []):
                name = svc["name"]
                deps = svc.get("dependencies", [])
                self.dependency_graph[name] = deps
                for dep in deps:
                    self.reverse_graph[dep].append(name)
        else:
            # Fallback hardcoded graph
            self.dependency_graph = {
                "frontend-service": ["auth-service", "payment-service", "inventory-service"],
                "auth-service": [],
                "payment-service": ["db-service"],
                "inventory-service": ["db-service"],
                "notification-service": [],
                "db-service": [],
            }
            for svc, deps in self.dependency_graph.items():
                for dep in deps:
                    self.reverse_graph[dep].append(svc)

    def analyze(self, anomaly_events: list[AnomalyEvent]) -> list[Alert]:
        """Analyze anomaly events and produce root-cause alerts.

        Logic:
        1. Group anomalies by time window overlap
        2. For each anomalous service, check if any of its dependencies
           are also anomalous at the same time
        3. If a dependency is anomalous, that dependency is the probable
           root cause (walk down the chain to find the deepest one)
        4. Generate an alert with the root cause and evidence
        """
        anomalies = [a for a in anomaly_events if a.is_anomaly]
        if not anomalies:
            print("[rca] No anomalies detected, no alerts to generate.")
            return []

        # Build time-indexed lookup: service -> anomaly events
        anomaly_index: dict[str, list[AnomalyEvent]] = defaultdict(list)
        for a in anomalies:
            anomaly_index[a.service_name].append(a)

        alerts: list[Alert] = []
        seen_root_causes: set[tuple[str, str]] = set()

        for anomaly in anomalies:
            service = anomaly.service_name
            root_cause = self._find_root_cause(service, anomaly, anomaly_index)
            related = self._find_related_services(service, anomaly, anomaly_index)

            # Deduplicate: one alert per (root_cause, affected_service)
            dedup_key = (root_cause, service)
            if dedup_key in seen_root_causes:
                continue
            seen_root_causes.add(dedup_key)

            severity = self._determine_severity(anomaly, related)
            reason = self._build_reason(service, root_cause, anomaly, related)

            alerts.append(Alert(
                alert_id=f"alert-{uuid.uuid4().hex[:8]}",
                triggered_at=anomaly.window_start,
                severity=severity,
                affected_service=service,
                probable_root_cause=root_cause,
                anomaly_type=anomaly.ground_truth_type,
                reason=reason,
                related_services=related,
                evidence=anomaly.feature_snapshot,
            ))

        print(f"[rca] Generated {len(alerts)} alerts from {len(anomalies)} anomalies")
        return alerts

    def _find_root_cause(
        self,
        service: str,
        anomaly: AnomalyEvent,
        anomaly_index: dict[str, list[AnomalyEvent]],
    ) -> str:
        """Walk the dependency chain to find the deepest anomalous dependency."""
        deps = self.dependency_graph.get(service, [])
        for dep in deps:
            if dep in anomaly_index:
                for dep_anomaly in anomaly_index[dep]:
                    if self._windows_overlap(anomaly, dep_anomaly):
                        return self._find_root_cause(dep, dep_anomaly, anomaly_index)
        return service

    def _find_related_services(
        self,
        service: str,
        anomaly: AnomalyEvent,
        anomaly_index: dict[str, list[AnomalyEvent]],
    ) -> list[str]:
        """Find all services with overlapping anomaly windows."""
        related = []
        for other_service, other_anomalies in anomaly_index.items():
            if other_service == service:
                continue
            for other in other_anomalies:
                if self._windows_overlap(anomaly, other):
                    related.append(other_service)
                    break
        return sorted(related)

    @staticmethod
    def _windows_overlap(a: AnomalyEvent, b: AnomalyEvent) -> bool:
        """Check if two anomaly windows overlap in time."""
        return a.window_start <= b.window_end and a.window_end >= b.window_start

    def _determine_severity(
        self, anomaly: AnomalyEvent, related: list[str]
    ) -> AlertSeverity:
        """Determine severity based on confidence and blast radius."""
        if anomaly.confidence > 0.8 and len(related) >= 2:
            return AlertSeverity.CRITICAL
        if anomaly.confidence > 0.5 or len(related) >= 1:
            return AlertSeverity.WARNING
        return AlertSeverity.INFO

    def _build_reason(
        self,
        affected: str,
        root_cause: str,
        anomaly: AnomalyEvent,
        related: list[str],
    ) -> str:
        """Generate a human-readable reason string."""
        if root_cause == affected:
            reason = f"Anomaly detected in {affected} (self-originated)"
        else:
            reason = f"Anomaly in {affected} likely caused by upstream failure in {root_cause}"

        top_features = list(anomaly.feature_snapshot.items())[:3]
        if top_features:
            evidence_str = ", ".join(f"{k}={v}" for k, v in top_features)
            reason += f". Key indicators: {evidence_str}"

        if related:
            reason += f". Also affecting: {', '.join(related)}"

        return reason
