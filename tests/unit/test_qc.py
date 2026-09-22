"""Quality control tests.

Detectors are tested by construction: build a series containing a known fault,
assert it is found, and — at least as important — build a series containing only
*legitimate* behaviour and assert it is not. The second half is what keeps the
checks usable, since a detector that fires on ordinary seasonal drying makes the
flag worthless.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smml.db.schema import QualityFlag
from smml.physics.simulator import generate_corpus
from smml.qc.checks import (
    HARD_MAX,
    detect_cross_depth_inconsistency,
    detect_drift,
    detect_flatline,
    detect_frozen,
    detect_rise_without_input,
    detect_spikes,
    detect_step_change,
    flag_clay_suspect,
    flag_physical_range,
    flag_salinity_suspect,
    infer_irrigation_events,
    qc_summary,
    run_qc,
)

def clean_series(n: int = 600, noise: float = 0.004, seed: int = 0) -> pd.Series:
    """A well-behaved series with a deliberately fast 60-day oscillation.

    Each call seeds its own generator. A module-level generator would make every
    test depend on which tests ran before it, which is exactly how a detector
    regression can pass in one ordering and fail in another.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(float(n))
    return pd.Series(0.25 + 0.06 * np.sin(2 * np.pi * t / 60) + noise * rng.standard_normal(n))


# --------------------------------------------------------------------------
# Range
# --------------------------------------------------------------------------


def test_flag_physical_range_marks_impossible_values():
    theta = pd.Series([-0.1, 0.0, 0.25, 0.9, np.nan])
    flags = flag_physical_range(theta)
    assert flags.iloc[0] == QualityFlag.OUT_OF_PHYSICAL_RANGE.value
    assert flags.iloc[1] == QualityFlag.GOOD.value
    assert flags.iloc[2] == QualityFlag.GOOD.value
    assert flags.iloc[3] == QualityFlag.OUT_OF_PHYSICAL_RANGE.value
    assert flags.iloc[4] == QualityFlag.MISSING.value


def test_flag_physical_range_allows_slight_oversaturation():
    """Real profiles read a little above a pedotransfer porosity; that is not a fault."""
    theta = pd.Series([0.46, 0.55])
    flags = flag_physical_range(theta, porosity=0.45, tolerance=0.03)
    assert flags.iloc[0] == QualityFlag.GOOD.value
    assert flags.iloc[1] == QualityFlag.EXCEEDS_SATURATION.value


def test_hard_max_is_below_any_real_porosity_ceiling():
    assert 0.6 < HARD_MAX < 1.0


# --------------------------------------------------------------------------
# Spikes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("amplitude", [0.10, 0.15, 0.22])
def test_spikes_above_the_absolute_floor_are_always_found(amplitude):
    series = clean_series()
    idx = np.arange(30, 570, 37)
    series.iloc[idx] += amplitude
    detected = detect_spikes(series)
    assert detected.iloc[idx].all()


def test_spike_detector_does_not_fire_on_clean_data():
    assert detect_spikes(clean_series()).mean() < 0.005


def test_spike_detector_handles_several_spikes_in_one_window():
    series = clean_series()
    for i in (100, 103, 106):
        series.iloc[i] += 0.15
    assert detect_spikes(series).iloc[[100, 103, 106]].all()


# --------------------------------------------------------------------------
# Flatline
# --------------------------------------------------------------------------


def test_flatline_detects_a_stuck_sensor():
    series = clean_series()
    series.iloc[200:260] = float(series.iloc[200])
    detected = detect_flatline(series, min_length=12)
    assert detected.iloc[210:255].all()


def test_flatline_ignores_a_varying_series():
    assert not detect_flatline(clean_series()).any()


