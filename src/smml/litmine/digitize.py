"""Recovering numeric data from published figures.

A large share of the world's irrigated-field soil moisture record exists only as
ink: a time series plotted in a paper whose underlying numbers were never
archived. Recovering those numbers is the difference between a database of a few
hundred instrumented stations and one spanning every field study ever published.

The module works in two modes, and the order matters because the first is exact
and the second is not.

**Vector extraction.** A figure produced by matplotlib, R, gnuplot, Origin or
Excel and embedded in a PDF as vector graphics still contains the polyline
coordinates of every plotted series, in PDF user space. Reading those drawing
operators and applying the axis transform recovers the original data to floating
point precision — not an estimate of it. This should always be tried first, and
on a modern paper it usually succeeds. It is, as far as digitization goes, free
and perfect.

**Raster tracing.** A scanned page, a bitmap figure, or a PDF whose figure was
rasterized before embedding leaves only pixels. Then the axes have to be located,
the tick labels read, the pixel-to-data transform fitted, and each series
separated by colour and traced. Every step introduces error, and the module's job
is as much to *quantify* that error as to minimize it: every returned point
carries an uncertainty derived from the pixel resolution and the axis calibration
residual, and those propagate into the database as observation uncertainty and
into training as sample weights.

Nothing here is trusted blindly. :func:`validate_series` applies physical and
structural checks, and the recommended workflow is to digitize automatically,
screen with those checks, and review by eye only what fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass
class AxisCalibration:
    """The affine (or log-affine) map from pixel to data coordinates.

    ``residual_px`` is the RMS of the fit over the reference points used. It is
    the primary indicator of whether the calibration can be trusted: a
    well-detected axis fits to a fraction of a pixel, while a residual of several
    pixels means a tick was misread and every value derived from it is wrong.
    """

    x_pixels: np.ndarray
    x_values: np.ndarray
    y_pixels: np.ndarray
    y_values: np.ndarray
    x_log: bool = False
    y_log: bool = False
    residual_px: float = 0.0

    def _fit(self, pixels: np.ndarray, values: np.ndarray, log_scale: bool):
        v = np.log10(values) if log_scale else values
        if len(pixels) < 2:
            raise ValueError("need at least two reference points per axis")
        slope, intercept = np.polyfit(pixels, v, 1)
        return slope, intercept

    def to_data(self, px: np.ndarray, py: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        sx, ix = self._fit(self.x_pixels, self.x_values, self.x_log)
        sy, iy = self._fit(self.y_pixels, self.y_values, self.y_log)
        x = sx * np.asarray(px, dtype=float) + ix
        y = sy * np.asarray(py, dtype=float) + iy
        if self.x_log:
            x = 10.0**x
        if self.y_log:
            y = 10.0**y
        return x, y

    def data_per_pixel(self) -> tuple[float, float]:
        """Data units spanned by one pixel — the resolution floor on any value."""
        sx, _ = self._fit(self.x_pixels, self.x_values, self.x_log)
        sy, _ = self._fit(self.y_pixels, self.y_values, self.y_log)
        return abs(float(sx)), abs(float(sy))


@dataclass
class DigitizedSeries:
    """One extracted curve, with provenance and uncertainty."""

    label: str
    x: np.ndarray
    y: np.ndarray
    method: str
    x_uncertainty: float = 0.0
    y_uncertainty: float = 0.0
    colour: tuple[int, int, int] | None = None
    n_points: int = 0
    calibration_residual_px: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.n_points = len(self.x)

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_label": self.label,
            "x_values": self.x.tolist(),
            "y_values": self.y.tolist(),
            "extraction_method": self.method,
            "y_uncertainty_data_units": float(self.y_uncertainty),
            "axis_calibration_rmse_px": float(self.calibration_residual_px),
            "n_points": int(self.n_points),
            "validation_notes": "; ".join(self.warnings),
        }

    def resample(self, x_grid: np.ndarray) -> DigitizedSeries:
        """Interpolate onto a regular grid, monotone in x.

        Traced curves come out unevenly spaced (a steep segment yields fewer
        x-distinct pixels than a flat one). Resampling makes series from
        different figures commensurable.
        """
        order = np.argsort(self.x)
        xs, ys = self.x[order], self.y[order]
        keep = np.concatenate([[True], np.diff(xs) > 0])
        y_new = np.interp(x_grid, xs[keep], ys[keep], left=np.nan, right=np.nan)
        return DigitizedSeries(
            label=self.label, x=np.asarray(x_grid, dtype=float), y=y_new,
            method=self.method + "+resampled", x_uncertainty=self.x_uncertainty,
            y_uncertainty=self.y_uncertainty, colour=self.colour,
            calibration_residual_px=self.calibration_residual_px, warnings=list(self.warnings),
        )


# --------------------------------------------------------------------------
# Vector extraction — exact
# --------------------------------------------------------------------------


def extract_vector_paths(
    pdf_path: Path | str,
    page_number: int = 0,
    clip: tuple[float, float, float, float] | None = None,
    min_points: int = 5,
) -> list[dict[str, Any]]:
    """Read polyline drawing operators from a PDF page.

    Returns one entry per stroked path with its point coordinates in PDF user
    space, its stroke colour and width. These are the *exact* coordinates the
    plotting library emitted, so combined with an axis calibration they recover
    the original data without digitization error.

    ``clip`` restricts to a rectangle ``(x0, y0, x1, y1)`` in page coordinates,
    which is how a single panel is isolated from a multi-panel figure.
    """
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf

    doc = pymupdf.open(str(pdf_path))
    try:
        page = doc[page_number]
        out = []
        for drawing in page.get_drawings():
            points: list[tuple[float, float]] = []
            for item in drawing["items"]:
                op = item[0]
                if op == "l":            # line segment
                    points.extend([(item[1].x, item[1].y), (item[2].x, item[2].y)])
                elif op == "c":          # cubic bezier — keep the anchors
                    points.extend([(item[1].x, item[1].y), (item[4].x, item[4].y)])
                elif op == "re":         # rectangle: frames, bars, markers
                    r = item[1]
                    points.extend([(r.x0, r.y0), (r.x1, r.y1)])
            if len(points) < min_points:
                continue
            arr = np.array(points, dtype=float)
            if clip is not None:
                x0, y0, x1, y1 = clip
                inside = (
                    (arr[:, 0] >= x0) & (arr[:, 0] <= x1)
                    & (arr[:, 1] >= y0) & (arr[:, 1] <= y1)
                )
                arr = arr[inside]
                if len(arr) < min_points:
                    continue
            out.append({
                "points": arr,
                "colour": drawing.get("color"),
                "fill": drawing.get("fill"),
                "width": drawing.get("width"),
                "n_points": len(arr),
            })
        return out
    finally:
        doc.close()


def dedupe_polyline(points: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    """Collapse the duplicated segment endpoints a path emits."""
    if len(points) == 0:
        return points
    keep = [0]
    for i in range(1, len(points)):
        if np.hypot(*(points[i] - points[keep[-1]])) > tol:
            keep.append(i)
    return points[keep]


# --------------------------------------------------------------------------
# Raster extraction
# --------------------------------------------------------------------------


def detect_plot_frame(image: np.ndarray, darkness: float = 0.45) -> tuple[int, int, int, int] | None:
    """Locate the axes rectangle by projection profiles.

    Axis spines are the longest dark runs in the image, so the rows and columns
    whose dark-pixel fraction spikes give the frame directly. More robust on
    scientific figures than a Hough transform, which is easily distracted by grid
    lines and by dense data.

    Returns ``(left, top, right, bottom)`` in pixels, or ``None`` if no frame is
    evident — which usually means a frameless style, and the caller must supply
    the calibration points itself.
    """
    grey = image if image.ndim == 2 else image.mean(axis=2)
    dark = grey < (grey.max() * 0.6)
    col_frac = dark.mean(axis=0)
    row_frac = dark.mean(axis=1)

    col_hits = np.where(col_frac > darkness)[0]
    row_hits = np.where(row_frac > darkness)[0]
    if len(col_hits) < 2 or len(row_hits) < 2:
        return None
    return int(col_hits.min()), int(row_hits.min()), int(col_hits.max()), int(row_hits.max())


def _column_runs(column_mask: np.ndarray, max_gap: int = 2) -> list[tuple[float, int]]:
    """Contiguous runs of set pixels in one image column, as (centre, length)."""
    rows = np.where(column_mask)[0]
    if len(rows) == 0:
        return []
    runs = []
    start = prev = rows[0]
    for r in rows[1:]:
        if r - prev <= max_gap:
            prev = r
            continue
        runs.append(((start + prev) / 2.0, int(prev - start + 1)))
        start = prev = r
    runs.append(((start + prev) / 2.0, int(prev - start + 1)))
    return runs


def trace_by_continuity(
    mask: np.ndarray,
    jump_penalty: float = 1.0,
    length_bonus: float = 2.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Follow a curve across the image by choosing the smoothest path.

    Per-column median fails on two structures that occur in almost every real
    figure. A **legend** sits inside the axes and its swatch is the same colour
    as the series, so wherever they share a column the median is pulled toward
    it. A **crossing** with another series breaks the curve into pieces, which
    defeats simple largest-component filtering because a broken piece can be
    smaller than the swatch.

    Both are solved by treating tracing as a shortest-path problem. Each column
    offers a few candidate runs of matching pixels; a dynamic program picks one
    per column minimizing

        sum_t  jump_penalty * |y_t - y_{t-1}|  -  length_bonus * len(run_t)

    so the path prefers to continue smoothly and to sit on thick evidence. A
    legend swatch is only reachable by a large vertical jump and so is never
    chosen; a curve interrupted by a crossing is rejoined because resuming at
    the same height is far cheaper than any alternative.

    Returns the pixel coordinates of the traced path.
    """
    n_cols = mask.shape[1]
    candidates: list[list[tuple[float, int]]] = [
        _column_runs(mask[:, c]) for c in range(n_cols)
    ]
    active = [c for c in range(n_cols) if candidates[c]]
    if not active:
        return np.array([]), np.array([])

    prev_costs: np.ndarray | None = None
    prev_centres: np.ndarray | None = None
    backptr: list[np.ndarray] = []
    centres_per_col: list[np.ndarray] = []

    for c in active:
        centres = np.array([r[0] for r in candidates[c]], dtype=float)
        lengths = np.array([r[1] for r in candidates[c]], dtype=float)
        local = -length_bonus * lengths
        if prev_costs is None:
            costs = local
            backptr.append(np.full(len(centres), -1, dtype=int))
        else:
            transition = jump_penalty * np.abs(centres[:, None] - prev_centres[None, :])
            total = transition + prev_costs[None, :]
            choice = np.argmin(total, axis=1)
            costs = total[np.arange(len(centres)), choice] + local
            backptr.append(choice)
        centres_per_col.append(centres)
        prev_costs, prev_centres = costs, centres

    # Walk the pointers back from the cheapest endpoint.
    path = np.empty(len(active), dtype=int)
    path[-1] = int(np.argmin(prev_costs))
    for i in range(len(active) - 1, 0, -1):
        path[i - 1] = backptr[i][path[i]]

    xs = np.array(active, dtype=float)
    ys = np.array([centres_per_col[i][path[i]] for i in range(len(active))], dtype=float)
    return xs, ys


