# smml — multi-depth soil moisture simulation for irrigated agriculture

A harmonized global soil moisture database and a machine-learning system that
estimates **multi-depth soil moisture in irrigated fields** from weather, soil
texture and salinity — with the aim of reducing how many sensors have to be in
the ground.

The premise is that dielectric soil moisture sensors are systematically biased
by **clay content** and by **salinity**, that enough measurements now exist in
the public record and in the published literature to learn the underlying
behaviour, and that a model which knows about those biases can do better than
the sensors it replaces. The code treats both biases as first-class physics
rather than as noise.

---

## What is here

| Stage | Module | Status |
|---|---|---|
| Source catalogue — 168 datasets, 93 studies | `smml.registry` | complete |
| Harvest connectors — weather, soil, salinity | `smml.sources` | written, parser-tested, **not run against live APIs** |
| ISMN bulk-download reader | `smml.sources.ismn` | complete |
| Literature discovery — repositories, OpenAlex, Europe PMC | `smml.litmine.discover` | written, **not run against live APIs** |
| Table extraction from theses and reports | `smml.litmine.tables` | complete, round-trip exact |
| Document triage by expected table yield | `smml.litmine.triage` | complete |
| Grey-literature harvest — OAI-PMH, Dataverse | `smml.litmine.repositories` | written, **endpoints unverified** |
| Cross-lingual terms and normalisation | `smml.litmine.multilingual` | complete |
| Endpoint verification | `smml.util.verify` | complete |
| Figure digitization — vector + raster | `smml.litmine.digitize` | complete and measured |
| Database — star schema, idempotent Parquet + DuckDB | `smml.db` | complete |
| Sensor physics — clay, salinity, unit harmonization | `smml.physics` | complete and cross-validated |
| Quality control + irrigation inference | `smml.qc` | complete and measured |
| Irrigation label fusion — evidence to calibrated probability | `smml.irrigation` | complete |
| Licence and TDM compliance gate | `smml.litmine.compliance` | complete (policy, not legal advice) |
| Falsifiable success criteria | `smml.eval.targets` | complete |
| Features, models, evaluation, tuning | `smml.features` `.models` `.eval` `.tune` | complete, run end to end |

### The one thing to know before running this

**No connector in this repository has ever contacted its live API.** The
environment it was built in blocks outbound HTTPS to every data and literature
host by policy — ISRIC, NASA POWER, OpenAlex, Crossref, NOAA, ISMN all return
403 at the egress proxy. So:

- endpoints, query syntax, rate limits and unit conversions come from a
  documentation survey, and each registry entry is marked `confirmed`
  (corroborated by a search result) or `recalled` (from model knowledge, verify
  it);
- the parsers *are* tested, against fixtures built to each service's documented
  response shape and seeded with the traps that actually bite — NASA POWER's
  `-999` fill value, SoilGrids' integer storage with a per-property divisor and
  texture fractions that do not sum to 100, SSURGO's multiple components per map
  unit and null salinity;
- expect to fix an endpoint or two on first run. Expect *not* to find a −999 mm
  rainfall day or a conductivity wrong by a factor of 3600.

**There is tooling for exactly this.** `smml verify endpoints` probes every
catalogued URL, tells you which moved and where to, and writes a CSV designed to
be handed back for repair. It correctly distinguishes a host blocked by a local
network policy from a genuinely broken endpoint, so a restricted network does not
turn into a hundred spurious failures.

```bash
smml verify endpoints        # probes the 91 recalled entries, writes endpoint_report.csv
smml verify repositories     # speaks OAI-PMH to the grey-literature seeds
```

Everything that does not require the network — the physics, the database, the
digitizer, QC, features, models, evaluation, tuning — is complete and was run.

