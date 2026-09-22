"""Ranking documents by whether they contain a depth-by-date soil water table.

The harvest's throughput is set by what it chooses to open. A thesis appendix
carries fifty to five hundred exact values; a review article carries none. Since
both match the same keyword query, the ordering matters more than the query
does, and ranking on the wrong thing is how a sweep spends a week downloading
literature reviews.

The scoring therefore asks one question — *does this document contain a table of
soil water content by depth and date* — rather than the usual "is this about
soil moisture". Those give very different orderings. A paper titled "Modelling
root zone soil moisture with machine learning" scores high on relevance and low
here, correctly: it consumes data rather than publishing it.

Three signals, in descending order of how much they are worth:

**Genre.** An MSc or PhD thesis is the densest source of depth-by-date tables in
existence, because degree regulations force raw data into appendices that
journals strip out. Experiment-station field-day reports are second, and
technical reports from the Joint FAO/IAEA neutron-probe programme third.

**Instrumentation named in the title or abstract.** A neutron probe access tube
is installed to read a profile at fixed increments and is almost never used to
publish a single depth. Naming one is close to a guarantee of a depth series.

**Depth language.** "0-120 cm at 15 cm increments" says what the table will look
like.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


#: Document genres, with how much a depth-by-date table is worth expecting.
#: Recalled priors, and the first thing to recalibrate once real yield is
#: measured — ``docs/harvest.md`` explains how.
GENRE_PRIOR: dict[str, float] = {
    "thesis_phd": 0.72,
    "thesis_msc": 0.68,
    "experiment_station_report": 0.60,
    "field_day_report": 0.58,
    "technical_report": 0.45,
    "iaea_tecdoc": 0.62,
    "conference_paper": 0.30,
    "journal_article": 0.26,
    "extension_factsheet": 0.04,
    "review": 0.02,
    "unknown": 0.22,
}

#: Genre detection, longest and most specific first.
GENRE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(doctoral|ph\.?\s?d\.?)\s+(thesis|dissertation)\b", "thesis_phd"),
    (r"\bdissertation submitted\b", "thesis_phd"),
    (r"\b(master'?s?|m\.?\s?sc\.?|m\.?s\.?)\s+(thesis|dissertation)\b", "thesis_msc"),
    (r"\bthesis submitted\b", "thesis_msc"),
    (r"\b(thesis|dissertation|tez|tesis|tese|dissertação|رساله)\b", "thesis_msc"),
    (r"\bfield day (report|proceedings)\b", "field_day_report"),
    (r"\b(agricultural )?experiment station (bulletin|report|circular)\b",
     "experiment_station_report"),
    (r"\b(research|progress) report\b", "experiment_station_report"),
    (r"\btecdoc\b", "iaea_tecdoc"),
    (r"\biaea[- ]tecdoc\b", "iaea_tecdoc"),
    (r"\b(technical|working) (report|paper)\b", "technical_report"),
    (r"\b(proceedings|congress|symposium)\b", "conference_paper"),
    (r"\b(a )?(systematic )?review\b", "review"),
    (r"\bmeta-analysis\b", "review"),
    (r"\b(fact ?sheet|extension bulletin)\b", "extension_factsheet"),
)

#: Instruments that imply a profile. A neutron probe access tube exists to be
#: read at fixed increments down its length.
PROFILE_INSTRUMENTS: tuple[str, ...] = (
    "neutron probe", "neutron moisture", "neutron scattering", "access tube",
    "中子仪", "中子水分仪", "sonda de neutrones", "sonda de nêutrons",
    "nötron probu", "нейтронный влагомер",
    "رطوبت‌سنج نوترونی",
    "gravimetric sampling", "soil coring", "auger sampling", "烘干法",
    "diviner 2000", "enviroscan", "sentek", "pr2 profile probe", "delta-t pr2",
    "trime", "drill and drop",
)

#: Language that describes a depth series rather than a single depth.
DEPTH_PHRASES: tuple[str, ...] = (
    "increments", "at 15 cm", "at 20 cm", "at 30 cm", "depth increments",
    "soil profile", "profile water", "to a depth of", "0-120", "0-150", "0-180",
    "0-100 cm", "0–100 cm", "successive depths", "each depth", "by depth",
    "土层", "剖面", "不同土层深度", "по слоям",
)

#: Wording that a table of raw values follows.
TABLE_PHRASES: tuple[str, ...] = (
    "appendix", "appendices", "raw data", "supplementary table", "table a",
    "tabulated", "data are presented in table", "附录", "anexo", "apêndice",
    "الملحق", "приложение",
)

#: Subjects that mention soil moisture constantly and publish none.
CONSUMER_PHRASES: tuple[str, ...] = (
    "machine learning", "deep learning", "neural network", "random forest",
    "data assimilation", "satellite retrieval", "downscaling", "reanalysis",
    "land surface model", "remote sensing of soil moisture", "smap validation",
)


@dataclass
class TriageScore:
    """Why a document was ranked where it was."""

    document_id: str
    score: float
    genre: str
    signals: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        row = {"document_id": self.document_id, "table_probability": round(self.score, 4),
               "genre": self.genre, "reasons": "; ".join(self.reasons)}
        row.update({f"signal_{k}": round(v, 3) for k, v in self.signals.items()})
        return row


def detect_genre(text: str) -> str:
    """Classify a document's genre from its title, type field and abstract."""
    if not text:
        return "unknown"
    lowered = text.lower()
    for pattern, genre in GENRE_PATTERNS:
        if re.search(pattern, lowered):
            return genre
    return "unknown"


