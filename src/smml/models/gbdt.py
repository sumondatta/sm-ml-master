"""Gradient-boosted tree models.

Boosted trees are the right default for this problem and usually the model to
beat. The feature set is tabular and heterogeneous (continuous weather
aggregates, categorical texture classes, a depth coordinate), the relationships
are strongly non-linear with sharp thresholds, and the corpus will contain
missing values everywhere — all of which LightGBM handles natively and a neural
network handles only with effort.

Two things here are specific to soil moisture rather than generic wrappers:

*Sample weighting by observation uncertainty.* The corpus mixes gravimetric
samples accurate to 0.01 m3/m3 with values digitized off a small printed figure.
Weighting by inverse variance is what stops the noisy majority from dominating.

*Monotonic constraints.* Water content cannot decrease when antecedent
precipitation increases, all else equal. Imposing that costs a little training
fit and buys extrapolation behaviour that stays physical outside the training
range — which is the whole point of a model meant for new fields.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from .base import SoilMoistureModel

log = logging.getLogger(__name__)

#: Features whose effect on water content is physically signed. Used to build
#: LightGBM/XGBoost monotone constraint vectors. Prefixes are matched, so
#: ``precip_sum_`` covers every window.
MONOTONE_INCREASING_PREFIXES = (
    "precip_sum_", "precip_max_", "wet_days_", "precip_lag",
    "api_", "irrigation_sum_", "bucket_storage_mm", "bucket_fill",
    "water_balance_",
)
MONOTONE_DECREASING_PREFIXES = (
    "days_since_rain_", "days_since_irrigation", "et0_sum_", "et0_lag",
)


def build_monotone_constraints(feature_cols: list[str]) -> list[int]:
    """+1, -1 or 0 per feature, by physical reasoning about its sign."""
    out = []
    for col in feature_cols:
        if col.startswith(MONOTONE_INCREASING_PREFIXES):
            out.append(1)
        elif col.startswith(MONOTONE_DECREASING_PREFIXES):
            out.append(-1)
        else:
            out.append(0)
    return out


DEFAULT_LGBM_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 127,
    "max_depth": -1,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.7,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l1": 0.0,
    "lambda_l2": 1.0,
    "max_bin": 255,
    "verbosity": -1,
    "num_threads": 0,
    "force_col_wise": True,
}


class LightGBMModel(SoilMoistureModel):
    """LightGBM regressor over the pooled multi-depth table.

    A single model across all depths, with depth as a feature, rather than one
    model per depth. Sharing lets the deep layers — which are always the
    scarcest data — borrow the weather-response structure learned from the
    abundant surface observations, and it lets the model serve a depth that was
    never in the training set.
    """

    name = "lightgbm"

    def __init__(
        self,
        params: dict | None = None,
        num_boost_round: int = 2000,
        early_stopping_rounds: int = 100,
        monotone: bool = False,
        objective: str = "regression",
    ) -> None:
        self.params = {**DEFAULT_LGBM_PARAMS, **(params or {})}
        self.params["objective"] = objective
        self.num_boost_round = num_boost_round
        self.early_stopping_rounds = early_stopping_rounds
        self.monotone = monotone
        self.booster_ = None
        self.feature_cols_: list[str] = []
        self.categorical_: list[str] = []
        self.best_iteration_: int | None = None

    def _dataset(self, frame, feature_cols, target_col, weight=None, reference=None):
        import lightgbm as lgb

        x = frame[feature_cols]
        y = frame[target_col].to_numpy(dtype=float)
        cats = [c for c in feature_cols if str(x[c].dtype) == "category"]
        return lgb.Dataset(x, label=y, weight=weight, categorical_feature=cats or "auto",
                           reference=reference, free_raw_data=False), cats

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        import lightgbm as lgb

        self.feature_cols_ = list(feature_cols)
        params = dict(self.params)
        if self.monotone:
            params["monotone_constraints"] = build_monotone_constraints(self.feature_cols_)
            params["monotone_constraints_method"] = "advanced"

        train_set, cats = self._dataset(frame, self.feature_cols_, target_col, sample_weight)
        self.categorical_ = cats

        callbacks = [lgb.log_evaluation(period=0)]
        valid_sets = []
        if validation is not None and len(validation):
            valid, _ = self._dataset(validation, self.feature_cols_, target_col,
                                     reference=train_set)
            valid_sets = [valid]
            callbacks.append(lgb.early_stopping(self.early_stopping_rounds, verbose=False))

        self.booster_ = lgb.train(
            params, train_set, num_boost_round=self.num_boost_round,
            valid_sets=valid_sets or None, callbacks=callbacks,
        )
        self.best_iteration_ = self.booster_.best_iteration or self.num_boost_round
        return self

    def predict(self, frame, feature_cols):
        if self.booster_ is None:
            raise RuntimeError("model is not fitted")
        return self.booster_.predict(frame[self.feature_cols_],
                                     num_iteration=self.best_iteration_)

    def feature_importance(self):
        if self.booster_ is None:
            return None
        return pd.DataFrame({
            "feature": self.booster_.feature_name(),
            "gain": self.booster_.feature_importance("gain"),
            "split": self.booster_.feature_importance("split"),
        }).sort_values("gain", ascending=False).reset_index(drop=True)

    def get_params(self):
        return dict(self.params)


class LightGBMQuantileModel(SoilMoistureModel):
    """A set of LightGBM quantile regressors, for prediction intervals.

    An irrigation decision needs to know how confident the estimate is, not just
    what it is. Quantile regression gives that directly and without a
    distributional assumption, which matters because soil moisture error is
    strongly heteroscedastic — much larger in wet transitions than in a stable
    drydown.
    """

    name = "lightgbm_quantile"

    def __init__(self, quantiles: tuple[float, ...] = (0.05, 0.25, 0.5, 0.75, 0.95),
                 params: dict | None = None, num_boost_round: int = 800):
        self.quantiles = quantiles
        self.params = {**DEFAULT_LGBM_PARAMS, **(params or {})}
        self.num_boost_round = num_boost_round
        self.models_: dict[float, LightGBMModel] = {}
        self.feature_cols_: list[str] = []

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        self.feature_cols_ = list(feature_cols)
        for q in self.quantiles:
            params = {**self.params, "objective": "quantile", "alpha": q, "metric": "quantile"}
            model = LightGBMModel(params=params, num_boost_round=self.num_boost_round,
                                  objective="quantile")
            model.fit(frame, feature_cols, target_col, sample_weight, validation)
            self.models_[q] = model
        return self

    def predict(self, frame, feature_cols):
        median = min(self.quantiles, key=lambda q: abs(q - 0.5))
        return self.models_[median].predict(frame, feature_cols)

    def predict_quantiles(self, frame, feature_cols, quantiles=None):
        qs = quantiles or self.quantiles
        out = {q: self.models_[q].predict(frame, feature_cols) for q in qs if q in self.models_}
        # Quantile regressors are fitted independently and can cross; sorting
        # the stacked predictions restores monotonicity, which is the standard
        # and least-damaging repair.
        keys = sorted(out)
        stacked = np.sort(np.vstack([out[k] for k in keys]), axis=0)
        return dict(zip(keys, stacked, strict=True))


DEFAULT_XGB_PARAMS: dict[str, Any] = {
    "objective": "reg:squarederror",
    "eval_metric": "rmse",
    "learning_rate": 0.05,
    "max_depth": 8,
    "min_child_weight": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "reg_lambda": 1.0,
    "reg_alpha": 0.0,
    "tree_method": "hist",
    "max_cat_to_onehot": 8,
}


class XGBoostModel(SoilMoistureModel):
    """XGBoost regressor. A second opinion with different inductive biases.

    Kept alongside LightGBM because their split-finding differs enough that they
    fail on different subsets, which makes the pair useful both as a check and
    as ensemble members.
    """

    name = "xgboost"

    def __init__(self, params: dict | None = None, num_boost_round: int = 2000,
                 early_stopping_rounds: int = 100, monotone: bool = False):
        self.params = {**DEFAULT_XGB_PARAMS, **(params or {})}
        self.num_boost_round = num_boost_round
        self.early_stopping_rounds = early_stopping_rounds
        self.monotone = monotone
        self.booster_ = None
        self.feature_cols_: list[str] = []
        self.best_iteration_: int | None = None

    def fit(self, frame, feature_cols, target_col, sample_weight=None, validation=None):
        import xgboost as xgb

        self.feature_cols_ = list(feature_cols)
        params = dict(self.params)
        if self.monotone:
            params["monotone_constraints"] = "(" + ",".join(
                str(v) for v in build_monotone_constraints(self.feature_cols_)
            ) + ")"

        dtrain = xgb.DMatrix(frame[self.feature_cols_], label=frame[target_col].to_numpy(dtype=float),
                             weight=sample_weight, enable_categorical=True)
        evals = []
        if validation is not None and len(validation):
            dvalid = xgb.DMatrix(validation[self.feature_cols_],
                                 label=validation[target_col].to_numpy(dtype=float),
                                 enable_categorical=True)
            evals = [(dvalid, "valid")]

        self.booster_ = xgb.train(
            params, dtrain, num_boost_round=self.num_boost_round, evals=evals,
            early_stopping_rounds=self.early_stopping_rounds if evals else None,
            verbose_eval=False,
        )
        self.best_iteration_ = getattr(self.booster_, "best_iteration", None)
        return self

    def predict(self, frame, feature_cols):
        import xgboost as xgb

        if self.booster_ is None:
            raise RuntimeError("model is not fitted")
        d = xgb.DMatrix(frame[self.feature_cols_], enable_categorical=True)
        kwargs = {}
        if self.best_iteration_ is not None:
            kwargs["iteration_range"] = (0, self.best_iteration_ + 1)
        return self.booster_.predict(d, **kwargs)

    def feature_importance(self):
        if self.booster_ is None:
            return None
        gain = self.booster_.get_score(importance_type="gain")
        return pd.DataFrame(
            {"feature": list(gain), "gain": list(gain.values())}
        ).sort_values("gain", ascending=False).reset_index(drop=True)

    def get_params(self):
        return dict(self.params)


def uncertainty_weights(
    frame: pd.DataFrame,
    uncertainty_col: str = "uncertainty_m3m3",
    default: float = 0.03,
    clip: tuple[float, float] = (0.2, 5.0),
) -> np.ndarray:
    """Inverse-variance sample weights, normalized to mean one.

    Clipped so that a single very precise observation cannot dominate a fold,
    and so a very uncertain one is down-weighted without being discarded.
    """
    if uncertainty_col in frame.columns:
        sigma = frame[uncertainty_col].to_numpy(dtype=float)
    else:
        sigma = np.full(len(frame), default)
    sigma = np.where(np.isfinite(sigma) & (sigma > 0), sigma, default)
    w = 1.0 / sigma**2
    w = w / w.mean()
    return np.clip(w, *clip)
