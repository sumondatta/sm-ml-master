"""Project path resolution.

Every path in the project derives from a single root so that the whole pipeline
can be pointed at an external disk (the harvested corpus is expected to reach
terabyte scale) by setting one environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_ROOT = "SMML_DATA_ROOT"


def repo_root() -> Path:
    """Directory containing pyproject.toml, walking up from this file."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[3]


def data_root() -> Path:
    """Root of all data storage. Override with ``SMML_DATA_ROOT``."""
    env = os.environ.get(ENV_ROOT)
    return Path(env).expanduser().resolve() if env else repo_root() / "data"


def _sub(name: str) -> Path:
    p = data_root() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def raw_dir() -> Path:
    """Immutable, content-addressed cache of everything downloaded."""
    return _sub("raw")


def interim_dir() -> Path:
    """Parsed-but-not-yet-harmonized intermediates."""
    return _sub("interim")


def processed_dir() -> Path:
    """The harmonized database (partitioned Parquet)."""
    return _sub("processed")


def external_dir() -> Path:
    """Third-party rasters/grids kept outside the fact tables."""
    return _sub("external")


def literature_dir() -> Path:
    """Literature corpus: metadata, PDFs, extracted figures, digitized series."""
    return _sub("literature")


def cache_dir() -> Path:
    """HTTP response cache."""
    return _sub("cache")


def artifacts_dir() -> Path:
    """Model artifacts, Optuna studies, evaluation reports."""
    p = repo_root() / "artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p