# --------------------------------------------------------------------------
# Step change — the detector that had to be rewritten
# --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_step_change_finds_a_genuine_discontinuity(seed):
    series = clean_series(seed=seed)
    series.iloc[300:] += 0.09
    detected = detect_step_change(series)
    assert detected.any(), "a sustained 0.09 level shift must be found"
    assert [int(i) for i in np.where(detected)[0]] == [300]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_step_change_ignores_a_seasonal_swing(seed):
    """A soil drying through a season moves far more than the shift threshold.

    Requiring only that the before/after means differ flagged 11 % of a whole
    corpus, which is why the abruptness condition exists.
    """
    t = np.arange(600.0)
    rng = np.random.default_rng(seed)
    seasonal = pd.Series(0.25 + 0.10 * np.sin(2 * np.pi * t / 365) + 0.004 * rng.standard_normal(600))
    assert detect_step_change(seasonal).mean() < 0.005


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_step_change_ignores_a_fast_drydown(seed):
    """0.35 to 0.12 over four months is ordinary drying, not an instrument fault."""
    dry = pd.Series(
        np.concatenate([np.full(100, 0.35), np.linspace(0.35, 0.12, 120), np.full(380, 0.12)])
        + 0.003 * np.random.default_rng(seed).standard_normal(600)
    )
    assert detect_step_change(dry).mean() < 0.005


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_step_change_does_not_confuse_a_spike_for_a_step(seed):
    """A spike is an opposing pair of excesses; neither half is a step."""
    series = clean_series(seed=seed)
    series.iloc[300] += 0.20
    assert not detect_step_change(series).any()


# --------------------------------------------------------------------------
# Frozen, drift, cross-depth
# --------------------------------------------------------------------------


def test_frozen_uses_soil_temperature_when_available():
    soil = pd.Series([-3.0, -0.2, 0.4, 5.0, np.nan])
    detected = detect_frozen(soil)
    assert list(detected) == [True, True, True, False, False]


def test_frozen_falls_back_to_a_colder_air_threshold():
    air = pd.Series([-5.0, -1.0, 10.0])
    detected = detect_frozen(None, air)
    assert list(detected) == [True, False, False]


def test_drift_detects_a_degrading_probe():
    n = 1200
    dates = pd.Series(pd.date_range("2018-01-01", periods=n, freq="D"))
    drifting = pd.Series(0.25 + np.linspace(0, 0.25, n) + 0.004 * np.random.default_rng(1).standard_normal(n))
    stable = pd.Series(0.25 + 0.05 * np.sin(np.linspace(0, 20, n)) + 0.004 * np.random.default_rng(1).standard_normal(n))
    assert detect_drift(drifting, dates)
    assert not detect_drift(stable, dates)


def test_drift_needs_a_long_enough_record():
    dates = pd.Series(pd.date_range("2020-01-01", periods=200, freq="D"))
    steep = pd.Series(np.linspace(0.1, 0.4, 200))
    assert not detect_drift(steep, dates)


def test_cross_depth_inconsistency_flags_an_impossible_gradient():
    wide = pd.DataFrame({"0_5": [0.20, 0.20], "5_15": [0.22, 0.60], "15_30": [0.24, 0.24]})
    flags = detect_cross_depth_inconsistency(wide)
    assert not flags.iloc[0].any()
    assert flags.iloc[1].any()


# --------------------------------------------------------------------------
# Sensor-physics flags
# --------------------------------------------------------------------------


def test_salinity_flag_spares_high_frequency_sensors():
    ece = pd.Series([8.0, 8.0])
    freq = pd.Series([50.0, 1000.0])
    flags = flag_salinity_suspect(ece, freq)
    assert bool(flags.iloc[0])
    assert not bool(flags.iloc[1])


def test_clay_flag_respects_a_soil_specific_calibration():
    """A probe calibrated gravimetrically has already absorbed the clay effect."""
    theta = pd.Series([0.30, 0.30])
    clay = pd.Series([50.0, 50.0])
    porosity = pd.Series([0.45, 0.45])
    calibration = pd.Series(["factory", "soil_specific"])
    flags = flag_clay_suspect(theta, clay, porosity, calibration)
    assert bool(flags.iloc[0])
    assert not bool(flags.iloc[1])


def test_clay_flag_is_quiet_in_sandy_soil():
    flags = flag_clay_suspect(pd.Series([0.25]), pd.Series([4.0]), pd.Series([0.42]))
    assert not bool(flags.iloc[0])


# --------------------------------------------------------------------------
# Rise without input / irrigation inference
# --------------------------------------------------------------------------


def test_rise_without_input_ignores_a_rise_that_rain_explains():
    theta = pd.Series([0.20, 0.20, 0.28, 0.28])
    precip = pd.Series([0.0, 0.0, 25.0, 0.0])
    assert not detect_rise_without_input(theta, precip).any()


