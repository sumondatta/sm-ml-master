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
| Source catalogue — 92 datasets, 93 studies | `smml.registry` | complete |
| Harvest connectors — weather, soil, salinity | `smml.sources` | written, parser-tested, **not run against live APIs** |
| Literature discovery — repositories, OpenAlex, Europe PMC | `smml.litmine.discover` | written, **not run against live APIs** |
| Figure digitization — vector + raster | `smml.litmine.digitize` | complete and measured |
| Database — star schema, idempotent Parquet + DuckDB | `smml.db` | complete |
| Sensor physics — clay, salinity, unit harmonization | `smml.physics` | complete and cross-validated |
| Quality control + irrigation inference | `smml.qc` | complete and measured |
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

```bash
smml simulate --n-sites 50 --years 4     # physics-based synthetic corpus
smml qc                                   # quality control
smml evaluate --include-optimism          # models vs baselines, and split honesty
smml tune --model lightgbm --trials 50    # hyperparameter search
```

## Run it on real data

```bash
smml registry list --category soil_property --max-priority 1
smml harvest soil    --sites sites.csv --source soilgrids_rest
smml harvest weather --sites sites.csv --source nasa_power --start 2000-01-01
smml literature discover
smml literature digitize figure3.png --x-min 0 --x-max 180 --y-min 0.10 --y-max 0.45
smml train --model lightgbm --split leave_site_out
```

---

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
  registry/     92 catalogued sources, 24 technique recipes, 93 studies (YAML)
  sources/      harvest connectors (weather, soil + salinity)
  litmine/      literature discovery; figure digitization
  db/           star schema; idempotent Parquet store with DuckDB views
  physics/      dielectric response, water retention, FAO-56, simulator
  qc/           quality control; irrigation inference
  features/     leakage-free feature construction
  models/       baselines, LightGBM, XGBoost, entity-aware LSTM
  eval/         metrics, spatiotemporal splits, CV runner
  tune/         Optuna search, nested CV
  cli/          command line interface
tests/          unit tests and API response fixtures
```

## Verification

```bash
pytest                       # unit tests, no network
pytest -m network            # live-API tests, skipped by default
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
- The in-situ network catalogue is thinner than the soil, weather and irrigation
  catalogues; that sweep had not returned when the registry was compiled.

## Licence

MIT for the code. Harvested data carries its own licence — every source in the
registry records one, and `redistributable` says whether the rows may be
republished or only used locally. Check before sharing any derived database.
