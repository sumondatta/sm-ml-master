"""Simulator correctness tests.

The synthetic corpus is only useful as a testbed if it is physically honest, so
these assert the properties a real field would have: mass is conserved, water
moves downward with increasing lag and decreasing amplitude, drydowns are slower
than wet-ups, runoff and drainage respond to texture in the right direction, and
the imposed sensor artefacts point the way the physics says they must.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smml.physics.simulator import (
    CLIMATE_ARCHETYPES,
    CURVE_NUMBER_ROW_CROP,
    TEXTURE_ARCHETYPES,
    IrrigationPolicy,
    SiteSpec,
    SoilColumn,
    climate_texture_design,
    generate_corpus,
    generate_weather,
    hydrologic_soil_group,
    scs_runoff_mm,
    simulate_site,
)


def _site(**kw) -> SiteSpec:
    base = dict(site_id="t", lat=37.0, lon=-100.5, elevation_m=850.0,
                sand_pct=40.0, clay_pct=25.0, om_pct=2.0, crop="maize")
    base.update(kw)
    return SiteSpec(**base)


def _run(spec: SiteSpec, days: int = 365 * 3, seed: int = 7):
    rng = np.random.default_rng(seed)
    weather = generate_weather(spec, "2018-01-01", days, rng)
    column = SoilColumn.from_texture(spec.sand_pct, spec.clay_pct, spec.om_pct,
                                     rng=np.random.default_rng(seed + 1))
    daily = simulate_site(spec, weather, rng=np.random.default_rng(seed + 2), column=column)
    return daily, column


def _closure_error(daily: pd.DataFrame, column: SoilColumn) -> float:
    cols = [c for c in daily.columns if c.startswith("theta_true_")]
    storage = (daily[cols].to_numpy() * column.thickness_mm).sum(axis=1)
    flux = (daily.precip_mm + daily.irrigation_mm - daily.et_actual_mm
            - daily.drainage_mm - daily.runoff_mm).to_numpy()[1:]
    return float((flux - np.diff(storage)).sum())


# --------------------------------------------------------------------------
# Conservation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("texture", ["sand", "sandy_loam", "loam", "clay_loam", "clay"])
def test_water_balance_closes(texture):
    """Inflow minus outflow must equal the change in storage, to rounding."""
    sand, clay = TEXTURE_ARCHETYPES[texture]
    daily, column = _run(_site(sand_pct=sand, clay_pct=clay))
    assert abs(_closure_error(daily, column)) < 0.05  # mm over three years


@pytest.mark.parametrize("method", ["center_pivot", "drip", "furrow", "flood", "rainfed"])
def test_water_balance_closes_for_every_irrigation_method(method):
    spec = _site(irrigation_method=method)
    rng = np.random.default_rng(3)
    weather = generate_weather(spec, "2018-01-01", 365 * 2, rng)
    column = SoilColumn.from_texture(spec.sand_pct, spec.clay_pct, spec.om_pct,
                                     rng=np.random.default_rng(4))
    daily = simulate_site(spec, weather, policy=IrrigationPolicy(method=method),
                          rng=np.random.default_rng(5), column=column)
    assert abs(_closure_error(daily, column)) < 0.05


def test_water_content_stays_between_physical_bounds():
    daily, column = _run(_site())
    for i, (top, bot) in enumerate(column.layers_cm):
        theta = daily[f"theta_true_{int(top)}_{int(bot)}"].to_numpy()
        assert theta.min() >= 0.0
        assert theta.max() <= column.theta_sat[i] + 1e-9


def test_rainfed_site_receives_no_irrigation():
    daily, _ = _run(_site(irrigation_method="rainfed"))
    assert daily.irrigation_mm.sum() == 0.0


# --------------------------------------------------------------------------
# Profile behaviour
# --------------------------------------------------------------------------


@pytest.mark.parametrize("texture", ["sand", "sandy_loam", "loam", "clay"])
def test_high_frequency_variability_damps_with_depth(texture):
    """Each layer must filter the one above it.

    The invariant is about *high-frequency* variability, measured as the spread
    of day-to-day changes. Total standard deviation is deliberately not used: a
    deep layer within the root zone carries a large slow seasonal drawdown that
    can exceed the surface layer's, which is real behaviour and not a failure of
    damping.
    """
    sand, clay = TEXTURE_ARCHETYPES[texture]
    daily, column = _run(_site(sand_pct=sand, clay_pct=clay))
    hf = [
        float(np.diff(daily[f"theta_true_{int(t)}_{int(b)}"].to_numpy()).std())
        for t, b in column.layers_cm
    ]
    assert np.all(np.diff(hf) < 0), hf


def test_total_range_narrows_with_depth():
    daily, column = _run(_site())
    spans = [
        float(np.ptp(daily[f"theta_true_{int(t)}_{int(b)}"].to_numpy()))
        for t, b in column.layers_cm
    ]
    assert spans[0] > spans[-1]
    assert np.all(np.diff(spans) < 0), spans


def test_deeper_layers_lag_the_surface():
    """Cross-correlation with the surface must peak at a non-negative lag."""
    daily, column = _run(_site())
    surface = daily[f"theta_true_{int(column.layers_cm[0][0])}_{int(column.layers_cm[0][1])}"].to_numpy()
    deep = daily["theta_true_30_60"].to_numpy()
    s = (surface - surface.mean()) / (surface.std() + 1e-12)
    d = (deep - deep.mean()) / (deep.std() + 1e-12)
    lags = range(0, 30)
    corr = [np.corrcoef(s[: len(s) - k], d[k:])[0, 1] for k in lags]
    assert int(np.argmax(corr)) > 0


def test_drydown_is_slower_than_wetup():
    """The asymmetry a learning model has to capture: fast wetting, slow drying."""
    daily, _ = _run(_site())
    d = np.diff(daily["theta_true_0_5"].to_numpy())
    rises, falls = d[d > 0], d[d < 0]
    assert rises.mean() > -falls.mean()


def test_irrigation_raises_soil_moisture():
    daily, _ = _run(_site(irrigation_method="center_pivot"))
    irr = daily.irrigation_mm.to_numpy()
    theta = daily["theta_true_0_5"].to_numpy()
    delta = np.diff(theta, prepend=theta[0])
    assert delta[irr > 0].mean() > delta[irr == 0].mean()


# --------------------------------------------------------------------------
# Runoff
# --------------------------------------------------------------------------


def test_hydrologic_soil_group_ordering():
    assert hydrologic_soil_group(5000) == "A"
    assert hydrologic_soil_group(1000) == "B"
    assert hydrologic_soil_group(200) == "C"
    assert hydrologic_soil_group(20) == "D"


def test_scs_runoff_is_zero_below_initial_abstraction():
    assert scs_runoff_mm(1.0, 78.0, 0.5) == 0.0


def test_scs_runoff_increases_with_rain_curve_number_and_wetness():
    assert scs_runoff_mm(60.0, 78.0, 0.5) > scs_runoff_mm(20.0, 78.0, 0.5)
    assert scs_runoff_mm(40.0, 89.0, 0.5) > scs_runoff_mm(40.0, 67.0, 0.5)
    assert scs_runoff_mm(40.0, 78.0, 1.0) > scs_runoff_mm(40.0, 78.0, 0.0)


def test_scs_runoff_never_exceeds_rainfall():
    for rain in (1.0, 10.0, 50.0, 200.0):
        for cn in CURVE_NUMBER_ROW_CROP.values():
            for wet in (0.0, 0.5, 1.0):
                assert 0.0 <= scs_runoff_mm(rain, cn, wet) <= rain


def test_fine_texture_runs_off_more_and_drains_less():
    sand_daily, _ = _run(_site(sand_pct=90, clay_pct=4, annual_precip_mm=700))
    clay_daily, _ = _run(_site(sand_pct=20, clay_pct=52, annual_precip_mm=700))
    assert clay_daily.runoff_mm.sum() > sand_daily.runoff_mm.sum()
    assert clay_daily.drainage_mm.sum() < sand_daily.drainage_mm.sum()


# --------------------------------------------------------------------------
# Sensor artefacts
# --------------------------------------------------------------------------


def test_clay_makes_the_sensor_read_low_at_matched_wetness():
    """Bound water is invisible to a dielectric probe, so error must fall with clay."""
    obs, sites = generate_corpus(n_sites=64, years=2, seed=11)
    merged = obs.merge(sites[["site_id", "clay_pct", "sensor_bias"]], on="site_id")
    merged["err"] = merged.theta_obs_m3m3 - merged.theta_true_m3m3 - merged.sensor_bias
    band = merged[(merged.theta_true_m3m3 > 0.20) & (merged.theta_true_m3m3 < 0.40)]
    grouped = band.groupby(
        pd.cut(band.clay_pct, [0, 15, 30, 70]), observed=True
    ).err.mean()
    assert np.all(np.diff(grouped.to_numpy()) < 0)


def test_salinity_biases_low_frequency_sensors_but_not_tdr():
    obs, sites = generate_corpus(n_sites=64, years=2, seed=11)
    merged = obs.merge(
        sites[["site_id", "ece_ds_m", "sensor_frequency_mhz", "sensor_bias"]], on="site_id"
    )
    merged["err"] = merged.theta_obs_m3m3 - merged.theta_true_m3m3 - merged.sensor_bias
    band = merged[(merged.theta_true_m3m3 > 0.20) & (merged.theta_true_m3m3 < 0.40)]
    low = band[band.sensor_frequency_mhz < 150]
    high = band[band.sensor_frequency_mhz >= 150]
    # Salinity pushes low-frequency readings up; TDR is far less affected.
    low_effect = low[low.ece_ds_m > 4].err.mean() - low[low.ece_ds_m < 2].err.mean()
    high_effect = high[high.ece_ds_m > 4].err.mean() - high[high.ece_ds_m < 2].err.mean()
    assert low_effect > 0.01
    assert low_effect > high_effect


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def test_design_covers_every_climate_texture_combination_before_repeating():
    rng = np.random.default_rng(0)
    n = len(CLIMATE_ARCHETYPES) * len(TEXTURE_ARCHETYPES)
    design = climate_texture_design(n, rng)
    assert len(set(design)) == n


def test_small_corpus_still_spans_the_texture_range():
    """The bug this guards: cyclic indexing reached only three textures at n=24."""
    rng = np.random.default_rng(0)
    design = climate_texture_design(24, rng)
    assert len({t for _, t in design}) >= 6
    assert len({c for c, _ in design}) >= 6


def test_corpus_has_the_expected_long_schema():
    obs, sites = generate_corpus(n_sites=4, years=1, seed=3)
    required = {
        "site_id", "date", "doy", "depth_top_cm", "depth_bottom_cm", "depth_mid_cm",
        "theta_true_m3m3", "theta_obs_m3m3", "saturation", "precip_mm", "et0_mm",
        "irrigation_mm", "layer_porosity_m3m3", "layer_fc_m3m3", "layer_wp_m3m3",
    }
    assert required <= set(obs.columns)
    assert {"site_id", "sand_pct", "silt_pct", "clay_pct", "ece_ds_m", "texture_class",
            "is_irrigated", "climate", "texture_archetype"} <= set(sites.columns)
    assert obs.site_id.nunique() == 4
    assert len(sites) == 4
    assert (obs.groupby("site_id").depth_top_cm.nunique() == 6).all()


def test_corpus_is_reproducible():
    a, _ = generate_corpus(n_sites=3, years=1, seed=99)
    b, _ = generate_corpus(n_sites=3, years=1, seed=99)
    pd.testing.assert_frame_equal(a, b)


def test_corpus_differs_across_seeds():
    a, _ = generate_corpus(n_sites=3, years=1, seed=1)
    b, _ = generate_corpus(n_sites=3, years=1, seed=2)
    assert not a.theta_true_m3m3.equals(b.theta_true_m3m3)


def test_texture_and_silt_are_consistent():
    _, sites = generate_corpus(n_sites=16, years=1, seed=5)
    total = sites.sand_pct + sites.silt_pct + sites.clay_pct
    assert np.allclose(total, 100.0, atol=1e-6)
