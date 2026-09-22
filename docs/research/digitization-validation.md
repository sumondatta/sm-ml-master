<!--
Compiled from a research sweep, not written by hand. Preserved verbatim because
it is reference material the implementation draws on rather than prose meant to
be read start to finish.

CONFIDENCE: the sweep's web-search budget was exhausted before these sections
ran, so everything in them is recalled from model knowledge and NONE of it was
corroborated by a search. Every URL and every accuracy figure must be verified
before it is relied on. Nothing here is legal advice.
-->

Zero web searches were possible: the session's WebSearch budget (200/200) was already exhausted by earlier steps in this workflow before my first call, and WebFetch/curl to external hosts are blocked. **Every citation and number below is `recalled` from training, not `confirmed`.** I have marked the ones that most need verification and put a prioritized verification list at the end. I have not invented any URL or endpoint.

---

# Empirical validation and throughput design for figure digitization of soil moisture time series

## 0. The framing correction that should come first

Before the protocol, one result from the error arithmetic in §4, because it reorders the whole design:

**Pixel-limited precision is never the binding constraint.** For a typical journal figure (plot area ~70 mm tall, y-axis span 0.35 m³/m³, 1 pt stroke) the combined trace/anti-aliasing/calibration error is **~0.0007 m³/m³ at 300 dpi, ~0.0013 at 150 dpi, and ~0.0026 even at 72 dpi**. Calibrated TDR/capacitance sensors are ±0.02–0.03 m³/m³; plot-scale spatial representativeness is ±0.015–0.025. Digitization noise is 1–3% of the honest total uncertainty.

So the reviewer's question "how do you know the digitized values are right?" is **not** a question about sub-pixel accuracy. It is a question about **blunders and semantics**:

| Error class | Magnitude when it occurs | Est. rate if unguarded |
|---|---|---|
| Pixel/trace geometry | 0.001–0.003 m³/m³ | ~always, negligible |
| Axis calibration blunder (wrong tick, log/linear confusion) | 0.05–0.30 | 2–5% of series |
| Series mis-assignment (trace attached to wrong depth) | 0.02–0.08 | **5–15%** in ≥4-series greyscale figures |
| Unit/quantity misidentification (w/w vs v/v, mm storage, %FC, %AW, depletion) | 0.05–0.20 | **10–20%** without full-text cross-check |
| ρb assumption in g/g → m³/m³ conversion | 0.01–0.03 | whenever gravimetric |
| Date-axis reconstruction (DAP/DAS → calendar) | 0–7 d typical, whole-season if planting date absent | 20–30% of figures |
| Representativeness (plot mean vs point) | 0.015–0.025 | irreducible, belongs in σ |

**Design consequence:** spend engineering effort on the semantic gauntlet (§4) and on a machine-readable provenance record, not on trace refinement. And split the architecture so that **geometry comes from pixels/vectors deterministically, semantics comes from a VLM reading text, and the VLM is never allowed to emit a coordinate.** That single rule removes the dominant VLM failure mode (confabulated numeric series, §3).

---

## 1. Vector yield survey — protocol and priors

### 1.1 Sampling frame

Target N = 280 PDFs, stratified two-way. Draw from your existing screened candidate list so the survey estimates the yield *of your corpus*, not of the literature at large.

Publisher strata (n per stratum):

| Stratum | n | Journals |
|---|---|---|
| Elsevier | 45 | Agricultural Water Management, Field Crops Research, Geoderma, Soil & Tillage Research, Agric. & Forest Meteorology, Sci. Total Environ. |
| Springer Nature | 30 | Irrigation Science, Plant and Soil, Precision Agriculture, Paddy & Water Environment |
| Wiley / ACSESS | 35 | Vadose Zone J., Water Resources Research, Agronomy J., SSSAJ, JEQ, Crop Science |
| MDPI | 30 | Water, Agronomy, Remote Sensing, Sustainability, Land |
| Frontiers | 20 | Front. Plant Sci., Front. Environ. Sci., Front. Water |
| Copernicus | 20 | HESS, SOIL, ESSD, Biogeosciences |
| ASABE | 20 | Trans. ASABE, Applied Eng. in Agriculture, J. Irrig. Drain. Eng. (ASCE) |
| Chinese journals (CNKI/Wanfang) | 35 | Trans. CSAE (农业工程学报), Sci. Agric. Sinica, J. Hydraulic Eng., Chinese J. Eco-Agriculture |
| Theses / grey literature | 25 | ProQuest, institutional repositories, FAO/ICARDA/IWMI/CGIAR reports |
| Other (Taylor & Francis, Iranian/Turkish/Indian, Scientia Agricola) | 20 | |

Decade strata, crossed: pre-1990, 1990–99, 2000–09, 2010–19, 2020–26, with a floor of n=25 in each pre-2000 cell so the raster-only hypothesis is actually testable.

### 1.2 Per-figure classification (5 classes, not 4)

Classify the *target figure only* (the θ-vs-time panel), not the whole PDF.

```
V1  True vector paths      page.get_drawings() yields Path items whose points
                           lie inside the axes bbox, AND stroke colour/dash
                           partitions them into >=1 series.
V2  Vector frame, raster   get_drawings() returns only axes/ticks/frame;
    data                   page.get_images() returns an image whose bbox is
                           inside the axes bbox. (Matlab -dpdf opengl, Word/EMF,
                           Excel paste, R with rasterised layers.)
R1  Raster >=300 DPI       Single embedded image, effective DPI = img.width /
                           (bbox.width/72) >= 300.
R2  Raster 150-300 DPI     as above, 150 <= eff. DPI < 300.
R3  Raster <150 DPI /      eff. DPI < 150, or bitonal (CCITT G4 / 1-bit),
    scanned                or page has no extractable text layer (scanned).
```

Also record, per figure, the four covariates that actually drive extractability: `n_series`, `colour|greyscale|bitonal`, `has_error_bars`, `has_second_axis`. The yield survey is wasted if it only gives you a vector fraction and not the joint distribution with series count.

Practical detection code sketch (deterministic, no ML):

