<!--
Compiled from a research sweep, not written by hand. Preserved verbatim because
it is reference material the implementation draws on rather than prose meant to
be read start to finish.

CONFIDENCE: the sweep's web-search budget was exhausted before these sections
ran, so everything in them is recalled from model knowledge and NONE of it was
corroborated by a search. Every URL and every accuracy figure must be verified
before it is relied on. Nothing here is legal advice.
-->

**METHODOLOGICAL CAVEAT — READ FIRST:** This session's WebSearch budget (200/200 calls) was already exhausted by prior subagents before I issued a single query. Both of my search attempts returned a budget-exhausted notice. **Every factual claim below is `recalled` from training, not `confirmed` by search.** I have marked confidence inline and flagged the items that must be verified against primary sources before they go into a proposal or a manuscript. No sources list is possible because no search returned results.

---

# PROJECT CHARTER: ML Simulation of Multi-Depth Soil Moisture in Irrigated Fields

## 0. The reframe that should happen before anything else

The stated goal — "replace or minimise soil moisture sensors" — is not falsifiable as written, and as written it is probably false. The defensible version, which is *stronger* and sits directly on the author's decade of expertise, is:

> **Replace *dielectric* soil moisture sensors in the soils where dielectric sensors are unreliable — high-activity clays and saline soils — using static soil attributes, irrigation forcing, remote sensing, and a handful of gravimetric calibration samples.**

This works rhetorically and physically because gravimetric sampling *does not fail* in clay or saline soils; it is the reference method and is immune to permittivity and bulk-EC artifacts. So "4 auger samples + a model" is exactly the right substitute for "a capacitance probe that over-reads by 0.10 m³/m³ in a saline vertisol." Everything below is built on that reframe.

---

## 1. OPERATIONAL MODES AND INPUT CONTRACTS

Three products, three different feasible accuracies. The leakage risk differs radically between them, which is why they must be separated in code, not just in prose.

### Product A — SENSOR REPLACEMENT (no in-situ θ, ever)

**Feature contract (what exists at prediction time at a never-instrumented field):**

| Group | Variables | Source (recalled) |
|---|---|---|
| Static soil, per layer | sand/silt/clay %, BD, SOC, coarse fragments, CEC, pH, ECe or EC₁:₅, CaCO₃ | measured where available; else POLARIS 30 m (CONUS, includes θ₃₃/θ₁₅₀₀), SoilGrids 250 m v2 (global) |
| Derived hydraulic | θr, θs, α, n, Ksat, θ_fc, θ_wp, TAW | Rosetta3 PTF (`rosetta-soil` PyPI, USDA-ARS) |
| Clay activity proxy | CEC/clay ratio (>0.5 cmol kg⁻¹ per % clay → high-activity/smectitic) | derived |
| Terrain | elevation, slope, aspect, TWI, curvature, dist-to-drainage | Copernicus DEM 30 m / SRTM |
| Weather forcing | P, ET₀ (FAO-56 PM), Tmax/Tmin, RH, u₂, Rs, VPD, hourly or daily | GEE `ECMWF/ERA5_LAND/HOURLY`; `IDAHO_EPSCOR/GRIDMET` for CONUS (ET₀ pre-computed); AgERA5 |
| Antecedent forcing | Σ(P−ET₀) at 3/7/14/30/60/90 d; API with decay; Σ irrigation | derived |
| **Irrigation forcing** | date + depth (mm); else method + system capacity + scheduling rule; else inferred | records; else OpenET residual, LANID/IrrMapper/MIrAD |
| Crop/canopy | NDVI, EVI, LAI, fCover, crop type, green-up date, Kc curve | Sentinel-2 10–20 m 5-day; MODIS MCD15A3H; USDA CDL |
| Surface state RS | S1 GRD IW σ⁰ VV/VH (10 m, 6–12 d), SMAP L3 9 km, SMAP L4 RZSM 9 km 0–100 cm, LST (Landsat/ECOSTRESS), OPTRAM |  |
| Structural | depth of prediction layer (continuous feature → one model, all depths), DOY sin/cos |  |

**Legitimate use of lagged θ: none.** Not the same site, not another depth in the same profile, not a neighbouring station in the same field, not a site-mean, not a site-normalised anomaly, not a target-encoded site ID.

**Illegitimate uses that are common in the published literature and will be caught by a reviewer:**
- θ at 10 cm used to predict θ at 30 cm at the same timestamp (this is the single most common leak in "multi-depth ML" papers and it inflates skill enormously).
- Random k-fold on rows. This gives ubRMSE ≈ 0.015–0.02 m³/m³ that collapses to 0.04–0.06 under leave-site-out. If you see 0.015, you have leaked.
- Any normalisation statistic (mean, σ, min-max) computed over the full record including the test fold.

**Realistic accuracy, leave-site-out, irrigated sites** *(recalled; my estimate from the pattern of ISMN-LSTM and SoMo.ml-class results, needs verification)*: ubRMSE 0.035–0.055 at 5–10 cm; 0.030–0.050 at 20–40 cm; 0.025–0.045 below 60 cm. **Per-site bias 0.03–0.08 m³/m³**, because θs and θr at an unseen site are unknown. Anomaly correlation at a new site typically 0.3–0.6.

**Question A answers:** "What is the plausible moisture climatology and event response of a field I have never instrumented?" Good for regional mapping, crop-model forcing, planning. **Not good enough to trigger an irrigation on a specific day in a specific field.**

### Product B — SENSOR REDUCTION (A + 2–6 calibration observations per site-season)

**Additional inputs:** 2–6 gravimetric samples with paired bulk density, per depth, per season; OR one season of a single shallow sensor. Sampling design matters more than count: one at 24–48 h post-irrigation (near field capacity), one at the dry end just before the next irrigation, one mid-range, per depth.

