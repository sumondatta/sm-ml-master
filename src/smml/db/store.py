"""Idempotent partitioned-Parquet store with a DuckDB query surface.

The harvest is long-running, interruptible, and repeatedly re-run as connectors
are fixed. That makes idempotence the central requirement: writing the same
observations twice must leave the database unchanged, and re-running a partially
completed harvest must not duplicate anything. Every fact table therefore has a
deterministic primary key (see :mod:`smml.util.ids`) and writes deduplicate
against what is already on disk within the affected partitions.

DuckDB reads the Parquet directly — no load step, no second copy, and partition
pruning from the Hive-style directory layout.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ..util.paths import processed_dir
from .schema import TABLES, TableSpec

log = logging.getLogger(__name__)

COMPRESSION = "zstd"
COMPRESSION_LEVEL = 6
TARGET_ROWS_PER_GROUP = 200_000


class Store:
    """The harmonized database on disk.

    Parameters
    ----------
    root:
        Directory holding one subdirectory per table. Defaults to the processed
        data directory, which honours ``SMML_DATA_ROOT``.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else processed_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- layout ----------------------------------------------------------

    def table_path(self, table: str) -> Path:
        return self.root / table

    def spec(self, table: str) -> TableSpec:
        if table not in TABLES:
            raise KeyError(f"unknown table {table!r}; known: {sorted(TABLES)}")
        return TABLES[table]

    def exists(self, table: str) -> bool:
        p = self.table_path(table)
        return p.exists() and any(p.rglob("*.parquet"))

    # -- writing ---------------------------------------------------------

    def write(
        self,
        table: str,
        frame: pd.DataFrame | pa.Table,
        mode: str = "upsert",
    ) -> int:
        """Write rows, returning the number actually added.

        ``mode``:

        ``upsert``
            Default. Rows whose primary key already exists are dropped; new rows
            are appended. This is what makes a re-run free.
        ``replace``
            Rewrite the touched partitions from scratch. Use when a connector's
            parsing has been corrected and the old rows are wrong rather than
            merely duplicated.
        ``append``
            Append blindly. Faster, and correct only when the caller can
            guarantee the rows are new.
        """
        spec = self.spec(table)
        arrow = self._coerce(frame, spec)
        if arrow.num_rows == 0:
            return 0

        if mode == "upsert":
            arrow = self._drop_existing(spec, arrow)
            if arrow.num_rows == 0:
                log.debug("%s: all rows already present", table)
                return 0
        elif mode == "replace":
            self._delete_partitions(spec, arrow)
        elif mode != "append":
            raise ValueError(f"mode must be upsert, replace or append; got {mode!r}")

        out = self.table_path(table)
        out.mkdir(parents=True, exist_ok=True)
        pq.write_to_dataset(
            arrow,
            root_path=str(out),
            partition_cols=list(spec.partition_cols) or None,
            compression=COMPRESSION,
            compression_level=COMPRESSION_LEVEL,
            row_group_size=TARGET_ROWS_PER_GROUP,
            existing_data_behavior="overwrite_or_ignore",
            use_dictionary=True,
        )
        log.info("%s: wrote %d rows", table, arrow.num_rows)
        return arrow.num_rows

    def _coerce(self, frame: pd.DataFrame | pa.Table, spec: TableSpec) -> pa.Table:
        """Project onto the declared schema, filling absent optional columns.

        Being permissive about missing columns matters: a connector for a network
        that reports no soil temperature should not have to know about the
        column. Being strict about *unknown* columns matters just as much, since
        a typo would otherwise silently create a shadow field.
        """
        if isinstance(frame, pa.Table):
            frame = frame.to_pandas()
        frame = frame.copy()

        declared = {f.name for f in spec.schema}
        extra = set(frame.columns) - declared
        if extra:
            raise ValueError(
                f"{spec.name}: columns not in the schema: {sorted(extra)}. "
                "Add them to the schema deliberately rather than by accident."
            )

        for field in spec.schema:
            if field.name not in frame.columns:
                if not field.nullable:
                    raise ValueError(f"{spec.name}: required column {field.name!r} is missing")
                frame[field.name] = None

        frame = frame[[f.name for f in spec.schema]]

        # Timestamps need explicit UTC localization before Arrow will accept the
        # tz-aware type.
        for field in spec.schema:
            if pa.types.is_timestamp(field.type) and field.type.tz:
                col = pd.to_datetime(frame[field.name], errors="coerce", utc=True)
                frame[field.name] = col
            elif pa.types.is_date(field.type):
                frame[field.name] = pd.to_datetime(frame[field.name], errors="coerce").dt.date

        return pa.Table.from_pandas(frame, schema=spec.schema, preserve_index=False)

    def _partition_filter(self, spec: TableSpec, arrow: pa.Table) -> dict[str, list[Any]] | None:
        """The distinct partition values the incoming rows touch."""
        if not spec.partition_cols:
            return None
        return {
            col: sorted({v for v in arrow.column(col).to_pylist() if v is not None})
            for col in spec.partition_cols
        }

    def _drop_existing(self, spec: TableSpec, arrow: pa.Table) -> pa.Table:
        """Remove rows whose primary key is already stored.

        Only the partitions the incoming rows touch are read, so the cost scales
        with the write rather than with the size of the database.
        """
        if not self.exists(spec.name):
            return self._dedupe_within(spec, arrow)

        arrow = self._dedupe_within(spec, arrow)
        keys = list(spec.primary_key)
        parts = self._partition_filter(spec, arrow)

        try:
            dataset = ds.dataset(self.table_path(spec.name), format="parquet", partitioning="hive")
            expr = None
            if parts:
                for col, values in parts.items():
                    field_expr = ds.field(col).isin(values)
                    expr = field_expr if expr is None else (expr & field_expr)
            existing = dataset.to_table(columns=keys, filter=expr)
        except (pa.ArrowInvalid, FileNotFoundError, OSError) as exc:
            log.warning("%s: could not read existing keys (%s); appending without dedup",
                        spec.name, exc)
            return arrow

        if existing.num_rows == 0:
            return arrow

        seen = set(map(tuple, existing.to_pandas()[keys].itertuples(index=False, name=None)))
        incoming = arrow.select(keys).to_pandas()
        mask = [tuple(row) not in seen for row in incoming.itertuples(index=False, name=None)]
        return arrow.filter(pa.array(mask))

    def _dedupe_within(self, spec: TableSpec, arrow: pa.Table) -> pa.Table:
        """Drop duplicate primary keys inside a single write, keeping the first."""
        keys = list(spec.primary_key)
        frame = arrow.select(keys).to_pandas()
        mask = ~frame.duplicated(subset=keys, keep="first")
        if mask.all():
            return arrow
        return arrow.filter(pa.array(mask.to_numpy()))

    def _delete_partitions(self, spec: TableSpec, arrow: pa.Table) -> None:
        parts = self._partition_filter(spec, arrow)
        base = self.table_path(spec.name)
        if not parts or not base.exists():
            return
        # Hive layout: col=value nested in declared partition order.
        import itertools
        import shutil

        for combo in itertools.product(*(parts[c] for c in spec.partition_cols)):
            target = base
            for col, val in zip(spec.partition_cols, combo, strict=True):
                target = target / f"{col}={val}"
            if target.exists():
                shutil.rmtree(target)

    # -- reading ---------------------------------------------------------

    def dataset(self, table: str) -> ds.Dataset:
        spec = self.spec(table)
        return ds.dataset(self.table_path(table), format="parquet",
                          partitioning="hive" if spec.partition_cols else None)

    def read(
        self,
        table: str,
        columns: list[str] | None = None,
        filters: Any = None,
    ) -> pd.DataFrame:
        if not self.exists(table):
            return pd.DataFrame(columns=[f.name for f in self.spec(table).schema])
        return self.dataset(table).to_table(columns=columns, filter=filters).to_pandas()

    def connect(self) -> duckdb.DuckDBPyConnection:
        """A DuckDB connection with every existing table registered as a view.

        Views rather than tables: the Parquet files stay the single copy, and a
        query that filters on a partition column prunes files rather than
        scanning.
        """
        con = duckdb.connect()
        for name in TABLES:
            if self.exists(name):
                path = self.table_path(name)
                con.execute(
                    f"CREATE OR REPLACE VIEW {name} AS "
                    f"SELECT * FROM read_parquet('{path}/**/*.parquet', hive_partitioning=true)"
                )
        return con

    def sql(self, query: str) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(query).fetchdf()

    # -- introspection ---------------------------------------------------

    def summary(self) -> pd.DataFrame:
        """Row counts and on-disk size per table."""
        rows = []
        for name in TABLES:
            path = self.table_path(name)
            if not self.exists(name):
                rows.append({"table": name, "rows": 0, "files": 0, "bytes": 0})
                continue
            files = list(path.rglob("*.parquet"))
            n = sum(pq.ParquetFile(f).metadata.num_rows for f in files)
            rows.append({
                "table": name,
                "rows": n,
                "files": len(files),
                "bytes": sum(f.stat().st_size for f in files),
            })
        frame = pd.DataFrame(rows)
        frame["mb"] = (frame["bytes"] / 1e6).round(2)
        return frame

    def write_manifest(self, name: str, payload: dict) -> Path:
        """Record what a harvest run did, for reproducibility."""
        manifest_dir = self.root / "_manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        path = manifest_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return path


def iter_batches(frame: pd.DataFrame, size: int = 500_000) -> Iterator[pd.DataFrame]:
    """Chunk a large frame so a write does not have to fit in memory twice."""
    for start in range(0, len(frame), size):
        yield frame.iloc[start : start + size]


def write_batched(store: Store, table: str, frames: Iterable[pd.DataFrame], mode: str = "upsert") -> int:
    total = 0
    for frame in frames:
        total += store.write(table, frame, mode=mode)
    return total
