"""Figure digitization tests.

Every test is a round trip: plot data whose values are known exactly, digitize
the resulting image or PDF, and measure how much was lost. That is the only
honest way to test a digitizer, and it also fixes the numbers quoted elsewhere
about how accurate the extraction is.

The accuracy bar is set against what the data is for. A dielectric soil moisture
sensor is accurate to roughly 0.02-0.035 m3/m3; an extraction whose error is an
order of magnitude below that adds no meaningful uncertainty to the database.
"""

from __future__ import annotations

import numpy as np
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from smml.litmine.digitize import (  # noqa: E402
    DigitizedSeries,
    calibration_from_frame,
    dedupe_polyline,
    detect_plot_frame,
    detect_series_colours,
    digitize_raster,
    extract_series_by_colour,
    extract_vector_paths,
    trace_by_continuity,
    validate_series,
)

DAYS = np.arange(0, 180, 1.0)
PALETTE = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd"]
Y_LIMITS = (0.10, 0.45)


def make_truth(n_series: int = 3, seed: int = 0) -> dict[str, np.ndarray]:
    """Soil-moisture-shaped series: seasonal swing plus measurement noise."""
    rng = np.random.default_rng(seed)
    specs = [("5 cm", 0.22, 0.09), ("20 cm", 0.28, 0.05),
             ("50 cm", 0.33, 0.025), ("100 cm", 0.37, 0.012)]
    return {
        label: base + amp * np.sin(2 * np.pi * DAYS / 45 + i) + 0.004 * rng.standard_normal(len(DAYS))
        for i, (label, base, amp) in enumerate(specs[:n_series])
    }


def render(truth: dict[str, np.ndarray], path, legend: bool = True, dpi: int = 110) -> None:
    fig, ax = plt.subplots(figsize=(8, 5), dpi=dpi)
    for (label, y), colour in zip(truth.items(), PALETTE, strict=False):
        ax.plot(DAYS, y, color=colour, lw=1.8, label=label)
    ax.set_xlim(DAYS.min(), DAYS.max())
    ax.set_ylim(*Y_LIMITS)
    ax.set_xlabel("Day of year")
    ax.set_ylabel("Volumetric water content")
    if legend:
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def load(path) -> np.ndarray:
    from PIL import Image

    return np.array(Image.open(path).convert("RGB"))


def match_and_error(series: DigitizedSeries, truth: dict[str, np.ndarray]) -> tuple[str, np.ndarray]:
    """Pair a digitized series with the truth series it is closest to."""
    grid = np.arange(DAYS.min() + 5, DAYS.max() - 5, 1.0)
    resampled = series.resample(grid).y
    best = min(truth, key=lambda k: np.nanmean((np.interp(grid, DAYS, truth[k]) - resampled) ** 2))
    return best, resampled - np.interp(grid, DAYS, truth[best])


# --------------------------------------------------------------------------
# Frame and colour detection
# --------------------------------------------------------------------------


def test_detects_the_plot_frame(tmp_path):
    png = tmp_path / "f.png"
    render(make_truth(), png)
    image = load(png)
    frame = detect_plot_frame(image)
    assert frame is not None
    left, top, right, bottom = frame
    assert 0 < left < right < image.shape[1]
    assert 0 < top < bottom < image.shape[0]
    # The axes should occupy most of a tight-layout figure.
    assert (right - left) > 0.6 * image.shape[1]


@pytest.mark.parametrize("n_series", [2, 3, 4])
def test_detects_exactly_one_colour_per_series(tmp_path, n_series):
    """Anti-aliasing must not be counted as extra series.

    This is the bug hue clustering exists to fix: RGB-proximity clustering
    reported seven series for a three-series plot, because each line deposits a
    ramp of tints toward the white background.
    """
    png = tmp_path / "f.png"
    truth = make_truth(n_series)
    render(truth, png)
    image = load(png)
    colours = detect_series_colours(image, frame=detect_plot_frame(image))
    assert len(colours) == n_series


# --------------------------------------------------------------------------
# Raster round trip
# --------------------------------------------------------------------------


def test_raster_round_trip_recovers_values_below_sensor_accuracy(tmp_path):
    png = tmp_path / "f.png"
    truth = make_truth(3)
    render(truth, png)
    image = load(png)
    frame = detect_plot_frame(image)
    calibration = calibration_from_frame(frame, DAYS.min(), DAYS.max(), *Y_LIMITS)

    series = digitize_raster(image, calibration, frame=frame)
    assert len(series) == 3

    recovered = set()
    for s in series:
        label, err = match_and_error(s, truth)
        recovered.add(label)
        rmse = float(np.sqrt(np.nanmean(err**2)))
        # An order of magnitude better than any dielectric sensor.
        assert rmse < 0.005, f"{label}: RMSE {rmse}"
        assert float(np.nanmax(np.abs(err))) < 0.02, f"{label}: max error"
    assert recovered == set(truth), "each plotted series must be recovered exactly once"


