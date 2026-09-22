"""Figure and palette tests.

Charts are checked for the properties that make them readable and honest rather
than for pixel output: that the palette clears its colour-vision gates, that an
ordered ramp stays ordered, that depth reads downward as a soil profile must,
and that every figure carries its data's provenance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from smml.viz import figures, style  # noqa: E402


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture
def predictions():
    """A held-out prediction set spanning depth, texture and salinity."""
    rng = np.random.default_rng(3)
    rows = []
    for site in range(14):
        clay = rng.uniform(5, 55)
        ece = rng.uniform(0.2, 9.0)
        texture = "clay" if clay > 35 else ("loam" if clay > 18 else "sandy_loam")
        base = 0.16 + 0.0025 * clay
        for depth in (2.5, 10.0, 22.5, 45.0, 80.0, 150.0):
            for day in range(90):
                truth = base + 0.05 * np.sin(day / 14 + depth / 40) + rng.normal(0, 0.006)
                rows.append({
                    "site_id": f"s{site:02d}",
                    "date": pd.Timestamp("2021-05-01") + pd.Timedelta(days=day),
                    "depth_mid_cm": depth,
                    "depth_top_cm": depth, "depth_bottom_cm": depth,
                    "theta_true_m3m3": truth,
                    "theta_obs_m3m3": truth - 0.002 * clay,
                    "prediction": truth + rng.normal(0, 0.025),
                    "clay_pct": clay, "ece_ds_m": ece, "texture_class": texture,
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------


def test_depth_ramp_is_ordered_and_distinct():
    """An ordered variable must not be given a ramp that wraps."""
    for n in (1, 3, 5, 6, 8, 12):
        ramp = style.depth_ramp(n)
        assert len(ramp) == n
        assert len(set(ramp)) == n, f"n={n} produced a repeat"


def test_depth_ramp_darkens_monotonically():
    """Shallow to deep must read as light to dark, or the ramp says nothing."""
    ramp = style.depth_ramp(6)

    def luminance(value: str) -> float:
        value = value.lstrip("#")
        r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    luminances = [luminance(c) for c in ramp]
    pairs = zip(luminances[:-1], luminances[1:], strict=True)
    assert all(a > b for a, b in pairs)


def test_scatter_forms_are_capped_at_three_series():
    """Past three slots, yellow sits beside orange and fails the all-pairs floor."""
    assert style.SERIES_ALL_PAIRS_CAP == 3


def test_categorical_slots_are_distinct():
    assert len(set(style.SERIES)) == len(style.SERIES)


def test_measured_and_predicted_take_the_first_two_slots():
    """Slots are assigned in order; the ordering is the CVD-safety mechanism."""
    assert style.MEASURED == style.SERIES[0]
    assert style.PREDICTED == style.SERIES[1]


def test_style_applies_recessive_chrome():
    style.apply()
    assert matplotlib.rcParams["axes.spines.top"] is False
    assert matplotlib.rcParams["axes.spines.right"] is False
    assert matplotlib.rcParams["legend.frameon"] is False


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def test_measured_vs_predicted_facets_by_depth(predictions):
    fig = figures.measured_vs_predicted(predictions, "theta_true_m3m3", "prediction")
    drawn = [ax for ax in fig.axes if ax.get_title()]
    assert len(drawn) == predictions["depth_mid_cm"].nunique()


def test_measured_vs_predicted_panels_are_square(predictions):
    """A 1:1 plot on unequal axes makes the 1:1 line lie about agreement."""
    fig = figures.measured_vs_predicted(predictions, "theta_true_m3m3", "prediction")
    for ax in fig.axes:
        if not ax.get_title():
            continue
        assert ax.get_xlim() == ax.get_ylim()
        assert ax.get_aspect() == 1.0


def test_measured_vs_predicted_thins_points_but_not_metrics(predictions):
    """Metrics must come from every row even when the scatter is sampled."""
    fig = figures.measured_vs_predicted(predictions, "theta_true_m3m3", "prediction",
                                        max_points_per_facet=25)
    panel = predictions[predictions.depth_mid_cm == 2.5]
    from smml.eval.metrics import compute_metrics

    expected = compute_metrics(panel["theta_true_m3m3"], panel["prediction"])
    texts = " ".join(t.get_text() for ax in fig.axes for t in ax.texts)
    assert f"{expected['n']:,}" in texts
    assert f"{expected['rmse']:.3f}" in texts


def test_performance_by_depth_reads_downward(predictions):
    """Depth increases downward, as a soil profile is always drawn."""
    fig, table = figures.performance_by_depth(predictions, "theta_true_m3m3",
                                              "prediction")
    low, high = fig.axes[0].get_ylim()
    assert low > high, "the depth axis must be inverted"
    assert len(table) == predictions["depth_mid_cm"].nunique()
    assert {"rmse", "ubrmse", "bias", "depth"} <= set(table.columns)


def test_time_series_draws_both_series_with_a_legend(predictions):
    sites = list(predictions.site_id.unique())[:2]
    fig = figures.time_series(predictions, "theta_true_m3m3", "prediction",
                              sites=sites, depths=[2.5, 22.5])
    assert fig.legends, "two series require a legend"
    labels = {t.get_text() for t in fig.legends[0].get_texts()}
    assert {"Measured", "Predicted"} <= labels


def test_error_by_stratum_covers_texture_and_salinity(predictions):
    fig = figures.error_by_stratum(predictions, "theta_true_m3m3", "prediction")
    titles = " ".join(ax.get_title() for ax in fig.axes)
    assert "texture" in titles
    assert "salinity" in titles
    assert "clay" in titles


def test_clay_correction_effect_shares_one_scale(predictions):
    """Two panels compared by eye must be on the same axis, or the comparison lies."""
    raw = predictions.copy()
    raw["prediction"] = raw["prediction"] - 0.002 * raw["clay_pct"]
    fig = figures.clay_correction_effect(raw, predictions, "theta_true_m3m3",
                                         "prediction")
    limits = [ax.get_ylim() for ax in fig.axes]
    assert limits[0] == limits[1]


def test_skill_decomposition_reports_both_numbers(predictions):
    fig, decomposition = figures.skill_decomposition_figure(
        predictions, "theta_true_m3m3", "prediction")
    assert "r_between" in decomposition
    assert "r_within" in decomposition
    titles = " ".join(ax.get_title() for ax in fig.axes)
    assert "between sites" in titles
    assert "within a site" in titles


@pytest.mark.parametrize("builder", [
    lambda f: figures.measured_vs_predicted(f, "theta_true_m3m3", "prediction"),
    lambda f: figures.performance_by_depth(f, "theta_true_m3m3", "prediction")[0],
    lambda f: figures.error_by_stratum(f, "theta_true_m3m3", "prediction"),
    lambda f: figures.skill_decomposition_figure(f, "theta_true_m3m3", "prediction")[0],
])
def test_every_figure_stamps_its_provenance(builder, predictions):
    """A figure gets separated from its caption the moment it lands in a slide."""
    fig = builder(predictions)
    stamped = " ".join(t.get_text() for t in fig.texts)
    assert "Synthetic" in stamped


def test_figures_write_to_disk(predictions, tmp_path):
    out = tmp_path / "scatter.png"
    figures.measured_vs_predicted(predictions, "theta_true_m3m3", "prediction", out=out)
    assert out.exists()
    assert out.stat().st_size > 20_000