---

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
```

Optional credentials, all free:

```bash
export OPENALEX_API_KEY=...   # required since Feb 2026; anonymous is 100 credits/day
export UNPAYWALL_EMAIL=you@example.org
export ZENODO_TOKEN=...       # optional
export SMML_DATA_ROOT=/mnt/big-disk/smml   # the corpus is expected to reach TB
```

## Run it end to end, with no network

One command builds the database, trains, tunes, and writes every figure and
table into `artifacts/`:

```bash
python scripts/run_full_pipeline.py      # ~40 min on four cores
```

Or stage by stage:

```bash
smml simulate --n-sites 50 --years 4     # physics-based synthetic corpus
smml qc                                   # quality control
smml irrigation-label                     # evidence fusion, worked example
smml compliance                           # what the sources permit
smml evaluate --include-optimism          # models vs baselines, and split honesty
smml tune --model lightgbm --trials 50    # hyperparameter search
```

### What comes out

`artifacts/` holds the database in three forms — partitioned Parquet for
working, a single portable `soil_moisture.duckdb` file to hand to someone, and
CSV for a spreadsheet — plus six figures and the result tables behind them. See
[`artifacts/README.md`](artifacts/README.md).

**The corpus those artifacts are built from is synthetic**, because this
environment could reach no data host. They show the pipeline works and its
diagnostics behave; they say nothing about accuracy on real soils. Every figure
carries that notice in its corner. Point the same script at a harvested database
by changing one path.

## Run it on real data

```bash
smml registry networks --irrigated          # the 21 networks with irrigated stations
smml registry networks --rainfed            # 16 rainfed controls
smml registry list --category soil_property --max-priority 1
smml harvest soil    --sites sites.csv --source soilgrids_rest
smml harvest weather --sites sites.csv --source nasa_power --start 2000-01-01
smml literature discover
smml literature digitize figure3.png --x-min 0 --x-max 180 --y-min 0.10 --y-max 0.45
smml train --model lightgbm --split leave_site_out
```

---

## What would count as success

"Replace soil moisture sensors" is not falsifiable, and as written it is
probably false — a model with nothing in the ground will not beat a
well-calibrated TDR probe in a loam. The defensible claim is narrower, stronger,
and sits exactly where your expertise does:

> Replace **dielectric** sensors in the soils where dielectric sensors are
> unreliable — high-activity clays and saline soils — using static soil
> attributes, irrigation forcing, remote sensing, and a handful of gravimetric
> calibration samples.

`smml.eval.targets` encodes that as three products with separate thresholds,
because a target written in a paragraph never gets checked:

| product | question | criterion |
|---|---|---|
| **A** no site data | what is the climatology and event response of a field never instrumented? | leave-site-out ubRMSE ≤ 0.045, KGE ≥ 0.5, within-site r ≥ 0.5 |
| **B** a few gravimetric samples | how much water is in *this* profile now? | **total RMSE ≤ 0.035 and \|bias\| ≤ 0.015 in clay ≥ 35 % or ECe ≥ 4 dS/m**, where a factory-calibrated probe achieves ≥ 0.05 |
| **C** forecast | what will it be in three days? | ≥ 25 % better than persistence at day+3, ≥ 15 % at day+7 |

Two things are built into this deliberately.

**Product B is scored on the difficult soils only.** Good performance in loam
must not be allowed to carry a failure in clay — the clay is the claim.

**The headline is total RMSE against gravimetric truth, not ubRMSE.** A
dielectric probe's error in clay and saline soil is predominantly bias, and
ubRMSE removes bias. Comparing model ubRMSE against sensor total RMSE would
flatter the model by exactly the quantity at issue.

`evaluate_targets` also raises a **leakage warning** below 0.020 ubRMSE, which
fires even when every threshold passes. Random k-fold on rows produces ubRMSE
around 0.015–0.02 on data whose honest leave-site-out value is 0.04–0.06, so a
suspiciously good score is the most reliable leak detector there is.

## The three findings that shaped the design

These came out of running the pipeline, not out of planning it. Each changed the
code.

### 1. Training on raw sensor readings bakes the clay bias into the model

A dielectric probe cannot see water bound to clay surfaces — bound water has a
permittivity near that of ice, not of free water — so it reads low, and more so
the finer the soil. A model trained on those readings faithfully reproduces the
bias.

Measured on the synthetic corpus, leave-site-out, scored against true water
content:

| trained on | RMSE | bias | r within site |
|---|---|---|---|
| raw sensor reading | 0.0692 | **−0.0422** | 0.790 |
| clay-corrected reading | **0.0486** | −0.0057 | 0.788 |

Correcting the target first removes the bias and cuts RMSE by 30 %. The
correction is applied by default in the pipeline and written to its own column;
the original observation is never overwritten.

### 2. A pooled correlation cannot tell a useful model from a useless one

Between-site variance is 84 % of the total in this corpus — texture alone sets a
field's mean water content across a range far wider than any one field's
variation over a season. So a static prediction of field capacity from texture,
which never changes in time, scored a pooled **r = 0.90** and beat gradient
boosting on RMSE.

Its within-site temporal correlation was **exactly zero**. It knows which fields
are wet and nothing about when to irrigate any of them.

`smml.eval.metrics.skill_decomposition` reports `r_between` and `r_within`
separately, and every evaluation prints both.

### 3. A random k-fold split measures memorization

Soil moisture is strongly autocorrelated in time and space, so a random split
puts near-duplicate rows on both sides of the boundary. `smml evaluate
--include-optimism` quantifies the gap on your own data. The splitter is called
`random_kfold_DO_NOT_USE` so that reaching for it has to be deliberate.

---

## The irrigated-network shortlist

Of 71 catalogued in-situ networks, these 21 are classified as having stations on
irrigated cropland — the starting point for the harvest:

`agweathernet_coagmet_intermountain` · `ameriflux` · `azmet` · `cimis` ·
`cma_soil_moisture_cn` · `illinois_climate_network_warm` ·
`mediterranean_irrigated` · `nebraska_nawmn_nrd` · `nrcs_awdb_rest_api` ·
`oklahoma_mesonet` · `osr_maghreb_irrigated` · `scan` · `ars_micronet_ok` ·
`cosmos_us` · `hobe` · `nebraska_mesonet` · `nrcs_report_generator` ·
`nysm_deos` · `crns_china` · `nsmn_ncsmmn` · `usgs_nwis_soil_mois`

Sixteen more are explicitly sited away from irrigation — SNOTEL, USCRN, NEON,
TxSON, TERENO, SMOSMANIA among them. Those are not a lesser category: a model
cannot learn what irrigation does without rainfed controls to contrast against.

The remaining 34 are `unknown`, which is the honest answer rather than a guess.
ISMN carries no irrigation attribute at all, which is why
`smml.sources.ismn.flag_likely_irrigated` exists.

## Table extraction — the higher-yield path

Digitizing a plotted curve recovers perhaps 5–15 points at ~2 % positional
error, after a calibration that does not amortize. **A table in a thesis
appendix carries 50–500 exact values**, and one parser handles every table in
the document.

Measured on a generated appendix PDF whose values are known: **88 of 88
recovered, with zero error.** Not a tolerance — reading a table involves no
tracing at all.

```bash
smml literature tables thesis.pdf --study-id 10.1234/xyz --out values.csv
```

Where those tables are is the other half. Journals strip appendices; degree
regulations force them in. So the harvest is ranked by *"does this contain a
depth × date table"* rather than *"is this about soil moisture"* — a different
question that gives a very different ordering:

| document | table probability |
|---|---|
| PhD thesis, neutron probe at 15 cm increments, data in Appendix C | **0.99** |
| IAEA-TECDOC, neutron scattering vs TDR across irrigated plots | 0.80 |
| Kansas AES limited-irrigation research report | 0.79 |
| *Machine learning prediction of root zone soil moisture from SMAP* | 0.04 |
| Review of soil moisture sensing technologies | 0.005 |

The modelling paper is highly relevant and publishes nothing. That is the point.

```bash
smml literature triage candidates.csv
smml literature repositories --list
```

Grey literature is reachable because almost all of it speaks **OAI-PMH** —
Digital Commons at `/do/oai/`, DSpace at `/oai/request` — so one harvester
covers the entire land-grant tier, CGSpace, Shodhganga and KrishiKosh. Dataverse
likewise gives every installation one API; ICRISAT Patancheru alone holds
neutron-probe profiles at 15 cm increments to 180 cm across decades.

## Searching in the languages the data is actually in

Most of the world's irrigated soil water measurements were not written in
English. `smml.litmine.multilingual` carries seed terms for Chinese, Persian,
Turkish, Spanish, Portuguese, Arabic, Russian, Japanese and Korean — and, more
importantly, the normalisation without which an exact match silently returns
nothing:

- **Persian** stores the same word with Arabic ي or Persian ی, inconsistently
  across Iranian databases, with zero-width non-joiners inside common compounds.
- **Turkish** has the dotted/dotless i: `"KISITLI".lower()` gives `kisitli`, not
  `kısıtlı`. The classic Turkish-I bug corrupts every token containing the letter.
- **Arabic** scanned-PDF text layers are full of presentation forms that render
  identically to base letters and never match them.
- **Portuguese** splits BR/PT on exactly the query words — umidade/humidade,
  irrigação/rega, nêutrons/neutrões.

Hindi and the other Indian languages are *deliberately skipped*, and the module
raises if you ask for them: Indian agricultural research publishes in English,
and that effort belongs in Shodhganga and KrishiKosh instead.

## Figure digitization

A large share of irrigated-field soil moisture exists only as ink in a paper.
Two modes, tried in this order:

**Vector.** A figure embedded in a PDF as vector graphics still carries the
polyline coordinates of every series. Reading the drawing operators recovers the
original numbers exactly — not an estimate. This usually works on a modern paper
and costs nothing.

**Raster.** Otherwise: detect the axes, calibrate, separate series, trace.
Round-trip tested against plots of known data, recovery is **~0.002 m³/m³ RMSE,
max error <0.009** — an order of magnitude below dielectric sensor accuracy.

Two things in there exist because of measured failures rather than foresight.
Clustering colours in RGB reported **seven** series for a three-series plot,
because anti-aliasing ramps every line toward the page background; clustering by
hue instead gives exactly one per series. And a per-column median was dragged
onto the **legend swatch**, which is the same colour and sits inside the axes,
for errors of 0.13 m³/m³ — three times the size of the signal. Tracing by
Viterbi shortest path fixes it, and also rejoins curves broken by crossings.

## Deciding what counts as irrigated

Nothing in the world records this directly. ISMN has no irrigation attribute.
An extent map answers "was this 30 m pixel irrigated somewhere this year", which
is not the question — a pivot corner, a field edge, or a station on the unmanaged
margin of an irrigated quarter-section all read as irrigated and are not.

So the label is **derived**, and the rule everything follows from is that
evidence is never collapsed into a boolean at ingest. Each raster sample, each
sentence in a paper, each moisture signature is stored as its own row, and the
label comes from a versioned fusion. When a better map ships, the label is
re-derived; nothing is re-ingested.

Three behaviours worth knowing:

- **A declared method outweighs any number of extent maps.** Maps are the most
  abundant evidence and the least valid at a point, so abundance must not
  outvote a single authoritative statement.
- **Correlated maps do not vote twice.** Products trained on overlapping imagery
  share their errors, so agreeing with itself five times counts barely more than
  twice.
- **A two-treatment study is flagged, not averaged.** Almost every irrigation
  experiment has a rainfed control, so "center pivot compared with a rainfed
  control" is the normal case. Fusing it gives a middling probability that is
  wrong in both directions; the honest output is
  `ambiguous_multi_treatment`, which says the source needs plot-level
  assignment before any of its rows can be used.

`uncertain` is a real answer. A station the evidence cannot settle belongs in
neither an irrigated nor a rainfed analysis.

## What may be published

Harvesting PDFs, extracting numbers from figures, and publishing the result are
three questions with three answers, and `smml.litmine.compliance` keeps them
separate. Run `smml compliance` before publishing anything.

Against the current registry: **102 of 168 sources** could have their rows
republished (60 of them requiring attribution), 18 are local-use only, and **47
have no usable licence recorded** — which is the number that matters, because a
licence recorded after ingest is usually a licence nobody can reconstruct.

This is a policy, not legal advice. `counsel_checklist()` lists the eight
questions a licensing search cannot settle.

## Recovering irrigation schedules

Most published irrigated-field studies plot soil moisture and never tabulate
when water was applied. A moisture rise that rainfall cannot explain is an
unrecorded input, so the schedule can be recovered from the moisture record
itself. Against the simulator's known schedule: **79 % median recall at 100 %
median precision**, amounts biased +2.4 mm.

It degrades where rain is frequent enough to be mistaken for irrigation — one
humid-climate test site scored 18 % precision. Use the confidence score.

---

## Layout

```
src/smml/
  registry/     168 catalogued sources, 24 technique recipes, 93 studies (YAML)
  sources/      harvest connectors (weather, soil + salinity)
  litmine/      discovery, triage, table extraction, figure digitization,
                grey-literature harvest, cross-lingual terms, compliance
  db/           star schema; idempotent Parquet store with DuckDB views
  physics/      dielectric response, water retention, FAO-56, simulator
  qc/           quality control; irrigation inference
  features/     leakage-free feature construction
  models/       baselines, LightGBM, XGBoost, entity-aware LSTM
  eval/         metrics, spatiotemporal splits, CV runner, success criteria
  tune/         Optuna search, nested CV
  irrigation/   evidence fusion into a calibrated irrigated/rainfed label
  cli/          command line interface
