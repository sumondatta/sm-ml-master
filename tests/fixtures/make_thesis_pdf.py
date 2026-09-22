"""Generate thesis-appendix-style PDFs with soil water tables of known values.

Used to measure what the table extractor actually recovers. Three layouts are
produced because all three occur in the literature and they fail differently:
depth down the rows with dates across the columns, the transpose of that, and a
gravimetric table with no bulk density anywhere — the pre-1960 bulletin case
that must be flagged rather than silently converted.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

DEPTHS = [(0, 15), (15, 30), (30, 60), (60, 90), (90, 120)]
DATES = ["12 May", "26 May", "09 Jun", "23 Jun", "07 Jul", "21 Jul", "04 Aug", "18 Aug"]

GRID = TableStyle([
    ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ("FONTSIZE", (0, 0), (-1, -1), 8),
])


def truth(seed: int = 11) -> np.ndarray:
    """Water contents that behave like a real profile: drier at the surface,
    damped with depth, drying through the season."""
    rng = np.random.default_rng(seed)
    out = np.zeros((len(DEPTHS), len(DATES)))
    for i, (top, bottom) in enumerate(DEPTHS):
        mid = (top + bottom) / 2
        base = 0.18 + 0.055 * np.log1p(mid) / np.log1p(105)
        amplitude = 0.075 * np.exp(-mid / 55)
        season = np.linspace(0.9, -0.9, len(DATES))
        out[i] = base + amplitude * season + rng.normal(0, 0.004, len(DATES))
    return np.round(np.clip(out, 0.02, 0.5), 3)


def build(path: Path, seed: int = 11) -> np.ndarray:
    values = truth(seed)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Appendix C. Soil water content measurements", styles["Heading2"]),
        Spacer(1, 8),
        Paragraph(
            "Table C.1 Volumetric soil water content (m3/m3) by depth and sampling "
            "date, subsurface drip irrigated cotton, 2019 season.",
            styles["BodyText"],
        ),
        Spacer(1, 4),
    ]

    # Layout 1 — depth down the rows.
    grid = [["Depth (cm)", *DATES]]
    for i, (top, bottom) in enumerate(DEPTHS):
        grid.append([f"{top}-{bottom}"] + [f"{v:.3f}" for v in values[i]])
    table = Table(grid)
    table.setStyle(GRID)
    story += [table, Spacer(1, 18)]

    # Layout 2 — the transpose, depths across the header.
    story += [
        Paragraph(
            "Table C.2 Volumetric water content (%) by sampling date, same plots, "
            "expressed as a percentage.",
            styles["BodyText"],
        ),
        Spacer(1, 4),
    ]
    grid = [["Sampling date"] + [f"{t}-{b} cm" for t, b in DEPTHS]]
    for j, date in enumerate(DATES):
        grid.append([date] + [f"{values[i, j] * 100:.1f}" for i in range(len(DEPTHS))])
    table = Table(grid)
    table.setStyle(GRID)
    story += [table, Spacer(1, 18)]

    # Layout 3 — gravimetric, no bulk density anywhere in the document.
    story += [
        Paragraph(
            "Table C.3 Gravimetric soil moisture (percent, dry weight basis), "
            "first and second foot, 1948 season.",
            styles["BodyText"],
        ),
        Spacer(1, 4),
    ]
    grid = [["Depth", *DATES[:4]]]
    for label, row in (("first foot", 0), ("second foot", 2)):
        grid.append([label] + [f"{values[row, j] * 100 / 1.35:.1f}" for j in range(4)])
    table = Table(grid)
    table.setStyle(GRID)
    story.append(table)

    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return values


if __name__ == "__main__":
    out = Path(__file__).parent / "thesis_appendix.pdf"
    values = build(out)
    np.save(out.with_suffix(".truth.npy"), values)
    print(f"wrote {out} and its ground truth {values.shape}")
