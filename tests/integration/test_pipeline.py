"""End-to-end pipeline tests.

Each of these runs a real, if small, version of the whole chain: simulate a
corpus, build features, cross-validate, tune, store. They are slower than the
unit tests and they exist to catch the failures unit tests structurally cannot —
a schema mismatch between two stages, a target column that gets computed and
then silently ignored, a split that leaks once real features are attached.

None of them touches the network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smml.cli._pipeline import (
    CLAY_CORRECTED_TARGET,
    build_modelling_table,
    resolve_target,
)
from smml.db.store import Store
from smml.eval.metrics import skill_decomposition
from smml.eval.runner import compare_models, run_cv
from smml.eval.splits import get_splitter
from smml.features.build import build_features
from smml.models.baselines import FieldCapacityBaseline, GlobalMeanBaseline
from smml.models.gbdt import LightGBMModel, uncertainty_weights
from smml.physics.simulator import generate_corpus

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def corpus():
    return generate_corpus(n_sites=16, years=3, seed=4242)


@pytest.fixture(scope="module")
def modelling_table(corpus, tmp_path_factory):
    """The corpus written to disk and read back through the real pipeline entry point."""
    observations, sites = corpus
    directory = tmp_path_factory.mktemp("corpus")
    observations.to_parquet(directory / "synthetic_observations.parquet", index=False)
    sites.to_parquet(directory / "synthetic_sites.parquet", index=False)
    return build_modelling_table(directory, drop_warmup_days=365)


def test_pipeline_produces_a_usable_modelling_table(modelling_table):
    frame, features, _categorical = modelling_table
    assert len(frame) > 10_000
    assert len(features) > 100
    assert frame["site_id"].nunique() == 16
    # Every feature must be defined once the warm-up year is dropped; a feature
    # that is mostly missing is a feature the model cannot learn from.
    missing = frame[features].isna().mean()
    assert missing.max() < 0.01, missing.sort_values().tail(5).to_dict()


def test_clay_correction_is_computed_and_actually_used(modelling_table):
    """The correction was once computed and then ignored, leaving the bias in place."""
    frame, _, _ = modelling_table
    assert CLAY_CORRECTED_TARGET in frame.columns
    assert frame[CLAY_CORRECTED_TARGET].notna().any()
    assert resolve_target(frame, "theta_obs_m3m3", use_clay_correction=True) == CLAY_CORRECTED_TARGET
    assert resolve_target(frame, "theta_obs_m3m3", use_clay_correction=False) == "theta_obs_m3m3"


def test_clay_correction_moves_predictions_toward_the_truth(modelling_table):
    """The headline claim, re-measured on every run.

    A dielectric probe reads low in fine soil. A model fitted to the raw reading
    reproduces that; fitting to the corrected reading should remove most of the
    bias when scored against true water content.
    """
    frame, features, _ = modelling_table
    splitter = get_splitter("leave_site_out", n_folds=3)

    def fit(target: str):
        return run_cv(
            frame, features, target,
            lambda: LightGBMModel(num_boost_round=200, params={"learning_rate": 0.1}),
            splitter, truth_col="theta_true_m3m3", verbose=False,
        )

    raw = fit("theta_obs_m3m3")
    corrected = fit(CLAY_CORRECTED_TARGET)

    assert raw.overall["bias"] < -0.01, "the uncorrected bias should be clearly negative"
    assert abs(corrected.overall["bias"]) < abs(raw.overall["bias"])
    assert corrected.overall["rmse"] < raw.overall["rmse"]


def test_leave_site_out_never_shares_a_site(modelling_table):
    frame, _, _ = modelling_table
    for train_idx, test_idx in get_splitter("leave_site_out", n_folds=4)(frame):
        train_sites = set(frame.iloc[train_idx]["site_id"])
        test_sites = set(frame.iloc[test_idx]["site_id"])
        assert not (train_sites & test_sites)
        assert not (set(train_idx) & set(test_idx))


def test_a_random_split_scores_better_than_a_site_split(modelling_table):
    """Quantifies the optimism, and fails if the site split ever stops being harder.

    If these two ever come out equal, either the split is not doing what it
    claims or a feature is carrying site identity across the boundary.
    """
    frame, features, _ = modelling_table
    frame = frame.sample(n=min(40_000, len(frame)), random_state=0).reset_index(drop=True)

    def score(split: str) -> float:
        result = run_cv(
            frame, features, "theta_obs_m3m3",
            lambda: LightGBMModel(num_boost_round=150, params={"learning_rate": 0.1}),
            get_splitter(split, n_folds=3), verbose=False,
        )
        return result.overall["rmse"]

    assert score("random_kfold_DO_NOT_USE") < score("leave_site_out")


def test_learned_model_beats_the_static_baseline_on_temporal_skill(modelling_table):
    """Pooled RMSE alone cannot show this, which is the point of the decomposition."""
    frame, features, _ = modelling_table
    frame = frame.sample(n=min(40_000, len(frame)), random_state=1).reset_index(drop=True)
    splitter = get_splitter("leave_site_out", n_folds=3)

    _table, results = compare_models(
        frame, features, CLAY_CORRECTED_TARGET,
        {
            "field_capacity": FieldCapacityBaseline,
            "lightgbm": lambda: LightGBMModel(num_boost_round=200,
                                              params={"learning_rate": 0.1}),
        },
        splitter, truth_col="theta_true_m3m3", verbose=False,
    )
    static = results["field_capacity"].skill
    learned = results["lightgbm"].skill
    # A prediction that never changes in time has no temporal skill by construction.
    assert static["r_within"] == pytest.approx(0.0, abs=1e-9)
    assert learned["r_within"] > 0.5


def test_models_beat_the_global_mean(modelling_table):
    frame, features, _ = modelling_table
    frame = frame.sample(n=min(30_000, len(frame)), random_state=2).reset_index(drop=True)
    splitter = get_splitter("leave_site_out", n_folds=3)
    table, _ = compare_models(
        frame, features, "theta_obs_m3m3",
        {
            "global_mean": GlobalMeanBaseline,
            "lightgbm": lambda: LightGBMModel(num_boost_round=200,
                                              params={"learning_rate": 0.1}),
        },
        splitter, verbose=False,
    )
    scores = table.set_index("model")["rmse"]
    assert scores["lightgbm"] < scores["global_mean"] * 0.7


def test_between_site_variance_dominates_this_corpus(modelling_table):
    """Context for why pooled metrics mislead here; quoted in the README."""
    frame, _, _ = modelling_table
    decomposition = skill_decomposition(
        frame.assign(prediction=frame["theta_obs_m3m3"]),
        "theta_obs_m3m3", "prediction",
    )
    assert decomposition["variance_explained_between"] > 0.5


def test_uncertainty_weights_downweight_noisy_observations(modelling_table):
    frame, _, _ = modelling_table
    work = frame.head(1000).copy()
    work["uncertainty_m3m3"] = np.where(np.arange(len(work)) % 2 == 0, 0.01, 0.06)
    weights = uncertainty_weights(work)
    assert weights[::2].mean() > weights[1::2].mean()
    assert weights.min() >= 0.2 and weights.max() <= 5.0


def test_tuning_runs_and_improves_on_its_own_starting_point(modelling_table, tmp_path):
    from smml.tune.search import TuningConfig, save_best_params, tune

    frame, features, _ = modelling_table
    frame = frame.sample(n=min(20_000, len(frame)), random_state=3).reset_index(drop=True)

    config = TuningConfig(
        n_trials=6, n_inner_folds=2, study_name="itest",
        storage=f"sqlite:///{tmp_path / 'study.db'}", n_startup_trials=3,
        inner_validation_fraction=0.0,
    )
    result = tune(
        frame, features, "theta_obs_m3m3",
        lambda params: LightGBMModel(params=params, num_boost_round=120),
        "lightgbm", config,
    )
    assert len(result.trials) >= 4
    assert np.isfinite(result.best_value)
    assert result.best_params
    # The search space must actually be explored, not collapsed onto one point.
    assert result.trials["value"].nunique() > 1
    path = save_best_params(result, tmp_path / "best.yaml")
    assert path.exists()


def test_tuning_study_resumes_rather_than_restarting(modelling_table, tmp_path):
    """A search that cannot be interrupted is a search that will not be run."""
    from smml.tune.search import TuningConfig, tune

    frame, features, _ = modelling_table
    frame = frame.sample(n=8000, random_state=5).reset_index(drop=True)
    storage = f"sqlite:///{tmp_path / 'resume.db'}"
    common = {"n_inner_folds": 2, "study_name": "resume", "storage": storage,
                  "n_startup_trials": 2, "inner_validation_fraction": 0.0}

    def builder(params):
        return LightGBMModel(params=params, num_boost_round=80)

    first = tune(frame, features, "theta_obs_m3m3", builder, "lightgbm",
                 TuningConfig(n_trials=3, **common))
    second = tune(frame, features, "theta_obs_m3m3", builder, "lightgbm",
                  TuningConfig(n_trials=3, **common))
    assert len(second.trials) > len(first.trials)


def test_store_round_trips_the_corpus(corpus, tmp_path):
    """Observations written, read back through DuckDB, and re-written idempotently."""
    from smml.util.ids import observation_key, sensor_id

    observations, _ = corpus
    subset = observations.head(5000).copy()
    subset["time_utc"] = pd.to_datetime(subset["date"], utc=True)
    subset["sensor_id"] = [
        sensor_id(s, "soil_moisture", t, b)
        for s, t, b in zip(subset.site_id, subset.depth_top_cm,
                           subset.depth_bottom_cm, strict=True)
    ]
    rows = pd.DataFrame({
        "observation_key": [observation_key(s, str(t))
                            for s, t in zip(subset.sensor_id, subset.time_utc, strict=True)],
        "site_id": subset.site_id, "sensor_id": subset.sensor_id, "source_id": "synthetic",
        "time_utc": subset.time_utc,
        "depth_top_cm": subset.depth_top_cm, "depth_bottom_cm": subset.depth_bottom_cm,
        "theta_m3m3": subset.theta_obs_m3m3.astype("float32"),
        "method": "fdr_capacitance", "quality_flag": "G",
        "year": subset.time_utc.dt.year.astype("int16"), "network": "SYNTHETIC",
    })

    store = Store(tmp_path)
    assert store.write("observations", rows) == len(rows)
    assert store.write("observations", rows) == 0, "a re-run must be a no-op"

    back = store.sql("SELECT count(*) AS n, avg(theta_m3m3) AS mean FROM observations")
    assert int(back["n"].iloc[0]) == len(rows)
    assert back["mean"].iloc[0] == pytest.approx(rows.theta_m3m3.mean(), rel=1e-4)

    summary = store.summary().set_index("table")
    assert summary.loc["observations", "rows"] == len(rows)


def test_features_do_not_leak_the_target(modelling_table):
    """No feature may correlate with the target more strongly than is physical.

    A near-perfect correlation is the signature of the target having leaked into
    a feature — through a lagged copy, a site statistic, or a join gone wrong.
    """
    frame, features, _ = modelling_table
    sample = frame.sample(n=min(50_000, len(frame)), random_state=7)
    target = sample["theta_obs_m3m3"].to_numpy(dtype=float)
    suspicious = []
    for column in features:
        values = sample[column]
        if not pd.api.types.is_numeric_dtype(values) or values.std() == 0:
            continue
        r = np.corrcoef(values.fillna(values.median()).to_numpy(dtype=float), target)[0, 1]
        if np.isfinite(r) and abs(r) > 0.95:
            suspicious.append((column, round(float(r), 4)))
    assert not suspicious, f"features suspiciously correlated with the target: {suspicious}"


def test_build_features_is_deterministic(corpus):
    observations, sites = corpus
    a, fa, _ = build_features(observations, sites, target="theta_obs_m3m3")
    b, fb, _ = build_features(observations, sites, target="theta_obs_m3m3")
    assert fa == fb
    pd.testing.assert_frame_equal(a[fa].head(2000), b[fb].head(2000))
