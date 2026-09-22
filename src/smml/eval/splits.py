"""Cross-validation schemes for spatiotemporal soil moisture data.

The default `KFold` is wrong for this problem, and wrong in a way that produces
excellent-looking numbers. Soil moisture observations are strongly autocorrelated
in time (yesterday's value explains most of today's) and in space (two stations
in the same field see the same weather). A random split puts near-duplicate rows
on both sides of the boundary, so the model is scored on data it has effectively
already seen. Reported R-squared above 0.95 for soil moisture prediction is
almost always this.

What the split should be depends on what the model is claimed to do:

``leave_site_out``
    Can it predict at a field with no sensor? The headline question for this
    project, and the hardest.
``spatial_block``
    The same question, but holding out whole geographic regions, so that a
    held-out site cannot borrow skill from a neighbour 500 m away.
``leave_year_out``
    Can it predict a year it has not seen — a drought, an unusual season?
``forward_chaining``
    Can it predict the future given the past? The operational setting.
``leave_group_out``
    Generic: hold out a climate zone, a texture class, a network, a source.

Every splitter yields integer index arrays and guarantees no row appears in both
sides of a fold.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _as_array(values) -> np.ndarray:
    return np.asarray(values)


def leave_group_out(
    groups: Sequence,
    n_folds: int | None = None,
    seed: int = 0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Hold out whole groups.

    With ``n_folds=None`` every group is held out in turn. Otherwise groups are
    shuffled and dealt into ``n_folds`` roughly equal buckets, which is what you
    want with hundreds of sites where one fold per site would be wasteful.
    """
    g = _as_array(groups)
    unique = pd.unique(g)
    rng = np.random.default_rng(seed)

    if n_folds is None or n_folds >= len(unique):
        buckets = [[u] for u in unique]
    else:
        shuffled = unique.copy()
        rng.shuffle(shuffled)
        buckets = [list(b) for b in np.array_split(shuffled, n_folds)]

    index = np.arange(len(g))
    for bucket in buckets:
        test_mask = np.isin(g, bucket)
        if not test_mask.any() or test_mask.all():
            continue
        yield index[~test_mask], index[test_mask]


