"""Orchestration and data-quality gates for HK Local Consumer ingestion."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

import pandas as pd

from .sources.afcd_food import fetch_afcd_food_prices
from .sources.consumer_council import fetch_consumer_council_prices
from .sources.consumer_council_pricewatch import fetch_consumer_council_pricewatch
from .sources.consumer_council_oilprice import fetch_consumer_council_oilprice
from .sources.consumer_council_complaints import fetch_consumer_council_complaints
from .sources.sge_gold import fetch_sge_gold_benchmark
from .sources.hk_valuation import fetch_hk_consumer_valuations
from .sources.cnsd_retail import fetch_cnsd_retail_sales
from .sources.censtatd_restaurant import fetch_censtatd_restaurant_survey
from .sources.immigration_flow import fetch_immigration_flow
from .sources.weather_demand_drivers import fetch_weather_demand_drivers
from .sources.fehd_licensed_premises import fetch_fehd_licensed_premises
from .storage import save_normalized_dataset, NORMALIZED_DIR


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hk_local_consumer_pipeline")


class PipelineRunError(RuntimeError):
    """Raised after a run has been fully audited and one or more datasets failed."""

    def __init__(self, message: str, results: Dict[str, Any], manifest_path: str):
        super().__init__(message)
        self.results = results
        self.manifest_path = manifest_path


QUALITY_SPECS: Dict[str, Dict[str, Any]] = {
    "afcd_wholesale_food_prices_daily": {
        "kind": "measure",
        "required": ["date", "category", "commodity_name", "price_hkd_per_kg"],
        "max_age_days": 400,
        "min_unique": {"category": 3, "commodity_name": 15},
        "strictly_positive": ["price_hkd_per_kg"],
        # The official daily sheet can report multiple market readings for
        # the same category/commodity. The dashboard aggregates those rows;
        # treating them as duplicate observations would discard valid data.
        "allow_duplicate_observations": True,
    },
    "consumer_council_price_watch_daily": {
        "kind": "catalog",
        "required": ["date", "product_id", "product_name", "price_hkd"],
    },
    "consumer_council_pricewatch_csv_daily": {
        "kind": "catalog",
        "required": ["date", "product_code", "product_name", "price"],
    },
    "consumer_council_oilprice_daily": {
        "kind": "measure",
        "required": ["date", "company", "fuel_type", "discounted_price_hkd"],
        "max_age_days": 400,
    },
    "consumer_council_complaints_by_sector": {
        "kind": "catalog",
        "required": ["period", "category", "amount"],
    },
    "sge_gold_benchmark_daily": {
        "kind": "measure",
        "required": ["date", "gold_benchmark_pm_rmb_gram"],
        "max_age_days": 400,
    },
    "hk_consumer_ticker_valuations_daily": {
        "kind": "measure",
        "required": ["date", "ticker", "company_name"],
        "max_age_days": 400,
    },
    "cnsd_retail_sales_monthly": {
        "kind": "measure",
        "required": ["date", "category", "sales_value_index"],
        "max_age_days": 400,
    },
    "censtatd_fast_food_survey_quarterly": {
        "kind": "measure",
        "required": ["quarter", "date", "sub_sector"],
        "max_age_days": 400,
    },
    "immigration_passenger_traffic_daily": {
        "kind": "measure",
        "required": ["date", "hk_resident_departures", "mainland_visitor_arrivals"],
        "max_age_days": 400,
    },
    "immigration_checkpoint_daily": {
        "kind": "measure",
        "required": ["date", "control_point", "direction", "total"],
        "max_age_days": 400,
    },
    "weather_demand_drivers_monthly": {
        "kind": "measure",
        "required": ["date", "month", "signal_8_plus_hours", "red_black_rain_hours"],
        "max_age_days": 400,
    },
    "weather_warning_events": {
        "kind": "catalog",
        "required": ["signal_name", "start", "end", "duration_hours"],
    },
    "fehd_licensed_premises_daily": {
        "kind": "catalog",
        "required": ["generation_date", "licno", "type_name", "district_name"],
        "min_unique": {"licno": 15000, "district_name": 15},
    },
}


def _quality_errors(dataset_name: str, df: pd.DataFrame) -> list[str]:
    spec = QUALITY_SPECS[dataset_name]
    if df.empty:
        return ["dataset yielded 0 records"]
    missing = [column for column in spec["required"] if column not in df.columns]
    if missing:
        return [f"missing required columns: {', '.join(missing)}"]
    null_columns = [column for column in spec["required"] if df[column].isna().any()]
    if null_columns:
        return [f"required columns contain null values: {', '.join(null_columns)}"]

    for column, minimum in spec.get("min_unique", {}).items():
        unique_values = int(df[column].nunique(dropna=True))
        if unique_values < minimum:
            return [f"{column} has only {unique_values} unique values; expected at least {minimum}"]

    for column in spec.get("strictly_positive", []):
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.isna().any() or (numeric <= 0).any():
            return [f"{column} must contain only positive numeric values"]

    if spec["kind"] == "measure":
        date_col = "observation_date" if "observation_date" in df.columns else "date"
        dates = pd.to_datetime(df[date_col], errors="coerce", utc=True)
        if dates.isna().any():
            return [f"{date_col} contains invalid values"]
        duplicate_key = [date_col]
        for candidate in ("commodity_name", "product_id", "ticker", "category", "sub_sector", "company", "fuel_type", "control_point", "direction"):
            if candidate in df.columns:
                duplicate_key.append(candidate)
        if not spec.get("allow_duplicate_observations", False) and df.duplicated(subset=duplicate_key).any():
            return [f"{date_col} contains duplicate observations"]
        latest = dates.max()
        now = pd.Timestamp.now(tz="UTC")
        if latest > now + pd.Timedelta(days=7):
            return [f"latest observation is implausibly in the future: {latest.date()}"]
        if latest < now - pd.Timedelta(days=spec["max_age_days"]):
            return [f"latest observation is stale: {latest.date()}"]
    return []


def write_run_manifest(run_id: str, group_name: str, results_summary: Dict[str, Any]) -> str:
    """Persist an append-safe, run-scoped audit manifest for successful and failed runs."""
    manifest_dir = NORMALIZED_DIR / "runs" / run_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest_data = json.load(f)
    else:
        manifest_data = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(), "groups": {}}
    manifest_data["groups"][group_name] = results_summary
    flattened = [item for group in manifest_data["groups"].values() for item in group.values()]
    manifest_data["status"] = "success" if flattened and all(item.get("status") == "success" for item in flattened) else "failed"
    manifest_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    return str(manifest_path)


def _error_result(error: Exception | str) -> Dict[str, Any]:
    return {"status": "error", "records": 0, "error": str(error)}


def _store_dataset(run_id: str, dataset_name: str, df: pd.DataFrame) -> Dict[str, Any]:
    errors = _quality_errors(dataset_name, df)
    if errors:
        status = "empty" if df.empty else "invalid"
        return {"status": status, "records": len(df), "errors": errors}
    # DataFrame attrs are runtime-only source context (for example an
    # immigration checkpoint detail frame). They are not a stable Parquet
    # contract and may contain Timestamps/DataFrames that Arrow cannot encode.
    persisted = df.copy()
    persisted.attrs = {}
    stored = save_normalized_dataset(
        dataset_name,
        persisted,
        run_id=run_id,
        raw_snapshot=df.attrs.get("raw_snapshot"),
        source_url=df.attrs.get("source_url"),
    )
    return {**stored, "records": len(df), "status": "success"}


def _finalize_group(run_id: str, group_name: str, results: Dict[str, Any], raise_on_failure: bool) -> Dict[str, Any]:
    manifest_path = write_run_manifest(run_id, group_name, results)
    failures = {name: value for name, value in results.items() if value["status"] != "success"}
    if failures and raise_on_failure:
        raise PipelineRunError(f"{group_name} ingestion failed; manifest: {manifest_path}", results, manifest_path)
    return results


def _record_many(run_id: str, results: Dict[str, Any], datasets: Mapping[str, pd.DataFrame]) -> None:
    for dataset_name, df in datasets.items():
        try:
            results[dataset_name] = _store_dataset(run_id, dataset_name, df)
        except Exception as exc:
            logger.exception("Failed to store %s", dataset_name)
            results[dataset_name] = _error_result(exc)


def run_stage_1_pipeline(run_id: str | None = None, *, _raise_on_failure: bool = False) -> Dict[str, Any]:
    """Run Stage 1: Structured APIs, Daily CSVs & akshare wrappers."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    
    try:
        logger.info("Ingesting AFCD wholesale fresh food prices...")
        _record_many(run_id, results, {"afcd_wholesale_food_prices_daily": fetch_afcd_food_prices()})
    except Exception as exc:
        logger.exception("AFCD ingestion failed")
        results["afcd_wholesale_food_prices_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting HK Consumer Council Online Price Watch...")
        _record_many(run_id, results, {"consumer_council_price_watch_daily": fetch_consumer_council_prices()})
    except Exception as exc:
        logger.exception("Consumer Council ingestion failed")
        results["consumer_council_price_watch_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting HK Consumer Council Online Price Watch (CSV open data)...")
        _record_many(run_id, results, {"consumer_council_pricewatch_csv_daily": fetch_consumer_council_pricewatch()})
    except Exception as exc:
        logger.exception("Consumer Council pricewatch CSV ingestion failed")
        results["consumer_council_pricewatch_csv_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting HK Consumer Council Auto Fuel Oil Price Calculator...")
        _record_many(run_id, results, {"consumer_council_oilprice_daily": fetch_consumer_council_oilprice()})
    except Exception as exc:
        logger.exception("Consumer Council oil price ingestion failed")
        results["consumer_council_oilprice_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting HK Consumer Council Complaint Statistics...")
        _record_many(run_id, results, {"consumer_council_complaints_by_sector": fetch_consumer_council_complaints()})
    except Exception as exc:
        logger.exception("Consumer Council complaints ingestion failed")
        results["consumer_council_complaints_by_sector"] = _error_result(exc)

    try:
        logger.info("Ingesting Shanghai Gold Exchange benchmark...")
        _record_many(run_id, results, {"sge_gold_benchmark_daily": fetch_sge_gold_benchmark()})
    except Exception as exc:
        logger.exception("SGE Gold Benchmark ingestion failed")
        results["sge_gold_benchmark_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting HK Consumer ticker daily valuations...")
        _record_many(run_id, results, {"hk_consumer_ticker_valuations_daily": fetch_hk_consumer_valuations()})
    except Exception as exc:
        logger.exception("HK Valuation ingestion failed")
        results["hk_consumer_ticker_valuations_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting C&SD Retail Sales & Visitor Arrivals...")
        _record_many(run_id, results, {"cnsd_retail_sales_monthly": fetch_cnsd_retail_sales()})
    except Exception as exc:
        logger.exception("C&SD Retail Sales ingestion failed")
        results["cnsd_retail_sales_monthly"] = _error_result(exc)

    try:
        logger.info("Ingesting CenStatD Quarterly Restaurant Survey...")
        _record_many(run_id, results, {"censtatd_fast_food_survey_quarterly": fetch_censtatd_restaurant_survey()})
    except Exception as exc:
        logger.exception("CenStatD Restaurant Survey ingestion failed")
        results["censtatd_fast_food_survey_quarterly"] = _error_result(exc)

    try:
        logger.info("Ingesting HK Immigration Department daily passenger traffic...")
        immigration = fetch_immigration_flow()
        checkpoints = immigration.attrs.get("checkpoint_history", pd.DataFrame()).copy()
        if not checkpoints.empty:
            checkpoints = checkpoints.rename(columns={
                "Date": "date", "Control Point": "control_point", "Arrival / Departure": "direction",
                "Hong Kong Residents": "hk_residents", "Mainland Visitors": "mainland_visitors",
                "Other Visitors": "other_visitors", "Total": "total",
            })
            checkpoints["date"] = pd.to_datetime(checkpoints["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        _record_many(run_id, results, {
            "immigration_passenger_traffic_daily": immigration,
            "immigration_checkpoint_daily": checkpoints,
        })
    except Exception as exc:
        logger.exception("Immigration Department daily passenger traffic ingestion failed")
        results["immigration_passenger_traffic_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting FEHD licensed restaurant directory (daily snapshot)...")
        _record_many(run_id, results, {"fehd_licensed_premises_daily": fetch_fehd_licensed_premises()})
    except Exception as exc:
        logger.exception("FEHD licensed premises ingestion failed")
        results["fehd_licensed_premises_daily"] = _error_result(exc)

    try:
        logger.info("Ingesting HKO weather warnings & FRED FX demand drivers...")
        weather = fetch_weather_demand_drivers()
        events = pd.DataFrame(weather.attrs.get("events", []))
        _record_many(run_id, results, {
            "weather_demand_drivers_monthly": weather,
            "weather_warning_events": events,
        })
    except Exception as exc:
        logger.exception("Weather and demand drivers ingestion failed")
        results["weather_demand_drivers_monthly"] = _error_result(exc)

    return _finalize_group(run_id, "stage_1", results, _raise_on_failure)


