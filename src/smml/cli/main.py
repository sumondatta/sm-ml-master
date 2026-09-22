"""Command line interface.

Every stage of the pipeline is a subcommand, and each writes its output to the
database so the next can pick it up. The stages are independent on purpose: the
harvest takes days and is network-bound, the modelling takes hours and is
CPU-bound, and coupling them would mean a network failure costing a training
run.

    smml registry summary                 what sources are catalogued
    smml harvest weather --sites sites.csv
    smml harvest soil    --sites sites.csv
    smml literature discover              find papers and datasets
    smml literature digitize FIG.png      recover numbers from a figure
    smml literature tables THESIS.pdf     recover numbers from tables (far higher yield)
    smml literature triage cands.csv      rank documents by expected table yield
    smml literature repositories --list   grey-literature sources
    smml verify endpoints                 probe the catalogue, report what is broken
    smml simulate                         generate a synthetic corpus
    smml qc                               run the quality control suite
    smml train                            fit and cross-validate
    smml tune                             hyperparameter search
    smml evaluate                         compare models and baselines
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

app = typer.Typer(add_completion=False, help=__doc__, no_args_is_help=True)
registry_app = typer.Typer(help="Inspect the catalogue of data sources.", no_args_is_help=True)
harvest_app = typer.Typer(help="Fetch data from external sources.", no_args_is_help=True)
literature_app = typer.Typer(help="Discover and mine the literature.", no_args_is_help=True)
verify_app = typer.Typer(help="Check that catalogued endpoints are reachable.",
                         no_args_is_help=True)
app.add_typer(registry_app, name="registry")
app.add_typer(harvest_app, name="harvest")
app.add_typer(literature_app, name="literature")
app.add_typer(verify_app, name="verify")

console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def _print_frame(frame, title: str, max_rows: int = 40, wrap: bool = False) -> None:
    """Render a frame as a table, one terminal row per record by default.

    Folding long cells onto several lines makes a catalogue listing unreadable —
    a twenty-row table becomes a hundred lines and the columns stop aligning by
    eye. Values are truncated instead, and the full entry is one
    `smml registry show <short_id>` away.
    """
    table = Table(title=title, show_lines=False, header_style="bold")
    for column in frame.columns:
        table.add_column(str(column), overflow="fold" if wrap else "ellipsis",
                         no_wrap=not wrap)
    for _, row in frame.head(max_rows).iterrows():
        table.add_row(*[f"{v:.4f}" if isinstance(v, float) else str(v) for v in row])
    console.print(table)
    if len(frame) > max_rows:
        console.print(f"[dim]... {len(frame) - max_rows} more rows[/dim]")


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


@registry_app.command("summary")
def registry_summary() -> None:
    """Counts of catalogued sources, techniques and studies."""
    from .. import registry

    console.print_json(json.dumps(registry.summary(), indent=2))


@registry_app.command("list")
def registry_list(
    category: str = typer.Option(None, help="in_situ_network, soil_property, weather_forcing, "
                                            "irrigation_extent, remote_sensing, repository"),
    max_priority: int = typer.Option(3, help="1 = must have, 3 = nice to have"),
    confirmed_only: bool = typer.Option(False, help="Only entries corroborated by a search result"),
) -> None:
    """List catalogued sources."""
    import pandas as pd

    from .. import registry

    items = registry.sources(
        category=category, max_priority=max_priority,
        min_confidence="confirmed" if confirmed_only else None,
    )
    if not items:
        console.print("[yellow]no sources match[/yellow]")
        raise typer.Exit()
    frame = pd.DataFrame(items)[
        ["priority", "short_id", "name", "category", "confidence"]
    ].sort_values(["priority", "category", "short_id"]).rename(
        columns={"priority": "pri", "confidence": "conf"}
    )
    frame["name"] = frame["name"].str.slice(0, 56)
    _print_frame(frame, f"{len(frame)} sources", max_rows=200)


@registry_app.command("show")
def registry_show(short_id: str) -> None:
    """Everything catalogued about one source."""
    from .. import registry

    console.print_json(json.dumps(registry.source(short_id), indent=2, default=str))


@registry_app.command("networks")
def registry_networks(
    irrigated: bool = typer.Option(False, help="Only networks with stations on irrigated cropland"),
    rainfed: bool = typer.Option(False, help="Only networks explicitly sited away from irrigation"),
) -> None:
    """List in-situ soil moisture networks."""
    import pandas as pd

    from .. import registry

    selector = True if irrigated else (False if rainfed else None)
    items = registry.networks(irrigated=selector)
    frame = pd.DataFrame(items)
    columns = [c for c in ("priority", "short_id", "name", "in_ismn", "irrigated_stations")
               if c in frame.columns]
    # Sorted by priority, then the column is dropped: it renders as a squeezed
    # sliver at terminal width and the ordering already carries it.
    frame = frame[columns].sort_values(["priority", "short_id"]).drop(columns=["priority"])
    frame = frame.rename(columns={"in_ismn": "ismn", "irrigated_stations": "irrig"})
    # These fields are prose and destroy the table layout; the full entry is one
    # `smml registry show <short_id>` away.
    frame["name"] = frame["name"].str.slice(0, 52)
    _print_frame(frame, f"{len(frame)} in-situ networks", max_rows=100)


@registry_app.command("studies")
def registry_studies(
    figure_only: bool = typer.Option(False, help="Only studies whose data exists solely in figures"),
    open_data: bool = typer.Option(False, help="Only studies with an archived dataset"),
) -> None:
    """List catalogued published studies."""
    import pandas as pd

    from .. import registry

    items = registry.studies(
        figure_only=figure_only or None,
        with_open_data=open_data or None,
    )
    frame = pd.DataFrame(items)
    columns = [c for c in ("citation", "location", "crop", "irrigation_method",
                           "depths_cm", "data_availability") if c in frame.columns]
    _print_frame(frame[columns], f"{len(frame)} studies", max_rows=200)


# --------------------------------------------------------------------------
# harvest
# --------------------------------------------------------------------------


@harvest_app.command("weather")
def harvest_weather(
    sites: Path = typer.Option(..., exists=True, help="CSV with site_id, lat, lon"),
    source: str = typer.Option("nasa_power", help="nasa_power | daymet_v4 | open_meteo"),
    start: str = typer.Option("2000-01-01"),
    end: str = typer.Option("2024-12-31"),
    out: Path = typer.Option(None, help="Database root; defaults to SMML_DATA_ROOT"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fetch daily weather for every site."""
    import pandas as pd

    from ..db.store import Store
    from ..sources.weather import WEATHER_CONNECTORS

    _setup_logging(verbose)
    frame = pd.read_csv(sites)
    connector = WEATHER_CONNECTORS[source]()
    result = connector.fetch_many(frame, start=start, end=end)
    store = Store(out)
    written = store.write("weather", result.weather) if not result.weather.empty else 0
    console.print(f"[green]wrote {written:,} weather rows[/green]")
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} sites failed[/yellow]")
        for message in result.errors[:10]:
            console.print(f"  [dim]{message}[/dim]")