def test_rise_without_input_catches_an_unexplained_rise():
    theta = pd.Series([0.20, 0.20, 0.28, 0.28])
    precip = pd.Series([0.0, 0.0, 0.0, 0.0])
    detected = detect_rise_without_input(theta, precip)
    assert bool(detected.iloc[2])


def test_irrigation_events_are_recovered_from_soil_moisture_alone():
    """The simulator knows exactly when it irrigated, so recall and precision are measurable.

    This is the capability that makes published figures usable: a study that
    plots soil moisture but never tabulates its irrigation schedule can still
    yield the schedule.
    """
    obs, _ = generate_corpus(n_sites=10, years=3, seed=77)
    obs["date"] = pd.to_datetime(obs["date"])

    recalls, precisions = [], []
    for _, group in obs.groupby("site_id"):
        truth = group[group.irrigation_mm > 0].drop_duplicates("date")
        if len(truth) < 5:
            continue
        found = infer_irrigation_events(
            group.rename(columns={"theta_obs_m3m3": "theta_m3m3"}),
            theta_col="theta_m3m3", precip_col="precip_mm",
            date_col="date", depth_col="depth_mid_cm",
        )
        if found.empty:
            continue
        true_dates = set(pd.to_datetime(truth.date))
        # One day of tolerance: water applied late in the day appears the next morning.
        hits = sum(
            any(abs((f - t).days) <= 1 for t in true_dates)
            for f in pd.to_datetime(found.date)
        )
        recalls.append(hits / len(true_dates))
        precisions.append(hits / len(found))

    assert len(recalls) >= 5
    assert float(np.median(recalls)) > 0.6
    assert float(np.median(precisions)) > 0.8


def test_irrigation_inference_returns_an_empty_frame_without_surface_data():
    frame = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=10),
        "theta_m3m3": 0.25, "precip_mm": 0.0, "depth_mid_cm": 150.0,
    })
    assert infer_irrigation_events(frame).empty


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def _qc_frame(n_sites: int = 4) -> pd.DataFrame:
    obs, sites = generate_corpus(n_sites=n_sites, years=2, seed=5)
    frame = obs[obs.depth_mid_cm <= 30].rename(columns={"theta_obs_m3m3": "theta_m3m3"}).copy()
    frame["time_utc"] = pd.to_datetime(frame["date"])
    frame["method"] = "fdr_capacitance"
    frame = frame.merge(
        sites[["site_id", "clay_pct", "porosity_m3m3", "ece_ds_m", "sensor_frequency_mhz"]],
        on="site_id",
    ).rename(columns={"sensor_frequency_mhz": "instrument_frequency_mhz"})
    return frame


def test_run_qc_adds_flags_and_uncertainty():
    result = run_qc(_qc_frame(), theta_col="theta_m3m3", date_col="time_utc")
    assert "quality_flag" in result.columns
    assert "uncertainty_m3m3" in result.columns
    assert result["uncertainty_m3m3"].gt(0).all()
    assert set(result["quality_flag"]) <= {f.value for f in QualityFlag}


def test_run_qc_false_positive_rates_are_tolerable_on_clean_data():
    """These rates are quoted; a regression in any detector should break this."""
    result = run_qc(_qc_frame(), theta_col="theta_m3m3", date_col="time_utc")
    assert result["qc_spike"].mean() < 0.02
    assert result["qc_step_change"].mean() < 0.04
    assert result["qc_flatline"].mean() < 0.05
    assert result["qc_out_of_range"].mean() < 0.001


def test_uncertainty_is_larger_for_flagged_observations():
    result = run_qc(_qc_frame(), theta_col="theta_m3m3", date_col="time_utc")
    good = result[result.quality_flag == QualityFlag.GOOD.value]["uncertainty_m3m3"]
    flagged = result[result.quality_flag != QualityFlag.GOOD.value]["uncertainty_m3m3"]
    assert good.mean() < flagged.mean()


def test_run_qc_flags_but_never_drops():
    frame = _qc_frame()
    assert len(run_qc(frame, theta_col="theta_m3m3", date_col="time_utc")) == len(frame)


def test_qc_summary_lists_every_check():
    result = run_qc(_qc_frame(), theta_col="theta_m3m3", date_col="time_utc")
    summary = qc_summary(result)
    assert not summary.empty
    assert {"check", "n", "pct"} <= set(summary.columns)
    assert summary["pct"].between(0, 100).all()
