"""Deciding whether a station-year is irrigated, and reconstructing the forcing.

This is the project's defining variable and nothing in the world records it
directly. ISMN has no irrigation attribute. Extent maps answer a different
question from the one being asked. Papers state it in prose, or not at all.

Three questions, and they are not the same question:

======  ===============================================  ==================
Q1      Was the soil volume around *this sensor*          station-year
        irrigated this season?
Q2      By what method, so the wetting geometry is        station-year
        known?
Q3      On what dates, and how much water?                station-day
======  ===============================================  ==================

An irrigation extent map answers "was this 30 m pixel irrigated somewhere this
year", which is neither Q1 nor Q2 nor Q3. A pivot corner, a field edge, or a
station sited on the unmanaged margin of an irrigated quarter-section all read
as irrigated on the map and are not irrigated at the sensor.

**The design rule that everything else follows from: evidence is never collapsed
into a boolean at ingest.** Each raster sample, each sentence in a paper, each
moisture-series signature is stored as its own :class:`Evidence` row, and the
label is *derived* from them by a versioned fusion. When a better irrigation map
ships, or the supplementary irrigation log turns up, the label is re-derived —
nothing is re-ingested and no earlier judgement has been overwritten.

The output is a calibrated probability with the contributing evidence attached,
not a verdict. A station with 0.55 is genuinely uncertain and should be handled
as such by whatever uses it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

#: Bumped whenever the fusion weights or rules change, and stored on every label
#: so that labels derived under different versions are never silently mixed.
FUSION_VERSION = "1.0.0"


class EvidenceKind(str, Enum):
    """Where a piece of evidence came from. Determines its weight."""

    #: The study, network or grower stated it. As close to ground truth as exists.
    DECLARED = "declared"
    #: An irrigation log or water-district delivery record.
    DELIVERY_RECORD = "delivery_record"
    #: Extracted from the paper's text ("plots were irrigated by center pivot").
    PUBLICATION_TEXT = "publication_text"
    #: An irrigation extent raster sampled at the coordinates.
    EXTENT_MAP = "extent_map"
    #: Wetting events in the soil moisture series that rainfall cannot explain.
    MOISTURE_SIGNATURE = "moisture_signature"
    #: The water balance cannot close without an additional input.
    WATER_BALANCE_DEFICIT = "water_balance_deficit"
    #: Crop grown where it could not be grown rainfed in this climate.
    AGRONOMIC_IMPLAUSIBILITY = "agronomic_implausibility"
    #: Land cover says the site is not cropland at all.
    LAND_COVER = "land_cover"


class IrrigationMethod(str, Enum):
    """Method, which is what sets the wetting geometry a sensor sees."""

    CENTER_PIVOT = "center_pivot"
    SPRINKLER = "sprinkler"
    FURROW = "furrow"
    FLOOD = "flood"
    BORDER = "border"
    DRIP_SURFACE = "drip_surface"
    DRIP_SUBSURFACE = "subsurface_drip"
    MICROSPRINKLER = "microsprinkler"
    RAINFED = "rainfed"
    UNKNOWN = "unknown"


#: How much each kind of evidence is worth, as a log-odds contribution when it
#: says "irrigated". A declared method is worth far more than a raster sample,
#: and the gap is deliberately wide: extent maps are the most abundant evidence
#: and the least valid at a point, so abundance must not be allowed to
#: outweigh a single authoritative statement.
EVIDENCE_WEIGHT: dict[str, float] = {
    EvidenceKind.DECLARED: 4.0,
    EvidenceKind.DELIVERY_RECORD: 3.5,
    EvidenceKind.PUBLICATION_TEXT: 2.5,
    EvidenceKind.MOISTURE_SIGNATURE: 1.6,
    EvidenceKind.WATER_BALANCE_DEFICIT: 1.2,
    EvidenceKind.AGRONOMIC_IMPLAUSIBILITY: 1.0,
    EvidenceKind.EXTENT_MAP: 0.9,
    EvidenceKind.LAND_COVER: 0.6,
}

#: Point-scale reliability of each irrigation extent product, as a multiplier on
#: its evidence weight. These are *recalled* figures, not measured here, and are
#: the single most important thing to replace with a real point-scale validation
#: against known-irrigated stations. Every product's headline accuracy is a
#: pixel-scale or county-aggregate number and overstates point validity.
EXTENT_MAP_RELIABILITY: dict[str, float] = {
    "lanid": 1.0,        # 30 m CONUS annual; best of the set in the arid West
    "irrmapper": 1.0,    # 30 m, western US, trained on field boundaries
    "aim_hpa": 0.95,     # High Plains aquifer, annual
    "mirad": 0.7,        # 250 m/1 km; too coarse for a point
    "lgrip30": 0.8,
    "worldcereal": 0.75,
    "gfsad": 0.5,        # 1 km global cropland extent
    "gmia": 0.35,        # ~10 km area fractions; a prior, not a point label
    "unknown": 0.5,
}


@dataclass
class Evidence:
    """One piece of evidence about one station-year."""

    site_id: str
    year: int
    kind: str
    says_irrigated: bool
    #: In [0, 1]: how strongly this particular observation supports its claim.
    strength: float = 1.0
    method: str | None = None
    product: str | None = None
    source: str = ""
    note: str = ""

    def log_odds(self) -> float:
        """Signed contribution to the fused log-odds."""
        weight = EVIDENCE_WEIGHT.get(self.kind, 0.5)
        if self.kind == EvidenceKind.EXTENT_MAP:
            weight *= EXTENT_MAP_RELIABILITY.get((self.product or "unknown").lower(), 0.5)
        magnitude = weight * float(np.clip(self.strength, 0.0, 1.0))
        return magnitude if self.says_irrigated else -magnitude


@dataclass
class IrrigationLabel:
    """The derived label for one station-year, with its provenance."""

    site_id: str
    year: int
    probability: float
    #: irrigated | rainfed | uncertain | ambiguous_multi_treatment
    status: str
    method: str
    method_confidence: float
    n_evidence: int
    evidence_kinds: list[str] = field(default_factory=list)
    fusion_version: str = FUSION_VERSION

    def as_row(self) -> dict:
        return {
            "site_id": self.site_id, "year": self.year,
            "irrigation_probability": round(self.probability, 4),
            "irrigation_status": self.status,
            "irrigation_method": self.method,
            "method_confidence": round(self.method_confidence, 3),
            "n_evidence": self.n_evidence,
            "evidence_kinds": ",".join(sorted(set(self.evidence_kinds))),
            "fusion_version": self.fusion_version,
        }


#: Probability thresholds. The middle band is wide on purpose — a station the
#: evidence cannot settle should be excluded from an irrigated-only analysis
#: *and* from a rainfed-only one, rather than pushed into whichever is nearer.
IRRIGATED_ABOVE = 0.75
RAINFED_BELOW = 0.25

#: Status for a source that describes irrigated *and* rainfed treatments at once.
MULTI_TREATMENT = "ambiguous_multi_treatment"


def detect_multi_treatment(evidence: list[Evidence]) -> bool:
    """Whether the textual evidence describes both irrigated and rainfed plots.

    Nearly every irrigation experiment includes a rainfed or deficit control, so
    a paper saying "center pivot irrigation was compared with a rainfed control"
    is the normal case rather than an edge case. Fusing such a source yields a
    middling probability that is wrong in both directions: the study contains
    both treatments, and which one a particular sensor sits in is simply not
    recoverable from the text.

    Detecting it and saying so is far more useful than averaging it away, because
    it converts a silently-wrong label into an explicit instruction — this source
    needs plot-level assignment, from the figure legend, the table caption or the
    series label, before any of its rows can be used.
    """
    text = [e for e in evidence if e.kind == EvidenceKind.PUBLICATION_TEXT]
    if len(text) < 2:
        return False
    asserts_irrigated = any(
        e.says_irrigated and e.method not in (None, IrrigationMethod.RAINFED.value)
        for e in text
    )
    asserts_rainfed = any(
        (not e.says_irrigated) or e.method == IrrigationMethod.RAINFED.value
        for e in text
    )
    return asserts_irrigated and asserts_rainfed


def fuse(evidence: list[Evidence], prior_log_odds: float = -0.85) -> IrrigationLabel:
    """Combine evidence for one station-year into a calibrated probability.

    A naive-Bayes log-odds sum. The default prior of −0.85 corresponds to about
    0.30 — roughly the share of instrumented agricultural stations that turn out
    to be irrigated — so a station with no evidence at all lands in the uncertain
    band rather than being assumed rainfed.

    Independence is assumed between evidence kinds and is *false* between
    extent maps, which are trained on overlapping imagery and share their
    errors. Multiple map samples are therefore pooled into a single contribution
    before summing, so that agreeing with itself three times does not count
    three times.
    """
    if not evidence:
        raise ValueError("fuse() needs at least one Evidence")

    site_id = evidence[0].site_id
    year = evidence[0].year

    maps = [e for e in evidence if e.kind == EvidenceKind.EXTENT_MAP]
    others = [e for e in evidence if e.kind != EvidenceKind.EXTENT_MAP]

    total = prior_log_odds + sum(e.log_odds() for e in others)
    if maps:
        # Correlated: take the best-supported single contribution and add a small
        # bonus for corroboration rather than summing them.
        contributions = [e.log_odds() for e in maps]
        strongest = max(contributions, key=abs)
        agreeing = sum(1 for c in contributions if np.sign(c) == np.sign(strongest)) - 1
        total += strongest * (1.0 + 0.25 * min(agreeing, 2))

    probability = 1.0 / (1.0 + np.exp(-total))
    multi = detect_multi_treatment(evidence)
    if multi:
        status = MULTI_TREATMENT
    elif probability >= IRRIGATED_ABOVE:
        status = "irrigated"
    elif probability <= RAINFED_BELOW:
        status = "rainfed"
    else:
        status = "uncertain"
    method, method_confidence = resolve_method(evidence, prefer_applied=multi)
    if multi:
        # The method named in the text is the treatment the study applied, but
        # which plot this sensor is in is unresolved, so the method cannot be
        # asserted for it either.
        method_confidence *= 0.4

    return IrrigationLabel(
        site_id=site_id, year=year, probability=float(probability), status=status,
        method=method, method_confidence=method_confidence,
        n_evidence=len(evidence), evidence_kinds=[e.kind for e in evidence],
    )


#: Which evidence kinds may determine the method, best first. A moisture
#: signature can distinguish broad classes but never a specific method.
METHOD_PRECEDENCE = (
    EvidenceKind.DECLARED,
    EvidenceKind.DELIVERY_RECORD,
    EvidenceKind.PUBLICATION_TEXT,
    EvidenceKind.MOISTURE_SIGNATURE,
)


def resolve_method(
    evidence: list[Evidence], prefer_applied: bool = False
) -> tuple[str, float]:
    """Pick the irrigation method by evidence precedence, with a confidence.

    ``prefer_applied`` skips rainfed assertions, which is what a two-treatment
    study needs: naming the method the irrigated arm used tells a plot-level
    assignment what to look for, whereas "rainfed" tells it nothing.

    Method matters because it sets the wetting geometry, and wetting geometry
    decides whether a sensor sees the water at all. A subsurface drip line
    wets a limited volume at 20-30 cm; a probe 40 cm away in the inter-row may
    register almost nothing while the crop is fully irrigated. Recording
    "irrigated" without the method makes such a record unusable, and worse,
    quietly misleading.
    """
    for kind in METHOD_PRECEDENCE:
        stated = [e for e in evidence if e.kind == kind and e.method]
        if prefer_applied:
            # In a two-treatment study the useful answer is what the *irrigated*
            # arm used — that is what a plot-level assignment has to look for.
            applied = [e for e in stated if e.method != IrrigationMethod.RAINFED.value]
            stated = applied or stated
        if not stated:
            continue
        methods = [e.method for e in stated]
        winner = max(set(methods), key=methods.count)
        agreement = methods.count(winner) / len(methods)
        base = {
            EvidenceKind.DECLARED: 0.95,
            EvidenceKind.DELIVERY_RECORD: 0.85,
            EvidenceKind.PUBLICATION_TEXT: 0.75,
            EvidenceKind.MOISTURE_SIGNATURE: 0.35,
        }[kind]
        return winner, base * agreement
    return IrrigationMethod.UNKNOWN.value, 0.0


def fuse_all(evidence: pd.DataFrame, prior_log_odds: float = -0.85) -> pd.DataFrame:
    """Fuse an evidence table into one label row per station-year."""
    required = {"site_id", "year", "kind", "says_irrigated"}
    missing = required - set(evidence.columns)
    if missing:
        raise ValueError(f"evidence table is missing {sorted(missing)}")

    rows = []
    for (site, year), group in evidence.groupby(["site_id", "year"], sort=False):
        items = [
            Evidence(
                site_id=site, year=int(year), kind=r["kind"],
                says_irrigated=bool(r["says_irrigated"]),
                strength=float(r.get("strength", 1.0) or 1.0),
                method=r.get("method"), product=r.get("product"),
                source=str(r.get("source", "")), note=str(r.get("note", "")),
            )
            for _, r in group.iterrows()
        ]
        rows.append(fuse(items, prior_log_odds=prior_log_odds).as_row())
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Building evidence
# --------------------------------------------------------------------------

#: Phrases asserting an irrigation method, longest first. Order matters: the
#: matcher consumes character spans, so "subsurface drip" is claimed before
#: "surface drip" can match inside it — a collision that silently assigned the
#: wrong wetting geometry, which is the one thing the method field exists to get
#: right.
METHOD_PHRASES: tuple[tuple[str, str], ...] = tuple(sorted((
    ("subsurface drip", IrrigationMethod.DRIP_SUBSURFACE.value),
    ("sub-surface drip", IrrigationMethod.DRIP_SUBSURFACE.value),
    ("subsurface drip irrigation", IrrigationMethod.DRIP_SUBSURFACE.value),
    ("buried drip", IrrigationMethod.DRIP_SUBSURFACE.value),
    ("sdi", IrrigationMethod.DRIP_SUBSURFACE.value),
    ("surface drip", IrrigationMethod.DRIP_SURFACE.value),
    ("drip irrigat", IrrigationMethod.DRIP_SURFACE.value),
    ("trickle irrigat", IrrigationMethod.DRIP_SURFACE.value),
    ("micro-sprinkler", IrrigationMethod.MICROSPRINKLER.value),
    ("microsprinkler", IrrigationMethod.MICROSPRINKLER.value),
    ("centre pivot", IrrigationMethod.CENTER_PIVOT.value),
    ("center pivot", IrrigationMethod.CENTER_PIVOT.value),
    ("centre-pivot", IrrigationMethod.CENTER_PIVOT.value),
    ("center-pivot", IrrigationMethod.CENTER_PIVOT.value),
    ("linear move", IrrigationMethod.SPRINKLER.value),
    ("lateral move", IrrigationMethod.SPRINKLER.value),
    ("solid set", IrrigationMethod.SPRINKLER.value),
    ("solid-set", IrrigationMethod.SPRINKLER.value),
    ("sprinkler irrigat", IrrigationMethod.SPRINKLER.value),
    ("furrow irrigat", IrrigationMethod.FURROW.value),
    ("border irrigat", IrrigationMethod.BORDER.value),
    ("basin irrigat", IrrigationMethod.FLOOD.value),
    ("flood irrigat", IrrigationMethod.FLOOD.value),
    ("surface irrigat", IrrigationMethod.FURROW.value),
), key=lambda kv: -len(kv[0])))

#: Phrases that assert irrigation happened (or, negated, that it did not) without
#: naming a method. Without these, "no supplemental irrigation was applied to the
#: control" — the sentence that identifies a rainfed control plot — produced no
#: evidence at all.
PRESENCE_PHRASES: tuple[str, ...] = (
    "supplemental irrigation",
    "supplementary irrigation",
    "irrigation was applied",
    "irrigation were applied",
    "water was applied",
    "irrigation treatment",
    "irrigation scheduling",
    "was irrigated",
    "were irrigated",
    "under irrigation",
    "irrigation amount",
    "irrigation depth",
)

#: Phrases asserting the absence of irrigation outright.
RAINFED_PHRASES: tuple[str, ...] = (
    "rainfed", "rain-fed", "rain fed", "dryland", "non-irrigated", "nonirrigated",
    "un-irrigated", "unirrigated", "without irrigation", "no irrigation",
)

#: Negations checked in a window before a match. "no supplemental irrigation was
#: applied" and "supplemental irrigation was applied" differ by two words.
NEGATIONS = ("no ", "not ", "never ", "without ", "absence of ", "neither ",
             "nor ", "zero ", "non-")

#: Acronyms short enough to match inside unrelated words; these require word
#: boundaries. "sdi" would otherwise fire inside any word containing it.
_SHORT_TOKENS = frozenset({"sdi"})


def _negated_before(text: str, start: int, window: int = 45) -> bool:
    return any(n in text[max(0, start - window) : start] for n in NEGATIONS)


def _find_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    import re as _re

    if phrase in _SHORT_TOKENS:
        return [(m.start(), m.end()) for m in _re.finditer(rf"\b{_re.escape(phrase)}\b", text)]
    out, i = [], text.find(phrase)
    while i != -1:
        out.append((i, i + len(phrase)))
        i = text.find(phrase, i + 1)
    return out


def evidence_from_text(
    site_id: str, year: int, text: str, source: str = "publication", max_items: int = 24
) -> list[Evidence]:
    """Extract irrigation assertions from a paper's text.

    Three passes, in order, each consuming the character spans it claims so that
    a later, shorter phrase cannot match inside an earlier, more specific one:

    1. **Method phrases**, longest first.
    2. **Presence phrases** that assert irrigation without naming a method.
    3. **Rainfed phrases**.

    A negated match produces evidence *against* irrigation rather than nothing,
    because "no supplemental irrigation was applied to the control" is a positive
    statement about a rainfed plot and is exactly as informative as its opposite.
    A negated rainfed phrase ("not rainfed") correspondingly supports irrigation.
    """
    if not text:
        return []
    lowered = text.lower()
    claimed: list[tuple[int, int]] = []

    def overlaps(span: tuple[int, int]) -> bool:
        return any(span[0] < c[1] and c[0] < span[1] for c in claimed)

    def snippet(start: int, end: int) -> str:
        return text[max(0, start - 60) : end + 60].strip()

    out: list[Evidence] = []

    for phrase, method in METHOD_PHRASES:
        for span in _find_spans(lowered, phrase):
            if overlaps(span) or len(out) >= max_items:
                continue
            claimed.append(span)
            negated = _negated_before(lowered, span[0])
            out.append(Evidence(
                site_id=site_id, year=year, kind=EvidenceKind.PUBLICATION_TEXT.value,
                says_irrigated=not negated, strength=0.85 if not negated else 0.75,
                method=method if not negated else None,
                source=source, note=snippet(*span),
            ))

    for phrase in PRESENCE_PHRASES:
        for span in _find_spans(lowered, phrase):
            if overlaps(span) or len(out) >= max_items:
                continue
            claimed.append(span)
            negated = _negated_before(lowered, span[0])
            out.append(Evidence(
                site_id=site_id, year=year, kind=EvidenceKind.PUBLICATION_TEXT.value,
                says_irrigated=not negated, strength=0.6,
                source=source, note=snippet(*span),
            ))

    for phrase in RAINFED_PHRASES:
        for span in _find_spans(lowered, phrase):
            if overlaps(span) or len(out) >= max_items:
                continue
            claimed.append(span)
            negated = _negated_before(lowered, span[0])
            out.append(Evidence(
                site_id=site_id, year=year, kind=EvidenceKind.PUBLICATION_TEXT.value,
                says_irrigated=negated, strength=0.8,
                method=None if negated else IrrigationMethod.RAINFED.value,
                source=source, note=snippet(*span),
            ))

    return out[:max_items]


def evidence_from_extent_map(
    site_id: str, year: int, product: str, fraction: float, source: str = ""
) -> Evidence:
    """One irrigation extent raster sample.

    ``fraction`` is the irrigated fraction or probability at the coordinates.
    The strength is the distance from 0.5, so a pixel the product is itself
    unsure about contributes almost nothing.
    """
    return Evidence(
        site_id=site_id, year=year, kind=EvidenceKind.EXTENT_MAP.value,
        says_irrigated=fraction >= 0.5,
        strength=float(np.clip(abs(fraction - 0.5) * 2.0, 0.0, 1.0)),
        product=product, source=source,
        note=f"{product} irrigated fraction {fraction:.2f}",
    )


def evidence_from_moisture(
    site_id: str,
    year: int,
    observations: pd.DataFrame,
    min_events: int = 4,
    theta_col: str = "theta_m3m3",
    precip_col: str = "precip_mm",
) -> Evidence | None:
    """Unexplained wetting events in the moisture record.

    Reuses :func:`smml.qc.checks.infer_irrigation_events`. Strength rises with
    the number of events and their individual confidence, and the whole thing is
    weak in humid climates where rainfall is frequent enough to be mistaken for
    irrigation — the detector's measured precision drops to below 20 % at such
    sites, which is why this kind is weighted well below a stated method.
    """
    from ..qc.checks import infer_irrigation_events

    if observations.empty:
        return None
    events = infer_irrigation_events(observations, theta_col=theta_col, precip_col=precip_col)
    if events.empty:
        return Evidence(site_id=site_id, year=year,
                        kind=EvidenceKind.MOISTURE_SIGNATURE.value,
                        says_irrigated=False, strength=0.4,
                        note="no unexplained wetting events detected")
    n = len(events)
    mean_confidence = float(events["confidence"].mean())
    says = n >= min_events and mean_confidence > 0.45
    strength = float(np.clip((n / 12.0) * mean_confidence, 0.0, 1.0)) if says else 0.4
    return Evidence(
        site_id=site_id, year=year, kind=EvidenceKind.MOISTURE_SIGNATURE.value,
        says_irrigated=says, strength=strength,
        note=f"{n} unexplained wetting events, mean confidence {mean_confidence:.2f}",
    )


def evidence_from_water_balance(
    site_id: str, year: int, precip_mm: float, etc_mm: float, threshold: float = 1.25
) -> Evidence | None:
    """A crop water requirement that rainfall alone cannot meet.

    If seasonal crop ET exceeds rainfall by more than ``threshold`` and the crop
    nonetheless completed its cycle, water came from somewhere. Weak on its own —
    stored soil water, a shallow water table and capillary rise can all supply
    the gap — but it is independent of every other line of evidence, which is
    what makes it worth carrying.
    """
    if not np.isfinite(precip_mm) or not np.isfinite(etc_mm) or precip_mm <= 0:
        return None
    ratio = etc_mm / precip_mm
    says = ratio > threshold
    strength = float(np.clip((ratio - threshold) / 1.5, 0.0, 1.0)) if says else \
        float(np.clip((threshold - ratio) / 1.0, 0.0, 1.0))
    return Evidence(
        site_id=site_id, year=year, kind=EvidenceKind.WATER_BALANCE_DEFICIT.value,
        says_irrigated=says, strength=strength,
        note=f"seasonal ETc/P = {ratio:.2f}",
    )


def label_error_budget(labels: pd.DataFrame, truth: pd.Series | None = None) -> dict[str, float]:
    """How much of the corpus the labelling actually settles, and how well.

    Without ``truth`` this reports coverage only — the share of station-years
    the evidence resolves either way, which is the number that decides how much
    of the corpus is usable for an irrigated-only analysis.

    With a validated subset it also reports precision and recall against it.
    Building that subset by hand for a few hundred station-years is the single
    highest-value piece of manual work in this project: every downstream claim
    about irrigated fields rests on this label, and at present nothing measures
    whether it is right.
    """
    out = {
        "n": int(len(labels)),
        "share_irrigated": float((labels["irrigation_status"] == "irrigated").mean()),
        "share_rainfed": float((labels["irrigation_status"] == "rainfed").mean()),
        "share_uncertain": float((labels["irrigation_status"] == "uncertain").mean()),
        "mean_evidence_per_label": float(labels["n_evidence"].mean()),
        "share_with_method": float((labels["irrigation_method"] != "unknown").mean()),
    }
    if truth is not None:
        predicted = labels["irrigation_status"] == "irrigated"
        actual = truth.reindex(labels.index).astype(bool)
        resolved = labels["irrigation_status"] != "uncertain"
        tp = int((predicted & actual & resolved).sum())
        fp = int((predicted & ~actual & resolved).sum())
        fn = int((~predicted & actual & resolved).sum())
        out["precision"] = tp / max(tp + fp, 1)
        out["recall"] = tp / max(tp + fn, 1)
        out["resolved_share"] = float(resolved.mean())
    return out