def extract_series_by_colour(
    image: np.ndarray,
    target_rgb: tuple[int, int, int],
    tolerance: float = 40.0,
    frame: tuple[int, int, int, int] | None = None,
    min_pixels_per_column: int = 1,
    min_component_fraction: float = 0.05,
    trace: str = "continuity",
    return_mask: bool = False,
):
    """Trace one coloured series, returning pixel coordinates.

    Matching is done in CIELAB rather than RGB. Perceptual distance in Lab
    corresponds much better to "the same series drawn with anti-aliasing" than
    Euclidean RGB distance does, so a single tolerance works across the light and
    dark colours in a default palette instead of needing per-colour tuning.

    The matched pixels are then filtered by connected component (dropping
    anything below ``min_component_fraction`` of the largest, which removes tick
    marks and stray glyphs) and traced by :func:`trace_by_continuity`, which is
    what actually handles legends and series crossings — see that function for
    why a per-column median does not. ``trace="median"`` selects the simpler
    behaviour for comparison.
    """
    from skimage.color import rgb2lab
    from skimage.measure import label

    rgb = image[:, :, :3].astype(np.float64) / 255.0
    lab = rgb2lab(rgb)
    target_lab = rgb2lab(np.array(target_rgb, dtype=np.float64).reshape(1, 1, 3) / 255.0)[0, 0]
    distance = np.linalg.norm(lab - target_lab, axis=2)
    mask = distance < tolerance

    if frame is not None:
        left, top, right, bottom = frame
        window = np.zeros_like(mask)
        window[top : bottom + 1, left : right + 1] = True
        mask &= window

    if mask.any() and min_component_fraction > 0:
        labelled = label(mask, connectivity=2)
        sizes = np.bincount(labelled.ravel())
        sizes[0] = 0  # background
        if sizes.max() > 0:
            keep_ids = np.where(sizes >= sizes.max() * min_component_fraction)[0]
            mask = np.isin(labelled, keep_ids)

    if trace == "continuity":
        x_arr, y_arr = trace_by_continuity(mask)
    elif trace == "median":
        xs, ys = [], []
        for col in range(mask.shape[1]):
            rows = np.where(mask[:, col])[0]
            if len(rows) >= min_pixels_per_column:
                xs.append(col)
                ys.append(float(np.median(rows)))
        x_arr, y_arr = np.array(xs, dtype=float), np.array(ys, dtype=float)
    else:
        raise ValueError(f"trace must be 'continuity' or 'median'; got {trace!r}")

    if return_mask:
        return x_arr, y_arr, mask
    return x_arr, y_arr


