from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from provider_adoption_data.models import DatasetRecord, Snapshot


NATURAL_KEYS: dict[str, list[str]] = {
    "pypi_downloads_daily": ["provider", "package_name", "with_mirrors", "download_date"],
    "npm_downloads_daily": ["provider", "package_name", "package_category", "download_date"],
    "huggingface_models_daily": ["provider", "author", "model_id", "download_date"],
    "github_repo_candidates_daily": ["provider", "repo_full_name", "repo_created_date"],
    "github_provider_signals_daily": ["provider", "repo_full_name", "signal_date", "signal_type"],
    "github_repo_rollup_daily": ["provider", "repo_full_name", "signal_date"],
    "github_provider_adoption_daily": ["provider", "signal_date"],
    "provider_momentum_daily": ["provider", "signal_date"],
}

DATASET_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "provider",
    "provider_display_name",
    "package_name",
    "package_type",
    "package_category",
    "with_mirrors",
    "download_date",
    "downloads",
    "author",
    "model_id",
    "hf_downloads_30d",
    "hf_downloads_all_time",
    "hf_downloads_daily_est",
    "hf_likes",
    "hf_last_modified",
    "repo_full_name",
    "repo_owner",
    "repo_name",
    "repo_html_url",
    "repo_created_date",
    "repo_created_at",
    "repo_pushed_at",
    "repo_default_branch",
    "language_bucket",
    "signal_date",
    "signal_type",
    "matched_file_path",
    "matched_pattern",
    "is_fork",
    "is_archived",
    "stargazers_count",
    "has_manifest_dependency",
    "has_code_import",
    "has_env_var",
    "has_model_name",
    "matched_signal_count",
    "pypi_7d_avg",
    "pypi_28d_avg",
    "pypi_share_28d",
    "pypi_growth_28d",
    "github_new_repo_count",
    "github_signal_repo_count",
    "github_manifest_repo_count",
    "github_repo_share",
    "github_import_repo_count",
    "github_env_repo_count",
    "github_model_repo_count",
    "momentum_score",
]

NUMERIC_COLUMNS = [
    "downloads",
    "hf_downloads_30d",
    "hf_downloads_all_time",
    "hf_downloads_daily_est",
    "hf_likes",
    "stargazers_count",
    "matched_signal_count",
    "pypi_7d_avg",
    "pypi_28d_avg",
    "pypi_share_28d",
    "pypi_growth_28d",
    "github_new_repo_count",
    "github_signal_repo_count",
    "github_manifest_repo_count",
    "github_repo_share",
    "github_import_repo_count",
    "github_env_repo_count",
    "github_model_repo_count",
    "momentum_score",
]

BOOL_COLUMNS = [
    "with_mirrors",
    "is_fork",
    "is_archived",
    "has_manifest_dependency",
    "has_code_import",
    "has_env_var",
    "has_model_name",
]

TEXT_COLUMNS = [
    column for column in DATASET_COLUMNS if column not in NUMERIC_COLUMNS and column not in BOOL_COLUMNS
]

SORT_KEYS: dict[str, list[str]] = {
    "pypi_downloads_daily": ["download_date", "provider", "package_category", "package_name", "with_mirrors"],
    "npm_downloads_daily": ["download_date", "provider", "package_category", "package_name"],
    "huggingface_models_daily": ["download_date", "provider", "author", "model_id"],
    "github_repo_candidates_daily": ["repo_created_date", "provider", "repo_full_name"],
    "github_provider_signals_daily": ["signal_date", "provider", "repo_full_name", "signal_type"],
    "github_repo_rollup_daily": ["signal_date", "provider", "repo_full_name"],
    "github_provider_adoption_daily": ["signal_date", "provider"],
    "provider_momentum_daily": ["signal_date", "provider"],
}

PARQUET_ONLY_DATASETS = {
    "github_repo_candidates_daily",
    "github_repo_rollup_daily",
}