```python
# per page, per figure bbox
d  = page.get_drawings()                       # PyMuPDF
im = page.get_image_info(xrefs=True)
in_axes = lambda r: fitz.Rect(r).intersects(axes_bbox)
paths_in  = [p for p in d if in_axes(p["rect"])]
imgs_in   = [i for i in im if in_axes(i["bbox"])]
eff_dpi   = i["width"] / (fitz.Rect(i["bbox"]).width / 72.0)
is_bitonal = i["cs-name"] == "DeviceGray" and i["bpc"] == 1
```
Class V2 is the one people forget and it is the costliest to miss, because `get_drawings()` returns *something* and a naive pipeline will happily digitize the axis frame and report zero data points.

### 1.3 Expected proportions — priors to be replaced by the measurement

These are reasoned from publisher typesetting workflows (LaTeX/EPS-preserving vs Word-based), **recalled, wide uncertainty, ±12 pp**:

| Stratum (2000–2026) | V1 | V2 | R1 | R2 | R3 |
|---|---|---|---|---|---|
| Copernicus | 75% | 5% | 15% | 4% | 1% |
| Wiley (WRR, VZJ) | 45% | 8% | 35% | 10% | 2% |
| Elsevier | 42% | 8% | 38% | 10% | 2% |
| Springer | 38% | 8% | 40% | 12% | 2% |
| Wiley/ACSESS (Agron. J., SSSAJ) | 32% | 10% | 42% | 14% | 2% |
| ASABE | 22% | 12% | 45% | 18% | 3% |
| MDPI | 18% | 10% | 55% | 15% | 2% |
| Frontiers | 15% | 10% | 58% | 15% | 2% |
| Chinese journals | 15% | 8% | 40% | 27% | 10% |
| Theses / grey | 40% | 6% | 26% | 18% | 10% |
| **Corpus-weighted 2000–2026** | **~30%** | **~9%** | **~42%** | **~14%** | **~5%** |

Pre-2000: **assume V1 = 0**. ScienceDirect/Springer/Wiley backfiles are scans of print, typically 300–600 dpi **bitonal CCITT G4**. Bitonal is not automatically bad for line art — resolution is often fine — but **colour and grey are destroyed**, so 4–6 depth series can only be separated by dash period and marker glyph, and dash period needs ≥400 dpi to resolve. Practical pre-2000 yield of multi-series figures is low. Flag: this is the single most confident prediction in this section and the one that most changes scope.

Note the V1 fraction is not the same as the *usable* V1 fraction. In V1 figures, expect **15–25% to fail series separation** because the PDF producer emitted all series as one concatenated `Path` with subpaths, or drew markers as filled `re`/`c` primitives indistinguishable from data glyphs, or clipped the axes so the trace extends beyond the visible region. Report **"V1 and separable"** as the headline number, not "V1".

### 1.4 DPI at which each method degrades

| Method | Works | Degrades | Fails |
|---|---|---|---|
| Vector path extraction (PyMuPDF `get_drawings`) | resolution-free | — | on V2, on concatenated paths, on clipped traces |
| Colour-mask auto-trace (WPD auto, HSV segmentation) | ≥200 dpi (stroke ≥2 px) | 150–200 dpi | <150 dpi with any series overlap; any greyscale with >2 series |
| Instance segmentation (LineFormer/LineEX) | inputs resized to **800–1200 px wide**; source ≥150 dpi | source 100–150 dpi | <100 dpi; >4 series in one colour family; >4 mutual crossings. **Also degrades if you feed 4000 px** — must downsample to training scale |
| Marker/blob detection (scatter series) | marker ≥6 px → ≥150 dpi for a 3 pt marker | 4–6 px | <4 px; markers merge with error-bar caps |
| Dash-pattern discrimination (bitonal scans) | ≥400 dpi | 300–400 dpi | <300 dpi |
| VLM reading axis/legend **text** | ≥120 dpi for 8 pt type | 90–120 dpi | <90 dpi |

---

## 2. Ground-truth benchmark

### 2.1 Concrete paired (figure, true data) sources

**Tier A — editorial policy guarantees the pair exists** (highest yield per hour of benchmark construction):

- **Data in Brief** (Elsevier, ISSN 2352-3409). Every article is a figure-plus-deposited-dataset by design. This is the best mine in the entire literature for this purpose and I would start here. Filter for irrigation/soil water entries.
- **Scientific Data** (Nature, ISSN 2052-4463) — descriptors must deposit; the technical-validation figures plot the deposited data.
- **ESSD** (Copernicus) — same guarantee, *and* LaTeX-produced, so ESSD gives you matched V1 figures while Data in Brief gives you mostly R1. Use both to get the vector/raster contrast within one truth source.
- **Papers with supplementary CSV/XLSX duplicating a figure** — detectable at scale by scanning supplementary filenames for `.csv|.xlsx` and column headers matching `depth|VWC|SWC|theta|date`.

**Tier B — public dataset replotted in a paper** (best source of *hard* cases):

- **ISMN** (International Soil Moisture Network, ismn.earth; Dorigo et al., HESS 2011 / 2021 — recalled). ~2,800 stations. **SMAP/SMOS Cal-Val papers plot named-station θ time series at 5/10/20/50/100 cm, with precipitation bars inverted from a top axis** — i.e. exactly the pathology you named — and the truth is one download away, keyed by station name + date range printed in the figure. This is the single richest source of realistic hard-case benchmark pairs.
- **USCRN** (5/10/20/50/100 cm soil moisture since ~2009), **SCAN** (NRCS), Oklahoma Mesonet, TxSON, TERENO, OzNet, REMEDHUS, HOBE, Twente, Naqu/Maqu/Ngari (Tibetan Plateau) — all heavily replotted.
- **AmeriFlux US-Ne1 / US-Ne2 / US-Ne3** (Mead, NE; irrigated continuous maize / irrigated maize-soybean / rainfed). SWC at ~10/25/50/100 cm; replotted in the Suyker & Verma line of papers and dozens of downstream modelling studies. BADM ancillary files give texture and management. **These are irrigated**, which most network sites are not — high value.
- **USDA-ARS Bushland, TX** large weighing lysimeters + neutron-probe profiles (Evett, Howell, Copeland, Marek, Colaizzi), deposited in **Ag Data Commons** (data.nal.usda.gov) with DOIs of the form `10.15482/USDA.ADC/…`. The same seasonal profiles appear as figures in the accompanying journal papers. *Recalled — I could not verify the specific dataset↔figure pairs or whether the descriptors are in Scientific Data specifically; verify before relying on this.*

