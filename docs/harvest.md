# Harvest runbook

How to actually build the database. Read the network caveat in the README first:
no connector here has been run against a live API, so budget time for fixing an
endpoint or two.

## Order of operations

Work outward from the data that is cheapest and best.

**1. Repositories, before anything else.** A dataset in Zenodo, Dryad or Pangaea
is the numbers themselves — machine-readable, licensed, no digitization error.
Roughly half the catalogued studies have one.

```bash
smml literature discover --repositories-only
```

**2. In-situ networks.** ISMN is the single largest source and aggregates ~70
member networks. It needs free registration and is served as a bulk download
rather than an API, so it is fetched by hand once and parsed locally.

**3. Open-access full text.** Europe PMC serves JATS XML, in which tables are
markup rather than pictures of numbers. Its `FIG:` query prefix searches figure
captions, which finds exactly the papers whose data is plotted.

```bash
smml literature discover
```

**4. Figures.** Whatever is left. See below.

**5. Covariates last.** Only once you know which sites exist — soil and weather
are queried per site and there is no point fetching either for a site you will
discard.

```bash
smml harvest soil    --sites sites.csv --source soilgrids_rest
smml harvest weather --sites sites.csv --source nasa_power --start 2000-01-01
```

## Pacing

Every request goes through `PoliteSession`, which enforces a per-host minimum
interval, retries with exponential backoff and jitter, honours `Retry-After`, and
caches every response to a content-addressed store. A re-run after a crash costs
nothing and the raw bytes stay available for re-parsing.

Limits that are configured, and that will get you blocked if you raise them:

| host | interval | why |
|---|---|---|
| `rest.isric.org` | 1.0 s | SoilGrids fair use is ~5 calls/min; it is labelled beta and has had multi-week outages |
| `power.larc.nasa.gov` | 2.1 s | 30 unique queries per 60 s per IP, then HTTP 429 |
| `api.openalex.org` | 0.11 s | ~10 req/s secondary limit |
| `zenodo.org` | 2.1 s | 30 req/min since Nov 2025, authenticated or not |
| `api.core.ac.uk` | 6.0 s | very tight free-tier quota |

**Do not use the SoilGrids REST API for more than about a thousand points.** At
five calls a minute that is three hours, and the service is shared. Past that,
read the cloud-optimized GeoTIFFs; the registry entry has the path.

## Credentials

All free, all optional except the first if you intend to do real discovery.

```bash
export OPENALEX_API_KEY=...   # required since Feb 2026; anonymous is 100 credits/day,
                              # a registered key is 100,000. The old mailto polite
                              # pool is ignored now.
export UNPAYWALL_EMAIL=you@example.org
export ZENODO_TOKEN=...
export SMML_DATA_ROOT=/mnt/big-disk/smml
```

## Digitizing a figure

Try the PDF first. A figure embedded as vector graphics still carries the exact
polyline coordinates of every series, so extraction is exact rather than
approximate:

```bash
smml literature digitize paper.pdf --page 3
```

For a raster figure, supply the axis limits from the published axes:

```bash
smml literature digitize fig3.png --x-min 0 --x-max 180 --y-min 0.10 --y-max 0.45 --out fig3.csv
```

Round-trip accuracy on plots of known data is ~0.002 m³/m³ RMSE, an order of
magnitude below dielectric sensor accuracy. Every series carries an uncertainty
derived from the calibration resolution and the traced line width, and
`validate_series` screens against physical range, impossible day-to-day steps and
too-few-points.

**Screen automatically, review by eye only what fails.** The failure that
survives everything is a misread axis label, which produces a plausible-looking
curve at entirely the wrong level.

### Licensing

Digitizing a figure for analysis is generally defensible under text-and-data-mining
provisions, and republishing the extracted values is a different question with
different answers by jurisdiction and publisher. The `studies` table records a
licence and `text_mining_allowed` per item; `sources.redistributable` says whether
harvested rows may be republished at all. Populate both at ingest — it cannot be
reconstructed later.

Paywalled PDFs are not downloaded. `UnpaywallClient` resolves a DOI to a legally
available copy first, and the open-access version is usually the same document.

## Scale

Expect the observation table to reach hundreds of millions of rows. It is
partitioned by `network` then `year` — the two filters essentially every query
applies, and the combination that keeps a partition workable without producing
tens of thousands of tiny files.

```python
from smml.db.store import Store
store = Store()
store.sql("""
    SELECT network, year, count(*) AS n, avg(theta_m3m3) AS mean
    FROM observations
    WHERE quality_flag = 'G' AND depth_top_cm < 15
    GROUP BY 1, 2 ORDER BY 1, 2
""")
```

DuckDB reads the Parquet directly with no load step, and a filter on a partition
column prunes files rather than scanning.

Writes are idempotent: every fact row has a deterministic key derived from its
content, so re-running a partially completed harvest adds only what is new.

## When it breaks

- **HTTP 429** — the limiter is too fast for that host. Raise its entry in
  `HOST_INTERVALS`. Never work around it with parallel IPs.
- **403 at a proxy** — an egress policy, not the service. Report the blocked host
  rather than routing around it.
- **An endpoint moved** — likely; the registry records `confirmed` vs `recalled`
  per entry. Fix the connector and update the YAML.
- **A parser fails on live data** — check the fixture in `tests/fixtures/` against
  the real response, update both, and add the difference as a test. That is what
  the fixtures are for.