# These two datasets grow by ~7200 append-only rows a day against ~917k rows
# already stored, so a single-file layout rewrote a 36 MB parquet blob every
# night for a 0.8% change.  Parquet is compressed binary, which git cannot
# delta, so each run added ~36 MB of incompressible history -- roughly 26 GB a
# year across the pair, which is what pushed the deployed checkout past its
# disk budget.  Storing one file per date means a day's update rewrites only
# the partitions it actually touched.
#
# The partition column is the dataset's own observation date, so a day's rows
# land in one partition.  Nothing outside this module needs to know: the
# directory is read and written through load_dataset/upsert_dataset like any
# other dataset.
PARTITION_COLUMNS: dict[str, str] = {
    "github_repo_candidates_daily": "repo_created_date",
    "github_repo_rollup_daily": "signal_date",
    # Same disease, smaller dose: these two rewrite a 3.7 MB and a 2.2 MB
    # monolith every day for an append-only day of rows.
    "huggingface_models_daily": "download_date",
    "github_provider_signals_daily": "signal_date",
}
_UNPARTITIONED = "__unpartitioned__"

# Partition files are only worth splitting if an unchanged partition keeps its
# exact bytes: git stores a rewritten-but-identical parquet as a brand new
# blob, which would put the whole 36 MB-a-night problem back.  Pandas dtypes
# are not stable across a parquet round-trip -- a bool column written from
# ``_coerce_types``' object dtype reads back as bool, and an all-present int
# column reads back as int64 where the concatenated frame held float64 -- so
# the same values would serialize to different bytes on consecutive runs.
# Pinning the Arrow schema removes that degree of freedom: bytes depend on
# values alone.
def _partition_arrow_schema() -> pa.Schema:
    fields = []
    for column in DATASET_COLUMNS:
        if column in BOOL_COLUMNS:
            arrow_type: pa.DataType = pa.bool_()
        elif column in NUMERIC_COLUMNS:
            arrow_type = pa.float64()
        else:
            arrow_type = pa.string()
        fields.append((column, arrow_type))
    return pa.schema(fields)


