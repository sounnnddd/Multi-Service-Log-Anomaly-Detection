"""Train the anomaly detection model on existing feature data.

Usage:
    python scripts/train.py
    python scripts/train.py --features-dir data/features --model-out data/models/isolation_forest.joblib
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.detector import AnomalyDetector


def train_model(
    features_dir: str = "data/features",
    model_out: str = "data/models/isolation_forest.joblib",
    contamination: float = 0.1,
) -> None:
    """Train Isolation Forest on feature CSVs."""
    feat_path = Path(features_dir)
    csv_files = sorted(feat_path.glob("*.csv"))

    if not csv_files:
        print(f"No feature CSVs found in {feat_path}")
        sys.exit(1)

    dfs = [pd.read_csv(f) for f in csv_files]
    df = pd.concat(dfs, ignore_index=True)
    print(f"Loaded {len(df)} total feature windows from {len(csv_files)} files")

    df_normal = df[df["has_anomaly"] == False].copy()
    print(f"Training on {len(df_normal)} normal windows (excluding {len(df) - len(df_normal)} anomalous)")

    detector = AnomalyDetector(contamination=contamination)
    detector.train(df_normal)
    detector.save(model_out)

    print("\nEvaluating on full dataset:")
    results = detector.score(df)
    detector.evaluate(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train anomaly detection model")
    parser.add_argument("--features-dir", default="data/features")
    parser.add_argument("--model-out", default="data/models/isolation_forest.joblib")
    parser.add_argument("--contamination", type=float, default=0.1)
    args = parser.parse_args()
    train_model(args.features_dir, args.model_out, args.contamination)