def test_continuity_tracing_beats_median_when_a_legend_overlaps_the_curve(tmp_path):
    """The legend swatch is the same colour as the series and sits inside the axes.

    A per-column median is dragged onto it wherever they share a column. The
    Viterbi trace cannot reach it without a large vertical jump, so it does not.
    """
    png = tmp_path / "f.png"
    truth = make_truth(3)
    render(truth, png, legend=True)
    image = load(png)
    frame = detect_plot_frame(image)
    calibration = calibration_from_frame(frame, DAYS.min(), DAYS.max(), *Y_LIMITS)
    colours = detect_series_colours(image, frame=frame)

    worst = {}
    for method in ("median", "continuity"):
        errors = []
        for colour in colours:
            px, py = extract_series_by_colour(image, colour, frame=frame, trace=method)
            if len(px) < 5:
                continue
            x, y = calibration.to_data(px, py)
            _, err = match_and_error(DigitizedSeries("s", x, y, method), truth)
            errors.append(float(np.nanmax(np.abs(err))))
        worst[method] = max(errors)

    assert worst["continuity"] < worst["median"]
    assert worst["continuity"] < 0.02


def test_legend_swatch_is_not_traced(tmp_path):
    """With and without a legend, the extraction must agree."""
    truth = make_truth(3)
    results = {}
    for tag, legend in (("with", True), ("without", False)):
        png = tmp_path / f"{tag}.png"
        render(truth, png, legend=legend)
        image = load(png)
        frame = detect_plot_frame(image)
        calibration = calibration_from_frame(frame, DAYS.min(), DAYS.max(), *Y_LIMITS)
        errs = {}
        for s in digitize_raster(image, calibration, frame=frame):
            label, err = match_and_error(s, truth)
            errs[label] = float(np.sqrt(np.nanmean(err**2)))
        results[tag] = errs
    for label in truth:
        assert results["with"][label] == pytest.approx(results["without"][label], abs=0.003), label


@pytest.mark.parametrize("dpi", [72, 110, 200])
def test_accuracy_improves_with_resolution(tmp_path, dpi):
    png = tmp_path / f"f{dpi}.png"
    truth = make_truth(2)
    render(truth, png, dpi=dpi)
    image = load(png)
    frame = detect_plot_frame(image)
    calibration = calibration_from_frame(frame, DAYS.min(), DAYS.max(), *Y_LIMITS)
    series = digitize_raster(image, calibration, frame=frame)
    assert len(series) == 2
    for s in series:
        _, err = match_and_error(s, truth)
        assert float(np.sqrt(np.nanmean(err**2))) < 0.01


def test_reported_uncertainty_is_not_wildly_optimistic(tmp_path):
    """A stated uncertainty that the actual error routinely exceeds is worse than none."""
    png = tmp_path / "f.png"
    truth = make_truth(3)
    render(truth, png)
    image = load(png)
    frame = detect_plot_frame(image)
    calibration = calibration_from_frame(frame, DAYS.min(), DAYS.max(), *Y_LIMITS)
    for s in digitize_raster(image, calibration, frame=frame):
        _, err = match_and_error(s, truth)
        rmse = float(np.sqrt(np.nanmean(err**2)))
        assert s.y_uncertainty > 0
        assert s.y_uncertainty >= rmse * 0.5, "stated uncertainty understates the error"
        assert s.y_uncertainty < 0.05, "stated uncertainty is uselessly wide"


# --------------------------------------------------------------------------
# Vector extraction
# --------------------------------------------------------------------------


def test_vector_extraction_finds_one_path_per_series(tmp_path):
    pdf = tmp_path / "f.pdf"
    truth = make_truth(3)
    render(truth, pdf)
    paths = extract_vector_paths(pdf, 0, min_points=50)
    long_paths = [p for p in paths if p["n_points"] >= len(DAYS) - 10]
    assert len(long_paths) == 3


def test_vector_extraction_preserves_the_point_count(tmp_path):
    """Vector paths carry the original vertices, so the count must survive."""
    pdf = tmp_path / "f.pdf"
    render(make_truth(1), pdf, legend=False)
    paths = extract_vector_paths(pdf, 0, min_points=50)
    best = max(paths, key=lambda p: p["n_points"])
    assert len(dedupe_polyline(best["points"])) == pytest.approx(len(DAYS), abs=5)


