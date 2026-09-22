"""Evaluation metrics for soil moisture prediction.

The soil moisture validation literature has settled on a specific set, and it is
worth using them rather than defaulting to R-squared. In particular **ubRMSE**
— root mean square error after removing the mean difference between prediction
and observation — is the standard, because a large share of the disagreement
between any two soil moisture estimates is a constant offset arising from sensor
calibration and from the mismatch between a point measurement and a modelled
volume. That offset is real but it is a different problem from getting the
dynamics right, and conflating the two hides which one a model has solved.

All functions ignore pairs where either value is missing, and return NaN rather
than raising when too little data survives.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

MIN_SAMPLES = 3


def _clean(y_true: ArrayLike, y_pred: ArrayLike) -> tuple[NDArray, NDArray]:
    t = np.asarray(y_true, dtype=float).ravel()
    p = np.asarray(y_pred, dtype=float).ravel()
    if t.shape != p.shape:
        raise ValueError(f"shape mismatch: {t.shape} vs {p.shape}")
    ok = np.isfinite(t) & np.isfinite(p)
    return t[ok], p[ok]


def rmse(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return float("nan")
    return float(np.sqrt(np.mean((p - t) ** 2)))


def ubrmse(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Unbiased RMSE — RMSE with the mean bias removed.

        ubRMSE = sqrt( mean( [(p - mean(p)) - (t - mean(t))]^2 ) )

    Equivalently ``sqrt(RMSE^2 - bias^2)``. This is the headline number in
    satellite and in-situ soil moisture validation, where the community target
    is 0.04 m3/m3.
    """
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return float("nan")
    return float(np.sqrt(np.mean(((p - p.mean()) - (t - t.mean())) ** 2)))