**Tier C — synthesized truth** (unlimited, controls the degradation axis, must never be the headline):

Take 200 real ISMN/AmeriFlux/Bushland series and render them through style emulators for matplotlib, ggplot2/R base, Excel, Origin and SigmaPlot, sweeping: DPI ∈ {72, 100, 150, 300, 600}, series count ∈ {2,3,4,5,6}, palette ∈ {default colour, viridis, greyscale, bitonal}, JPEG quality ∈ {60, 85, 100}, error bars on/off, second axis on/off. Then **print–scan round-trip** a subset at 200/300/600 dpi bitonal to emulate pre-2000 backfiles.

Report Tier A/B as the headline; Tier C only as the degradation curve. Reporting synthetic numbers as headline accuracy is exactly how the chart-extraction literature (§3) overstates itself, and a reviewer in this field will catch it.

**A fourth source appears for free later:** every corresponding author who sends you raw data (§6) for a paper you already digitized becomes a new Tier-A benchmark row. Instrument the email workflow to capture these.

### 2.2 Benchmark composition — 108 figures, ~420 series

| Cell | Figures | Why |
|---|---|---|
| Easy control: 2–3 separated colour series, V1 | 15 | establishes the ceiling |
| 4–6 overlapping depth series, colour | 20 | the modal real case |
| 4–6 overlapping depth series, greyscale/dashed | 15 | the hardest common case |
| Markers only, no connecting line | 8 | neutron-probe convention |
| With error bars | 10 | known systematic bias |
| Dual axis, inverted precipitation bars from top | 10 | near-universal in this domain |
| Log y or broken axis | 6 | rare but catastrophic if unflagged |
| Raster <150 dpi / scanned bitonal | 10 | scope decision |
| Non-Latin axis labels (Chinese / Persian / Turkish) | 6 | OCR failure mode |
| 2D contour (θ or ECe isopleths over depth×time) | 8 | measured *in order to justify excluding* |

Plus a **human-ceiling arm**: two trained analysts independently digitize 30 of these with WebPlotDigitizer, blind to each other. Their disagreement is the practical noise floor and the only fair comparator for automation. Pre-register that any automated method within the inter-analyst band is "at human parity"; do not claim better.

### 2.3 Metrics

Per point, per series, per figure:

1. **MAE and RMSE in m³/m³** — the units a reviewer cares about.
2. **Relative error vs axis range**, `|Δθ| / (θ_max,axis − θ_min,axis)` — comparable across figures with different axis spans; this is also the unit the chart-extraction literature reports in, so it enables comparison with §3.
3. **Date-alignment error in days** — the fitted time offset (see §2.4), reported separately from value error.
4. **Series-assignment accuracy** — fraction of extracted series bound to the correct depth label.
5. **Series-level pass/fail** — pass iff median |Δθ| ≤ 0.010 **and** P95 |Δθ| ≤ 0.025 **and** the assignment is correct **and** |time offset| ≤ 3 d. This single binary is what feeds the throughput model.
6. **Point recall/precision** — fraction of truth timestamps covered; fraction of extracted points that are spurious (error-bar caps, gridline artefacts, legend glyphs traced as data).
7. **Calibration of the reported σ** — are 68% of errors inside ±1σ from the §4 formula? A σ that is not calibrated is worse than no σ, because the ML model will weight on it.

### 2.4 Matching an irregular extracted trace to a regular truth series

**Use interpolation with a fitted affine time correction. Do not use DTW as the primary matcher.** Justification:

- Time here is a *shared physical axis with independent ground truth*, not a latent warping. DTW's whole premise — that the time correspondence is unknown and free — is false, and warping time destroys the exact quantity (date-alignment error) you are trying to measure.
- DTW will cheerfully align an extracted 30 cm trace onto the truth 60 cm curve and report a low distance, silently hiding the dominant real error (series mis-assignment).
- Drydown dynamics confound value and timing error, but they are separately meaningful and separately actionable (a timing error means the DAP→calendar conversion is wrong; a value error means the axis or trace is wrong).

Procedure:

```
(a) Fit a 2-parameter affine time map t' = a*t + b by minimising SSE,
    bounded |b| <= 10 d and |a-1| <= 0.03.
    Report b as the date-alignment error. a != 1 beyond the bound => reject
    (the x-axis was mis-calibrated, not merely offset).
(b) With time fixed, PCHIP-interpolate the extracted trace onto the truth
    timestamps that fall strictly inside the extracted x-range.
    PCHIP, not cubic spline: no overshoot at drydown inflections.
    Never extrapolate.
(c) Compute metrics 1-3 on those timestamps.
(d) Series assignment: Hungarian matching between extracted and truth series,
    cost = median |dtheta|. Report the fraction correct. This cleanly
    separates "traced well, labelled wrong" from "traced badly".
(e) Use open-begin-end DTW ONLY as a diagnostic: if the DTW path departs
    from the affine model by more than the (a,b) bounds allow, raise an
    axis-calibration flag. Never use its distance as an accuracy metric.
```

---

## 3. Method comparison and expected errors

**All numbers in this section are recalled and must be verified.** I flag the ones I am least sure of.

### 3.1 Manual WebPlotDigitizer — the meta-analysis methods literature

This literature exists and is the right thing to cite, because it measured digitization against original data. Recalled studies:

