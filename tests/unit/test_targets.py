"""Success-criterion tests.

A target written in a paragraph never gets checked. These assert that the
criteria are applied where they are meant to apply — Product B on the difficult
soils only — and that an implausibly good score raises a leakage warning even
while it passes every threshold, which is the case most likely to be believed
when it should not be.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smml.eval.targets import (
    ALL_TARGETS,
    DIFFICULT_SOIL,
    IMPLAUSIBLE_UBRMSE,
    SENSOR_BASELINE_RMSE,
    beats_the_sensor,
    difficult_soil_mask,
    evaluate_targets,
)


def make_frame(noise: float, n: int = 3000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame({
        "clay_pct": rng.uniform(5, 55, n),
        "ece_ds_m": rng.uniform(0, 10, n),
        "y": rng.uniform(0.1, 0.4, n),
    })
    frame["p"] = frame["y"] + rng.normal(0, noise, n)
    return frame


def test_difficult_soil_mask_takes_either_condition():
    """High clay and high salinity are different failure modes; one suffices."""
    frame = pd.DataFrame({"clay_pct": [40.0, 10.0, 10.0], "ece_ds_m": [0.5, 6.0, 0.5]})
    assert list(difficult_soil_mask(frame)) == [True, True, False]


def test_difficult_soil_mask_handles_missing_columns():
    frame = pd.DataFrame({"clay_pct": [40.0, 10.0]})
    assert list(difficult_soil_mask(frame)) == [True, False]
    assert not difficult_soil_mask(pd.DataFrame({"x": [1, 2]})).any()


def test_product_b_is_scored_only_on_the_difficult_soils():
    """Good performance in loam must not carry a failure in clay."""
    frame = make_frame(0.03)
    report = evaluate_targets(frame, "y", "p", product="B")
    assert report.n_observations < len(frame)
    assert report.n_observations == int(difficult_soil_mask(frame).sum())
    assert any("restricted to clay" in n for n in report.notes)


def test_product_a_is_scored_on_everything():
    frame = make_frame(0.03)
    report = evaluate_targets(frame, "y", "p", product="A", skill={"r_within": 0.6})
    assert report.n_observations == len(frame)


def test_a_realistic_model_passes():
    frame = make_frame(0.028)
    assert evaluate_targets(frame, "y", "p", product="B").passed


def test_a_poor_model_fails_product_b():
    frame = make_frame(0.09)
    report = evaluate_targets(frame, "y", "p", product="B")
    assert not report.passed


def test_bias_is_compared_on_its_absolute_value():
    """A model biased -0.05 is as wrong as one biased +0.05."""
    frame = make_frame(0.01)
    frame["p"] = frame["y"] - 0.05
    report = evaluate_targets(frame, "y", "p", product="B")
    row = report.rows[report.rows["target"] == "abs_bias_difficult_soils"].iloc[0]
    assert row["value"] == pytest.approx(0.05, abs=1e-3)
    assert row["passes"] is False or row["passes"] == False  # noqa: E712


def test_an_implausibly_good_score_raises_a_leakage_warning():
    """Random k-fold on rows produces exactly this, and it passes every threshold."""
    frame = make_frame(0.010)
    report = evaluate_targets(frame, "y", "p", product="A", skill={"r_within": 0.9})
    assert report.passed, "the point is that it passes"
    assert report.leakage_warning is not None
    assert "leave-site-out" in report.leakage_warning


def test_a_realistic_score_raises_no_warning():
    report = evaluate_targets(make_frame(0.035), "y", "p", product="A",
                              skill={"r_within": 0.6})
    assert report.leakage_warning is None


def test_the_leakage_threshold_is_below_any_honest_site_score():
    assert IMPLAUSIBLE_UBRMSE < 0.03


def test_beats_the_sensor_uses_total_rmse_not_ubrmse():
    """A dielectric probe's error in these soils is mostly bias, which ubRMSE
    removes — so comparing ubRMSE with a sensor's total RMSE flatters the model
    by exactly the quantity at issue."""
    frame = make_frame(0.02)
    frame["p"] = frame["y"] + 0.06          # pure offset: ubRMSE small, RMSE large
    result = beats_the_sensor(frame, "y", "p")
    assert result["rmse"] > SENSOR_BASELINE_RMSE
    assert not result["beats_sensor"]


def test_beats_the_sensor_on_a_good_model():
    result = beats_the_sensor(make_frame(0.025), "y", "p")
    assert result["beats_sensor"]
    assert result["meets_product_b"]


def test_beats_the_sensor_reports_when_there_is_nothing_to_test_on():
    frame = pd.DataFrame({"clay_pct": [10.0] * 50, "ece_ds_m": [0.5] * 50,
                          "y": [0.25] * 50, "p": [0.25] * 50})
    result = beats_the_sensor(frame, "y", "p")
    assert result["n"] == 0
    assert not result["beats_sensor"]


def test_every_target_states_why_it_is_where_it_is():
    for targets in ALL_TARGETS.values():
        for target in targets:
            assert len(target.rationale) > 40, target.name
            assert target.direction in {"min", "max"}


def test_unknown_product_is_rejected():
    with pytest.raises(KeyError):
        evaluate_targets(make_frame(0.03), "y", "p", product="Z")


def test_difficult_soil_thresholds_match_the_sensor_failure_literature():
    """Clay >= 35% is where bound water becomes a large share; ECe >= 4 dS/m is
    the USDA moderately-saline boundary."""
    assert DIFFICULT_SOIL["clay_pct_min"] == 35.0
    assert DIFFICULT_SOIL["ece_ds_m_min"] == 4.0