def leave_site_out(
    frame: pd.DataFrame,
    n_folds: int | None = 5,
    site_col: str = "site_id",
    seed: int = 0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Hold out entire sites. The primary evaluation for this project."""
    yield from leave_group_out(frame[site_col].to_numpy(), n_folds=n_folds, seed=seed)


def leave_year_out(
    frame: pd.DataFrame,
    date_col: str = "date",
    n_folds: int | None = None,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Hold out entire calendar years, across all sites."""
    years = pd.to_datetime(frame[date_col]).dt.year.to_numpy()
    yield from leave_group_out(years, n_folds=n_folds)


def forward_chaining(
    frame: pd.DataFrame,
    n_splits: int = 5,
    date_col: str = "date",
    gap_days: int = 0,
    expanding: bool = True,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Train on the past, test on the future, repeatedly.

    ``gap_days`` inserts a dead zone between train and test. That gap matters
    here: with rolling features spanning up to a year, a test day immediately
    after the training cut shares most of its feature window with training rows,
    which leaks. Set it to at least the longest feature window for a clean
    operational estimate.

    ``expanding`` grows the training set each split; ``False`` gives a sliding
    window of constant size, which is the right choice when the process is
    non-stationary.
    """
    dates = pd.to_datetime(frame[date_col])
    order = np.argsort(dates.to_numpy())
    sorted_dates = dates.to_numpy()[order]
    n = len(order)
    fold_size = n // (n_splits + 1)
    if fold_size == 0:
        raise ValueError(f"not enough rows ({n}) for {n_splits} forward-chaining splits")

    for k in range(1, n_splits + 1):
        train_end = fold_size * k
        cutoff = sorted_dates[train_end - 1]
        gap_end = cutoff + np.timedelta64(gap_days, "D")
        test_start = int(np.searchsorted(sorted_dates, gap_end, side="right"))
        test_end = min(train_end + fold_size + (test_start - train_end), n)
        if test_start >= test_end:
            continue
        train_start = 0 if expanding else max(0, train_end - fold_size)
        yield order[train_start:train_end], order[test_start:test_end]


def spatial_block(
    frame: pd.DataFrame,
    n_folds: int = 5,
    lat_col: str = "lat",
    lon_col: str = "lon",
    block_size_deg: float = 2.0,
    seed: int = 0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Hold out contiguous geographic blocks.

    Leave-site-out is not sufficient on its own when stations cluster: holding
    out one station of a dense network leaves its neighbours in training, and the
    model can interpolate rather than generalize. Blocking on a coarse grid
    removes that, and is the standard remedy for spatial autocorrelation in
    ecological and hydrological model evaluation.
    """
    lat = frame[lat_col].to_numpy(dtype=float)
    lon = frame[lon_col].to_numpy(dtype=float)
    block = (
        np.floor(lat / block_size_deg).astype(int).astype(str)
        + "_"
        + np.floor(lon / block_size_deg).astype(int).astype(str)
    )
    yield from leave_group_out(block, n_folds=n_folds, seed=seed)


def leave_site_and_year_out(
    frame: pd.DataFrame,
    n_site_folds: int = 4,
    site_col: str = "site_id",
    date_col: str = "date",
    seed: int = 0,
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Hold out unseen sites *in* unseen years — the strictest test.

    Train rows must differ from test rows in both site and year. This is the
    closest analogue to the real deployment: a new field, in a season nobody has
    observed yet.
    """
    sites = frame[site_col].to_numpy()
    years = pd.to_datetime(frame[date_col]).dt.year.to_numpy()
    unique_sites = pd.unique(sites)
    unique_years = pd.unique(years)
    rng = np.random.default_rng(seed)
    shuffled = unique_sites.copy()
    rng.shuffle(shuffled)
    site_buckets = [list(b) for b in np.array_split(shuffled, min(n_site_folds, len(unique_sites)))]

    index = np.arange(len(frame))
    for k, bucket in enumerate(site_buckets):
        held_year = unique_years[k % len(unique_years)]
        test = np.isin(sites, bucket) & (years == held_year)
        train = ~np.isin(sites, bucket) & (years != held_year)
        if test.sum() == 0 or train.sum() == 0:
            continue
        yield index[train], index[test]


def random_kfold_DO_NOT_USE(
    frame: pd.DataFrame, n_folds: int = 5, seed: int = 0
) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """Plain random k-fold. Present only as a leakage demonstration.

    Included so that :func:`compare_split_optimism` can quantify how much a
    random split inflates the score on this data, and so that anyone reaching
    for it in this codebase has to type the name.
    """
    n = len(frame)
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    for fold in np.array_split(order, n_folds):
        mask = np.zeros(n, dtype=bool)
        mask[fold] = True
        yield np.arange(n)[~mask], np.arange(n)[mask]


SPLITTERS = {
    "leave_site_out": leave_site_out,
    "leave_year_out": leave_year_out,
    "forward_chaining": forward_chaining,
    "spatial_block": spatial_block,
    "leave_site_and_year_out": leave_site_and_year_out,
    "random_kfold_DO_NOT_USE": random_kfold_DO_NOT_USE,
}


def get_splitter(name: str, **kwargs):
    """Look up a splitter by name and bind its options."""
    if name not in SPLITTERS:
        raise KeyError(f"unknown split {name!r}; known: {sorted(SPLITTERS)}")
    fn = SPLITTERS[name]

    def splitter(frame: pd.DataFrame):
        return fn(frame, **kwargs)

    splitter.__name__ = name  # type: ignore[attr-defined]
    return splitter


def describe_splits(frame: pd.DataFrame, splitter, site_col: str = "site_id") -> pd.DataFrame:
    """Summarize a split: sizes, and whether any site or row is shared.

    Run this before trusting a new split. The ``sites_shared`` column must be
    zero for any site-holdout scheme; a non-zero value means the evaluation is
    measuring memorization.
    """
    rows = []
    for i, (train, test) in enumerate(splitter(frame)):
        train_sites = set(frame.iloc[train][site_col].unique())
        test_sites = set(frame.iloc[test][site_col].unique())
        rows.append({
            "fold": i,
            "n_train": len(train),
            "n_test": len(test),
            "train_sites": len(train_sites),
            "test_sites": len(test_sites),
            "sites_shared": len(train_sites & test_sites),
            "rows_shared": len(set(train.tolist()) & set(test.tolist())),
        })
    return pd.DataFrame(rows)
