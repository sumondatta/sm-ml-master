"""Hyperparameter optimization with Optuna.

Three things distinguish this from a generic Optuna wrapper, and all three exist
because getting them wrong silently invalidates the result:

**The search is scored on the same kind of split the model will be judged by.**
Tuning against a random k-fold and then reporting a leave-site-out score means
the hyperparameters were chosen to exploit leakage. The inner objective here
uses a site-disjoint split by default.

**Nested cross-validation is available and is the honest option.** Choosing
hyperparameters on the same folds used to report performance biases that report
optimistically, because the search has seen the test data through the selection.
:func:`nested_cv` keeps an outer loop for reporting and runs a full independent
search inside each outer training fold. It costs roughly ``n_outer`` times more
and is the right thing to do for a number that goes in a paper.

**Pruning is fold-aware.** Trials report after each inner fold, so a
hopeless configuration is abandoned after one fold instead of five.

Studies are persisted to SQLite by default, so a search can be interrupted,
resumed, inspected mid-flight, and extended later without losing history.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..eval.metrics import compute_metrics
from ..eval.runner import Splitter
from ..eval.splits import leave_site_out
from ..models.base import SoilMoistureModel
from ..util.paths import artifacts_dir

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Search spaces
# --------------------------------------------------------------------------


def lightgbm_space(trial) -> dict[str, Any]:
    """LightGBM search space sized for tabular hydrology data.

    The ranges are deliberately wide on regularization and narrow on learning
    rate: with tens of millions of rows and heavily correlated features, the
    decisive choices are how much the trees are constrained and how much of the
    data each one sees, not the step size.
    """
    return {
        "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 511, log=True),
        "max_depth": trial.suggest_int("max_depth", 4, 16),
        "min_data_in_leaf": trial.suggest_int("min_data_in_leaf", 20, 2000, log=True),
        "feature_fraction": trial.suggest_float("feature_fraction", 0.3, 1.0),
        "bagging_fraction": trial.suggest_float("bagging_fraction", 0.4, 1.0),
        "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
        "lambda_l1": trial.suggest_float("lambda_l1", 1e-8, 10.0, log=True),
        "lambda_l2": trial.suggest_float("lambda_l2", 1e-8, 50.0, log=True),
        "min_gain_to_split": trial.suggest_float("min_gain_to_split", 0.0, 1.0),
        "max_bin": trial.suggest_categorical("max_bin", [127, 255, 511]),
        "cat_smooth": trial.suggest_float("cat_smooth", 1.0, 100.0, log=True),
    }


def xgboost_space(trial) -> dict[str, Any]:
    return {
        "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.2, log=True),
        "max_depth": trial.suggest_int("max_depth", 3, 14),
        "min_child_weight": trial.suggest_float("min_child_weight", 0.5, 200.0, log=True),
        "subsample": trial.suggest_float("subsample", 0.4, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
        "colsample_bylevel": trial.suggest_float("colsample_bylevel", 0.3, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 50.0, log=True),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "gamma": trial.suggest_float("gamma", 1e-8, 5.0, log=True),
        "max_bin": trial.suggest_categorical("max_bin", [128, 256, 512]),
    }


def ea_lstm_space(trial) -> dict[str, Any]:
    """EA-LSTM space. Sequence length is the expensive axis, so it is coarse."""
    return {
        "sequence_length": trial.suggest_categorical("sequence_length", [60, 120, 180, 270, 365]),
        "hidden_size": trial.suggest_categorical("hidden_size", [32, 64, 128, 256]),
        "head_hidden": trial.suggest_categorical("head_hidden", [32, 64, 128]),
        "dropout": trial.suggest_float("dropout", 0.0, 0.5),
        "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-2, log=True),
        "weight_decay": trial.suggest_float("weight_decay", 1e-7, 1e-3, log=True),
        "batch_size": trial.suggest_categorical("batch_size", [64, 128, 256, 512]),
    }


SEARCH_SPACES: dict[str, Callable[[Any], dict[str, Any]]] = {
    "lightgbm": lightgbm_space,
    "xgboost": xgboost_space,
    "ea_lstm": ea_lstm_space,
}


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


@dataclass
class TuningConfig:
    n_trials: int = 100
    timeout_s: float | None = None
    n_inner_folds: int = 3
    metric: str = "rmse"
    direction: str = "minimize"
    seed: int = 0
    study_name: str = "smml"
    storage: str | None = None
    pruner: str = "median"
    sampler: str = "tpe"
    n_startup_trials: int = 15
    #: Fraction of training sites held out inside each inner fold for early
    #: stopping. Site-disjoint, so early stopping cannot leak either.
    inner_validation_fraction: float = 0.15
    #: Optional second objective for multi-objective search.
    secondary_metric: str | None = None
    secondary_direction: str = "minimize"
    #: Subsample the training data during search. A search does not need every
    #: row to rank configurations, and the speedup buys more trials.
    search_sample_fraction: float = 1.0
    n_jobs: int = 1
    show_progress: bool = False
    extra_model_kwargs: dict[str, Any] = field(default_factory=dict)


def _make_sampler(optuna, cfg: TuningConfig):
    if cfg.sampler == "tpe":
        return optuna.samplers.TPESampler(
            seed=cfg.seed, n_startup_trials=cfg.n_startup_trials, multivariate=True, group=True
        )
    if cfg.sampler == "cmaes":
        return optuna.samplers.CmaEsSampler(seed=cfg.seed, n_startup_trials=cfg.n_startup_trials)
    if cfg.sampler == "random":
        return optuna.samplers.RandomSampler(seed=cfg.seed)
    if cfg.sampler == "nsga2":
        return optuna.samplers.NSGAIISampler(seed=cfg.seed)
    raise ValueError(f"unknown sampler {cfg.sampler!r}")


def _make_pruner(optuna, cfg: TuningConfig):
    if cfg.pruner == "median":
        return optuna.pruners.MedianPruner(n_startup_trials=cfg.n_startup_trials, n_warmup_steps=1)
    if cfg.pruner == "hyperband":
        return optuna.pruners.HyperbandPruner()
    if cfg.pruner == "successive_halving":
        return optuna.pruners.SuccessiveHalvingPruner()
    if cfg.pruner in (None, "none"):
        return optuna.pruners.NopPruner()
    raise ValueError(f"unknown pruner {cfg.pruner!r}")


# --------------------------------------------------------------------------
# The objective
# --------------------------------------------------------------------------


def _subsample_by_site(frame: pd.DataFrame, fraction: float, seed: int) -> pd.DataFrame:
    """Thin the data for the search by taking a fraction of *days*, keeping all sites.

    Dropping sites would change the difficulty of the task the search is tuning
    for. Dropping days within every site keeps the site diversity — which is what
    the hyperparameters have to cope with — while cutting the cost.
    """
    if fraction >= 1.0:
        return frame
    rng = np.random.default_rng(seed)
    keep = rng.random(len(frame)) < fraction
    return frame[keep]


def make_objective(
    frame: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    model_builder: Callable[[dict[str, Any]], SoilMoistureModel],
    space: Callable[[Any], dict[str, Any]],
    cfg: TuningConfig,
    splitter_factory: Callable[[pd.DataFrame, int], Iterator] | None = None,
    truth_col: str | None = None,
):
    """Build the Optuna objective: mean inner-fold score, with pruning."""
    import optuna

    def inner_splits(data: pd.DataFrame):
        if splitter_factory is not None:
            return splitter_factory(data, cfg.n_inner_folds)
        return leave_site_out(data, n_folds=cfg.n_inner_folds, seed=cfg.seed)

    def objective(trial):
        params = space(trial)
        data = _subsample_by_site(frame, cfg.search_sample_fraction, cfg.seed)
        scores: list[float] = []
        secondary: list[float] = []

        for step, (train_idx, test_idx) in enumerate(inner_splits(data)):
            train = data.iloc[train_idx]
            test = data.iloc[test_idx]

            validation = None
            if cfg.inner_validation_fraction > 0 and "site_id" in train.columns:
                sites = pd.unique(train["site_id"])
                rng = np.random.default_rng(cfg.seed + step)
                n_val = max(1, int(len(sites) * cfg.inner_validation_fraction))
                val_sites = set(rng.choice(sites, size=min(n_val, len(sites) - 1), replace=False))
                mask = train["site_id"].isin(val_sites)
                validation, train = train[mask], train[~mask]

            model = model_builder({**params, **cfg.extra_model_kwargs})
            model.fit(train, feature_cols, target_col, validation=validation)
            pred = model.predict(test, feature_cols)

            score_col = truth_col if (truth_col and truth_col in test.columns) else target_col
            metrics = compute_metrics(test[score_col], pred)
            value = metrics.get(cfg.metric, float("nan"))
            if not np.isfinite(value):
                raise optuna.TrialPruned(f"non-finite {cfg.metric}")
            scores.append(value)
            if cfg.secondary_metric:
                secondary.append(metrics.get(cfg.secondary_metric, float("nan")))

            # Report the running mean so the pruner can compare like with like.
            trial.report(float(np.mean(scores)), step)
            if trial.should_prune():
                raise optuna.TrialPruned()

        trial.set_user_attr("fold_scores", scores)
        primary = float(np.mean(scores))
        if cfg.secondary_metric:
            return primary, float(np.mean(secondary))
        return primary

    return objective


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


@dataclass
class TuningResult:
    study: Any
    best_params: dict[str, Any]
    best_value: float | tuple[float, ...]
    trials: pd.DataFrame
    param_importance: pd.DataFrame | None
    config: TuningConfig

    def __str__(self) -> str:
        return (
            f"best {self.config.metric}={self.best_value} "
            f"over {len(self.trials)} trials\n"
            + "\n".join(f"  {k}: {v}" for k, v in self.best_params.items())
        )


def tune(
    frame: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    model_builder: Callable[[dict[str, Any]], SoilMoistureModel],
    space: Callable[[Any], dict[str, Any]] | str = "lightgbm",
    cfg: TuningConfig | None = None,
    splitter_factory: Callable[[pd.DataFrame, int], Iterator] | None = None,
    truth_col: str | None = None,
) -> TuningResult:
    """Run a hyperparameter search and return the best configuration.

    The study is persisted (SQLite under ``artifacts/``) unless ``cfg.storage``
    says otherwise, so an interrupted search resumes where it stopped and a
    finished one can be extended by calling again with the same ``study_name``.
    """
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    cfg = cfg or TuningConfig()
    if isinstance(space, str):
        if space not in SEARCH_SPACES:
            raise KeyError(f"unknown space {space!r}; known: {sorted(SEARCH_SPACES)}")
        space = SEARCH_SPACES[space]

    storage = cfg.storage
    if storage is None:
        db = artifacts_dir() / "optuna"
        db.mkdir(parents=True, exist_ok=True)
        storage = f"sqlite:///{db / (cfg.study_name + '.db')}"

    directions = None
    direction = cfg.direction
    if cfg.secondary_metric:
        directions = [cfg.direction, cfg.secondary_direction]
        direction = None

    study = optuna.create_study(
        study_name=cfg.study_name,
        storage=storage,
        load_if_exists=True,
        direction=direction,
        directions=directions,
        sampler=_make_sampler(optuna, cfg),
        pruner=_make_pruner(optuna, cfg),
    )

    objective = make_objective(frame, feature_cols, target_col, model_builder, space, cfg,
                               splitter_factory=splitter_factory, truth_col=truth_col)
    study.optimize(objective, n_trials=cfg.n_trials, timeout=cfg.timeout_s,
                   n_jobs=cfg.n_jobs, show_progress_bar=cfg.show_progress,
                   catch=(ValueError, RuntimeError))

    trials = study.trials_dataframe()
    importance = None
    if not cfg.secondary_metric:
        try:
            raw = optuna.importance.get_param_importances(study)
            importance = pd.DataFrame(
                {"param": list(raw), "importance": list(raw.values())}
            ).sort_values("importance", ascending=False).reset_index(drop=True)
        except (ValueError, RuntimeError) as exc:
            log.debug("parameter importance unavailable: %s", exc)

    if cfg.secondary_metric:
        best = study.best_trials[0]
        best_params, best_value = best.params, tuple(best.values)
    else:
        best_params, best_value = study.best_params, study.best_value

    return TuningResult(study, best_params, best_value, trials, importance, cfg)


def nested_cv(
    frame: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    model_builder: Callable[[dict[str, Any]], SoilMoistureModel],
    outer_splitter: Splitter,
    space: Callable[[Any], dict[str, Any]] | str = "lightgbm",
    cfg: TuningConfig | None = None,
    truth_col: str | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], np.ndarray]:
    """Nested cross-validation: an independent search inside every outer fold.

    Returns ``(per_fold_metrics, per_fold_best_params, out_of_fold_predictions)``.

    This is the only way to get a performance estimate that is not biased by
    hyperparameter selection. It is expensive — ``n_outer`` complete searches —
    so the usual practice is a single search for development and one nested run
    for the number that gets published.
    """
    cfg = cfg or TuningConfig()
    frame = frame.reset_index(drop=True)
    oof = np.full(len(frame), np.nan)
    rows, chosen = [], []

    for fold, (train_idx, test_idx) in enumerate(outer_splitter(frame)):
        train = frame.iloc[train_idx]
        test = frame.iloc[test_idx]
        log.info("nested fold %d: searching on %d rows", fold, len(train))

        fold_cfg = TuningConfig(**{**vars(cfg), "study_name": f"{cfg.study_name}_outer{fold}",
                                   "seed": cfg.seed + fold})
        result = tune(train, feature_cols, target_col, model_builder, space, fold_cfg,
                      truth_col=truth_col)

        model = model_builder({**result.best_params, **cfg.extra_model_kwargs})
        model.fit(train, feature_cols, target_col)
        pred = np.asarray(model.predict(test, feature_cols), dtype=float)
        oof[test_idx] = pred

        score_col = truth_col if (truth_col and truth_col in test.columns) else target_col
        metrics = compute_metrics(test[score_col], pred)
        metrics["fold"] = fold
        metrics["n_trials"] = len(result.trials)
        rows.append(metrics)
        chosen.append(result.best_params)

    return pd.DataFrame(rows), chosen, oof


def save_best_params(result: TuningResult, path: Path | str | None = None) -> Path:
    """Write the chosen configuration to YAML for reuse and for the record."""
    import yaml

    path = Path(path) if path else artifacts_dir() / f"{result.config.study_name}_best.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "study_name": result.config.study_name,
        "metric": result.config.metric,
        "best_value": result.best_value,
        "n_trials": len(result.trials),
        "params": result.best_params,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return path
