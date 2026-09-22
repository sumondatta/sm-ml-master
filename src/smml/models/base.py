"""Common interface for every model in the project."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class SoilMoistureModel(ABC):
    """Fit on a feature frame, predict volumetric water content.

    Models take the *frame* rather than a bare matrix because several of them
    need the grouping columns — a sequence model needs to know which rows form a
    site's time series, and the baselines need site and depth identity. Keeping
    one signature across all of them is what lets the cross-validation runner and
    the tuner treat them interchangeably.
    """

    name: str = "base"
    #: Whether the model consumes time-ordered sequences rather than rows.
    sequential: bool = False

    @abstractmethod
    def fit(
        self,
        frame: pd.DataFrame,
        feature_cols: list[str],
        target_col: str,
        sample_weight: np.ndarray | None = None,
        validation: pd.DataFrame | None = None,
    ) -> SoilMoistureModel:
        ...

    @abstractmethod
    def predict(self, frame: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        ...

    def predict_quantiles(
        self, frame: pd.DataFrame, feature_cols: list[str], quantiles: tuple[float, ...]
    ) -> dict[float, np.ndarray]:
        raise NotImplementedError(f"{self.name} does not produce quantiles")

    def feature_importance(self) -> pd.DataFrame | None:
        return None

    def save(self, path: Path | str) -> None:
        import joblib

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path | str) -> SoilMoistureModel:
        import joblib

        return joblib.load(path)

    def get_params(self) -> dict[str, Any]:
        return {}
