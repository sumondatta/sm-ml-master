<!--
Compiled from a research sweep, not written by hand. Preserved verbatim because
it is reference material the implementation draws on rather than prose meant to
be read start to finish.

CONFIDENCE: the sweep's web-search budget was exhausted before these sections
ran, so everything in them is recalled from model knowledge and NONE of it was
corroborated by a search. Every URL and every accuracy figure must be verified
before it is relied on. Nothing here is legal advice.
-->

## CRITICAL CAVEAT — READ FIRST

**This session's WebSearch budget was already exhausted (200/200 calls consumed) before this subtask started.** Both search attempts returned budget-exceeded errors. Everything below is therefore from trained knowledge and reasoning, i.e. **confidence = `recalled` throughout unless explicitly marked otherwise**. I have not fabricated endpoints; where I am unsure a thing exists I say so. §8 is a prioritised verification queue — treat it as mandatory before any of these numbers go into a manuscript.

---

# Irrigation Labelling & Forcing-Reconstruction Layer — Specification

## 0. The core reframing

Extent maps answer *"was this ~30 m pixel irrigated somewhere in this year?"* The project needs three different things:

| Question | Unit | What answers it |
|---|---|---|
| Q1. Was the **soil volume around this sensor** irrigated in this season? | station-year | fused label model (§3) |
| Q2. By **what method** (so I know the wetting geometry)? | station-year | declared parcel attributes > paper text > SM vertical signature (§4) |
| Q3. **When and how much** water arrived? | station-day | event detection + inversion (§4) or rule simulation (§5) |

Q1 is a *classification with calibrated probability*. Q2 is what determines whether Q3 is even answerable. Q3 for most literature-derived rows will be `unknown` — and the honest design decision is to **carry that as an explicit provenance channel rather than to zero it** (§6).

**Non-negotiable design rule:** never collapse evidence into a boolean at ingest. Store every piece of evidence (each raster sample, each text assertion, each climate ratio) in a `irrigation_evidence` table keyed by station-year, and derive the label by a versioned model. When LANID v3 ships or you find the paper's supplementary irrigation log, you re-fuse — you don't re-ingest.

---

## 1. Point-scale validity of irrigation maps

### 1.1 Product-by-product

All accuracy figures below: **`recalled`**. The column that matters most is the last one.

| Product | Res / extent / years | Recalled accuracy | Validation design | Where errors concentrate | Ever validated at POINT scale vs known sites? |
|---|---|---|---|---|---|
| **LANID** (Xie & Lark, UW-Madison SAGE; ISPRS 2019 + RSE 2021) | 30 m, CONUS, annual ~1997–2017 (extended later) | OA ~90–95%; irrigated-class F1 ~0.90 in the West, materially lower (~0.70–0.80) in the humid East; county agreement with NASS R²~0.88–0.98 | Visually interpreted reference points (NAIP/Landsat time series), stratified by region; plus county-census aggregation | Humid East (supplemental irrigation), small fields, irrigated pasture/hay, orchards/vineyards under drip | **No.** Photo-interpretation + census. Photo-interpretation cannot see supplemental irrigation or drip. |
| **IrrMapper v1.2** (Ketchum et al. 2020, *Remote Sensing*) | 30 m, 11 western US states, annual 1986–~2023 | OA ~97–98% (dominated by the easy non-irrigated class); irrigated F1 ~0.90–0.95 | Hand-digitised polygons (irrigated / dryland / uncultivated / wetland) from NAIP + Landsat; explicitly includes *dryland-agriculture* and *wetland* negative classes — a real strength, because wetlands and dryland wheat are the classic commission sources | Montana/Idaho flood-irrigated pasture; wet meadows; fallow-in-rotation years | **Partially** — the reference polygons are field-level and hand-verified, which is closer to point scale than LANID's. Still not against instrumented sites. |
| **AIM-HPA** (Deines, Kendall, Butler, Hyndman; RSE 2019) + **AIM-RRB** (GRL 2017) | 30 m, High Plains Aquifer, annual 1984–2017 | OA ~92–98%; irrigated UA ~90%+; county r² ~0.88–0.96 | Reference points from NAIP + county census | Field edges, pivot corners, partial-year/partial-field irrigation, deficit irrigation in SW Kansas | **No.** But AIM-RRB was compared against **water-rights/metered** records in the Republican River Basin — closest thing in the list to a true point validation. |
| **MIrAD-US v4** (USGS EROS; Pervez & Brown) | 250 m, CONUS, 5-yearly (2002/07/12/17) | Agreement 75–90% | **Circular**: it downscales NASS *county* irrigated acreage onto a MODIS peak-NDVI ranking. It cannot be validated against the census that produced it. | Any county where irrigation is spatially fragmented; 250 m pixel is larger than most fields outside the West | **No, and structurally cannot be.** Use only as a county-total sanity check, never as a point label. |
| **LGRIP30** (GFSAD/NASA-USGS; Teluguntla, Thenkabail et al.) | 30 m, global, nominal 2015 (single epoch). Classes: 0 non-crop / 1 rainfed / 2 irrigated / 3 cropland | OA ~90%; irrigated PA/UA ~80–90% at continental aggregation, much worse regionally | GFSAD global reference point database (very-high-res imagery, street view, some field visits) | Humid Asia (irrigated vs rainfed rice), smallholder mosaics, Africa | **Reference points are points**, so nominally yes — but they are *photo-interpreted* points, not sites with irrigation records. |
| **GMIA v5** (Siebert et al. 2013, FAO/Frankfurt) | 5 arc-min (~10 km), global, ~2005 | n/a | Pure statistics downscaling of national/subnational **Area Equipped for Irrigation (AEI)** | Everywhere; AEI ≠ area actually irrigated (AAI); a 10 km cell at 30% AEI tells you nothing about a point | **No, and structurally cannot be.** Prior only. |
| **Mehta et al. 2022 AEI** (ESSD, 1900–2015) | 5 arc-min, global, annual-ish | n/a | Same class of product: historical reconstruction of AEI from census | Same | **No.** Use as a *temporal* prior ("was irrigation even present in this region in 1998?"). |
| **MIRCA-OS** (open-source MIRCA2000 successor, ~2024–25 *Scientific Data*) | 5 arc-min, monthly irrigated + rainfed area by ~20+ crop classes | n/a | Census + cropping-calendar allocation | Same as GMIA | **No.** Its real value is **crop-specific** and **monthly**: it tells you *which crop* is irrigated in a cell and *in which months* — that is a much better prior than a bare AEI fraction. Use it for the crop-conditioned labelling function (§3, LF7). |
| **ECIRA** | European irrigated area | **I cannot confirm this product's identity, publisher or accuracy from memory.** Do not cite until verified. For Europe I would instead lean on (a) national LPIS/GSAA declarations (§2), (b) the JRC AI4Boundaries/EuroCrops ecosystem, (c) Salmon et al. 2015 global 500 m irrigated/rainfed/paddy. | | | |
| **IrriMap_CN** (Zhang et al., RSE ~2022) | 500 m, China, annual 2000–2019 | OA ~90% recalled | Machine learning on MODIS + county statistics + ground samples | N. China Plain mosaics; 500 m >> field size in southern China | **No.** |
| **CIrrMap250** (ESSD ~2024) | 250 m, China, annual 2000–2020 | F1 ~0.80–0.90 recalled | Multi-source fusion constrained by irrigation statistics and water-use data | Same | **No.** |
| **India irrigated-area maps** (Ambika, Wardlow & Mishra 2016 *Sci Data*, 250 m, 2000–2015; IWMI/Gumma 250 m) | 250 m | ~80–90% vs district statistics | District-statistics agreement | Field size (median <1 ha), conjunctive canal+groundwater, multiple seasons per year (kharif/rabi/zaid must be handled separately) | **No.** 250 m over sub-hectare fields is a mixed pixel by construction. |
| **ESA WorldCereal** irrigation layer (Van Tricht et al. 2023 ESSD) | 10 m, global, season-specific, 2021 | **Weakest layer in the product.** My recollection is the authors explicitly caution that the "active irrigation" layer is a first attempt with limited quality; irrigated-class F1 plausibly ~0.4–0.6 in many AEZs | CEMS/WorldCereal reference database | Everywhere outside heavily-sampled AEZs | **No.** Single year (2021) also makes it useless for most literature station-years. |

