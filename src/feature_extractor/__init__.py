"""Feature extractor: time-windowed aggregation of normalized log events."""

from .extractor import extract_features, extract_from_file

__all__ = ["extract_features", "extract_from_file"]