def run_all_pipelines() -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    merged: Dict[str, Any] = {}
    merged.update(run_stage_1_pipeline(run_id, _raise_on_failure=False))
    manifest_path = write_run_manifest(run_id, "all", merged)
    failures = {name: value for name, value in merged.items() if value["status"] != "success"}
    if failures:
        raise PipelineRunError(f"Full ingestion failed; manifest: {manifest_path}", merged, manifest_path)
    return merged


def run_dashboard_history_sources(run_id: str | None = None) -> Dict[str, Any]:
    """Materialise only the event/detail sources required by local-consumer charts."""
    run_id = run_id or str(uuid.uuid4())
    results: Dict[str, Any] = {}
    immigration = fetch_immigration_flow()
    checkpoints = immigration.attrs.get("checkpoint_history", pd.DataFrame()).copy().rename(columns={
        "Date": "date", "Control Point": "control_point", "Arrival / Departure": "direction",
        "Hong Kong Residents": "hk_residents", "Mainland Visitors": "mainland_visitors",
        "Other Visitors": "other_visitors", "Total": "total",
    })
    if not checkpoints.empty:
        checkpoints["date"] = pd.to_datetime(checkpoints["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    weather = fetch_weather_demand_drivers()
    events = pd.DataFrame(weather.attrs.get("events", []))
    _record_many(run_id, results, {
        "immigration_passenger_traffic_daily": immigration,
        "immigration_checkpoint_daily": checkpoints,
        "weather_demand_drivers_monthly": weather,
        "weather_warning_events": events,
    })
    return _finalize_group(run_id, "dashboard_history", results, False)


if __name__ == "__main__":
    run_all_pipelines()