### 1.2 The five failure modes that extent maps cannot fix

1. **Annual vs static.** LANID / IrrMapper / AIM / IrriMap_CN / CIrrMap250 are *annual* — they can tell you the field was fallow or dryland that specific season. LGRIP30 / GMIA / Mehta / WorldCereal are *single-epoch* and will happily label a field "irrigated" for a station-year in which it was not. **Hard rule: static maps may only contribute to the prior, never to the year-specific likelihood.**
2. **Pixel ≠ wetted volume.** Furrow: alternate-furrow irrigation wets ~50% of the surface. Drip: 20–50% wetted fraction. SDI: the surface may never wet. Pivot corners: on a quarter-section with a pivot, ~21% of the square is never wetted, and instrument enclosures and access tracks are *preferentially sited in exactly those corners*.
3. **Supplemental irrigation.** In the humid East, "irrigated" may mean two rescue applications in a dry August. The map says irrigated; the water balance is ~95% rainfed. This needs its own class, not the binary.
4. **Deficit irrigation experiments.** Literature soil-moisture data disproportionately comes from *irrigation-treatment trials* — one plot at 100% ETc, one at 50%, one rainfed, all within one pixel or within one map polygon. Extent maps are structurally blind to this, and it is a large fraction of the corpus you are mining. **Treatment ID from the paper always beats every raster.**
5. **Rice.** "Irrigated" for paddy means ponding, a different hydrological regime; a dielectric sensor is above porosity and effectively out of range.

### 1.3 Geolocation error — quantified

Coordinate precision → nominal positional uncertainty radius *r*:

| Reported precision | Δlat | Δlon at 40° | Effective *r* (half-cell) |
|---|---|---|---|
| 5 dp (0.00001°) | 1.1 m | 0.85 m | ~1 m |
| 4 dp | 11 m | 8.5 m | ~7 m |
| 3 dp | 111 m | 85 m | ~70 m |
| 2 dp | 1.11 km | 0.85 km | ~700 m |
| "near town X" | — | — | 2–10 km |

Add, independently: GPS/handheld error (3–10 m), datum mismatch (WGS84 vs NAD27 ≈ up to ~200 m in CONUS — a real and frequently-overlooked error in older papers), coordinate given for the *farm/station/institute* rather than the plot (common; can be 0.5–5 km), and digitising-from-a-figure error.

**Probability the coordinate lands in the correct field.** Model the field as a square of side *L* and the true sensor position as uniform within it; displace by an isotropic vector of magnitude *r*. The probability the displaced point is still in the same field is the expected normalised overlap of the square with its translate:

```
P(same field) ≈ E[(1 − |r cosθ|/L)⁺ (1 − |r sinθ|/L)⁺]
             ≈ 1 − (4/π)(r/L) + O((r/L)²)      for r < L
             ≈ 1 − 1.27 (r/L)
```

| | L = 800 m (US quarter-section pivot) | L = 400 m (16 ha) | L = 200 m (4 ha, EU/China) | L = 70 m (0.5 ha, S. Asia / SSA) |
|---|---|---|---|---|
| r = 7 m (4 dp) | 0.99 | 0.98 | 0.96 | 0.87 |
| r = 70 m (3 dp) | **0.89** | **0.78** | **0.56** | **~0.05** |
| r = 200 m (datum error) | 0.68 | 0.36 | ~0.05 | 0 |
| r = 700 m (2 dp) | ~0.05 | 0 | 0 | 0 |

Caveat that makes this *pessimistic-optimistic in both directions*: the uniform-position assumption is wrong — sensors cluster near field margins, access roads and instrument huts, which **lowers** P; but neighbouring fields are often under the same management, which **raises** P(same *irrigation status*) well above P(same field). The quantity you actually care about is the latter. Empirically, in a landscape with irrigated fraction φ and strong spatial clustering of irrigation, P(same status | wrong field) ≈ 0.6–0.85 in an irrigation district and ≈ φ in a mixed landscape.

### 1.4 Buffer + majority-vote recommendation

Do **not** sample a single pixel. Procedure per station-year, per raster product:

1. Set `R = max(r_geoloc, 0.5 × L_median_local, 1.5 × pixel_size)` where `L_median_local` comes from a field-size product (§2) or from a regional field-size prior (Lesiv et al. 2019 crowdsourced global field size is the standard prior — `recalled`).
2. Sample the raster in a disc of radius R **and** in discs of radius R/2 and 2R. Store, for each: `frac_irrigated`, `n_pixels`, `n_distinct_classes`, and `majority_class`.
3. Compute a **spatial-stability** score `s = 1 − |frac(R/2) − frac(2R)|`. Low `s` means the point sits on an irrigation boundary — the single most useful red flag in the whole pipeline, and it is free.
4. Emit evidence, not a decision: `(product, year, R, frac_irrigated, s, n_pixels)`.

Thresholds for the *labelling function* layer (not the final label): `frac ≥ 0.80 and s ≥ 0.85` → strong positive; `frac ≤ 0.05 and s ≥ 0.85` → strong negative; otherwise abstain. **Abstention is the whole point of a labelling function** — the fusion model (§3) handles the middle.

5. **Pivot-corner test.** In pivot-dominated regions, if the field polygon's minimum-area bounding rectangle has aspect ≈ 1 and the irrigated pixels form an inscribed disc, compute the point's radial position ρ/R_pivot. If ρ > 0.98 or the point is outside the disc → `pivot_corner_risk = true`, and downweight to near-zero regardless of `frac`. This single check is worth more than adding another extent map.

---

## 2. Field-boundary-aware joins

