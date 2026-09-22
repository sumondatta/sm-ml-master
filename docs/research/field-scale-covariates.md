<!--
Compiled from a research sweep, not written by hand. Preserved verbatim because
it is reference material the implementation draws on rather than prose meant to
be read start to finish.

CONFIDENCE: the sweep's web-search budget was exhausted before these sections
ran, so everything in them is recalled from model knowledge and NONE of it was
corroborated by a search. Every URL and every accuracy figure must be verified
before it is relied on. Nothing here is legal advice.
-->

## CRITICAL CAVEAT ON PROVENANCE

**Zero web searches executed.** The session's WebSearch budget (200/200) was already exhausted by prior agents in this workflow before my first call returned. WebFetch/curl are blocked per the environment constraints. **Everything below is from trained knowledge and is labelled `recalled`.** Nothing here is `confirmed`. Treat every URL, coefficient, and product ID as requiring verification before you write a downloader against it. I have flagged the ones I would personally bet on versus the ones I would not. Where I do not know an endpoint, I say "unknown — verify" rather than inventing one.

---

# 1. WITHIN-FIELD SENSOR PLACEMENT AND WETTING GEOMETRY

## 1.1 Why this dominates the error budget

Under localized irrigation the soil moisture field is **deterministically non-uniform in 3D** at the scale of tens of centimetres. This is not noise — it is the governing physics, and it is the single largest unmodelled term in the plan as it stands. A model trained on pooled (x, y, z) samples without position labels is fitting a mixture of physically distinct regimes and will produce a conditional mean that matches no actual sensor.

## 1.2 Method-by-method magnitudes

### Surface drip (point source)

Wetted-bulb geometry. The standard empirical model is **Schwartzman & Zur (1986)**, *J. Irrig. Drain. Eng.* 112(3), "Emitter spacing and geometry of wetted soil volume", of the form:

```
z = 2.54 · V^0.63 · Ks^0.45 · q^-0.32        (wetted depth, cm)
w = 1.82 · V^0.22 · Ks^-0.17 · q^0.17        (wetted width, cm)
   V = cumulative applied volume (L), Ks = cm/h, q = emitter discharge (L/h)
```
`recalled` — the *functional form* (depth increases with q^negative, width with q^positive; sand = deep+narrow, clay = shallow+wide) I am confident in; **the exact exponents and the 2.54/1.82 coefficients need verification against the original paper.** Do not hard-code these without checking.

Typical wetted radius at the surface for a 2–4 L/h emitter, 20–40 L applied: ~15–25 cm in sand, ~30–45 cm in silt loam, ~40–60 cm in clay loam (lateral spread greater, depth less). `recalled`.

Observed θ contrasts, near-emitter vs. midpoint between emitters, same depth, same day:
- 0–20 cm depth: **0.08–0.20 m³/m³** in loam/sandy loam. `recalled`
- 40–60 cm depth: contrast collapses to ~0.02–0.05 m³/m³ (the bulb merges laterally with depth and redistribution homogenizes).
- The gradient is *steepest immediately post-irrigation* and decays over 24–72 h. So position × hours-since-irrigation is an **interaction**, not two main effects.

Key papers to mine for these numbers (all `recalled`, all should be in your harvest anyway):
- **Skaggs, Trout, Šimůnek & Shouse (2004)**, "Comparison of HYDRUS-2D simulations of drip irrigation with experimental observations", *J. Irrig. Drain. Eng.* 130(4) — USDA-ARS Parlier; measured θ on a 2D grid around a surface emitter in sandy loam. This is arguably *the* reference dataset for the near-emitter gradient.
- **Gärdenäs, Hopmans, Hanson & Šimůnek (2005)**, *Agric. Water Manage.* 74 — 2D simulation of N leaching under four micro-irrigation types (surface drip, SDI, microspray, fan-jet); gives the θ field for each geometry.
- **Provenzano (2007)**, "Using HYDRUS-2D simulation model to evaluate wetted soil volume in subsurface drip irrigation systems", *J. Irrig. Drain. Eng.*
- **Kandelous & Šimůnek (2010)**, *Agric. Water Manage.* 97 — SDI wetting patterns, HYDRUS-2D vs. field; and Kandelous, Šimůnek, van Genuchten & Malek (2011) 2D/3D comparison.
- **Elmaloglou & Diamantopoulos** — layered soils and the effect of a textural interface on bulb shape.
- **Lazarovitch, Warrick, Furman & Šimůnek** — steady/transient source solutions, useful for a closed-form bulb prior.

### Subsurface drip (SDI)

Two extra parameters dominate: **tape depth** (typically 20–45 cm; US Great Plains corn/cotton SDI 30–40 cm; Xinjiang film-mulched cotton is usually *surface* drip under the film, not SDI) and **tape spacing** (0.8–1.6 m, or one tape per two rows).

Signature effect: **the 0–10 cm layer stays dry under SDI** — θ at 5–10 cm can be 0.05–0.12 m³/m³ *lower* than under surface drip at identical ET and identical applied depth, because there is no surface wetting and upward flux is capillarity-limited. `recalled`. A model that does not know `tape_depth_cm` will systematically over-predict SDI surface moisture. This is a first-order sign error, not a calibration nuisance.

Corollary: the **vertical θ profile shape inverts** — SDI has a subsurface maximum at tape depth; surface drip has a monotonic decline from the surface. If your model emits a multi-depth profile, this single covariate flips the profile's shape.

### Furrow

- **Bed top vs. furrow bottom** at 15 cm: routinely **0.05–0.15 m³/m³**, furrow bottom wetter, decaying with depth; by 60–90 cm the difference is usually <0.03. `recalled`
- **Alternate-furrow irrigation (AFI)** — very common in China (Gansu, Xinjiang), Iran, India — creates a *persistent* lateral asymmetry: irrigated furrow vs. dry furrow differ by 0.06–0.15 m³/m³ at 20–40 cm for most of the interval. A dataset that pools AFI plots without the furrow flag is fitting a bimodal distribution.
- **Bed shoulder / bed centre** on raised beds: shoulder is the driest point in the whole geometry (lateral wetting from both furrows has the longest path, plus it is the evaporation hotspot).
- **Distance down the run**: infiltration opportunity time = (recession time − advance time) at each station. For long furrows without cutback/surge, head-to-tail infiltrated depth ratios of **1.3–2.0** are typical; θ at 0–60 cm follows. This is computable if the paper reports furrow length, inflow rate, slope and cutoff time — feed those into a Kostiakov-Lewis / WinSRFR-style advance model to get an opportunity-time fraction per station. Most papers instrument at the 1/3 and 2/3 stations or only mid-field.

### Border / basin / flood

Same opportunity-time logic, plus basin flood is close to spatially uniform in application (DU 0.80–0.90 for level basins) but the *infiltration* is not, because of soil-variability-driven Ks. For level basins I would model position as negligible and put the variance into the soil term; for graded borders, model `distance_down_run_frac` ∈ [0,1].

### Centre pivot

- **Radial position**: designed application *depth* is nominally uniform with radius, but the instantaneous **application rate** scales linearly with radius (outer spans deliver the same depth in a much shorter window), so runoff/redistribution risk and surface sealing are radius-dependent. Under a linear-move this disappears.
- **End gun / corner arm**: end-gun-served annuli have markedly lower uniformity and are often the wettest or driest zone.
- **Wheel tracks**: compacted, low infiltration, locally saturated or ponded — a sensor 1 m from a track is a different regime. Almost never reported.
- Pivot uniformity is conventionally reported as **Heermann–Hein CU** (ASABE S436.1, the radius-weighted variant), typically **0.85–0.94** for a well-maintained pivot. `recalled`

### Sprinkler (solid-set / hand-move / linear)

Reported as **DU_lq** (low-quarter distribution uniformity) or **CU** (Christiansen). Typical ranges `recalled`:

| System | CU | DU_lq |
|---|---|---|
| Surface drip / micro | 0.90–0.95 (as EU) | 0.85–0.95 |
| SDI | 0.90–0.97 | 0.85–0.95 |
| Centre pivot | 0.85–0.94 | 0.75–0.88 |
| Solid-set sprinkler | 0.75–0.88 | 0.65–0.82 |
| Hand-move / travelling gun | 0.65–0.80 | 0.55–0.72 |
| Graded furrow | — | 0.60–0.80 |
| Level basin | — | 0.80–0.90 |

Empirical interconversions (Keller & Bliesner; Burt et al. 1997 ASCE *J. Irrig. Drain. Eng.* 123(6) "Irrigation performance measures: efficiency and uniformity"): `CU ≈ 100 − 0.63(100 − DU_lq)` and `DU_lq ≈ 100 − 1.59(100 − CU)`. `recalled`.

## 1.3 Turning DU/CU into a σ inflator — the derivation you actually need

Assume applied depth `d` over the field is approximately normal with mean `d̄` and CV `c`.

