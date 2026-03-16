.PHONY: generate normalize extract train detect pipeline api dashboard test clean

# --- Data Pipeline ---
generate:
	python simulate_data/generate.py --minutes 60 --seed 42 --output-dir data/raw

normalize:
	python -m src.normalizer data/raw data/normalized

extract:
	python -m src.feature_extractor data/normalized data/features

train:
	python scripts/train.py --features-dir data/features --model-out data/models/isolation_forest.joblib

detect:
	python scripts/run_pipeline.py --minutes 60 --seed 42

pipeline: generate normalize extract train detect

# --- Services ---
api:
	uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

dashboard:
	streamlit run src/dashboard/app.py --server.port 8501

# --- Testing ---
test:
	python -m pytest tests/ -v

# --- Cleanup ---
clean:
	rm -rf data/raw/* data/normalized/* data/features/* data/models/*
	rm -rf __pycache__ .pytest_cache
