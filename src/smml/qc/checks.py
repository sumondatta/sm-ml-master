"""Quality control for a heterogeneous soil moisture corpus.

Data assembled from hundreds of sources contains every failure a soil moisture
sensor can have: probes that flatline, probes that drift, probes reading through
frozen soil, values recorded in the wrong unit, and values that are simply
physically impossible for the soil they sit in. None of it is labelled.

The design choice throughout is **flag, never delete**. A reading that exceeds
porosity is suspicious, but the porosity it was compared against is usually
*estimated* from a texture class, and a bad estimate is at least as likely as a
bad reading. Dropping the observation destroys information; flagging it lets the
analyst decide, lets the flag itself become a model feature, and keeps the
decision auditable.

Flags follow :class:`~smml.db.schema.QualityFlag`, which mirrors the ISMN scheme
where it applies so that data arriving already flagged can be merged without
translation.

One check earns a special mention. :func:`detect_rise_without_input` finds
moisture increases that rainfall cannot explain. On a rainfed site that is a
sensor fault. On an irrigated field it is an **irrigation event** — which makes
the same computation both a quality check and the primary way to recover
irrigation scheduling for the very large number of studies that report soil
moisture but never state when water was applied.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..db.schema import METHOD_UNCERTAINTY, QualityFlag
from ..physics.dielectric import clay_bias, salinity_bias_risk

log = logging.getLogger(__name__)

#: Absolute bounds outside which a volumetric water content cannot be real,
#: whatever the soil. Anything beyond these is a unit error or a corrupt record.
HARD_MIN = 0.0
HARD_MAX = 0.75


def flag_physical_range(
    theta: pd.Series,
    porosity: pd.Series | float | None = None,
    tolerance: float = 0.03,
) -> pd.Series:
    """Flag values outside the physically possible range for the soil.

    The tolerance above porosity is deliberate: porosity is usually estimated
    from texture, real soils contain macropores, and a genuinely saturated
    profile routinely reads slightly above a pedotransfer porosity.
    """
    flags = pd.Series(QualityFlag.GOOD.value, index=theta.index, dtype=object)
    flags[theta.isna()] = QualityFlag.MISSING.value
    outside = (theta < HARD_MIN) | (theta > HARD_MAX)
    flags[outside & theta.notna()] = QualityFlag.OUT_OF_PHYSICAL_RANGE.value
    if porosity is not None:
        limit = (porosity + tolerance) if np.isscalar(porosity) else (porosity + tolerance)
        over = theta.notna() & (theta > limit) & ~outside
        flags[over] = QualityFlag.EXCEEDS_SATURATION.value
    return flags


def detect_spikes(
    theta: pd.Series,
    window: int = 25,
    n_sigma: float = 5.0,
    min_absolute: float = 0.05,
) -> pd.Series:
    """Flag isolated excursions from a rolling median.

    Both a robust threshold (``n_sigma`` times the rolling median absolute
    deviation) and an absolute floor must be exceeded. The absolute floor matters
    because a sensor sitting in a stable drydown has a very small MAD, and a
    sigma-only rule would then flag ordinary noise as spikes.
    """
    med = theta.rolling(window, center=True, min_periods=max(3, window // 3)).median()
    residual = theta - med
    mad = residual.abs().rolling(window, center=True, min_periods=max(3, window // 3)).median()
    scale = 1.4826 * mad  # MAD -> sigma for a normal distribution
    threshold = np.maximum(n_sigma * scale, min_absolute)
    return (residual.abs() > threshold) & theta.notna()


def detect_flatline(theta: pd.Series, min_length: int = 12, tolerance: float = 1e-6) -> pd.Series:
    """Flag runs of identical values — the signature of a dead or stuck sensor.

    Genuinely constant soil moisture over many consecutive readings does not
    occur in a field: even a deep layer under no drainage drifts. The exception
    is a value pinned at an instrument limit, which this also catches and should.
    """
    changed = theta.diff().abs() > tolerance
    run = changed.cumsum()
    sizes = theta.groupby(run).transform("size")
    return (sizes >= min_length) & theta.notna()


def detect_frozen(
    soil_temp_c: pd.Series | None,
    air_temp_c: pd.Series | None = None,
    threshold_c: float = 0.5,
) -> pd.Series:
    """Flag readings taken while the soil was at or below freezing.

    A dielectric sensor in frozen soil reads the permittivity of ice, about 3.2
    against liquid water's 80, so it reports a dramatic and entirely spurious
    drydown. This is the single most important mask for any site with a cold
    season and is the reason most soil moisture studies exclude winter outright.

    Soil temperature is used when available; air temperature is a poor proxy
    (soil lags and is insulated by snow) so a colder air threshold is applied.
    """
    if soil_temp_c is not None:
        return soil_temp_c.notna() & (soil_temp_c <= threshold_c)
    if air_temp_c is not None:
        return air_temp_c.notna() & (air_temp_c <= -2.0)
    return pd.Series(False, index=(soil_temp_c if soil_temp_c is not None else air_temp_c).index)


def detect_rise_without_input(
    theta: pd.Series,
    precip_mm: pd.Series | None,
    min_rise: float = 0.015,
    precip_threshold_mm: float = 1.0,
    lookback_days: int = 2,
) -> pd.Series:
    """Flag moisture increases that rainfall cannot account for.

    Water content cannot rise without water arriving. A rise with no rain in the
    preceding ``lookback_days`` is therefore either a sensor fault or an
    unrecorded input — and on agricultural land the unrecorded input is almost
    always irrigation.

    That makes this the project's irrigation-detection algorithm as well as a
    quality check. A very large share of published irrigated-field studies plot
    soil moisture without ever tabulating the irrigation schedule; recovering the
    events from the moisture record itself is often the only way to obtain them.
    See :func:`infer_irrigation_events` for the labelled form.

    The lookback matters: water applied late in the day shows at depth the next
    morning, so a same-day-only comparison misses real responses and produces
    false positives.
    """
    rise = theta.diff()
    if precip_mm is None:
        return (rise > min_rise) & theta.notna()
    recent = precip_mm.rolling(lookback_days + 1, min_periods=1).sum()
    return (rise > min_rise) & (recent < precip_threshold_mm) & theta.notna()


def detect_step_change(
    theta: pd.Series,
    water_input_mm: pd.Series | None = None,
    window: int = 30,
    min_shift: float = 0.05,
    revert_fraction: float = 0.5,
    persistence: float = 0.5,
    water_threshold_mm: float = 2.0,
    water_lag_days: int = 3,
) -> pd.Series:
    """Flag persistent level shifts — recalibration, reinstallation, a swapped probe.

    Works on the differenced series rather than on window means, which is what
    makes it robust to the thing it kept tripping over. Comparing the mean of the
    thirty days before a point with the mean of the thirty days after it sounds
    like a level-shift test, but on a soil that is drying through a season those
    means legitimately differ by far more than any fault threshold: on this
    project's corpus that formulation flagged 11 % of all observations.

    Instead, let ``d`` be the day-to-day change and ``b`` the local median of
    ``d`` — the ordinary drift rate at that time of year. The excess

        e_i = d_i - b_i

    is the part of the change that the prevailing trend does not account for. A
    seasonal drydown has ``e`` near zero however fast it is drying, because the
    drift rate absorbs it. A probe swap produces one large ``e`` and no
    corresponding return.

    That last clause is the second condition: a **spike** also produces a large
    ``e``, but it comes as an opposing pair — the excursion and the return. An
    excess adjacent to an opposing excess of more than ``revert_fraction`` of its
    size is therefore part of an outlier, not a step. Both neighbours are
    checked, because testing only the following day leaves the return itself
    reported as a downward step. Points independently identified as spikes are
    excluded too, the two diagnoses being mutually exclusive and the spike the
    more specific one.

    The third condition is **persistence**, and it is what makes the check usable
    on irrigated land specifically: an irrigation event is large, abrupt and not
    reverted the next day, so it satisfies everything above. What separates it
    from a probe swap is that the water drains away over the following days while
    an instrument offset stays. The level a full window later is therefore
    compared with the level before, after removing the drift expected over that
    span, and a shift that has decayed away is not reported.
    """
    d = theta.diff()
    span = 2 * window + 1
    drift = d.rolling(span, center=True, min_periods=max(5, window // 2)).median()
    excess = d - drift

    # A spike shows up as two adjacent, opposing excesses: the excursion and the
    # return. Both have to be excluded — checking only the following day leaves
    # the return itself flagged as a downward step.
    def _opposes(other: pd.Series) -> pd.Series:
        return (
            (np.sign(other) != np.sign(excess))
            & (other.abs() > revert_fraction * excess.abs())
        ).fillna(False)

    paired = _opposes(excess.shift(-1)) | _opposes(excess.shift(1))

    # Third condition: the shift has to last. A wetting event is large, abrupt
    # and not reverted the next day, so on irrigated land the first two
    # conditions alone flag every irrigation — 5.6 % of the simulated corpus.
    # The physical difference is that applied water drains and evaporates away
    # over days while a recalibration offset does not, so the level is compared
    # a full window later, with the ordinary drift over that span removed.
    level_before = theta.rolling(window, min_periods=window // 2).median()
    level_after = (
        theta[::-1].rolling(window, min_periods=window // 2).median()[::-1].shift(-1)
    )
    expected_from_drift = drift * window
    persistent = (level_after - level_before) - expected_from_drift
    lasts = persistent.abs() >= persistence * excess.abs()

    # Fourth condition, and the one that actually settles it: the shift must be
    # *unexplained*. Rainfall and irrigation produce jumps that are large,
    # abrupt, unreverted and — in a clay soil, or when followed by more
    # applications — persistent, so they satisfy everything above. On the
    # simulated corpus 73 % of the remaining flags coincided with a real water
    # input within a couple of days. No statistic computed from the moisture
    # series alone can separate those from a recalibration, because they look the
    # same; the information simply is not in the series. Supplying the water
    # record resolves it, and an instrument fault is in any case *defined* as a
    # shift nothing explains. Without a water record the check still runs, and
    # its output must then be read as "level shift, cause unknown".
    explained = pd.Series(False, index=theta.index)
    if water_input_mm is not None:
        wet = water_input_mm.fillna(0.0) > water_threshold_mm
        span = 2 * water_lag_days + 1
        explained = (
            wet.rolling(span, center=True, min_periods=1).max().astype(bool)
        )

    spike = detect_spikes(theta, window=max(7, window // 3))
    return (
        (excess.abs() > min_shift)
        & ~paired
        & lasts.fillna(False)
        & ~spike
        & ~explained
        & theta.notna()
    )


def detect_drift(
    theta: pd.Series,
    dates: pd.Series,
    min_years: float = 2.0,
    max_trend_per_year: float = 0.03,
) -> bool:
    """Whether a sensor shows a monotone trend too large to be climate.

    Returns a single verdict for the series rather than per-observation flags,
    because drift is a property of the instrument. A trend beyond about
    0.03 m3/m3 per year sustained over years is not a climate signal at a point;
    it is a probe degrading, and the whole record should be treated with caution.
    """
    ok = theta.notna()
    if ok.sum() < 100:
        return False
    t = pd.to_datetime(dates[ok])
    span_years = (t.max() - t.min()).days / 365.25
    if span_years < min_years:
        return False
    x = (t - t.min()).dt.total_seconds().to_numpy() / (365.25 * 86400)
    slope = np.polyfit(x, theta[ok].to_numpy(dtype=float), 1)[0]
    return bool(abs(slope) > max_trend_per_year)


def detect_cross_depth_inconsistency(
    wide: pd.DataFrame,
    max_gradient_per_cm: float = 0.02,
) -> pd.DataFrame:
    """Flag implausible jumps between adjacent depths at the same time.

    Columns are depth labels in increasing order. Sharp wetting fronts are real,
    so the threshold is set at what a front can actually be, not at smoothness;
    what this catches is a mislabelled depth or a probe wired to the wrong
    channel, which show up as a gradient no soil physics can produce.
    """
    depths = [float(str(c).split("_")[0]) for c in wide.columns]
    flags = pd.DataFrame(False, index=wide.index, columns=wide.columns)
    for i in range(len(wide.columns) - 1):
        dz = max(depths[i + 1] - depths[i], 1.0)
        gradient = (wide.iloc[:, i + 1] - wide.iloc[:, i]).abs() / dz
        bad = gradient > max_gradient_per_cm
        flags.iloc[:, i] |= bad
        flags.iloc[:, i + 1] |= bad
    return flags


# --------------------------------------------------------------------------
# Sensor-physics flags
# --------------------------------------------------------------------------


def flag_salinity_suspect(
    ece_ds_m: pd.Series,
    sensor_frequency_mhz: pd.Series,
    risk_threshold: float = 0.25,
) -> pd.Series:
    """Flag readings likely inflated by pore-water salts.

    Combines how saline the soil is with how vulnerable the instrument is; see
    :func:`~smml.physics.dielectric.salinity_bias_risk`. A TDR probe in a saline
    soil is largely fine and is not flagged; a 50 MHz capacitance probe in the
    same soil is not.
    """
    risk = salinity_bias_risk(ece_ds_m.to_numpy(dtype=float),
                              sensor_frequency_mhz.to_numpy(dtype=float))
    return pd.Series(np.nan_to_num(risk) > risk_threshold, index=ece_ds_m.index)


def flag_clay_suspect(
    theta: pd.Series,
    clay_pct: pd.Series,
    porosity: pd.Series,
    calibration: pd.Series | None = None,
    bias_threshold: float = 0.03,
) -> pd.Series:
    """Flag readings materially biased low by clay-bound water.

    Only factory or Topp calibrations are flagged. A probe with a soil-specific
    gravimetric calibration has already absorbed the clay effect into its own
    coefficients, and flagging it would be wrong.
    """
    bias = clay_bias(theta.to_numpy(dtype=float), clay_pct.to_numpy(dtype=float),
                     porosity.to_numpy(dtype=float))
    suspect = pd.Series(np.nan_to_num(bias) > bias_threshold, index=theta.index)
    if calibration is not None:
        suspect &= calibration.fillna("unknown").isin(["factory", "topp", "unknown"])
    return suspect


# --------------------------------------------------------------------------
# Irrigation inference
# --------------------------------------------------------------------------


def infer_irrigation_events(
    frame: pd.DataFrame,
    theta_col: str = "theta_m3m3",
    precip_col: str = "precip_mm",
    date_col: str = "date",
    depth_col: str = "depth_mid_cm",
    surface_max_cm: float = 30.0,
    min_rise: float = 0.02,
    precip_threshold_mm: float = 2.0,
    min_interval_days: int = 2,
) -> pd.DataFrame:
    """Recover irrigation dates and approximate amounts from soil moisture.

    Uses the shallowest available layer, since irrigation is applied at the
    surface and the signal is strongest and least lagged there. A rise beyond
    ``min_rise`` with insufficient rainfall to explain it is recorded as an
    event, and the amount is estimated by converting the profile storage increase
    to millimetres and dividing by an assumed application efficiency.

    The amounts are rough — they miss whatever drained or evaporated before the
    next reading, so they are systematic *underestimates* — but the dates are
    reliable, and dates alone are enough to make irrigation a usable model input
    and to separate irrigated from rainfed records.

    Returns one row per detected event with a confidence score.
    """
    work = frame.sort_values([date_col]).copy()
    surface = work[work[depth_col] <= surface_max_cm]
    if surface.empty:
        return pd.DataFrame(columns=["date", "amount_mm", "evidence", "confidence"])

    daily = surface.groupby(date_col).agg(
        theta=(theta_col, "mean"),
        precip=(precip_col, "mean") if precip_col in surface.columns else (theta_col, "size"),
    )
    if precip_col not in surface.columns:
        daily["precip"] = 0.0

    rise = daily["theta"].diff()
    recent_rain = daily["precip"].rolling(3, min_periods=1).sum()
    is_event = (rise > min_rise) & (recent_rain < precip_threshold_mm)

    events = []
    last_date = None
    for date, flag in is_event.items():
        if not flag:
            continue
        if last_date is not None and (pd.Timestamp(date) - pd.Timestamp(last_date)).days < min_interval_days:
            continue
        delta = float(rise.loc[date])
        # Storage change over the surface layer, grossed up for application loss.
        amount = delta * surface_max_cm * 10.0 / 0.8
        # Confidence rises with the size of the unexplained rise and falls with
        # how much rain there was to potentially explain it.
        confidence = float(np.clip(delta / (min_rise * 3), 0.2, 1.0)) * float(
            np.clip(1.0 - recent_rain.loc[date] / max(precip_threshold_mm, 1e-6), 0.2, 1.0)
        )
        events.append({
            "date": date,
            "amount_mm": round(amount, 2),
            "evidence": "inferred_from_soil_moisture",
            "confidence": round(confidence, 3),
        })
        last_date = date
    return pd.DataFrame(events)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_qc(
    frame: pd.DataFrame,
    theta_col: str = "theta_m3m3",
    group_cols: tuple[str, ...] = ("site_id", "depth_top_cm"),
    date_col: str = "time_utc",
    porosity_col: str | None = "porosity_m3m3",
    soil_temp_col: str | None = "soil_temp_c",
    air_temp_col: str | None = "tmean_c",
    precip_col: str | None = "precip_mm",
    clay_col: str | None = "clay_pct",
    ece_col: str | None = "ece_ds_m",
    frequency_col: str | None = "instrument_frequency_mhz",
    method_col: str | None = "method",
) -> pd.DataFrame:
    """Apply every check and return the frame with a quality flag and uncertainty.

    Checks run per sensor series (site and depth), in time order. Where several
    fire on one observation the most severe wins, ordered by :data:`FLAG_PRIORITY`
    — a frozen-soil reading is reported as frozen rather than as a spike, because
    that is the actionable diagnosis.

    Adds:

    ``quality_flag``
        The worst flag that fired.
    ``qc_*``
        A boolean column per check, kept so that a downstream filter can be
        specific rather than having to accept or reject the whole flag.
    ``uncertainty_m3m3``
        Per-observation 1-sigma, from the method's baseline (see
        :data:`~smml.db.schema.METHOD_UNCERTAINTY`) inflated where a check fired.
    """
    out = frame.copy()
    n = len(out)
    checks = {
        "qc_spike": np.zeros(n, dtype=bool),
        "qc_flatline": np.zeros(n, dtype=bool),
        "qc_frozen": np.zeros(n, dtype=bool),
        "qc_rise_no_input": np.zeros(n, dtype=bool),
        "qc_step_change": np.zeros(n, dtype=bool),
        "qc_drift": np.zeros(n, dtype=bool),
    }

    present = [c for c in group_cols if c in out.columns]
    if present:
        out = out.sort_values([*present, date_col]).reset_index(drop=True)
        grouper = out.groupby(present, observed=True, sort=False)
        iterator = grouper.indices.items()
    else:
        out = out.sort_values(date_col).reset_index(drop=True)
        iterator = [((), np.arange(len(out)))]

    for _, idx in iterator:
        block = out.iloc[idx]
        theta = block[theta_col]
        checks["qc_spike"][idx] = detect_spikes(theta).to_numpy()
        checks["qc_flatline"][idx] = detect_flatline(theta).to_numpy()
        water = None
        if precip_col and precip_col in block:
            water = block[precip_col].astype(float).fillna(0.0)
            if "irrigation_mm" in block:
                water = water + block["irrigation_mm"].astype(float).fillna(0.0)
        checks["qc_step_change"][idx] = detect_step_change(theta, water).to_numpy()
        soil_t = block[soil_temp_col] if soil_temp_col and soil_temp_col in block else None
        air_t = block[air_temp_col] if air_temp_col and air_temp_col in block else None
        if soil_t is not None or air_t is not None:
            checks["qc_frozen"][idx] = detect_frozen(soil_t, air_t).to_numpy()
        precip = block[precip_col] if precip_col and precip_col in block else None
        checks["qc_rise_no_input"][idx] = detect_rise_without_input(theta, precip).to_numpy()
        if date_col in block:
            checks["qc_drift"][idx] = detect_drift(theta, block[date_col])

    for name, values in checks.items():
        out[name] = values

    porosity = out[porosity_col] if porosity_col and porosity_col in out.columns else None
    range_flags = flag_physical_range(out[theta_col], porosity)
    out["qc_out_of_range"] = range_flags == QualityFlag.OUT_OF_PHYSICAL_RANGE.value
    out["qc_exceeds_saturation"] = range_flags == QualityFlag.EXCEEDS_SATURATION.value
    out["qc_missing"] = range_flags == QualityFlag.MISSING.value

    if clay_col in (out.columns if clay_col else ()) and porosity is not None:
        out["qc_clay_suspect"] = flag_clay_suspect(
            out[theta_col], out[clay_col], porosity,
            out["calibration"] if "calibration" in out.columns else None,
        ).to_numpy()
    else:
        out["qc_clay_suspect"] = False

    if ece_col in (out.columns if ece_col else ()) and frequency_col in (out.columns if frequency_col else ()):
        out["qc_salinity_suspect"] = flag_salinity_suspect(out[ece_col], out[frequency_col]).to_numpy()
    else:
        out["qc_salinity_suspect"] = False

    out["quality_flag"] = _resolve_flags(out)
    out["uncertainty_m3m3"] = _assign_uncertainty(out, method_col)
    return out


#: Which flag wins when several fire. Ordered most to least severe: a value that
#: is impossible outranks one that is merely suspicious, and a physical cause
#: (frozen soil) outranks a symptom (a spike) because it is the actionable one.
FLAG_PRIORITY: tuple[tuple[str, str], ...] = (
    ("qc_missing", QualityFlag.MISSING.value),
    ("qc_out_of_range", QualityFlag.OUT_OF_PHYSICAL_RANGE.value),
    ("qc_frozen", QualityFlag.FROZEN_SOIL.value),
    ("qc_exceeds_saturation", QualityFlag.EXCEEDS_SATURATION.value),
    ("qc_flatline", QualityFlag.CONSTANT_VALUE.value),
    ("qc_step_change", QualityFlag.STEP_CHANGE.value),
    ("qc_drift", QualityFlag.SENSOR_DRIFT.value),
    ("qc_spike", QualityFlag.SPIKE.value),
    ("qc_rise_no_input", QualityFlag.RISE_WITHOUT_WATER_INPUT.value),
    ("qc_salinity_suspect", QualityFlag.SALINITY_SUSPECT.value),
    ("qc_clay_suspect", QualityFlag.CLAY_SUSPECT.value),
)


def _resolve_flags(frame: pd.DataFrame) -> pd.Series:
    flags = pd.Series(QualityFlag.GOOD.value, index=frame.index, dtype=object)
    for column, value in reversed(FLAG_PRIORITY):
        if column in frame.columns:
            flags[frame[column].astype(bool)] = value
    return flags


#: Multiplier applied to the baseline method uncertainty when a check fires.
UNCERTAINTY_INFLATION: dict[str, float] = {
    "qc_spike": 3.0,
    "qc_step_change": 2.0,
    "qc_drift": 2.0,
    "qc_exceeds_saturation": 2.0,
    "qc_salinity_suspect": 2.5,
    "qc_clay_suspect": 2.0,
    "qc_frozen": 5.0,
    "qc_flatline": 4.0,
}


def _assign_uncertainty(frame: pd.DataFrame, method_col: str | None) -> pd.Series:
    if method_col and method_col in frame.columns:
        base = frame[method_col].map(METHOD_UNCERTAINTY).fillna(
            METHOD_UNCERTAINTY["unknown"]
        )
    else:
        base = pd.Series(METHOD_UNCERTAINTY["unknown"], index=frame.index)
    sigma = base.astype(float).copy()
    for column, factor in UNCERTAINTY_INFLATION.items():
        if column in frame.columns:
            sigma = np.where(frame[column].astype(bool), sigma * factor, sigma)
            sigma = pd.Series(sigma, index=frame.index)
    return sigma


def qc_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """Counts and percentages per check — the first thing to look at after a harvest."""
    rows = []
    for column, _ in FLAG_PRIORITY:
        if column in frame.columns:
            n = int(frame[column].astype(bool).sum())
            rows.append({"check": column, "n": n, "pct": round(100 * n / max(len(frame), 1), 3)})
    return pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)