| Study (recalled) | Domain | Finding |
|---|---|---|
| Shadish, Brasil, Illingworth, White, Galindo, Nagler, Rindskopf (2009), *Behav. Res. Methods* 41(1):45–52 | single-case behavioural graphs, UnGraph | near-perfect agreement with known values |
| Rakap, Rakap, Evran, Cig (2016), *Computers in Human Behavior* 55:159–166 | UnGraph vs GraphClick vs DigitizeIt | all three high reliability and validity; no meaningful difference between them |
| Drevon, Fursa, Malcolm (2017), *Behavior Modification* 41(2):323–339 | **WebPlotDigitizer specifically** | intercoder ICC ≈ 0.99; validity vs known values very high |
| Jelicic Kadic, Vucic, Dosenovic, Sapunar, Puljak (2016), *J. Clin. Epidemiol.* 74:119–123 | Cochrane figures | software extraction **faster and with higher interrater reliability** than manual ruler extraction |
| Cramond, O'Mara-Eves, Doran-Constant, Rice, Macleod, Thomas (2016), *Wellcome Open Research* 1:14 | preclinical systematic reviews | purpose-built online graph-extraction app; good agreement |
| Burda, O'Connor, Webb, Tricco (2017), *Research Synthesis Methods* 8(3):258–262 | web-based extraction for SRs | small discrepancies; practical cautions |

**Typical reported magnitudes: ICC / Pearson r ≥ 0.99; mean absolute discrepancy generally <1–2% of the plotted axis range.** On a 0.35 m³/m³ axis that is 0.0035–0.007 m³/m³.

**Critical caveat you must state in your own paper:** every one of these studies extracted a modest number of well-separated points from clean 1–2 series behavioural or clinical graphs. **None of them is a test of 5 overlapping depth series in greyscale with error bars over an inverted precipitation axis.** Quoting "ICC 0.99" as your expected accuracy would be indefensible. Treat these as the *floor* — the error you get when the figure is easy — and let your own §2 benchmark supply the number for the hard cells.

### 3.2 Automatic curve tracing and chart-extraction models

| System (recalled) | Venue | Reported metric | My read |
|---|---|---|---|
| ChartOCR (Luo et al.) | WACV 2021 | keypoint-based, chart-type-specific | superseded |
| LineEX (Shivasankaran, Kumar, Jawahar) | WACV 2023 | improvement over ChartOCR on synthetic line charts | synthetic-heavy |
| **LineFormer** (Lal et al.) | ICDAR 2023 | instance segmentation; **data-extraction F1 ~0.93–0.97 on synthetic (LineEX / Adobe Synthetic); markedly lower on real charts** — exact real-chart number I do **not** recall reliably | best available open line-tracer; still review-only |
| ChartDETR | — | metrics not reliably recalled | unverified |
| DePlot (Liu, Chen, Eisenschlos et al.) | ACL Findings 2023 | chart→table; **RNSS** and **RMS_F1** ~87–94% on synthetic; DePlot+LLM raised ChartQA human-set accuracy by **~24 points** over prior SOTA | table derivation, not per-point trace recovery |
| MatCha (Liu et al.) | ACL 2023 | chart pretraining | upstream of DePlot |
| UniChart (Masry et al.) | EMNLP 2023 | chart-domain vision-language pretraining | |
| ChartGemma (Masry et al.) | 2024 | 3B, PaliGemma-based, instruction-tuned on chart images | |

**The tolerance trap.** ChartQA's headline metric is **relaxed accuracy with ±5% tolerance**. On a 0–0.5 m³/m³ axis, ±5% is **±0.025 m³/m³** — the entire sensor error budget. A model reported at "90% on ChartQA" is being graded at a tolerance that is useless to you. Never quote ChartQA numbers as evidence for this project. Grade everything at your own thresholds (§2.3, metric 5).

### 3.3 Frontier VLMs reading numeric values off scientific line charts

Recalled 2024–2026 evidence:

- **CharXiv** (Wang et al., NeurIPS 2024) — real charts harvested from arXiv, deliberately unlike ChartQA's cleaned synthetic-ish set. Strongest proprietary VLMs scored roughly **47–50% on the reasoning split versus ~80% human**, with descriptive questions far easier than value-extraction ones. The headline finding — **that models look strong on ChartQA and collapse on real scientific figures** — is the single most relevant published result for this project.
- **SciFIBench** (2024) — scientific figure interpretation benchmark built from real paper figures; same qualitative conclusion.
- **PlotExtract** — named in the task brief. **I cannot confirm this from training and could not search. Treat as unverified; do not cite it until you have read it.**

**Failure modes, in order of how much they will hurt you** (recalled from the behaviour of this model class, high confidence qualitatively):

1. **Confabulated series.** Asked for 25 (date, θ) pairs, a VLM produces 25 plausible, smooth, axis-respecting numbers that are not the curve. This is the killer: the output is *syntactically perfect and unfalsifiable by inspection*. It is why the VLM must never emit coordinates.
2. **Regularization.** Returns exactly N evenly spaced points when sampling was irregular; smooths out the sharp irrigation wetting fronts that carry all the physical information.
3. **Legend/series order confusion** — assigns the 100 cm trace the 10 cm label. Directly produces the §0 "series mis-assignment" error.
4. **Secondary-axis blindness** — reads precipitation bars against the θ axis.
5. **Log-axis linearization** — reads a log axis as linear.
6. **Counting failure** beyond ~15–20 points.
7. **Axis-range hallucination** when tick labels are small or non-Latin.

### 3.4 Safe unsupervised vs review-only — the verdict

| Method | Verdict |
|---|---|
| **PyMuPDF vector path extraction**, when the figure is V1, series separate cleanly by stroke colour/dash, and the tick re-projection residual passes G1 | **Safe unsupervised.** Deterministic; exact to typesetter precision. This is the only fully trustworthy path, and it covers ~25% of the corpus (0.30 V1 × ~0.8 separable). Maximize this fraction — it is why the §1 survey matters. |
| Colour-mask auto-trace on ≥300 dpi raster with ≤3 well-separated colour series | **Safe unsupervised with G10 cross-check** (two independent extractors agreeing within 0.010). |
| LineFormer / LineEX on raster | **Review-only.** Good geometry proposals; unacceptable unsupervised error rate on the hard cells. |
| DePlot / UniChart / ChartGemma / MatCha | **Review-only, and mostly the wrong tool** — they produce a table summarizing a chart, not a faithful per-point trace of an irregularly sampled time series. |
| **Frontier VLM emitting numeric coordinates** | **Never. Not even review-only.** Confabulation is undetectable by the reviewer at the speed review must run. |
| **Frontier VLM reading text: axis labels, units, legend entries, depth labels, treatment names, caption, in-scope/out-of-scope triage, DAP→date anchor from the methods section** | **Safe with a text-grounding check** — require the VLM to quote the source string it read, and verify that string exists in the PDF text layer or OCR. This is where VLMs are genuinely excellent and where they resolve the §0 dominant error classes (units, depth labels, dates). |

