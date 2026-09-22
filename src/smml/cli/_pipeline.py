"""Pipeline stages behind the CLI.

Kept out of ``main.py`` so the command definitions stay readable and so the
stages can be called directly from a notebook or a script without going through
Typer.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def load_corpus(data: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load observations and sites from a directory of parquet files."""
    candidates = [
        ("synthetic_observations.parquet", "synthetic_sites.parquet"),
        ("observations.parquet", "sites.parquet"),
    ]
    for obs_name, site_name in candidates:
        obs_path, site_path = data / obs_name, data / site_name
        if obs_path.exists() and site_path.exists():
            return pd.read_parquet(obs_path), pd.read_parquet(site_path)
    raise FileNotFoundError(
        f"no corpus in {data}. Run `smml simulate` first, or point --data at a "
        "directory containing observations.parquet and sites.parquet."
    )


CLAY_CORRECTED_TARGET = "theta_clay_corrected_m3m3"


def resolve_target(frame: pd.DataFrame, target: str, use_clay_correction: bool) -> str:
    """Which column to actually train on.

    Separated out and used by every stage so that the correction cannot be
    computed and then silently ignored, which is what happened the first time:
    the corrected column was written and the models were still fitted on the raw
    reading, leaving the -0.034 bias the correction exists to remove.
    """
    if use_clay_correction and CLAY_CORRECTED_TARGET in frame.columns:
        if frame[CLAY_CORRECTED_TARGET].notna().any():
            return CLAY_CORRECTED_TARGET
        log.warning("clay-corrected target is entirely missing; falling back to %s", target)
    return target


