"""Recovering soil water data from tables in documents.

This is the highest-yield extraction path in the project and it was not obvious
at the outset. Digitizing a plotted curve recovers perhaps five to fifteen points
at two to five percent positional error, after a per-figure calibration that
does not amortize. A table in a thesis appendix carries fifty to five hundred
**exact** values with their units, depths, dates and replicate structure, and a
single parser handles every table in the document.

Where those tables are is equally unobvious. Journals strip appendices; degree
regulations force them in. MSc and PhD theses in irrigation and soil physics are
consequently the densest source of depth-by-date soil water tables in existence,
followed by agricultural experiment station field-day reports and the Joint
FAO/IAEA neutron-probe programme's national reports. All three are grey
literature that the modern machine-learning soil moisture papers essentially
never cite.

The parser is domain-aware rather than generic. A generic table extractor returns
a rectangle of strings; what is needed is the recognition that one axis is depth,
another is time, and that the numbers are water contents in one of six
conventions. Three traps drive most of the design:

**Gravimetric versus volumetric is often unmarked.** Chinese papers use
质量含水率 (gravimetric) and 体积含水率 (volumetric) in roughly equal measure and
do not always say which in the table itself. A value of 18 could be either, and
converting between them needs bulk density.

**Pre-1960 bulletins report "percent moisture in the first foot"** with no bulk
density anywhere in the document. Those records are flagged
``basis=gravimetric, bulk_density=unknown`` and are *not* silently converted.

**Russian and Soviet-tradition papers report запасы влаги** — profile water
storage in millimetres per layer — instead of a water content at all.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


class MoistureBasis:
    """How a reported water content is defined."""

    VOLUMETRIC = "volumetric"          # m3/m3 or vol %
    GRAVIMETRIC = "gravimetric"        # g/g or mass %
    STORAGE = "storage_mm"             # mm of water in a layer
    SATURATION = "degree_of_saturation"
    RELATIVE = "relative"              # normalized 0-1 against unstated bounds
    UNKNOWN = "unknown"


#: Markers that identify the basis, by language. The Chinese pair is the
#: important one: the two terms differ by a single character and decide whether a
#: value needs dividing by bulk density.
BASIS_MARKERS: tuple[tuple[str, str], ...] = (
    # volumetric
    ("volumetric", MoistureBasis.VOLUMETRIC),
    ("vol. water", MoistureBasis.VOLUMETRIC),
    ("vwc", MoistureBasis.VOLUMETRIC),
    ("m3/m3", MoistureBasis.VOLUMETRIC),
    ("m3 m-3", MoistureBasis.VOLUMETRIC),
    ("cm3/cm3", MoistureBasis.VOLUMETRIC),
    ("cm3 cm-3", MoistureBasis.VOLUMETRIC),
    ("体积含水率", MoistureBasis.VOLUMETRIC),
    ("体积含水量", MoistureBasis.VOLUMETRIC),
    ("rutubat-i hacimsel", MoistureBasis.VOLUMETRIC),
    ("hacimsel su", MoistureBasis.VOLUMETRIC),
    ("contenido volum", MoistureBasis.VOLUMETRIC),
    ("umidade volum", MoistureBasis.VOLUMETRIC),
    ("رطوبت حجمی", MoistureBasis.VOLUMETRIC),
    # gravimetric
    ("gravimetric", MoistureBasis.GRAVIMETRIC),
    ("mass water", MoistureBasis.GRAVIMETRIC),
    ("dry weight basis", MoistureBasis.GRAVIMETRIC),
    ("oven-dry", MoistureBasis.GRAVIMETRIC),
    ("g/g", MoistureBasis.GRAVIMETRIC),
    ("质量含水率", MoistureBasis.GRAVIMETRIC),
    ("重量含水率", MoistureBasis.GRAVIMETRIC),
    ("烘干法", MoistureBasis.GRAVIMETRIC),
    ("رطوبت وزنی", MoistureBasis.GRAVIMETRIC),
    ("umidade grav", MoistureBasis.GRAVIMETRIC),
    # storage
    ("water storage", MoistureBasis.STORAGE),
    ("soil water storage", MoistureBasis.STORAGE),
    ("profile storage", MoistureBasis.STORAGE),
    ("запасы влаги", MoistureBasis.STORAGE),
    ("土壤储水量", MoistureBasis.STORAGE),
    ("stored water", MoistureBasis.STORAGE),
    # saturation / relative
    ("degree of saturation", MoistureBasis.SATURATION),
    ("relative soil moisture", MoistureBasis.RELATIVE),
    ("relative water content", MoistureBasis.RELATIVE),
)

#: Header fragments that mark a depth axis.
DEPTH_MARKERS = (
    "depth", "soil depth", "layer", "horizon", "profundidad", "profondeur",
    "tiefe", "toprak derinli", "derinlik", "土层", "深度", "土壤深度", "剖面",
    "عمق", "глубина", "слой", "camada", "profundidade", "심도", "토심", "深さ",
)

#: Header fragments that mark a time axis.
DATE_MARKERS = (
    "date", "day", "doy", "dap", "das", "days after", "sampling", "time",
    "month", "week", "fecha", "data", "tarih", "日期", "取样时间", "播后天数",
    "تاریخ", "дата", "срок",
)

#: Unit strings and the multiplier that puts them on the canonical scale.
#: Volumetric and gravimetric percentages both divide by 100; storage stays mm.
UNIT_SCALE: dict[str, float] = {
    "%": 0.01, "percent": 0.01, "pct": 0.01,
    "m3/m3": 1.0, "m3 m-3": 1.0, "cm3/cm3": 1.0, "cm3 cm-3": 1.0,
    "g/g": 1.0, "kg/kg": 1.0,
    "mm": 1.0, "cm": 10.0,   # storage: cm of water -> mm
}

#: A depth range written in any of the usual ways: "0-15", "0–15 cm", "15 to 30",
#: "0.0-0.15 m", "first foot".
DEPTH_RANGE_RE = re.compile(
    r"(?P<top>\d+(?:[.,]\d+)?)\s*(?:-|–|—|to|~|a|至|ila)\s*(?P<bottom>\d+(?:[.,]\d+)?)"
    r"\s*(?P<unit>cm|mm|m|ft|foot|feet|in|inch|inches|厘米|см)?",
    re.IGNORECASE,
)
DEPTH_POINT_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>cm|mm|m|ft|foot|feet|in|inch|inches|厘米|см)\b",
    re.IGNORECASE,
)

#: Depth unit -> centimetres.
DEPTH_TO_CM: dict[str, float] = {
    "cm": 1.0, "mm": 0.1, "m": 100.0, "ft": 30.48, "foot": 30.48, "feet": 30.48,
    "in": 2.54, "inch": 2.54, "inches": 2.54, "厘米": 1.0, "см": 1.0,
}


@dataclass
class ExtractedTable:
    """One table recovered from a document, with what could be inferred about it."""

    page: int
    index: int
    raw: pd.DataFrame
    caption: str = ""
    basis: str = MoistureBasis.UNKNOWN
    unit: str = ""
    depth_axis: str | None = None      # "rows" | "columns" | None
    date_axis: str | None = None
    score: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def shape(self) -> tuple[int, int]:
        return self.raw.shape


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------


def parse_depth(text: str) -> tuple[float, float] | None:
    """Interpret a cell as a depth or depth interval, returned in centimetres.

    A point depth becomes a zero-thickness interval, which is what a probe at a
    nominal depth actually is; the layer-overlap weighting downstream handles
    both cases.
    """
    if text is None:
        return None
    cleaned = str(text).strip().lower().replace("−", "-")
    if not cleaned:
        return None

    if "first foot" in cleaned:
        return 0.0, 30.48
    if "second foot" in cleaned:
        return 30.48, 60.96

    match = DEPTH_RANGE_RE.search(cleaned)
    if match:
        unit = (match.group("unit") or "cm").lower()
        scale = DEPTH_TO_CM.get(unit, 1.0)
        top = float(match.group("top").replace(",", ".")) * scale
        bottom = float(match.group("bottom").replace(",", ".")) * scale
        # "0.0-0.15" with no unit is metres written as a fraction, not centimetres.
        if match.group("unit") is None and bottom <= 3.0 and "." in cleaned:
            top, bottom = top * 100.0, bottom * 100.0
        return (top, bottom) if bottom >= top else (bottom, top)

    match = DEPTH_POINT_RE.search(cleaned)
    if match:
        scale = DEPTH_TO_CM.get(match.group("unit").lower(), 1.0)
        value = float(match.group("value").replace(",", ".")) * scale
        return value, value

    if re.fullmatch(r"\d+(?:[.,]\d+)?", cleaned):
        value = float(cleaned.replace(",", "."))
        if 0 < value <= 400:
            return value, value
    return None


def parse_number(text: Any) -> float | None:
    """A numeric cell, tolerating the notations tables actually use.

    Handles a decimal comma, a thousands separator, a trailing significance
    letter ("0.21 a"), a trailing unit ("12.3 %", "0.21 cm3/cm3"), a plus-minus
    standard deviation ("0.21±0.03"), and parenthesised values. Returns the central value; the dispersion is discarded
    here and recovered separately where it matters.
    """
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return None
    cleaned = str(text).strip()
    if not cleaned or cleaned.lower() in {"na", "n/a", "nd", "-", "—", "–", "*"}:
        return None

    cleaned = re.split(r"[±±]", cleaned)[0]
    cleaned = re.sub(r"\((.*?)\)", "", cleaned)
    # Trailing unit and significance marks: "18.4 a", "12.3 %", "0.21 cm3/cm3".
    cleaned = re.sub(r"[%\u2030]\s*$", "", cleaned).strip()
    cleaned = re.sub(
        r"[a-zA-Z\u4e00-\u9fff][a-zA-Z0-9/\u00b3\u4e00-\u9fff\s.-]*$", "", cleaned
    ).strip()
    cleaned = re.sub(r"[%\u2030]\s*$", "", cleaned).strip()
    cleaned = cleaned.replace("−", "-").replace(" ", "")

    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")          # thousands separator
    elif re.fullmatch(r"-?\d+,\d+", cleaned):
        cleaned = cleaned.replace(",", ".")          # decimal comma

    try:
        return float(cleaned)
    except ValueError:
        return None


def detect_basis(text: str) -> str:
    """Identify the water-content convention from surrounding text."""
    if not text:
        return MoistureBasis.UNKNOWN
    lowered = str(text).lower()
    for marker, basis in BASIS_MARKERS:
        if marker in lowered:
            return basis
    return MoistureBasis.UNKNOWN


def detect_unit(text: str) -> str:
    """Pull a unit string out of a header or caption."""
    if not text:
        return ""
    lowered = str(text).lower()
    for unit in ("m3/m3", "m3 m-3", "cm3/cm3", "cm3 cm-3", "g/g", "kg/kg",
                 "mm", "cm", "%"):
        if unit in lowered:
            return unit
    if "percent" in lowered or "pct" in lowered:
        return "%"
    return ""


def _is_axis(text: Any, markers: tuple[str, ...]) -> bool:
    if text is None:
        return False
    lowered = str(text).strip().lower()
    return any(marker in lowered for marker in markers)


def plausible_water_content(values: np.ndarray, basis: str) -> bool:
    """Whether a block of numbers could be soil water contents at all.

    Applied to values **already converted to the canonical scale** — a fraction
    for volumetric and gravimetric, millimetres for storage. Checking the
    declared unit here instead was a real bug: the percent range was applied to
    values that had already been divided by a hundred, and every table reported
    in percent was silently discarded.

    This is the strongest single filter available. A volumetric water content
    lives in roughly [0.01, 0.75]; anything whose bulk sits outside that is a
    yield table, a temperature series or a plot number, and rejecting it here
    saves a great deal of downstream nonsense.
    """
    finite = values[np.isfinite(values)]
    if finite.size < 3:
        return False
    median = float(np.nanmedian(finite))
    maximum = float(np.nanmax(finite))
    if basis == MoistureBasis.STORAGE:
        return bool(1.0 < median < 2000.0)
    if basis == MoistureBasis.GRAVIMETRIC:
        # Gravimetric runs lower than volumetric in mineral soil and higher in
        # peat, so the window is wider at both ends.
        return bool(0.005 <= median <= 0.80 and maximum <= 1.5)
    if basis in (MoistureBasis.SATURATION, MoistureBasis.RELATIVE):
        return bool(0.0 <= median <= 1.05 and maximum <= 1.1)
    return bool(0.01 <= median <= 0.75 and maximum <= 1.05)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def extract_tables(
    pdf_path: Path | str,
    pages: list[int] | None = None,
    max_pages: int = 400,
) -> list[ExtractedTable]:
    """Pull every table out of a PDF, with the text around it.

    The caption matters as much as the grid: the basis, the units and often the
    depths are stated there rather than in the header row.
    """
    import pdfplumber

    out: list[ExtractedTable] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        page_numbers = pages or range(min(len(pdf.pages), max_pages))
        for page_number in page_numbers:
            if page_number >= len(pdf.pages):
                continue
            page = pdf.pages[page_number]
            try:
                tables = page.extract_tables()
                page_text = page.extract_text() or ""
            except Exception as exc:
                log.debug("page %d failed: %s", page_number, exc)
                continue

            for index, grid in enumerate(tables):
                if not grid or len(grid) < 2:
                    continue
                frame = pd.DataFrame(grid[1:], columns=[str(c or "") for c in grid[0]])
                caption = _nearest_caption(page_text, index)
                out.append(ExtractedTable(page=page_number, index=index,
                                          raw=frame, caption=caption))
    return out


CAPTION_RE = re.compile(
    r"(?:table|tab\.|tabla|tabela|tablo|\u0442\u0430\u0431\u043b\u0438\u0446\u0430|\u8868|\u062c\u062f\u0648\u0644)"
    r"\s*[.:]?\s*(?:[A-Z]?[.\-]?\d+(?:\.\d+)?)[.:]?\s*(?P<text>[^\n]{0,300})",
    re.IGNORECASE,
)


def _nearest_caption(page_text: str, index: int) -> str:
    captions = [m.group(0).strip() for m in CAPTION_RE.finditer(page_text or "")]
    if not captions:
        return ""
    return captions[min(index, len(captions) - 1)]


def classify_table(table: ExtractedTable) -> ExtractedTable:
    """Work out whether a table holds soil water data, and how it is laid out.

    The axis logic is the part that is easy to get backwards, and getting it
    backwards recovers nothing. A column *headed* "Depth (cm)" means the depths
    are listed **down that column**, so depth runs along the rows. Depth runs
    along the columns only when several column headers *parse as depths* —
    "0-15 cm", "15-30 cm". The two cases look similar and mean opposite things.

    Sets ``basis``, ``unit``, the two axes, and a score in [0, 1]. The score is
    what triage ranks on, so it reads only the header row, the first column and
    the caption, never the whole grid.
    """
    frame = table.raw
    columns = [str(c) for c in frame.columns]
    caption = table.caption or ""

    # Column headers that are themselves depths, e.g. "0-15 cm".
    header_depth_values = [c for c in columns if parse_depth(c) is not None]
    # A column whose header names the depth axis, e.g. "Depth (cm)".
    depth_named_columns = [c for c in columns if _is_axis(c, DEPTH_MARKERS)]
    date_named_columns = [c for c in columns if _is_axis(c, DATE_MARKERS)]

    first_column = frame.iloc[:, 0] if frame.shape[1] else pd.Series(dtype=object)
    first_column_depths = sum(1 for v in first_column if parse_depth(v) is not None)

    if len(header_depth_values) >= 2:
        table.depth_axis = "columns"
    elif depth_named_columns or first_column_depths >= 2:
        table.depth_axis = "rows"

    if table.depth_axis == "rows":
        table.date_axis = "columns"
    elif table.depth_axis == "columns" or date_named_columns:
        table.date_axis = "rows"

    # Units: the value unit lives in the caption or in a value-column header,
    # never in the depth column's header — "Depth (cm)" is not a unit of water.
    value_headers = [c for c in columns if c not in depth_named_columns]
    table.unit = (
        detect_unit(caption)
        or detect_unit(" ".join(value_headers))
        or ("%" if "%" in caption else "")
    )
    table.basis = detect_basis(caption) or MoistureBasis.UNKNOWN
    if table.basis == MoistureBasis.UNKNOWN:
        table.basis = detect_basis(" ".join(columns))

    context = (caption + " " + " ".join(columns)).lower()
    score = 0.0
    if table.depth_axis:
        score += 0.45
    if table.date_axis:
        score += 0.15
    if table.basis != MoistureBasis.UNKNOWN:
        score += 0.20
    moisture_words = ("moisture", "water content", "swc", "vwc", "\u03b8", "humedad",
                      "umidade", "nem", "\u542b\u6c34", "\u0631\u0637\u0648\u0628\u062a",
                      "\u0432\u043b\u0430\u0436\u043d\u043e\u0441\u0442")
    if any(w in context for w in moisture_words):
        score += 0.20
    table.score = min(score, 1.0)

    if table.basis == MoistureBasis.GRAVIMETRIC:
        table.notes.append(
            "gravimetric basis: bulk density is required to convert to volumetric "
            "and is frequently absent from the document"
        )
    return table


def table_to_long(
    table: ExtractedTable,
    study_id: str = "",
    site_id: str = "",
    default_basis: str | None = None,
) -> pd.DataFrame:
    """Reshape a classified table into one row per depth, time and value.

    Returns the harmonized long format: ``depth_top_cm``, ``depth_bottom_cm``,
    ``value``, ``basis``, ``unit``, plus provenance. Conversion to volumetric
    water content is deliberately **not** done here — a gravimetric value needs a
    bulk density that the document often does not contain, and inventing one is
    worse than carrying the basis forward honestly.
    """
    frame = table.raw
    basis = default_basis or table.basis
    scale = UNIT_SCALE.get(table.unit, 1.0)
    rows: list[dict] = []

    if table.depth_axis == "columns":
        depth_columns = {c: parse_depth(c) for c in frame.columns}
        depth_columns = {c: d for c, d in depth_columns.items() if d is not None}
        label_columns = [c for c in frame.columns if c not in depth_columns]
        for _, record in frame.iterrows():
            label = " ".join(str(record[c]) for c in label_columns[:2]).strip()
            for column, (top, bottom) in depth_columns.items():
                value = parse_number(record[column])
                if value is None:
                    continue
                rows.append({"depth_top_cm": top, "depth_bottom_cm": bottom,
                             "time_label": label, "value_raw": value,
                             "value": value * scale})
    elif table.depth_axis == "rows":
        depth_column = frame.columns[0]
        value_columns = list(frame.columns[1:])
        for _, record in frame.iterrows():
            depth = parse_depth(record[depth_column])
            if depth is None:
                continue
            for column in value_columns:
                value = parse_number(record[column])
                if value is None:
                    continue
                rows.append({"depth_top_cm": depth[0], "depth_bottom_cm": depth[1],
                             "time_label": str(column).strip(), "value_raw": value,
                             "value": value * scale})
    else:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    out["basis"] = basis
    out["unit"] = table.unit
    out["study_id"] = study_id
    out["site_id"] = site_id
    out["source_page"] = table.page
    out["source_table"] = table.index
    out["caption"] = table.caption
    out["extraction_method"] = "pdf_table"

    # A percent-scaled value that still looks like a fraction means the unit was
    # misread; better to say so than to divide it by a hundred again.
    values = out["value"].to_numpy(dtype=float)
    if table.unit == "%" and np.nanmedian(values) < 0.02:
        out["unit_warning"] = "declared percent but values look like fractions"
    return out


def harvest_tables(
    pdf_path: Path | str,
    study_id: str = "",
    site_id: str = "",
    min_score: float = 0.5,
) -> tuple[pd.DataFrame, list[ExtractedTable]]:
    """Extract, classify, filter and reshape every soil water table in a document.

    Returns the long-format values and the classified tables, including the ones
    that were rejected — a rejected table is still evidence about what the
    document contains, and the rejection threshold is the first thing to tune
    when yield looks wrong.
    """
    tables = [classify_table(t) for t in extract_tables(pdf_path)]
    frames = []
    for table in tables:
        if table.score < min_score:
            continue
        long = table_to_long(table, study_id=study_id, site_id=site_id)
        if long.empty:
            continue
        if not plausible_water_content(long["value"].to_numpy(dtype=float), table.basis):
            table.notes.append("values are not in a plausible range for soil water")
            continue
        frames.append(long)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combined, tables