def detect_series_colours(
    image: np.ndarray,
    frame: tuple[int, int, int, int] | None = None,
    max_series: int = 8,
    min_fraction: float = 0.0004,
    saturation_threshold: float = 0.45,
    value_threshold: float = 0.20,
    hue_merge_deg: float = 25.0,
) -> list[tuple[int, int, int]]:
    """Find the distinct plotted colours, clustering by **hue**.

    Clustering on RGB proximity does not work here. Anti-aliasing blends every
    line toward the page background, so a single red curve deposits a whole ramp
    from saturated red to near-white; in RGB those tints are far apart and get
    counted as separate series. In hue they are all the same angle, and only the
    saturation differs. Clustering by hue and then taking the most saturated
    member of each cluster as the representative recovers one colour per series.

    Greys are excluded by the saturation floor: axes, text, grid lines and error
    bars are almost always achromatic while data series almost always are not.
    That assumption fails for a monochrome print figure, where the caller must
    pass the series colours (or line styles) explicitly.
    """
    from matplotlib.colors import rgb_to_hsv

    rgb = image[:, :, :3].astype(np.float64)
    if frame is not None:
        left, top, right, bottom = frame
        rgb = rgb[top : bottom + 1, left : right + 1]
    total = rgb.shape[0] * rgb.shape[1]
    hsv = rgb_to_hsv(rgb / 255.0).reshape(-1, 3)
    flat = rgb.reshape(-1, 3)

    keep = (hsv[:, 1] > saturation_threshold) & (hsv[:, 2] > value_threshold)
    if not keep.any():
        return []
    hues = hsv[keep, 0] * 360.0
    sats = hsv[keep, 1]
    colours = flat[keep]

    # Histogram hue into 2-degree bins and take the peaks.
    bins = np.arange(0, 362, 2.0)
    counts, _ = np.histogram(hues, bins=bins)
    order = np.argsort(-counts)

    chosen_hues: list[float] = []
    out: list[tuple[int, int, int]] = []
    for b in order:
        if counts[b] / total < min_fraction:
            break
        centre = (bins[b] + bins[b + 1]) / 2.0
        # Circular distance to an already-accepted hue.
        if any(min(abs(centre - h), 360 - abs(centre - h)) < hue_merge_deg for h in chosen_hues):
            continue
        delta = np.abs(hues - centre)
        member = np.minimum(delta, 360 - delta) < hue_merge_deg
        if not member.any():
            continue
        # Representative = the most saturated pixel of the cluster, which is the
        # line's own colour rather than one of its anti-aliased tints.
        best = np.argmax(sats[member])
        out.append(tuple(int(v) for v in colours[member][best]))
        chosen_hues.append(centre)
        if len(out) >= max_series:
            break
    return out


