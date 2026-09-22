"""Soil water state: unit harmonization, retention curves and pedotransfer.

A database assembled from hundreds of sources arrives in incompatible units.
Papers report gravimetric water content, volumetric water content, degree of
saturation, plant-available water fraction, profile storage in millimetres, or a
"relative soil moisture" normalized by some site-specific pair of bounds that is
often not stated. Nothing can be learned across sites until all of it is on one
scale, and every conversion needs ancillary data (bulk density, porosity, field
capacity, wilting point) that must itself be estimated where it was not
reported. That estimation is what the pedotransfer functions here are for.

The canonical internal unit for this project is **volumetric water content in
m3/m3**, with a parallel **degree of saturation** column because saturation is
the more transferable quantity across textures for a learning model.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray

PARTICLE_DENSITY = 2.65  # g/cm3, quartz-dominated mineral soil
WATER_DENSITY = 1.0      # g/cm3


def _arr(x: ArrayLike) -> NDArray[np.float64]:
    return np.asarray(x, dtype=float)


# --------------------------------------------------------------------------
# Unit conversions
# --------------------------------------------------------------------------


def gravimetric_to_volumetric(w_grav: ArrayLike, bulk_density: ArrayLike) -> NDArray[np.float64]:
    """theta_v = w_g * rho_b / rho_w. Inputs g/g and g/cm3."""
    w, rb = _arr(w_grav), _arr(bulk_density)
    return np.where((w >= 0) & (rb > 0), w * rb / WATER_DENSITY, np.nan)


def volumetric_to_gravimetric(theta: ArrayLike, bulk_density: ArrayLike) -> NDArray[np.float64]:
    th, rb = _arr(theta), _arr(bulk_density)
    return np.where((th >= 0) & (rb > 0), th * WATER_DENSITY / rb, np.nan)


def porosity_from_bulk_density(
    bulk_density: ArrayLike, particle_density: float = PARTICLE_DENSITY
) -> NDArray[np.float64]:
    """n = 1 - rho_b / rho_s. Total porosity, i.e. water content at saturation."""
    rb = _arr(bulk_density)
    n = 1.0 - rb / particle_density
    return np.where((rb > 0.1) & (n > 0.0) & (n < 1.0), n, np.nan)


def bulk_density_from_porosity(
    porosity: ArrayLike, particle_density: float = PARTICLE_DENSITY
) -> NDArray[np.float64]:
    n = _arr(porosity)
    return np.where((n > 0) & (n < 1), (1.0 - n) * particle_density, np.nan)


def degree_of_saturation(theta: ArrayLike, porosity: ArrayLike) -> NDArray[np.float64]:
    """S = theta / n, clipped to [0, 1.05] to tolerate small measurement overshoot."""
    th, n = _arr(theta), _arr(porosity)
    return np.where((n > 0) & (th >= 0), np.clip(th / n, 0.0, 1.05), np.nan)


def water_filled_pore_space(theta: ArrayLike, porosity: ArrayLike) -> NDArray[np.float64]:
    """WFPS in percent — the form used in soil respiration and denitrification work."""
    return degree_of_saturation(theta, porosity) * 100.0


def plant_available_fraction(
    theta: ArrayLike, wilting_point: ArrayLike, field_capacity: ArrayLike
) -> NDArray[np.float64]:
    """Fraction of plant-available water remaining, (theta - WP) / (FC - WP).

    Clipped to [0, 1.2]: values above 1 are real (the soil is wetter than field
    capacity after irrigation and is draining) but values far above it indicate a
    bad FC estimate rather than a real state.
    """
    th, wp, fc = _arr(theta), _arr(wilting_point), _arr(field_capacity)
    awc = fc - wp
    return np.where(awc > 0.01, np.clip((th - wp) / awc, 0.0, 1.2), np.nan)


def storage_mm(theta: ArrayLike, layer_thickness_cm: ArrayLike) -> NDArray[np.float64]:
    """Depth-equivalent water in a layer, in mm. theta [m3/m3] * thickness [cm] * 10."""
    th, dz = _arr(theta), _arr(layer_thickness_cm)
    return np.where((th >= 0) & (dz > 0), th * dz * 10.0, np.nan)


def storage_to_theta(storage: ArrayLike, layer_thickness_cm: ArrayLike) -> NDArray[np.float64]:
    st, dz = _arr(storage), _arr(layer_thickness_cm)
    return np.where(dz > 0, st / (dz * 10.0), np.nan)


def denormalize_relative(
    relative: ArrayLike, theta_min: ArrayLike, theta_max: ArrayLike
) -> NDArray[np.float64]:
    """Recover theta from a site-normalized "relative soil moisture" in [0, 1].

    Many papers and satellite products publish only this. Recovering absolute
    water content requires the normalizing pair, which is frequently *not*
    stated — in that case the record must be kept as relative and excluded from
    absolute-scale training, not guessed at.
    """
    r, lo, hi = _arr(relative), _arr(theta_min), _arr(theta_max)
    return np.where(hi > lo, lo + r * (hi - lo), np.nan)


# --------------------------------------------------------------------------
# Water retention
# --------------------------------------------------------------------------


def van_genuchten_theta(
    h_cm: ArrayLike,
    theta_r: ArrayLike,
    theta_s: ArrayLike,
    alpha: ArrayLike,
    n: ArrayLike,
) -> NDArray[np.float64]:
    """van Genuchten (1980) retention: water content at matric head h (cm, positive).

        theta(h) = theta_r + (theta_s - theta_r) / [1 + (alpha h)^n]^m,   m = 1 - 1/n
    """
    h, tr, ts, a, nn = (_arr(v) for v in (h_cm, theta_r, theta_s, alpha, n))
    m = 1.0 - 1.0 / nn
    se = (1.0 + (a * np.abs(h)) ** nn) ** (-m)
    out = tr + (ts - tr) * se
    return np.where((nn > 1.0) & (a > 0) & (ts > tr) & (h >= 0), out, np.nan)


def van_genuchten_head(
    theta: ArrayLike,
    theta_r: ArrayLike,
    theta_s: ArrayLike,
    alpha: ArrayLike,
    n: ArrayLike,
) -> NDArray[np.float64]:
    """Inverse retention: matric head (cm) at a given water content."""
    th, tr, ts, a, nn = (_arr(v) for v in (theta, theta_r, theta_s, alpha, n))
    m = 1.0 - 1.0 / nn
    se = np.clip((th - tr) / (ts - tr), 1e-9, 1.0)
    h = (se ** (-1.0 / m) - 1.0) ** (1.0 / nn) / a
    return np.where((nn > 1.0) & (a > 0) & (ts > tr), h, np.nan)


def mualem_conductivity(
    theta: ArrayLike,
    theta_r: ArrayLike,
    theta_s: ArrayLike,
    n: ArrayLike,
    k_sat: ArrayLike,
    l: float = 0.5,
) -> NDArray[np.float64]:
    """Mualem-van Genuchten unsaturated hydraulic conductivity, same units as k_sat.

        K = Ks Se^l [1 - (1 - Se^(1/m))^m]^2
    """
    th, tr, ts, nn, ks = (_arr(v) for v in (theta, theta_r, theta_s, n, k_sat))
    m = 1.0 - 1.0 / nn
    se = np.clip((th - tr) / (ts - tr), 1e-9, 1.0)
    inner = 1.0 - (1.0 - se ** (1.0 / m)) ** m
    out = ks * se**l * inner**2
    return np.where((nn > 1.0) & (ts > tr) & (ks > 0), out, np.nan)


# --------------------------------------------------------------------------
# Pedotransfer functions
# --------------------------------------------------------------------------


def saxton_rawls(
    sand_pct: ArrayLike,
    clay_pct: ArrayLike,
    om_pct: ArrayLike = 2.0,
) -> dict[str, NDArray[np.float64]]:
    """Saxton & Rawls (2006) pedotransfer functions.

    Returns wilting point (1500 kPa), field capacity (33 kPa), saturation,
    saturated conductivity and derived bulk density / porosity / available water
    capacity, all from texture and organic matter alone. This is the workhorse
    for the very large fraction of the corpus that reports texture but no
    hydraulic properties.

    Units: sand/clay/OM in percent by weight, water contents m3/m3, Ksat mm/h,
    bulk density g/cm3. Valid roughly for mineral soils with OM < 8 %.

    Source: Saxton, K.E. & Rawls, W.J. (2006), SSSAJ 70:1569-1578, eqs. 1-5 and
    the density-adjustment set.
    """
    S = _arr(sand_pct) / 100.0
    C = _arr(clay_pct) / 100.0
    OM = _arr(om_pct)

    # 1500 kPa (wilting point)
    t1500t = (
        -0.024 * S + 0.487 * C + 0.006 * OM
        + 0.005 * (S * OM) - 0.013 * (C * OM) + 0.068 * (S * C) + 0.031
    )
    wp = t1500t + (0.14 * t1500t - 0.02)

    # 33 kPa (field capacity)
    t33t = (
        -0.251 * S + 0.195 * C + 0.011 * OM
        + 0.006 * (S * OM) - 0.027 * (C * OM) + 0.452 * (S * C) + 0.299
    )
    fc = t33t + (1.283 * t33t**2 - 0.374 * t33t - 0.015)

    # Saturation minus 33 kPa
    s33t = (
        0.278 * S + 0.034 * C + 0.022 * OM
        - 0.018 * (S * OM) - 0.027 * (C * OM) - 0.584 * (S * C) + 0.078
    )
    s33 = s33t + (0.636 * s33t - 0.107)

    sat = fc + s33 - 0.097 * S + 0.043
    rho_b = (1.0 - sat) * PARTICLE_DENSITY

    # Saturated conductivity, mm/h
    lam_den = np.log(1500.0) - np.log(33.0)
    b = (np.log(1500.0) - np.log(33.0)) / np.maximum(np.log(np.maximum(fc, 1e-6)) - np.log(np.maximum(wp, 1e-6)), 1e-6)
    lam = 1.0 / np.maximum(b, 1e-6)
    ksat = 1930.0 * np.maximum(sat - fc, 1e-6) ** (3.0 - lam)
    _ = lam_den

    valid = (S >= 0) & (S <= 1) & (C >= 0) & (C <= 1) & (S + C <= 1.001)
    keep = lambda x: np.where(valid, x, np.nan)  # noqa: E731

    return {
        "wilting_point_m3m3": keep(np.clip(wp, 0.01, 0.45)),
        "field_capacity_m3m3": keep(np.clip(fc, 0.05, 0.60)),
        "saturation_m3m3": keep(np.clip(sat, 0.20, 0.75)),
        "bulk_density_g_cm3": keep(np.clip(rho_b, 0.7, 1.9)),
        "porosity_m3m3": keep(np.clip(sat, 0.20, 0.75)),
        "ksat_mm_h": keep(np.clip(ksat, 0.01, 500.0)),
        "awc_m3m3": keep(np.clip(fc - wp, 0.01, 0.40)),
        "lambda_": keep(lam),
    }


# Rosetta H2 class-average van Genuchten parameters by USDA texture class.
# theta_r, theta_s (m3/m3), log10(alpha [1/cm]), log10(n), log10(Ksat [cm/day]).
# Schaap, Leij & van Genuchten (2001), Table 3. Used when no measured hydraulic
# data exist, which is the common case.
ROSETTA_CLASS_VG: dict[str, tuple[float, float, float, float, float]] = {
    "sand":            (0.053, 0.375, -1.453, 0.502, 2.808),
    "loamy_sand":      (0.049, 0.390, -1.459, 0.242, 2.022),
    "sandy_loam":      (0.039, 0.387, -1.574, 0.161, 1.583),
    "loam":            (0.061, 0.399, -1.954, 0.168, 1.081),
    "silt":            (0.050, 0.489, -2.182, 0.225, 1.641),
    "silt_loam":       (0.065, 0.439, -2.296, 0.221, 1.261),
    "sandy_clay_loam": (0.063, 0.384, -1.676, 0.124, 1.120),
    "clay_loam":       (0.079, 0.442, -1.801, 0.151, 0.913),
    "silty_clay_loam": (0.090, 0.482, -2.076, 0.182, 1.046),
    "sandy_clay":      (0.117, 0.385, -1.476, 0.082, 1.055),
    "silty_clay":      (0.111, 0.481, -1.790, 0.121, 0.983),
    "clay":            (0.098, 0.459, -1.825, 0.098, 1.169),
}


def usda_texture_class(sand_pct: ArrayLike, clay_pct: ArrayLike) -> NDArray[np.str_]:
    """USDA soil texture triangle class from sand and clay percentages.

    Silt is inferred as ``100 - sand - clay``. Boundaries follow the USDA
    textural triangle as implemented in the NRCS Soil Survey Manual; where two
    classes share a boundary the test order below resolves it the same way the
    NRCS algorithm does.
    """
    sand = _arr(sand_pct)
    clay = _arr(clay_pct)
    sand, clay = np.broadcast_arrays(sand, clay)
    silt = 100.0 - sand - clay
    out = np.full(sand.shape, "unknown", dtype=object)

    def setc(mask, name):
        nonlocal out
        out = np.where(mask & (out == "unknown"), name, out)

    valid = (sand >= 0) & (clay >= 0) & (silt >= -0.5) & (sand + clay <= 100.5)

    setc(valid & (clay >= 40) & (silt >= 40), "silty_clay")
    setc(valid & (clay >= 35) & (sand >= 45), "sandy_clay")
    setc(valid & (clay >= 40), "clay")
    setc(valid & (clay >= 27) & (clay < 40) & (sand <= 20), "silty_clay_loam")
    setc(valid & (clay >= 27) & (clay < 40) & (sand > 20) & (sand <= 45), "clay_loam")
    setc(valid & (clay >= 20) & (clay < 35) & (silt < 28) & (sand > 45), "sandy_clay_loam")
    setc(valid & (silt >= 80) & (clay < 12), "silt")
    setc(valid & (silt >= 50) & (clay >= 12) & (clay < 27), "silt_loam")
    setc(valid & (silt >= 50) & (silt < 80) & (clay < 12), "silt_loam")
    setc(valid & (clay >= 7) & (clay < 27) & (silt >= 28) & (silt < 50) & (sand <= 52), "loam")
    setc(valid & (sand >= 85) & ((silt + 1.5 * clay) < 15), "sand")
    setc(valid & (sand >= 70) & (sand < 91) & ((silt + 1.5 * clay) >= 15) & ((silt + 2.0 * clay) < 30), "loamy_sand")
    setc(valid & (clay < 20) & (sand > 52), "sandy_loam")
    setc(valid & (clay < 7) & (silt < 50) & (sand > 43), "sandy_loam")
    setc(valid, "loam")
    return out.astype(str)


def rosetta_class_params(sand_pct: ArrayLike, clay_pct: ArrayLike) -> dict[str, NDArray[np.float64]]:
    """Class-average van Genuchten parameters looked up from the texture triangle."""
    cls = usda_texture_class(sand_pct, clay_pct)
    shape = cls.shape
    tr = np.full(shape, np.nan)
    ts = np.full(shape, np.nan)
    al = np.full(shape, np.nan)
    nn = np.full(shape, np.nan)
    ks = np.full(shape, np.nan)
    for name, (r, s, la, ln, lk) in ROSETTA_CLASS_VG.items():
        m = cls == name
        tr[m], ts[m] = r, s
        al[m], nn[m] = 10.0**la, 10.0**ln
        ks[m] = 10.0**lk
    return {
        "texture_class": cls,
        "vg_theta_r": tr,
        "vg_theta_s": ts,
        "vg_alpha_1cm": al,
        "vg_n": nn,
        "ksat_cm_day": ks,
    }


# --------------------------------------------------------------------------
# Depth harmonization
# --------------------------------------------------------------------------

#: Standard depth layers for the harmonized database, chosen to align with the
#: depths most commonly instrumented in agricultural fields and with the
#: SoilGrids / GlobalSoilMap standard intervals where possible.
STANDARD_LAYERS_CM: tuple[tuple[float, float], ...] = (
    (0.0, 5.0),
    (5.0, 15.0),
    (15.0, 30.0),
    (30.0, 60.0),
    (60.0, 100.0),
    (100.0, 200.0),
)


def layer_overlap_weights(
    sensor_top_cm: ArrayLike,
    sensor_bottom_cm: ArrayLike,
    layer_top_cm: float,
    layer_bottom_cm: float,
) -> NDArray[np.float64]:
    """Fraction of each sensor's support interval that falls inside a target layer.

    Point sensors (top == bottom) are given their nominal depth and count fully
    toward whichever layer contains them. Integrating sensors (a neutron probe
    access tube reading, a CRNS footprint, a paper reporting "0-30 cm") are
    split across layers in proportion to overlap.
    """
    top, bot = _arr(sensor_top_cm), _arr(sensor_bottom_cm)
    top, bot = np.broadcast_arrays(top, bot)
    thickness = bot - top
    point = thickness <= 1e-9
    overlap = np.maximum(0.0, np.minimum(bot, layer_bottom_cm) - np.maximum(top, layer_top_cm))
    frac = np.where(point,
                    ((top >= layer_top_cm) & (top < layer_bottom_cm)).astype(float),
                    overlap / np.where(thickness > 0, thickness, 1.0))
    return np.clip(frac, 0.0, 1.0)


def profile_storage_mm(
    theta_by_layer: ArrayLike,
    layers_cm: tuple[tuple[float, float], ...] = STANDARD_LAYERS_CM,
    max_depth_cm: float | None = None,
) -> NDArray[np.float64]:
    """Integrate a layered profile of theta into total stored water (mm).

    ``theta_by_layer`` has the layer axis last. Layers deeper than
    ``max_depth_cm`` are excluded, and a layer straddling that depth is counted
    pro rata, which is what makes root-zone storage to an arbitrary rooting
    depth well defined.
    """
    th = _arr(theta_by_layer)
    total = np.zeros(th.shape[:-1])
    for i, (top, bot) in enumerate(layers_cm):
        if max_depth_cm is not None:
            if top >= max_depth_cm:
                continue
            bot = min(bot, max_depth_cm)
        total = total + np.nan_to_num(th[..., i]) * (bot - top) * 10.0
    return total


def exponential_filter_swi(
    surface_theta: ArrayLike,
    times_days: ArrayLike,
    t_characteristic_days: float = 20.0,
) -> NDArray[np.float64]:
    """Wagner exponential filter: root-zone index from a surface soil moisture series.

    Recursive form (Albergel et al. 2008):

        K_n = K_{n-1} / (K_{n-1} + exp(-(t_n - t_{n-1}) / T))
        SWI_n = SWI_{n-1} + K_n (theta_n - SWI_{n-1})

    ``T`` is the characteristic time length, roughly 5-10 days for the top
    30 cm and 20-40 days for a 1 m profile. Useful both as a baseline to beat
    and as an input feature for the deeper layers.
    """
    th = _arr(surface_theta)
    t = _arr(times_days)
    out = np.full(th.shape, np.nan)
    swi = np.nan
    k = 1.0
    for i in range(th.size):
        x = th.flat[i]
        if not np.isfinite(x):
            out.flat[i] = swi
            continue
        if not np.isfinite(swi):
            swi, k = x, 1.0
        else:
            dt = float(t.flat[i] - t.flat[i - 1]) if i > 0 else 1.0
            k = k / (k + np.exp(-dt / t_characteristic_days))
            swi = swi + k * (x - swi)
        out.flat[i] = swi
    return out
