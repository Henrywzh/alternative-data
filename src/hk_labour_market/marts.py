"""Source-backed analytical marts for Hong Kong labour-market research.

The marts are deliberately long-form.  C&SD classifications and frequencies
do not line up perfectly across tables, so this layer standardizes names and
units while retaining the source dataset and original dimensions.  It does
not fabricate a cross-table sector join.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .config import BASE_DIR, MARTS_DIR, NORMALIZED_DIR
from .source_registry import CORE_CENSTATD_TABLES, STAGE_2_CENSTATD_TABLES, STAGE_3_CENSTATD_TABLES
from .sources.immigration_employment import EMPLOYMENT_POLICY_SOURCES


CORE_DATASETS = tuple(spec.dataset_id for spec in CORE_CENSTATD_TABLES)
STAGE_2_DATASETS = tuple(spec.dataset_id for spec in STAGE_2_CENSTATD_TABLES)
STAGE_3_DATASETS = tuple(spec.dataset_id for spec in STAGE_3_CENSTATD_TABLES)
POLICY_DATASETS = ("esls_applications_annual",) + tuple(
    source["dataset_id"] for source in EMPLOYMENT_POLICY_SOURCES
)
DATASET_STAGE = {
    **{dataset: "stage_1" for dataset in CORE_DATASETS},
    **{dataset: "stage_2" for dataset in STAGE_2_DATASETS},
    **{dataset: "stage_3" for dataset in STAGE_3_DATASETS},
    **{dataset: "stage_4" for dataset in POLICY_DATASETS},
}


def _resolve_path(value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else BASE_DIR / path


def _nonempty(series: pd.Series) -> pd.Series:
    return series.replace(r"^\s*$", pd.NA, regex=True)


def _coalesce(frame: pd.DataFrame, *columns: str, default: str | None = None) -> pd.Series:
    result = pd.Series(pd.NA, index=frame.index, dtype="object")
    for column in columns:
        if column in frame:
            result = result.fillna(_nonempty(frame[column].astype("string")))
    if default is not None:
        result = result.fillna(default)
    return result


def _json_dimensions(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _latest_manifest_entry(dataset_id: str) -> tuple[dict[str, Any], Path]:
    """Resolve a dataset through the pointer, with a manifest fallback."""
    pointer_path = NORMALIZED_DIR / "latest_runs.json"
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    if pointer_path.exists():
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FileNotFoundError("latest_runs.json is invalid JSON") from exc
        stage = DATASET_STAGE.get(dataset_id)
        entry = pointer.get(stage) if stage else None
        manifest_value = entry.get("manifest") if isinstance(entry, dict) else None
        if entry is not None and not manifest_value:
            raise FileNotFoundError(f"latest run pointer for {stage} has no manifest")
        manifest_path = _resolve_path(manifest_value) if manifest_value else Path()
        if manifest_value and manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            dataset_entry = manifest.get("datasets", {}).get(dataset_id, {})
            parquet_value = dataset_entry.get("parquet")
            if manifest.get("status") == "success" and dataset_entry.get("status") == "success" and parquet_value:
                parquet_path = _resolve_path(parquet_value)
                if parquet_path.is_file():
                    dataset_entry = dict(dataset_entry)
                    dataset_entry["parquet"] = str(parquet_path)
                    return dataset_entry, manifest_path
            raise FileNotFoundError(f"latest run pointer for {dataset_id} is invalid")
        if entry is not None:
            raise FileNotFoundError(f"latest run pointer for {stage} references a missing manifest")

    for manifest_path in (NORMALIZED_DIR / "runs").glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        dataset_entry = manifest.get("datasets", {}).get(dataset_id, {})
        parquet_value = dataset_entry.get("parquet")
        parquet_path = _resolve_path(parquet_value) if parquet_value else Path()
        if manifest.get("status") == "success" and dataset_entry.get("status") == "success" and parquet_path.exists():
            dataset_entry = dict(dataset_entry)
            dataset_entry["parquet"] = str(parquet_path)
            candidates.append((str(manifest.get("created_at", "")), manifest_path, dataset_entry))
    if not candidates:
        raise FileNotFoundError(f"No successful normalized vintage found for {dataset_id}")
    _, manifest_path, dataset_entry = sorted(candidates, key=lambda item: item[0])[-1]
    return dataset_entry, manifest_path


def load_latest_dataset(dataset_id: str) -> tuple[pd.DataFrame, Path]:
    entry, manifest_path = _latest_manifest_entry(dataset_id)
    return pd.read_parquet(entry["parquet"]), manifest_path


def _standard_frame(frame: pd.DataFrame, *, dataset_id: str, metric_name: pd.Series | str, unit: pd.Series | str) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    result["dataset_id"] = dataset_id
    result["source_table_id"] = frame.get("source_table_id")
    result["source_title"] = frame.get("source_title")
    result["source_url"] = frame.get("source_url")
    result["period"] = frame.get("period")
    result["period_end"] = frame.get("period_end")
    result["frequency_code"] = frame.get("frequency_code")
    result["frequency_label"] = frame.get("frequency_label")
    result["retrieved_at"] = frame.get("retrieved_at")
    result["data_source"] = frame.get("data_source")
    result["metric_name"] = metric_name
    result["metric_label"] = frame.get("metric_label")
    result["unit"] = unit
    result["value"] = pd.to_numeric(frame.get("value"), errors="coerce")
    result["status_flag"] = frame.get("status_flag")
    result["dimension_key"] = frame.get("dimension_key")
    result["source_dimensions_json"] = frame.get("source_dimensions_json")
    result["industry_code"] = _coalesce(frame, "industry_code", "main_industry_code")
    result["industry"] = _coalesce(frame, "industry", "main_industry")
    result["occupation_code"] = _coalesce(frame, "occupation_code", "main_occupation_code")
    result["occupation"] = _coalesce(frame, "occupation", "main_occupation")
    result["sex"] = _coalesce(frame, "sex")
    result["employment_nature"] = _coalesce(frame, "employment_nature")
    result["age_group"] = _coalesce(frame, "age_group")
    result["education"] = _coalesce(frame, "education")
    result["household_size"] = _coalesce(frame, "household_size")
    return result.reset_index(drop=True)


def build_labour_sector_panel() -> pd.DataFrame:
    rows: list[pd.DataFrame] = []

    demand, _ = load_latest_dataset("labour_demand_by_industry")
    demand = demand[demand["metric_label"].isin(["No.", "(%)"])].copy()
    demand_metric = demand["metric_code"].map({"PE": "persons_engaged", "VAC": "vacancies", "VACR": "vacancy_rate"})
    demand = demand[demand_metric.notna()].copy()
    rows.append(_standard_frame(demand, dataset_id="labour_demand_by_industry", metric_name=demand_metric.loc[demand.index], unit=demand_metric.loc[demand.index].map({"vacancy_rate": "percent", "persons_engaged": "persons", "vacancies": "persons"})))

    wage_specs = (
        ("nominal_wage_index_by_industry", "nominal_wage_yoy_pct", "percent"),
        ("real_wage_index_by_industry", "real_wage_yoy_pct", "percent"),
        ("nominal_payroll_index_by_industry", "nominal_payroll_yoy_pct", "percent"),
        ("real_payroll_index_by_industry", "real_payroll_yoy_pct", "percent"),
    )
    for dataset_id, metric_name, unit in wage_specs:
        frame, _ = load_latest_dataset(dataset_id)
        frame = frame[frame["metric_label"].astype("string").str.contains("Year-on-year", na=False)].copy()
        rows.append(_standard_frame(frame, dataset_id=dataset_id, metric_name=metric_name, unit=unit))

    earnings, _ = load_latest_dataset("median_earnings_by_industry")
    earnings = earnings[earnings.get("sex", pd.Series(index=earnings.index, dtype="object")).astype("string").eq("Total")].copy()
    rows.append(_standard_frame(earnings, dataset_id="median_earnings_by_industry", metric_name="median_monthly_earnings", unit="HKD"))
    return pd.concat(rows, ignore_index=True).sort_values(["period_end", "industry", "metric_name"], na_position="last").reset_index(drop=True)


def build_labour_income_panel() -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    median_specs = (
        ("median_earnings_by_industry", "industry", "median_monthly_earnings", "HKD"),
        ("median_earnings_by_occupation", "occupation", "median_monthly_earnings", "HKD"),
        ("economically_active_household_income", "household_size", "median_monthly_household_income", "HKD"),
    )
    for dataset_id, dimension_type, metric_name, unit in median_specs:
        frame, _ = load_latest_dataset(dataset_id)
        standard = _standard_frame(frame, dataset_id=dataset_id, metric_name=metric_name, unit=unit)
        standard["dimension_type"] = dimension_type
        standard["dimension_label"] = standard[dimension_type]
        rows.append(standard)

    for dataset_id in STAGE_3_DATASETS:
        frame, _ = load_latest_dataset(dataset_id)
        standard = _standard_frame(frame, dataset_id=dataset_id, metric_name=dataset_id, unit=frame["metric_label"].map(_unit_from_metric_label))
        standard["dimension_type"] = "source_dimensions"
        standard["dimension_label"] = _coalesce(frame, "industry", "main_industry", "occupation", "main_occupation", "age_group", "education", "employment_nature", default="Total")
        rows.append(standard)

    return pd.concat(rows, ignore_index=True).sort_values(["period_end", "dataset_id", "dimension_label"], na_position="last").reset_index(drop=True)


def _unit_from_metric_label(label: Any) -> str:
    text = str(label).lower()
    if "hk$" in text:
        return "HKD"
    if "hour" in text:
        return "hours"
    if "percentage" in text or "%" in text:
        return "percent"
    if "number" in text:
        return "thousand_persons"
    return "source_defined"


def build_labour_policy_supply_panel() -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for dataset_id in POLICY_DATASETS:
        try:
            frame, _ = load_latest_dataset(dataset_id)
        except FileNotFoundError:
            continue
        policy_unit = frame["metric_label"].map(_policy_unit)
        standard = _standard_frame(frame, dataset_id=dataset_id, metric_name=frame["metric_code"], unit=policy_unit)
        dimensions = frame.get("source_dimensions_json", pd.Series("{}", index=frame.index)).map(_json_dimensions)
        standard["scheme"] = dimensions.map(lambda item: item.get("scheme", ""))
        standard["scheme"] = standard["scheme"].replace("", pd.NA).fillna(
            "Enhanced Supplementary Labour Scheme" if dataset_id == "esls_applications_annual" else dataset_id
        )
        standard["breakdown_type"] = frame.get("dimension_type", pd.Series(index=frame.index, dtype="object"))
        standard["dimension_label"] = frame.get("dimension_label", pd.Series(index=frame.index, dtype="object"))
        standard["dimension_label"] = standard["dimension_label"].fillna(dimensions.map(lambda item: item.get("dimension", "All applicants")))
        rows.append(standard)
    if not rows:
        raise FileNotFoundError("No successful labour-supply policy datasets found")
    return pd.concat(rows, ignore_index=True).sort_values(["period_end", "dataset_id", "dimension_label", "metric_name"], na_position="last").reset_index(drop=True)


def _policy_unit(label: Any) -> str:
    text = str(label).lower()
    if "quota" in text:
        return "quota_cases"
    if "approved" in text:
        return "applications_approved"
    if "received" in text or "application" in text:
        return "applications_received"
    return "source_defined"


def _write_mart(name: str, frame: pd.DataFrame, source_manifests: Iterable[Path]) -> dict[str, Any]:
    MARTS_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = MARTS_DIR / f"{name}.parquet"
    frame.to_parquet(parquet_path, index=False)
    return {
        "parquet": str(parquet_path),
        "records": int(len(frame)),
        "columns": list(frame.columns),
        "source_manifests": sorted({str(path) for path in source_manifests}),
    }


def build_analysis_marts() -> dict[str, Any]:
    sector = build_labour_sector_panel()
    income = build_labour_income_panel()
    policy = build_labour_policy_supply_panel()
    manifests = []
    for dataset_id in (*CORE_DATASETS, *STAGE_3_DATASETS, *POLICY_DATASETS):
        try:
            _, manifest_path = _latest_manifest_entry(dataset_id)
        except FileNotFoundError:
            continue
        manifests.append(manifest_path)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "marts": {
            "labour_sector_panel": _write_mart("labour_sector_panel", sector, manifests),
            "labour_income_panel": _write_mart("labour_income_panel", income, manifests),
            "labour_policy_supply_panel": _write_mart("labour_policy_supply_panel", policy, manifests),
        },
        "definitions": {
            "labour_sector_panel": "Long panel of industry employment, vacancies, wage/payroll YoY and employment-earnings medians; source frequencies and classifications remain explicit.",
            "labour_income_panel": "Long panel of median earnings, household income, AEHS wage distributions and weekly-hours distributions.",
            "labour_policy_supply_panel": "Long panel of applications received/approved and QMAS quota cases; quota cases are not actual arrivals or employment.",
        },
    }
    (MARTS_DIR / "manifest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
