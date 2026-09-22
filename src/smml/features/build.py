"""Feature construction for multi-depth soil moisture prediction.

Two principles govern everything here.

**No leakage, by construction rather than by review.** Every dynamic feature is
built from strictly past information using closed left windows. The target is
never an input, not lagged, not smoothed, not through a site statistic. Site-level
statistics that *would* leak across a cross-validation boundary (a site's mean
water content, its observed minimum and maximum) are deliberately absent — they
are exactly the features that inflate a leave-site-out score while being
unavailable at any new field, which is the setting this model is for. The one
exception is offered explicitly and separately: :func:`add_autoregressive_features`
is opt-in, and its docstring says what it costs.

**Features a new field could actually supply.** The intended use is predicting
soil moisture where no sensor exists. A feature that requires an installed probe
is useless for that, however much it improves a benchmark. Soil attributes are
therefore taken from the gridded columns wherever both are present, since a
gridded value is what any new location will have.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..physics.agromet import CROP_PARAMS, kc_curve, root_depth_cm
from ..physics.water import saxton_rawls, usda_texture_class

log = logging.getLogger(__name__)

#: Look-back windows in days for rolling weather summaries. Chosen to span the
#: response times of the profile: a few days for the surface, a season for a
#: metre down.
DEFAULT_WINDOWS: tuple[int, ...] = (1, 2, 3, 7, 14, 30, 60, 90, 180, 365)

#: Individual lagged days, for the short-range structure that a rolling mean
#: smooths away — the difference between 30 mm yesterday and 30 mm a week ago.
DEFAULT_LAGS: tuple[int, ...] = (1, 2, 3, 4, 5, 7, 10, 14, 21, 30)


def _rolling_past(
    series: pd.Series,
    window: int,
    how: str = "sum",
    min_fraction: float = 0.5,
) -> pd.Series:
    """Rolling statistic over the ``window`` days *before* the current day.

    The shift by one is what makes the window closed on the left. A rolling sum
    that includes today's precipitation is legitimate for a same-day nowcast but
    not for a forecast, and mixing the two silently is the most common way this
    kind of model ends up reporting a score it cannot reproduce.
    """
    shifted = series.shift(1)
    roll = shifted.rolling(window, min_periods=max(1, int(window * min_fraction)))
    return getattr(roll, how)()


def antecedent_precipitation_index(precip: pd.Series, k: float = 0.92) -> pd.Series:
    """API: a decaying memory of past rainfall.

        API_t = k API_{t-1} + P_{t-1}

    ``k`` near 0.9 gives an e-folding memory of about ten days. A single number
    that carries the wetting history, and consistently one of the strongest
    single predictors of surface soil moisture.
    """
    p = precip.shift(1).fillna(0.0).to_numpy(dtype=float)
    out = np.zeros(len(p))
    acc = 0.0
    for i in range(len(p)):
        acc = k * acc + p[i]
        out[i] = acc
    return pd.Series(out, index=precip.index)


def simple_bucket_state(
    precip: pd.Series,
    et0: pd.Series,
    capacity_mm: float,
    kc: pd.Series | None = None,
    runoff_fraction: float = 0.1,
) -> pd.DataFrame:
    """A one-layer water balance run alongside the data, as a physics prior.

    Returns the bucket's storage, its relative fill, and cumulative drainage.
    This is not a competitor to the learned model — it is a feature for it, and
    simultaneously the baseline the learned model has to beat. Giving a
    gradient-booster a physically integrated state variable is what lets it
    represent memory that no fixed set of rolling windows can.

    Driven entirely by weather, so it is available anywhere.
    """
    p = precip.shift(1).fillna(0.0).to_numpy(dtype=float)
    e = et0.shift(1).fillna(0.0).to_numpy(dtype=float)
    c = kc.shift(1).fillna(1.0).to_numpy(dtype=float) if kc is not None else np.ones(len(p))

    storage = np.zeros(len(p))
    drainage = np.zeros(len(p))
    level = capacity_mm * 0.5
    for i in range(len(p)):
        infil = p[i] * (1.0 - runoff_fraction)
        level += infil
        if level > capacity_mm:
            drainage[i] = level - capacity_mm
            level = capacity_mm
        demand = e[i] * c[i] * np.clip(level / max(capacity_mm, 1e-6), 0.0, 1.0)
        level = max(level - demand, 0.0)
        storage[i] = level
    return pd.DataFrame(
        {
            "bucket_storage_mm": storage,
            "bucket_fill": storage / max(capacity_mm, 1e-6),
            "bucket_drainage_mm": drainage,
        },
        index=precip.index,
    )


def days_since_event(values: pd.Series, threshold: float) -> pd.Series:
    """Days since the last day exceeding ``threshold``, counted from yesterday.

    Capped at 365. Drydown length is the dominant control on surface soil
    moisture and is awkward for a tree to recover from rolling sums alone.
    """
    exceeded = (values.shift(1) > threshold).to_numpy()
    out = np.empty(len(exceeded))
    count = 365.0
    for i, hit in enumerate(exceeded):
        count = 0.0 if hit else min(count + 1.0, 365.0)
        out[i] = count
    return pd.Series(out, index=values.index)


# --------------------------------------------------------------------------
# Per-site dynamic features
# --------------------------------------------------------------------------


def build_site_weather_features(
    weather: pd.DataFrame,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    crop: str | None = None,
    planting_doy: int | None = None,
    awc_mm: float = 150.0,
) -> pd.DataFrame:
    """Dynamic features for one site's daily weather record.

    ``weather`` must be sorted by date, one row per day, and carry at least
    ``date``, ``precip_mm`` and ``et0_mm``.
    """
    weather = weather.sort_values("date").reset_index(drop=True)
    # Columns are accumulated in a dict and assembled once. Assigning ~150
    # columns one at a time to a DataFrame reallocates the block manager on
    # nearly every insert, which dominates the runtime at corpus scale.
    cols: dict[str, np.ndarray] = {}

    date = pd.to_datetime(weather["date"])
    doy = date.dt.dayofyear.to_numpy()
    cols["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    cols["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    cols["month"] = date.dt.month.to_numpy()

    precip = weather["precip_mm"].astype(float)
    et0 = weather["et0_mm"].astype(float)

    # Crop phenology, if the crop and planting date are known. Available at a
    # new field from the cropping calendar, so it is a legitimate covariate.
    kc_series = None
    if crop and planting_doy is not None:
        params = CROP_PARAMS.get(crop)
        if params is not None:
            season = params["l_ini"] + params["l_dev"] + params["l_mid"] + params["l_late"]
            dap = (doy - planting_doy) % 365
            in_season = dap <= season
            dap_masked = np.where(in_season, dap, -1)
            cols["days_after_planting"] = dap_masked
            cols["in_season"] = in_season.astype(np.int8)
            cols["kc"] = np.asarray(kc_curve(
                dap_masked, params["l_ini"], params["l_dev"],
                params["l_mid"], params["l_late"], params["kc_ini"],
                params["kc_mid"], params["kc_end"],
            ))
            cols["root_depth_cm"] = np.asarray(
                root_depth_cm(dap_masked, params["root_max_cm"], season)
            )
            kc_series = pd.Series(cols["kc"], index=weather.index)
            cols["etc_mm"] = et0.shift(1).fillna(0.0).to_numpy() * cols["kc"]

    # Rolling weather summaries.
    for w in windows:
        p_sum = _rolling_past(precip, w, "sum").to_numpy()
        e_sum = _rolling_past(et0, w, "sum").to_numpy()
        cols[f"precip_sum_{w}d"] = p_sum
        cols[f"et0_sum_{w}d"] = e_sum
        cols[f"water_balance_{w}d"] = p_sum - e_sum
        if w >= 7:
            cols[f"precip_max_{w}d"] = _rolling_past(precip, w, "max").to_numpy()
            cols[f"wet_days_{w}d"] = _rolling_past((precip > 1.0).astype(float), w, "sum").to_numpy()
        for col, name in (("tmean_c", "tmean"), ("tmax_c", "tmax"),
                          ("srad_mj_m2", "srad"), ("rh_mean_pct", "rh"),
                          ("wind_2m_ms", "wind")):
            if col in weather.columns and w in (3, 7, 30, 90):
                cols[f"{name}_mean_{w}d"] = _rolling_past(
                    weather[col].astype(float), w, "mean"
                ).to_numpy()

    # Individual lagged days.
    for lag in lags:
        cols[f"precip_lag{lag}"] = precip.shift(lag).to_numpy()
        cols[f"et0_lag{lag}"] = et0.shift(lag).to_numpy()
        if "tmean_c" in weather.columns and lag <= 7:
            cols[f"tmean_lag{lag}"] = weather["tmean_c"].astype(float).shift(lag).to_numpy()

    cols["api_10d"] = antecedent_precipitation_index(precip, k=0.90).to_numpy()
    cols["api_30d"] = antecedent_precipitation_index(precip, k=0.967).to_numpy()
    cols["days_since_rain_1mm"] = days_since_event(precip, 1.0).to_numpy()
    cols["days_since_rain_10mm"] = days_since_event(precip, 10.0).to_numpy()

    bucket = simple_bucket_state(precip, et0, capacity_mm=awc_mm, kc=kc_series)
    for col in bucket.columns:
        cols[col] = bucket[col].to_numpy()

    # Irrigation, when the schedule is known. Absent at most sites, which is why
    # it is optional and why the bucket above must carry the load without it.
    if "irrigation_mm" in weather.columns:
        irr = weather["irrigation_mm"].astype(float)
        cols["days_since_irrigation"] = days_since_event(irr, 0.1).to_numpy()
        for w in (7, 14, 30, 90):
            cols[f"irrigation_sum_{w}d"] = _rolling_past(irr, w, "sum").to_numpy()

    out = pd.DataFrame(cols, index=weather.index)
    out.insert(0, "date", weather["date"].to_numpy())
    return out


# --------------------------------------------------------------------------
# Static features
# --------------------------------------------------------------------------

#: Site attributes that are available anywhere on Earth from public gridded
#: products, and are therefore legitimate predictors for an uninstrumented field.
STATIC_NUMERIC = [
    "lat", "lon", "elevation_m",
    "sand_pct", "silt_pct", "clay_pct", "om_pct",
    "bulk_density_g_cm3", "ece_ds_m",
    "wilting_point_m3m3", "field_capacity_m3m3", "porosity_m3m3", "ksat_mm_h",
    "mean_annual_precip_mm", "mean_annual_temp_c", "aridity",
    "slope_pct", "twi",
]

STATIC_CATEGORICAL = [
    "texture_class", "crop", "irrigation_method", "climate", "land_cover",
]


def build_static_features(sites: pd.DataFrame, prefer_gridded: bool = True) -> pd.DataFrame:
    """Static per-site features, with derived soil hydraulics filled in.

    ``prefer_gridded`` substitutes the ``*_grid`` soil columns where they exist.
    That is the honest default for this project's purpose: a model meant to
    replace sensors at new fields will only ever see gridded soil data there, so
    training it on field-measured texture would overstate what it can do.
    """
    out = sites.copy()

    if prefer_gridded:
        for base in ("sand_pct", "silt_pct", "clay_pct", "om_pct", "bulk_density_g_cm3"):
            grid = f"{base}_grid" if base != "bulk_density_g_cm3" else "bulk_density_grid_g_cm3"
            if grid in out.columns:
                out[base] = out[grid].where(out[grid].notna(), out.get(base))

    if {"sand_pct", "clay_pct"} <= set(out.columns):
        need = [c for c in ("wilting_point_m3m3", "field_capacity_m3m3",
                            "porosity_m3m3", "ksat_mm_h")
                if c not in out.columns or out[c].isna().any()]
        if need:
            ptf = saxton_rawls(
                out["sand_pct"].to_numpy(dtype=float),
                out["clay_pct"].to_numpy(dtype=float),
                out.get("om_pct", pd.Series(2.0, index=out.index)).fillna(2.0).to_numpy(dtype=float),
            )
            for col in need:
                key = col if col in ptf else None
                if key:
                    out[col] = out[col].fillna(pd.Series(ptf[key], index=out.index)) \
                        if col in out.columns else ptf[key]
        if "texture_class" not in out.columns or out["texture_class"].isna().any():
            out["texture_class"] = usda_texture_class(
                out["sand_pct"].to_numpy(dtype=float), out["clay_pct"].to_numpy(dtype=float)
            )
        out["awc_m3m3"] = out["field_capacity_m3m3"] - out["wilting_point_m3m3"]
        out["clay_sand_ratio"] = out["clay_pct"] / np.maximum(out["sand_pct"], 1.0)

    if "ece_ds_m" in out.columns:
        out["log_ece"] = np.log1p(out["ece_ds_m"].clip(lower=0))

    if {"mean_annual_precip_mm", "mean_annual_temp_c"} <= set(out.columns):
        # A crude Thornthwaite-style aridity proxy, available from any climate grid.
        out["aridity_proxy"] = out["mean_annual_precip_mm"] / (
            np.maximum(out["mean_annual_temp_c"], -5.0) + 15.0
        )

    return out


# --------------------------------------------------------------------------
# Depth features
# --------------------------------------------------------------------------


def add_depth_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Encode the measurement depth so one model can serve the whole profile.

    Treating depth as a feature rather than fitting one model per layer lets the
    model share the physics that is common across depths and lets it interpolate
    to a depth it never saw — which matters because the harvested corpus reports
    a chaotic assortment of installation depths.
    """
    out = frame.copy()
    top = out["depth_top_cm"].astype(float)
    bottom = out["depth_bottom_cm"].astype(float)
    mid = (top + bottom) / 2.0
    out["depth_mid_cm"] = mid
    out["depth_thickness_cm"] = bottom - top
    out["log_depth"] = np.log1p(mid)
    # A saturating transform: the difference between 5 and 15 cm matters far more
    # than between 150 and 160, and a linear depth makes a tree spend splits
    # resolving the deep end where nothing happens.
    out["depth_decay"] = np.exp(-mid / 30.0)
    out["is_surface"] = (mid <= 10.0).astype(np.int8)
    out["is_rootzone"] = ((mid > 10.0) & (mid <= 100.0)).astype(np.int8)

    if "root_depth_cm" in out.columns:
        out["depth_rel_root"] = mid / np.maximum(out["root_depth_cm"].astype(float), 5.0)
        out["within_root_zone"] = (mid <= out["root_depth_cm"].astype(float)).astype(np.int8)
    return out


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_features(
    observations: pd.DataFrame,
    sites: pd.DataFrame,
    weather: pd.DataFrame | None = None,
    windows: tuple[int, ...] = DEFAULT_WINDOWS,
    lags: tuple[int, ...] = DEFAULT_LAGS,
    target: str = "theta_obs_m3m3",
    prefer_gridded: bool = True,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Assemble the modelling table.

    Returns ``(frame, feature_columns, categorical_columns)``.

    ``observations`` is the long table: one row per site, date and depth.
    ``weather`` may be supplied separately or, when omitted, is taken from the
    daily columns already present on the observations.
    """
    obs = observations.copy()
    obs["date"] = pd.to_datetime(obs["date"])

    if weather is None:
        weather_cols = [c for c in ("date", "site_id", "precip_mm", "et0_mm", "tmax_c", "tmin_c",
                                    "tmean_c", "rh_mean_pct", "wind_2m_ms", "srad_mj_m2",
                                    "irrigation_mm")
                        if c in obs.columns]
        weather = obs[weather_cols].drop_duplicates(subset=["site_id", "date"]).copy()
    weather = weather.copy()
    weather["date"] = pd.to_datetime(weather["date"])

    static = build_static_features(sites, prefer_gridded=prefer_gridded)
    static_lookup = static.set_index("site_id")

    dynamic_frames = []
    for site, group in weather.groupby("site_id", sort=False):
        row = static_lookup.loc[site] if site in static_lookup.index else None
        crop = row.get("crop") if row is not None else None
        planting = row.get("planting_doy") if row is not None else None
        awc = 150.0
        if row is not None and pd.notna(row.get("field_capacity_m3m3")) and pd.notna(row.get("wilting_point_m3m3")):
            awc = float(max((row["field_capacity_m3m3"] - row["wilting_point_m3m3"]) * 1000.0, 20.0))
        feats = build_site_weather_features(
            group, windows=windows, lags=lags,
            crop=crop if isinstance(crop, str) else None,
            planting_doy=int(planting) if pd.notna(planting) else None,
            awc_mm=awc,
        )
        feats["site_id"] = site
        dynamic_frames.append(feats)
    dynamic = pd.concat(dynamic_frames, ignore_index=True)
    dynamic["date"] = pd.to_datetime(dynamic["date"])

    keep_obs = [c for c in ("site_id", "date", "depth_top_cm", "depth_bottom_cm", target)
                if c in obs.columns]
    extra_targets = [c for c in ("theta_true_m3m3", "saturation") if c in obs.columns and c != target]
    frame = obs[keep_obs + extra_targets].merge(dynamic, on=["site_id", "date"], how="left")

    static_cols = ["site_id"] + [
        c for c in STATIC_NUMERIC + STATIC_CATEGORICAL + [
            "awc_m3m3", "clay_sand_ratio", "log_ece", "aridity_proxy", "planting_doy",
        ] if c in static.columns
    ]
    frame = frame.merge(static[static_cols], on="site_id", how="left")
    frame = add_depth_features(frame)

    never_features = {
        "site_id", "date", target, "theta_true_m3m3", "saturation",
        "depth_top_cm", "depth_bottom_cm",
    }
    categorical = [c for c in STATIC_CATEGORICAL if c in frame.columns]
    feature_cols = [
        c for c in frame.columns
        if c not in never_features and (
            pd.api.types.is_numeric_dtype(frame[c]) or c in categorical
        )
    ]

    for col in categorical:
        frame[col] = frame[col].astype("category")

    log.info("built %d features over %d rows, %d sites",
             len(feature_cols), len(frame), frame.site_id.nunique())
    return frame, feature_cols, categorical


def add_autoregressive_features(
    frame: pd.DataFrame,
    target: str,
    lags: tuple[int, ...] = (1, 2, 3, 7),
    group_cols: tuple[str, ...] = ("site_id", "depth_top_cm"),
) -> tuple[pd.DataFrame, list[str]]:
    """Opt-in lagged-target features. Read this before using them.

    Lagged soil moisture is overwhelmingly the strongest predictor of soil
    moisture, and adding it will improve every metric dramatically. It also
    changes what the model is: a system that needs yesterday's reading needs a
    sensor in the ground, which defeats the purpose of building it. It is
    appropriate for gap-filling an existing record and for short-horizon
    forecasting at an instrumented site, and inappropriate for the primary task
    of estimating water content where nothing is installed.

    Kept out of :func:`build_features` so the choice has to be deliberate.
    """
    out = frame.sort_values([*group_cols, "date"]).copy()
    names = []
    grouped = out.groupby(list(group_cols), observed=True)[target]
    for lag in lags:
        name = f"{target}_lag{lag}"
        out[name] = grouped.shift(lag)
        names.append(name)
    name = f"{target}_delta1"
    out[name] = out[f"{target}_lag1"] - out[f"{target}_lag2"] if len(lags) > 1 else np.nan
    names.append(name)
    return out, names