Joining on the **polygon** rather than the pixel is the single largest accuracy gain available, because it converts "what does the pixel say" into "what does the *field* say, by majority, with a known field size".

### 2.1 Boundary geometry products

| Product | Access | Notes |
|---|---|---|
| **USDA Common Land Unit (CLU)** | **Public distribution ended in 2008** — §1619 of the Food, Conservation and Energy Act of 2008 exempted producer data from FOIA. A **2008 national snapshot** entered the public domain before the restriction and still circulates (shapefiles by county; mirrored on various academic/commercial sites). Current CLU is USDA-internal only. | Use the 2008 snapshot for CONUS geometry. Boundaries are ~stable at 10-yr scale but pivot installs and field consolidation since 2008 are real. `recalled` — verify current mirror availability. |
| **Fields of the World (FTW)** | Kerner et al. 2024; open benchmark, ~24 countries, Sentinel-2-based instance segmentation, permissive licence, `ftw-tools` CLI + pretrained models on GitHub. | This is the right tool for **inferring** boundaries where no registry exists. Use the pretrained model to delineate the field containing each station. |
| **AI4Boundaries** | JRC, d'Andrimont et al. 2023 *ESSD*; 7 EU countries; Sentinel-2 (10 m) and aerial (1 m) image/mask chips derived from LPIS/GSAA. Open. | Training data, not a wall-to-wall product. |
| **AI4SmallFarms** | Persello et al.; Vietnam + Cambodia smallholder boundaries, Sentinel-2. Open. | Essential if you want any SE Asian smallholder coverage. |
| **FracTAL ResUNet / ResUNet-a** | Waldner & Diakogiannis 2020 *RSE*; Waldner et al. 2021 "Detect, consolidate, delineate" multi-task. Code on GitHub (CSIRO). | The method behind most modern delineation. FTW's baselines supersede it for turnkey use. |
| **EuroCrops** | Schneider et al.; harmonised **crop-code taxonomy** across ~16 EU member states' GSAA declarations, Zenodo + GitHub, open. | Gives you *declared crop* per parcel — a first-class labelling function (rice ⇒ flooded; maize in Spain ⇒ irrigated). |

### 2.2 Registries carrying a **DECLARED irrigation attribute** — the highest-value targets

A declaration beats any remote-sensing inference. Ranked by value and confidence:

| Source | Irrigation attribute | Confidence |
|---|---|---|
| **Washington State Dept. of Agriculture Crop Layer** (annual, statewide, open shapefile/GDB) | `Irrigation` field with explicit values: Center Pivot, Drip, Rill, Sprinkler, Wheel Line, Big Gun, None, Unknown — **plus crop**. This is method-level ground truth at parcel scale, annual, free. | **High** |
| **Colorado DWR / Division of Water Resources irrigated lands** (by water division, annual-ish) | Irrigation type (FLOOD / SPRINKLER / DRIP), crop, acreage, water source | **High** |
| **Idaho IDWR irrigated lands / water-rights place-of-use** | Irrigated polygons, water source, sometimes method | Moderate-high |
| **Utah Div. of Water Resources "Water Related Land Use"** | Irrigation method attribute | Moderate-high |
| **Oregon WRD water-rights place-of-use** | Irrigated place-of-use polygons | Moderate |
| **California DWR Statewide Crop Mapping** (annual, 2014–) + older DWR Land Use Surveys | Crop; older county surveys carried irrigation method; the modern layer's irrigation attribution is weaker | Moderate |
| **ABARES Catchment Scale Land Use of Australia (CLUM)** | ALUM classification **explicitly separates class 4.x irrigated agriculture from 3.x dryland**, ~50 m, national, open | **High** — the only national product I know of where irrigated/dryland is a *definitional* land-use split rather than an inference |
| **Spain SIGPAC** | Parcel registry with land-use code; several autonomous communities distribute an irrigation coefficient / `regadío` attribute. Also **ESYRCE** (national crop survey, irrigation recorded) and the MAPA **SIAR/Inventario de Regadíos** | Moderate — verify which CCAA expose the attribute |
| **France RPG (Registre Parcellaire Graphique)** | Annual, open via IGN/data.gouv.fr, parcel geometry + crop group. Whether an *irrigation* declaration is in the public release varies by year and I am not confident — the fuller declaration set (with irrigation for certain aid measures) may be researcher-access only via ASP. | **Low — verify** |
| **Italy AGEA / SIAN** | National parcel data restricted; several regions (e.g. Emilia-Romagna, Puglia) publish GSAA openly; irrigation consortia (Consorzi di bonifica) hold delivery records | Low-moderate |
| **Netherlands BRP Gewaspercelen / Denmark Markblokke & Marker** | Fully open annual parcel + crop; irrigation not declared (but NL/DK sprinkler permits exist separately) | High for geometry, none for irrigation |
| **India land records (Bhulekh, state-wise)** | Revenue records classify land irrigated/unirrigated for assessment; digitised unevenly, rarely machine-readable, rarely geo-referenced to a polygon. **ICRISAT District Level Database** gives net irrigated area by source at *district* level — use as a regional prior only. | Low for point use |
| **China** | No open parcel registry. Fall back to CIrrMap250/IrriMap_CN plus the fact that most irrigation districts (灌区) have published command-area boundaries in local yearbooks | Low |
| **US water-rights / metering** | Kansas **WIMAS** (metered groundwater withdrawals by well, annual, open), Nebraska NRD metering (varies by district), Republican River Basin metered records | **High value where it exists** — WIMAS gives *actual annual volume pumped per well*; join wells to fields and you have amounts, not just extent |

**Implementation of the join:** for each station, (1) if a registry polygon exists and contains the buffered point, use it; (2) else run FTW delineation on a Sentinel-2 composite for that year and take the containing polygon; (3) else fall back to the buffer disc of §1.4. Record `boundary_source` and `boundary_confidence`. Then aggregate all rasters **within the polygon** and record `field_area_ha` — which retroactively tightens the geolocation probability in §1.3.

---

## 3. Multi-evidence label fusion

### 3.1 Labelling functions (each returns `{IRRIGATED, RAINFED, ABSTAIN}` plus a strength)

