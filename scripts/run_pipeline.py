"""End-to-end pipeline runner.

Executes: generate -> normalize -> extract features -> train -> detect -> RCA -> save results

Usage:
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --minutes 60 --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from simulate_data.generate import generate
from src.normalizer import normalize_file
from src.feature_extractor.extractor import extract_from_file
from src.detector import AnomalyDetector
from src.rca import RCAEngine


def run_pipeline(
    minutes: int = 60,
    seed: int = 42,
    n_services: int = 6,
    anomaly_rate: float = 0.08,
    window_seconds: int = 60,
    contamination: float = 0.1,
) -> dict:
    """Execute the full pipeline and return summary metrics."""

    data_dir = Path("data")
    raw_dir = data_dir / "raw"
    norm_dir = data_dir / "normalized"
    feat_dir = data_dir / "features"
    model_dir = data_dir / "models"
    results_dir = data_dir / "results"

    for d in [raw_dir, norm_dir, feat_dir, model_dir, results_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Step 1: Generate
    print("\n" + "=" * 60)
    print("STEP 1: Generating simulated logs")
    print("=" * 60)
    raw_path = generate(
        n_services=n_services,
        duration_minutes=minutes,
        anomaly_rate=anomaly_rate,
        output_dir=str(raw_dir),
        seed=seed,
    )
    raw_file = Path(raw_path)

    # Step 2: Normalize
    print("\n" + "=" * 60)
    print("STEP 2: Normalizing log events")
    print("=" * 60)
    norm_file = norm_dir / raw_file.name
    normalize_file(raw_file, norm_file)

    # Step 3: Extract features
    print("\n" + "=" * 60)
    print("STEP 3: Extracting features")
    print("=" * 60)
    feat_file = feat_dir / raw_file.stem
    extract_from_file(norm_file, feat_file, window_seconds)
    feat_csv = feat_file.with_suffix(".csv")
    df = pd.read_csv(feat_csv)

    # Step 4: Train on normal data
    print("\n" + "=" * 60)
    print("STEP 4: Training anomaly detector")
    print("=" * 60)
    df_normal = df[df["has_anomaly"] == False].copy()
    detector = AnomalyDetector(contamination=contamination)
    detector.train(df_normal)
    model_path = model_dir / "isolation_forest.joblib"
    detector.save(model_path)

    # Step 5: Score all windows
    print("\n" + "=" * 60)
    print("STEP 5: Detecting anomalies")
    print("=" * 60)
    anomaly_events = detector.score(df)
    eval_metrics = detector.evaluate(anomaly_events)

    # Step 6: Root cause analysis
    print("\n" + "=" * 60)
    print("STEP 6: Root cause analysis")
    print("=" * 60)
    rca = RCAEngine()
    alerts = rca.analyze(anomaly_events)

    # Step 7: Save results
    print("\n" + "=" * 60)
    print("STEP 7: Saving results")
    print("=" * 60)
    anomalies_out = results_dir / "anomalies.json"
    anomalies_data = [a.model_dump(mode="json") for a in anomaly_events]
    anomalies_out.write_text(json.dumps(anomalies_data, indent=2, default=str), encoding="utf-8")
    print(f"  Anomalies -> {anomalies_out}")

    alerts_out = results_dir / "alerts.json"
    alerts_data = [a.model_dump(mode="json") for a in alerts]
    alerts_out.write_text(json.dumps(alerts_data, indent=2, default=str), encoding="utf-8")
    print(f"  Alerts -> {alerts_out}")

    with open(norm_file, encoding="utf-8") as f:
        norm_doc = json.load(f)

    summary = {
        "meta": {
            "total_events": len(norm_doc.get("events", [])),
            "feature_windows": len(df),
            "normal_windows": len(df_normal),
            "anomalies_detected": sum(1 for a in anomaly_events if a.is_anomaly),
            "alerts_generated": len(alerts),
        },
        "evaluation": eval_metrics,
        "model": {
            "type": "IsolationForest",
            "contamination": contamination,
            "n_features": len(df.columns),
            "model_path": str(model_path),
        },
    }
    metrics_out = results_dir / "metrics.json"
    metrics_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"  Metrics -> {metrics_out}")

    # Print summary
    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Events generated:    {summary['meta']['total_events']:,}")
    print(f"  Feature windows:     {summary['meta']['feature_windows']:,}")
    print(f"  Anomalies detected:  {summary['meta']['anomalies_detected']:,}")
    print(f"  Alerts generated:    {summary['meta']['alerts_generated']:,}")
    print(f"  Precision:           {eval_metrics['precision']:.3f}")
    print(f"  Recall:              {eval_metrics['recall']:.3f}")
    print(f"  F1 Score:            {eval_metrics['f1_score']:.3f}")
    print()

    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the full anomaly detection pipeline")
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--services", type=int, default=6)
    parser.add_argument("--anomaly-rate", type=float, default=0.08)
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--contamination", type=float, default=0.1)
    args = parser.parse_args()

    run_pipeline(
        minutes=args.minutes,
        seed=args.seed,
        n_services=args.services,
        anomaly_rate=args.anomaly_rate,
        window_seconds=args.window,
        contamination=args.contamination,
    )
