"""Cross-validation runner.

One entry point that takes a model, a split scheme and a feature frame, and
returns out-of-fold predictions plus stratified metrics. Everything downstream —
baseline comparison, hyperparameter search, the final report — goes through it,
so the evaluation protocol is defined in exactly one place and cannot drift
between experiments.

The out-of-fold prediction vector is the primary output, not the metric. Having
every prediction the model made on data it did not see lets any metric be
recomputed later, lets errors be sliced by any covariate, and lets models be
compared on identical folds.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..models.base import SoilMoistureModel
from .metrics import (
    compute_metrics,
    metrics_by_group,
    per_site_then_average,
    skill_decomposition,
)

log = logging.getLogger(__name__)

Splitter = Callable[[pd.DataFrame], Iterator[tuple[np.ndarray, np.ndarray]]]


@dataclass
class CVResult:
    """Everything a cross-validation run produced."""

    model_name: str
    split_name: str
    target_col: str
    oof: pd.DataFrame
    fold_metrics: pd.DataFrame
    overall: dict[str, float]
    per_site: dict[str, float]
    skill: dict[str, float]
    by_depth: pd.DataFrame
    by_texture: pd.DataFrame
    by_salinity: pd.DataFrame
    by_irrigation: pd.DataFrame
    importance: pd.DataFrame | None = None
    fit_seconds: float = 0.0
    params: dict[str, Any] = field(default_factory=dict)

    def summary_row(self) -> dict[str, Any]:
        row = {"model": self.model_name, "split": self.split_name, "target": self.target_col}
        row.update(dict(self.overall.items()))
        row.update({k: v for k, v in self.per_site.items() if k.startswith("site_mean")})
        row.update({k: self.skill[k] for k in ("r_between", "r_within", "ubrmse_within")
                    if k in self.skill})
        row["fit_seconds"] = round(self.fit_seconds, 1)
        return row

    def __str__(self) -> str:
        o = self.overall
        return (
            f"{self.model_name} / {self.split_name}: "
            f"RMSE={o.get('rmse', float('nan')):.4f} "
            f"ubRMSE={o.get('ubrmse', float('nan')):.4f} "
            f"bias={o.get('bias', float('nan')):+.4f} "
            f"R={o.get('r', float('nan')):.3f} "
            f"KGE={o.get('kge', float('nan')):+.3f} "
            f"r_within={self.skill.get('r_within', float('nan')):.3f} "
            f"n={o.get('n', 0):,}"
        )


def _salinity_band(values: pd.Series) -> pd.Series:
    return pd.cut(values, [-0.01, 2, 4, 8, 1e6],
                  labels=["non_saline", "slightly", "moderately", "strongly"])


def _depth_band(values: pd.Series) -> pd.Series:
    return pd.cut(values, [-0.01, 10, 30, 60, 100, 1e6],
                  labels=["0-10cm", "10-30cm", "30-60cm", "60-100cm", ">100cm"])


def run_cv(
    frame: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    model_factory: Callable[[], SoilMoistureModel],
    splitter: Splitter,
    split_name: str = "split",
    sample_weight_fn: Callable[[pd.DataFrame], np.ndarray] | None = None,
    inner_validation_fraction: float = 0.0,
    truth_col: str | None = None,
    max_folds: int | None = None,
    verbose: bool = True,
) -> CVResult:
    """Fit and score a model across folds, returning out-of-fold predictions.

    ``inner_validation_fraction`` carves a validation slice out of each training
    fold for early stopping. It is split *by site*, not at random, so early
    stopping is judged on unseen sites and cannot itself leak.

    ``truth_col`` lets a model trained against the noisy observed value be scored
    against a clean reference where one exists — meaningful only for synthetic
    data, where it separates error the model could have avoided from noise it
    could not.
    """
    frame = frame.reset_index(drop=True)
    oof_pred = np.full(len(frame), np.nan)
    oof_fold = np.full(len(frame), -1, dtype=int)
    fold_rows = []
    importance = None
    started = time.time()

    for fold_index, (train_idx, test_idx) in enumerate(splitter(frame)):
        if max_folds is not None and fold_index >= max_folds:
            break
        train = frame.iloc[train_idx]
        test = frame.iloc[test_idx]

        validation = None
        if inner_validation_fraction > 0 and "site_id" in train.columns:
            sites = pd.unique(train["site_id"])
            rng = np.random.default_rng(fold_index)
            n_val = max(1, int(len(sites) * inner_validation_fraction))
            val_sites = set(rng.choice(sites, size=min(n_val, len(sites) - 1), replace=False))
            mask = train["site_id"].isin(val_sites)
            validation = train[mask]
            train = train[~mask]

        weight = sample_weight_fn(train) if sample_weight_fn else None

        model = model_factory()
        model.fit(train, feature_cols, target_col, sample_weight=weight, validation=validation)
        pred = np.asarray(model.predict(test, feature_cols), dtype=float)

        oof_pred[test_idx] = pred
        oof_fold[test_idx] = fold_index

        score_against = truth_col if (truth_col and truth_col in test.columns) else target_col
        m = compute_metrics(test[score_against], pred)
        m["fold"] = fold_index
        m["n_train"] = len(train)
        fold_rows.append(m)

        if importance is None:
            importance = model.feature_importance()

        if verbose:
            log.info("fold %d: RMSE=%.4f n=%d", fold_index, m["rmse"], m["n"])

    oof = frame.copy()
    oof["prediction"] = oof_pred
    oof["fold"] = oof_fold
    scored = oof[oof["fold"] >= 0].copy()

    score_against = truth_col if (truth_col and truth_col in scored.columns) else target_col
    overall = compute_metrics(scored[score_against], scored["prediction"])
    per_site = per_site_then_average(scored, score_against, "prediction")
    skill = skill_decomposition(scored, score_against, "prediction")

    def stratify(col_values: pd.Series | None, name: str) -> pd.DataFrame:
        if col_values is None:
            return pd.DataFrame()
        work = scored.copy()
        work[name] = col_values.reset_index(drop=True) if hasattr(col_values, "reset_index") else col_values
        return metrics_by_group(work, score_against, "prediction", name)

    by_depth = stratify(_depth_band(scored["depth_mid_cm"]) if "depth_mid_cm" in scored else None, "depth_band")
    by_texture = stratify(scored.get("texture_class", None), "texture_class")
    by_salinity = stratify(_salinity_band(scored["ece_ds_m"]) if "ece_ds_m" in scored else None, "salinity_band")
    by_irrigation = stratify(scored.get("irrigation_method", None), "irrigation_method")

    model_name = model_factory().name
    return CVResult(
        model_name=model_name,
        split_name=split_name,
        target_col=target_col,
        oof=oof,
        fold_metrics=pd.DataFrame(fold_rows),
        overall=overall,
        per_site=per_site,
        skill=skill,
        by_depth=by_depth,
        by_texture=by_texture,
        by_salinity=by_salinity,
        by_irrigation=by_irrigation,
        importance=importance,
        fit_seconds=time.time() - started,
    )


def compare_models(
    frame: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    factories: dict[str, Callable[[], SoilMoistureModel]],
    splitter: Splitter,
    split_name: str = "split",
    truth_col: str | None = None,
    **kwargs,
) -> tuple[pd.DataFrame, dict[str, CVResult]]:
    """Run several models over identical folds and tabulate them."""
    results: dict[str, CVResult] = {}
    for name, factory in factories.items():
        log.info("running %s", name)
        result = run_cv(frame, feature_cols, target_col, factory, splitter,
                        split_name=split_name, truth_col=truth_col, **kwargs)
        result.model_name = name
        results[name] = result
    table = pd.DataFrame([r.summary_row() for r in results.values()])
    if "rmse" in table.columns:
        table = table.sort_values("rmse").reset_index(drop=True)
    return table, results


def compare_split_optimism(
    frame: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    model_factory: Callable[[], SoilMoistureModel],
    splitters: dict[str, Splitter],
    truth_col: str | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Score the same model under several split schemes.

    The gap between a random k-fold score and a leave-site-out score is the
    amount by which the random split is lying. Quantifying it on this specific
    corpus is worth doing once and quoting thereafter, because it is the single
    most common reason published soil moisture ML results do not reproduce in
    the field.
    """
    rows = []
    for name, splitter in splitters.items():
        result = run_cv(frame, feature_cols, target_col, model_factory, splitter,
                        split_name=name, truth_col=truth_col, **kwargs)
        row = {"split": name}
        row.update(result.overall)
        rows.append(row)
    table = pd.DataFrame(rows)
    if "rmse" in table.columns:
        table["optimism_vs_worst"] = (table["rmse"].max() - table["rmse"]).round(4)
    return table.sort_values("rmse").reset_index(drop=True)