| # | LF | Source | Notes |
|---|---|---|---|
| LF1 | Annual extent map, polygon-aggregated, per product | LANID / IrrMapper / AIM-HPA / IrriMap_CN / CIrrMap250 / India maps | One LF per product, but **they are strongly correlated** (shared Landsat/NDVI logic, shared census constraints) — must be a correlated group in the fusion model |
| LF2 | Static extent map | LGRIP30 / GMIA / Mehta AEI / WorldCereal | Prior-only; low strength; abstain if station-year is >5 yr from map epoch |
| LF3 | Declared parcel attribute | §2.2 registries | **Highest strength.** Dominates everything else when present. Also sets `irrigation_method`. |
| LF4 | Source-paper text assertion | LLM extraction from the paper, with three sub-levels: (a) explicit schedule/log table, (b) "the field was irrigated by X", (c) mentions irrigation ambiguously | Must record the verbatim sentence + page. (a) also populates §5. **Second-highest strength.** |
| LF5 | Treatment/plot ID | Paper's experimental design | If the paper has rainfed and irrigated treatments, the *treatment* is the label; extent maps are irrelevant and must be suppressed |
| LF6 | Water-rights / metered withdrawal | KS WIMAS, place-of-use polygons | High strength; also gives amounts |
| LF7 | Crop × region implication | EuroCrops / CDL / WorldCereal crop / MIRCA-OS | Rice anywhere ⇒ flooded (unless explicitly upland/aerobic rice — check). Alfalfa/cotton in AZ/CA/NM ⇒ irrigated with p≈0.98. Maize in Nebraska ⇒ ~60% irrigated (weak). |
| LF8 | Climatic necessity | Growing-season P/ET0 from AgERA5 or gridMET, plus evidence the crop completed its cycle (NDVI/EVI seasonal integral above a threshold from Landsat/HLS) | Formalise: if seasonal `P < 0.4 × ETc_potential` **and** peak NDVI > 0.65 **and** the crop is not deep-rooted/perennial ⇒ IRRIGATED, strength high. This is the strongest *inferential* LF and the one that works globally. |
| LF9 | Soil-moisture-series signature | §4 | Wetting events with no precipitation; absence of dry-down below a threshold; inverted vertical wetting order; supra-porosity plateaus | 
| LF10 | Negative controls | USCRN / SCAN / TERENO / REMEDHUS metadata; explicit "rainfed" in text; ALUM dryland class | You need strong RAINFED LFs or the model calibrates only on one side |

### 3.2 Which fusion model — recommendation for a single researcher

**Recommendation: a supervised, calibrated discriminative model over LF outputs, with a Snorkel-style generative label model only as a fallback where gold labels are absent.** Concretely:

- **Primary:** L2-regularised **logistic regression** (or gradient-boosted trees if you have >1000 gold rows) on a feature vector built from the LF outputs *plus* the continuous evidence (`frac_irrigated` per product, spatial stability `s`, `field_area_ha`, `r_geoloc`, `P/ET0`, peak NDVI, `pivot_corner_risk`, text-assertion level). Fit on the gold set (§3.3). Calibrate with **isotonic regression** (or Platt if <300 gold rows) on a held-out fold. Report `p_irrigated` ∈ [0,1].
- **Fallback for zero-gold regions:** **FlyingSquid** (Fu et al. 2020 — closed-form triplet method, no EM, trivially fast) or **Dawid–Skene** EM, over the discrete LF votes, with LF1's products declared as one correlated group. Snorkel's `LabelModel` also works but its conditional-independence assumption is badly violated here and you must pass the dependency structure explicitly.

**Why not a pure weak-supervision pipeline?** Snorkel exists to avoid needing labels. You *can* get 300–600 gold labels here (§3.3), which is exactly the regime where direct supervision + calibration dominates an unsupervised generative label model. The LFs are the right abstraction; the generative label model is not.

**Why not a Bayesian network?** A hand-specified BN (pgmpy) is attractive for interpretability and for encoding causal structure (aridity → irrigation → SM signature), but you will spend weeks eliciting CPTs, and with 600 gold rows you cannot identify them. Use the BN only if you want to *generate* synthetic evidence for sensitivity analysis.

**Output schema, not a boolean:**
```
irrigation_class        ENUM(irrigated, rainfed, supplemental, flooded_paddy, unknown)
p_irrigated             FLOAT       -- calibrated
p_irrigated_ci_lo/hi    FLOAT       -- bootstrap 90%
label_model_version     TEXT
dominant_evidence       TEXT[]      -- top-3 contributing LFs (for audit)
```
Three-class-plus: `supplemental` is a real class (irrigation supplies <20% of growing-season water), not a confidence level. Detect it via LF8 (P/ET0 near 1) combined with LF9 (few events).

### 3.3 Gold-standard validation set

**Positive (documented irrigation dates + amounts + multi-depth SM):**

| Site | What it gives | Notes |
|---|---|---|
| **Bushland, TX** — USDA-ARS CPRL | 4 large weighing lysimeters, logged irrigation, **neutron-probe multi-depth to 2.4 m**, maize/cotton/sorghum/winter wheat, LEPA + SDI + dryland treatments | The single best site on Earth for this. The Evett/Marek/Copeland/Howell *WRR* data papers + USDA **Ag Data Commons** releases. Includes **dryland controls** — paired positives and negatives. |
| **AmeriFlux US-Ne1 / US-Ne2 / US-Ne3** (Mead, NE; Suyker) | Ne1 = irrigated continuous maize, Ne2 = irrigated maize–soy, **Ne3 = rainfed maize–soy**; SM at ~10/25/50/100 cm; pivot irrigation logged | **The controlled experiment of the whole project.** Same soil, same climate, irrigated vs rainfed, 20 yr. Use it for the §6 ablation. |
| **Maricopa, AZ** — USDA-ALARC / UA MAC | SDI and level-basin, detailed logs, FACE/deficit trials; also the home of `pyfao56` | Gives you an SDI positive, which is otherwise nearly impossible to find |
| **Barrax / Las Tiesas, Spain** (SPARC, SEN2Flex, REFLEX) | Pivot + drip, irrigation records | |
| **HiWATER / Heihe, Zhangye, China** (Daman superstation + ~17 EC sites) | Flood-irrigated maize oasis, documented irrigation dates, dense SM network; data via TPDC | Only strong non-Western positive I'm confident about |
| **Ningxia / Yellow River diversion** | Border/flood irrigation | Lower confidence on data access |
| **Urgell & Algerri-Balaguer (Catalonia), Ebro; Budrio & Faenza, Po valley** | ESA **Irrigation+** demonstration sites — declared irrigation amounts from consortia, used by Dari et al. | These are the sites the irrigation-retrieval literature validates on; reusing them means your numbers are comparable |
| **Kairouan / Merguellil, Tunisia** (IRD/CESBIO) | Irrigated wheat, drip + flood, used in S1 detection work | |
| **Yanco / Murrumbidgee, Australia** (OzNet + SMAP core site) | Irrigated rice and cotton alongside dryland | |

**Negative (documented rainfed):** US-Ne3, USCRN (all, essentially), the rainfed subset of SCAN, TERENO (Germany), REMEDHUS rainfed plots (Spain), Twente/Raam (NL), COSMOS-UK, Australian ALUM dryland class.

**Required size.** To fit a ~12–20 feature logistic model and then calibrate it: minimum **~400 gold station-years**, target **800**, with a hard floor of **30 per stratum** where strata = {region} × {method}. For a 10-bin reliability diagram you want ≥100 per bin, i.e. ~1000 — you will not have that, so use **5 bins** or an adaptive-width (equal-count) binning and report bootstrap CIs on ECE. Split by *site*, never by station-year, or you leak.