PARTITION_ARROW_SCHEMA = _partition_arrow_schema()


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "provider_adoption"
        self.normalized_root = base_dir / "data" / "normalized" / "provider_adoption"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots: Iterable[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            suffix = ".json" if snapshot.body.strip().startswith(("{", "[")) else ".txt"
            (run_dir / f"{snapshot.name}{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def partition_dir(self, dataset_id: str) -> Path:
        return self.normalized_root / dataset_id

    def partition_paths(self, dataset_id: str) -> list[Path]:
        """Every partition file for a partitioned dataset, oldest name first."""

        directory = self.partition_dir(dataset_id)
        if dataset_id not in PARTITION_COLUMNS or not directory.is_dir():
            return []
        return sorted(directory.glob("*.parquet"))

    @staticmethod
    def _partition_name(value: Any) -> str:
        """File stem for one partition value; blanks get an explicit bucket.

        A null observation date is real data, not a reason to drop the row, so
        it gets its own partition rather than being silently discarded or
        merged into an arbitrary date.
        """

        if value is None or pd.isna(value) or not str(value).strip():
            return _UNPARTITIONED
        # Keep the stem filesystem-safe without inventing a new date format.
        return str(value).strip().replace("/", "-")

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        partitions = self.partition_paths(dataset_id)
        if partitions:
            # A leftover single-file copy would silently double every row, so
            # the partitioned directory is authoritative once it exists.
            dataframe = pd.concat(
                [pd.read_parquet(path) for path in partitions], ignore_index=True
            )
        elif parquet_path.exists():
            dataframe = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            dataframe = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=DATASET_COLUMNS)
        for column in DATASET_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[DATASET_COLUMNS]

    def upsert_dataset(self, dataset_id: str, records: Iterable[DatasetRecord]) -> pd.DataFrame:
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=DATASET_COLUMNS)
        if incoming.empty:
            return self.load_dataset(dataset_id)

        existing = self.load_dataset(dataset_id)
        if not existing.empty:
            # Avoid pandas' changing dtype inference for schema-padding columns
            # that are entirely null in one side of the upsert. Restore the
            # canonical schema immediately after concatenating real columns.
            merged = pd.concat(
                [existing.dropna(axis=1, how="all"), incoming.dropna(axis=1, how="all")],
                ignore_index=True,
            )
            for column in DATASET_COLUMNS:
                if column not in merged.columns:
                    merged[column] = pd.NA
            merged = merged[DATASET_COLUMNS]
        else:
            merged = incoming.copy()
        merged = self._coerce_types(merged)
        merged = merged.drop_duplicates(subset=NATURAL_KEYS[dataset_id], keep="last")
        merged = merged.sort_values(by=SORT_KEYS[dataset_id], na_position="last").reset_index(drop=True)

        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        if dataset_id in PARTITION_COLUMNS:
            self._write_partitions(dataset_id, merged)
            # The pre-partition single file is now a stale duplicate of the
            # whole dataset; leaving it behind would double-count on any reader
            # that still prefers it.
            parquet_path.unlink(missing_ok=True)
            csv_path.unlink(missing_ok=True)
            return merged
        merged.to_parquet(parquet_path, index=False)
        if dataset_id in PARQUET_ONLY_DATASETS:
            csv_path.unlink(missing_ok=True)
        else:
            merged.to_csv(csv_path, index=False)
        return merged

    def _write_partitions(self, dataset_id: str, merged: pd.DataFrame) -> list[Path]:
        """Write one file per partition value, rewriting only what changed.

        Rewriting an unchanged partition would put the whole point of this
        layout back: a byte-identical parquet still becomes a new git blob.  So
        each partition is compared against what is already on disk and skipped
        when equal.
        """

        column = PARTITION_COLUMNS[dataset_id]
        directory = self.partition_dir(dataset_id)
        directory.mkdir(parents=True, exist_ok=True)
        names = merged[column].map(self._partition_name)

        written: list[Path] = []
        for name, group in merged.groupby(names, sort=True):
            path = directory / f"{name}.parquet"
            frame = group[DATASET_COLUMNS].reset_index(drop=True)
            payload = self._serialize_partition(frame)
            # Compare the bytes we are about to write, not the frames: a frame
            # comparison answers "are these equal in pandas", while the only
            # question that matters here is "would this create a new blob".
            if path.exists() and path.read_bytes() == payload:
                continue
            path.write_bytes(payload)
            written.append(path)

        # A partition whose rows all disappeared must not linger as a ghost
        # that load_dataset would concatenate back in.
        keep = {f"{name}.parquet" for name in names.unique()}
        for stale in directory.glob("*.parquet"):
            if stale.name not in keep:
                stale.unlink()
        return written

    @staticmethod
    def _serialize_partition(frame: pd.DataFrame) -> bytes:
        """Serialize one partition to parquet bytes under the pinned schema."""

        table = pa.Table.from_pandas(
            frame[DATASET_COLUMNS], schema=PARTITION_ARROW_SCHEMA, preserve_index=False
        )
        # ``from_pandas`` records the source frame's dtypes in the schema's
        # pandas metadata. That JSON travels into the file, so a partition
        # whose values never changed still serializes to different bytes when
        # the in-memory dtype differed -- object-vs-bool after a round trip is
        # enough. Dropping the metadata leaves the bytes a function of the
        # values and the pinned schema, which is the whole point.
        table = table.replace_schema_metadata(None)
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink)
        return sink.getvalue().to_pybytes()

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame) -> pd.DataFrame:
        for column in NUMERIC_COLUMNS:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in BOOL_COLUMNS:
            dataframe[column] = dataframe[column].map(
                lambda value: value
                if pd.isna(value) or isinstance(value, bool)
                else str(value).strip().lower() == "true"
            )
        for column in TEXT_COLUMNS:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe
