"""Auditable research-only imputation for monthly airline operating KPIs.

The canonical issuer-release parquet is never modified.  This module creates
an aggregate company-total research view for short internal gaps.  Level
metrics can be linearly interpolated only when both a prior and a subsequent
observation exist and the gap is short.  Load factors are recomputed from the
underlying level metrics rather than interpolated independently.

Every non-observed value carries the previous/next observation lineage and an
explicit future-use flag.  Any value that uses a future observation is not
PIT-safe for the 1H2026 event model, even though it can be useful for a
descriptive historical chart or a sensitivity comparison.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR, ROOT_DIR


MONTHLY_PATH = ROOT_DIR / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
SOURCE_RECOVERED_MONTHLY_PATH = NORMALIZED_DIR / "airline_operating_kpi_source_recovered.parquet"
OUTPUT_PATH = NORMALIZED_DIR / "airline_operating_kpi_imputed.parquet"
AUDIT_OUTPUT_PATH = NORMALIZED_DIR / "airline_operating_kpi_imputation_audit.csv"

COMPANIES = {
    "600029": "China Southern Airlines",
    "600115": "China Eastern Airlines",
    "600221": "Hainan Airlines Holdings",
    "601021": "Spring Airlines",
    "601111": "Air China",
    "603885": "Juneyao Airlines",
}

LEVEL_METRICS = (
    "ask", "rpk", "passengers", "cargo_tonnes", "aftk", "atk", "rftk", "rtk",
)
RATIO_METRICS = {
    "passenger_load_factor_pct": ("rpk", "ask"),
    "freight_load_factor_pct": ("rftk", "aftk"),
    "overall_load_factor_pct": ("rtk", "atk"),
}
MAX_INTERPOLATION_GAP_MONTHS = 3

# Capacity/demand around the 2020 COVID shock is not a smooth time series.
# Do not bridge a missing value across this regime with a straight line.
REGIME_BREAK_MONTHS = {f"2020-{month:02d}" for month in range(1, 7)}


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _month_index(value: str) -> int:
    period = pd.Period(value, freq="M")
    return period.year * 12 + period.month


def _month_from_index(value: int) -> str:
    year, month = divmod(value - 1, 12)
    return f"{year:04d}-{month + 1:02d}"


def _source_rows_for_month_metric(frame: pd.DataFrame, code: str, month: str, metric: str) -> tuple[float | None, str, str | None, str | None, str | None, int]:
    rows = frame.loc[
        frame["airline_code"].astype(str).eq(str(code))
        & frame["month"].astype(str).eq(month)
        & frame["metric"].eq(metric)
    ].copy()
    if rows.empty:
        return None, "missing_source_row", None, None, None, 0
    rows["value_num"] = pd.to_numeric(rows["value"], errors="coerce")
    total = rows.loc[
        rows["region"].astype(str).str.lower().eq("total")
        & rows["value_num"].notna()
    ]
    if not total.empty:
        selected = total.iloc[0]
        return (
            float(selected["value_num"]),
            "observed_total",
            _date_text(selected.get("announcement_date")),
            str(selected.get("source_pdf_url")) if pd.notna(selected.get("source_pdf_url")) else None,
            str(selected.get("source_quality")) if pd.notna(selected.get("source_quality")) else None,
            int(len(rows)),
        )
    regional = rows.loc[
        ~rows["region"].astype(str).str.lower().eq("total")
        & rows["value_num"].notna()
    ]
    if not regional.empty:
        dates = pd.to_datetime(regional.get("announcement_date"), errors="coerce").dropna()
        urls = regional.get("source_pdf_url", pd.Series(dtype=object)).dropna().astype(str).drop_duplicates()
        qualities = regional.get("source_quality", pd.Series(dtype=object)).dropna().astype(str).drop_duplicates()
        return (
            float(regional["value_num"].sum()),
            "observed_regional_sum",
            dates.max().strftime("%Y-%m-%d") if not dates.empty else None,
            ";".join(urls.tolist()) if not urls.empty else None,
            ";".join(qualities.tolist()) if not qualities.empty else None,
            int(len(rows)),
        )
    return None, "missing_numeric_value", None, None, None, int(len(rows))


def _date_text(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _raw_monthly_panel(
    frame: pd.DataFrame,
    retrieved_at: str,
    *,
    source_path: Path,
) -> tuple[pd.DataFrame, dict[tuple[str, str, str], dict[str, object]]]:
    source = frame.copy()
    source["airline_code"] = source["airline_code"].astype(str)
    source["month"] = source["month"].astype(str)
    source["announcement_date"] = pd.to_datetime(source["announcement_date"], errors="coerce")
    source["value"] = pd.to_numeric(source["value"], errors="coerce")
    source = source.loc[source["airline_code"].isin(COMPANIES)].copy()
    rows: list[dict[str, object]] = []
    raw_lookup: dict[tuple[str, str, str], dict[str, object]] = {}
    for code, company in COMPANIES.items():
        company_source = source.loc[source["airline_code"].eq(code)]
        if company_source.empty:
            continue
        min_month = str(company_source["month"].min())
        max_month = str(company_source["month"].max())
        month_indices = range(_month_index(min_month), _month_index(max_month) + 1)
        metrics = sorted(set(company_source["metric"].dropna().astype(str)) & set(LEVEL_METRICS))
        ratio_metrics = sorted(set(company_source["metric"].dropna().astype(str)) & set(RATIO_METRICS))
        for metric in metrics + ratio_metrics:
            for month_index in month_indices:
                month = _month_from_index(month_index)
                value, raw_method, announcement_date, source_url, source_quality, row_count = _source_rows_for_month_metric(source, code, month, metric)
                if metric in RATIO_METRICS and raw_method == "observed_regional_sum":
                    # Regional load-factor percentages cannot be added.  Keep
                    # the raw regional rows in the source parquet and derive
                    # the company-total ratio from aggregate level metrics.
                    value = None
                    raw_method = "regional_ratio_not_aggregated"
                    source_quality = "derived_from_level_metrics"
                entry = {
                    "dataset_id": "airline_operating_kpi_imputed",
                    "company": company,
                    "ticker": f"{code}.SH",
                    "airline_code": code,
                    "region": "Total",
                    "scope": "company_total",
                    "month": month,
                    "observation_date": f"{month}-01",
                    "metric": metric,
                    "value_raw": value,
                    "value": value,
                    "observation_status": "observed" if value is not None else "missing",
                    "imputation_method": "none" if value is not None else "not_filled",
                    "prev_observation_month": None,
                    "next_observation_month": None,
                    "prev_observation_value": None,
                    "next_observation_value": None,
                    "prev_announcement_date": None,
                    "next_announcement_date": None,
                    "interpolation_weight": None,
                    "gap_months_between_observations": None,
                    "uses_future_observation": False,
                    "pit_safe_for_h1_event": value is not None,
                    "raw_aggregation_method": raw_method,
                    "raw_source_row_count": row_count,
                    "announcement_date": announcement_date,
                    "source_pdf_url": source_url,
                    "source_quality": source_quality if value is not None else "missing_source_row",
                    "source_path": str(source_path),
                    "source_note": "Observed company-total row; Total issuer row is preferred and regional rows are summed only when Total is absent." if value is not None else "No usable source value for this company/month/metric within the retained monthly release archive.",
                    "retrieved_at": retrieved_at,
                }
                rows.append(entry)
                raw_lookup[(company, month, metric)] = entry
    return pd.DataFrame(rows), raw_lookup


def _nearest_observed(series: pd.DataFrame, month_index: int, direction: int) -> pd.Series | None:
    indices = series["month_index"].astype(int)
    candidates = series.loc[indices < month_index] if direction < 0 else series.loc[indices > month_index]
    if candidates.empty:
        return None
    selected_index = candidates["month_index"].max() if direction < 0 else candidates["month_index"].min()
    return candidates.loc[candidates["month_index"].eq(selected_index)].iloc[0]


def _impute_level_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    result["month_index"] = result["month"].map(_month_index)
    for (company, metric), group in result.groupby(["company", "metric"], sort=True):
        if metric not in LEVEL_METRICS:
            continue
        observed = group.loc[group["value_raw"].notna()].copy()
        if observed.empty:
            continue
        for row_index, row in group.loc[group["value_raw"].isna()].iterrows():
            target_index = int(row["month_index"])
            previous = _nearest_observed(observed, target_index, -1)
            following = _nearest_observed(observed, target_index, 1)
            if previous is None or following is None:
                continue
            previous_month = str(previous["month"])
            following_month = str(following["month"])
            span = int(following["month_index"] - previous["month_index"])
            missing_count = span - 1
            crossed_regime = any(
                _month_index(previous_month) <= _month_index(month) <= _month_index(following_month)
                for month in REGIME_BREAK_MONTHS
            )
            if missing_count > MAX_INTERPOLATION_GAP_MONTHS or crossed_regime:
                result.at[row_index, "imputation_method"] = "not_filled_regime_or_long_gap"
                result.at[row_index, "source_note"] = "Not filled: the nearest observations are separated by a long gap or cross the 2020 COVID regime guard."
                continue
            weight = (target_index - int(previous["month_index"])) / span
            value = float(previous["value_raw"] + (following["value_raw"] - previous["value_raw"]) * weight)
            result.at[row_index, "value"] = value
            result.at[row_index, "observation_status"] = "imputed"
            result.at[row_index, "imputation_method"] = "linear_interpolation_short_gap"
            result.at[row_index, "prev_observation_month"] = previous_month
            result.at[row_index, "next_observation_month"] = following_month
            result.at[row_index, "prev_observation_value"] = float(previous["value_raw"])
            result.at[row_index, "next_observation_value"] = float(following["value_raw"])
            result.at[row_index, "prev_announcement_date"] = previous.get("announcement_date")
            result.at[row_index, "next_announcement_date"] = following.get("announcement_date")
            result.at[row_index, "interpolation_weight"] = weight
            result.at[row_index, "gap_months_between_observations"] = missing_count
            result.at[row_index, "uses_future_observation"] = True
            result.at[row_index, "pit_safe_for_h1_event"] = False
            result.at[row_index, "announcement_date"] = following.get("announcement_date")
            result.at[row_index, "source_pdf_url"] = ";".join(
                [str(value) for value in [previous.get("source_pdf_url"), following.get("source_pdf_url")] if pd.notna(value) and value]
            ) or None
            result.at[row_index, "source_quality"] = "derived_imputed_linear_interpolation"
            result.at[row_index, "source_note"] = "Research-only linear interpolation between the nearest observed company-total monthly releases; not PIT-safe because it uses a future observation."
    return result


def _derive_ratio_metrics(
    panel: pd.DataFrame,
    raw_lookup: dict[tuple[str, str, str], dict[str, object]],
    retrieved_at: str,
    *,
    source_path: Path,
) -> pd.DataFrame:
    level = panel.loc[panel["metric"].isin(LEVEL_METRICS)].copy()
    lookup = level.set_index(["company", "month", "metric"])
    rows: list[dict[str, object]] = []
    for company in sorted(panel["company"].unique()):
        company_level = level.loc[level["company"].eq(company)]
        months = sorted(company_level["month"].unique())
        code = str(company_level["airline_code"].iloc[0])
        for month in months:
            for ratio_metric, (numerator_metric, denominator_metric) in RATIO_METRICS.items():
                raw = raw_lookup.get((company, month, ratio_metric))
                raw_value = raw.get("value_raw") if raw else None
                num_row = lookup.loc[(company, month, numerator_metric)] if (company, month, numerator_metric) in lookup.index else None
                den_row = lookup.loc[(company, month, denominator_metric)] if (company, month, denominator_metric) in lookup.index else None
                derived_value = None
                underlying_imputed = False
                underlying_future = False
                if num_row is not None and den_row is not None:
                    num = _num(num_row["value"])
                    den = _num(den_row["value"])
                    if num is not None and den not in (None, 0):
                        derived_value = 100.0 * num / den
                    underlying_imputed = num_row["observation_status"] == "imputed" or den_row["observation_status"] == "imputed"
                    underlying_future = bool(num_row["uses_future_observation"] or den_row["uses_future_observation"])
                if raw_value is not None:
                    value = raw_value
                    status = "observed"
                    method = "observed_total"
                    source_quality = raw.get("source_quality")
                    source_note = "Observed issuer Total load-factor row retained; it is not replaced by a derived ratio."
                    pit_safe = True
                elif derived_value is not None:
                    value = derived_value
                    status = "derived_from_imputed_levels" if underlying_imputed else "derived"
                    method = "derived_from_rpk_ask" if ratio_metric == "passenger_load_factor_pct" else "derived_from_level_metrics"
                    source_quality = "derived_from_imputed_levels" if underlying_imputed else "derived_from_observed_levels"
                    source_note = "Derived from company-total level metrics; it is not independently interpolated."
                    pit_safe = not underlying_future
                else:
                    value = None
                    status = "missing"
                    method = "not_filled"
                    source_quality = "missing_source_row"
                    source_note = "No observed or derivable company-total level metrics."
                    pit_safe = False
                rows.append({
                    "dataset_id": "airline_operating_kpi_imputed",
                    "company": company,
                    "ticker": f"{code}.SH",
                    "airline_code": code,
                    "region": "Total",
                    "scope": "company_total",
                    "month": month,
                    "observation_date": f"{month}-01",
                    "metric": ratio_metric,
                    "value_raw": raw_value,
                    "value": value,
                    "observation_status": status,
                    "imputation_method": method,
                    "prev_observation_month": None,
                    "next_observation_month": None,
                    "prev_observation_value": None,
                    "next_observation_value": None,
                    "prev_announcement_date": None,
                    "next_announcement_date": None,
                    "interpolation_weight": None,
                    "gap_months_between_observations": None,
                    "uses_future_observation": underlying_future,
                    "pit_safe_for_h1_event": pit_safe,
                    "raw_aggregation_method": raw.get("raw_aggregation_method") if raw else "derived",
                    "raw_source_row_count": raw.get("raw_source_row_count") if raw else 0,
                    "announcement_date": raw.get("announcement_date") if raw else None,
                    "source_pdf_url": raw.get("source_pdf_url") if raw else None,
                    "source_quality": source_quality,
                    "source_path": str(source_path),
                    "source_note": source_note,
                    "retrieved_at": retrieved_at,
                })
    return pd.DataFrame(rows)


def build_airline_operating_kpi_imputed(
    frame: pd.DataFrame | None = None,
    *,
    retrieved_at: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the isolated company-total imputed view and its audit table."""
    source_path = (
        SOURCE_RECOVERED_MONTHLY_PATH
        if frame is None and SOURCE_RECOVERED_MONTHLY_PATH.exists()
        else MONTHLY_PATH
    )
    source = frame if frame is not None else pd.read_parquet(source_path)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    panel, raw_lookup = _raw_monthly_panel(
        source,
        retrieved,
        source_path=source_path,
    )
    ratio_raw_lookup = {
        key: value for key, value in raw_lookup.items() if key[2] in RATIO_METRICS
    }
    panel = panel.loc[panel["metric"].isin(LEVEL_METRICS)].copy()
    panel = _impute_level_metrics(panel)
    ratios = _derive_ratio_metrics(
        panel,
        ratio_raw_lookup,
        retrieved,
        source_path=source_path,
    )
    all_columns = list(dict.fromkeys([*panel.columns.tolist(), *ratios.columns.tolist()]))
    result = pd.concat(
        [panel.reindex(columns=all_columns).astype(object), ratios.reindex(columns=all_columns).astype(object)],
        ignore_index=True,
        sort=False,
    )
    result = result.drop(columns=["month_index"], errors="ignore")
    result = result.sort_values(["company", "month", "metric"]).reset_index(drop=True)
    audit = result.loc[
        result["observation_status"].isin(["imputed", "missing"])
        | result["imputation_method"].str.startswith("not_filled", na=False)
    ].copy()
    result.to_parquet(OUTPUT_PATH, index=False)
    audit.to_csv(AUDIT_OUTPUT_PATH, index=False)
    return result, audit


def fetch_airline_operating_kpi_imputed() -> tuple[pd.DataFrame, pd.DataFrame]:
    return build_airline_operating_kpi_imputed()
