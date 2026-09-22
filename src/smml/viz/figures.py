"""Figures comparing measured and predicted soil moisture.

The set a soil moisture validation needs, and only that set. Each answers a
question the others cannot:

``measured_vs_predicted``
    The 1:1 scatter, faceted by depth. Faceted rather than coloured because six
    depths exceed the three-series cap for forms where every pair is on screen at
    once, and because depth is ordered — a facet grid preserves the ordering that
    six arbitrary hues would destroy.
``time_series``
    Whether the model tracks a field through a season, which the scatter cannot
    show. A scatter can look excellent while the predictions are shifted a week.
``performance_by_depth``
    Where in the profile the model works. Surface and metre depth behave
    differently enough that a pooled number hides both.
``error_by_stratum``
    Error by texture and by salinity — the strata this project exists for.
``clay_correction_effect``
    What the sensor-physics correction actually bought.
``skill_decomposition_figure``
    Between-site against within-site skill, which is the difference between
    knowing which fields are wet and knowing when to irrigate one.

Every figure carries its data's provenance in the corner, because a figure gets
separated from its caption the moment it lands in a slide.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.metrics import compute_metrics, skill_decomposition
from . import style

log = logging.getLogger(__name__)


def _axes_square(ax, low: float, high: float) -> None:
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect("equal", adjustable="box")


def _one_to_one(ax, low: float, high: float) -> None:
    """The 1:1 line, plus the +/-0.04 band that is the community accuracy target."""
    ax.plot([low, high], [low, high], color=style.INK["secondary"],
            linewidth=1.0, linestyle="-", zorder=2)
    ax.fill_between([low, high], [low - 0.04, high - 0.04], [low + 0.04, high + 0.04],
                    color=style.INK["secondary"], alpha=0.07, linewidth=0, zorder=1)


def measured_vs_predicted(
    frame: pd.DataFrame,
    truth_col: str,
    pred_col: str,
    depth_col: str = "depth_mid_cm",
    out: Path | str | None = None,
    max_points_per_facet: int = 4000,
    title: str = "Measured against predicted soil water content",
    notice: str = style.SYNTHETIC_NOTICE,
):
    """The 1:1 scatter, one panel per depth.

    Points are thinned per panel: at a million rows the ink saturates and the
    density structure disappears, and a saturated blob is not more informative
    than a sample of it. The metrics printed in each panel are computed on **all**
    the rows, not on the thinned sample.
    """
    import matplotlib.pyplot as plt

    style.apply()
    depths = sorted(frame[depth_col].dropna().unique())
    n = len(depths)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.3 * cols, 3.45 * rows), squeeze=False)
    colours = style.depth_ramp(n)

    finite = frame[[truth_col, pred_col]].replace([np.inf, -np.inf], np.nan).dropna()
    low = float(max(0.0, min(finite[truth_col].min(), finite[pred_col].min()) - 0.02))
    high = float(min(0.75, max(finite[truth_col].max(), finite[pred_col].max()) + 0.02))
    rng = np.random.default_rng(0)

    for index, depth in enumerate(depths):
        ax = axes[index // cols][index % cols]
        panel = frame[frame[depth_col] == depth][[truth_col, pred_col]].dropna()
        metrics = compute_metrics(panel[truth_col], panel[pred_col])

        shown = panel
        if len(panel) > max_points_per_facet:
            shown = panel.iloc[rng.choice(len(panel), max_points_per_facet, replace=False)]

        _one_to_one(ax, low, high)
        ax.scatter(shown[truth_col], shown[pred_col], s=4, alpha=0.20,
                   color=colours[index], linewidths=0, zorder=3, rasterized=True)
        _axes_square(ax, low, high)
        ax.set_title(f"{depth:g} cm", pad=6)
        ax.text(0.04, 0.96,
                f"RMSE {metrics['rmse']:.3f}\nubRMSE {metrics['ubrmse']:.3f}\n"
                f"bias {metrics['bias']:+.3f}\nr {metrics['r']:.3f}\nn {metrics['n']:,}",
                transform=ax.transAxes, va="top", ha="left", fontsize=7.4,
                color=style.INK["secondary"], linespacing=1.45)
        if index % cols == 0:
            ax.set_ylabel("Predicted  (m$^3$ m$^{-3}$)")
        if index // cols == rows - 1:
            ax.set_xlabel("Measured  (m$^3$ m$^{-3}$)")

    for index in range(n, rows * cols):
        axes[index // cols][index % cols].axis("off")

    fig.suptitle(title, y=0.995, fontsize=12, color=style.INK["primary"])
    fig.text(0.5, 0.963, "grey band is the ±0.04 m$^3$ m$^{-3}$ accuracy target",
             ha="center", fontsize=8, color=style.INK["muted"])
    fig.tight_layout(rect=(0, 0.015, 1, 0.955))
    style.stamp_provenance(fig, notice)
    if out:
        fig.savefig(out)
        log.info("wrote %s", out)
    return fig


def time_series(
    frame: pd.DataFrame,
    truth_col: str,
    pred_col: str,
    site_col: str = "site_id",
    date_col: str = "date",
    depth_col: str = "depth_mid_cm",
    sites: list[str] | None = None,
    depths: list[float] | None = None,
    out: Path | str | None = None,
    title: str = "Measured and predicted through the season",
    notice: str = style.SYNTHETIC_NOTICE,
):
    """Two series through time, per site and depth.

    The check the scatter cannot make: a prediction shifted a week in time scores
    almost as well on a 1:1 plot as one in phase, and is useless for scheduling.
    Two series only, so the first two categorical slots suffice.
    """
    import matplotlib.pyplot as plt

    style.apply()
    work = frame.copy()
    work[date_col] = pd.to_datetime(work[date_col])
    sites = sites or list(pd.unique(work[site_col]))[:3]
    depths = depths or sorted(work[depth_col].dropna().unique())[:3]

    fig, axes = plt.subplots(len(sites), len(depths),
                             figsize=(4.0 * len(depths), 2.5 * len(sites)),
                             squeeze=False, sharex="col")

    for r, site in enumerate(sites):
        for c, depth in enumerate(depths):
            ax = axes[r][c]
            panel = work[(work[site_col] == site) & (work[depth_col] == depth)]
            panel = panel.sort_values(date_col)
            if panel.empty:
                ax.axis("off")
                continue
            ax.plot(panel[date_col], panel[truth_col], color=style.MEASURED,
                    linewidth=1.4, label="Measured", zorder=3)
            ax.plot(panel[date_col], panel[pred_col], color=style.PREDICTED,
                    linewidth=1.4, label="Predicted", zorder=4)
            metrics = compute_metrics(panel[truth_col], panel[pred_col])
            ax.text(0.02, 0.05,
                    f"RMSE {metrics['rmse']:.3f}  r {metrics['r']:.2f}",
                    transform=ax.transAxes, fontsize=7.2,
                    color=style.INK["secondary"])
            if r == 0:
                ax.set_title(f"{depth:g} cm", pad=5)
            if c == 0:
                ax.set_ylabel("$\\theta$  (m$^3$ m$^{-3}$)")
                short = str(site)
                ax.text(-0.30, 0.5, short[-22:], transform=ax.transAxes,
                        rotation=90, va="center", ha="center", fontsize=7.4,
                        color=style.INK["muted"])
            if r == len(sites) - 1:
                ax.tick_params(axis="x", labelrotation=30)

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", ncol=2,
               bbox_to_anchor=(0.995, 0.995))
    fig.suptitle(title, y=0.998, x=0.02, ha="left", fontsize=12,
                 color=style.INK["primary"])
    fig.tight_layout(rect=(0.02, 0.015, 1, 0.955))
    style.stamp_provenance(fig, notice)
    if out:
        fig.savefig(out)
        log.info("wrote %s", out)
    return fig


def performance_by_depth(
    frame: pd.DataFrame,
    truth_col: str,
    pred_col: str,
    depth_col: str = "depth_mid_cm",
    out: Path | str | None = None,
    title: str = "Error through the profile",
    notice: str = style.SYNTHETIC_NOTICE,
):
    """RMSE, ubRMSE and bias against depth, with depth on the vertical axis.

    Depth increases downward, as a soil profile is always drawn. Plotting it on a
    horizontal axis would be conventional for a bar chart and wrong for a soil
    scientist.
    """
    import matplotlib.pyplot as plt

    style.apply()
    depths = sorted(frame[depth_col].dropna().unique())
    rows = []
    for depth in depths:
        panel = frame[frame[depth_col] == depth]
        metrics = compute_metrics(panel[truth_col], panel[pred_col])
        metrics["depth"] = depth
        rows.append(metrics)
    table = pd.DataFrame(rows)

    fig, axes = plt.subplots(1, 3, figsize=(10.2, 4.3), sharey=True)
    specs = [
        ("rmse", "RMSE  (m$^3$ m$^{-3}$)", style.MEASURED),
        ("ubrmse", "ubRMSE  (m$^3$ m$^{-3}$)", style.PREDICTED),
        ("bias", "Bias  (m$^3$ m$^{-3}$)", style.THIRD),
    ]
    for ax, (column, label, colour) in zip(axes, specs, strict=True):
        ax.plot(table[column], table["depth"], color=colour, linewidth=1.8,
                marker="o", markersize=5.5, markeredgecolor=style.INK["surface"],
                markeredgewidth=1.2, zorder=3)
        for _, row in table.iterrows():
            ax.annotate(f"{row[column]:.3f}", (row[column], row["depth"]),
                        textcoords="offset points", xytext=(7, 0), fontsize=7.2,
                        va="center", color=style.INK["secondary"])
        if column == "bias":
            ax.axvline(0, color=style.INK["axis"], linewidth=0.9, zorder=2)
        ax.set_xlabel(label)
        margin = max(abs(table[column]).max() * 0.45, 0.004)
        ax.set_xlim(table[column].min() - margin, table[column].max() + margin)

    axes[0].set_ylabel("Depth  (cm)")
    axes[0].invert_yaxis()
    fig.suptitle(title, y=0.99, x=0.01, ha="left", fontsize=12,
                 color=style.INK["primary"])
    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    style.stamp_provenance(fig, notice)
    if out:
        fig.savefig(out)
        log.info("wrote %s", out)
    return fig, table


def error_by_stratum(
    frame: pd.DataFrame,
    truth_col: str,
    pred_col: str,
    out: Path | str | None = None,
    texture_col: str = "texture_class",
    salinity_col: str = "ece_ds_m",
    clay_col: str = "clay_pct",
    title: str = "Error where dielectric sensors are unreliable",
    notice: str = style.SYNTHETIC_NOTICE,
):
    """Error by texture and by salinity — the strata the project is about.

    Clay and salinity are the two conditions under which a dielectric probe
    misreads, so these are the panels that decide whether the model is worth
    anything. A pooled RMSE says nothing about either.
    """
    import matplotlib.pyplot as plt

    style.apply()
    work = frame.copy()
    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.2))

    # Texture, ordered coarse to fine rather than alphabetically.
    order = ["sand", "loamy_sand", "sandy_loam", "loam", "silt_loam",
             "sandy_clay_loam", "clay_loam", "silty_clay_loam", "sandy_clay",
             "silty_clay", "clay"]
    if texture_col in work.columns:
        rows = []
        for texture in order:
            panel = work[work[texture_col] == texture]
            if len(panel) < 50:
                continue
            metrics = compute_metrics(panel[truth_col], panel[pred_col])
            metrics["texture"] = texture.replace("_", " ")
            rows.append(metrics)
        table = pd.DataFrame(rows)
        positions = np.arange(len(table))
        axes[0].barh(positions, table["rmse"], color=style.MEASURED, height=0.62,
                     zorder=3)
        axes[0].set_yticks(positions, table["texture"], fontsize=8)
        axes[0].invert_yaxis()
        for y, value in zip(positions, table["rmse"], strict=True):
            axes[0].annotate(f"{value:.3f}", (value, y), xytext=(4, 0),
                             textcoords="offset points", va="center", fontsize=7.2,
                             color=style.INK["secondary"])
        axes[0].set_xlabel("RMSE  (m$^3$ m$^{-3}$)")
        axes[0].set_title("by texture, coarse to fine", pad=6)
        axes[0].grid(axis="y", visible=False)

    # Salinity band.
    if salinity_col in work.columns:
        bands = pd.cut(work[salinity_col], [-0.01, 2, 4, 8, 1e6],
                       labels=["non-saline\n<2", "slightly\n2-4",
                               "moderately\n4-8", "strongly\n>8"])
        rows = []
        for band in bands.cat.categories:
            panel = work[bands == band]
            if len(panel) < 50:
                continue
            metrics = compute_metrics(panel[truth_col], panel[pred_col])
            metrics["band"] = band
            rows.append(metrics)
        table = pd.DataFrame(rows)
        positions = np.arange(len(table))
        axes[1].bar(positions, table["rmse"], color=style.PREDICTED, width=0.6,
                    zorder=3)
        axes[1].set_xticks(positions, table["band"], fontsize=8)
        for x, value in zip(positions, table["rmse"], strict=True):
            axes[1].annotate(f"{value:.3f}", (x, value), xytext=(0, 4),
                             textcoords="offset points", ha="center", fontsize=7.4,
                             color=style.INK["secondary"])
        axes[1].set_ylabel("RMSE  (m$^3$ m$^{-3}$)")
        axes[1].set_xlabel("Saturation-extract EC  (dS m$^{-1}$)")
        axes[1].set_title("by salinity", pad=6)
        axes[1].grid(axis="x", visible=False)

    # Residual against clay, which is the mechanism.
    if clay_col in work.columns:
        residual = work[pred_col] - work[truth_col]
        bins = pd.cut(work[clay_col], np.arange(0, 70, 7))
        grouped = pd.DataFrame({"clay": work[clay_col], "residual": residual,
                                "bin": bins}).dropna()
        summary = grouped.groupby("bin", observed=True).agg(
            clay=("clay", "mean"), median=("residual", "median"),
            low=("residual", lambda v: v.quantile(0.25)),
            high=("residual", lambda v: v.quantile(0.75)),
            n=("residual", "size"),
        ).reset_index()
        summary = summary[summary["n"] >= 50]
        axes[2].axhline(0, color=style.INK["axis"], linewidth=0.9, zorder=2)
        axes[2].fill_between(summary["clay"], summary["low"], summary["high"],
                             color=style.THIRD, alpha=0.22, linewidth=0, zorder=3)
        axes[2].plot(summary["clay"], summary["median"], color=style.THIRD,
                     linewidth=1.8, marker="o", markersize=5,
                     markeredgecolor=style.INK["surface"], markeredgewidth=1.1,
                     zorder=4, label="median residual")
        axes[2].set_xlabel("Clay  (%)")
        axes[2].set_ylabel("Predicted − measured  (m$^3$ m$^{-3}$)")
        axes[2].set_title("residual against clay, IQR shaded", pad=6)
        axes[2].legend(loc="upper left")

    fig.suptitle(title, y=0.995, x=0.008, ha="left", fontsize=12,
                 color=style.INK["primary"])
    fig.tight_layout(rect=(0, 0.02, 1, 0.94))
    style.stamp_provenance(fig, notice)
    if out:
        fig.savefig(out)
        log.info("wrote %s", out)
    return fig


def clay_correction_effect(
    raw: pd.DataFrame,
    corrected: pd.DataFrame,
    truth_col: str,
    pred_col: str,
    clay_col: str = "clay_pct",
    out: Path | str | None = None,
    title: str = "What the sensor-physics correction buys",
    notice: str = style.SYNTHETIC_NOTICE,
):
    """Bias against clay, before and after correcting the training target.

    The figure that carries the project's central claim: a model fitted to raw
    dielectric readings inherits their texture bias, and correcting the target
    first removes it.
    """
    import matplotlib.pyplot as plt

    style.apply()
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.3))

    for ax, (frame, label, colour) in zip(
        axes,
        [(raw, "Trained on raw sensor reading", style.MEASURED),
         (corrected, "Trained on clay-corrected reading", style.PREDICTED)],
        strict=True,
    ):
        work = frame.dropna(subset=[truth_col, pred_col, clay_col])
        residual = work[pred_col] - work[truth_col]
        bins = pd.cut(work[clay_col], np.arange(0, 70, 7))
        summary = pd.DataFrame({"clay": work[clay_col], "residual": residual,
                                "bin": bins}).dropna().groupby(
            "bin", observed=True).agg(
            clay=("clay", "mean"), median=("residual", "median"),
            low=("residual", lambda v: v.quantile(0.25)),
            high=("residual", lambda v: v.quantile(0.75)),
            n=("residual", "size")).reset_index()
        summary = summary[summary["n"] >= 50]

        ax.axhline(0, color=style.INK["axis"], linewidth=1.0, zorder=2)
        ax.fill_between(summary["clay"], summary["low"], summary["high"],
                        color=colour, alpha=0.20, linewidth=0, zorder=3)
        ax.plot(summary["clay"], summary["median"], color=colour, linewidth=1.9,
                marker="o", markersize=5.5, markeredgecolor=style.INK["surface"],
                markeredgewidth=1.2, zorder=4)
        metrics = compute_metrics(work[truth_col], work[pred_col])
        ax.set_title(f"{label}\nRMSE {metrics['rmse']:.4f}   bias "
                     f"{metrics['bias']:+.4f}", pad=8, fontsize=10)
        ax.set_xlabel("Clay  (%)")
        ax.set_ylabel("Predicted − measured  (m$^3$ m$^{-3}$)")

    limits = [ax.get_ylim() for ax in axes]
    low = min(limit[0] for limit in limits)
    high = max(limit[1] for limit in limits)
    for ax in axes:
        ax.set_ylim(low, high)

    fig.suptitle(title, y=0.995, x=0.008, ha="left", fontsize=12,
                 color=style.INK["primary"])
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    style.stamp_provenance(fig, notice)
    if out:
        fig.savefig(out)
        log.info("wrote %s", out)
    return fig


def skill_decomposition_figure(
    frame: pd.DataFrame,
    truth_col: str,
    pred_col: str,
    site_col: str = "site_id",
    out: Path | str | None = None,
    title: str = "Skill between sites against skill within a site",
    notice: str = style.SYNTHETIC_NOTICE,
):
    """Site means on the left, per-site temporal correlation on the right.

    These are different abilities and a pooled correlation conflates them. A
    prediction that never changes in time can score a high pooled correlation
    purely by ranking fields correctly, while being useless for deciding when to
    irrigate any one of them.
    """
    import matplotlib.pyplot as plt

    style.apply()
    work = frame.dropna(subset=[truth_col, pred_col])
    decomposition = skill_decomposition(work, truth_col, pred_col, site_col)

    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.4))

    means = work.groupby(site_col, observed=True)[[truth_col, pred_col]].mean()
    low = float(min(means.min()) - 0.02)
    high = float(max(means.max()) + 0.02)
    _one_to_one(axes[0], low, high)
    axes[0].scatter(means[truth_col], means[pred_col], s=26, color=style.MEASURED,
                    alpha=0.8, linewidths=0.8, edgecolors=style.INK["surface"],
                    zorder=4)
    _axes_square(axes[0], low, high)
    axes[0].set_xlabel("Measured site mean  (m$^3$ m$^{-3}$)")
    axes[0].set_ylabel("Predicted site mean  (m$^3$ m$^{-3}$)")
    axes[0].set_title(f"between sites   r = {decomposition['r_between']:.3f}", pad=6)

    per_site = []
    for _, group in work.groupby(site_col, observed=True):
        if len(group) < 30 or group[truth_col].std() == 0 or group[pred_col].std() == 0:
            continue
        per_site.append(float(np.corrcoef(group[truth_col], group[pred_col])[0, 1]))
    axes[1].hist(per_site, bins=np.linspace(-0.2, 1.0, 25), color=style.PREDICTED,
                 zorder=3)
    axes[1].axvline(float(np.median(per_site)), color=style.INK["primary"],
                    linewidth=1.4, zorder=4)
    axes[1].annotate(f"median {np.median(per_site):.3f}",
                     (float(np.median(per_site)), axes[1].get_ylim()[1] * 0.93),
                     xytext=(6, 0), textcoords="offset points", fontsize=8.5,
                     color=style.INK["primary"])
    axes[1].set_xlabel("Within-site correlation")
    axes[1].set_ylabel("Number of sites")
    axes[1].set_title(f"within a site   median r = {decomposition['r_within']:.3f}",
                      pad=6)
    axes[1].grid(axis="x", visible=False)

    fig.suptitle(title, y=0.995, x=0.008, ha="left", fontsize=12,
                 color=style.INK["primary"])
    fig.text(0.008, 0.935,
             f"between-site variance is {decomposition['variance_explained_between']:.0%} "
             "of the total, so a pooled correlation mostly measures the left panel",
             fontsize=8, color=style.INK["muted"])
    fig.tight_layout(rect=(0, 0.02, 1, 0.925))
    style.stamp_provenance(fig, notice)
    if out:
        fig.savefig(out)
        log.info("wrote %s", out)
    return fig, decomposition
