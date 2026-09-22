"""Baselines that a learned model has to beat to be worth anything.

Each of these is cheap, interpretable, and surprisingly hard to beat on some
subsets of the data. Reporting a neural network's RMSE without these alongside
says nothing: soil moisture has a strong seasonal cycle and enormous day-to-day
persistence, so a model can look accurate while adding no information at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..physics.water import saxton_rawls
from .base import SoilMoistureModel


class GlobalMeanBaseline(SoilMoistureModel):
    """Predict the training mean everywhere. The absolute floor."""

    name = "global_mean"

    def __init__(self) -> None:
        self.mean_ = np.nan

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        self.mean_ = float(np.nanmean(frame[target_col].to_numpy(dtype=float)))
        return self

    def predict(self, frame, feature_cols):
        return np.full(len(frame), self.mean_)


class DepthClimatologyBaseline(SoilMoistureModel):
    """Predict the seasonal mean for this depth and time of year.

    Fitted per depth band and per day-of-year window from the training sites
    only, so it transfers to a held-out site. This is the baseline that matters:
    it captures everything obtainable from "what month is it and how deep",
    which is a large fraction of the variance and none of the useful signal.
    """

    name = "depth_climatology"

    def __init__(self, doy_window: int = 15, depth_bins: tuple[float, ...] = (0, 10, 30, 60, 100, 1000)):
        self.doy_window = doy_window
        self.depth_bins = depth_bins
        self.table_: pd.DataFrame | None = None
        self.fallback_ = np.nan

    def _keys(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        depth = pd.cut(frame["depth_mid_cm"].astype(float), self.depth_bins, labels=False,
                       include_lowest=True)
        doy = pd.to_datetime(frame["date"]).dt.dayofyear
        bucket = ((doy - 1) // self.doy_window).astype(int)
        return depth.to_numpy(), bucket.to_numpy()

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        depth, bucket = self._keys(frame)
        work = pd.DataFrame({"depth": depth, "bucket": bucket,
                             "y": frame[target_col].to_numpy(dtype=float)})
        self.table_ = work.groupby(["depth", "bucket"], dropna=True).y.mean()
        self.fallback_ = float(np.nanmean(work.y))
        return self

    def predict(self, frame, feature_cols):
        depth, bucket = self._keys(frame)
        idx = pd.MultiIndex.from_arrays([depth, bucket])
        out = self.table_.reindex(idx).to_numpy()
        return np.where(np.isfinite(out), out, self.fallback_)


class FieldCapacityBaseline(SoilMoistureModel):
    """Predict the soil's field capacity from texture. A pure-pedology guess.

    No weather, no season — just what the soil would hold after drainage. It is
    the answer an agronomist would give with no other information, and a learned
    model that cannot beat it has learned nothing about hydrology.
    """

    name = "field_capacity"

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        self.fallback_ = float(np.nanmean(frame[target_col].to_numpy(dtype=float)))
        return self

    def predict(self, frame, feature_cols):
        if "field_capacity_m3m3" in frame.columns:
            out = frame["field_capacity_m3m3"].to_numpy(dtype=float)
        elif {"sand_pct", "clay_pct"} <= set(frame.columns):
            om = frame["om_pct"].fillna(2.0).to_numpy(dtype=float) if "om_pct" in frame else 2.0
            out = saxton_rawls(frame["sand_pct"].to_numpy(dtype=float),
                               frame["clay_pct"].to_numpy(dtype=float), om)["field_capacity_m3m3"]
        else:
            out = np.full(len(frame), self.fallback_)
        return np.where(np.isfinite(out), out, self.fallback_)


class BucketBaseline(SoilMoistureModel):
    """Scale the simple water-balance bucket onto the observed range.

    The bucket state is already a feature (see
    :func:`smml.features.build.simple_bucket_state`); this fits a per-depth
    linear map from bucket fill to water content, giving a physics-only
    prediction driven entirely by weather and texture. It is the strongest of
    the non-learned baselines and the fairest benchmark for "does machine
    learning add anything over a conventional water balance".
    """

    name = "bucket"

    def __init__(self, depth_bins: tuple[float, ...] = (0, 10, 30, 60, 100, 1000)):
        self.depth_bins = depth_bins
        self.coef_: dict[int, tuple[float, float]] = {}
        self.fallback_ = (0.0, np.nan)

    def _depth_bin(self, frame: pd.DataFrame) -> np.ndarray:
        return pd.cut(frame["depth_mid_cm"].astype(float), self.depth_bins, labels=False,
                      include_lowest=True).to_numpy()

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        if "bucket_fill" not in frame.columns:
            raise ValueError("BucketBaseline needs the bucket_fill feature")
        x = frame["bucket_fill"].to_numpy(dtype=float)
        y = frame[target_col].to_numpy(dtype=float)
        bins = self._depth_bin(frame)
        ok = np.isfinite(x) & np.isfinite(y)
        self.fallback_ = (0.0, float(np.nanmean(y[ok])) if ok.any() else np.nan)
        for b in np.unique(bins[ok]):
            m = ok & (bins == b)
            if m.sum() < 30 or np.std(x[m]) < 1e-9:
                continue
            slope, intercept = np.polyfit(x[m], y[m], 1)
            self.coef_[int(b)] = (float(slope), float(intercept))
        return self

    def predict(self, frame, feature_cols):
        x = frame["bucket_fill"].to_numpy(dtype=float)
        bins = self._depth_bin(frame)
        out = np.empty(len(frame))
        for i, (xi, b) in enumerate(zip(x, bins, strict=True)):
            slope, intercept = self.coef_.get(int(b) if np.isfinite(b) else -1, self.fallback_)
            out[i] = slope * xi + intercept if np.isfinite(xi) else intercept
        return out


class PersistenceBaseline(SoilMoistureModel):
    """Predict yesterday's observed value at the same site and depth.

    Only meaningful where a sensor already exists, so it is *not* a valid
    baseline for the primary task. It is included because it is the correct
    baseline for the gap-filling and short-horizon-forecast use cases, and
    because its score makes clear how much of a good-looking result comes from
    autocorrelation alone.
    """

    name = "persistence"

    def __init__(self, lag: int = 1):
        self.lag = lag
        self.fallback_ = np.nan

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        self.target_col_ = target_col
        self.fallback_ = float(np.nanmean(frame[target_col].to_numpy(dtype=float)))
        return self

    def predict(self, frame, feature_cols):
        work = frame.sort_values(["site_id", "depth_top_cm", "date"])
        shifted = work.groupby(["site_id", "depth_top_cm"], observed=True)[self.target_col_].shift(self.lag)
        out = shifted.reindex(frame.index).to_numpy(dtype=float)
        return np.where(np.isfinite(out), out, self.fallback_)


BASELINES = {
    "global_mean": GlobalMeanBaseline,
    "depth_climatology": DepthClimatologyBaseline,
    "field_capacity": FieldCapacityBaseline,
    "bucket": BucketBaseline,
    "persistence": PersistenceBaseline,
}
