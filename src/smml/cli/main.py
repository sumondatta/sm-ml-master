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
app.add_typer(registry_app, name="registry")
app.add_typer(harvest_app, name="harvest")
app.add_typer(literature_app, name="literature")

console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def _print_frame(frame, title: str, max_rows: int = 40) -> None:
    table = Table(title=title, show_lines=False, header_style="bold")
    for column in frame.columns:
        table.add_column(str(column), overflow="fold")
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
        ["priority", "short_id", "name", "category", "access_method", "auth", "confidence"]
    ].sort_values(["priority", "category", "short_id"])
    _print_frame(frame, f"{len(frame)} sources", max_rows=200)


@registry_app.command("show")
def registry_show(short_id: str) -> None:
    """Everything catalogued about one source."""
    from .. import registry

    console.print_json(json.dumps(registry.source(short_id), indent=2, default=str))


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
    if source == "usda_sda":
        result = connector.fetch_batch(frame)
    else:
        result = connector.fetch_many(frame)
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
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fit a model under a leakage-free split and report stratified metrics."""
    from ._pipeline import run_training

    _setup_logging(verbose)
    result = run_training(data, model, split, folds, target, truth, out, console)
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
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Compare every model against the baselines on identical folds."""
    from ._pipeline import run_evaluation

    _setup_logging(verbose)
    run_evaluation(data, split, folds, include_optimism, console)


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