**Calibration metrics (report all):**
- **Expected Calibration Error (ECE)**, equal-count bins, with bootstrap 90% CI. Target ECE < 0.05.
- **Brier score + Murphy decomposition** into reliability / resolution / uncertainty. Reliability is the calibration term; resolution tells you whether the model is doing anything at all beyond base rate.
- **Reliability diagram** with histogram of predictions underneath.
- **Coverage at precision ≥ 0.95** — "what fraction of station-years can I label confidently?" This is the number that determines whether the project is feasible, and it is the one to put in the abstract.
- Stratified versions of all of the above by region and by irrigation method.

⚠️ **ISMN caveat:** the International Soil Moisture Network's station metadata does **not** carry a reliable irrigation flag. Do not treat ISMN "land cover = cropland" as anything. Several ISMN networks sit in irrigation districts with no indication.

---

## 4. Event detection and amount inversion from the SM series

### 4.1 Methods, with recalled skill

| Method | Core idea | Recalled skill | Fails on |
|---|---|---|---|
| **dθ/dt threshold + no-rain filter** (baseline) | Event if Δθ over 24 h at 5–10 cm exceeds max(0.02 m³/m³, 3σ of dry-down residual) **and** precipitation in the preceding 24–48 h < 1–2 mm | POD 0.75–0.9 for sprinkler/pivot ≥15 mm; **FAR is dominated entirely by precipitation-product error**: ~0.10–0.25 with gauge-corrected radar (Stage IV / AORC / PRISM-hourly), ~0.35–0.60 with IMERG/CHIRPS alone | Convective rain misses in satellite precip = false irrigation; sub-daily sampling required |
| **SM2RAIN family** (Brocca et al. 2013/2014 JGR; Brocca et al. 2018 *Remote Sensing* for irrigation; **Dari et al.** 2020–2023, *RSE*/*HESS*; **ESA Irrigation+**) | Invert the surface-layer water balance: `p(t) = Z·n·dS/dt + g(S) + e(S)`; the residual above rainfall is irrigation | Over Ebro/Po at 1–6 km: monthly irrigation-amount RMSE of order **10–30 mm/month**; correlation with declared volumes ~0.5–0.8; **systematic underestimation of 20–50%** at high application rates | Saturation (the layer can't store the water so dS/dt understates p); deep percolation and runoff are lumped into `g`+`e`; short-interval satellite revisit aliases events |
| **Sentinel-1 backscatter event detection** (Bazzi / Le Page / Baghdadi / Zribi, CESBIO-INRAE; Ouaadi et al. Morocco) | σ⁰ jump at plot scale (VV/VH + NDVI to control vegetation) | Plot-scale *seasonal* irrigated/non-irrigated classification 70–90%; **individual-event detection is revisit-limited** — Le Page et al. 2020 concluded events ≳20–25 mm are detectable at 6-day revisit, with POD falling off sharply below that | 6–12 day revisit **cannot** resolve 3-day drip cycles — this is a hard information limit, not a method weakness. Dense vegetation saturates σ⁰. Post-S1B-failure (Dec 2021) revisit halved over much of the globe until S1C. |
| **SMAP/Sentinel-1 disaggregation** (SPL2SMAP_S, 3 km & 1 km) | Active-passive downscaling | 3 km ubRMSE ~0.05 m³/m³ | **Product ceased after the Sentinel-1B anomaly (Dec 2021).** 1–3 km is still >> field size. |
| **Model-minus-observation** (Zaussinger et al. 2019 *HESS* CONUS; Lawston/Santanello/Kumar 2017 *GRL*; Kumar et al. 2015) | An LSM with no irrigation process, driven by rainfall only, minus a satellite SM retrieval; the positive residual is irrigation | State-scale IWU estimates with large biases vs USGS/NASS — recalled as underestimating by ~40–70% in some states, overestimating in others; r ~0.5–0.7 at state level. Lawston et al. showed SMAP *can* see an irrigation signal over Columbia/Snake/Central Valley — but as a **regional** signature | Requires contiguous, intense irrigation; hopeless for a single field; the residual also absorbs all LSM and retrieval bias |
| **Bayesian change detection** (the 2024 *Agricultural Water Management* Mead, Nebraska study named in the brief) | Changepoint detection on the SM series (likely Adams & MacKay online BOCPD or a BEAST-style Bayesian decomposition) | **I cannot recall this paper's reported POD/FAR.** For methods of this class at pivot-irrigated sites I would *expect* POD 0.7–0.9, FAR 0.2–0.4, but this is inference, not recall. **Must verify.** | Same precipitation-confusion problem; changepoint priors need tuning per site |

### 4.2 Recommended detection stack

Do not pick one. Run a **cascade** and record which tier fired:

1. **Tier A — in-situ, sub-daily, with good precipitation:** dθ/dt threshold on the shallowest sensor, with a **Bayesian changepoint** model (BOCPD) as the second opinion, and an exhaustive no-rain filter using the *best available* precipitation (station gauge > AORC/Stage IV > PRISM > MSWEP > IMERG-Final > CHIRPS, in that order; record which was used, because it sets your FAR).
2. **Tier B — vertical-signature classifier (the key novelty):** compute the **cross-correlation lag between depths** for each wetting event. Rain and sprinkler wet top-first (lag 5 cm → 20 cm positive, order minutes–hours). **SDI wets the emitter depth first** — lag is *negative* or the surface never responds. Flood produces near-simultaneous saturation to depth. This single feature discriminates the three method families and should be a first-class column, and it also feeds LF9.
3. **Tier C — absence-of-dry-down detector:** for drip/micro, event detection is hopeless; instead fit an exponential dry-down to every inter-event segment and flag seasons where the profile never drops below a depletion fraction that the local ET0 would demand. "The soil never got dry when it should have" is stronger evidence than any individual event.
4. **Tier D — remote sensing (S1 σ⁰, SMAP-based) only for seasonal classification**, never for daily events.
5. **Tier E — amount inversion:** only attempt where Tier A fired *and* you have ≥3 depths spanning the root zone. Invert `I = ΔS_profile + ET_est + DP_est − P`, with DP from a simple free-drainage or unit-gradient assumption. Report the estimate as a **lower bound** with an explicit note, because DP is the term you cannot see.

### 4.3 Explicit failure table by method (use this as the `detectability` column)

| Method | Typical event | Surface (5 cm) signature | Event POD | Amount inversion |
|---|---|---|---|---|
| Centre pivot / sprinkler | 15–30 mm / 3–7 d | Clean top-down wetting, identical to rain | 0.8–0.9 (in-situ) | Fair; RMSE ~5–10 mm/event; bias low if no runoff |
| LEPA / low-elevation bubbler | 15–25 mm, in-furrow | Strongly localised between rows | 0.4–0.7, depends entirely on sensor position relative to furrow | Poor |
| Surface drip / micro | 3–8 mm every 1–3 d, 20–50% wetted fraction | **Often invisible** unless sensor is within ~15 cm of the emitter | **0.1–0.4** | Not attempted — use Tier C + §5 rule simulation instead |
| **Subsurface drip (SDI, 20–45 cm)** | 4–10 mm / 1–3 d | **Zero at 5 cm.** Sharp rise at emitter depth; inverted wetting order | 0 at surface; 0.6–0.8 if a sensor sits at emitter depth | Poor |
| Furrow / alternate furrow | 50–100 mm / 10–21 d | Depends on furrow vs bed placement; can be near-zero on the bed | 0.3–0.8 | Poor — large DP |
| Flood / border / basin | 75–150 mm | **Saturation plateau; capacitance sensors clip at/above porosity** for hours–days | 0.9 (easy to see) | **Worst case — underestimates by 30–70%** because most water leaves as DP/runoff |
| Plastic-film mulch + drip (N. China, Xinjiang) | small, frequent | **Inverted logic: rain produces no SM rise (film sheds it), irrigation does.** Both facts are diagnostic. | 0.5–0.8, and FAR is *low* because rain is excluded | Poor |
| Rice paddy ponding | continuous | θ ≥ porosity, sensor out of range | n/a — regime, not events | n/a |

---

## 5. Rule-based scheduler simulation

Many papers give a rule, not a log. Convert it into a **daily applied-water ensemble** via FAO-56 dual-Kc.

### 5.1 Engine

**Use `pyfao56`** (Thorp, USDA-ARS Maricopa; JOSS ~2022) — a Python implementation of the FAO-56 dual crop coefficient with irrigation scheduling, built at one of your gold-standard sites. Alternative reference implementation: **SIMDualKc** (Rosa et al. 2012, *AWM*) — better documented for deep percolation and capillary rise, but not open Python. `recalled`, high confidence on pyfao56's existence.

**Core equations (FAO-56, Allen, Pereira, Raes & Smith 1998):**
```
ETc_adj,i = (Ks,i · Kcb,i + Ke,i) · ET0,i
Dr,i      = Dr,i−1 − (P − RO)i − Ii − CRi + ETc_adj,i + DPi
TAW       = 1000 (θFC − θWP) Zr
RAW       = p_adj · TAW
Ks        = (TAW − Dr)/((1 − p_adj) TAW)   for Dr > RAW;  else 1
p_adj     = p_table + 0.04 (5 − ETc),  clipped to [0.1, 0.8]
```
Tables: Kcb ini/mid/end, Zr and p by crop, and Kc_ini as a function of wetting frequency are all in FAO-56 (I recall Table 17 for Kcb, Table 22 for Zr and p, Tables 11–12 for single Kc — **verify the table numbers before citing**). **Use the updated coefficients of Pereira, Paredes, Allen et al. (2021, *Agricultural Water Management*, two-part "Standard single and basal crop coefficients… Updates and advances")** in preference to the 1998 tables, and record which set you used.

### 5.2 ET0 and precipitation sources

| Need | CONUS | Global |
|---|---|---|
| ET0 | **gridMET** (Abatzoglou 2013), 4 km daily, provides both `etr` (alfalfa) and `eto` (grass) — **match the reference the paper used or your Kc is wrong by ~15–30%** | **AgERA5** (Copernicus CDS, "Agrometeorological indicators…1979–present", 0.1° daily, bias-corrected to WFDE5) — has Tmax/Tmin/RH/wind/radiation for full FAO-56 PM. Second choice: ERA5-Land 9 km hourly. |
| Actual ET (huge asset) | **OpenET** (Melton et al. 2022 *JAWRA*), 30 m monthly (and daily for some models), western US, ensemble of eeMETRIC / SSEBop / SIMS / PT-JPL / DisALEXI / geeSEBAL. Volk et al. 2024 *Nature Water* intercomparison: cropland MAE roughly 0.5–0.8 mm/d monthly. | No equivalent. GLEAM / MOD16 at 500 m–25 km are too coarse. |
| Precipitation | AORC / Stage IV / PRISM / Daymet | MSWEP v2.8 > IMERG-Final > ERA5 > CHIRPS (CHIRPS is precipitation-*only* and gauge-sparse in many ag regions) |

**For CONUS this unlocks a direct method:** `I ≈ ET_OpenET − P + ΔS_measured + DP`, closed at 30 m on the actual field polygon. That is far better than any SM inversion, and it is the strongest argument for treating CONUS station-years as a separate, higher-quality tier.

### 5.3 Rule → series conversions

| Reported rule | Conversion |
|---|---|
| "irrigated at X% depletion" / "MAD = X%" | Run the balance; trigger when `Dr ≥ (X/100)·TAW`; apply `I = min(Dr, system_capacity_per_event)`. Pivot gross capacity ~6–8 mm/d ⇒ ~25 mm per pass; surface systems 75–100 mm per event. |
| "weekly 25 mm" | Calendar-deterministic. **But you must decide whether they skipped after rain** — encode *both* variants as ensemble branches and let the uncertainty reflect it. |
| "100% ETc replacement" | `I_i = max(0, ETc_adj,i − Pe,i)` accumulated to the stated interval; `Pe` from the USDA-SCS or FAO-56 effective-rainfall method (state which). |
| "50% / 75% of ETc" (deficit trials) | Scale the above; **and turn on Ks** — deficit plots are stressed, so `Kcb` must be reduced by Ks or you over-apply. |
| "irrigated when θ fell below X" | Use the *measured* θ to trigger — this is the easy case and is nearly as good as a log. |
| "total seasonal application = X mm" | Disaggregate with the depletion rule, then rescale to match the reported total. Constraining to a reported seasonal total is a big accuracy gain — prioritise extracting that number. |

**Gross vs net.** Papers rarely say. Apply application efficiency `Ea`: pivot 0.85–0.90 (LEPA ~0.95), drip 0.85–0.95, furrow 0.55–0.75, border/basin 0.60–0.80. Store both `irrigation_gross_mm` and `irrigation_net_mm` and a flag for which one the paper reported.

### 5.4 Uncertainty propagation

Monte Carlo, n = 500, sampling jointly:

| Parameter | Distribution |
|---|---|
| ET0 | ×(1 + N(0, 0.10)) |
| Kcb mid | ×(1 + N(0, 0.15)) |
| θFC, θWP | ±0.03 m³/m³, or sample from **Rosetta3** / **SoilGrids 2.0** pedotransfer uncertainty at the site texture |
| Zr | ×(1 + N(0, 0.25)) |
| p | ±0.05 |
| Season start/end | ±7 d |
| Ea | ±0.10 |
| Precipitation | ×(1 + N(0, 0.20)), or use an ensemble of precip products |
| "skipped after rain?" | Bernoulli(0.5) branch |

Persist: daily median, p10, p90, the ensemble spread, and a hash of the parameter draw so it is reproducible.

### 5.5 `irrigation_provenance` enum

```
measured_flowmeter     -- metered volume, per event or seasonal (WIMAS, lysimeter, research plot)
logged_operator        -- dates + amounts stated in the paper or a farm log
rule_simulated         -- §5: derived from a stated rule via FAO-56 dual Kc
inferred_from_sm       -- §4: event detection ± inversion from the SM series itself
inferred_from_rs       -- S1/SMAP/OpenET-residual seasonal estimate, no daily structure
unknown                -- irrigated by label, but no forcing reconstruction possible
not_irrigated          -- rainfed; forcing is identically zero and that is a FACT, not a gap
```

The distinction between `unknown` (missing forcing) and `not_irrigated` (zero forcing) is the most important single column in this schema. Conflating them is precisely the bias the brief warns about.

⚠️ **Circularity guard:** `inferred_from_sm` forcing is derived *from the target variable*. If you feed it as an input to a model predicting that same target, you leak. Either (a) exclude `inferred_from_sm` rows from the input channel and let the latent embedding handle them, or (b) derive the forcing from a *strictly causally prior* window and enforce it in the feature pipeline. I recommend (a). Say this explicitly in the paper — a reviewer will find it.

---

## 6. The unknown-irrigation case

### 6.1 Options in the literature

| Option | Precedent | Verdict |
|---|---|---|
| **Zero the channel** | The naive default | **Reject.** Teaches the model that these sites are wetter than their rainfall justifies ⇒ a learned site-specific bias that does not transfer. |
| **Mask the loss during suspected irrigation windows** | Standard for missing *observations* in hydrology LSTMs | **Reject for this project.** You would be masking out exactly the wet, irrigated conditions the project exists to predict. It buys a better-looking metric by deleting the hard cases. |
| **Per-site latent embedding** | **EA-LSTM** (Kratzert et al. 2019 *HESS*) — static catchment attributes gate the input layer; and the regionalisation results in Kratzert et al. 2019 "Toward improved predictions in ungauged basins" | **Adopt, with a caveat** (below). |
| **Learned latent forcing / differentiable hybrid** | δHBV (Feng, Shen et al. 2022 *WRR*), Tsai et al. 2021 *Nature Comms* "From calibration to parameter learning" | Attractive and principled — learn irrigation as a latent input constrained by a water balance. **Too ambitious for v1**; keep as the follow-up paper. |
| **Exclude from training, retain for evaluation** | Conservative | Wastes most of the corpus. Use only for the *headline* metric. |

### 6.2 Recommendation (adopt all four parts)

1. **Explicit forcing channel with provenance.** Feed `[irrigation_mm, irrigation_sigma_mm, one-hot(provenance)]` as daily inputs. The network learns to discount `rule_simulated` relative to `measured_flowmeter` on its own — you do not have to hand-tune trust.
2. **Entity-aware static gate** (EA-LSTM style) over an "irrigation propensity" static vector: fused `p_irrigated`, `irrigation_method`, aridity index, MIRCA-OS crop-conditioned irrigated fraction, `field_area_ha`, `label_confidence`.
   ⚠️ **The deployability trap:** a *free* per-site embedding memorises and cannot be produced for an unseen field, so the model is undeployable — which defeats the entire point of replacing sensors. **Fix:** two-stage. (a) train with free per-site embeddings; (b) train a regressor from *observable static attributes* → embedding; (c) fine-tune and evaluate using **only** the regressed embedding. Report both numbers; the gap between them is your honest "cost of ungauged deployment" and is a publishable result in itself.
3. **Confidence-weighted loss**: weight each sample by `p_label_correct`, downweighting `unknown` rows rather than deleting them.
4. **Stratified evaluation**: the headline ubRMSE comes **only** from `provenance ∈ {measured_flowmeter, logged_operator}` with `p_irrigated > 0.9` or `< 0.1`. Everything else is reported in a separate table.

### 6.3 Cost of zeroing the forcing — quantified (reasoned, not cited)

In irrigated maize at Mead, NE: growing-season P ≈ 350–450 mm, irrigation ≈ 150–300 mm ⇒ irrigation is **30–45%** of water input. In Arizona alfalfa or the Ebro, **70–95%**.

Why the naive intuition ("the RMSE will explode") is wrong, and what actually happens: the missing water is bounded by root-zone storage. With TAW ≈ 150 mm over a 1 m profile, 250 mm of unmodelled irrigation is ~1.7 refills spread over a season. A flexible model will absorb most of that into a **wetter site-level offset** and a damped dry-down rate. So:

- **Overall RMSE degrades only modestly** — my estimate, **+0.01 to 0.02 m³/m³** on top of a ~0.02–0.035 m³/m³ baseline. This is the trap: the aggregate metric looks acceptable.
- **Event-scale skill collapses.** Correlation of dθ/dt, timing of wetting fronts, and the top-quintile-of-θ conditional bias all degrade severely. I would expect a **strongly negative bias in the wet tail** (the model under-predicts exactly the post-irrigation conditions an irrigation-scheduling user cares about) and a **loss of transferability** — because the absorbed offset is site-specific, held-out-site performance degrades far more than held-out-time performance.
- **The metric to report is therefore not RMSE.** Report: conditional bias in the top quintile of θ, dθ/dt correlation, and wetting-event timing error, in addition to ubRMSE.

**Run the experiment rather than citing me.** The **US-Ne1/Ne2 (irrigated) vs US-Ne3 (rainfed)** triplet is a natural controlled experiment: same soil series, same climate, same crop rotation, 20 years, logged irrigation. Train with the true irrigation series, with it zeroed, and with it replaced by a §5 rule-simulation, and report all three. This is cheap, it is rigorous, and it directly quantifies the project's central risk. **I would make this Figure 2 of the paper.**

---

## 7. Deliverable — the specification

### 7.1 Schema

```sql
-- one row per station-year
CREATE TABLE irrigation_label (
  station_id              TEXT NOT NULL,
  year                    INT  NOT NULL,
  season                  TEXT,            -- kharif|rabi|zaid|main|second, for multi-crop years

  -- CLASS
  irrigation_class        TEXT NOT NULL,   -- irrigated|rainfed|supplemental|flooded_paddy|unknown
  p_irrigated             REAL NOT NULL,   -- calibrated [0,1]
  p_irrigated_lo, p_irrigated_hi REAL,     -- bootstrap 90% CI
  label_model_version     TEXT NOT NULL,
  dominant_evidence       TEXT[],          -- audit trail: top-3 LFs

  -- METHOD
  irrigation_method       TEXT,            -- center_pivot|linear_move|solid_set|big_gun|
                                           -- lepa|furrow|alternate_furrow|border|basin|
                                           -- flood_paddy|surface_drip|subsurface_drip|
                                           -- micro_sprinkler|manual|unknown
  method_source           TEXT,            -- declared|paper_text|sm_vertical_signature|inferred|unknown
  p_method                REAL,
  wetted_fraction_est     REAL,            -- 0.2-1.0; drives the wetting-geometry prior
  emitter_depth_cm        REAL,            -- SDI only

  -- GEOLOCATION QUALITY
  coord_decimal_places    INT,
  geoloc_sigma_m          REAL,
  datum_declared          TEXT,
  boundary_source         TEXT,            -- registry|clu2008|ftw_inferred|buffer_only
  field_area_ha           REAL,
  p_correct_field         REAL,            -- from the 1.3 model
  pivot_corner_risk       BOOL,
  spatial_stability_s     REAL,

  -- SANITY
  fallow_flag             BOOL,
  deficit_treatment       TEXT,            -- e.g. "50pct_ETc"
  seasonal_P_over_ET0     REAL,
  peak_ndvi               REAL
);

-- one row per station-day
CREATE TABLE irrigation_forcing (
  station_id TEXT, date DATE,
  irrigation_gross_mm     REAL,
  irrigation_net_mm       REAL,
  irrigation_sigma_mm     REAL,            -- from the §5.4 Monte Carlo
  irrigation_p10_mm, irrigation_p90_mm REAL,
  irrigation_provenance   TEXT NOT NULL,   -- §5.5 enum
  event_detected          BOOL,
  event_detector          TEXT,            -- dtheta_dt|bocpd|s1_sigma0|none
  event_confidence        REAL,
  precip_product_used     TEXT,            -- sets the FAR; must be recorded
  vertical_wetting_order  TEXT,            -- top_down|bottom_up|simultaneous|none
  is_model_output         BOOL NOT NULL,   -- TRUE for rule_simulated / inferred_*
  derived_from_target     BOOL NOT NULL    -- leakage guard for inferred_from_sm
);

-- evidence, never discarded, so labels can be recomputed
CREATE TABLE irrigation_evidence (
  station_id TEXT, year INT,
  lf_name TEXT, lf_vote TEXT, lf_strength REAL,
  product TEXT, product_version TEXT,
  buffer_radius_m REAL, frac_irrigated REAL, n_pixels INT,
  raw_value JSONB, extracted_at TIMESTAMP
);
```

### 7.2 Decisions, stated plainly

- **Fusion model:** regularised logistic regression on LF outputs + continuous evidence, fitted on ≥400 gold station-years, isotonically calibrated, site-wise CV. FlyingSquid/Dawid–Skene fallback for zero-gold regions. **Not** Snorkel-as-primary (correlated LFs violate its assumptions and you have labels).
- **Event detection per method:** dθ/dt + BOCPD with the best available precipitation for sprinkler/pivot/flood; **vertical wetting-order classifier** for SDI; **absence-of-dry-down** for drip/micro; **no daily detection at all** for drip — fall back to §5 rule simulation with honest uncertainty. S1/SMAP for seasonal classification only.
- **Unknown forcing:** explicit channel + provenance one-hot + EA-LSTM-style static gate regressed from observable attributes + confidence-weighted loss + stratified reporting. Never zero, never mask.

### 7.3 Honest expected label-error rate

`recalled`/reasoned. These are the numbers to put in a limitations section.

| Region / setting | Class error | Method error | Daily-amount availability |
|---|---|---|---|
| Western US, pivot, ≥4 dp coords, IrrMapper+registry | **2–5%** | 5–15% | Good (WA/CO attributes, WIMAS, OpenET) |
| Western US, 3 dp coords | 5–12% | 15–30% | Moderate |
| High Plains Aquifer, AIM-HPA | 4–10% | 20–35% | Good where metered (KS) |
| **Humid eastern US, supplemental** | **20–35%** | 30–50% | Poor |
| EU with LPIS/GSAA + declared irrigation (ES, parts of IT/FR) | 5–12% | 10–25% | Moderate (consortia records) |
| EU without declaration | 15–28% | 40–60% | Poor |
| China, N. China Plain / oasis | 10–22% | 30–50% | Poor |
| China, film-mulch drip (Xinjiang) | 10–20% | 25–40% | Poor, but the film signature helps |
| India | **22–40%** | 50–70% | Very poor |
| Sub-Saharan Africa smallholder | **35–60%** | 60–80% | Effectively none |
| Rice paddy, anywhere | 5–12% (extent easy) | n/a | "Amount" is not a meaningful quantity |
| **Any drip / SDI, anywhere** | 10–25% | **30–50%** | Near zero from SM; rule-simulation only |
| Research plots with logged treatments | **<2%** | <5% | Excellent |

**Implications, stated for the paper:**
1. The **headline** model metric must come from the high-confidence subset (`p_irrigated` > 0.9 or < 0.1, provenance ∈ {measured, logged}). Everything else goes in a stratified supplementary table.
2. **Report "coverage at precision ≥0.95"** alongside accuracy. If that coverage is 30%, the honest framing is "a high-quality 30% core with a larger noisy periphery," not "a terabyte-scale global database."
3. India / SSA / humid-East rows should carry a visible **`low_confidence_region`** flag and be excluded from headline claims by default. Publishing them with the flag is better science than dropping them silently, and it makes the database useful to someone who later brings better labels.
4. **Method error exceeding class error is the structural problem**, because method determines whether the amount channel means anything. Prioritise the declared-attribute registries in §2.2 — WA, CO, UT, ID, ABARES CLUM, SIGPAC — over adding a fifth extent map. One state with a declared irrigation-method attribute is worth more than the global raster stack.

---

## 8. Mandatory verification queue (search budget was exhausted)

Verify before citing any number above. Ordered by consequence:

1. **The 2024 *Agricultural Water Management* Bayesian change-detection paper at Mead, NE** — exact citation, method, POD/FAR/amount RMSE. I could not recall it and did not invent numbers for it.
2. **ECIRA** — confirm the product exists, who publishes it, its resolution and accuracy. I could not identify it and it should not be cited until confirmed.
3. **ESA WorldCereal irrigation layer** — the actual reported irrigated-class F1 per AEZ and the authors' own caveat wording.
4. **LANID** — current version, year coverage, and the East-vs-West accuracy split; whether a post-2017 extension exists.
5. **IrrMapper v1.2** — confirm the version number, state coverage and the irrigated-class PA/UA (not just OA).
6. **FAO-56 table numbers** (Kcb, Zr, p) and the exact Pereira et al. 2021 *AWM* two-part citation.
7. **USDA CLU 2008 snapshot** — current public mirror and licence status.
8. **French RPG** — whether an irrigation declaration is in the public release, and for which years.
9. **Spain SIGPAC** — which autonomous communities expose an irrigation coefficient attribute.
10. **MIRCA-OS** — exact publication, year range and resolution.
11. **`pyfao56`** — current version, and whether it implements the depletion-trigger scheduler natively.
12. **Dari et al. / ESA Irrigation+** — the actual reported irrigation-amount RMSE and bias over Ebro and Po, in mm/month.
13. **Bushland lysimeter data** — current Ag Data Commons DOIs and which crop-years include multi-depth neutron-probe profiles.
14. **OpenET** — current spatial/temporal coverage and the Volk et al. 2024 cropland accuracy figures.

**Sources:** none — both WebSearch calls returned "web search budget exhausted (200/200)". No URLs were retrieved in this subtask, so no source list can honestly be given. Every factual claim above is recalled from training and carries the confidence flags stated inline.