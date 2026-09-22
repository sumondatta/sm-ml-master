"""The falsifiable success criteria, encoded so results are scored against them.

"Replace or minimise soil moisture sensors" is not falsifiable as written, and
as written it is probably false — a model with no sensor in the field will not
beat a well-calibrated TDR probe in a loam. The defensible version is narrower,
stronger, and sits exactly where dielectric sensors fail:

    Replace *dielectric* soil moisture sensors in the soils where dielectric
    sensors are unreliable — high-activity clays and saline soils — using static
    soil attributes, irrigation forcing, remote sensing, and a handful of
    gravimetric calibration samples.

Three products, because they answer three different questions and have three
different accuracy ceilings:

======  =========================================  ========================
A       What is the moisture climatology and       no site data at all
        event response of a field never
        instrumented?
B       How much water is in *this* profile now,   a few gravimetric samples
        to within a few mm, with no permanent
        sensor?
C       What will it be in three days?             forecast forcing
======  =========================================  ========================

Two warnings are built into the thresholds below and should be repeated in any
write-up.

**ubRMSE removes bias, and a dielectric sensor's error in clay and saline soil is
mostly bias.** Comparing a model's ubRMSE against a sensor's total RMSE flatters
the model and a good reviewer will say so. The headline number here is therefore
total RMSE against gravimetric truth, not ubRMSE.

**Satellite validation figures are themselves validated against sensor networks**,
which in clay and saline soils are wrong. Those numbers are unreliable in both
directions in precisely the soils this project targets.

All numeric values are recalled estimates from the literature, not measured
here. They are targets to be argued with, and the point of encoding them is that
a target in code gets checked while a target in a paragraph does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .metrics import compute_metrics

#: Soils where dielectric sensors are unreliable, and therefore where this
#: project's claim actually lives. A model that only works in loam is not
#: answering the question.
DIFFICULT_SOIL = {"clay_pct_min": 35.0, "ece_ds_m_min": 4.0}

#: What a factory-calibrated dielectric probe achieves in those soils — the bar
#: to beat. Recalled; verify against your own gravimetric campaigns.
SENSOR_BASELINE_RMSE = 0.05


@dataclass(frozen=True)
class Target:
    """One numeric criterion, with the reason it is set where it is."""

    name: str
    metric: str
    threshold: float
    direction: str          # "max" = metric must not exceed; "min" = must reach
    rationale: str
    product: str = "A"

    def passes(self, value: float) -> bool | None:
        if value is None or not np.isfinite(value):
            return None
        return value <= self.threshold if self.direction == "max" else value >= self.threshold


#: Product A — no site data. Regional mapping, crop-model forcing, planning.
#: Explicitly *not* good enough to trigger an irrigation on a given day.
PRODUCT_A_TARGETS: tuple[Target, ...] = (
    Target("ubrmse_all_depths", "ubrmse", 0.045, "max", product="A",
           rationale="Leave-site-out ubRMSE at an uninstrumented field. Below ~0.045 is "
                     "competitive with satellite root-zone products; below 0.03 at a new "
                     "site almost certainly means leakage."),
    Target("kge", "kge", 0.50, "min", product="A",
           rationale="Kling-Gupta above 0.5 means correlation, bias and variability are "
                     "all being reproduced, not just one of them."),
    Target("anomaly_r", "r_within", 0.50, "min", product="A",
           rationale="Within-site temporal correlation. A model can score a high pooled "
                     "correlation by reproducing the seasonal cycle and nothing else."),
)

#: Product B — the actual claim. A handful of gravimetric samples, then no sensor.
PRODUCT_B_TARGETS: tuple[Target, ...] = (
    Target("rmse_difficult_soils", "rmse", 0.035, "max", product="B",
           rationale="Total RMSE against gravimetric truth in clay >= 35% or ECe >= 4 dS/m, "
                     "where a factory-calibrated dielectric probe achieves >= 0.05. This is "
                     "the criterion the project stands or falls on."),
    Target("abs_bias_difficult_soils", "bias", 0.015, "max", product="B",
           rationale="Bias is what a dielectric sensor gets wrong in these soils, so a "
                     "replacement that is merely unbiased-on-average is not a replacement."),
)

#: Product C — short-horizon forecast. Scored as improvement over persistence.
PRODUCT_C_TARGETS: tuple[Target, ...] = (
    Target("rmse_gain_over_persistence_day3", "rmse_reduction", 0.25, "min", product="C",
           rationale="25% better than persistence at day+3. Persistence is extremely strong "
                     "at short horizons and a forecast that cannot beat it adds nothing."),
    Target("rmse_gain_over_persistence_day7", "rmse_reduction", 0.15, "min", product="C",
           rationale="15% better than persistence at day+7. The bar is lower than at day+3 "
                     "because persistence itself degrades over a week, so a smaller relative "
                     "gain represents more absolute skill; a forecast that cannot manage even "
                     "this is not informing an irrigation decision a week out."),
)

ALL_TARGETS: dict[str, tuple[Target, ...]] = {
    "A": PRODUCT_A_TARGETS,
    "B": PRODUCT_B_TARGETS,
    "C": PRODUCT_C_TARGETS,
}

#: Below this, a leave-site-out score is not believable and should be
#: investigated as leakage before it is celebrated. Random k-fold on rows gives
#: ubRMSE around 0.015-0.02 on data whose honest leave-site-out value is
#: 0.04-0.06, so a suspiciously good number is the most reliable leak detector
#: there is.
IMPLAUSIBLE_UBRMSE = 0.020


@dataclass
class TargetReport:
    product: str
    rows: pd.DataFrame
    n_observations: int
    leakage_warning: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        decided = self.rows[self.rows["passes"].notna()]
        return bool(len(decided)) and bool(decided["passes"].all())

    def __str__(self) -> str:
        verdict = "PASS" if self.passed else "not met"
        return f"Product {self.product}: {verdict} ({self.n_observations:,} observations)"


def difficult_soil_mask(frame: pd.DataFrame) -> pd.Series:
    """Rows in the soils where dielectric sensors are unreliable.

    Either condition suffices: high-activity clay hides water as bound water, and
    salinity inflates the apparent permittivity of a low-frequency probe. They
    are different failure modes and a soil needs only one of them to be a soil
    this project is about.
    """
    clay = frame.get("clay_pct")
    ece = frame.get("ece_ds_m")
    mask = pd.Series(False, index=frame.index)
    if clay is not None:
        mask |= clay.fillna(-1) >= DIFFICULT_SOIL["clay_pct_min"]
    if ece is not None:
        mask |= ece.fillna(-1) >= DIFFICULT_SOIL["ece_ds_m_min"]
    return mask


def evaluate_targets(
    frame: pd.DataFrame,
    y_true: str,
    y_pred: str,
    product: str = "A",
    skill: dict[str, float] | None = None,
) -> TargetReport:
    """Score predictions against a product's criteria.

    Product B is evaluated on the difficult-soil subset only, because that is
    where its claim applies; scoring it on everything would let good performance
    in loam carry a failure in clay.
    """
    if product not in ALL_TARGETS:
        raise KeyError(f"unknown product {product!r}; known: {sorted(ALL_TARGETS)}")

    work = frame
    notes: list[str] = []
    if product == "B":
        mask = difficult_soil_mask(frame)
        work = frame[mask]
        notes.append(
            f"restricted to clay >= {DIFFICULT_SOIL['clay_pct_min']:.0f}% or "
            f"ECe >= {DIFFICULT_SOIL['ece_ds_m_min']:.0f} dS/m "
            f"({len(work):,} of {len(frame):,} rows)"
        )
        if work.empty:
            notes.append("no rows in the difficult-soil subset; the claim is untested here")

    metrics = compute_metrics(work[y_true], work[y_pred]) if len(work) else {}
    if skill:
        metrics.update(skill)

    rows = []
    for target in ALL_TARGETS[product]:
        value = metrics.get(target.metric)
        if target.metric == "bias" and value is not None:
            value = abs(value)
        rows.append({
            "target": target.name,
            "metric": target.metric,
            "value": round(value, 5) if value is not None and np.isfinite(value) else None,
            "threshold": target.threshold,
            "direction": target.direction,
            "passes": target.passes(value),
            "rationale": target.rationale,
        })

    warning = None
    ubrmse = metrics.get("ubrmse")
    if ubrmse is not None and np.isfinite(ubrmse) and ubrmse < IMPLAUSIBLE_UBRMSE:
        warning = (
            f"ubRMSE of {ubrmse:.4f} is below {IMPLAUSIBLE_UBRMSE} and is not plausible for "
            "an uninstrumented site. Random k-fold on rows produces exactly this, and the "
            "honest leave-site-out value is usually 0.04-0.06. Check the split and check "
            "for a feature carrying site identity before reporting it."
        )

    if product == "B" and len(work):
        rmse = metrics.get("rmse")
        if rmse is not None and np.isfinite(rmse):
            notes.append(
                f"a factory-calibrated dielectric probe in these soils achieves "
                f"RMSE >= {SENSOR_BASELINE_RMSE}; this model achieves {rmse:.4f}"
            )

    return TargetReport(product=product, rows=pd.DataFrame(rows),
                        n_observations=len(work), leakage_warning=warning, notes=notes)


def beats_the_sensor(frame: pd.DataFrame, y_true: str, y_pred: str) -> dict[str, float | bool]:
    """The headline comparison: does the model beat a dielectric probe where probes fail?

    Reports **total RMSE**, not ubRMSE. A dielectric sensor's error in clay and
    saline soil is predominantly bias, which ubRMSE removes, so comparing model
    ubRMSE with sensor total RMSE would flatter the model by exactly the quantity
    at issue.
    """
    subset = frame[difficult_soil_mask(frame)]
    if subset.empty:
        return {"n": 0, "beats_sensor": False,
                "note": "no observations in clay >= 35% or ECe >= 4 dS/m"}
    metrics = compute_metrics(subset[y_true], subset[y_pred])
    return {
        "n": int(metrics["n"]),
        "rmse": round(metrics["rmse"], 5),
        "abs_bias": round(abs(metrics["bias"]), 5),
        "sensor_baseline_rmse": SENSOR_BASELINE_RMSE,
        "beats_sensor": bool(metrics["rmse"] < SENSOR_BASELINE_RMSE),
        "meets_product_b": bool(metrics["rmse"] <= 0.035 and abs(metrics["bias"]) <= 0.015),
    }