def test_vector_round_trip_is_exact(tmp_path):
    """Calibrated against the axis limits, vector extraction should be near-exact.

    'Near' only because the path vertices are the plotted points and the axis
    limits are known to full precision; there is no pixel quantization at all,
    so the residual is pure floating point and PDF coordinate rounding.
    """
    pdf = tmp_path / "f.pdf"
    truth = make_truth(1)
    y_true = next(iter(truth.values()))
    render(truth, pdf, legend=False)

    paths = extract_vector_paths(pdf, 0, min_points=50)
    points = dedupe_polyline(max(paths, key=lambda p: p["n_points"])["points"])
    points = points[np.argsort(points[:, 0])]

    # Map the path's own extent onto the known axis limits. PDF y grows upward
    # in user space but PyMuPDF reports page coordinates with y growing down,
    # so the y reference pair is inverted relative to the data.
    from smml.litmine.digitize import AxisCalibration

    calibration = AxisCalibration(
        x_pixels=np.array([points[:, 0].min(), points[:, 0].max()]),
        x_values=np.array([DAYS.min(), DAYS.max()]),
        y_pixels=np.array([points[:, 1].max(), points[:, 1].min()]),
        y_values=np.array([y_true.min(), y_true.max()]),
    )
    x, y = calibration.to_data(points[:, 0], points[:, 1])
    err = y - np.interp(x, DAYS, y_true)
    assert float(np.sqrt(np.mean(err**2))) < 1e-3


# --------------------------------------------------------------------------
# Tracing and validation units
# --------------------------------------------------------------------------


def test_trace_by_continuity_ignores_an_isolated_blob():
    mask = np.zeros((100, 60), dtype=bool)
    mask[50:52, :] = True        # the curve: a flat line across every column
    mask[10:12, 20:28] = True    # a legend swatch, far above, in some columns
    xs, ys = trace_by_continuity(mask)
    assert len(xs) == 60
    assert np.allclose(ys, 50.5, atol=0.6)


def test_trace_by_continuity_rejoins_across_a_gap():
    mask = np.zeros((100, 60), dtype=bool)
    mask[50:52, :] = True
    mask[50:52, 28:32] = False   # a crossing erased four columns
    xs, ys = trace_by_continuity(mask)
    assert len(xs) == 56
    assert np.allclose(ys, 50.5, atol=0.6)


def test_validate_series_rejects_impossible_values():
    s = DigitizedSeries("x", np.arange(50.0), np.full(50, 0.9), "test")
    ok, problems = validate_series(s)
    assert not ok
    assert any("outside" in p for p in problems)


def test_validate_series_rejects_impossible_jumps():
    y = np.full(50, 0.25)
    y[25] = 0.65
    s = DigitizedSeries("x", np.arange(50.0), y, "test")
    ok, problems = validate_series(s)
    assert not ok
    assert any("step" in p for p in problems)


def test_validate_series_accepts_a_plausible_curve():
    y = 0.25 + 0.05 * np.sin(np.linspace(0, 6, 100))
    s = DigitizedSeries("x", np.arange(100.0), y, "test")
    ok, problems = validate_series(s)
    assert ok, problems


def test_resample_puts_series_on_a_common_grid():
    s = DigitizedSeries("x", np.array([0.0, 1.0, 5.0, 9.0]), np.array([0.1, 0.2, 0.3, 0.4]), "test")
    grid = np.arange(0.0, 10.0, 1.0)
    r = s.resample(grid)
    assert len(r.x) == len(grid)
    assert r.y[0] == pytest.approx(0.1)
    assert np.isnan(r.y[-1]) or r.y[-1] <= 0.4


def test_calibration_inverts_the_pixel_transform():
    calibration = calibration_from_frame((100, 50, 900, 550), 0.0, 180.0, 0.10, 0.45)
    x, y = calibration.to_data(np.array([100.0, 900.0]), np.array([550.0, 50.0]))
    assert x == pytest.approx([0.0, 180.0])
    assert y == pytest.approx([0.10, 0.45])


def test_calibration_reports_its_resolution():
    calibration = calibration_from_frame((100, 50, 900, 550), 0.0, 180.0, 0.10, 0.45)
    dx, dy = calibration.data_per_pixel()
    assert dx == pytest.approx(180.0 / 800.0)
    assert dy == pytest.approx(0.35 / 500.0)


def test_log_axis_calibration():
    from smml.litmine.digitize import AxisCalibration

    calibration = AxisCalibration(
        x_pixels=np.array([0.0, 100.0]), x_values=np.array([1.0, 1000.0]),
        y_pixels=np.array([100.0, 0.0]), y_values=np.array([0.1, 1.0]),
        x_log=True, y_log=True,
    )
    x, y = calibration.to_data(np.array([50.0]), np.array([50.0]))
    assert float(x[0]) == pytest.approx(31.62, rel=1e-3)   # 10^1.5
    assert float(y[0]) == pytest.approx(0.3162, rel=1e-3)