- Christiansen CU is `1 − E|d − d̄|/d̄`. For a normal variate, `E|d − d̄| = σ√(2/π) = 0.7979σ`. Therefore **`c = (1 − CU)/0.7979 = 1.2533(1 − CU)`**.
- DU_lq is `d̄_lowest quarter / d̄`. For a normal variate the mean of the lowest quartile is `d̄ − 1.2711σ`. Therefore **`c = (1 − DU_lq)/1.2711`**.

(These are the standard normal-distribution relations — Warrick (1983) derived the CU↔CV family for several distributions; use log-normal instead if you want the tail right for surface systems. `recalled`.)

Then convert an application-depth CV into a θ standard deviation for a control volume of thickness `Δz` (m) receiving `I` mm:

```
σ_θ,irrigation ≈ c · I / (1000 · Δz)            [m³/m³]
```

Worked: pivot, CU = 0.88 → c = 0.150; I = 25 mm over Δz = 0.30 m → σ_θ ≈ 0.0125 m³/m³. Solid-set, CU = 0.78 → c = 0.276; same I, Δz → σ_θ ≈ 0.023.

**The honest conclusion from this arithmetic:** stochastic sprinkler/pivot non-uniformity contributes only **0.01–0.03 m³/m³** — real, but modest. The **0.10–0.20 m³/m³** figure in the gap statement is *not* a uniformity effect; it is the **deterministic drip wetting-bulb geometry**. Do not conflate them. They need different treatments: uniformity → additive heteroscedastic noise term; bulb geometry → a *mean-shift covariate*.

## 1.4 What fraction of papers report position?

I cannot measure this without the corpus, and I will not pretend to. My prior, offered as a prior only (`recalled`, low confidence):

| Journal class | Reports depth | Reports horizontal position at all | Reports full geometry (distance + spacing + discharge) |
|---|---|---|---|
| *Agric. Water Manage.*, *Irrig. Sci.*, *J. Irrig. Drain. Eng.* — drip-focused agronomy | ~100% | ~40–55% | ~15–25% |
| Chinese-language / Xinjiang film-mulch drip corpus | ~100% | ~50–65% (often as "between the two inner rows under the film") | ~25–35% (film/tube/row layout is usually stated as "1 film 2 tubes 4 rows") |
| Furrow/surface irrigation agronomy | ~100% | ~30–45% (bed vs furrow) | n/a |
| Pivot/sprinkler agronomy | ~100% | ~10–20% (radial position) | ~5% |
| Remote-sensing / SM-validation / calibration-validation papers | ~95% | **<5%** | ~0% |

**Do not take my number. Measure it.** Add to the extraction schema a mandatory `position_reported` tri-state and report the observed rate per corpus stratum. That measured rate is itself a deliverable and determines whether §1.5 is a footnote or the centre of the modelling design.

**High-value harvest target:** papers that report **two or more horizontal positions at the same depth and date** are *direct observations of the within-field gradient*. There are enough of them (the HYDRUS-validation literature above is exactly this) to fit an empirical `Δθ(distance, depth, hours_since_irrigation, texture)` response surface. Flag and prioritize these during figure digitization — a 2-panel "near emitter / mid-row" figure is worth ten single-position time series for calibrating your σ prior.

## 1.5 Recommended schema

```
-- geometry of the irrigation system
irrigation_method            enum{surface_drip, sdi, microspray, sprinkler_solidset,
                                  sprinkler_handmove, center_pivot, linear_move, gun,
                                  furrow_every, furrow_alternate, border, basin,
                                  flood_wild, subirrigation, unknown}
emitter_spacing_cm           float   NULL
emitter_discharge_lph        float   NULL
lateral_spacing_cm           float   NULL
tape_depth_cm                float   NULL      -- SDI; 0 for surface drip
tape_spacing_cm              float   NULL
furrow_spacing_cm            float   NULL
bed_width_cm                 float   NULL
run_length_m                 float   NULL
reported_DU_lq               float   NULL
reported_CU                  float   NULL

-- where the sensor actually is
depth_cm                     float   NOT NULL
emitter_distance_cm          float   NULL      -- horizontal, to nearest emitter
row_offset_cm                float   NULL      -- horizontal, to nearest plant row
bed_position                 enum{bed_center, bed_shoulder, furrow_bottom, furrow_side,
                                  irrigated_furrow, dry_furrow, flat, under_film,
                                  between_films, unknown}
radial_position_frac         float   NULL      -- pivot, r/R
distance_down_run_frac       float   NULL      -- surface systems
n_replicate_positions        int                -- how many horizontal positions averaged
value_is_spatial_mean        bool

-- provenance
position_reported            enum{explicit, inferable_from_figure, stated_qualitatively,
                                  not_reported}
position_source              enum{text, figure_caption, figure_digitized, schematic,
                                  regional_default, none}
```

Note `value_is_spatial_mean` and `n_replicate_positions`: a reported value that is already the mean of 4 access-tube positions has **much lower** variance than a single-probe value and should get a **smaller** σ, scaled roughly by `1/√n`. Getting this backwards would be a silent, systematic miscalibration.

## 1.6 Treatment when position is unreported — recommendation

**Use both: a per-series latent AND an explicit heteroscedastic σ head. They do different jobs.**

**(a) Per-series random effect / embedding — for in-domain fit.**
Define `series_id = hash(paper_doi, site, field, treatment_arm, depth, sensor_position_label)`. Give the network `nn.Embedding(n_series, d)` with `d ≈ 8–16`, added to the penultimate representation, with L2 penalty toward zero (this *is* a Gaussian random-effect prior; λ sets the prior variance).

Critical detail: **train with embedding dropout.** On ~30–50% of minibatches, zero the embedding. This forces the backbone to be predictive without it and makes the `embedding = 0` inference path (the only path available at a new site) well-calibrated rather than out-of-distribution. Without this, the embedding soaks up all the signal and the model collapses at deployment — which is precisely the sensor-replacement use case.

Report **two skill numbers, always**: in-domain (embedding known) and zero-shot (embedding zeroed). The zero-shot number is the one that speaks to the user's actual claim. Papers that report only the former are not answering the question.

**(b) Heteroscedastic σ head — for honest uncertainty.**
Train with Gaussian NLL, the network emitting `(μ, log σ)`, where the σ head consumes: `position_reported`, `irrigation_method`, `depth_cm`, `hours_since_irrigation`, `n_replicate_positions`, `value_is_spatial_mean`, `DU_lq/CU`. It will learn the inflation itself given enough data. Seed it with the priors in §1.7 via a soft penalty in the first epochs if data are thin.

Prefer NLL over quantile regression here because you want a per-row σ you can *propagate*; if you want distribution-free intervals, add split-conformal calibration on a held-out-by-paper split, with a **group-conditional** conformal (separate quantile per `irrigation_method × position_reported` cell) so the coverage guarantee is not just marginal.

**(c) Physically-informed imputation for the missing-position rows.**
When position is not reported, do not drop and do not impute a single value. Impute the **method-conditional modal placement** (below), set `position_source = regional_default`, set the missingness indicator, and let σ inflate. Modal defaults (`recalled`, these are conventions, not facts — each should be overridable per paper):

| Method | Modal unreported placement |
|---|---|
| Surface drip, row crop | 10–15 cm from emitter, in the crop row |
| Film-mulched drip (Xinjiang cotton) | under film, between the two inner rows, ~15–20 cm from the tape |
| SDI | directly above the tape, in the row |
| Furrow, row crop | bed centre / in the plant row |
| Sprinkler / pivot | plant row, mid-field, away from wheel track |
| Basin / border | mid-field |

**(d) Split by paper, never by row.** With per-series latents and autocorrelated time series, a random row split will report an R² that is pure leakage. Use `GroupKFold` on `paper_doi`, and also report a **leave-one-region-out** and a **leave-one-irrigation-method-out** score.

## 1.7 Published priors for within-field σ_θ

Usable priors (`recalled`; verify each before citing in a manuscript):

- **Famiglietti, Ryu, Berg, Rodell & Jackson (2008)**, *Water Resour. Res.* 44, W01423 — "Field observations of soil moisture variability across scales". Establishes the **upside-down-U**: σ_θ rises with mean θ to a peak near θ̄ ≈ 0.15–0.25 m³/m³, then declines toward saturation. Peak σ_θ in the range **0.04–0.06 m³/m³** for footprints of 10²–10³ m. Earlier: **Famiglietti, Rudnicki & Rodell (1998)**, *J. Hydrol.* 210, transect study.
- **Brocca, Morbidelli, Melone & Moramarco (2007)**, *J. Hydrol.* 333, and **Brocca et al. (2010)**, *WRR* — σ(θ̄) relations for Italian catchments; gives fitted parametric forms.
- **Vereecken, Kamai, Harter, Kasteel, Hopmans & Vanderborght (2007)**, *Geophys. Res. Lett.* 34 — "Explaining soil moisture variability as a function of mean soil moisture"; derives the upside-down-U analytically from the water retention curve, so it gives you a **texture-conditional** σ prior, which is exactly what you want given you already have Rosetta VG parameters.
- **Lawrence & Hornberger (2007)**, *GRL* — soil texture control on the σ–θ̄ relationship.
- **Western, Blöschl & Grayson (1998, 2004)** — Tarrawarra; geostatistics of θ, correlation lengths of 10–50 m.