That split — **geometry deterministic, semantics VLM-with-quote-grounding, no VLM coordinates ever** — is the core architectural recommendation of this whole analysis.

---

## 4. Accept/reject gauntlet with numeric thresholds

Every series must pass. Three failure actions: **R** = auto-reject, **T** = human triage queue, **F** = admit with inflated σ and a flag.

| ID | Check | Threshold | Fail action |
|---|---|---|---|
| G1 | **Axis calibration residual.** Re-project ≥4 known tick positions through the fitted transform | RMS residual ≤ 0.4% of axis length (≈3 px on an 800 px axis) | **R** |
| G2 | **Strictly increasing x.** Sort; merge duplicates within 0.25× nominal sampling interval | >5% duplicates or any reversal >0.5 interval | **T** (≤5%: **F**) |
| G3 | **Physical range.** θ ∈ [0.8·θr, 1.05·θs] from Carsel & Parrish (1988) / Rosetta3 (Zhang & Schaap 2017) for the reported texture. 1.05·θs allows near-saturation under flood/basin irrigation | >2% of points outside → **R**; ≤2% → clip + flag **F** | **R/F** |
| G4 | **No unexplained wetting.** At depth ≤30 cm, Δθ > +0.015 between consecutive points with no precipitation or irrigation in the preceding (Δt + 2 d) window | >2 such events, or any single event >0.05 | **T** |
| G5 | **Monotonic drydown recession.** Between wetting events at 20–100 cm | ≤20% of inter-event steps positive, none > +0.008 | **T** |
| G6 | **Depth variance ordering.** SD(θ) non-increasing with depth | SD(d_{i+1}) ≤ 1.25 × SD(d_i) | **T** + auto re-assignment attempt |
| G7 | **Cross-depth lag.** Peak cross-correlation lag, adjacent depths | lag ≥ 0 d (deeper lags shallower) and ≤ 15 d | **T** + auto re-assignment attempt |
| G8 | **Point count vs stated interval.** n vs span_days / stated interval | n ∈ [0.6, 1.4] × expected | **T** |
| G9 | **Quantisation / confabulation guard.** Fraction of values snapping to a grid finer than 1 px, or to round numbers | >60% snapped | **R** |
| G10 | **Cross-method agreement.** Two independent extractors (vector or colour-mask, and LineFormer) | median \|Δθ\| ≤ 0.010 → auto-accept; 0.010–0.025 → **T**; >0.025 → **R** | — |
| G11 | **Seasonal mass balance**, where irrigation + rainfall are reported | Σ(positive Δstorage) ≤ 1.25 × (irrigation + rainfall) | **T** |
| G12 | **Unit/quantity guard.** VLM-read axis label must parse to one of {v/v fraction, v/v %, g/g %, mm per stated layer, % FC, % AW, depletion}. ρb required for g/g→v/v | unparsed, or conversion needed with no ρb | **T**; if ρb absent, admit **as gravimetric only**, never silently converted |

G6 and G7 together enable **automatic repair** of the single largest error class: when depth ordering is violated, test all permutations of the series→depth assignment and accept the unique permutation that satisfies both G6 and G7. If more than one permutation satisfies them, send to triage. Repaired series carry a ×2.0 σ inflation (below).

Carsel & Parrish θr/θs by texture class (HYDRUS defaults, **recalled** — verify against Rosetta3 for your final table): sand 0.045/0.43; loamy sand 0.057/0.41; sandy loam 0.065/0.41; loam 0.078/0.43; silt 0.034/0.46; silt loam 0.067/0.45; sandy clay loam 0.100/0.39; clay loam 0.095/0.41; silty clay loam 0.089/0.43; sandy clay 0.100/0.38; silty clay 0.070/0.36; clay 0.068/0.38. For your salinity-focused sites, prefer Rosetta3 predictions from the actual sand/silt/clay percentages over the class averages.

### Per-point σ formula

```
s = Δθ_axis / H_px                      # m³/m³ per pixel

σ_point² = s²·( σ_trace² + σ_aa² + σ_cal² )  +  σ_unit²  +  σ_repr²

σ_trace = w_px / √12                    # w_px = stroke width in pixels
          + 1.0 px in quadrature for each series crossing within 3 px
σ_aa    = 0.6 px for raster, 0.0 for vector
σ_cal   = RMS tick re-projection residual from G1, in pixels
σ_unit  = 0                       for direct v/v
        = θ_g · σ_ρb              for g/g → v/v, σ_ρb ≈ 0.08 g cm⁻³
        = θ · σ_Δz / Δz           for mm → v/v with layer-thickness ambiguity
σ_repr  = 0.015–0.025 m³/m³       plot-mean vs point representativeness

Inflate:  ×1.5 if admitted with any F flag
          ×2.0 if the depth assignment was resolved by the G6/G7
                permutation search rather than read directly from the legend
```

Worked example — 300 dpi raster, H = 827 px, Δθ = 0.35, 1 pt stroke (4.17 px), σ_cal = 0.8 px, direct v/v:

```
s        = 0.35 / 827            = 4.23e-4
σ_trace  = 4.17/√12              = 1.20 px
σ_aa     = 0.6 px ;  σ_cal = 0.8 px
pixel term = 4.23e-4 · √(1.44+0.36+0.64) = 4.23e-4 · 1.56 = 6.6e-4 m³/m³
σ_point  = √(6.6e-4² + 0² + 0.020²)      = 0.0200 m³/m³
```

The pixel term contributes **0.1% of the variance**. Weight the ML training loss by σ_repr; do not build machinery to shave σ_trace.

---

## 5. Throughput and cost model

### Assumptions (state these in the paper)

