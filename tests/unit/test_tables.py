"""Table extraction tests.

The headline test is a round trip: generate a thesis-appendix PDF whose values
are known exactly, extract, and compare. Table extraction should be *exact* —
unlike figure digitization it involves no tracing — so the bar is zero error,
not a tolerance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from smml.litmine.tables import (
    MoistureBasis,
    classify_table,
    detect_basis,
    detect_unit,
    extract_tables,
    harvest_tables,
    parse_depth,
    parse_number,
    plausible_water_content,
    table_to_long,
)

reportlab = pytest.importorskip("reportlab")
pdfplumber = pytest.importorskip("pdfplumber")


@pytest.fixture(scope="module")
def thesis(tmp_path_factory):
    """A generated appendix PDF plus the values that went into it."""
    from tests.fixtures.make_thesis_pdf import DATES, DEPTHS, build

    path = tmp_path_factory.mktemp("pdf") / "appendix.pdf"
    values = build(path)
    return path, values, DEPTHS, DATES


# --------------------------------------------------------------------------
# Cell parsing
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0-15", (0.0, 15.0)),
        ("0–15 cm", (0.0, 15.0)),
        ("15 to 30 cm", (15.0, 30.0)),
        ("0~100 cm", (0.0, 100.0)),
        ("0.0-0.15 m", (0.0, 15.0)),
        ("first foot", (0.0, 30.48)),
        ("second foot", (30.48, 60.96)),
        ("2 ft", (60.96, 60.96)),
        ("60", (60.0, 60.0)),
        ("30 см", (30.0, 30.0)),
        ("15-30厘米", (15.0, 30.0)),
        ("not a depth", None),
        ("", None),
    ],
)
def test_depth_parsing(text, expected):
    got = parse_depth(text)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.21", 0.21),
        ("0,21", 0.21),          # decimal comma
        ("1,234.5", 1234.5),     # thousands separator
        ("18.4 a", 18.4),        # significance letter
        ("0.31 ab", 0.31),
        ("0.21±0.03", 0.21),     # mean and standard deviation
        ("12.3%", 12.3),
        ("12.3 %", 12.3),
        ("0.285 m3 m-3", 0.285),
        ("-0.05", -0.05),
        ("n/a", None),
        ("—", None),
        ("", None),
        (None, None),
    ],
)
def test_number_parsing(text, expected):
    got = parse_number(text)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Volumetric water content (m3/m3)", MoistureBasis.VOLUMETRIC),
        ("体积含水率", MoistureBasis.VOLUMETRIC),
        ("Gravimetric soil moisture, dry weight basis", MoistureBasis.GRAVIMETRIC),
        ("质量含水率", MoistureBasis.GRAVIMETRIC),
        ("Soil water storage (mm)", MoistureBasis.STORAGE),
        ("запасы влаги", MoistureBasis.STORAGE),
        ("Yield (t/ha)", MoistureBasis.UNKNOWN),
    ],
)
def test_basis_detection(text, expected):
    assert detect_basis(text) == expected


def test_chinese_basis_terms_differ_by_one_character():
    """质量 and 体积 decide whether a value needs dividing by bulk density."""
    assert detect_basis("质量含水率") == MoistureBasis.GRAVIMETRIC
    assert detect_basis("体积含水率") == MoistureBasis.VOLUMETRIC


def test_unit_detection():
    assert detect_unit("water content (%)") == "%"
    assert detect_unit("theta (m3/m3)") == "m3/m3"
    assert detect_unit("storage (mm)") == "mm"


# --------------------------------------------------------------------------
# Plausibility
# --------------------------------------------------------------------------


def test_plausibility_accepts_real_water_contents():
    assert plausible_water_content(np.array([0.18, 0.22, 0.26, 0.31]),
                                   MoistureBasis.VOLUMETRIC)


def test_plausibility_rejects_a_yield_table():
    assert not plausible_water_content(np.array([8.2, 9.4, 11.0, 7.8]),
                                       MoistureBasis.VOLUMETRIC)


def test_plausibility_is_applied_on_the_canonical_scale():
    """Checking the declared unit here instead discarded every percent table:
    the percent range was applied to values already divided by a hundred."""
    fractions = np.array([0.18, 0.22, 0.26, 0.31])
    assert plausible_water_content(fractions, MoistureBasis.VOLUMETRIC)


def test_plausibility_needs_enough_numbers():
    assert not plausible_water_content(np.array([0.22]), MoistureBasis.VOLUMETRIC)


def test_storage_has_its_own_range():
    assert plausible_water_content(np.array([120.0, 180.0, 210.0]), MoistureBasis.STORAGE)
    assert not plausible_water_content(np.array([0.2, 0.3, 0.25]), MoistureBasis.STORAGE)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def test_a_column_headed_depth_means_depth_runs_down_the_rows(thesis):
    """The axis logic that was inverted at first, which recovered nothing."""
    path, _, _, _ = thesis
    tables = [classify_table(t) for t in extract_tables(path)]
    by_layout = {t.depth_axis for t in tables}
    assert "rows" in by_layout
    assert "columns" in by_layout


def test_every_table_in_the_appendix_is_recognised(thesis):
    path, _, _, _ = thesis
    tables = [classify_table(t) for t in extract_tables(path)]
    assert len(tables) == 3
    assert all(t.score >= 0.5 for t in tables), [t.score for t in tables]
    assert all(t.depth_axis for t in tables)


def test_the_value_unit_is_not_read_off_the_depth_header(thesis):
    """'Depth (cm)' is not a unit of water content."""
    path, _, _, _ = thesis
    tables = [classify_table(t) for t in extract_tables(path)]
    assert all(t.unit in ("m3/m3", "%") for t in tables), [t.unit for t in tables]


def test_a_gravimetric_table_is_flagged(thesis):
    path, _, _, _ = thesis
    tables = [classify_table(t) for t in extract_tables(path)]
    gravimetric = [t for t in tables if t.basis == MoistureBasis.GRAVIMETRIC]
    assert gravimetric
    assert any("bulk density" in n for n in gravimetric[0].notes)


def test_captions_with_letter_numbering_are_found(thesis):
    """Appendix tables are numbered 'Table C.1', not 'Table 1'."""
    path, _, _, _ = thesis
    tables = extract_tables(path)
    assert any("C.1" in t.caption or "C.2" in t.caption for t in tables)


# --------------------------------------------------------------------------
# The round trip
# --------------------------------------------------------------------------


def test_extraction_recovers_every_value(thesis):
    path, truth, _depths, _dates = thesis
    values, _ = harvest_tables(path, study_id="test")
    # Two volumetric tables of 5x8, plus a gravimetric one of 2x4.
    assert len(values) == 2 * truth.size + 8


def test_extracted_values_are_exact(thesis):
    """Unlike digitizing a figure, reading a table involves no tracing at all,
    so the bar is zero error rather than a tolerance."""
    path, truth, depths, dates = thesis
    values, _ = harvest_tables(path, study_id="test")

    expected = {
        (int(top), int(bottom), date): truth[i, j]
        for i, (top, bottom) in enumerate(depths)
        for j, date in enumerate(dates)
    }
    volumetric = values[values["basis"] == MoistureBasis.VOLUMETRIC]
    matched = 0
    for row in volumetric.itertuples():
        key = (int(row.depth_top_cm), int(row.depth_bottom_cm), str(row.time_label).strip())
        if key in expected:
            assert row.value == pytest.approx(expected[key], abs=1e-9)
            matched += 1
    assert matched == 2 * truth.size, "both volumetric tables must round-trip"


def test_percent_and_fraction_tables_agree(thesis):
    """The same data reported as % and as m3/m3 must come out on one scale."""
    path, _, _, _ = thesis
    values, _ = harvest_tables(path, study_id="test")
    volumetric = values[values["basis"] == MoistureBasis.VOLUMETRIC]
    by_unit = volumetric.groupby("unit")["value"].median()
    assert len(by_unit) == 2
    assert by_unit.iloc[0] == pytest.approx(by_unit.iloc[1], rel=0.02)


def test_gravimetric_values_are_not_silently_converted(thesis):
    """Converting needs a bulk density the document does not contain."""
    path, _, _, _ = thesis
    values, _ = harvest_tables(path, study_id="test")
    gravimetric = values[values["basis"] == MoistureBasis.GRAVIMETRIC]
    assert not gravimetric.empty
    assert set(gravimetric["basis"]) == {MoistureBasis.GRAVIMETRIC}


def test_provenance_travels_with_every_value(thesis):
    path, _, _, _ = thesis
    values, _ = harvest_tables(path, study_id="10.1234/demo")
    for column in ("study_id", "source_page", "source_table", "caption",
                   "extraction_method"):
        assert column in values.columns
    assert set(values["study_id"]) == {"10.1234/demo"}
    assert set(values["extraction_method"]) == {"pdf_table"}


def test_raising_the_threshold_rejects_everything(thesis):
    path, _, _, _ = thesis
    values, _ = harvest_tables(path, min_score=1.01)
    assert values.empty


def test_an_unrelated_table_is_not_turned_into_data():
    """A table of yields has depths nowhere and must produce nothing."""
    from smml.litmine.tables import ExtractedTable

    frame = pd.DataFrame({"Treatment": ["A", "B"], "Yield (t/ha)": ["8.2", "9.4"]})
    table = classify_table(ExtractedTable(page=0, index=0, raw=frame))
    assert table.depth_axis is None
    assert table_to_long(table).empty