tests/          unit tests, integration tests, API response fixtures
docs/research/  the research sweep's own output, preserved verbatim
```

## Verification

```bash
pytest tests/unit            # 413 fast tests
pytest tests/integration     # 14 end-to-end tests (~2 min)
pytest                       # all 427, no network required
```

What is checked, and against what:

- **Reference ET** matches the independent `refet` implementation of ASCE/FAO-56
  to 0.02 % across six climates.
- **The water balance closes** to <0.05 mm over three years for every texture
  and every irrigation method.
- **The four-phase dielectric mixing law** is satisfied exactly — the solution is
  closed-form, after a fixed-point formulation turned out to contract by only
  ~0.9 per pass in dry clay and not converge usefully.
- **Clay and salinity biases** move in the directions the physics requires, and
  salinity affects low-frequency probes while sparing TDR.
- **Digitization** recovers plotted values to ~0.002 m³/m³.
- **Connector parsers** handle each service's documented traps.
- **QC detectors** are tested against injected faults *and* against legitimate
  behaviour they must not flag.

The integration suite re-measures the load-bearing claims on every run rather
than trusting this README:

- the clay-corrected target is the one actually selected, and fitting to it
  reduces both bias and RMSE against true water content;
- a random k-fold really does score better than a site split — if they ever tie,
  either the split is broken or a feature is carrying site identity across the
  boundary;
- no feature correlates with the target above 0.95, which is the signature of
  leakage through a lagged copy or a bad join;
- a learned model has within-site temporal skill where the static baseline has
  exactly none;
- an interrupted hyperparameter search resumes rather than restarting;
- writing the same observations twice is a no-op.

## Known limitations

- No connector has been run against a live API (see above).
- The synthetic corpus is generated by a tipping-bucket model parameterized with
  Saxton-Rawls pedotransfer functions, which makes a Saxton-Rawls baseline
  unusually strong on it. Treat cross-model comparisons on synthetic data as a
  test of the machinery, not as evidence about real soils.
- The bound-water model has a single tuning constant
  (`BOUND_WATER_PER_CLAY = 0.002` m³/m³ per percent clay, roughly illitic). Fit
  it per soil wherever gravimetric calibration samples exist; use ~0.003 for
  smectitic and ~0.001 for kaolinitic.
- `EALSTMModel` is implemented and unit-tested but has not been benchmarked
  against the boosted trees at corpus scale.
- Of the 71 catalogued in-situ networks, 21 are classified as having irrigated
  stations and 16 as explicitly rainfed; **34 are `unknown`**. The classification
  is derived from prose in each entry and is deliberately conservative — confirm
  any of them against an irrigation extent map before treating it as fact.
- 91 of the 168 source entries are marked `recalled` rather than `confirmed`.
  Their endpoints came from model knowledge, not from a verified response.

## Licence

MIT for the code. Harvested data carries its own licence — every source in the
registry records one, and `redistributable` says whether the rows may be
republished or only used locally. Check before sharing any derived database.