def _column_spread(
    image: np.ndarray,
    target_rgb: tuple[int, int, int],
    tolerance: float,
    frame: tuple[int, int, int, int] | None,
) -> float:
    """Median vertical extent, in pixels, of a series within one image column.

    A clean single line spans two or three pixels. A column where two series of
    the same detected colour overlap, or where the curve is near-vertical, spans
    many more. The median over columns is a robust summary of how ambiguous the
    trace is, and feeds the reported uncertainty.
    """
    _, _, mask = extract_series_by_colour(
        image, target_rgb, tolerance=tolerance, frame=frame, return_mask=True
    )
    spreads = []
    for col in range(mask.shape[1]):
        rows = np.where(mask[:, col])[0]
        if len(rows):
            spreads.append(float(rows.max() - rows.min() + 1))
    return float(np.median(spreads)) if spreads else 1.0


def digitize_raster(
    image: np.ndarray,
    calibration: AxisCalibration,
    frame: tuple[int, int, int, int] | None = None,
    colours: list[tuple[int, int, int]] | None = None,
    labels: list[str] | None = None,
    tolerance: float = 40.0,
) -> list[DigitizedSeries]:
    """Digitize every coloured series in a raster plot."""
    if frame is None:
        frame = detect_plot_frame(image)
    if colours is None:
        colours = detect_series_colours(image, frame=frame)

    dx, dy = calibration.data_per_pixel()
    out = []
    for i, colour in enumerate(colours):
        px, py = extract_series_by_colour(image, colour, tolerance=tolerance, frame=frame)
        if len(px) < 5:
            continue
        x, y = calibration.to_data(px, py)
        label = labels[i] if labels and i < len(labels) else f"series_{i + 1}"
        warnings = []
        if calibration.residual_px > 2.0:
            warnings.append(f"axis calibration residual {calibration.residual_px:.1f} px")
        if len(px) < 20:
            warnings.append(f"only {len(px)} points recovered")
        # Uncertainty combines the calibration resolution with the measured
        # vertical spread of the matched pixels in each column, which is the
        # drawn line width and widens wherever two series cross. Taking the
        # resolution alone understates the real error by an order of magnitude
        # at crossings, which is exactly where a reader would not trust the
        # figure either.
        spread_px = _column_spread(image, colour, tolerance, frame)
        y_unc = float(np.hypot(dy * 2.0, dy * spread_px))
        out.append(DigitizedSeries(
            label=label, x=x, y=y, method="raster_colour_trace",
            x_uncertainty=dx * 2.0, y_uncertainty=y_unc,
            colour=colour, calibration_residual_px=calibration.residual_px,
            warnings=warnings,
        ))
    return out


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_series(
    series: DigitizedSeries,
    y_range: tuple[float, float] | None = (0.0, 0.7),
    max_jump: float | None = 0.25,
    min_points: int = 10,
) -> tuple[bool, list[str]]:
    """Screen a digitized series against physical and structural expectations.

    Defaults are for volumetric water content. The checks catch the failure modes
    that actually occur: a misread axis label (values outside any possible range),
    a trace jumping between two overlapping series (impossible day-to-day steps),
    and a series that was mostly not found (too few points).
    """
    problems: list[str] = []
    y = series.y[np.isfinite(series.y)]

    if len(y) < min_points:
        problems.append(f"only {len(y)} valid points")
    if y_range is not None and len(y):
        lo, hi = y_range
        outside = np.mean((y < lo) | (y > hi))
        if outside > 0.02:
            problems.append(f"{outside:.0%} of values outside [{lo}, {hi}]")
    if max_jump is not None and len(y) > 2:
        jumps = np.abs(np.diff(y))
        if np.nanmax(jumps) > max_jump:
            problems.append(f"largest step {np.nanmax(jumps):.3f} exceeds {max_jump}")
    if len(series.x) > 1 and not np.all(np.diff(np.sort(series.x)) >= 0):
        problems.append("x values are not orderable")
    if series.calibration_residual_px > 3.0:
        problems.append(f"poor axis calibration ({series.calibration_residual_px:.1f} px)")

    return (not problems), problems


def calibration_from_frame(
    frame: tuple[int, int, int, int],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    x_log: bool = False,
    y_log: bool = False,
) -> AxisCalibration:
    """Build a calibration from the plot frame and the axis limits.

    The common case when the figure is generated by a known tool or the limits
    are stated in the caption. Note the y inversion: image rows increase
    downward, data values increase upward.
    """
    left, top, right, bottom = frame
    return AxisCalibration(
        x_pixels=np.array([left, right], dtype=float),
        x_values=np.array([x_min, x_max], dtype=float),
        y_pixels=np.array([bottom, top], dtype=float),
        y_values=np.array([y_min, y_max], dtype=float),
        x_log=x_log, y_log=y_log, residual_px=0.0,
    )