**These are all rainfed/natural fields.** For irrigated fields I know of **no** published, compiled, method-stratified σ_θ table. That is a genuine gap and, notably, **a publishable contribution your corpus can produce**: harvest the multi-position papers of §1.4 and publish the first empirical `σ_θ(irrigation_method, depth, texture, hours_since_irrigation)` table. I would pitch that as a standalone methods paper.

Interim working priors for irrigated fields (my construction from the magnitudes above — **explicitly my estimate, not a citation**):

| Method | σ_θ at 0–20 cm | σ_θ at 20–60 cm | σ_θ at >60 cm |
|---|---|---|---|
| Surface drip, position unknown | 0.055 | 0.030 | 0.018 |
| SDI, position unknown | 0.050 | 0.040 | 0.020 |
| Furrow (every), position unknown | 0.045 | 0.028 | 0.018 |
| Furrow (alternate), position unknown | 0.065 | 0.040 | 0.022 |
| Centre pivot | 0.030 | 0.022 | 0.015 |
| Solid-set sprinkler | 0.035 | 0.025 | 0.016 |
| Level basin / border | 0.028 | 0.022 | 0.015 |
| Any method, position explicitly reported | multiply above by ~0.45 | " | " |

Multiply by the Famiglietti/Vereecken wetness factor `f(θ̄)` peaking at θ̄ ≈ 0.20, and by `1/√n_replicate_positions` where the value is a spatial mean.

---

# 2. MULCH AND SURFACE COVER

## 2.1 Plastic film mulch — magnitudes

Effects (`recalled`, from the Xinjiang / Gansu / Loess Plateau literature):

- **Soil evaporation reduced by 50–80%** under the film relative to bare soil; near-total suppression directly beneath intact film, with the residual E occurring through the planting holes and the uncovered inter-film strips.
- **Seasonal ET reduced 10–30%**, but **transpiration often *increased* 10–25%** because canopy development is faster and biomass higher. Net ET reduction is therefore smaller than the E reduction alone suggests.
- **Topsoil temperature +2–5 °C** at 5–10 cm during the day in early season (up to +6–8 °C peak for clear film; black film less). This accelerates emergence and shifts the thermal-time clock — so mulch interacts with your GDD phenology coordinate in §3.
- **θ in 0–20 cm higher by 0.02–0.06 m³/m³** under film vs. bare at equal irrigation.
- **Diurnal condensation cycling**: water evaporates, condenses on the film underside, and drips back. The 0–5 cm layer under film shows a *damped* diurnal θ signal and no sustained drying front. A model with a bare-soil evaporation prior will predict a drying surface layer that simply does not exist there.
- **Salinity**: film suppresses the evaporative concentration of salt at the surface; under-film drip in Xinjiang is explicitly used as a *desalinization* strategy (salt is pushed to the inter-film strips and below the bulb). This is directly relevant to the user's salinity interest and reverses the usual arid-zone surface-salt-crust expectation.
- **Coverage fraction** is the key quantitative field: Xinjiang "one film, two tapes, four rows" (一膜两管四行) or "one film, three tapes, six rows" layouts cover roughly **55–75%** of the ground. Do not encode mulch as a boolean; encode `mulch_cover_frac`.

**Straw / residue mulch** (`recalled`): at 3–9 t ha⁻¹, reduces E by **20–50%**, lowers daytime soil temperature by 1–3 °C (opposite sign to plastic), raises 0–20 cm θ by **0.01–0.04 m³/m³**, and slows the drying-front advance.

## 2.2 FAO-56 dual-Kc treatment

**Allen, Pereira, Raes & Smith (1998), FAO Irrigation & Drainage Paper 56**, §7 "Mulches" (`recalled`, verify page/section):

- **Organic/straw mulch**: reduce `Ke` by approximately **5% for each 10%** of the soil surface covered. So 80% straw cover → `Ke` × ~0.60.
- **Plastic mulch**: `Kc ini` is strongly reduced; `Kc mid` and `Kc end` are **increased by 10–30%** relative to the non-mulched crop because transpiration rises; total seasonal ET is reduced **10–30%**, and irrigation depth reduced ~5–15% more than that because deep percolation falls too.
- Implementation: the cleanest encoding is not to alter Kc but to alter the **exposed-and-wetted fraction `few`** in the dual-Kc evaporation term: `few = min(1 − fc, fw) × (1 − f_mulch)` where `f_mulch` is the *impermeable* cover fraction. This keeps FAO-56's own machinery and is physically transparent.
- For **drip under film**, `fw` (fraction wetted) is already small (0.30–0.40 per FAO-56 Table 20 for trickle), and `f_mulch` then knocks it down further — the product is the right feature.

Feed the model `Ke_adjusted`, `few`, and `f_mulch` as separate features, not just a mulch flag; the physics is in the product.

## 2.3 Gridded mulch / plastic-cover products

This is the weakest link in my recall, and I will be explicit about it.