@harvest_app.command("soil")
def harvest_soil(
    sites: Path = typer.Option(..., exists=True, help="CSV with site_id, lat, lon"),
    source: str = typer.Option("soilgrids_rest", help="soilgrids_rest | usda_sda"),
    out: Path = typer.Option(None),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fetch soil properties for every site."""
    import pandas as pd

    from ..db.store import Store
    from ..sources.soil import SOIL_CONNECTORS

    _setup_logging(verbose)
    frame = pd.read_csv(sites)
    connector = SOIL_CONNECTORS[source]()
    result = connector.fetch_batch(frame) if source == "usda_sda" else connector.fetch_many(frame)
    store = Store(out)
    written = store.write("sites", result.sites, mode="upsert") if not result.sites.empty else 0
    console.print(f"[green]wrote {written:,} site-layer rows[/green]")
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} sites failed[/yellow]")


# --------------------------------------------------------------------------
# literature
# --------------------------------------------------------------------------


@literature_app.command("discover")
def literature_discover(
    max_per_source: int = typer.Option(2000),
    repositories_only: bool = typer.Option(False, help="Skip article databases"),
    out: Path = typer.Option(None),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Search repositories and article databases for candidate studies."""
    from ..db.store import Store
    from ..litmine.discover import discover_all, screen_works

    _setup_logging(verbose)
    result = discover_all(max_per_source=max_per_source, include_articles=not repositories_only)
    works = screen_works(result.works)
    console.print(f"[green]{len(works):,} works, {len(result.datasets):,} datasets[/green]")
    if not works.empty:
        _print_frame(works.head(20)[["relevance_score", "year", "title"]], "top candidates", 20)
    store = Store(out)
    path = store.write_manifest("literature_discovery", {
        "n_works": len(works), "n_datasets": len(result.datasets), "errors": result.errors,
    })
    if not works.empty:
        works.to_parquet(store.root / "_literature_works.parquet", index=False)
    if not result.datasets.empty:
        result.datasets.to_parquet(store.root / "_literature_datasets.parquet", index=False)
    console.print(f"[dim]manifest: {path}[/dim]")


@literature_app.command("digitize")
def literature_digitize(
    figure: Path = typer.Argument(..., exists=True, help="PNG/JPG figure, or a PDF page"),
    x_min: float = typer.Option(..., help="Value at the left edge of the axes"),
    x_max: float = typer.Option(...),
    y_min: float = typer.Option(..., help="Value at the bottom of the axes"),
    y_max: float = typer.Option(...),
    out: Path = typer.Option(None, help="CSV to write"),
    page: int = typer.Option(0, help="PDF page number"),
) -> None:
    """Recover numeric series from a plotted figure.

    For a PDF the vector paths are tried first, which is exact. A raster figure
    falls back to colour tracing, whose uncertainty is reported per series.
    """
    import numpy as np
    import pandas as pd

    from ..litmine.digitize import (
        calibration_from_frame,
        detect_plot_frame,
        digitize_raster,
        extract_vector_paths,
        validate_series,
    )

    _setup_logging(False)
    if figure.suffix.lower() == ".pdf":
        paths = extract_vector_paths(figure, page)
        console.print(f"[green]{len(paths)} vector paths found[/green] "
                      "[dim](exact coordinates; calibrate against the axis limits)[/dim]")
        rows = [{"path": i, "n_points": p["n_points"], "colour": p["colour"]}
                for i, p in enumerate(paths)]
        _print_frame(pd.DataFrame(rows), "vector paths")
        return

    from PIL import Image

    image = np.array(Image.open(figure).convert("RGB"))
    frame = detect_plot_frame(image)
    if frame is None:
        console.print("[red]could not locate the plot frame[/red]")
        raise typer.Exit(code=1)
    calibration = calibration_from_frame(frame, x_min, x_max, y_min, y_max)
    series = digitize_raster(image, calibration, frame=frame)

    rows = []
    frames = []
    for s in series:
        ok, problems = validate_series(s)
        rows.append({"series": s.label, "n": s.n_points, "colour": s.colour,
                     "y_uncertainty": round(s.y_uncertainty, 5),
                     "valid": ok, "notes": "; ".join(problems)})
        frames.append(pd.DataFrame({"series": s.label, "x": s.x, "y": s.y}))
    _print_frame(pd.DataFrame(rows), f"{len(series)} series recovered")
    if out and frames:
        pd.concat(frames, ignore_index=True).to_csv(out, index=False)
        console.print(f"[green]wrote {out}[/green]")


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------


@app.command("simulate")
def simulate(
    n_sites: int = typer.Option(60),
    years: int = typer.Option(4),
    seed: int = typer.Option(20240501),
    out: Path = typer.Option(Path("data/interim"), help="Directory for the parquet output"),
) -> None:
    """Generate a synthetic corpus for testing the pipeline end to end."""
    from ..physics.simulator import generate_corpus

    _setup_logging(False)
    observations, sites = generate_corpus(n_sites=n_sites, years=years, seed=seed)
    out.mkdir(parents=True, exist_ok=True)
    observations.to_parquet(out / "synthetic_observations.parquet", index=False)
    sites.to_parquet(out / "synthetic_sites.parquet", index=False)
    console.print(f"[green]{len(observations):,} observations at {len(sites)} sites[/green]")
    console.print(f"[dim]{out}/synthetic_observations.parquet[/dim]")


@app.command("train")
def train(
    data: Path = typer.Option(Path("data/interim"), help="Directory with observations and sites parquet"),
    model: str = typer.Option("lightgbm", help="lightgbm | xgboost | ea_lstm | baselines"),
    split: str = typer.Option("leave_site_out"),
    folds: int = typer.Option(5),
    target: str = typer.Option("theta_obs_m3m3"),
    truth: str = typer.Option("theta_true_m3m3", help="Score against this where present"),
    out: Path = typer.Option(None, help="Directory for artifacts"),
    clay_correction: bool = typer.Option(
        True, help="Train on the clay-corrected reading. Without it the model "
                   "reproduces the sensor's texture bias."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fit a model under a leakage-free split and report stratified metrics."""
    from ._pipeline import run_training

    _setup_logging(verbose)
    result = run_training(data, model, split, folds, target, truth, out, console,
                          use_clay_correction=clay_correction)
    console.print(f"\n[bold green]{result}[/bold green]")


@app.command("tune")
def tune(
    data: Path = typer.Option(Path("data/interim")),
    model: str = typer.Option("lightgbm", help="lightgbm | xgboost"),
    trials: int = typer.Option(50),
    inner_folds: int = typer.Option(3),
    metric: str = typer.Option("rmse"),
    study: str = typer.Option("smml"),
    sample: float = typer.Option(1.0, help="Fraction of rows to use during the search"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Search hyperparameters with site-disjoint inner folds."""
    from ._pipeline import run_tuning

    _setup_logging(verbose)
    run_tuning(data, model, trials, inner_folds, metric, study, sample, console)


@app.command("evaluate")
def evaluate(
    data: Path = typer.Option(Path("data/interim")),
    split: str = typer.Option("leave_site_out"),
    folds: int = typer.Option(5),
    include_optimism: bool = typer.Option(
        False, help="Also score under a random k-fold to quantify how much it lies"
    ),
    clay_correction: bool = typer.Option(True, help="Train on the clay-corrected reading"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Compare every model against the baselines on identical folds."""
    from ._pipeline import run_evaluation

    _setup_logging(verbose)
    run_evaluation(data, split, folds, include_optimism, console,
                   use_clay_correction=clay_correction)


@app.command("qc")
def qc(
    data: Path = typer.Option(Path("data/interim")),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the quality control suite and report flag rates."""
    import pandas as pd

    from ..qc.checks import qc_summary, run_qc

    _setup_logging(verbose)
    observations = pd.read_parquet(data / "synthetic_observations.parquet")
    sites = pd.read_parquet(data / "synthetic_sites.parquet")
    frame = observations.rename(columns={"theta_obs_m3m3": "theta_m3m3"}).copy()
    frame["time_utc"] = pd.to_datetime(frame["date"])
    frame["method"] = "fdr_capacitance"
    join = [c for c in ("clay_pct", "porosity_m3m3", "ece_ds_m", "sensor_frequency_mhz")
            if c in sites.columns]
    frame = frame.merge(sites[["site_id", *join]], on="site_id").rename(
        columns={"sensor_frequency_mhz": "instrument_frequency_mhz"}
    )
    result = run_qc(frame, theta_col="theta_m3m3", date_col="time_utc")
    _print_frame(qc_summary(result), "quality control")
    console.print(f"[green]{len(result):,} observations flagged, none dropped[/green]")


@literature_app.command("tables")
def literature_tables(
    pdf: Path = typer.Argument(..., exists=True, help="PDF to extract soil water tables from"),
    study_id: str = typer.Option("", help="DOI or identifier to stamp on every value"),
    min_score: float = typer.Option(0.5, help="Reject tables below this table-likeness score"),
    out: Path = typer.Option(None, help="CSV to write the long-format values to"),
    show_rejected: bool = typer.Option(False, help="Also list the tables that were rejected"),
) -> None:
    """Recover soil water values from tables in a document.

    Higher yield than digitizing figures by roughly two orders of magnitude, and
    the values are exact rather than traced. Theses and experiment station
    reports are where these tables live.
    """
    import pandas as pd

    from ..litmine.tables import harvest_tables

    _setup_logging(False)
    values, tables = harvest_tables(pdf, study_id=study_id, min_score=min_score)

    summary = pd.DataFrame([{
        "pg": t.page, "shape": f"{t.shape[0]}x{t.shape[1]}",
        "score": round(t.score, 2), "basis": t.basis, "unit": t.unit,
        "depth": t.depth_axis or "", "ok": t.score >= min_score,
        "accepted": t.score >= min_score,
    } for t in tables])
    if not summary.empty and not show_rejected:
        summary = summary[summary["accepted"]]
    _print_frame(summary.drop(columns=["accepted"]), f"{len(tables)} tables found",
                 max_rows=40)

    if values.empty:
        console.print("[yellow]no soil water values recovered[/yellow]")
        console.print("[dim]Lower --min-score, or the tables may be images rather than "
                      "text — those need the figure digitizer instead.[/dim]")
        raise typer.Exit()

    console.print(f"[green]{len(values):,} values recovered[/green]")
    _print_frame(values.head(15)[["depth_top_cm", "depth_bottom_cm", "time_label",
                                  "value", "basis", "unit"]], "sample", max_rows=15)

    gravimetric = values[values["basis"] == "gravimetric"]
    if not gravimetric.empty:
        console.print(
            f"\n[yellow]{len(gravimetric):,} values are gravimetric.[/yellow] Converting "
            "them to volumetric needs a bulk density, which these documents often do not "
            "report. They are carried forward unconverted rather than guessed at."
        )
    if out:
        values.to_csv(out, index=False)
        console.print(f"[green]wrote {out}[/green]")


@literature_app.command("triage")
def literature_triage(
    candidates: Path = typer.Argument(..., exists=True,
                                      help="CSV with title, abstract and type columns"),
    out: Path = typer.Option(None, help="CSV to write the ranked list to"),
    top: int = typer.Option(25, help="How many to show"),
) -> None:
    """Rank documents by whether they contain a depth-by-date soil water table.

    Different from ranking by relevance, and the difference matters: a paper
    modelling soil moisture with machine learning is highly relevant and
    publishes no data.
    """
    import pandas as pd

    from ..litmine.triage import triage, yield_estimate

    _setup_logging(False)
    ranked = triage(pd.read_csv(candidates))
    if ranked.empty:
        console.print("[yellow]nothing to rank[/yellow]")
        raise typer.Exit()

    columns = [c for c in ("table_probability", "genre", "title") if c in ranked.columns]
    _print_frame(ranked.head(top)[columns], f"top {min(top, len(ranked))} of {len(ranked)}",
                 max_rows=top)
    _print_frame(yield_estimate(ranked), "expected yield by probability band", max_rows=10)
    if out:
        ranked.to_csv(out, index=False)
        console.print(f"[green]wrote {out}[/green]")


@literature_app.command("repositories")
def literature_repositories(
    list_only: bool = typer.Option(False, "--list", help="List the seed repositories"),
    only: str = typer.Option(None, help="Comma-separated short_ids to harvest"),
    max_records: int = typer.Option(2000, help="Per repository"),
    out: Path = typer.Option(None),
) -> None:
    """Harvest grey literature from OAI-PMH repositories.

    Theses and experiment station reports, which the article databases index
    worst and which carry the densest tables. Digital Commons and DSpace both
    speak OAI-PMH, so one harvester reaches the whole land-grant tier.
    """
    import pandas as pd

    from ..litmine.repositories import SEED_REPOSITORIES, harvest_seed_repositories
    from ..litmine.triage import triage

    _setup_logging(False)
    if list_only:
        frame = pd.DataFrame([{
            "short_id": r.short_id, "name": r.name[:40], "platform": r.platform,
            "country": r.country, "why": r.why[:60],
        } for r in SEED_REPOSITORIES])
        _print_frame(frame, f"{len(frame)} seed repositories", max_rows=40)
        console.print("[dim]Every URL is recalled, not verified. Run "
                      "`smml verify repositories` before trusting one.[/dim]")
        raise typer.Exit()

    selected = tuple(only.split(",")) if only else None
    records = harvest_seed_repositories(max_records_each=max_records, only=selected)
    if records.empty:
        console.print("[yellow]no records harvested[/yellow]")
        raise typer.Exit()

    ranked = triage(records, id_col="oai_identifier")
    console.print(f"[green]{len(ranked):,} records from "
                  f"{ranked['repository_id'].nunique()} repositories[/green]")
    _print_frame(ranked.head(20)[["table_probability", "genre", "title"]],
                 "most likely to contain a table", max_rows=20)
    if out:
        ranked.to_csv(out, index=False)
        console.print(f"[green]wrote {out}[/green]")


@verify_app.command("endpoints")
def verify_endpoints(
    category: str = typer.Option(None, help="Restrict to one source category"),
    recalled_only: bool = typer.Option(
        True, help="Only entries never corroborated by a search — where failures concentrate"
    ),
    limit: int = typer.Option(None, help="Stop after this many"),
    out: Path = typer.Option(Path("endpoint_report.csv"), help="CSV to write"),
) -> None:
    """Probe every catalogued endpoint and report which need fixing.

    91 of the 168 registry entries are recalled rather than verified, and no
    connector has ever contacted a live server. Run this on a machine with open
    internet; the CSV it writes is designed to be handed back for repair.
    """
    from ..util.verify import summarize, verify_registry

    _setup_logging(False)
    console.print("[dim]probing; this is rate-limited per host and will take a few "
                  "minutes[/dim]")
    report = verify_registry(category=category, recalled_only=recalled_only, limit=limit)
    if report.empty:
        console.print("[yellow]nothing to probe[/yellow]")
        raise typer.Exit()

    _print_frame(summarize(report), "results", max_rows=15)
    broken = report[report["needs_fix"]]
    if not broken.empty:
        console.print(f"\n[yellow]{len(broken)} endpoints need fixing[/yellow]")
        _print_frame(broken[["short_id", "status", "http_code", "url"]],
                     "needs fixing", max_rows=40)
    blocked = report[report["status"] == "blocked_by_egress_policy"]
    if not blocked.empty:
        console.print(f"[dim]{len(blocked)} were blocked by a network policy rather than "
                      "by the service; those results say nothing about the endpoint.[/dim]")
    report.to_csv(out, index=False)
    console.print(f"[green]wrote {out}[/green] — send this back and the connectors can "
                  "be fixed against it")


@verify_app.command("repositories")
def verify_repositories_cmd(
    out: Path = typer.Option(Path("repository_report.csv")),
) -> None:
    """Check the OAI-PMH seed repositories by speaking the protocol to them."""
    from ..util.verify import verify_repositories

    _setup_logging(False)
    report = verify_repositories()
    _print_frame(report[["short_id", "status", "reported_name", "earliest_record"]],
                 f"{len(report)} repositories", max_rows=40)
    alive = int((report["status"] == "alive").sum())
    console.print(f"[green]{alive} of {len(report)} answered as OAI endpoints[/green]")
    report.to_csv(out, index=False)
    console.print(f"[green]wrote {out}[/green]")


@app.command("compliance")
def compliance(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """What the catalogued sources permit: fetching, extraction, republication.

    Run this before publishing anything derived from the harvest. The three
    questions have three different answers and conflating them is how a database
    becomes unpublishable after the work is done.
    """
    import pandas as pd

    from .. import registry
    from ..litmine.compliance import (
        attribution_manifest,
        compliance_report,
        counsel_checklist,
        gate,
    )

    _setup_logging(verbose)
    items = pd.DataFrame(registry.sources())
    _print_frame(compliance_report(items), "catalogued sources by verdict", max_rows=30)

    decided = gate(items, "redistribute")
    undeclared = decided[decided["redistribute_verdict"] == "deny"]
    if not undeclared.empty:
        console.print(
            f"\n[yellow]{len(undeclared)} sources have no usable licence recorded.[/yellow] "
            "Their rows cannot be republished until one is, and a licence recorded "
            "after ingest is usually a licence nobody can reconstruct."
        )
        _print_frame(undeclared[["short_id", "name", "licence"]].head(15),
                     "licence not recorded", max_rows=15)

    manifest = attribution_manifest(items, citation_col="citation")
    console.print(f"\n[green]{len(manifest)} sources would require attribution[/green]")

    console.print("\n[bold]Questions a licensing search cannot settle:[/bold]")
    for question in counsel_checklist():
        console.print(f"  • {question}")
    console.print("\n[dim]This is a policy, not legal advice. "
                  "See docs/research/compliance-and-licensing.md.[/dim]")


@app.command("irrigation-label")
def irrigation_label(
    evidence: Path = typer.Option(None, exists=True,
                                  help="CSV of evidence rows; omit for a worked demonstration"),
    out: Path = typer.Option(None, help="CSV to write the labels to"),
) -> None:
    """Fuse irrigation evidence into a calibrated label per station-year."""
    import pandas as pd

    from ..irrigation.label import fuse_all, label_error_budget

    _setup_logging(False)
    if evidence is None:
        console.print("[dim]no evidence file given; showing a worked example[/dim]")
        frame = pd.DataFrame([
            {"site_id": "declared_pivot", "year": 2020, "kind": "declared",
             "says_irrigated": True, "strength": 1.0, "method": "center_pivot"},
            {"site_id": "maps_only", "year": 2020, "kind": "extent_map",
             "says_irrigated": True, "strength": 0.9, "product": "lanid"},
            {"site_id": "maps_only", "year": 2020, "kind": "extent_map",
             "says_irrigated": True, "strength": 0.8, "product": "gmia"},
            {"site_id": "no_evidence", "year": 2020, "kind": "land_cover",
             "says_irrigated": True, "strength": 0.1},
            {"site_id": "stated_rainfed", "year": 2020, "kind": "declared",
             "says_irrigated": False, "strength": 1.0, "method": "rainfed"},
        ])
    else:
        frame = pd.read_csv(evidence)

    labels = fuse_all(frame)
    _print_frame(labels, "irrigation labels", max_rows=50)
    budget = label_error_budget(labels)
    console.print_json(json.dumps(budget, indent=2))
    console.print("[dim]`uncertain` is a real answer: a station the evidence cannot "
                  "settle belongs in neither an irrigated nor a rainfed analysis.[/dim]")
    if out:
        labels.to_csv(out, index=False)
        console.print(f"[green]wrote {out}[/green]")


@app.command("info")
def info() -> None:
    """Database contents and environment."""
    from .. import __version__, registry
    from ..db.store import Store
    from ..util.paths import data_root

    console.print(f"[bold]smml {__version__}[/bold]")
    console.print(f"data root: {data_root()}")
    _print_frame(Store().summary(), "database")
    console.print_json(json.dumps(registry.summary(), indent=2))


if __name__ == "__main__":
    app()
