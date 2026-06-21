from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from semiconductor_proxy_data.models import (
    BackupCheckPoint,
    OfficialMonthlyPoint,
    PipelineResult,
    RunContext,
    Snapshot,
    SourceCatalogPoint,
)
from semiconductor_proxy_data.sources.comtrade import ComtradeSource
from semiconductor_proxy_data.sources.hongkong_censtatd import HongKongCenstatdSource
from semiconductor_proxy_data.sources.japan_customs import JapanCustomsSource
from semiconductor_proxy_data.sources.korea_customs import KoreaCustomsSource
from semiconductor_proxy_data.sources.nbs import NbsSource
from semiconductor_proxy_data.storage import StorageManager

PARSER_VERSION = "semi-tiered-v2"
DEFAULT_START_MONTH = "2024-01"
DEFAULT_REGIONS = ["japan", "korea", "hongkong"]
DEFAULT_CATEGORIES = ["ic_only", "broad_semiconductor"]


class SemiconductorProxyPipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        official_sources: list[object] | None = None,
        backup_source: ComtradeSource | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.official_sources = (
            official_sources
            if official_sources is not None
            else [JapanCustomsSource(), KoreaCustomsSource(), HongKongCenstatdSource(), NbsSource()]
        )
        self.backup_source = backup_source or ComtradeSource()

    def run_backfill(
        self,
        *,
        start_month: str | None = None,
        end_month: str | None = None,
        regions: list[str] | None = None,
        categories: list[str] | None = None,
        sources: str = "all",
    ) -> PipelineResult:
        target_end = end_month or _latest_closed_month()
        target_start = start_month or DEFAULT_START_MONTH
        months = _month_range(target_start, target_end)
        return self._run_pipeline(
            months=months,
            regions=regions or DEFAULT_REGIONS,
            categories=categories or DEFAULT_CATEGORIES,
            command="backfill",
            sources=sources,
        )

    def run_update_latest(
        self,
        *,
        regions: list[str] | None = None,
        categories: list[str] | None = None,
        period_month: str | None = None,
        sources: str = "all",
    ) -> PipelineResult:
        month = period_month or _latest_closed_month()
        return self._run_pipeline(
            months=[month],
            regions=regions or DEFAULT_REGIONS,
            categories=categories or DEFAULT_CATEGORIES,
            command="update-latest",
            sources=sources,
        )

    def compare_backup(self) -> PipelineResult:
        context = self._create_context()
        official = self.storage.load_dataset("semiconductor_official_monthly")
        backup = self.storage.load_dataset("semiconductor_backup_check_monthly")
        official, backup = _apply_comparison_gaps(official, backup)
        official = self.storage.upsert_dataset("semiconductor_official_monthly", _frame_to_points(official, OfficialMonthlyPoint))
        backup = self.storage.upsert_dataset("semiconductor_backup_check_monthly", _frame_to_points(backup, BackupCheckPoint))
        return PipelineResult(
            run_id=context.run_id,
            datasets_written={
                "semiconductor_official_monthly": len(official),
                "semiconductor_backup_check_monthly": len(backup),
                "semiconductor_source_catalog": len(self.storage.load_dataset("semiconductor_source_catalog")),
            },
            raw_run_dir=str(self.storage.raw_root),
            dataset_row_deltas={},
        )

    def validate(self) -> dict[str, int | str | None]:
        official_df = self.storage.load_dataset("semiconductor_official_monthly")
        backup_df = self.storage.load_dataset("semiconductor_backup_check_monthly")
        catalog_df = self.storage.load_dataset("semiconductor_source_catalog")
        official_stale_rows = 0
        backup_stale_rows = 0
        if not official_df.empty:
            official_stale_rows = int(
                (
                    pd.to_numeric(official_df["lag_days"], errors="coerce")
                    > pd.to_numeric(official_df["expected_release_window_days"], errors="coerce")
                ).fillna(False).sum()
            )
        if not backup_df.empty:
            backup_stale_rows = int(
                (
                    pd.to_numeric(backup_df["lag_days"], errors="coerce")
                    > pd.to_numeric(backup_df["expected_release_window_days"], errors="coerce")
                ).fillna(False).sum()
            )
        return {
            "official_rows": int(len(official_df)),
            "backup_rows": int(len(backup_df)),
            "catalog_rows": int(len(catalog_df)),
            "official_duplicates": int(official_df.duplicated(
                subset=["source_region", "metric_type", "category_id", "flow_code", "period", "partner_scope"]
            ).sum()) if not official_df.empty else 0,
            "backup_duplicates": int(backup_df.duplicated(
                subset=["source_region", "metric_type", "category_id", "flow_code", "period", "partner_scope", "source_name"]
            ).sum()) if not backup_df.empty else 0,
            "official_latest_period": str(official_df["period"].max()) if not official_df.empty else None,
            "backup_latest_period": str(backup_df["period"].max()) if not backup_df.empty else None,
            "official_stale_rows": official_stale_rows,
            "backup_stale_rows": backup_stale_rows,
        }

    def import_custom_csv(
        self,
        filepath: Path,
        region: str,
        category_id: str,
        metric_type: str,
        flow_code: str,
        scale_thousand: bool = False,
    ) -> PipelineResult:
        context = self._create_context()
        df = pd.read_csv(filepath)

        period_col = _find_column(df.columns, {"period", "ym", "y/m", "기간", "년월", "date", "날짜"}) or df.columns[0]
        val_col = _find_value_column(df.columns)
        if not val_col:
            raise ValueError(f"Could not identify export value column in CSV. Columns: {list(df.columns)}")
        partner_col = _find_column(df.columns, {"partner", "country", "국가", "상대국", "partner_name"})
        is_thousand = scale_thousand or any(key in str(val_col).lower() for key in ["thousand", "천불", "천달러"])

        points: list[OfficialMonthlyPoint] = []
        for _, row in df.iterrows():
            period = _normalize_period(str(row[period_col]).strip())
            raw_val = row[val_col]
            if pd.isna(raw_val):
                continue
            val_str = str(raw_val).replace(",", "").strip()
            try:
                value = float(val_str)
            except ValueError:
                continue
            if is_thousand:
                value *= 1000.0

            partner_scope = "world"
            if partner_col and not pd.isna(row[partner_col]):
                partner_scope = _normalize_partner_scope(str(row[partner_col]).strip())

            points.append(
                OfficialMonthlyPoint(
                    dataset_id="semiconductor_official_monthly",
                    source_region=region.lower(),
                    country_name=_region_country_name(region),
                    metric_type=metric_type,
                    flow_code=flow_code,
                    partner_scope=partner_scope,
                    period=period,
                    release_date=None,
                    expected_release_window_days=None,
                    lag_days=None,
                    category_id=category_id,
                    category_label=_category_label(category_id),
                    classification_system="HS",
                    classification_code="8542" if category_id == "ic_only" else "8541,8542",
                    unit="usd",
                    currency="USD",
                    value=value,
                    yoy_pct=None,
                    mom_pct=None,
                    is_preliminary=False,
                    is_revised=False,
                    is_official_primary=True,
                    comparison_gap_pct=None,
                    source_name=f"{_region_country_name(region)} official CSV import",
                    source_url=f"file://{filepath.name}",
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    parser_version=PARSER_VERSION,
                )
            )

        existing_official = self.storage.load_dataset("semiconductor_official_monthly")
        written_official = self.storage.upsert_dataset("semiconductor_official_monthly", points)
        return PipelineResult(
            run_id=context.run_id,
            datasets_written={
                "semiconductor_official_monthly": len(written_official),
                "semiconductor_backup_check_monthly": len(self.storage.load_dataset("semiconductor_backup_check_monthly")),
                "semiconductor_source_catalog": len(self.storage.load_dataset("semiconductor_source_catalog")),
            },
            raw_run_dir=str(filepath.parent),
            dataset_row_deltas={
                "semiconductor_official_monthly": max(len(written_official) - len(existing_official), 0),
            },
        )

    def _run_pipeline(
        self,
        *,
        months: list[str],
        regions: list[str],
        categories: list[str],
        command: str,
        sources: str,
    ) -> PipelineResult:
        context = self._create_context()
        snapshots: list[Snapshot] = []
        failures: list[str] = []
        official_points: list[OfficialMonthlyPoint] = []
        backup_points: list[BackupCheckPoint] = []
        catalog_points: list[SourceCatalogPoint] = []

        if sources in {"official", "all"}:
            for source in self.official_sources:
                try:
                    source_snapshots = source.fetch_snapshots(months, regions, categories)
                    snapshots.extend(source_snapshots)
                    extracted = source.extract(source_snapshots, run_id=context.run_id, scraped_at=context.scraped_at_iso)
                    official_points.extend(extracted)
                    if source_snapshots and hasattr(source, "catalog_points"):
                        catalog_points.extend(source.catalog_points(context.run_id, context.scraped_at_iso))
                except Exception as exc:
                    failures.append(f"{source.__class__.__name__}:official-error:{exc}")

        if sources in {"backup", "all"}:
            backup_categories = [category for category in categories if category == "ic_only"]
            if backup_categories:
                try:
                    backup_snapshots = self.backup_source.fetch_snapshots(months, regions, cmd_codes=["8542"])
                    snapshots.extend(backup_snapshots)
                    backup_points.extend(
                        self.backup_source.extract(
                            backup_snapshots,
                            run_id=context.run_id,
                            scraped_at=context.scraped_at_iso,
                            category_id="ic_only",
                            category_label=_category_label("ic_only"),
                            metric_type="exports",
                        )
                    )
                except Exception as exc:
                    failures.append(f"backup:fetch-error:{exc}")

        manifest = self._build_manifest(
            context,
            command=command,
            months=months,
            regions=regions,
            categories=categories,
            snapshots=snapshots,
            failures=failures,
            official_rows=len(official_points),
            backup_rows=len(backup_points),
            catalog_rows=len(catalog_points),
            sources=sources,
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        existing_official = self.storage.load_dataset("semiconductor_official_monthly")
        existing_backup = self.storage.load_dataset("semiconductor_backup_check_monthly")
        existing_catalog = self.storage.load_dataset("semiconductor_source_catalog")

        written_official = self.storage.upsert_dataset("semiconductor_official_monthly", official_points)
        written_backup = self.storage.upsert_dataset("semiconductor_backup_check_monthly", backup_points)
        written_catalog = self.storage.upsert_dataset("semiconductor_source_catalog", catalog_points)
        official_with_gaps, backup_with_gaps = _apply_comparison_gaps(written_official, written_backup)
        written_official = self.storage.upsert_dataset(
            "semiconductor_official_monthly",
            _frame_to_points(official_with_gaps, OfficialMonthlyPoint),
        )
        written_backup = self.storage.upsert_dataset(
            "semiconductor_backup_check_monthly",
            _frame_to_points(backup_with_gaps, BackupCheckPoint),
        )
        catalog_with_latest = _apply_catalog_latest_periods(written_catalog, written_official, written_backup)
        written_catalog = self.storage.upsert_dataset(
            "semiconductor_source_catalog",
            _frame_to_catalog_points(catalog_with_latest),
        )

        return PipelineResult(
            run_id=context.run_id,
            datasets_written={
                "semiconductor_official_monthly": len(written_official),
                "semiconductor_backup_check_monthly": len(written_backup),
                "semiconductor_source_catalog": len(written_catalog),
            },
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas={
                "semiconductor_official_monthly": max(len(written_official) - len(existing_official), 0),
                "semiconductor_backup_check_monthly": max(len(written_backup) - len(existing_backup), 0),
                "semiconductor_source_catalog": max(len(written_catalog) - len(existing_catalog), 0),
            },
        )

    def _create_context(self) -> RunContext:
        return RunContext(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            scraped_at=datetime.now(timezone.utc),
        )

    def _build_manifest(
        self,
        context: RunContext,
        *,
        command: str,
        months: list[str],
        regions: list[str],
        categories: list[str],
        snapshots: list[Snapshot],
        failures: list[str],
        official_rows: int,
        backup_rows: int,
        catalog_rows: int,
        sources: str,
    ) -> dict[str, object]:
        return {
            "run_id": context.run_id,
            "scraped_at": context.scraped_at_iso,
            "command": command,
            "months": months,
            "regions": regions,
            "categories": categories,
            "sources": sources,
            "parser_version": PARSER_VERSION,
            "official_row_count": official_rows,
            "backup_row_count": backup_rows,
            "catalog_row_count": catalog_rows,
            "failure_count": len(failures),
            "failures": failures,
            "snapshots": [{"name": snapshot.name, "source_url": snapshot.source_url} for snapshot in snapshots],
        }


def _apply_comparison_gaps(
    official_df: pd.DataFrame,
    backup_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if official_df.empty or backup_df.empty:
        return official_df, backup_df

    join_keys = ["source_region", "metric_type", "category_id", "flow_code", "period", "partner_scope"]
    official = official_df.copy()
    backup = backup_df.copy()
    joined = official[join_keys + ["value"]].merge(
        backup[join_keys + ["value"]],
        on=join_keys,
        how="inner",
        suffixes=("_official", "_backup"),
    )
    if joined.empty:
        return official, backup

    joined["comparison_gap_pct"] = (
        (joined["value_official"] - joined["value_backup"]).abs() / joined["value_official"].abs()
    ) * 100.0
    gap_map = joined.set_index(join_keys)["comparison_gap_pct"].to_dict()

    def _assign_gap(frame: pd.DataFrame) -> pd.DataFrame:
        updated = frame.copy()
        updated["comparison_gap_pct"] = [
            gap_map.get(tuple(row[key] for key in join_keys), row.get("comparison_gap_pct"))
            for _, row in updated.iterrows()
        ]
        return updated

    return _assign_gap(official), _assign_gap(backup)


def _apply_catalog_latest_periods(
    catalog_df: pd.DataFrame,
    official_df: pd.DataFrame,
    backup_df: pd.DataFrame,
) -> pd.DataFrame:
    if catalog_df.empty:
        return catalog_df

    latest_entries: list[tuple[str, str, str, str, str]] = []
    if not official_df.empty:
        latest_official = (
            official_df.groupby(["source_region", "metric_type", "category_id"], dropna=False)["period"]
            .max()
            .reset_index()
        )
        latest_entries.extend(
            (
                str(row.source_region),
                str(row.metric_type),
                str(row.category_id),
                "official",
                str(row.period),
            )
            for row in latest_official.itertuples(index=False)
        )
    if not backup_df.empty:
        latest_backup = (
            backup_df.groupby(["source_region", "metric_type", "category_id"], dropna=False)["period"]
            .max()
            .reset_index()
        )
        latest_entries.extend(
            (
                str(row.source_region),
                str(row.metric_type),
                str(row.category_id),
                "backup",
                str(row.period),
            )
            for row in latest_backup.itertuples(index=False)
        )

    if not latest_entries:
        return catalog_df

    latest_map = {
        (source_region, metric_type, category_id, source_tier): period
        for source_region, metric_type, category_id, source_tier, period in latest_entries
    }
    updated = catalog_df.copy()
    updated["latest_period"] = [
        latest_map.get(
            (
                str(row.get("source_region", "")),
                str(row.get("metric_type", "")),
                str(row.get("category_id", "")),
                str(row.get("source_tier", "")),
            ),
            row.get("latest_period"),
        )
        for _, row in updated.iterrows()
    ]
    return updated


def _frame_to_points(frame: pd.DataFrame, point_cls: type[OfficialMonthlyPoint] | type[BackupCheckPoint]) -> list[OfficialMonthlyPoint] | list[BackupCheckPoint]:
    if frame.empty:
        return []
    records: list[OfficialMonthlyPoint] | list[BackupCheckPoint] = []
    for row in frame.to_dict(orient="records"):
        cleaned = {key: (None if pd.isna(value) else value) for key, value in row.items()}
        records.append(point_cls(**cleaned))
    return records


def _frame_to_catalog_points(frame: pd.DataFrame) -> list[SourceCatalogPoint]:
    if frame.empty:
        return []
    return [SourceCatalogPoint(**record) for record in frame.to_dict(orient="records")]


def _find_column(columns: pd.Index, accepted: set[str]) -> str | None:
    for column in columns:
        if str(column).lower() in accepted:
            return str(column)
    return None


def _find_value_column(columns: pd.Index) -> str | None:
    for column in columns:
        lowered = str(column).lower()
        if any(key in lowered for key in ["export", "value", "trade_value", "수출", "금액"]):
            return str(column)
    return None


def _normalize_period(raw_period: str) -> str:
    clean_period = re.sub(r"[./-]", "", raw_period)
    if len(clean_period) == 6:
        return f"{clean_period[:4]}-{clean_period[4:]}"
    if len(clean_period) == 8:
        return f"{clean_period[:4]}-{clean_period[4:6]}"
    if "-" in raw_period and len(raw_period.split("-")) >= 2:
        parts = raw_period.split("-")
        return f"{parts[0]:>04s}-{parts[1]:>02s}"
    return raw_period


def _normalize_partner_scope(raw_partner: str) -> str:
    partner_lower = raw_partner.strip().lower()
    if "china" in partner_lower or "중국" in partner_lower:
        return "china"
    if "usa" in partner_lower or "united states" in partner_lower or "미국" in partner_lower:
        return "usa"
    if "hong" in partner_lower or "홍콩" in partner_lower:
        return "hongkong"
    if "japan" in partner_lower or "일본" in partner_lower:
        return "japan"
    if "korea" in partner_lower or "한국" in partner_lower:
        return "korea"
    if "world" in partner_lower or "세계" in partner_lower or "합계" in partner_lower:
        return "world"
    return re.sub(r"[^a-z0-9]+", "_", partner_lower).strip("_") or "other"


def _region_country_name(region: str) -> str:
    mapping = {
        "korea": "South Korea",
        "china": "China",
        "hongkong": "Hong Kong",
        "japan": "Japan",
    }
    return mapping.get(region.lower(), region)


def _category_label(category_id: str) -> str:
    mapping = {
        "ic_only": "IC-only",
        "broad_semiconductor": "Broad Semiconductor",
    }
    return mapping.get(category_id, category_id.replace("_", " ").title())


def _latest_closed_month() -> str:
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}"


def _month_range(start_month: str, end_month: str) -> list[str]:
    start = pd.Period(start_month, freq="M")
    end = pd.Period(end_month, freq="M")
    if end < start:
        raise ValueError("end_month must be greater than or equal to start_month")
    return [period.strftime("%Y-%m") for period in pd.period_range(start=start, end=end, freq="M")]