**Adaptation mechanisms, in increasing order of complexity — use them in this order:**
1. **Bias correction / CDF matching.** Most of A's error is site bias; the samples fix it. ubRMSE unchanged, total RMSE drops hard. Do this first; it is defensible and nearly free.
2. **Rescaling to site-specific θ_fc, θ_wp** estimated from the samples plus the drydown envelope.
3. **Per-site random effect / learned static embedding** partially observed from the samples (EA-LSTM's static embedding is the natural hook).
4. **Sequential update** — treat the model as the process, samples as observations, Kalman/EnKF update of the state.

**Realistic accuracy:** total RMSE 0.025–0.040, ubRMSE 0.025–0.035. **Hard floor:** gravimetric→volumetric conversion needs BD; a BD error of 0.05 g cm⁻³ on 1.35 is ~4% relative ≈ **0.010 m³/m³ at θ=0.25**. You cannot beat your own reference. Say so in the paper.

**Question B answers:** "How much water is in this profile right now, to within a few mm, without a permanent sensor?"

### Product C — FORECAST / SCHEDULING AID (A + observed θ up to t → t+1…t+7)

**Additional inputs:** observed θ history (any source), forecast weather (GFS/ECMWF/NBM), a *planned* irrigation scenario as a counterfactual input.

Lagged θ is fully legitimate here, but only strictly ≤ t, and the forcing must be *forecast* forcing, not reanalysis — training on ERA5 and deploying on GFS is a silent train/serve skew that will cost you 20–30% of the apparent skill.

**Realistic accuracy** *(recalled)*: day+1 RMSE 0.010–0.020; day+7 0.020–0.035. **This is the easy problem — persistence alone is strong.** Any C paper that does not report skill score against (i) persistence and (ii) an FAO-56 dual-Kc water balance is not saying anything.

**Question C answers:** "Should I irrigate in the next three days, and how much?"

### Recommended honest primary deliverable: **B**, with A as the ablation floor and C as a secondary

Reasons, in order of force:
1. **B is the only one where a fair head-to-head against a sensor is possible.** Model and sensor are both estimating the same quantity against the same gravimetric truth, with the same calibration effort. A vs sensor is apples-to-oranges in the model's favour; site-calibrated-sensor vs A is apples-to-oranges against it.
2. **The motivation demands it.** Sensors fail in clay/saline soils *because of the dielectric measurement*. Gravimetric sampling does not. B substitutes a robust measurement for a fragile one.
3. **B is adoptable.** Growers will pull four cores a season. They will not trust a zero-input model, and they are right not to.
4. **A is probably not beatable against the right baseline.** If A cannot beat a calibrated FAO-56 water balance driven by the same irrigation records, the ML has added nothing. Run that test in month 5, not month 15.

---

## 2. THE ACCURACY TARGET — WHAT MUST BE BEATEN

**All numbers in this section are `recalled` and must be re-verified against current datasheets and the primary calibration literature before publication.** This is precisely the section where a wrong recalled number is dangerous, so treat the whole table as a to-verify list.

### (a) Sensor accuracy, normal soils

| Sensor | Freq. | Factory/generic calibration | Soil-specific calibration | Notes |
|---|---|---|---|---|
| Neutron probe (CPN 503DR, Troxler) | — | n/a (always site-calibrated) | **±0.005–0.010** | Best field method. Responds to H, so needs correction for OM, lattice H, and neutron absorbers (B, Cd, Cl). **Insensitive to EC and to bound water.** Dying for regulatory reasons, not accuracy. |
| Gravimetric + core BD | — | — | **±0.010–0.020** | Reference. Error dominated by BD and spatial variability. |
| Campbell TDR310S/TDR315 | ~1 GHz eff. | ±0.025 (Topp) | **±0.005–0.010** | True waveform; you can see the failure. |
| Delta-T ML3 ThetaProbe | 100 MHz | ±0.05 | ±0.01 | |
| Delta-T PR2 profile probe | 100 MHz | ±0.04 | ±0.01–0.02 | Access tube — **installation air gaps dominate**. |
| METER TEROS 12 | 70 MHz | ±0.03 | ±0.01–0.02 | EC output; datasheet EC range ~0–20 dS/m bulk (verify). |
| METER EC-5 | 70 MHz | ±0.03 | ±0.02 | No EC output → no way to diagnose salinity error. |
| Campbell CS655/CS650 | ~175 MHz | ±0.03 **conditional** | ±0.01–0.02 | Datasheet caveats explicitly for bulk EC > ~8 dS/m and clay > ~30% (verify exact thresholds). |
| Sentek Drill & Drop / EnviroSCAN | capacitance | ~±0.03 claimed | needs site cal | Slim profile installed in a slurry/tube — installation is the dominant error term in practice. |
| AquaSpy | capacitance | **no credible absolute m³/m³ spec** | — | Treat output as a **relative index**, not VWC. Do not use as reference truth. |
| CRNS/COSMOS | — | ±0.01–0.03 | | ~200 m footprint, 12–70 cm variable depth. Different support volume — not a profile. |

### (b) Degradation in high-clay and saline soils — the whole premise

**Bound water (high-activity/smectitic clays)** *(recalled)*: water adsorbed on clay surfaces is rotationally immobilised and has an effective permittivity near 4–6 rather than ~80. Topp's equation was calibrated on mineral soils with roughly <30% clay, so in vertisols and montmorillonitic soils it **under-predicts θ by 0.05–0.10 m³/m³**, with reports exceeding 0.10 in strongly smectitic soils.

**Frequency dependence — and a sign flip that matters:** at low frequency (<100 MHz capacitance/FDR) Maxwell–Wagner interfacial polarisation and the clay double layer *inflate* apparent permittivity, so capacitance probes in clay typically **over**-read; TDR at effective ~0.5–1 GHz is dominated by bound water and **under**-reads. **The sign of the clay error depends on the technology.** This is a genuinely useful point for the error-budget paper and is under-appreciated in the agronomic literature.

**Salinity** *(recalled)*:
- TDR: bulk EC increases the imaginary permittivity and attenuates the waveform. Above roughly 2–4 dS/m bulk the second reflection gets hard to pick with standard rod lengths; above ~5–8 dS/m many probes fail to return an interpretable waveform. Error before outright failure: 0.02–0.05.
- Capacitance/FDR at 70–100 MHz: apparent permittivity rises with EC → **over-prediction of 0.05–0.15 m³/m³ at bulk EC 4–8 dS/m**. The diagnostic signature is physically impossible apparent VWC (>0.60) in a soil whose θs is 0.45.
- Temperature sensitivity worsens in clay/saline soils: 0.001–0.005 m³/m³ °C⁻¹ uncorrected → diurnal artifacts of 0.02–0.05, which can exceed the actual daily drying signal.

**Consolidated sensor baseline in a saline clay, uncalibrated: RMSE 0.06–0.12 m³/m³, bias-dominated, with episodic outright failure.** With a soil-specific calibration done in that soil at that salinity: back to 0.02–0.03 — **but that calibration requires the same gravimetric campaign Product B uses**, and it drifts as soil salinity changes seasonally under saline irrigation water. *That drift is where the model genuinely wins, because the model takes EC as an input rather than being confounded by it.* Make this the central argument.

### (c) Best published ML benchmarks *(all recalled — verify citations and numbers)*

- **SoMo.ml** (Sungmin O & Orth, *Sci. Data* 2021): global LSTM, 0.25°, daily, three layers (0–10, 10–30, 30–50 cm), 2000–2019, trained on ISMN. Median correlation against withheld stations ≈ 0.6–0.7. It is a model-derived product, not a validated point product.
- **Field-scale multi-depth ML, western/midwestern US (~2022)**: I recall RMSE in the 0.03–0.05 range. **I cannot reconstruct the exact citation with confidence — verify before citing.**
- **ERA5-Land + SMAP fusion (ESSD-class products)**: ubRMSE ≈ 0.03–0.05 against ISMN.
- **1 km China products (SMAP downscaling family)**: ubRMSE ≈ 0.03–0.04, surface.

### (d) The 0.04 benchmark

SMAP's mission requirement is **ubRMSE ≤ 0.04 m³/m³** for the top 5 cm, excluding densely vegetated areas (VWC > 5 kg m⁻²); L2/L3 routinely achieve ~0.038–0.045 at core validation sites *(recalled)*. **This is surface-only, 5 cm, at 9–36 km.** Importing it as a root-zone field-scale target is not apples to apples and a good reviewer will say so.

### Apples-to-apples warnings — state these explicitly in the methods

1. **ubRMSE removes bias. Sensor error in clay/saline is mostly bias.** Comparing model ubRMSE to sensor total RMSE flatters the model. Report both; make **total RMSE against gravimetric truth** the headline.
2. Satellite ubRMSE figures are validated *against sensor networks*, which in clay/saline soils are themselves wrong. Those validation numbers are unreliable in both directions in exactly the soils this project targets.
3. Support volume differs by orders of magnitude: TDR rods ≈ cm³; capacitance ≈ 5–10 cm sphere; neutron probe ≈ 15–30 cm sphere; CRNS ≈ 200 m; SMAP ≈ 9–36 km. "Field mean at depth z" and "point value at the probe" are different quantities.
4. Scale mismatch inflates apparent model error against point sensors and deflates it against footprint averages.

### THE FALSIFIABLE SUCCESS CRITERION (commit to this in writing, in the pre-registration)

> **Primary.** On held-out irrigated sites with clay ≥ 35% and/or ECe ≥ 4 dS/m (bulk EC ≥ 2 dS/m), evaluated against **gravimetric + BD reference samples** — not against other sensors — **Product B achieves total RMSE ≤ 0.035 m³/m³ and |bias| ≤ 0.015 m³/m³ at each of ~10, ~30 and ~60 cm, while a factory-calibrated dielectric sensor in those same soils achieves RMSE ≥ 0.05 m³/m³.**
>
> **Falsified if** model RMSE exceeds the uncalibrated-sensor RMSE in that soil class, **or** exceeds 0.045 m³/m³ absolutely.

**Secondary gates:**
- Product A: leave-site-out ubRMSE ≤ 0.045 at all depths; KGE ≥ 0.5; anomaly *r* ≥ 0.5.
- Product C: ≥ 25% RMSE reduction vs persistence at day+3, ≥ 15% at day+7, ≥ 10% vs FAO-56 water balance.

**Mandatory baseline suite reported alongside every result** — a model that doesn't beat these is not publishable:
(i) depth-wise climatology; (ii) site-mean; (iii) Rosetta θ_fc/θ_wp interpolation; (iv) **FAO-56 dual-Kc water balance with the actual irrigation records** ← the one that matters; (v) ERA5-Land layer-matched; (vi) SMAP L4 RZSM.

---

## 3. DECISION-RELEVANT EVALUATION

Pooled RMSE is not the objective function of an irrigator. Five metric families, all computed on **root-zone storage**, not on single-depth θ.

Define: `S(t) = Σ_layers θ_i·Δz_i` over 0→Zr(t), with Zr from crop stage; `S_MAD = S_fc − MAD·(S_fc − S_wp)`.

### 3.1 MAD threshold-crossing date error
For each drydown cycle, `D_obs` = first day S crosses below S_MAD; `D_pred` likewise. **Metric: ΔD = D_pred − D_obs, in days.**
- Report median |ΔD|, and the fraction of cycles with |ΔD| ≤ 1 day.
- **Target: median |ΔD| ≤ 1 day; ≥ 70% of cycles within ±1 day; ≤ 10% of cycles with ΔD ≥ +3 (late = crop stress) and ≤ 10% with ΔD ≤ −3 (early = wasted water + nitrate leaching).**
- **Report the sign separately. Never pool.** Late and early errors have a cost ratio near 20:1 (§3.5).

### 3.2 Binary "irrigate today"
`y(t) = 1 if S(t) < S_MAD`. Confusion matrix over site-days, but **cluster bootstrap by drydown cycle** for CIs — site-days are massively autocorrelated and naive CIs will be ~5× too narrow.
- Report POD, FAR, CSI, F1 at the operating point, plus the full ROC obtained by sweeping the model's S threshold so a user can pick a conservative point.
- **Target: POD ≥ 0.85 at FAR ≤ 0.20 for 50% MAD.**
- Also report a cost-weighted score with the cost ratio exposed as a parameter (default 5:1, missed:spurious), so readers can substitute their own.

### 3.3 Seasonal cumulative storage
- Error in seasonal ΔS (mm) planting→harvest. **Target |error| ≤ 15 mm, or ≤ 5% of seasonal applied irrigation.**
- Error in profile available water PAW(t) = S(t) − S_wp. **Target RMSE ≤ 12 mm over 0–60 cm** (see §3.5 — this is the same number as 0.02 m³/m³, deliberately).
- Residual-implied drainage + ET as a physical sanity check.

### 3.4 Drydown-specific skill — the only moment that matters
Segment: event start = local max of S following a wetting ≥ 10 mm; end = next wetting ≥ 5 mm, or dS/dt > 0 for 2 consecutive days; require ≥ 5 days.
Per event: (i) within-event RMSE; (ii) error in the decay constant τ from `S(t) = S∞ + (S₀−S∞)e^{−t/τ}`, **target |Δτ|/τ ≤ 25%**; (iii) error in the day 50% depletion is reached; (iv) error in total depletion depth (mm).
**Report the ratio `drydown-RMSE / overall-RMSE`. If > 1.3, the model is coasting on wet-period persistence and is useless for scheduling.** This one ratio will catch more bad models than any other number in the paper.

### 3.5 Agronomic framing — what 0.02 m³/m³ actually costs

| Management depth | 0.02 m³/m³ equals | In context |
|---|---|---|
| 0–60 cm | **12 mm** ≈ 0.47 in ≈ 120 m³/ha ≈ 12,800 gal/ac | ~50% of one centre-pivot pass (20–25 mm); ~15% of a furrow set (75–100 mm) |
| 0–100 cm | **20 mm** | a **full** pivot pass |

At peak crop ET of 6–9 mm/day (High Plains / desert Southwest summer), **12 mm ≈ 1.5–2 days of demand.** So:

> **A 0.02 m³/m³ root-zone error = ~1.5–2 days of scheduling error at peak demand. A 0.04 error = 3–4 days = a stressed crop or a wasted pass.**

That sentence belongs in the abstract; it is the entire justification for the numeric target. It also implies the tolerance should be specified **in mm of storage over the management depth, not in m³/m³**, and should tighten as rooting depth increases.

Economics *(order-of-magnitude, recalled)*: pumping + water ≈ $0.05–0.15/m³ in the High Plains → 120 m³/ha ≈ **$6–18/ha** per erroneous application. Under-irrigation at a critical stage in maize can cost 5–15% of yield → at 12 t/ha and $200/t, **$120–360/ha**. Asymmetry ≈ 20:1, confirming §3.1.

### 3.6 Stratified reporting — mandatory
Every metric reported as a table crossed by:
- **Texture:** sand (clay<18, sand>65) / loam / clay-loam (clay 27–40) / clay (≥40), with high- vs low-activity clay flagged by CEC/clay.
- **Salinity:** ECe < 2 / 2–4 / 4–8 / > 8 dS/m.
- **Irrigation method:** furrow-flood / sprinkler-pivot / SDI / surface drip / rainfed control.
- **Depth:** 0–10 / 10–30 / 30–60 / 60–100 cm.
- **Season phase:** pre-plant / vegetative / peak ET / senescence.

Show **n in site-seasons** (not site-days) in every cell. **Grey out cells with n < 5 site-seasons rather than reporting them** — this is how the clay/saline claim stays honest with a small v1 dataset.

---

## 4. MINIMUM VIABLE SLICE

### Selection criteria for a v1 site
(a) multi-depth θ at ≥ 3 depths; (b) **known irrigation dates AND amounts**; (c) measured texture and BD by layer; (d) on-site or near-site weather; (e) public licence.

Criterion (b) eliminates ~90% of candidate data. It is the binding constraint of the entire project.

### v1 site list

| Site | Why | Access/licence *(recalled — verify)* |
|---|---|---|
| **USDA-ARS Bushland, TX** | Large weighing lysimeters, Pullman clay loam, sprinkler + SDI, maize/cotton/sorghum/wheat, neutron probe profiles to 2.4 m, full irrigation records. **The best single site in the world for this purpose.** | USDA Ag Data Commons, public |
| **AmeriFlux US-Ne1 / US-Ne2 / US-Ne3** (Mead, NE) | Irrigated continuous maize / irrigated maize–soy / **rainfed control on the same soil and climate**. The single best natural experiment for isolating the irrigation signal. TDR profiles, flux towers, management records. | AmeriFlux, CC-BY-4.0 |
| **OzNet / Yanco, NSW Australia** | Irrigated rice/cotton on **vertisols** — heavy smectitic clay, exactly the failure regime. Long public record. **Probably the best publicly available vertisol site.** | oznet.org.au, public |
| **HiWATER / Zhangye oasis, Heihe Basin, China** | Dense multi-depth network (HiWATER-MUSOEXE matrix), **flood-irrigated maize on saline-alkali soils at the oasis margin** — the salinity arm. | National Tibetan Plateau Data Center; registration; often CC-BY-NC |

**Deferred to v2 (cut from v1 to hit the 6-month gate):** Maricopa AZ (MAC/FACE legacy), Barrax Spain (SPARC/SEN2FLEX/REFLEX), USDA-ARS LIRF Greeley CO, Ningxia Yellow River district, USDA Salinity Lab / San Joaquin west-side saline-sodic fields.

### v1 hard exclusions
- **Zero figure digitization.** Not one figure.
- **No ISMN bulk ingest** — but *do* pull the ISMN metadata catalogue in month 1 to choose v2 sites and to audit how many irrigated, multi-depth, irrigation-documented stations actually exist.
- No gridded product. Point-based only.

### v1 models
1. Baselines: climatology, site-mean, Rosetta interpolation, **FAO-56 dual-Kc water balance with measured irrigation**, ERA5-Land, SMAP L4 RZSM.
2. **LightGBM** on tabular features, depth as a continuous feature.
3. **EA-LSTM** (entity-aware: static attributes → input gate, dynamic forcing → sequence), multi-output head over depths. **Use `neuralhydrology`; do not write your own.**

CV: **leave-one-site-out (LOSO)** outer, inner 5-fold leave-site-out for HPO. Report **per-fold**, never just the pooled mean, with a site-level bootstrap CI.

### The paper *is* the ablations
- with / without irrigation records ← the headline result
- with / without measured texture (i.e. POLARIS/SoilGrids only)
- with / without Sentinel-1
- **A vs B vs C input contracts** on identical folds
- pooled vs texture-stratified training

### What v1 CAN claim
> "At N well-characterised irrigated sites spanning X textures and Y salinity classes, an entity-aware LSTM conditioned on static soil attributes and irrigation forcing estimates multi-depth θ at unseen sites with ubRMSE of Z, outperforming ERA5-Land, SMAP L4 RZSM and a calibrated FAO-56 water balance. Adding four gravimetric calibration samples per season reduces total RMSE by W%, bringing it below the documented factory-calibration error of dielectric sensors in high-clay and saline soils."

It can also claim the **mechanism** — which features carry the signal, and that irrigation forcing is the binding constraint.

### What v1 CANNOT claim
- Global generality. N ≈ 10 sites means **10 samples**; LOSO CIs will be wide. Show them.
- Anything about unrepresented soils, climates, or irrigation methods.
- That it works without irrigation records — **test this explicitly; it will likely degrade badly, and that negative result is one of the most valuable things in the paper.**
- Superiority over a *site-calibrated* sensor. Almost certainly false. Say so.
- Operational readiness.

### GO / NO-GO GATES

**Gate 1 (M6) → proceed to ISMN bulk ingest?**
- LOSO ubRMSE ≤ 0.05 at all three depths; beats ERA5-Land by ≥ 20% RMSE; beats the FAO-56 water balance by ≥ 10%; Product B beats Product A by ≥ 25% total RMSE; **Paper 2 submitted**.
- **If ubRMSE > 0.06, or the model fails to beat the water balance: STOP. Do not add data.** The cause is almost certainly irrigation forcing, not model capacity. Add *physics* — a water-balance state variable as an input feature, or a hybrid residual model that learns the water balance's error.

**Gate 2 (M12) → proceed to literature digitization?**
- ISMN ingest improves ubRMSE by ≥ 10% **on the original v1 held-out sites** (proves transfer, not just more data), AND the count of genuinely irrigated, multi-depth, irrigation-documented ISMN stations is ≥ 30.
- **I expect the irrigated subset of ISMN to be small** — ISMN is dominated by rainfed/natural networks (SCAN, USCRN, OzNet non-irrigated arms), and irrigation metadata in ISMN is sparse to nonexistent *(recalled — audit this in month 1, it is a 3-hour job that reshapes the whole plan)*. If it is < 30, the bottleneck is confirmed and digitization becomes *justified* — but only for papers reporting irrigation amounts.

**Gate 3 (M15) → digitization at scale? Pilot 20 papers first.**
- ≥ 50% of candidate papers report irrigation dates AND amounts AND texture AND depth; throughput ≥ 3 papers/hour including QC; digitized series pass the physical-plausibility screen (θ ∈ [θr, θs]; drydown slope ≤ potential ET; mass balance closes within 30%).
- **If < 30% have irrigation amounts: abandon scale digitization.** Keep the pilot as supplementary data only. **I expect this gate to fail, and planning for that failure is the single most useful item in this charter.**

**Gate 4 (M18) → global scale-out?** Almost certainly no. Defer to a funded follow-on.

---

## 5. EFFORT, COMPUTE AND COST

### Person-hours *(estimates for one experienced researcher, limited SWE time; assume ~25 productive h/week)*

| Component | Hours |
|---|---|
| Site selection + reading site documentation | 60 |
| Bushland ingest (Ag Data Commons) | 25 |
| AmeriFlux US-Ne1/2/3 ingest (BASE files, clean) | 20 |
| OzNet/Yanco ingest | 20 |
| HiWATER ingest (registration, metadata, format variety) | 50 |
| **Harmonisation layer** (units, depth conventions, timezones, QC flags, one schema) | **120** ← universally underestimated |
| Static soil attributes + Rosetta3 | 40 |
| Weather forcing extraction | 50 |
| Remote sensing extraction via GEE (S1 preprocessing is the sink) | 80 |
| FAO-56 dual-Kc water balance baseline | 40 |
| LightGBM + CV harness | 60 |
| EA-LSTM via neuralhydrology | 80 |
| HPO runs + analysis | 50 |
| Decision-metrics module (§3) | 50 |
| Figures, writing, revision | 180 |
| Slack, debugging, rework | 200 |
| **v1 total** | **≈ 1,125 h** |

**≈ 11 months at 25 h/week.** That already blows the 6-month MVS — which is why Barrax and Maricopa were cut above. With the four-source list, v1 is **≈ 700–750 h ≈ 6–7 months at 25 h/week**. That is the real minimum viable slice, and it is still tight.

Later stages: ISMN bulk ingest **150–250 h**. Digitization: pipeline build **120 h** + per-paper 35–80 min including QC → **500 papers ≈ 300–600 h of irreducible human time**. Automated plot extraction (WebPlotDigitizer automation or a VLM extractor) does not remove the QC burden. **That is 0.5 FTE-year for the digitization arm alone.** Global scale-out: 300+ h.

### Compute

**Google Earth Engine.** A free noncommercial research account is fine for v1 (tens of sites × a decade). It is **not** fine for 10k–100k sites: you hit `Computation timed out` and `User memory limit exceeded` on `reduceRegions` over long ImageCollections, and the ~5-minute interactive request ceiling. The pattern that scales: chunk the `FeatureCollection` into 500–1000 points, one `Export.table.toCloudStorage` task per chunk per year, managed by a task queue. Free-tier concurrent export tasks are limited (order 2–20 depending on account) *(recalled)* — budget **days-to-weeks of wall clock**, not hours. For Sentinel-1 at 100k points, strongly consider **Microsoft Planetary Computer** (free, STAC + Dask) or **AWS Open Data / Earth Search STAC + stackstac**, which parallelise point extraction far better.

**CDS / ERA5-Land — the trap.** Per-user concurrent-request caps (order 1–5) and per-request cost limits mean a full multi-variable, multi-decade hourly pull is dozens of requests and **realistically 1–3 weeks of elapsed time**, with the new CDS-Beta migration having invalidated old `cdsapi` URLs/keys *(recalled)*. Mitigations, best first:
1. **Do not use the CDS API for point extraction at all. Use GEE's `ECMWF/ERA5_LAND/HOURLY`.** This single decision saves weeks and is the highest-leverage item in this section.
2. For CONUS use **`IDAHO_EPSCOR/GRIDMET`** (4 km daily, **ET₀ already computed**) in GEE.
3. If you need gridded ERA5, use **ARCO-ERA5 Zarr on GCS** (`gs://gcp-public-data-arco-era5`) — no queue, but it's ERA5 (~31 km), not ERA5-Land (~9 km).
4. Use **AgERA5** (daily, agro-ready) instead of hourly ERA5-Land wherever daily suffices.

**NASA Earthdata / AppEEARS.** Right tool for MODIS/VIIRS/SMAP point time series. Free with Earthdata Login. A few thousand coordinates × a few products returns in hours to a day; there are per-request coordinate and layer limits *(recalled — chunk accordingly)*. For bulk SMAP, `earthaccess` + direct S3 in **us-west-2** is far faster than downloading — but only if your compute is also in us-west-2; otherwise you are egress-limited.

**Optuna / EA-LSTM HPO — do the arithmetic.**

*v1 scale:* ~12 sites × ~10 site-years × 365 d × 3–4 depths ≈ 150–200k rows; sequences of 365 with ~30 dynamic features. One EA-LSTM (hidden 128, 1 layer) training run ≈ **5–20 min on a single modern GPU** (L4/A10/A100) — the dataset is small.

*Full nested spatial CV:* 12 outer LOSO folds × 60 Optuna trials × 5 inner folds × 12 min = **43,200 GPU-min = 720 GPU-hours** ≈ **$500–1,500** at $0.70–1.20/h, or ~30 days on one local GPU. **Too much for a solo project.**

*The fix (and it is standard practice, so declare it rather than hiding it):*
- **Run HPO once on a designated development subset of sites held out from the final test sites**, freeze the hyperparameters, then run the 12 outer folds. → 60 × 5 × 12 min = **60 GPU-h** for HPO + 12 × 12 min = **2.4 GPU-h** for final CV ≈ **63 GPU-hours ≈ $50–80.** Mild optimism bias; state it explicitly in the methods.
- Use Optuna's `MedianPruner` or Hyperband → 40–60% fewer trials. 60 trials over ~8 hyperparameters is plenty; 200 is waste.
- **LightGBM HPO is essentially free** (CPU, seconds per fit) — do *full* nested CV for LightGBM, the cheaper protocol for EA-LSTM, and say so. The LightGBM nested result then serves as an honest upper bound on the optimism.

*v2 scale (ISMN, ~1,500 sites, ~15k site-years):* one run ≈ 3–8 GPU-h; HPO at 60 × 5 × 5 h ≈ **1,500 GPU-h ≈ $1,000–1,800**. At that point: cut to 25 trials, subsample sites for HPO, and use spot/preemptible instances.

**Storage — and a correction to a project assumption.** v1 raw + harmonised: **< 50 GB**. v2 ISMN raw: 30–100 GB. Point extractions of Sentinel-1/2 are tiny — they are points. **The "terabytes of data" framing is wrong for the point-based formulation and right only for a gridded product. Point-based is the correct formulation, and it is gigabytes on a laptop plus one cloud bucket.** Saying this out loud de-risks the entire project and removes the main excuse for building infrastructure.

**Total cloud budget, v1 (12 months):** GEE free ($0) + AppEEARS free ($0) + GPU $80–200 + object storage ~$5/mo + a small VM for backups ~$20/mo ≈ **under $600**. v2 adds $1,500–2,500 for HPO.

### Buy or reuse, do not build

| Need | Reuse this | Instead of |
|---|---|---|
| EA-LSTM/LSTM + CV harness | **neuralhydrology** | writing your own |
| ISMN parsing | **`ismn`** PyPI package | custom parsers |
| ET₀ | **`pyet`/`refet`**, or gridMET's precomputed ET₀ | implementing Penman-Monteith |
| PTFs | **`rosetta-soil`** (USDA-ARS Rosetta3) | fitting your own |
| Raster → point | **GEE** | local raster downloads |
| Soil properties | **POLARIS 30 m** (CONUS, has θ₃₃/θ₁₅₀₀), **SoilGrids 250 m** (global) | hand-interpolating SSURGO |
| Root-zone baseline | **SMAP L4 RZSM** 9 km, 0–100 cm, 3-hourly | building a DA system |
| **ET / inferred irrigation** | **OpenET** (30 m ensemble ET, CONUS, free API) | building an ET model — and OpenET residual water balance is the fallback for missing irrigation records |

**Pay for nothing except GPU hours.** The temptation to buy tooling is a scope-creep symptom.

---

## 6. FAILURE MODES, IN THE ORDER THEY WILL ACTUALLY HAPPEN

**1. Week 1–2 — account and API-key walls.** GEE now requires a Cloud project registered as noncommercial with the Earth Engine API enabled (trips most newcomers); Earthdata Login; CDS-Beta migration invalidating old keys; National Tibetan Plateau Data Center registration for HiWATER; AmeriFlux data-use agreement.
*Indicator:* any of these not working by day 10. *Mitigation:* do all account setup in week 1 as a single task before writing any code. Keep `docs/CREDENTIALS.md` recording account names and key locations — **never secrets**.

**2. Month 1 — CDS queue times.** *Indicator:* a single test request exceeding 2 h. *Mitigation:* pre-committed — use GEE's ERA5-Land. If you must use CDS for AgERA5 bulk, submit on day 1 of month 1 as a background batch so it cooks while you work.

**3. Months 1–3 — silent unit / coordinate / timezone errors.** The most damaging class, because it never announces itself. Known traps: θ in % vs m³/m³ vs mm per layer; depth as sensor centre vs layer top; negative-down vs positive-down; **local standard vs daylight vs UTC** (a 6-hour shift destroys the diurnal signal and irrigation-timing alignment); lon/lat swapped; **ERA5 total precipitation is in metres**, accumulated, valid for the hour *ending* at the timestamp.
*Indicator & mitigation — build a physics assertion suite that runs on every ingest:*
- 0 ≤ θ ≤ θs(Rosetta) + 0.05
- |dθ/dt| below 40 cm never exceeds 0.05 d⁻¹
- diurnal minimum of θ occurs in the afternoon, not at 03:00 (catches timezone errors)
- annual precipitation within 30% of climatology for the coordinates (catches unit and lon/lat errors)
- ET₀ peaks in summer and falls in 2–12 mm/d
Any site failing is **quarantined, not silently included.** This is ~1 day of work and is the highest-ROI code in the project.

**4. Months 2–4 — the ISMN licence discovery.** ISMN requires registration and acknowledgement, and the **individual contributing networks carry heterogeneous, network-specific licences**, some requiring direct provider contact and some prohibiting redistribution *(recalled — read the ISMN data policy and the per-network terms in month 1)*. You can very likely train on ISMN; you very likely **cannot redistribute a harmonised derivative containing raw values** — which kills the "publish a terabyte dataset" ambition.
*Mitigation:* design the deliverable as **code + a station-ID manifest + a processing recipe + derived features + model weights**, not a redistributed data blob. This turns the output from a data paper into a methods paper. Decide that in month 1, not month 8.

**5. Months 3–6 (only if digitization starts early) — publisher rate-limit ban.** Scripted access to Elsevier/Springer/Wiley from a university IP gets **the whole institution blocked**. That is a career-grade embarrassment.
*Indicator:* any HTTP 429 or captcha. *Mitigation:* **never scrape publisher sites.** Use only (i) Crossref REST and OpenAlex/Semantic Scholar APIs for metadata (both explicitly permit polite bulk use with a `mailto`/User-Agent), (ii) Unpaywall/OpenAlex OA locations and the PMC OA subset for full text, (iii) Elsevier's TDM API with an institutional key if one exists, (iv) manual download otherwise. Rate-limit to ≤ 1 req/s with a descriptive User-Agent containing a contact email. **Get written sign-off from the library before any bulk text mining.**

**6. Months 4–8 — most literature series lack irrigation amounts.** The likeliest single cause of project failure. A θ figure without the irrigation schedule is nearly useless for training an irrigated-field model: the input explaining most of the variance is missing.
*Indicator:* the 20-paper pilot (Gate 3). *Mitigation, specified in advance so a failed gate is a pivot rather than a crisis:* (a) pre-register the pilot; (b) if amounts are missing but dates are inferable from the θ series itself, **treat irrigation as a latent variable to be jointly inferred** — that is a genuinely better paper; (c) infer irrigation from the OpenET ET−P residual, or from LANID/IrrMapper/MIrAD irrigated-area maps plus a water-balance inversion.

**7. Months 6–12 — scope creep into a global product.** Symptoms: "while I'm here I'll add Africa"; refactoring ingest to be generic; building a web map.
*Indicator:* two consecutive weeks with no change to the results notebook. *Mitigation:* a **written scope freeze at Gate 1** listing what v1 will NOT include, co-signed by a collaborator willing to enforce it.

**8. Months 6–9 — the stretch with nothing publishable.** The most common way this project dies.
*Mitigation — the single most important recommendation in this charter:* **front-load a publishable unit that does not depend on the ML working.** By month 4–5, write and submit a short synthesis: *"How wrong are dielectric soil moisture sensors in high-clay and saline irrigated soils, and what would a model have to achieve to beat them?"* It is a review + reanalysis of existing calibration literature, needs no new ML, sits squarely in the author's decade of expertise, is genuinely useful to the community, and **it defines the success criterion in §2 with a citable number.** If the ML fails, you still have a paper. If it succeeds, you cite yourself for the target.

**9. Ongoing — Product A fails to beat the FAO-56 water balance.** *Indicator:* month 5. *Mitigation:* pre-commit to publishing either way, framed as *"what does ML add over a physically-based water balance in irrigated fields, and under what conditions?"* — a good paper whichever way it lands.

**10. Month 10+ — the reviewer who demands independent field validation.** *Mitigation:* gravimetrically sample 2–3 local fields (ideally one saline clay) on 6–8 dates during year 1, purely as an independent test set. **Do this in month 3–4, so the samples exist before you need them.** ~40 h and ~$2k.

---

## 7. SOLO-OPERATOR ERGONOMICS

### Recommended minimal stack — explicitly replacing the Dagster/DVC/Postgres proposal

| Layer | Use | Not | Why |
|---|---|---|---|
| Storage | **Parquet on disk**, partitioned by source and site | Postgres | DuckDB queries Parquet directly, joins 100 GB on a laptop, no server, no migrations, no backups. The "database" is a directory you can `rsync`. DuckDB→Postgres later is a one-day port; Postgres on day 1 costs a month. |
| Query | **DuckDB** | ORM | SQL over Parquet, zero setup |
| Orchestration | **Makefile + plain Python scripts** | Dagster | Make is installed, does incremental rebuilds on timestamps for free, has been stable for 40 years. Dagster is for teams with on-call rotations. One person with six ingests has a *remembering* problem, and Make solves that. ~30 lines gets 80% of Dagster. |
| Data versioning | **git for code + content-addressed, date-stamped immutable raw** | DVC | DVC adds a second mental model and a remote to maintain. `data/raw/<source>/<YYYY-MM-DD>/` never edited, each with `manifest.json` (URL, request params, retrieval timestamp, SHA256, row count), `rclone sync`'d nightly. That *is* reproducibility; DVC is bookkeeping on top of it. |
| Environment | **pixi** or `uv` + locked requirements | unpinned conda | Record the lockfile hash in the run ledger |
| Config | one `config.yaml` per experiment, hashed into the run ID | argparse sprawl | |
| Tracking | **run ledger Parquet** (+ optional local-file MLflow) | Weights & Biases | Another account, another network dependency, another dashboard to forget |

Make targets: `data/raw/%.ok` → `data/interim/harmonised.parquet` → `data/processed/features.parquet` → `results/cv_<model>.parquet` → `paper/figs/%.pdf`. Single entry point: `make all`. Everything idempotent.

### The run ledger
One append-only `results/runs.parquet`, one row per run:
`run_id` (ULID) · `timestamp_utc` · `git_sha` · **`git_dirty`** (refuse to write results if dirty, or record it loudly) · `config_hash` · `config_json` · `dataset_version` (the set of date-stamped raw folders) · `model` · `cv_scheme` · `fold` · `n_train_sites` · `n_test_sites` · metrics · `wall_clock_s` · `hostname` · `notes`.

Every figure is generated by a query against this table and carries its `run_id` in the caption while drafting. **This one file is the difference between a resumable project and a pile of notebooks.** Commit it to git — it's small.

### Scheduled vs on-demand ingests
Almost nothing here needs scheduling; the sites are historical. Make everything **on-demand and idempotent**, triggered by Make. Only two things deserve cron: (a) nightly `rclone sync` backup of `data/raw/`; (b) weekly re-run of the physics assertion suite over `data/interim/`, which catches rot. **Resist a scheduled ingest until there is a live operational deployment.**

### Resumable after a three-week absence
- **`README.md`** whose first section is literally *"If you are returning after a break, read this"*: current stage, last thing that worked, the one command to reproduce the latest results, next three concrete actions.
- **`JOURNAL.md`**, append-only, one dated entry per session, 5–15 lines: what I did, what broke, **what I decided and why**. Decisions especially — in six weeks you will not remember why you excluded a site.
- **`make verify`** — assertion suite + fast smoke CV on 2 sites in < 5 minutes, prints PASS/FAIL. First thing you run when you come back.
- **`NEXT.md`** — 5 ordered TODOs, updated at the *end* of each session, never the start.

### Notebook vs pipeline discipline
**Notebooks are for looking; modules are for computing.** A notebook may import from `src/` and may plot; it may never define a function the pipeline needs, and it may never write into `data/processed/` or `results/`. Any cell worth running twice becomes a function in `src/` that same day. Strip outputs with an `nbstripout` pre-commit hook. Date-prefix and treat as disposable: `2026-09-22-drydown-exploration.ipynb`, never `analysis_v3_final.ipynb`. Exactly one exemption: `notebooks/figures.ipynb`, which reads the run ledger and emits paper figures — and even that should become `make figs`.

### Surviving a laptop failure
The recovery test *is* the spec: **if the laptop dies today, can a competent stranger with the git repo and the cloud bucket reproduce the results in a week?** Therefore off-laptop: git repo (pushed daily — put `git push` in the JOURNAL habit); `data/raw/` mirrored with manifests; the lockfile; the run ledger (in git); all `config.yaml`; README/JOURNAL/NEXT; site documentation PDFs in `docs/sources/`. Credentials in a password manager, never only on the laptop. **Do a literal restore drill in month 3 on a fresh cloud VM: clone, restore, `make verify`.** Budget 4 hours. It will find three things.

### Handover
The handover artifact is `README.md` + `JOURNAL.md` + `docs/DATA_SOURCES.md` (one page per source: what it is, how to get it, licence, contact person, known quirks, the exact request that fetched it) + the run ledger. If those four are current, handover is a one-hour conversation.

### Cadence
**One 90-minute block per week reserved for maintenance only** — dependency updates, backup verification, ledger tidying, README refresh. Not optional; it is what keeps the three-week-absence property true.

---

## 8. THE CHARTER

### 8.1 Three products, one table

| | **A — Replacement** | **B — Reduction** ★ primary | **C — Forecast** |
|---|---|---|---|
| In-situ θ input | none, ever | 2–6 gravimetric samples/season | full history ≤ t |
| Lagged θ | forbidden at every lag and depth | only via the calibration samples | legitimate, ≤ t only |
| Forcing | reanalysis/gridded | same | **forecast** weather (train/serve skew risk) |
| Expected ubRMSE | 0.035–0.055 | 0.025–0.035 | d+1 0.010–0.020; d+7 0.020–0.035 |
| Expected total RMSE | 0.05–0.09 (bias-dominated) | **0.025–0.040** | — |
| Must beat | FAO-56 WB, ERA5-Land, SMAP L4 | **uncalibrated dielectric sensor in saline clay** | persistence + FAO-56 WB |
| Question | "plausible moisture at an uninstrumented field" | "how much water is in this profile now" | "irrigate in the next 3 days?" |

### 8.2 Numeric success criteria
- **Primary (falsifiable):** Product B, held-out irrigated sites with clay ≥ 35% and/or ECe ≥ 4 dS/m, against gravimetric truth: **total RMSE ≤ 0.035 m³/m³, |bias| ≤ 0.015, at ~10/30/60 cm**, while a factory-calibrated dielectric sensor in those soils achieves ≥ 0.05. Falsified if model RMSE ≥ sensor RMSE in that class, or ≥ 0.045 absolutely.
- Product A: LOSO ubRMSE ≤ 0.045 all depths; KGE ≥ 0.5; anomaly r ≥ 0.5; beats FAO-56 WB by ≥ 10%.
- Product C: ≥ 25% vs persistence at d+3; ≥ 15% at d+7.
- Decision level: median |ΔD| ≤ 1 day; ≥ 70% of drydowns within ±1 day; POD ≥ 0.85 at FAR ≤ 0.20; seasonal ΔS error ≤ 15 mm; PAW RMSE ≤ 12 mm (0–60 cm); |Δτ|/τ ≤ 25%; **drydown-RMSE/overall-RMSE ≤ 1.3**.

### 8.3 18-month staged plan (from Oct 2026)

| Month | Work | Deliverable / Gate |
|---|---|---|
| **M0** Oct'26 | All accounts, scope freeze document, repo skeleton, **physics assertion suite** | `make verify` passes on one site |
| **M1–M2** | Ingest Bushland + US-Ne1/2/3; harmonised schema v1; **ISMN irrigated-station audit (3 h)**; **read ISMN per-network licences** | ≥ 30 harmonised site-years; licence decision recorded |
| **M2–M3** | Static soil + weather + RS features via GEE; FAO-56 dual-Kc baseline | Feature table; baseline RMSE in the ledger |
| **M3–M4** | Ingest Yanco (vertisol) + HiWATER (saline); **start local gravimetric campaign**; **restore drill**; draft the sensor error-budget review | Independent test samples exist |
| **M4–M5** | LightGBM + EA-LSTM; LOSO CV; A/B/C ablations | **Submit Paper 1 (sensor error budget)** |
| **M5–M6** | Decision-metrics module; stratified tables; write up | **GATE 1** · **Submit Paper 2 (MVS methods)** |
| **M7–M10** | ISMN ingest; irrigated-subset audit; retrain; transfer test on v1 held-out sites | Transfer ≥ 10% improvement or not |
| **M11–M12** | Paper 2 revisions; Gate 2 analysis | **GATE 2** — digitization go/no-go |
| **M12–M14** | 20-paper digitization pilot (only if Gate 2 passed) | Pilot statistics |
| **M15** | Evaluate pilot | **GATE 3** — *expected outcome: NO-GO*; pivot to latent-irrigation inference |
| **M15–M18** | Paper 3: either expanded multi-site model, or **joint latent-irrigation inference**; release code + station manifest + weights; write follow-on proposal | **GATE 4** — global scale-out only as funded follow-on |

Three papers, none of which depends on the previous one succeeding. That property is the point.

### 8.4 Effort and cost

| Phase | Person-hours | Cloud cost | Wall clock |
|---|---|---|---|
| v1 MVS (4 sources, A/B/C, decision metrics, Paper 2) | 700–750 | ~$300 | 6–7 mo @ 25 h/wk |
| Paper 1 (sensor error budget) | 80–120 | $0 | overlaps M3–M5 |
| ISMN ingest + retrain | 150–250 | $200 | 4 mo |
| EA-LSTM HPO, dev-set protocol | (in above) | $50–80 | 3 days wall clock |
| Digitization pipeline + 20-paper pilot | 120 + 25 | $0 | 2 mo |
| Digitization at scale *(if Gate 3 passes — expected not to)* | **300–600** | $0 | 6 mo |
| v2 HPO at ISMN scale | — | $1,000–1,800 | 1–2 wk |
| **18-month total (Gate 3 NO-GO path)** | **~1,150–1,300 h** | **~$600–1,000** | 18 mo |

Storage: < 100 GB throughout. **Not terabytes.**

### 8.5 Risk register

| # | Risk | P | Impact | Early-warning indicator | Mitigation |
|---|---|---|---|---|---|
| 1 | API/account walls | High | Low | Any account not working by day 10 | All setup in week 1, before code |
| 2 | CDS queue | High | Med | Test request > 2 h | **Use GEE ERA5-Land; never CDS for points** |
| 3 | Silent unit/TZ/coord errors | **Very High** | **Very High** | Assertion suite failures; diurnal θ min at 03:00 | Physics assertion suite on every ingest; quarantine failures |
| 4 | ISMN redistribution barred | High | Med | Per-network licence read in M1 | Ship code + manifest + recipe, not data. Methods paper, not data paper |
| 5 | Publisher IP ban | Med | **Very High** | Any 429/captcha | Crossref/OpenAlex/Unpaywall only; ≤ 1 req/s; library sign-off |
| 6 | Literature lacks irrigation amounts | **Very High** | High | 20-paper pilot (Gate 3) | Pre-specified pivot: latent-irrigation inference; OpenET residual |
| 7 | Scope creep to global | High | High | 2 weeks with no change to the results notebook | Written scope freeze at Gate 1, co-signed |
| 8 | Nothing publishable by M9 | **High** | **Very High** | No submission by M5 | **Front-load Paper 1 (sensor error budget) — needs no ML** |
| 9 | A fails to beat FAO-56 WB | Med | Med | M5 baseline comparison | Pre-commit to publishing the negative result; add physics, not data |
| 10 | Reviewer demands independent validation | Med | Med | — | Gravimetric campaign on 2–3 local fields in M3–M4 |
| 11 | HPO cost blowout | Med | Med | GPU spend > $150 in v1 | Dev-set HPO protocol; pruner; full nested CV only for LightGBM |
| 12 | Infrastructure sinkhole | High | High | > 2 weeks on tooling with no new result | Make + Parquet + DuckDB; a tooling change needs a JOURNAL justification |
| 13 | Laptop loss | Low | **Very High** | Restore drill fails | Daily push; nightly rclone; **M3 restore drill on a fresh VM** |

### 8.6 Scope cuts recommended — be willing to make all eight

1. **Cut figure digitization from v1 entirely**, and probably from all 18 months. Highest cost, lowest certainty, gated on a condition I expect to fail.
2. **Cut the "terabyte global database."** The correct point-based formulation is gigabytes. A terabyte target is a symptom of a gridded scope this project should not have.
3. **Cut Dagster / DVC / Postgres** → Make + Parquet + DuckDB.
4. **Cut nested HPO inside every outer fold** → one dev-set HPO, declared in the methods.
5. **Cut Barrax and Maricopa from v1** (keep for v2). Four sources, not six.
6. **Cut "global" from the v1 title and abstract.**
7. **Cut the plan to redistribute a harmonised dataset** until every contributing network's licence has been checked individually.
8. **Reframe the goal**: not "replace sensors" but *"replace dielectric sensors in high-clay and saline soils using a few gravimetric samples."* Narrower, defensible, falsifiable, and it is exactly where a decade of soil-physics expertise is the differentiator rather than a nice-to-have.

---

### Verification priority list (do these first, they change the plan)
1. **ISMN irrigated + multi-depth + irrigation-documented station count.** ~3 hours. Reshapes Gate 2 and the whole v2 arm.
2. **ISMN per-network licence terms re: redistribution.** Determines data paper vs methods paper.
3. **Current datasheet accuracy specs and EC/clay caveats** for CS655, TEROS 12, PR2, Drill&Drop — §2(a) is all recalled.
4. **Published bound-water and bulk-EC error magnitudes in m³/m³** for smectitic and saline soils — §2(b) is the premise of the project and every number there is recalled.
5. **The exact citation for the 2022 field-scale multi-depth US ML paper** — I could not reconstruct it reliably.
6. **GEE free-tier concurrent export-task limits** and **AppEEARS per-request coordinate limits** — both recalled as order-of-magnitude only.
7. **Bushland, Yanco and HiWATER data access terms and actual irrigation-record completeness** — the v1 site list stands or falls on criterion (b).

**No sources can be listed: the session's WebSearch budget was exhausted before this subagent ran, so nothing above was confirmed by search.**