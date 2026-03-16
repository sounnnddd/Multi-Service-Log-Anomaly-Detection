"""Anomaly detector module.

Trains an Isolation Forest on feature windows and scores new windows
for anomalous behaviour.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src.schemas import AnomalyEvent, AnomalyType

# Features used for training / scoring (excludes metadata & ground truth)
FEATURE_COLUMNS = [
    "total_requests",
    "error_count",
    "warn_count",
    "info_count",
    "client_error_count",
    "timeout_count",
    "db_failure_count",
    "auth_failure_count",
    "unique_event_types",
    "latency_mean",
    "latency_p50",
    "latency_p95",
    "latency_p99",
    "latency_std",
    "error_rate",
    "requests_per_second",
    "status_2xx_ratio",
    "status_4xx_ratio",
    "status_5xx_ratio",
]


class AnomalyDetector:
    """Isolation-Forest-based anomaly detector.

    Workflow:
        1. detector = AnomalyDetector()
        2. detector.train(df_normal)        # train on normal-only data
        3. results = detector.score(df_all)  # score all windows
        4. detector.save("model.joblib")     # persist
    """

    def __init__(
        self,
        contamination: float = 0.1,
        n_estimators: int = 200,
        random_state: int = 42,
    ):
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.model = IsolationForest(
            contamination=contamination,
            n_estimators=n_estimators,
            random_state=random_state,
        )
        self.scaler = StandardScaler()
        self._is_fitted = False

    def train(self, df: pd.DataFrame) -> "AnomalyDetector":
        """Train on feature windows (should be NORMAL-only data)."""
        X = df[FEATURE_COLUMNS].fillna(0).values
        self.scaler.fit(X)
        X_scaled = self.scaler.transform(X)
        self.model.fit(X_scaled)
        self._is_fitted = True
        print(f"[detector] Trained on {len(df)} normal windows, {len(FEATURE_COLUMNS)} features")
        return self

    def score(self, df: pd.DataFrame) -> list[AnomalyEvent]:
        """Score feature windows and return AnomalyEvent objects."""
        if not self._is_fitted:
            raise RuntimeError("Detector not trained. Call train() first.")

        X = df[FEATURE_COLUMNS].fillna(0).values
        X_scaled = self.scaler.transform(X)

        raw_scores = self.model.decision_function(X_scaled)
        predictions = self.model.predict(X_scaled)  # -1 = anomaly, 1 = normal

        # Normalize scores to [0, 1] confidence (1 = very anomalous)
        score_min, score_max = raw_scores.min(), raw_scores.max()
        score_range = score_max - score_min if score_max != score_min else 1.0
        confidences = 1.0 - (raw_scores - score_min) / score_range

        results: list[AnomalyEvent] = []
        for i, row in df.iterrows():
            is_anomaly = predictions[i] == -1

            # Top contributing features (by absolute z-score)
            z_scores = X_scaled[i]
            top_indices = np.argsort(np.abs(z_scores))[-5:][::-1]
            feature_snapshot = {
                FEATURE_COLUMNS[j]: round(float(df.iloc[i][FEATURE_COLUMNS[j]]), 4)
                for j in top_indices
            }

            # Ground truth
            gt_anomaly = bool(row.get("has_anomaly", False))
            gt_type = None
            if row.get("dominant_anomaly_type"):
                try:
                    gt_type = AnomalyType(row["dominant_anomaly_type"])
                except ValueError:
                    pass

            results.append(AnomalyEvent(
                window_start=_parse_dt(row["window_start"]),
                window_end=_parse_dt(row["window_end"]),
                service_name=row["service_name"],
                anomaly_score=round(float(raw_scores[i]), 6),
                is_anomaly=is_anomaly,
                confidence=round(float(confidences[i]), 4),
                feature_snapshot=feature_snapshot,
                ground_truth_anomaly=gt_anomaly,
                ground_truth_type=gt_type,
            ))

        detected = sum(1 for r in results if r.is_anomaly)
        print(f"[detector] Scored {len(results)} windows: {detected} anomalies detected")
        return results

    def evaluate(self, results: list[AnomalyEvent]) -> dict:
        """Compute precision, recall, F1 against ground truth."""
        tp = sum(1 for r in results if r.is_anomaly and r.ground_truth_anomaly)
        fp = sum(1 for r in results if r.is_anomaly and not r.ground_truth_anomaly)
        fn = sum(1 for r in results if not r.is_anomaly and r.ground_truth_anomaly)
        tn = sum(1 for r in results if not r.is_anomaly and not r.ground_truth_anomaly)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        metrics = {
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "true_negatives": tn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "total_windows": len(results),
        }
        print(
            f"[detector] Evaluation: precision={precision:.3f} recall={recall:.3f} "
            f"f1={f1:.3f} (TP={tp} FP={fp} FN={fn} TN={tn})"
        )
        return metrics

    def save(self, path: str | Path) -> None:
        """Persist the trained model and scaler."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "scaler": self.scaler}, path)
        print(f"[detector] Model saved to {path}")

    def load(self, path: str | Path) -> "AnomalyDetector":
        """Load a previously saved model."""
        data = joblib.load(path)
        self.model = data["model"]
        self.scaler = data["scaler"]
        self._is_fitted = True
        print(f"[detector] Model loaded from {path}")
        return self


def _parse_dt(val) -> datetime:
    """Flexibly parse a datetime from string or datetime object."""
    if isinstance(val, datetime):
        return val
    return datetime.fromisoformat(str(val)).replace(tzinfo=timezone.utc)