| Product | What | Res / extent | Access | Confidence |
|---|---|---|---|---|
| **Global plastic greenhouse map, Tang et al. (2023) *Nature Food*** | Plastic-covered greenhouses, global, Sentinel-2 | ~10 m, global, ~2019 | I believe the data were deposited on Zenodo with the paper. **URL unknown — verify via the paper's Data Availability statement.** | `recalled`, moderate — I am fairly confident such a paper exists; less confident of authors/year |
| **Plastic-mulched farmland (PMF) mapping, China** | Row-crop plastic film (not greenhouses) from Landsat/Sentinel-2 | 10–30 m, provincial to national China | Several candidates: the **National Tibetan Plateau / Third Pole Environment Data Center (https://data.tpdc.ac.cn)** and the **National Earth System Science Data Center (http://www.geodata.cn)** both host Chinese agricultural land-cover products. Search terms: "plastic-mulched farmland", "地膜覆盖". Hasituya et al. and Lu et al. published PMF-mapping methods with Landsat/HJ-1. **No specific DOI I can vouch for.** | `recalled`, low on the specific product |
| **ESA WorldCover / WorldCereal** | Neither maps mulch | — | — | `recalled`, high — I am confident mulch is *absent* from these |
| **China Statistical Yearbook / National Bureau of Statistics** | Province-level **plastic film use (tonnes)** and **film-mulched area (kha)**, annual, long time series | province, annual | stats.gov.cn; reproduced in many papers | `recalled`, high — this definitely exists and is the most reliable fallback |

**Practical recommendation.** Do not build the pipeline on a gridded mulch product you have not yet located. Build it on a **region × crop × year prior table**, with the gridded product as an optional refinement:

```
P(plastic_film_mulch | region, crop, year):
  Xinjiang cotton, ≥2000                 0.95    cover_frac 0.65
  Xinjiang cotton, 1990–1999             0.60    cover_frac 0.60
  Gansu / Ningxia / Inner Mongolia maize 0.70    cover_frac 0.60
  Loess Plateau maize / potato           0.60    cover_frac 0.55
  NE China (Heilongjiang) maize          0.15
  North China Plain wheat–maize          0.05
  Korea / Japan vegetables               0.80
  Turkey / Spain / Italy vegetables      0.50  (+ greenhouse separately)
  US CA strawberry                       0.98    cover_frac 0.80
  US CA processing tomato                0.25    cover_frac 0.55
  US Southeast plasticulture vegetables  0.85    cover_frac 0.65
  US field maize / soy / cotton          0.01
  India, Pakistan field crops            0.05
  Egypt Nile Delta field crops           0.05
```
(`recalled` throughout — these are my regional-agronomy priors, offered as a starting table to be revised as the corpus is read; the corpus itself will tell you the real rates within your papers.)

**Where the paper states it, always override the prior.** In practice the Xinjiang corpus almost always says so, because film is the defining feature of the system.

## 2.4 Schema

```
mulch_type            enum{none, plastic_clear, plastic_black, plastic_silver,
                           biodegradable_film, straw, residue_standing,
                           gravel_sand, greenhouse, shade_net, unknown}
mulch_cover_frac      float NULL          -- 0–1, fraction of ground
mulch_residue_t_ha    float NULL          -- straw/residue only
mulch_source          enum{paper_text, paper_figure, regional_prior, gridded_product}
f_mulch_impermeable   float               -- derived; 0 for straw, = cover_frac for film
few_adjusted          float               -- derived FAO-56 exposed-wetted fraction
```

---

# 3. CROP, PHENOLOGY AND ROOTING DEPTH AS TIME-VARYING COVARIATES

## 3.1 Crop type per field-year

| Source | Coverage | Res | Access | Confidence |
|---|---|---|---|---|
| **USDA Cropland Data Layer (CDL)** | CONUS, 2008–present national (some states from 1997) | 30 m, annual | CropScape: `https://nassgeodata.gmu.edu/CropScape/`. Point-query API: `https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue?year=2020&x=<X>&y=<Y>` — **coordinates default to EPSG:5070 (CONUS Albers)**; there is a `GetCDLFile` and a `GetCDLStat` service too. Also mirrored in Google Earth Engine as `USDA/NASS/CDL`. Public domain. | `recalled`, high on CropScape and the GEE ID; medium on the exact axis2 path |
| **ESA WorldCereal v1.0** | global, 2021 season only | 10 m | `https://esa-worldcereal.org`; products on Zenodo and via the WorldCereal VITO viewer; layers: `temporarycrops`, `maize`, `wintercereals`, `springcereals`, **`irrigation`** (active irrigation binary — directly relevant to your irrigation-extent need too). CC-BY-4.0. | `recalled`, medium-high |
| **AAFC Annual Crop Inventory** | Canada, 2009–present | 30 m | open.canada.ca; GEE `AAFC/ACI` | `recalled`, high |
| **EuroCrops** | EU parcel-level crop type, harmonized taxonomy | vector parcels | `https://github.com/maja601/EuroCrops` | `recalled`, high |
| National parcel registries | France RPG, Germany (state InVeKoS), Netherlands BRP, Denmark, Slovenia, Spain SIGPAC | vector | national portals | `recalled` |
| **The paper itself** | everything | — | This will be your dominant source. Crop is stated in ~100% of agronomy papers. | — |

**Reality check:** for a literature-harvested corpus, crop type comes from the paper text at ~100% and gridded crop maps are nearly redundant. Use gridded maps only to (a) sanity-check geocoding, and (b) supply *surrounding-landscape* crop context.

## 3.2 Planting / harvest dates

| Source | Coverage | Access | Confidence |
|---|---|---|---|
| **Sacks, Deryng, Foley & Ramankutty (2010)**, *Global Ecol. Biogeogr.* 19, "Crop planting dates: an analysis of global patterns" | global, 5 arc-min, 19 crops, mean planting & harvest DOY + range | Historically at the U. Wisconsin SAGE / Nelson Institute data page. **Exact URL unknown — verify.** Also redistributed with several crop-model input packages. | `recalled`, high on the paper, low on the URL |
| **MIRCA2000 (Portmann, Siebert & Döll, 2010)**, *Global Biogeochem. Cycles* 24 | 5 arc-min, 26 crop classes × irrigated/rainfed, monthly growing areas + **cropping calendars incl. multi-cropping** | Uni Frankfurt / Uni Bonn hydrology group pages; widely mirrored | `recalled`, high on the dataset |
| **MIRCA-OS** | An open-source, updated MIRCA (I recall a *Scientific Data* paper c. 2024–25, ~2000–2015, with code) | **Verify — I am not confident of the exact citation.** | `recalled`, low |
| **GGCMI Phase 3 crop calendar (Jägermeyr et al.; Minoli et al. 2019)** | 0.5°, planting & maturity DOY, maize/rice/soy/wheat, **separately for rainfed and irrigated** | ISIMIP repository / Zenodo, PIK | `recalled`, medium-high — this is the cleanest *irrigated-specific* calendar I know of |
| **USDA NASS Crop Progress** | US, **state-level weekly % in each phenological stage**, 1979–present | QuickStats API: `https://quickstats.nass.usda.gov/api/api_GET/?key=<KEY>&source_desc=SURVEY&sector_desc=CROPS&statisticcat_desc=PROGRESS&commodity_desc=CORN&year=2020&state_alpha=NE&format=JSON`. Free key at `https://quickstats.nass.usda.gov/api`. | `recalled`, high — I am confident this API exists and works roughly this way |
| **ASAP / GEOGLAM Crop Monitor** | global, crop-calendar-by-region | JRC ASAP `https://agricultural-production-hotspots.ec.europa.eu` | `recalled`, medium |

Again: the **paper text** gives planting date for a large fraction of agronomy papers. Prioritize extracting it.

## 3.3 Time-varying LAI / fCover

| Product | Variable names | Res / cadence | Access | Confidence |
|---|---|---|---|---|
| **MODIS MCD15A3H v061** | `Lai_500m`, `Fpar_500m`, `LaiStdDev_500m`, `FparLai_QC`, `FparExtra_QC` | 500 m, 4-day | LP DAAC; GEE `MODIS/061/MCD15A3H`; AppEEARS point-sampling service (`https://appeears.earthdatacloud.nasa.gov`) is ideal for a point corpus | `recalled`, high |
| **MODIS MOD15A2H / MYD15A2H v061** | same | 500 m, 8-day | as above | `recalled`, high |
| **VIIRS VNP15A2H v002** | `Lai`, `Fpar` | 500 m, 8-day | LP DAAC | `recalled`, high |
| **Copernicus Global Land LAI / FAPAR / FCOVER 300 m V1.1** | `LAI`, `FAPAR`, `FCOVER` | 300 m, 10-day, 2014–present | `https://land.copernicus.eu/global/products/lai` (and `/fapar`, `/fcover`); also a 1 km V2 back to 1999 | `recalled`, high |
| **Sentinel-2 biophysical (SNAP Biophysical Processor / S2ToolBox; Weiss & Baret)** | LAI, FAPAR, FCOVER, CAB, CW | **10–20 m**, 5-day revisit | Run locally on L2A, or GEE community implementations | `recalled`, high |
| **HLS v2.0 (HLSL30 / HLSS30)** | surface reflectance → your own LAI/VI | **30 m, ~2–3 day** | LP DAAC / `https://hls.gsfc.nasa.gov`; CMR-STAC | `recalled`, high |

**Strong recommendation: 500 m MODIS LAI is the wrong scale for a 1-ha experimental plot.** A MODIS pixel over a research farm is a mixture of plots under different treatments — precisely the treatments whose contrast you are trying to learn. Use **Sentinel-2-derived LAI at 10–20 m (2016+)** or **HLS at 30 m (2013+)** as the primary, MODIS only as a pre-2016 fallback, and **always carry `lai_source` and `lai_pixel_size_m` as features** so the model can learn to distrust the coarse ones.

Better still for many rows: most agronomy papers **report measured LAI** at several dates. Digitize it. A measured LAI curve beats any satellite retrieval over a small plot.

## 3.4 Canopy height

Honest assessment: **GEDI L2A/L2B, ETH global canopy height (Lang et al. 2023, 10 m), Potapov et al. (30 m)** are all forest products with effectively zero skill on annual crops (sub-metre to 3 m canopies, below GEDI's noise floor). **Do not chase these.**

Instead use **FAO-56 Table 12**, which tabulates maximum plant height `h` by crop alongside Kc and Zr, and scale it by the phenology coordinate (linear from emergence to the start of mid-season, constant thereafter). `h` matters chiefly through the aerodynamic term in ET₀ adjustment and through `fc`; for a Kc-based framework its marginal value is small. **Low priority.**

## 3.5 Rooting depth

**Static maximum depth** — **FAO-56 Table 22** gives `Zr,max` (m) and depletion fraction `p` per crop (`recalled`, approximate ranges):

| Crop | Zr,max (m) | p |
|---|---|---|
| Maize (field) | 1.0–1.7 | 0.55 |
| Cotton | 1.0–1.7 | 0.65 |
| Wheat (winter) | 1.5–1.8 | 0.55 |
| Wheat (spring) | 1.0–1.5 | 0.55 |
| Soybean | 0.6–1.3 | 0.50 |
| Potato | 0.4–0.6 | 0.35 |
| Tomato | 0.7–1.5 | 0.40 |
| Alfalfa | 1.0–2.0 (to 3.0) | 0.55 |
| Rice | 0.5–1.0 | 0.20 |
| Sugarcane | 1.2–2.0 | 0.65 |
| Onion | 0.3–0.6 | 0.30 |

`p` is directly useful too: it sets the depletion threshold at which the stress coefficient `Ks` begins to reduce transpiration, which is exactly the nonlinearity that governs how fast deep layers dry.

**Time-varying root depth curve.** Two standard forms (`recalled`):
- **Linear**: `Zr(t) = Zr_init + (Zr_max − Zr_init) · min(1, DAP / DAP_to_full_cover)`, with `Zr_init ≈ 0.15–0.30 m`. Used in AquaCrop/CROPWAT-style models.
- **Borg & Grimes (1986)**, *Transactions of the ASAE* 29(1), "Depth development of roots with time: an empirical description" — sigmoidal:
  ```
  Zr(t) = Zr_max · [0.5 + 0.5 · sin(3.03 · (DAP/DTM) − 1.47)]
  ```
  `recalled`, good confidence on the form and the 3.03/1.47 constants, but verify.

Use Borg & Grimes; it is a one-liner and better-shaped than linear.

**Global rooting-depth datasets:**
- **Fan, Miguez-Macho, Jobbágy, Jackson & Otero-Casal (2017)**, *PNAS* 114(40), "Hydrologic regulation of plant rooting depth" — the key conceptual result for you: **rooting depth is set by water-table depth and the depth to which the wetting front penetrates**, not just by species. This is exactly the §4 interaction. Data availability in the paper's SI.
- **Schenk & Jackson (2002)**, *Ecol. Monogr.* 72, and **(2005)**, *Geoderma* — global root-profile compilation; archived at **ORNL DAAC** as "Global Distribution of Root Profiles in Terrestrial Ecosystems" (`https://daac.ornl.gov`). `recalled`, medium-high.
- Caveat: both are dominated by **natural vegetation**. For croplands FAO-56 Table 22 is more appropriate and more defensible.

## 3.6 A transferable phenology coordinate — concrete specification

Do **not** feed raw day-of-year. It is hemisphere-inverted, crop-inverted (winter wheat spans the new year), and latitude-confounded.

Emit **four** coordinates and let the model choose:

**(a) `f_thermal` — normalized thermal time [0, 1]. Primary.**
```
GDD_d = clip(( min(Tmax, Tupper) + max(Tmin, Tbase) )/2 − Tbase, 0, ∞)
GDD_cum(t) = Σ_{planting}^{t} GDD_d
f_thermal  = clip( GDD_cum(t) / GDD_req(crop, cultivar_group), 0, 1.5 )
```
Crop constants (`recalled`): maize Tbase 10 °C / Tupper 30 °C, GDD_req 1300–1800 °C·d; cotton Tbase 15.6 °C (the US "DD60" convention), GDD_req ~1400–1800; wheat Tbase 0 °C, GDD_req 1800–2400; rice Tbase 10 °C; soybean Tbase 10 °C. Allow >1.0 to represent post-maturity senescence. Under plastic mulch, soil-temperature elevation advances emergence — carry `mulch_type` alongside so the model can learn the offset.

**(b) `f_dap` = DAP / DTM.** Redundant with (a) but robust when Tbase is unknown.

**(c) Photoperiod and top-of-atmosphere radiation — hemisphere-safe replacements for DOY.**
Both are exact functions of latitude and DOY and are automatically correct in both hemispheres, unlike `sin(2π·DOY/365)`:
```
δ  = 0.409 · sin(2π·DOY/365 − 1.39)                      # solar declination, FAO-56 Eq. 24
ωs = arccos(−tan(φ)·tan(δ))                              # sunset hour angle, Eq. 25
N  = 24/π · ωs                                            # daylight hours, Eq. 34
Ra = (24·60/π)·Gsc·dr·[ωs·sin φ·sin δ + cos φ·cos δ·sin ωs]   # Eq. 21, Gsc = 0.0820 MJ m⁻² min⁻¹
```
`recalled`, high confidence — these are standard FAO-56 equations.

**(d) `f_root` = Zr(t)/Zr_max` from Borg & Grimes**, and the derived **`is_below_root_zone = (depth_cm/100 > Zr(t))`** boolean per row. That last one is quietly one of the most valuable features in the whole table: it tells the model whether the layer it is predicting is currently being actively extracted or is hydraulically decoupled from transpiration. It is cheap, it is available for nearly every row, and it is exactly the multi-depth structure the model must capture.

---

# 4. SHALLOW WATER TABLE AND CAPILLARY RISE

## 4.1 Why the gap statement is right

In the Nile Delta, lower Indus, Fergana Valley, parts of the San Joaquin, the North China Plain and the older Xinjiang districts, water tables sit at **1–3 m** under irrigation. At those depths, upward capillary flux supplies **1–4 mm/day**, i.e. **20–60% of peak crop ET**. A model without WTD cannot distinguish "wet at 60 cm because it was irrigated three days ago" from "wet at 60 cm because the water table is at 1.2 m and always will be". Those two states have opposite forecasts and opposite management implications, and conflating them is fatal to a sensor-replacement claim.

It is also the physical engine of secondary salinization — the mechanism the user explicitly cares about — and of waterlogging.

## 4.2 Water-table depth datasets

| Source | What | Res / coverage | Access | Confidence |
|---|---|---|---|---|
| **Fan, Li & Miguez-Macho (2013)**, *Science* 339(6122), 940–943, "Global patterns of groundwater table depth" | Simulated equilibrium WTD, the standard global reference | **30 arc-sec (~1 km)**, global | Distributed from a THREDDS server at Universidade de Santiago de Compostela (Miguez-Macho's group). **I recall a path of the form `http://thredds-gfnl.usc.es/thredds/catalog/GLOBALWTDFTP/` — treat as unverified.** Also widely mirrored; some versions on HydroShare/Zenodo. | `recalled`, high on the paper, **low on the URL** |
| **de Graaf, Sutanudjaja, van Beek & Bierkens (2015, 2017)** — global transient groundwater model coupled to PCR-GLOBWB | Simulated head / WTD, transient | **5 arc-min (~10 km)**, global, monthly | Utrecht Dept. Physical Geography / OPeNDAP; also **de Graaf et al. (2019)**, *Nature* 574, on pumping-induced streamflow depletion | `recalled`, medium |
| **IGRAC Global Groundwater Information System (GGIS)** and **GGMN** | Portal for national monitoring data; **GGMN** hosts actual well time series of depth-to-water | point wells, global but very patchy | `https://ggis.un-igrac.org` | `recalled`, high on the portal existing, medium on data density |
| **USGS NWIS groundwater levels** | Measured depth to water, ~1M+ US wells | point, US, 1900s–present | `https://waterservices.usgs.gov/nwis/gwlevels/?format=rdb&stateCd=ca&startDT=2010-01-01&endDT=2020-12-31`; daily-value service `https://waterservices.usgs.gov/nwis/dv/?parameterCd=72019`. **Parameter codes: `72019` = depth to water below land surface (ft); `62610` = groundwater level above NAVD88.** USGS is migrating to an OGC-API at `api.waterdata.usgs.gov` — check which is current. | `recalled`, **high** — this is the one I would bet on |
| **California DWR periodic groundwater levels** | Semi-annual + continuous; the San Joaquin/Tulare record | point, CA | `https://data.cnra.ca.gov/dataset/periodic-groundwater-level-measurements`; SGMA data viewer at `https://sgma.water.ca.gov/webgis/` | `recalled`, high |
| **India-WRIS / CGWB** | CGWB monitors ~15–20k wells **4×/year (Jan, May, Aug, Nov)** | point, India | `https://indiawris.gov.in` — has a data-download UI and some REST endpoints; **exact API paths unknown, verify.** Also the annual *Ground Water Year Book*. | `recalled`, high on existence, low on API |
| **Australia BoM National Groundwater Information System** | bore water levels | point, AU | `http://www.bom.gov.au/water/groundwater/` | `recalled`, medium-high |
| **Netherlands DINOloket** | dense piezometer network | point, NL | `https://www.dinoloket.nl` | `recalled`, high |
| **EEA WISE / national EU services** | Groundwater body level status | varies | `https://www.eea.europa.eu/data-and-maps` | `recalled`, medium |
| **Pakistan (SMO/WAPDA, Punjab Irrigation Dept piezometers)** | Indus Basin WTD, biannual (pre/post-monsoon) | point | **Not openly accessible.** Obtain WTD contour maps from the published literature (IWMI has extensive Indus WTD mapping) — digitize them. | `recalled`, high that it is closed |
| **Egypt (RIGW Nile Delta piezometers)** | Delta WTD | point | **Not openly accessible.** Literature maps only. | `recalled` |
| **China (MWR / China Geological Survey)** | North China Plain, Xinjiang monitoring | point | **Not openly accessible.** Literature and provincial water-resources bulletins. | `recalled` |
| **GRACE / GRACE-FO** | Total water storage **anomaly** | 0.5°–3°, monthly | JPL RL06 mascons via PO.DAAC; the **NASA/NDMC GRACE-FO drought indicators (groundwater & soil moisture percentile, 0.125°, weekly)** at `https://nasagrace.unl.edu` | `recalled`, high |

**Be blunt about GRACE.** It gives a ~300 km, monthly *storage anomaly percentile*. It cannot give absolute WTD, and at field scale it is nearly information-free. Include the NASA-GRACE 0.125° groundwater percentile as a slow-varying regional-depletion index if you like, but **do not represent it as water-table depth**. Its real value is as a trend covariate for multi-decade corpora (e.g., encoding that the North China Plain in 2015 is a different aquifer state from 1995).

**Recommended construction order:**
1. Paper text (many irrigation papers in shallow-WT districts state WTD — it is a design consideration for them). **Highest quality, use first.**
2. National well network, nearest-neighbour or IDW within a radius cap (say 10 km) with a distance feature.
3. Fan et al. 2013 1 km equilibrium WTD as a universal fallback.
4. Missingness indicator, always.

## 4.3 Encoding capillary rise

### (a) FAO-56 / Doorenbos tabular approach — the quick version

FAO-56 states that capillary rise is normally taken as **zero when the water table is more than about 1 m below the bottom of the root zone**, and must be estimated otherwise. FAO-24 (Doorenbos & Pruitt) and the FAO-56 annexes carry tables of capillary contribution (mm/day) as a function of WTD and soil type. `recalled`. Usable as a coarse lookup but too crude for an ML feature — the discretization throws away exactly the continuum you want.

### (b) Gardner (1958) analytical steady upward flux — the good closed form

**Gardner, W.R. (1958)**, *Soil Science* 85(4), "Some steady-state solutions of the unsaturated moisture flow equation with application to evaporation from a water table". With `K(h) = a / (h^n + b)`, the maximum steady upward flux from a water table at depth `d` is:

```
q_max = A · a / d^n         with   A = n · sin(π/n) / π
```
`recalled` — I am confident in the `q_max ∝ d^-n` scaling and reasonably confident in `A`; **verify the constant.**

The exponent `n` is texture-dependent: **n ≈ 1.5–2 for coarse sands, 3–4 for loams, 4+ for clays** (`recalled`). The physical consequence is the well-known non-monotonicity: **sands sustain the highest flux at very shallow WTD but lose capillary contact abruptly with depth; clays sustain lower but far more persistent flux to 2–3 m.** Loams are the worst case for salinization because they combine appreciable flux with appreciable depth reach.

### (c) The version I recommend you actually implement — free reuse of Rosetta

You already have Rosetta PTFs in the plan. Use them. Precompute, offline and once, a lookup table by solving the **steady-state Richards equation** for the maximum upward flux:

```
d = ∫_{h_surface}^{0}  dh / ( 1 + q / K(h) )
```
Solve for `q` given `d`, with `K(h)` from van Genuchten–Mualem using Rosetta-predicted (θr, θs, α, n, Ks) for the local texture/bulk density. Take `h_surface` as the air-dry or wilting-point head (−15 000 cm) for `q_max`, or the actual simulated head for the operational flux.

Tabulate `q_cap_max(texture_class, WTD)` at WTD = 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0 m for the 12 USDA texture classes, then interpolate. Order-of-magnitude expectations (`recalled`, verify by running it):

| WTD | Sand | Loam | Silt loam | Clay |
|---|---|---|---|---|
| 0.5 m | 5–12 mm/d | 8–15 | 8–15 | 3–6 |
| 1.0 m | 0.2–1 | 3–6 | 4–7 | 1.5–3 |
| 1.5 m | <0.1 | 1–2.5 | 1.5–3 | 1–2 |
| 2.0 m | ~0 | 0.4–1.0 | 0.6–1.5 | 0.6–1.2 |
| 3.0 m | ~0 | 0.1–0.3 | 0.15–0.4 | 0.3–0.6 |

This is also exactly the computation behind the "**critical water-table depth**" used in irrigation-district salinity management: **~1.5 m in Xinjiang, ~2.0–3.0 m in the Indus and the Nile Delta** (`recalled`).

### (d) The salinity coupling — this is the part that speaks to the user's thesis

Steady-state root-zone salt mass balance under capillary rise from saline groundwater:

```
salt_in  = I·EC_iw·k  +  q_cap·EC_gw·k        [mass per area per time]
salt_out = D·EC_dw·k                           (D = drainage below root zone)
```
with `k` a units constant (for `EC` in dS/m and depth in mm, TDS mg/L ≈ 640·EC gives mass directly).

When WTD is shallow, `q_cap · EC_gw` can exceed the irrigation salt input, and drainage `D` is suppressed (the drainable pore volume is gone), so **`salt_out → 0` and salt accumulates monotonically**. This is the classic rising-water-table → capillary-rise → evaporative-concentration → root-zone salinization cascade of the Indus, the Aral Basin and the Nile Delta. A rising water table is therefore a *joint* driver of moisture and salinity, which is exactly why it cannot be omitted from a project whose stated motivation is sensor sensitivity to salinity.

### (e) Features to construct

```
water_table_depth_m                float    -- best available
wtd_source                         enum{paper_text, well_nearest, well_idw,
                                         fan2013_1km, degraaf_5arcmin, none}
wtd_distance_to_well_km            float NULL
wtd_measurement_lag_days           int   NULL
wtd_seasonal_mean_m                float    -- climatology
wtd_seasonal_amplitude_m           float
wtd_anomaly_m                      float    -- value minus climatology
shallow_wt_flag                    bool     -- WTD < 2.5 m
wtd_minus_rootdepth_m              float    -- WTD − Zr(t); NEGATIVE means roots in the
                                            --   capillary fringe. High-value feature.
wtd_minus_sensor_depth_m           float    -- WTD − depth_cm/100, per row
capillary_rise_mm_day              float    -- Rosetta/Gardner lookup(texture, WTD)
cap_rise_frac_of_etc               float    -- capillary_rise_mm_day / ETc
gw_ec_ds_m                         float NULL
capillary_salt_load_kg_ha_day      float    -- capillary_rise_mm_day × gw_ec × 6.4
grace_gw_percentile                float NULL  -- regional depletion context only
```

`wtd_minus_sensor_depth_m` deserves emphasis: it is the single feature that tells the model whether the layer it is predicting is **above the capillary fringe, inside it, or below the water table (saturated)**. A sensor at 100 cm with the water table at 90 cm reads θs and will never dry — no amount of weather or irrigation data explains that, and without this feature the model will treat those rows as irreducible noise and inflate its error everywhere else.

---

# 5. MANAGEMENT AND SOIL STRUCTURE

## 5.1 Physical effects

(`recalled` throughout)

- **No-till vs. conventional, 0–10 cm**: NT bulk density typically **+0.05–0.12 g/cm³**, but with greater macropore *continuity*, so field-saturated Ks is often **equal or higher** despite higher BD. Volumetric θ at field capacity is usually **+0.01–0.03 m³/m³** under NT, driven mainly by the residue cover reducing evaporation rather than by the tillage itself.
- **Plough pan / traffic pan**: this is the big one for multi-depth work. A pan at **20–35 cm** with BD **1.6–1.85 g/cm³** and Ks reduced by **1–2 orders of magnitude** produces: perched water and a θ spike immediately above the pan; a sharp θ discontinuity across it; restricted rooting below it; and suppressed deep drainage. **A model using SoilGrids/POLARIS BD — neither of which resolves a pan — will systematically mis-predict the 20–40 cm layer in every intensively tilled, mechanized irrigated system.** Xinjiang (decades of rotary tillage under film) and the rice–wheat belt of Indian/Pakistani Punjab (puddling-induced hardpan under rice) are the worst cases, and both are heavily represented in the irrigated-soil-moisture literature.
- **Puddled rice** is a special case worth its own flag: deliberate destruction of structure to create a low-Ks plough sole, ponded surface, near-saturation 0–20 cm for months. Rice rows in your corpus are a different physical system and arguably should be modelled separately or given a hard indicator.

## 5.2 Datasets

| Source | Coverage | Access | Confidence |
|---|---|---|---|
| **Porwollik, Rolinski, Heinke & Müller** — global gridded crop-specific tillage data | I recall a *Scientific Data* / GMD paper (c. 2019) providing **5 arc-min global tillage-system shares** (roughly: conventional annual, traditional annual, reduced, no-till, rotational, traditional rotational) for ~2005, built as a GGCMI model input | PIK / Zenodo / MPG PURE | `recalled`, **medium** — confident such a product exists, less so of the exact citation |
| **Prestele, Hirsch, Davin, Seneviratne & Verburg (2018)**, *Global Change Biology* — "A spatially explicit representation of conservation agriculture for application in global change studies" | Global **5 arc-min conservation-agriculture / no-till extent**, with scenarios | Supplementary / Zenodo | `recalled`, medium-high |
| **Kassam, Friedrich & Derpsch** — periodic global conservation-agriculture area statistics | **country-level %**, updated every few years in *Int. J. Environ. Studies* | journal tables | `recalled`, high |
| **OpTIS (Operational Tillage Information System)** — CTIC / Regrow / TNC | **US Corn Belt + expanding**, field-to-county **tillage class and residue cover, annual, from Landsat/Sentinel** | `https://www.ctic.org` (OpTIS pages); Regrow. Aggregated county summaries have been released publicly; field-level is commercial. | `recalled`, medium-high |
| **CTIC National Crop Residue Management Survey** | **US county-level** tillage acres, historical (roughly 1989–2004 continuous) | CTIC | `recalled`, medium |
| **USDA NASS Census of Agriculture (2012/2017/2022)** | **US county-level acres** of no-till, conservation-till, conventional-till, cover crops | QuickStats API, same endpoint as §3.2; query `short_desc` containing `"NO-TILL"` / `"CONSERVATION TILLAGE"` under the PRACTICES domain | `recalled`, high |
| **USDA ARMS / Irrigation & Water Management Survey** | US **state-level** tillage and irrigation practice | NASS/ERS | `recalled`, medium |

## 5.3 Honest verdict

**Globally you can obtain a coarse (5 arc-min, ~2005, static) *probability* of no-till. You cannot obtain field-level tillage, and you cannot obtain plough-pan presence or depth anywhere, at any resolution.** For CONUS you get county-level shares plus OpTIS in the Corn Belt.

The corpus itself is a better source than any map: agronomy papers routinely state the tillage operation, and a meaningful minority report **measured bulk density by depth**, which is the actual quantity of interest and directly reveals a pan. **Prioritize extracting measured BD-by-depth profiles from the papers** over acquiring gridded tillage maps. A measured BD profile at three depths is worth more than every global tillage raster combined.

Schema:
```
tillage_system      enum{conventional_inversion, conventional_noninversion, reduced,
                         minimum, no_till, strip_till, ridge_till, puddled_rice,
                         deep_ripped_subsoiled, unknown}
tillage_depth_cm    float NULL
residue_cover_frac  float NULL
years_since_tillage_change  int NULL
bd_measured_g_cm3   float NULL   -- per depth layer, from the paper
bd_measured_depth_cm float NULL
pan_reported        bool
pan_depth_cm        float NULL
prob_notill_gridded float NULL   -- Prestele / Porwollik fallback
tillage_source      enum{paper_text, county_census, optis, gridded_global, unknown}
```

---

# 6. APPLIED-WATER QUALITY

## 6.1 Why it is a double-duty covariate

Applied-water EC matters **twice**, and the second reason is the one that bears directly on the user's premise:

1. **Physically** — salt accumulation lowers osmotic potential, reduces transpiration via the salinity stress coefficient, and alters the retention curve slightly, changing how fast the profile dries.
2. **As a measurement-bias term** — dielectric sensors read apparent permittivity, which is contaminated by bulk EC. **This is the exact problem the user named as their motivation.** So `EC` is not merely a physics covariate: it is a covariate on the *label-generating process*. It belongs in the model whether or not it improves the physical prediction.

**Corollary you should act on: `sensor_technology` must be a first-class field.** Salinity sensitivity is strongly technology-dependent (`recalled`):

| Technology | Salinity sensitivity |
|---|---|
| Gravimetric / oven-dry | none |
| Neutron probe | none |
| COSMOS / cosmic-ray neutron | none |
| TDR (~1 GHz, waveform) | low-moderate; bulk EC attenuates the waveform, biasing at EC_b > ~2–4 dS/m |
| TDT | low-moderate |
| Impedance / 100 MHz (e.g. ThetaProbe) | moderate |
| Capacitance / FDR at 70 MHz (many commercial probes) | **moderate-high** |
| Capacitance at <50 MHz (older probes) | **high** — can be uninterpretable above ~2 dS/m |
| GPR / active microwave | moderate |

Record `sensor_make_model`, `sensor_technology`, `sensor_frequency_MHz`, `calibration_type` (factory / soil-specific / gravimetric-validated), and `calibration_reported`. A soil-specific gravimetric calibration in a saline field is a far more trustworthy label than a factory default — and it should get a smaller σ. This is arguably a higher-value addition than half the geophysical covariates, because it goes to label quality, and no amount of covariate engineering repairs bad labels.

## 6.2 Water-source and EC sources

| Source | What | Access | Confidence |
|---|---|---|---|
| **Siebert et al. (2010)**, *HESS* 14, "Groundwater use for irrigation – a global inventory" | **5 arc-min global fractions of area irrigated from groundwater vs. surface water vs. non-conventional**, consistent with GMIA/AQUASTAT | Uni Bonn / Uni Frankfurt hydrology pages; FAO AQUASTAT GMIA at `https://www.fao.org/aquastat/` | `recalled`, **high on the dataset** — this is the solid, citable baseline |
| A recent downscaled/high-resolution global irrigation water-source product | The task prompt refers to one; I have **no reliable recall of its name or location**. **Unknown — verify.** Do not build on it until located. | — | — |
| **GRIPC (Salmon, Friedl, Frolking, Wisser & Douglas, 2015)**, *Int. J. Appl. Earth Obs. Geoinf.* | **500 m global irrigated / rainfed / paddy** map, c. 2005 | BU / published supplement | `recalled`, medium-high — note it classifies *type*, not *source* |
| **USGS Water Use (county, 5-yearly)** | US irrigation withdrawals split **groundwater vs. surface water** by county | `https://waterdata.usgs.gov/nwis/wu`; the Water Use data releases on ScienceBase | `recalled`, high |
| **USDA Irrigation & Water Management Survey (IWMS, formerly FRIS)** | US state-level water source, system type, energy, scheduling method | NASS | `recalled`, high |
| **USGS NWIS specific conductance** | **pcode `00095`**, µS/cm at 25 °C, surface water and groundwater | `https://waterservices.usgs.gov/nwis/iv/` and `/dv/` with `parameterCd=00095` | `recalled`, high |
| **Water Quality Portal (WQP)** | NWIS + EPA STORET + USDA merged; the best single US water-chemistry endpoint | `https://www.waterqualitydata.us/data/Result/search?characteristicName=Specific%20conductance&statecode=US%3A06&mimeType=csv` | `recalled`, medium-high on the exact query syntax; the portal definitely exists |
| **California GAMA** | CA groundwater quality, incl. EC/TDS | `https://gamagroundwater.waterboards.ca.gov` | `recalled`, high |
| **CGWB India Ground Water Year Book** | District-level groundwater EC | CGWB / India-WRIS | `recalled`, medium |
| **UNEP GEMStat** | Global surface/ground water chemistry, sparse | `https://gemstat.org` | `recalled`, medium |
| **GLORICH** | Global river chemistry compilation | PANGAEA | `recalled`, medium |
| **FAO-29 Rev. 1, Ayers & Westcot (1985)**, *Water Quality for Agriculture* | The classification framework, not a dataset | `https://www.fao.org/3/t0234e/t0234e00.htm` | `recalled`, medium-high on the URL |

## 6.3 FAO-29 classification and the leaching equations

**FAO-29 Table 1 salinity restriction on use** (`recalled`):
| Restriction | EC_w (dS/m) | TDS (mg/L) |
|---|---|---|
| None | < 0.7 | < 450 |
| Slight to moderate | 0.7 – 3.0 | 450 – 2000 |
| Severe | > 3.0 | > 2000 |

(Plus the SAR × EC_w infiltration-hazard table — low EC with high SAR causes dispersion and **reduced infiltration**, which is itself a soil-moisture-relevant effect independent of salinity.)

**Leaching requirement** (Ayers & Westcot / Rhoades, `recalled`):
```
LR = EC_w / (5·EC_e* − EC_w)                surface and sprinkler, conventional frequency
LR = EC_w / (2·max EC_e)                    high-frequency drip / SDI
AW = ET_c / (1 − LR)                        applied water needed
LF = D_drainage / D_applied                 actual leaching fraction
```
where `EC_e*` is the crop's tolerance threshold ECe for the acceptable yield level (Maas & Hoffman threshold–slope tables; e.g. cotton threshold ~7.7 dS/m, maize ~1.7, wheat ~6.0, bean ~1.0 — `recalled`, approximate).

**Steady-state root-zone concentration factor** `F_c` (ECe_avg ≈ F_c · EC_w, for a 40-30-20-10 water-uptake distribution), from the Ayers & Westcot table (`recalled`, approximate):

| LF | 0.05 | 0.10 | 0.15 | 0.20 | 0.30 | 0.40 | 0.50 |
|---|---|---|---|---|---|---|---|
| F_c | ~3.2 | ~2.1 | ~1.7 | ~1.5 | ~1.3 | ~1.2 | ~1.1 |

**Making it a usable feature.** LF is almost never reported. Estimate it:
```
LF_est = max(0, (I + P − ET_c − ΔS)) / (I + P)
```
using the paper's reported irrigation `I`, gridded `P`, and `ET_c` from your FAO-56 chain — you already have all three in the plan. Then:
```
ece_rootzone_est = F_c(LF_est) · ec_iw
```
This is crude — it assumes steady state, which a single season is not — but it is a physically-ordered feature, which is what a gradient-boosted or neural model needs. Carry `ece_estimation_method` and treat it as low-confidence.

**Preferred whenever available: the paper's own measured ECe or EC_1:5.** Many Xinjiang, Indian and Egyptian salinity papers report a measured salinity profile alongside the moisture profile. That is a direct measurement and should override the estimate. Add `ece_measured_ds_m`, `ec_1to5_ds_m`, `ec_bulk_ds_m`, `salinity_depth_cm`, `salinity_method` to the schema — and note that harvesting these gives you a **second target variable**, which opens a multi-task model (predict θ and ECe jointly). Given the user's stated salinity motivation, that is probably the highest-leverage structural idea in this whole document.

Schema:
```
water_source          enum{groundwater, surface_canal, surface_river, reservoir,
                           reclaimed_wastewater, drainage_reuse, desalinated,
                           conjunctive, rainwater, unknown}
gw_fraction           float NULL      -- Siebert 5 arc-min fallback
ec_iw_ds_m            float NULL
ec_iw_source          enum{paper, nwis_wqp, national_db, regional_prior, none}
sar_iw                float NULL
leaching_fraction_est float
ece_rootzone_est_ds_m float
ece_measured_ds_m     float NULL
sensor_technology     enum{...}
sensor_frequency_mhz  float NULL
calibration_type      enum{factory, soil_specific, gravimetric_validated, unknown}
```

---

# 7. CONSOLIDATED COVARIATE TABLE AND RANKING

## 7.1 Ranking by expected contribution to **zero-shot** multi-depth skill

The critical framing: the user's goal is **replacing sensors**, which means predicting at sites with **no local sensor history**. So rank by value *at a new site*, not by in-sample R². A per-series latent will absorb enormous in-sample variance and contribute **exactly zero** at a new site. Do not let it flatter your metrics.

| # | Covariate block | Zero-shot value | Expected missingness in a literature corpus | Verdict |
|---|---|---|---|---|
| 1 | **Irrigation event series** (date + depth + method) | **Very high** | 30–60% partial (many papers give seasonal totals only) | Not in my brief, but it is the #1 gap. Nothing else matters as much. Extract date-level events wherever possible; where only seasonal totals exist, disaggregate with the scheduling rule the paper states and flag it. |
| 2 | **Irrigation method + wetting geometry** (§1) | **Very high** | method ~5% missing; geometry 60–85% missing | Chase hard. Method alone is a large win and nearly always available. Full geometry is a smaller additional win on fewer rows. |
| 3 | **`wtd_minus_sensor_depth_m` / capillary rise** (§4) | **High where shallow, zero where deep** | 60–80% (Fan 2013 fills 100% at low quality) | Chase. Cheap to add via Fan 2013 + USGS/India-WRIS. Highest marginal value in the Nile Delta / Indus / San Joaquin / NCP strata the user cares about. |
| 4 | **Phenology coordinate + `is_below_root_zone`** (§3.5–3.6) | **High** | planting date 20–40% missing; the derived features are 100% computable once you have it | Chase. Nearly free once planting date is extracted; `is_below_root_zone` is one line of code and directly encodes the multi-depth structure. |
| 5 | **Plastic mulch** (§2) | **Decisive in Xinjiang/Gansu; irrelevant elsewhere** | 20–40% missing globally; near 0% in the Chinese corpus | Chase via paper text + regional priors. **Do not block on locating a gridded product.** |
| 6 | **Time-varying LAI / fCover at 10–30 m** | Medium-high | satellite fills 100% post-2016; pre-2013 only 500 m MODIS | Chase Sentinel-2/HLS. Skip MODIS-only rows or heavily downweight them. |
| 7 | **Sensor technology + calibration + EC** (§6) | **High — but as a label-quality term, not physics** | technology ~20% missing; EC 70–85% missing | Chase the sensor metadata hard (it is in the Methods section of nearly every paper and is cheap to extract). Chase EC opportunistically. |
| 8 | **Measured bulk density by depth from papers** (§5) | Medium-high | 60–75% missing | Chase — better than any gridded BD product where present. |
| 9 | **Measured ECe / salinity profile from papers** | Medium as a covariate; **high as a second target** | 80–90% missing | Chase. Opens the multi-task formulation. |
| 10 | Straw/residue mulch | Medium-low | 40% missing | Extract if cheap. |
| 11 | Applied-water source (Siebert gridded) | Low-medium | 0% (gridded fills all) | Add; it is one raster lookup. |
| 12 | Tillage system from paper text | Low-medium | 40–60% missing | Extract if cheap; do not invest in it. |
| 13 | **Gridded global tillage / no-till maps** (Prestele, Porwollik) | **Low** — 5 arc-min, static, ~2005 | 0% (fills all, at near-zero information) | **Not worth chasing.** A 10 km probability-of-no-till is essentially a country dummy. |
| 14 | OpTIS | Low, and CONUS-Corn-Belt only | — | **Not worth chasing** unless the corpus turns out to be Corn-Belt-heavy. |
| 15 | **Spaceborne canopy height (GEDI, ETH, Potapov)** | **≈ Zero for annual crops** | — | **Do not chase.** Use FAO-56 Table 12 heights. |
| 16 | **GRACE/GRACE-FO as a WTD proxy** | **≈ Zero at field scale** | — | **Do not chase as WTD.** Optionally include the 0.125 ° groundwater percentile as a decadal regional-state index only. |
| 17 | Plough-pan presence | Would be high — **but unobtainable** | ~95% | Unobtainable. Let the per-series latent absorb it in-domain; accept the error out-of-domain and say so in the paper. |
| 18 | Per-series latent embedding | **Zero at a new site, by construction** | — | Include for fit and for diagnosis, but **never report a headline number that uses it.** |

## 7.2 Missing-data treatment — a single consistent policy

1. **Never mean-impute silently.** For every covariate `X`, carry `X_missing` (boolean) and `X_source` (categorical). Tree ensembles (LightGBM/XGBoost) handle NaN natively with learned default directions — use that rather than imputing. Neural nets: impute to a fixed sentinel *plus* the indicator, or use a learned per-feature "missing" embedding.

2. **Physics-informed imputation with a flag beats statistical imputation.** `capillary_rise_mm_day` from Fan-2013 WTD + Rosetta is a defensible default; the mean of the column is not.

3. **Train with random feature masking.** Randomly drop 10–30% of the optional covariates per training sample, at rates matched to their real deployment missingness. This is the only way the model is calibrated when it meets a new site that has texture and weather but no mulch flag and no WTD. Without it, a model trained on complete rows degrades unpredictably.

4. **Hierarchical fallbacks are features, not implementation detail.** `wtd_source ∈ {paper, well_10km, well_50km, fan2013}` is itself predictive of error magnitude — feed it to the σ head.

5. **Evaluate under deployment missingness.** Build an explicit "sensor-replacement scenario" test set: paper-level holdout, embedding zeroed, all paper-text-only covariates (geometry, tillage, measured BD, measured EC) masked out, leaving only what is obtainable from public rasters and APIs at an arbitrary field. **That number is the project's real headline result.** Everything above it is diagnostic.

## 7.3 Three things I would change about the plan beyond the stated gap

- **Irrigation events, not irrigation extent.** The plan has irrigation *extent maps*. The model needs irrigation *events*: date and applied depth. Extent maps tell you a pixel is irrigated; they cannot tell you why θ jumped 0.15 on 12 July. Without event-level forcing, the model must infer irrigation from its consequences, which is circular when the consequence is the target. If events are unavailable for most rows, be explicit that the model is diagnostic (given θ history, fill gaps) rather than prognostic (predict θ with no sensor) — those are very different products, and only the second supports the sensor-replacement claim.

- **Sensor metadata is a first-class block.** It is cheap to extract, it is in every Methods section, and it governs label quality — which no covariate can repair. Currently absent from the plan entirely.

- **Model salinity jointly.** Given the user's motivation, and given that a meaningful subset of irrigated-field papers report both a θ profile and an ECe profile, a multi-task head (θ and ECe) is well-supported by the corpus and directly addresses the thesis that sensors are unreliable in saline soils. This is likely the difference between "another soil-moisture ML paper" and the contribution the user is describing.

## 7.4 Where I am least reliable

Ranked by how much I would want verified before a line of code is written:

1. **Every URL in this document.** Zero were checked. The ones I would bet on: `waterservices.usgs.gov/nwis/gwlevels` with pcode 72019; `quickstats.nass.usda.gov/api`; `nassgeodata.gmu.edu/CropScape/`; `land.copernicus.eu/global/products/lai`; `ggis.un-igrac.org`; GEE asset IDs `MODIS/061/MCD15A3H`, `USDA/NASS/CDL`, `AAFC/ACI`. The ones I would **not**: the Fan 2013 THREDDS path; anything for plastic-mulch mapping; the India-WRIS API paths; the "downscaled irrigation water source" dataset (which I could not identify at all).
2. **Numeric coefficients**: Schwartzman & Zur exponents; the Gardner `A` constant; Borg & Grimes 3.03/1.47; the F_c(LF) table; the CU↔DU conversion constants 0.63/1.59. The normal-distribution derivations in §1.3 (0.7979, 1.2711) I derived here and am confident in.
3. **My σ_θ prior table in §1.7** — that is my construction, not a citation. Re-estimate it from the multi-position papers in your own corpus; that re-estimation is itself publishable.
4. **The "fraction of papers reporting position" estimates** — a prior only. Measure it.

**Recommendation to the caller:** re-run this task in a session with WebSearch budget, targeting specifically (a) the Fan et al. 2013 WTD download location, (b) global and Chinese plastic-mulch/greenhouse products, (c) the downscaled irrigation-water-source dataset, and (d) the Porwollik gridded tillage citation. Those four are the only items where my recall is weak enough that the plan could stall on them. Everything else here is implementable as written, subject to routine URL verification.

**Sources:** none — no web search executed (budget exhausted at 200/200 before this agent's first call). All content above is from trained knowledge and is labelled `recalled`.