def _hits(text: str, phrases: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [p for p in phrases if p in lowered]


def score_document(
    document_id: str,
    title: str = "",
    abstract: str = "",
    genre_hint: str = "",
    full_text: str = "",
) -> TriageScore:
    """Probability, roughly, that this document contains a depth-by-date table.

    Starts from the genre prior and moves it with the other signals in log-odds
    so that no single signal can saturate the result. ``full_text`` is optional
    and worth a great deal when available — "Appendix C. Soil water content" is
    close to decisive, and is invisible in a title.
    """
    context = " ".join(filter(None, [title, abstract, genre_hint]))
    genre = detect_genre(context) if not genre_hint else (
        detect_genre(genre_hint) if detect_genre(genre_hint) != "unknown" else detect_genre(context)
    )
    prior = GENRE_PRIOR.get(genre, GENRE_PRIOR["unknown"])
    log_odds = float(np.log(prior / (1 - prior)))

    signals: dict[str, float] = {}
    reasons: list[str] = []
    searchable = context + " " + (full_text[:200_000] if full_text else "")

    instruments = _hits(searchable, PROFILE_INSTRUMENTS)
    if instruments:
        bump = min(0.9 * len(instruments), 1.8)
        log_odds += bump
        signals["instrument"] = bump
        reasons.append(f"profile instrument named ({instruments[0]})")

    depths = _hits(searchable, DEPTH_PHRASES)
    if depths:
        bump = min(0.45 * len(depths), 1.2)
        log_odds += bump
        signals["depth_language"] = bump
        reasons.append(f"depth-series language ({len(depths)} cues)")

    tables = _hits(searchable, TABLE_PHRASES)
    if tables:
        bump = min(0.6 * len(tables), 1.5)
        log_odds += bump
        signals["table_language"] = bump
        reasons.append(f"tabulated-data language ({tables[0]})")

    consumers = _hits(context, CONSUMER_PHRASES)
    if consumers:
        penalty = min(0.8 * len(consumers), 2.0)
        log_odds -= penalty
        signals["data_consumer"] = -penalty
        reasons.append(f"consumes rather than publishes data ({consumers[0]})")

    if genre in ("review", "extension_factsheet"):
        log_odds -= 1.5
        signals["genre_penalty"] = -1.5
        reasons.append(f"{genre} genre rarely carries raw values")

    score = float(1.0 / (1.0 + np.exp(-log_odds)))
    return TriageScore(document_id=document_id, score=score, genre=genre,
                       signals=signals, reasons=reasons)


def triage(
    documents: pd.DataFrame,
    id_col: str = "doi",
    title_col: str = "title",
    abstract_col: str = "abstract",
    genre_col: str | None = "type",
    full_text_col: str | None = None,
) -> pd.DataFrame:
    """Rank a candidate set, highest expected table yield first."""
    rows = []
    for _, record in documents.iterrows():
        rows.append(score_document(
            document_id=str(record.get(id_col, "")),
            title=str(record.get(title_col, "") or ""),
            abstract=str(record.get(abstract_col, "") or ""),
            genre_hint=str(record.get(genre_col, "") or "") if genre_col else "",
            full_text=str(record.get(full_text_col, "") or "") if full_text_col else "",
        ).as_row())
    scored = pd.DataFrame(rows)
    if scored.empty:
        return scored
    merged = documents.reset_index(drop=True).join(
        scored.drop(columns=["document_id"]).reset_index(drop=True)
    )
    return merged.sort_values("table_probability", ascending=False).reset_index(drop=True)


def yield_estimate(scored: pd.DataFrame, values_per_table: float = 90.0) -> pd.DataFrame:
    """How many values each slice of the ranked list is expected to return.

    Turns the ranking into a stopping rule: fetch down the list until the
    marginal expected yield per download stops justifying the bandwidth and the
    politeness budget. ``values_per_table`` is the mean count from a real
    thesis-appendix table and should be replaced with a measured figure once a
    few hundred documents have been processed.
    """
    if scored.empty or "table_probability" not in scored:
        return pd.DataFrame()
    work = scored.sort_values("table_probability", ascending=False).reset_index(drop=True)
    work["rank"] = np.arange(1, len(work) + 1)
    work["expected_values"] = work["table_probability"] * values_per_table
    work["cumulative_expected"] = work["expected_values"].cumsum()
    buckets = pd.cut(work["table_probability"], [0, 0.2, 0.4, 0.6, 0.8, 1.0],
                     labels=["<0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", ">0.8"])
    return (
        work.groupby(buckets, observed=True)
        .agg(n_documents=("rank", "size"),
             expected_values=("expected_values", "sum"),
             mean_probability=("table_probability", "mean"))
        .reset_index()
        .rename(columns={"table_probability": "probability_band"})
        .iloc[::-1]
        .reset_index(drop=True)
    )