Mean 3.2 series per figure; 1.4 usable figures per paper; 150 productive hours per person-month; trained analyst, purpose-built tooling, not a first-time user.

### Minutes per figure

**(a) Fully manual WebPlotDigitizer**

| Step | min |
|---|---|
| Axis calibration (4 points, units, log check) | 2.5 |
| Per-series masked auto-extract + manual cleanup, ×3.2 | 8.0 |
| Export, sanity-check, file | 2.0 |
| **Digitizing subtotal** | **12.5** |
| Paper metadata (site, coords, texture, depths, treatments, dates, irrigation) 15 min/paper ÷ 1.4 | 10.7 |
| Screening 8 min/paper ÷ 1.4 | 5.7 |
| **End-to-end** | **~29** |

**(b) Automated extraction + human verification** (assumes a 70% first-pass accept rate in the review UI — *this number comes out of the §2 benchmark; until then it is an assumption, not a result*)

| Step | min |
|---|---|
| Verify in overlay UI: 0.7 × 2.5 (accept) + 0.3 × 9.0 (manual redo) | 4.5 |
| LLM metadata extraction + human confirm, 5 min/paper ÷ 1.4 | 3.6 |
| LLM-assisted screening, 2 min/paper ÷ 1.4 | 1.4 |
| **End-to-end** | **~9.5** |

**(c) Fully automatic + 10% spot-check audit**

| Step | min |
|---|---|
| Audit 0.1 × 4.5 | 0.45 |
| Gauntlet exception handling | 0.5 |
| Metadata auto + 10% audit | 0.5 |
| **End-to-end** | **~1.5** — at an unmeasured error rate likely in the 15–30% band |

### Person-months

| Figures | (a) manual | (b) assisted | (c) automatic |
|---|---|---|---|
| 1,000 | 483 h = **3.2 PM** | 158 h = **1.1 PM** | 25 h = **0.2 PM** |
| 10,000 | 4,833 h = **32 PM** | 1,583 h = **10.6 PM** | 250 h = **1.7 PM** |
| 100,000 | 48,333 h = **322 PM** | 15,833 h = **106 PM** | 2,500 h = **17 PM** |

The realistic corpus is **4,000–8,000 figures** (§7), so route (b) is **4–8 person-months**. That is the number to put in the grant: *one person, roughly half a year*, for a defensible corpus. Route (a) at that size is 13–26 PM and is not worth it. Route (c) is tempting but unpublishable without the §2 benchmark to bound its error.

### VLM API cost per figure

Anthropic image token count ≈ `(width × height) / 750`. A figure downsampled to the 1568 px long-edge cap, ~1568×1100 → **~2,300 image tokens**. Plus ~1,500 tokens of instructions (cacheable) and ~3,800 output tokens (compact JSON for 4 series × 25 points, plus adaptive-thinking tokens, which bill as output).

Current pricing:

| Model | $/MTok in | $/MTok out | $/figure (1×) | ×3 self-consistency | ×3 + Batch (−50%) |
|---|---|---|---|---|---|
| `claude-opus-5` | $5.00 | $25.00 | $0.114 | $0.34 | **$0.17** |
| `claude-sonnet-5` | $2.00 | $10.00 | $0.046 | $0.14 | **$0.07** |
| `claude-haiku-4-5` | $1.00 | $5.00 | $0.023 | $0.07 | **$0.035** |

Totals with `claude-opus-5`, 3× self-consistency, Batch API:

| Figures | API cost |
|---|---|
| 1,000 | **$170** |
| 10,000 | **$1,700** |
| 100,000 | **$17,000** |

**Conclusion: API cost is irrelevant and human minutes are everything.** At 10,000 figures the API bill is ~$1.7k against ~10.6 PM of loaded labour (order $60k–$130k). Therefore: run 3–5× self-consistency and a two-model cross-check on every figure as a **free confidence signal** feeding the triage in §5.2. Cache the instruction block; use the Batch API throughout.

### 5.1 Minimal review UI

Streamlit or Gradio, one figure per screen, keyboard-driven — the whole point is to get accept/reject down to 2.5 seconds of decision plus render time.

```
Layout
  Left  : figure PNG at native resolution, with the extracted trace
          re-drawn on top as a semi-transparent overlay, one colour per
          extracted series, markers at every extracted point.
  Right : the gauntlet report — each of G1..G12 as a green/amber/red row
          with its numeric value, so the reviewer sees WHY it was queued.
          Below it: axis calibration points, parsed units, depth labels,
          and the VLM's quoted source strings for each.
  Bottom: sparkline of the extracted series vs the median of the other
          series in the same figure (catches assignment errors instantly).

Keys
  A  accept          R  reject (+ reason code from a 6-item list)
  1..6 toggle series visibility
  S  swap two series' depth labels  (the single most common fix)
  D  open in WebPlotDigitizer pre-loaded with the fitted axis calibration
  ?  show the paper's methods paragraph (VLM-extracted, quote-grounded)
```

Two details that matter more than the rest: **pre-load the fitted axis calibration into WPD** when the reviewer escalates to manual, so the 2.5-minute calibration is never repeated; and **log every reject reason code**, because that log is your active-learning label set and your error taxonomy for the paper.

### 5.2 Active-learning triage

Route to human only the low-confidence extractions. Confidence features, all available before any human sees the figure:

- G10 cross-method median |Δθ| (strongest single feature)
- VLM self-consistency spread across the 3–5 samples on axis range, units, depth labels
- number of series × number of mutual crossings within 3 px
- palette type (colour / greyscale / bitonal)
- effective DPI and vector class V1/V2/R1/R2/R3
- count of amber/red gauntlet rows
- tick re-projection residual (G1)
- fraction of points where the trace touches another series' mask

Train a gradient-boosted classifier on the first 500 human decisions to predict "reviewer will accept". Set the operating point by **fixing the false-accept rate at ≤2%** and letting the review volume fall out of that — not the other way round. Re-fit weekly. Expect the reviewed fraction to fall from 100% to ~35–45% after ~1,500 labels, which roughly halves route (b)'s cost. Keep a permanent **random 5% audit stream** outside the triage so the false-accept rate stays measured rather than assumed.

