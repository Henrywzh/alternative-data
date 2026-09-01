from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from taiwan_semiconductor_revenue_data.models import PipelineResult, RunContext, Snapshot
from taiwan_semiconductor_revenue_data.sources.mops import MopsMonthlyRevenueSource
from taiwan_semiconductor_revenue_data.storage import StorageManager


PARSER_VERSION = "tw-revenue-v1"
DEFAULT_START_MONTH = "2013-01"


class TaiwanSemiconductorRevenuePipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        source: MopsMonthlyRevenueSource | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = StorageManager(base_dir)
        self.source = source or MopsMonthlyRevenueSource()

    def run_backfill(
        self,
        *,
        start_month: str | None = None,
        end_month: str | None = None,
        company_codes: list[str] | None = None,
    ) -> PipelineResult:
        target_end = end_month or _latest_closed_month()
        target_start = start_month or DEFAULT_START_MONTH
        months = _month_range(target_start, target_end)
        return self._run_months(months, company_codes=company_codes, command="backfill")

    def run_update_latest(
        self,
        *,
        company_codes: list[str] | None = None,
        revenue_month: str | None = None,
    ) -> PipelineResult:
        month = revenue_month or _latest_closed_month()
        return self._run_months([month], company_codes=company_codes, command="update-latest")

    def validate(self) -> dict[str, int]:
        dataframe = self.storage.load_dataset("tw_monthly_revenue")
        if dataframe.empty:
            return {
                "rows": 0,
                "companies": 0,
                "duplicate_keys": 0,
                "missing_monthly_revenue": 0,
                "missing_yoy_pct": 0,
                "missing_ytd_revenue": 0,
                "month_gaps": 0,
            }

        return {
            "rows": int(len(dataframe)),
            "companies": int(dataframe["company_code"].nunique()),
            "duplicate_keys": int(dataframe.duplicated(subset=["company_code", "revenue_month"]).sum()),
            "missing_monthly_revenue": int(dataframe["monthly_revenue_ntd"].isna().sum()),
            "missing_yoy_pct": int(dataframe["yoy_pct"].isna().sum()),
            "missing_ytd_revenue": int(dataframe["ytd_revenue_ntd"].isna().sum()),
            "month_gaps": _count_month_gaps(dataframe),
        }

    def _run_months(
        self,
        months: list[str],
        *,
        company_codes: list[str] | None,
        command: str,
    ) -> PipelineResult:
        context = self._create_context()
        companies = self.source.resolve_companies(company_codes)
        snapshots = self.source.fetch_snapshots(months, companies)

        points = []
        failures: list[str] = []
        for snapshot in snapshots:
            try:
                extracted, snapshot_failures = self.source.extract(
                    snapshot,
                    companies=companies,
                    run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    parser_version=PARSER_VERSION,
                )
                points.extend(extracted)
                failures.extend(snapshot_failures)
            except Exception as exc:
                failures.append(f"{snapshot.name}:snapshot-error:{exc}")

        manifest = self._build_manifest(
            context,
            command=command,
            months=months,
            snapshots=snapshots,
            failures=failures,
            rows=len(points),
        )
        raw_run_dir = self.storage.write_raw_run(context.run_id, snapshots, manifest)

        if not points:
            # Every failure so far has gone into the manifest and nowhere else,
            # so a run that fetched nothing at all exited 0, committed nothing,
            # and left a green tick. `validate --fail-on-issues` then checked
            # the dataset already on disk, which is untouched by a failed
            # fetch, so it agreed. A scheduled run exists to bring a month
            # back; coming back empty-handed is a failure, not a quiet no-op.
            raise RuntimeError(
                f"MOPS returned no usable rows for {', '.join(months)} "
                f"({len(failures)} extraction failures"
                + (f": {failures[0]}" if failures else "")
                + ")"
            )

        existing = self.storage.load_dataset("tw_monthly_revenue")
        points = _fill_missing_mom(points, existing)
        written = self.storage.upsert_dataset("tw_monthly_revenue", points)
        return PipelineResult(
            run_id=context.run_id,
            datasets_written={"tw_monthly_revenue": len(written)},
            raw_run_dir=str(raw_run_dir),
            dataset_row_deltas={"tw_monthly_revenue": max(len(written) - len(existing), 0)},
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
        snapshots: list[Snapshot],
        failures: list[str],
        rows: int,
    ) -> dict[str, object]:
        return {
            "run_id": context.run_id,
            "scraped_at": context.scraped_at_iso,
            "source": "mops",
            "command": command,
            "months": months,
            "parser_version": PARSER_VERSION,
            "row_count": rows,
            "failure_count": len(failures),
            "failures": failures,
            "snapshots": [{"name": snapshot.name, "source_url": snapshot.source_url} for snapshot in snapshots],
        }


def _count_month_gaps(dataframe: pd.DataFrame) -> int:
    """Months absent from the middle of a company's own reported range.

    MOPS publishes every month, so a company that reports January and March
    but not February is missing data, not quiet.  This is the check that
    notices a month being *removed*: on 2026-08-17 a coverage-expansion commit
    rebuilt this dataset from a local snapshot taken on 2026-08-07 and dropped
    July, which CI had collected on the 10th-12th.  A truncation at the end
    looks like a contiguous range, so nothing complained -- until the next
    month lands and the hole becomes interior, which is exactly when this
    fires.
    """
    total = 0
    months = pd.to_datetime(dataframe["revenue_month"], errors="coerce")
    frame = dataframe.assign(_period=months.dt.to_period("M")).dropna(subset=["_period"])
    for _, group in frame.groupby("company_code"):
        observed = set(group["_period"])
        if len(observed) < 2:
            continue
        expected = set(pd.period_range(min(observed), max(observed), freq="M"))
        total += len(expected - observed)
    return int(total)


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


def _fill_missing_mom(points: list[object], existing: pd.DataFrame) -> list[object]:
    """Derive MoM only when the source did not publish it and prior revenue exists."""
    revenue_by_key: dict[tuple[str, str], float] = {}
    if not existing.empty:
        for row in existing.itertuples(index=False):
            value = getattr(row, "monthly_revenue_ntd", None)
            if pd.notna(value):
                revenue_by_key[(str(row.company_code), str(row.revenue_month))] = float(value)

    enriched: list[object] = []
    for point in sorted(points, key=lambda item: (item.company_code, item.revenue_month)):
        current = point.monthly_revenue_ntd
        mom = point.mom_pct
        derived = point.mom_pct_is_derived
        if mom is None and current is not None:
            previous_month = (pd.Period(point.revenue_month, freq="M") - 1).strftime("%Y-%m")
            previous = revenue_by_key.get((point.company_code, previous_month))
            if previous not in (None, 0):
                mom = round((float(current) / previous - 1.0) * 100.0, 10)
                derived = True
        enriched_point = replace(point, mom_pct=mom, mom_pct_is_derived=derived)
        enriched.append(enriched_point)
        if current is not None:
            revenue_by_key[(point.company_code, point.revenue_month)] = float(current)
    return enriched
