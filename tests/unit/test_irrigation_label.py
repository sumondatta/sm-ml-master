"""Irrigation labelling tests.

This is the project's defining variable and nothing records it directly, so the
label is derived. These tests fix the behaviour that derivation must have: that
authoritative evidence outweighs abundant weak evidence, that correlated sources
do not get to vote twice, that a two-treatment study is flagged rather than
averaged, and that absent evidence produces "unknown" rather than "rainfed".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smml.irrigation.label import (
    IRRIGATED_ABOVE,
    MULTI_TREATMENT,
    RAINFED_BELOW,
    Evidence,
    EvidenceKind,
    IrrigationMethod,
    detect_multi_treatment,
    evidence_from_extent_map,
    evidence_from_moisture,
    evidence_from_text,
    evidence_from_water_balance,
    fuse,
    fuse_all,
    label_error_budget,
    resolve_method,
)


def declared(method="center_pivot", irrigated=True):
    return Evidence("s", 2020, EvidenceKind.DECLARED.value, irrigated, 1.0, method=method)


# --------------------------------------------------------------------------
# Fusion
# --------------------------------------------------------------------------


def test_fuse_needs_evidence():
    with pytest.raises(ValueError):
        fuse([])


def test_a_declared_method_outweighs_disagreeing_extent_maps():
    """Extent maps are the most abundant evidence and the least valid at a point."""
    label = fuse([
        declared(),
        evidence_from_extent_map("s", 2020, "gmia", 0.1),
        evidence_from_extent_map("s", 2020, "gfsad", 0.2),
        evidence_from_extent_map("s", 2020, "mirad", 0.15),
    ])
    assert label.status == "irrigated"
    assert label.probability > IRRIGATED_ABOVE


def test_extent_maps_alone_do_not_settle_the_question():
    """A pivot corner, a field edge or an unmanaged margin all read as irrigated."""
    label = fuse([
        evidence_from_extent_map("s", 2020, "lanid", 0.95),
        evidence_from_extent_map("s", 2020, "irrmapper", 0.92),
    ])
    assert label.status == "uncertain"


def test_correlated_maps_do_not_vote_three_times():
    """Maps share training imagery and share their errors, so agreeing with
    itself repeatedly must not accumulate like independent evidence."""
    two = fuse([evidence_from_extent_map("s", 2020, "lanid", 0.95),
                evidence_from_extent_map("s", 2020, "irrmapper", 0.95)])
    five = fuse([evidence_from_extent_map("s", 2020, p, 0.95)
                 for p in ("lanid", "irrmapper", "aim_hpa", "lgrip30", "worldcereal")])
    assert five.probability - two.probability < 0.2


def test_a_coarse_map_counts_for_less_than_a_fine_one():
    fine = fuse([evidence_from_extent_map("s", 2020, "lanid", 1.0)])
    coarse = fuse([evidence_from_extent_map("s", 2020, "gmia", 1.0)])
    assert fine.probability > coarse.probability


def test_a_map_unsure_of_itself_contributes_almost_nothing():
    sure = evidence_from_extent_map("s", 2020, "lanid", 1.0)
    unsure = evidence_from_extent_map("s", 2020, "lanid", 0.52)
    assert unsure.strength < 0.1
    assert abs(unsure.log_odds()) < abs(sure.log_odds())


def test_no_evidence_lands_in_the_uncertain_band_not_rainfed():
    """Absence of evidence about irrigation is not evidence of rainfed."""
    label = fuse([Evidence("s", 2020, EvidenceKind.LAND_COVER.value, True, 0.1)])
    assert label.status == "uncertain"
    assert RAINFED_BELOW < label.probability < IRRIGATED_ABOVE


def test_a_declared_rainfed_site_is_labelled_rainfed():
    label = fuse([declared(method=IrrigationMethod.RAINFED.value, irrigated=False)])
    assert label.status == "rainfed"
    assert label.probability < RAINFED_BELOW


def test_label_records_its_fusion_version():
    """Labels derived under different weightings must never be silently mixed."""
    label = fuse([declared()])
    assert label.fusion_version
    assert label.as_row()["fusion_version"] == label.fusion_version


def test_label_records_its_evidence():
    label = fuse([declared(), evidence_from_extent_map("s", 2020, "lanid", 0.9)])
    assert label.n_evidence == 2
    assert "declared" in label.as_row()["evidence_kinds"]
    assert "extent_map" in label.as_row()["evidence_kinds"]


# --------------------------------------------------------------------------
# Method
# --------------------------------------------------------------------------


def test_method_follows_evidence_precedence():
    label = fuse([
        Evidence("s", 2020, EvidenceKind.MOISTURE_SIGNATURE.value, True, 0.8, method="furrow"),
        declared(method="subsurface_drip"),
    ])
    assert label.method == "subsurface_drip"
    assert label.method_confidence > 0.8


def test_method_is_unknown_when_nothing_states_it():
    method, confidence = resolve_method([evidence_from_extent_map("s", 2020, "lanid", 0.9)])
    assert method == IrrigationMethod.UNKNOWN.value
    assert confidence == 0.0


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------


def test_a_longer_phrase_is_not_shadowed_by_a_substring():
    """'surface drip' matches inside 'subsurface drip'. Left unhandled it assigned
    the wrong wetting geometry, which is the one thing the method field is for."""
    items = evidence_from_text("s", 2020, "Plots used subsurface drip at 0.3 m spacing.")
    assert items
    methods = {e.method for e in items if e.method}
    assert methods == {IrrigationMethod.DRIP_SUBSURFACE.value}


def test_short_acronyms_need_word_boundaries():
    """'sdi' must not fire inside an unrelated word."""
    items = evidence_from_text("s", 2020, "The subsidiary plots were rainfed.")
    assert all(e.method != IrrigationMethod.DRIP_SUBSURFACE.value for e in items)


def test_negation_is_detected():
    items = evidence_from_text("s", 2020, "No supplemental irrigation was applied.")
    assert items
    assert all(not e.says_irrigated for e in items)


def test_a_negated_rainfed_phrase_supports_irrigation():
    items = evidence_from_text("s", 2020, "The plots were not rainfed.")
    assert items
    assert any(e.says_irrigated for e in items)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("All plots were irrigated by center pivot to replace 100% of crop ET.", "irrigated"),
        ("This was a rainfed study; the site is not irrigated.", "rainfed"),
        ("The experiment compared center pivot irrigation with a rainfed control.", MULTI_TREATMENT),
        ("Cotton was grown under furrow irrigation; the dryland treatment received no irrigation.",
         MULTI_TREATMENT),
    ],
)
def test_text_is_classified_correctly(text, expected):
    assert fuse(evidence_from_text("s", 2020, text)).status == expected


def test_multi_treatment_names_the_applied_method_not_the_control():
    """A plot-level assignment needs to know what the irrigated arm used."""
    label = fuse(evidence_from_text(
        "s", 2020, "The experiment compared center pivot irrigation with a rainfed control."
    ))
    assert label.status == MULTI_TREATMENT
    assert label.method == IrrigationMethod.CENTER_PIVOT.value
    assert label.method_confidence < 0.5, "the sensor's own plot is still unresolved"


def test_multi_treatment_is_not_flagged_for_a_single_treatment_study():
    assert not detect_multi_treatment(
        evidence_from_text("s", 2020, "All plots received drip irrigation.")
    )


def test_empty_text_yields_no_evidence():
    assert evidence_from_text("s", 2020, "") == []


# --------------------------------------------------------------------------
# Other evidence builders
# --------------------------------------------------------------------------


def test_water_balance_deficit_supports_irrigation():
    item = evidence_from_water_balance("s", 2020, precip_mm=150, etc_mm=600)
    assert item is not None
    assert item.says_irrigated


def test_a_wet_climate_does_not_imply_irrigation():
    item = evidence_from_water_balance("s", 2020, precip_mm=900, etc_mm=500)
    assert item is not None
    assert not item.says_irrigated


def test_water_balance_needs_usable_numbers():
    assert evidence_from_water_balance("s", 2020, precip_mm=0, etc_mm=500) is None
    assert evidence_from_water_balance("s", 2020, precip_mm=np.nan, etc_mm=500) is None


def test_moisture_signature_uses_the_detector():
    from smml.physics.simulator import generate_corpus

    obs, _ = generate_corpus(n_sites=6, years=2, seed=31)
    obs["date"] = pd.to_datetime(obs["date"])
    frame = obs.rename(columns={"theta_obs_m3m3": "theta_m3m3"})
    irrigated = frame[frame.site_id == frame[frame.irrigation_mm > 0].site_id.iloc[0]]
    item = evidence_from_moisture("s", 2020, irrigated)
    assert item is not None
    assert item.says_irrigated
    assert 0.0 < item.strength <= 1.0


def test_moisture_signature_on_an_empty_record():
    assert evidence_from_moisture("s", 2020, pd.DataFrame()) is None


# --------------------------------------------------------------------------
# Batch and reporting
# --------------------------------------------------------------------------


def test_fuse_all_produces_one_row_per_station_year():
    evidence = pd.DataFrame([
        {"site_id": "a", "year": 2020, "kind": "declared", "says_irrigated": True,
         "strength": 1.0, "method": "center_pivot"},
        {"site_id": "a", "year": 2021, "kind": "declared", "says_irrigated": True,
         "strength": 1.0, "method": "center_pivot"},
        {"site_id": "b", "year": 2020, "kind": "extent_map", "says_irrigated": False,
         "strength": 0.9, "product": "lanid"},
    ])
    labels = fuse_all(evidence)
    assert len(labels) == 3
    assert set(labels.columns) >= {"site_id", "year", "irrigation_probability",
                                   "irrigation_status", "irrigation_method",
                                   "n_evidence", "fusion_version"}


def test_fuse_all_rejects_a_malformed_evidence_table():
    with pytest.raises(ValueError, match="missing"):
        fuse_all(pd.DataFrame([{"site_id": "a", "year": 2020}]))


def test_error_budget_reports_coverage():
    evidence = pd.DataFrame(
        [{"site_id": f"s{i}", "year": 2020, "kind": "declared", "says_irrigated": i % 2 == 0,
          "strength": 1.0, "method": "center_pivot" if i % 2 == 0 else "rainfed"}
         for i in range(10)]
        + [{"site_id": "sx", "year": 2020, "kind": "land_cover", "says_irrigated": True,
            "strength": 0.1}]
    )
    budget = label_error_budget(fuse_all(evidence))
    assert budget["n"] == 11
    assert budget["share_irrigated"] > 0
    assert budget["share_rainfed"] > 0
    assert budget["share_uncertain"] > 0
    assert 0 <= budget["share_with_method"] <= 1