---

## 6. The competing strategy: emailing corresponding authors

### 6.1 Published response rates (all recalled — verify)

| Study | Field | Result |
|---|---|---|
| Wicherts, Borsboom, Kats, Molenaar (2006), *American Psychologist* 61:726–728 | psychology | **27%** of 141 datasets shared after 6 months of requests |
| Savage & Vickers (2009), *PLoS ONE* 4(9):e7078 | PLoS journals with data policies | **1 of 10** |
| Krawczyk & Reuben (2012), *Accountability in Research* 19:175–186 | economics | ~**44%** provided |
| Vines et al. (2014), *Current Biology* 24:94–97 | ecology/evolution, 516 papers 1991–2011 | odds of data being available **fell ~17% per year**; dead email addresses were a major cause |
| Stodden, Seiler, Ma (2018), *PNAS* 115:2584–2589 | *Science*, post-policy | ~**44%** responded with some artifact; substantially fewer supplied enough to reproduce |
| Tedersoo et al. (2021), *Scientific Data* 8:192 | cross-disciplinary, large-scale | headline ~**7% shared**; I am **not confident** whether this is "of all requests" or "of responders" — verify |
| **Gabelica, Bojčić, Puljak (2022), *J. Clin. Epidemiol.* 150:33–41** | 1,792 BMC papers whose statement said data available on request | **6.8% (122/1,792) actually sent data.** Highest-confidence figure here |

**Agronomy/soil science specifically: I know of no published response-rate study.** That is a real gap — and running your own 100-email pilot with a pre-registered protocol would itself be a publishable methods note, as well as giving you the number you need.