def bias(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return float("nan")
    return float(np.mean(p - t))


def mae(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return float("nan")
    return float(np.mean(np.abs(p - t)))


def pearson_r(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES or t.std() == 0 or p.std() == 0:
        return float("nan")
    return float(np.corrcoef(t, p)[0, 1])


def spearman_r(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return float("nan")
    tr = pd.Series(t).rank().to_numpy()
    pr = pd.Series(p).rank().to_numpy()
    if tr.std() == 0 or pr.std() == 0:
        return float("nan")
    return float(np.corrcoef(tr, pr)[0, 1])


def r2(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Coefficient of determination against the observed mean.

    Note this is Nash-Sutcliffe efficiency, not the square of the correlation;
    it penalizes bias and variance error, and can be negative.
    """
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return float("nan")
    ss_res = np.sum((t - p) ** 2)
    ss_tot = np.sum((t - t.mean()) ** 2)
    if ss_tot == 0:
        return float("nan")
    return float(1.0 - ss_res / ss_tot)


nse = r2


def kge(y_true: ArrayLike, y_pred: ArrayLike, modified: bool = True) -> float:
    """Kling-Gupta efficiency.

        KGE = 1 - sqrt( (r - 1)^2 + (beta - 1)^2 + (gamma - 1)^2 )

    with ``beta = mean(p)/mean(t)`` the bias ratio and, in the 2012 modified
    form used here by default, ``gamma = CV(p)/CV(t)`` the variability ratio.
    Setting ``modified=False`` uses the original 2009 ``alpha = sd(p)/sd(t)``.

    Decomposing skill into correlation, bias and variability is exactly the
    diagnosis wanted here, because a soil moisture model typically fails in one
    of those three ways and the remedy differs for each.
    """
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return float("nan")
    mt, mp = t.mean(), p.mean()
    st, sp = t.std(), p.std()
    if st == 0 or mt == 0:
        return float("nan")
    r = np.corrcoef(t, p)[0, 1] if (st > 0 and sp > 0) else np.nan
    beta = mp / mt
    gamma = (sp / mp) / (st / mt) if modified and mp != 0 else sp / st
    if not np.isfinite(r) or not np.isfinite(gamma):
        return float("nan")
    return float(1.0 - np.sqrt((r - 1) ** 2 + (beta - 1) ** 2 + (gamma - 1) ** 2))


def kge_components(y_true: ArrayLike, y_pred: ArrayLike, modified: bool = True) -> dict[str, float]:
    """The three KGE terms separately, for diagnosis."""
    t, p = _clean(y_true, y_pred)
    if t.size < MIN_SAMPLES:
        return {"kge_r": np.nan, "kge_beta": np.nan, "kge_gamma": np.nan}
    mt, mp, st, sp = t.mean(), p.mean(), t.std(), p.std()
    r = np.corrcoef(t, p)[0, 1] if (st > 0 and sp > 0) else np.nan
    beta = mp / mt if mt != 0 else np.nan
    gamma = ((sp / mp) / (st / mt)) if (modified and mp != 0 and mt != 0 and st != 0) else (
        sp / st if st != 0 else np.nan
    )
    return {"kge_r": float(r), "kge_beta": float(beta), "kge_gamma": float(gamma)}


def anomaly_correlation(
    y_true: ArrayLike, y_pred: ArrayLike, doy: ArrayLike, window: int = 35
) -> float:
    """Correlation after removing the seasonal climatology from both series.

    A soil moisture model can score a high raw correlation by reproducing the
    annual cycle alone, which is not the skill anyone wants from it. The
    anomaly correlation asks the harder question — whether it gets the departures
    from the seasonal norm right — and is the standard companion metric in
    satellite soil moisture validation.
    """
    t = np.asarray(y_true, dtype=float).ravel()
    p = np.asarray(y_pred, dtype=float).ravel()
    d = np.asarray(doy, dtype=float).ravel()
    ok = np.isfinite(t) & np.isfinite(p) & np.isfinite(d)
    t, p, d = t[ok], p[ok], d[ok]
    if t.size < 30:
        return float("nan")

    def deseason(values: NDArray) -> NDArray:
        clim = np.empty_like(values)
        for i, day in enumerate(d):
            # Circular window around this day of year.
            delta = np.abs(d - day)
            delta = np.minimum(delta, 365.25 - delta)
            sel = delta <= window / 2
            clim[i] = values[sel].mean() if sel.sum() >= 5 else values.mean()
        return values - clim

    ta, pa = deseason(t), deseason(p)
    if ta.std() == 0 or pa.std() == 0:
        return float("nan")
    return float(np.corrcoef(ta, pa)[0, 1])


ALL_METRICS = {
    "rmse": rmse,
    "ubrmse": ubrmse,
    "bias": bias,
    "mae": mae,
    "r": pearson_r,
    "spearman": spearman_r,
    "r2": r2,
    "kge": kge,
}


def compute_metrics(
    y_true: ArrayLike,
    y_pred: ArrayLike,
    prefix: str = "",
) -> dict[str, float]:
    """Every scalar metric at once."""
    out = {f"{prefix}{name}": fn(y_true, y_pred) for name, fn in ALL_METRICS.items()}
    out.update({f"{prefix}{k}": v for k, v in kge_components(y_true, y_pred).items()})
    t, _ = _clean(y_true, y_pred)
    out[f"{prefix}n"] = int(t.size)
    return out


def metrics_by_group(
    frame: pd.DataFrame,
    y_true: str,
    y_pred: str,
    group_cols: str | list[str],
    min_n: int = 10,
) -> pd.DataFrame:
    """Metrics computed within each group.

    Stratified reporting is not optional for this problem. A pooled RMSE hides
    that a model is excellent in loam and useless in clay, or fine at 5 cm and
    hopeless at 1 m — and those are the differences that decide whether it can
    replace a sensor.
    """
    cols = [group_cols] if isinstance(group_cols, str) else list(group_cols)
    rows = []
    for keys, group in frame.groupby(cols, observed=True, dropna=False):
        if len(group) < min_n:
            continue
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(cols, keys, strict=True))
        row.update(compute_metrics(group[y_true], group[y_pred]))
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=cols + list(ALL_METRICS) + ["n"])
    return pd.DataFrame(rows).sort_values(cols).reset_index(drop=True)


def per_site_then_average(
    frame: pd.DataFrame,
    y_true: str,
    y_pred: str,
    site_col: str = "site_id",
    min_n: int = 30,
) -> dict[str, float]:
    """Metrics averaged over sites rather than over observations.

    Pooling every observation lets the sites with the longest records dominate
    the score. Since record length has nothing to do with how hard a site is,
    the per-site average is the fairer summary and the one to quote for
    leave-site-out results. Both are reported in practice; they often differ
    substantially.
    """
    per_site = metrics_by_group(frame, y_true, y_pred, site_col, min_n=min_n)
    if per_site.empty:
        return {f"site_mean_{k}": float("nan") for k in ALL_METRICS}

    def _agg(column: pd.Series, how: str) -> float:
        # A constant prediction has no variance, so correlation is undefined at
        # every site and the whole column is NaN. Reducing that is legitimate and
        # the answer is NaN, but NumPy warns about it; the warning is noise here
        # and would mask a real one elsewhere in the run.
        values = column.dropna()
        if values.empty:
            return float("nan")
        return float(values.mean() if how == "mean" else values.median())

    out = {f"site_mean_{k}": _agg(per_site[k], "mean") for k in ALL_METRICS if k in per_site}
    out.update({f"site_median_{k}": _agg(per_site[k], "median")
                for k in ALL_METRICS if k in per_site})
    out["n_sites"] = len(per_site)
    return out


def _median_or_nan(values: list[float]) -> float:
    """Median over the finite entries, or NaN if there are none, without warning."""
    finite = [v for v in values if np.isfinite(v)]
    return float(np.median(finite)) if finite else float("nan")


def skill_decomposition(
    frame: pd.DataFrame,
    y_true: str,
    y_pred: str,
    site_col: str = "site_id",
    min_n: int = 30,
) -> dict[str, float]:
    """Separate skill *between* sites from skill *within* each site.

    A pooled correlation on a multi-site soil moisture dataset is dominated by
    between-site variance, because texture alone sets a site's mean water content
    over a range far wider than any site's own temporal variation. A model that
    only predicts the site mean therefore scores a high pooled correlation while
    being useless for the thing soil moisture is actually used for — knowing when
    a particular field needs water.

    This decomposition makes that visible, and it is not a hypothetical concern:
    on this project's synthetic corpus, a static pedotransfer baseline that
    predicts field capacity and never changes scored a pooled r of 0.90, third
    best of everything tried, with a within-site r of exactly zero.

    Returns

    ``r_between``
        Correlation of the per-site *means*. High means the model knows which
        fields are wet.
    ``r_within``
        Median over sites of the within-site temporal correlation, computed
        after removing each site's mean. This is the operationally useful skill.
    ``ubrmse_within``
        Median per-site ubRMSE — error after both the site mean and the
        prediction's own offset are removed.
    ``variance_explained_between``
        Share of total variance in the observations that is between-site rather
        than within-site. Context for how much the pooled metrics can be trusted.
    """
    work = frame[[site_col, y_true, y_pred]].dropna()
    if work.empty:
        return {"r_between": np.nan, "r_within": np.nan, "ubrmse_within": np.nan,
                "variance_explained_between": np.nan, "n_sites": 0}

    counts = work.groupby(site_col, observed=True)[y_true].transform("size")
    work = work[counts >= min_n]
    if work.empty or work[site_col].nunique() < 2:
        return {"r_between": np.nan, "r_within": np.nan, "ubrmse_within": np.nan,
                "variance_explained_between": np.nan, "n_sites": int(work[site_col].nunique())}

    means = work.groupby(site_col, observed=True)[[y_true, y_pred]].mean()
    r_between = (
        float(np.corrcoef(means[y_true], means[y_pred])[0, 1])
        if means[y_true].std() > 0 and means[y_pred].std() > 0 else np.nan
    )

    per_site_r, per_site_ub = [], []
    for _, group in work.groupby(site_col, observed=True):
        t, p = group[y_true].to_numpy(), group[y_pred].to_numpy()
        if t.std() > 0 and p.std() > 0:
            per_site_r.append(float(np.corrcoef(t, p)[0, 1]))
        else:
            per_site_r.append(0.0 if p.std() == 0 else np.nan)
        per_site_ub.append(ubrmse(t, p))

    valid_r = [v for v in per_site_r if np.isfinite(v)]
    r_within = float(np.median(valid_r)) if valid_r else float("nan")

    site_mean = work.groupby(site_col, observed=True)[y_true].transform("mean")
    total_var = float(work[y_true].var())
    within_var = float((work[y_true] - site_mean).var())
    between_share = 1.0 - within_var / total_var if total_var > 0 else np.nan

    return {
        "r_between": r_between,
        "r_within": r_within,
        "ubrmse_within": _median_or_nan(per_site_ub),
        "variance_explained_between": float(between_share),
        "n_sites": int(work[site_col].nunique()),
    }