def build_modelling_table(
    data: Path,
    target: str = "theta_obs_m3m3",
    drop_warmup_days: int = 365,
    apply_clay_correction: bool = True,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Assemble features and return ``(frame, feature_cols, categorical_cols)``.

    Two steps here are decisions rather than mechanics.

    The first year is discarded. Rolling features span up to 365 days, so before
    that they are partly undefined, and training on rows whose features are
    half-formed teaches the model a relationship that does not exist.

    The clay correction is applied to the target by default. A dielectric sensor
    in a fine-textured soil reads low because bound water is nearly invisible to
    it, and a model trained on the uncorrected reading learns to reproduce that
    bias: measured against true water content it came out 0.042 m3/m3 low, and
    correcting first removed the bias and cut RMSE by 30 %. The corrected value
    is written to its own column; the original is never overwritten.
    """
    from ..features.build import build_features
    from ..physics.dielectric import correct_for_clay

    observations, sites = load_corpus(data)
    observations = observations.copy()
    observations["date"] = pd.to_datetime(observations["date"])

    if apply_clay_correction and "clay_pct" in sites.columns:
        merged = observations.merge(sites[["site_id", "clay_pct"]], on="site_id", how="left")
        porosity = (
            merged["layer_porosity_m3m3"]
            if "layer_porosity_m3m3" in merged
            else merged.get("porosity_m3m3", pd.Series(0.45, index=merged.index))
        )
        corrected = correct_for_clay(
            merged[target].to_numpy(dtype=float),
            merged["clay_pct"].to_numpy(dtype=float),
            porosity.to_numpy(dtype=float),
        )
        observations["theta_clay_corrected_m3m3"] = pd.Series(
            corrected, index=merged.index
        ).fillna(merged[target])

    frame, features, categorical = build_features(observations, sites, target=target)
    frame["date"] = pd.to_datetime(frame["date"])

    extra = [c for c in ("theta_clay_corrected_m3m3",) if c in observations.columns]
    if extra:
        keys = ["site_id", "date", "depth_top_cm"]
        frame = frame.merge(observations[keys + extra], on=keys, how="left")

    if drop_warmup_days:
        cutoff = frame["date"].min() + pd.Timedelta(days=drop_warmup_days)
        frame = frame[frame["date"] >= cutoff].reset_index(drop=True)

    return frame, features, categorical


def _model_factory(name: str, params: dict | None = None):
    from ..models.baselines import BASELINES
    from ..models.gbdt import LightGBMModel, XGBoostModel
    from ..models.sequence import EALSTMConfig, EALSTMModel

    params = params or {}
    if name == "lightgbm":
        return lambda: LightGBMModel(params=params, num_boost_round=params.pop("n_estimators", 800))
    if name == "lightgbm_mono":
        return lambda: LightGBMModel(params=params, num_boost_round=800, monotone=True)
    if name == "xgboost":
        return lambda: XGBoostModel(params=params, num_boost_round=800)
    if name == "ea_lstm":
        return lambda: EALSTMModel(config=EALSTMConfig(**params))
    if name in BASELINES:
        return BASELINES[name]
    raise KeyError(f"unknown model {name!r}")


def run_training(
    data: Path,
    model: str,
    split: str,
    folds: int,
    target: str,
    truth: str,
    out: Path | None,
    console,
    use_clay_correction: bool = True,
):
    """Cross-validate one model and print stratified metrics."""
    from ..eval.runner import run_cv
    from ..eval.splits import get_splitter
    from ..util.paths import artifacts_dir

    frame, features, _ = build_modelling_table(data, target=target)
    target = resolve_target(frame, target, use_clay_correction)
    console.print(f"[dim]{len(frame):,} rows, {frame.site_id.nunique()} sites, "
                  f"{len(features)} features, target={target}[/dim]")

    kwargs = {"n_folds": folds} if split != "forward_chaining" else {"n_splits": folds,
                                                                     "gap_days": 365}
    splitter = get_splitter(split, **kwargs)
    result = run_cv(
        frame, features, target, _model_factory(model), splitter, split_name=split,
        truth_col=truth if truth in frame.columns else None,
        inner_validation_fraction=0.15, verbose=False,
    )

    _report(result, console)
    destination = Path(out) if out else artifacts_dir()
    destination.mkdir(parents=True, exist_ok=True)
    result.oof.to_parquet(destination / f"oof_{model}_{split}.parquet", index=False)
    console.print(f"[dim]out-of-fold predictions: "
                  f"{destination / f'oof_{model}_{split}.parquet'}[/dim]")
    return result


def _report(result, console) -> None:
    from rich.table import Table

    overall = Table(title=f"{result.model_name} / {result.split_name}", header_style="bold")
    for name in ("RMSE", "ubRMSE", "bias", "r", "R2", "KGE", "r_between", "r_within", "n"):
        overall.add_column(name, justify="right")
    overall.add_row(
        f"{result.overall['rmse']:.4f}", f"{result.overall['ubrmse']:.4f}",
        f"{result.overall['bias']:+.4f}", f"{result.overall['r']:.3f}",
        f"{result.overall['r2']:+.3f}", f"{result.overall['kge']:+.3f}",
        f"{result.skill.get('r_between', float('nan')):.3f}",
        f"{result.skill.get('r_within', float('nan')):.3f}",
        f"{result.overall['n']:,}",
    )
    console.print(overall)

    for frame, title in (
        (result.by_depth, "by depth"),
        (result.by_texture, "by texture"),
        (result.by_salinity, "by salinity"),
    ):
        if frame is None or frame.empty:
            continue
        table = Table(title=title, header_style="bold")
        columns = [c for c in frame.columns if c in
                   (frame.columns[0], "rmse", "ubrmse", "bias", "r", "n")]
        for column in columns:
            table.add_column(str(column), justify="right")
        for _, row in frame.iterrows():
            table.add_row(*[f"{row[c]:.4f}" if isinstance(row[c], float) else str(row[c])
                            for c in columns])
        console.print(table)

    if result.importance is not None and not result.importance.empty:
        table = Table(title="top features by gain", header_style="bold")
        table.add_column("feature")
        table.add_column("gain", justify="right")
        for _, row in result.importance.head(15).iterrows():
            table.add_row(str(row["feature"]), f"{row['gain']:,.0f}")
        console.print(table)


def run_tuning(
    data: Path,
    model: str,
    trials: int,
    inner_folds: int,
    metric: str,
    study: str,
    sample: float,
    console,
):
    """Hyperparameter search, then report the best configuration."""
    from ..models.gbdt import LightGBMModel, XGBoostModel
    from ..tune.search import TuningConfig, save_best_params, tune

    frame, features, _ = build_modelling_table(data)
    target = resolve_target(frame, "theta_obs_m3m3", use_clay_correction=True)
    console.print(f"[dim]{len(frame):,} rows, {frame.site_id.nunique()} sites, "
                  f"target={target}[/dim]")

    builders = {
        "lightgbm": lambda params: LightGBMModel(params=params, num_boost_round=600),
        "xgboost": lambda params: XGBoostModel(params=params, num_boost_round=600),
    }
    if model not in builders:
        raise KeyError(f"tuning supports {sorted(builders)}; got {model!r}")

    config = TuningConfig(
        n_trials=trials, n_inner_folds=inner_folds, metric=metric,
        study_name=f"{study}_{model}", search_sample_fraction=sample,
    )
    truth = "theta_true_m3m3" if "theta_true_m3m3" in frame.columns else None
    result = tune(frame, features, target, builders[model], model, config,
                  truth_col=truth)

    console.print(f"\n[bold green]best {metric} = {result.best_value:.5f}[/bold green]")
    from rich.table import Table

    table = Table(title="best hyperparameters", header_style="bold")
    table.add_column("parameter")
    table.add_column("value", justify="right")
    for key, value in result.best_params.items():
        table.add_row(key, f"{value:.5g}" if isinstance(value, float) else str(value))
    console.print(table)

    if result.param_importance is not None and not result.param_importance.empty:
        table = Table(title="which parameters mattered", header_style="bold")
        table.add_column("parameter")
        table.add_column("importance", justify="right")
        for _, row in result.param_importance.iterrows():
            table.add_row(str(row["param"]), f"{row['importance']:.3f}")
        console.print(table)

    path = save_best_params(result)
    console.print(f"[dim]saved: {path}[/dim]")
    return result


def run_evaluation(data: Path, split: str, folds: int, include_optimism: bool, console,
                   use_clay_correction: bool = True):
    """Every model against every baseline on identical folds."""
    from rich.table import Table

    from ..eval.runner import compare_models, compare_split_optimism
    from ..eval.splits import get_splitter
    from ..models.baselines import (
        BucketBaseline,
        DepthClimatologyBaseline,
        FieldCapacityBaseline,
        GlobalMeanBaseline,
    )
    from ..models.gbdt import LightGBMModel

    frame, features, _ = build_modelling_table(data)
    truth = "theta_true_m3m3" if "theta_true_m3m3" in frame.columns else None
    target = resolve_target(frame, "theta_obs_m3m3", use_clay_correction)
    console.print(f"[dim]{len(frame):,} rows, {frame.site_id.nunique()} sites, "
                  f"target={target}[/dim]")

    factories = {
        "global_mean": GlobalMeanBaseline,
        "depth_climatology": DepthClimatologyBaseline,
        "field_capacity": FieldCapacityBaseline,
        "bucket": BucketBaseline,
        "lightgbm": lambda: LightGBMModel(num_boost_round=600,
                                          params={"learning_rate": 0.06, "num_leaves": 95}),
    }
    splitter = get_splitter(split, n_folds=folds)
    table, results = compare_models(
        frame, features, target, factories, splitter,
        split_name=split, truth_col=truth, inner_validation_fraction=0.15, verbose=False,
    )

    display = Table(title=f"models under {split}", header_style="bold")
    for column in ("model", "rmse", "ubrmse", "bias", "r", "kge", "r_between", "r_within"):
        display.add_column(column, justify="right")
    for _, row in table.iterrows():
        display.add_row(
            str(row["model"]), f"{row['rmse']:.4f}", f"{row['ubrmse']:.4f}",
            f"{row['bias']:+.4f}", f"{row['r']:.3f}", f"{row['kge']:+.3f}",
            f"{row.get('r_between', float('nan')):.3f}",
            f"{row.get('r_within', float('nan')):.3f}",
        )
    console.print(display)
    console.print(
        "[dim]r_between is skill at ranking sites; r_within is skill at tracking a field "
        "over time. A static baseline can score well on the first and zero on the "
        "second.[/dim]"
    )

    if include_optimism:
        splitters = {
            "leave_site_out": get_splitter("leave_site_out", n_folds=folds),
            "spatial_block": get_splitter("spatial_block", n_folds=folds),
            "random_kfold_DO_NOT_USE": get_splitter("random_kfold_DO_NOT_USE", n_folds=folds),
        }
        optimism = compare_split_optimism(
            frame, features, target,
            lambda: LightGBMModel(num_boost_round=400), splitters, truth_col=truth,
        )
        display = Table(title="how much each split flatters the model", header_style="bold")
        for column in ("split", "rmse", "r", "r2"):
            display.add_column(column, justify="right")
        for _, row in optimism.iterrows():
            display.add_row(str(row["split"]), f"{row['rmse']:.4f}",
                            f"{row['r']:.3f}", f"{row['r2']:+.3f}")
        console.print(display)
        console.print(
            "[dim]The gap between random k-fold and leave-site-out is the amount by "
            "which a random split overstates what the model can do at a new field."
            "[/dim]"
        )
    return table, results