**Planning number: 10–25% overall.** Stratify hard — expect 25–40% for papers <5 years old with an institutional email and a data-availability statement, and **near zero for pre-2010** (Vines et al.'s decay is the governing result, and it is driven as much by dead addresses as by unwillingness).

### 6.2 Yield per person-hour

**Email route:** 4 min to identify the paper, find a current address (ORCID, current affiliation page, Google Scholar), and mail-merge; 2 min amortized for follow-up and receipt handling → 6 min/paper → **10 papers/hour**. At 15% success: 1.5 datasets/hour. A responding dataset averages ~5 series at gold fidelity with full metadata — and typically includes **extra depths, extra years, and extra treatments that never appeared in the figure**, a bonus multiplier of ~2–3×. → **~15–20 series/hour, gold fidelity.**

**Digitization route (b):** 9.5 min/figure ÷ 3.2 series = 3.0 min/series → 20 series/hour, × 0.85 gauntlet retention → **~17 series/hour, silver fidelity.**

**Verdict: comparable per hour.** Email wins decisively on *fidelity* and on the bonus depths/years; digitization wins on *latency* (minutes vs 2–8 weeks), *determinism* (no dependence on strangers), and *scalability* (no ceiling — you can always digitize more, you cannot make more people reply).

### 6.3 Recommended blended strategy

1. **Score every candidate paper for email-worthiness:** recency, number of treatments, number of depths, presence of a data-availability statement, whether the site is in an under-sampled stratum (saline, Vertisol/high-clay, Global South), and whether the author has other papers you also want. Email the **top 300**.
2. **Templated request**, one page, containing: (i) exactly which figure and which series you want; (ii) an offer of co-authorship or formal acknowledgement, stated as their choice; (iii) a CC-BY / CC-BY-NC deposit plan naming the repository and the DOI they will get; (iv) **the digitized version of their own figure attached**, with the line *"we have digitized this and will use it either way — sending the real numbers takes you five minutes and makes it correct."* This last point is the strongest lever available and costs nothing: it converts the request from a favour into an error-correction opportunity.
3. **Two follow-ups**, at 14 and 35 days, then stop.
4. **Tracking:** one row per request in a SQLite/Airtable table — `paper_doi, author, email, sent_date, followups, status ∈ {sent, bounced, declined, received}, n_series_received, bonus_depths, bonus_years, benchmark_pair_created`.
5. **Every received dataset for a paper you already digitized becomes a Tier-A benchmark row.** Wire this in from day one; it grows your benchmark for free and is the answer to "is your benchmark representative of your actual corpus?"
6. Expected combined yield from the email arm: 300 × 15% × 5 series × 2.5 bonus ≈ **560 gold series**, plus ~45 new benchmark pairs, for ~30 person-hours.

---

## 7. Deliverable: totals, error table, and scope decisions

### 7.1 Predicted error by method × figure type

**These are pre-registered predictions, not measurements.** Their purpose is to be falsified by the §2 benchmark. Values are median |Δθ| in m³/m³ (series pass-rate at the §2.3 metric-5 threshold in parentheses).

| Figure type | Vector (V1) | Colour-mask auto | LineFormer | VLM coords | Manual WPD |
|---|---|---|---|---|---|
| 2–3 separated colour series, ≥300 dpi | 0.000 (99%) | 0.003 (95%) | 0.006 (88%) | 0.03 (35%) | 0.004 (96%) |
| 4–6 overlapping colour series | 0.001 (92%) | 0.010 (65%) | 0.012 (62%) | 0.05 (15%) | 0.006 (90%) |
| 4–6 overlapping greyscale/dashed | 0.002 (70%) | 0.030 (20%) | 0.025 (30%) | 0.06 (8%) | 0.008 (82%) |
| Markers only, no line | 0.001 (90%) | 0.006 (80%) | 0.020 (40%) | 0.04 (20%) | 0.005 (92%) |
| With error bars | 0.004 (75%) | 0.018 (45%) | 0.022 (38%) | 0.05 (12%) | 0.006 (88%) |
| Dual axis + inverted precip bars | 0.001 (88%) | 0.012 (55%) | 0.030 (30%) | 0.08 (5%) | 0.006 (88%) |
| Log / broken axis | 0.002 (60%) | 0.040 (15%) | 0.060 (8%) | 0.12 (2%) | 0.008 (78%) |
| Raster <150 dpi / bitonal scan | n/a | 0.035 (18%) | 0.040 (15%) | 0.09 (5%) | 0.015 (55%) |
| 2D contour (θ or ECe isopleths) | n/a | n/a | n/a | n/a | 0.030 (—) |

Read the pattern, not the digits: **vector is a different regime**, manual is robust but slow, LineFormer is a good proposal generator and a bad final answer, and VLM coordinates are never acceptable.

### 7.2 Total usable series

```
Candidate records (irrigated + field + soil water content)      25,000-60,000
 × screening precision ~25%                             →       8,000-15,000 relevant papers
 × fraction with a θ-vs-time figure ~30-40%             →       2,500- 6,000 papers
 × 1.4 usable figures/paper × 3.2 series/figure         →      11,000-27,000 raw series
 × metadata gauntlet (coords, texture, depth, absolute dates)
      strict  (sand/silt/clay reported)  ~35%           →       3,900- 9,500
      relaxed (texture class + SoilGrids/SSURGO fill) ~60% →     6,600-16,200
 × numeric gauntlet §4 pass ~85%                        →
```

**Strict: ~3,300–8,100 series. Relaxed: ~5,600–13,800. Point estimate ~7,000 series, ~22 points each, ~150,000 point-observations (plausible range 1×10⁵–3×10⁵).**

Plus ~560 gold series from the email arm (§6.3).

### 7.3 The honest comparison — and what this corpus is actually for

ISMN alone is >2,800 stations at sub-daily resolution over many years: order **10⁹ point-observations**. The figure-digitization corpus is order **10⁵**. **You will not get terabytes from figures — you will get roughly 0.01–0.1% of ISMN's point volume.**

That is not a reason to abandon it. It is a reason to state the value proposition correctly, because the correct statement is stronger than the volume one:

> The digitized corpus contributes **~7,000 series from irrigated, saline, and high-clay agricultural fields — strata in which the global monitoring networks are nearly empty.** ISMN, USCRN, SCAN and FLUXNET are overwhelmingly rainfed, temperate, and coarse-to-medium textured. Irrigated Vertisols under saline water in Iran, Egypt, India, Pakistan and the North China Plain are the exact conditions under which capacitance sensors fail, which is the problem this project exists to solve — and they are almost entirely absent from the networks.

Total person-months, route (b) with active-learning triage at the realistic 4,000–8,000 figure corpus: **4–8 PM of digitization, plus ~1 PM for the email arm, plus ~2 PM for the §1 survey and §2 benchmark**. Call it **7–11 person-months** for the complete, validated, defensible dataset. Front-load the survey and benchmark: they are ~2 PM and they determine whether the remaining 5–9 PM is spent well.

### 7.4 Recommended out of scope

Be willing to say these out loud; the scope discipline is itself a credibility signal.

1. **2D contour plots** (θ or ECe isopleths over depth × time) — **out of scope as point series.** Extracting a series at a fixed depth means inverting an interpolated field whose gridding algorithm (kriging? Surfer's default? linear triangulation?) the authors did not report. The recovered "series" would be an artifact of their contouring, and the error is unquantifiable in principle, not just in practice. **Salvage:** extract only the contour levels bracketing the target depth and admit the observation as **interval-censored**, θ ∈ [level_i, level_{i+1}]. A likelihood-based ML model handles censored observations natively, and this recovers real information from a figure class that is otherwise a total loss. Same treatment for box plots (admit as quantile constraints, not as time series).
2. **Pre-1995 scans** — out of scope unless bitonal ≥400 dpi *and* ≤3 series. Below that, dash-pattern discrimination fails and the human-manual cost per usable series exceeds the email route's.
3. **>6 overlapping series in one panel** — out of scope. Series assignment is unreliable, and G6/G7 cannot disambiguate 7! permutations.
4. **Figures with no reconstructable calendar date axis** — x = "irrigation event number" or "sampling occasion" with no anchoring date in the text. (x = DAP/DAS *is* in scope when the planting date appears anywhere in the paper; that is a VLM text-extraction task with quote grounding, and it succeeds often.)
5. **Any series where the quantity cannot be resolved to m³/m³ with a stated ρb** — admit as gravimetric with an explicit flag, or exclude. Never silently convert.

---

## Verification list, in priority order

I could not confirm anything by search. Before any of this is quoted in a manuscript, verify:

1. **Gabelica, Bojčić & Puljak (2022) 6.8%** — load-bearing for §6, and the one I am most confident about; confirm the exact n and denominator.
2. **Tedersoo et al. (2021) *Sci Data* 8:192** — confirm whether ~7% is of all requests or of responders. My uncertainty here is genuine.
3. **CharXiv (NeurIPS 2024) headline numbers** — the ~47–50% vs ~80% human figure is the strongest single argument against unsupervised VLM extraction; get it exact.
4. **LineFormer (ICDAR 2023) real-chart accuracy** — I recall the synthetic F1 but not the real-chart number, and the real-chart number is the one that matters.
5. **Drevon, Fursa & Malcolm (2017) *Behavior Modification* 41(2):323–339** — the only WPD-specific validation study I recall; confirm the ICC and the error magnitude.
6. **PlotExtract** — named in the brief; I cannot confirm it exists. Read it before citing it.
7. **Bushland Ag Data Commons dataset↔figure pairs** — I recall the `10.15482/USDA.ADC/` DOI prefix and the Evett/Howell/Colaizzi lysimeter datasets, but **not** that the descriptors are in *Scientific Data* specifically. Verify the pairing before building benchmark cells on it.
8. **Carsel & Parrish θr/θs table** — recalled from HYDRUS defaults; cross-check against Rosetta3 (Zhang & Schaap 2017) before wiring the G3 thresholds.
9. Springer/Wiley/Elsevier figure-format submission requirements (Elsevier's 1000 dpi line art / 500 dpi combination / 300 dpi halftone guidance is recalled and underpins the §1.3 priors).

The §1 vector survey and the §2 benchmark are the two things that turn all of the above from priors into results. Both are executable now: the survey is about **two person-weeks** for 280 PDFs, and it is the single highest-value two weeks in this project, because the V1 fraction moves the error floor by an order of magnitude and determines whether route (b) or route (c) is viable.