"""Tencent official quarterly financials with explicit PIT and source lineage.

The specialised output is deliberately richer than the current global
``earnings_actuals_v1`` mart.  Integration must extend that mart rather than
discarding the canonical basis, source-document, and value-origin fields.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.research_control_tower.build import (
    EARNINGS_ACTUALS_COLUMNS,
    SOURCE_STATE_COLUMNS,
)

TENCENT_ENTITY_ID = "TENCENT"
TENCENT_LISTING_ID = "0700_HK"
TENCENT_CANONICAL_TICKER = "0700.HK"
TENCENT_REPORTING_CURRENCY = "CNY"

PIT_CLASS_OBSERVED = "snapshot_from_live_source"
LICENSE_CLASS = "official_public_metadata"
SOURCE_QUALITY_OFFICIAL = "official_body"
REGISTRY_VERSION = "v1"
MINIMUM_COMPLETE_CORE_QUARTERS = 12

SUPPORTED_METRIC_BASES = {
    "GAAP_REPORTED",
    "NON_IFRS_MANAGEMENT",
    "PROVIDER_UNVERIFIED",
}
TENCENT_OFFICIAL_METRIC_BASES = {
    "GAAP_REPORTED",
    "NON_IFRS_MANAGEMENT",
}
SUPPORTED_PIT_CLASSES = {PIT_CLASS_OBSERVED}
SUPPORTED_VALUE_ORIGINS = {
    "direct_quarterly_disclosure",
    "derived_from_official_disclosure",
}
SUPPORTED_DERIVATION_METHODS = {
    "as_reported_quarterly_table",
    "direct_q4_column_in_annual_results",
    "as_reported_management_measure",
}
REQUIRED_CORE_METRICS = {
    ("revenue_total", "GAAP_REPORTED"),
    ("operating_profit", "GAAP_REPORTED"),
    ("net_profit_attributable", "GAAP_REPORTED"),
    ("diluted_eps", "GAAP_REPORTED"),
}


def _enriched_columns() -> list[str]:
    # Return canonical list of columns
    base = [
        "actual_id", "version", "supersedes_actual_id", "entity_id", "listing_id",
        "canonical_ticker", "metric", "source_metric_label", "metric_basis",
        "period_label", "period_start", "period_end", "reported_value",
        "normalized_value", "normalization_note", "currency", "unit",
        "accounting_basis", "filing_at", "published_at", "retrieved_at_utc",
        "source_url", "accession_no", "source_document_id",
        "source_document_sha256", "source_page_ref", "value_origin",
        "derivation_method", "timestamp_precision", "form", "xbrl_frame",
        "revision_reason", "is_restatement", "source_id", "source_quality",
        "pit_class", "source_license_class", "source_note", "registry_version",
    ]
    return base


TENCENT_EARNINGS_ACTUALS_COLUMNS = _enriched_columns()


@dataclass(frozen=True)
class MetricDefinition:
    metric: str
    source_field: str
    source_metric_label: str
    metric_basis: str
    accounting_basis: str
    unit: str
    is_per_share: bool = False


METRIC_DEFINITIONS = (
    MetricDefinition(
        "revenue_total",
        "revenue_total",
        "Revenues",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
    MetricDefinition(
        "operating_profit",
        "operating_profit_gaap",
        "Operating profit",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
    MetricDefinition(
        "operating_profit",
        "operating_profit_non_ifrs",
        "Non-IFRS operating profit",
        "NON_IFRS_MANAGEMENT",
        "Non-IFRS management measure",
        "CNY",
    ),
    MetricDefinition(
        "net_profit_attributable",
        "net_profit_attributable_gaap",
        "Profit attributable to equity holders of the Company",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
    MetricDefinition(
        "net_profit_attributable",
        "net_profit_attributable_non_ifrs",
        "Non-IFRS profit attributable to equity holders of the Company",
        "NON_IFRS_MANAGEMENT",
        "Non-IFRS management measure",
        "CNY",
    ),
    MetricDefinition(
        "diluted_eps",
        "diluted_eps_gaap",
        "Diluted EPS",
        "GAAP_REPORTED",
        "IFRS",
        "CNY/share",
        True,
    ),
    MetricDefinition(
        "diluted_eps",
        "diluted_eps_non_ifrs",
        "Non-IFRS diluted EPS",
        "NON_IFRS_MANAGEMENT",
        "Non-IFRS management measure",
        "CNY/share",
        True,
    ),
    MetricDefinition(
        "capex",
        "capex",
        "Capital expenditures",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
    MetricDefinition(
        "free_cash_flow",
        "fcf",
        "Free cash flow",
        "NON_IFRS_MANAGEMENT",
        "Non-IFRS management measure",
        "CNY",
    ),
    MetricDefinition(
        "revenue_vas",
        "revenue_vas",
        "VAS",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
    MetricDefinition(
        "revenue_online_advertising",
        "revenue_online_advertising",
        "Online Advertising",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
    MetricDefinition(
        "revenue_marketing_services",
        "revenue_marketing_services",
        "Marketing Services",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
    MetricDefinition(
        "revenue_fintech_business_services",
        "revenue_fintech_business_services",
        "FinTech and Business Services",
        "GAAP_REPORTED",
        "IFRS",
        "CNY",
    ),
)


def _utc_timestamp(value: Any, *, field: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"{field} is not a valid timestamp")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


def _default_fixture_path() -> Path:
    candidates = (
        Path(__file__).resolve().parent.parent
        / "tests"
        / "fixtures"
        / "tencent_ir"
        / "tencent_disclosures_2021_2026.json",
        Path.cwd()
        / "tests"
        / "fixtures"
        / "tencent_ir"
        / "tencent_disclosures_2021_2026.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Tencent disclosures fixture is not installed")


def load_tencent_disclosure_records(
    fixture_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load the audited, source-backed disclosure index."""
    path = _default_fixture_path() if fixture_path is None else Path(fixture_path)
    if not path.is_file():
        raise FileNotFoundError(f"Tencent disclosures fixture not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("Tencent disclosures fixture must contain a JSON list")
    return payload


def _actual_id(
    *,
    entity_id: str,
    accession_no: str,
    metric: str,
    accounting_basis: str,
    metric_basis: str,
    period_label: str,
    value_origin: str,
    version: int,
    revision_reason: str,
    source_document_id: str,
    source_document_sha256: str,
    published_at: pd.Timestamp,
) -> str:
    payload = {
        "accounting_basis": accounting_basis,
        "accession_no": accession_no,
        "entity_id": entity_id,
        "metric": metric,
        "metric_basis": metric_basis,
        "period_label": period_label,
        "published_at": published_at.isoformat(),
        "revision_reason": revision_reason,
        "source_document_id": source_document_id,
        "source_document_sha256": source_document_sha256,
        "value_origin": value_origin,
        "version": version,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"ACT_0700_{digest}"


def _disclosure_timestamps(
    item: Mapping[str, Any],
) -> tuple[pd.Timestamp, pd.Timestamp]:
    filing_at = _utc_timestamp(item["filing_at"], field="filing_at")
    published_at = _utc_timestamp(item["published_at"], field="published_at")
    return filing_at, published_at


def transform_tencent_disclosures_to_actuals(
    disclosures: Sequence[Mapping[str, Any]],
    *,
    as_of_utc: pd.Timestamp | None = None,
    retrieved_at_utc: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    """Transform only disclosures that were public by ``as_of_utc``."""
    retrieved_at = _utc_timestamp(
        (
            pd.Timestamp.now(tz="UTC")
            if retrieved_at_utc is None
            else retrieved_at_utc
        ),
        field="retrieved_at_utc",
    )
    visibility_cutoff = _utc_timestamp(
        retrieved_at if as_of_utc is None else as_of_utc,
        field="as_of_utc",
    )
    if retrieved_at < visibility_cutoff:
        raise ValueError("retrieved_at_utc must be on or after as_of_utc")
    rows: list[dict[str, Any]] = []

    sorted_disclosures = sorted(
        disclosures,
        key=lambda item: (
            str(item["period_end"]),
            str(item.get("published_at", "")),
        ),
    )
    for item in sorted_disclosures:
        filing_at, published_at = _disclosure_timestamps(item)
        disclosure_public_at = max(filing_at, published_at)
        if disclosure_public_at > visibility_cutoff:
            continue

        period_label = str(item["period_label"]).strip()
        period_start = _utc_timestamp(item["period_start"], field="period_start")
        period_end = _utc_timestamp(item["period_end"], field="period_end")
        accession_no = str(item["accession_no"]).strip()
        source_document_id = str(item["source_document_id"]).strip()
        source_document_sha256 = str(item["source_document_sha256"]).strip().lower()
        source_url = str(item["source_url"]).strip()
        version = int(item.get("version", 1))
        revision_reason = str(
            item.get("revision_reason", "initial_filing")
        ).strip()
        value_origin = str(item["value_origin"]).strip()
        source_page_refs = item.get("source_page_refs")
        if not isinstance(source_page_refs, Mapping):
            raise ValueError(f"{period_label}: source_page_refs must be a mapping")
        derivation_methods = item.get("derivation_methods")
        if not isinstance(derivation_methods, Mapping):
            raise ValueError(f"{period_label}: derivation_methods must be a mapping")

        for definition in METRIC_DEFINITIONS:
            if item.get(definition.source_field) is None:
                continue
            source_page_ref = str(
                source_page_refs.get(definition.source_field, "")
            ).strip()
            if not source_page_ref:
                raise ValueError(
                    f"{period_label}: missing source_page_ref for "
                    f"{definition.source_field}"
                )

            raw_value = float(item[definition.source_field])
            if definition.is_per_share:
                reported_value = raw_value
                normalization_note = "as_reported_rmb_per_share"
            else:
                reported_value = raw_value * 1_000_000.0
                normalization_note = "scaled_from_millions_rmb_as_reported"

            actual_id = _actual_id(
                entity_id=TENCENT_ENTITY_ID,
                accession_no=accession_no,
                metric=definition.metric,
                accounting_basis=definition.accounting_basis,
                metric_basis=definition.metric_basis,
                period_label=period_label,
                value_origin=value_origin,
                version=version,
                revision_reason=revision_reason,
                source_document_id=source_document_id,
                source_document_sha256=source_document_sha256,
                published_at=published_at,
            )
            row = {
                "actual_id": actual_id,
                "version": version,
                "supersedes_actual_id": str(
                    item.get("supersedes_actual_id", "")
                ).strip(),
                "entity_id": TENCENT_ENTITY_ID,
                "listing_id": TENCENT_LISTING_ID,
                "canonical_ticker": TENCENT_CANONICAL_TICKER,
                "metric": definition.metric,
                "source_metric_label": definition.source_metric_label,
                "metric_basis": definition.metric_basis,
                "period_label": period_label,
                "period_start": period_start,
                "period_end": period_end,
                "reported_value": reported_value,
                "normalized_value": reported_value,
                "normalization_note": normalization_note,
                "currency": TENCENT_REPORTING_CURRENCY,
                "unit": definition.unit,
                "accounting_basis": definition.accounting_basis,
                "filing_at": filing_at,
                "published_at": published_at,
                "retrieved_at_utc": retrieved_at,
                "source_url": source_url,
                "accession_no": accession_no,
                "source_document_id": source_document_id,
                "source_document_sha256": source_document_sha256,
                "source_page_ref": source_page_ref,
                "value_origin": value_origin,
                "derivation_method": str(
                    derivation_methods.get(definition.source_field, "")
                ).strip(),
                "timestamp_precision": str(item["timestamp_precision"]).strip(),
                "form": "RESULTS_ANNOUNCEMENT",
                "xbrl_frame": "",
                "revision_reason": revision_reason,
                "is_restatement": bool(item.get("is_restatement", False)),
                "source_id": "hkex:tencent_results",
                "source_quality": SOURCE_QUALITY_OFFICIAL,
                "pit_class": PIT_CLASS_OBSERVED,
                "source_license_class": LICENSE_CLASS,
                "source_note": (
                    f"{str(item['document_title']).strip()}; "
                    "HKEX publication timestamp converted from Asia/Hong_Kong "
                    "metadata to UTC; current-period values only; "
                    f"source_body_evidence={str(item['source_body_evidence']).strip()}"
                ),
                "registry_version": REGISTRY_VERSION,
            }
            rows.append(row)

    return rows


def validate_tencent_actuals(frame: pd.DataFrame) -> None:
    """Fail closed on contract, identity, causality, and basis violations."""
    if list(frame.columns) != TENCENT_EARNINGS_ACTUALS_COLUMNS:
        raise ValueError("Tencent actuals do not match the enriched exact schema")
    if frame.empty:
        return

    if frame["actual_id"].duplicated().any():
        raise ValueError("Tencent actuals contain duplicate actual_id values")
    natural_key = [
        "entity_id",
        "accession_no",
        "period_label",
        "metric",
        "metric_basis",
        "version",
    ]
    if frame.duplicated(natural_key).any():
        raise ValueError("Tencent actuals contain duplicate natural keys")

    required_text = [
        "actual_id",
        "entity_id",
        "listing_id",
        "canonical_ticker",
        "metric",
        "source_metric_label",
        "metric_basis",
        "period_label",
        "currency",
        "unit",
        "accounting_basis",
        "source_url",
        "accession_no",
        "source_document_id",
        "source_document_sha256",
        "source_page_ref",
        "value_origin",
        "derivation_method",
        "timestamp_precision",
        "pit_class",
    ]
    for column in required_text:
        col_series = frame[column]
        if isinstance(col_series, pd.DataFrame):
            col_series = col_series.iloc[:, 0]
        if col_series.isna().any() or col_series.astype(str).str.strip().eq("").any():
            raise ValueError("Tencent actuals contain missing required values")

    numeric = frame[["reported_value", "normalized_value"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric.isna().any().any() or not (
        numeric.abs() < float("inf")
    ).all().all():
        raise ValueError("Tencent actual values must be finite")

    timestamp_columns = (
        "period_start",
        "period_end",
        "filing_at",
        "published_at",
        "retrieved_at_utc",
    )
    if frame[list(timestamp_columns)].isna().any().any():
        raise ValueError("Tencent actuals contain missing timestamps")
    if (frame["period_start"] > frame["period_end"]).any():
        raise ValueError("Tencent actuals contain invalid period bounds")
    if (frame["period_end"] > frame["filing_at"]).any():
        raise ValueError("Tencent actuals contain periods ending after filing")
    for source_time in ("filing_at", "published_at"):
        if (frame[source_time] > frame["retrieved_at_utc"]).any():
            raise ValueError(
                f"Tencent actuals violate {source_time}/retrieved_at causality"
            )

    metric_bases = set(frame["metric_basis"])
    if not metric_bases.issubset(TENCENT_OFFICIAL_METRIC_BASES):
        raise ValueError(f"unsupported metric_basis values: {sorted(metric_bases)}")
    metric_contract = {
        (definition.metric, definition.metric_basis): definition.source_metric_label
        for definition in METRIC_DEFINITIONS
    }
    observed_metric_pairs = set(
        zip(frame["metric"], frame["metric_basis"], strict=True)
    )
    if not observed_metric_pairs.issubset(metric_contract):
        raise ValueError("unsupported canonical metric/metric_basis pair")
    expected_labels = frame.apply(
        lambda row: metric_contract[(row["metric"], row["metric_basis"])],
        axis=1,
    )
    if not frame["source_metric_label"].eq(expected_labels).all():
        raise ValueError("source_metric_label does not match canonical metric")
    for _, period_rows in frame.groupby("period_label", sort=False):
        period_metrics = set(period_rows["metric"])
        if {
            "revenue_online_advertising",
            "revenue_marketing_services",
        }.issubset(period_metrics):
            raise ValueError(
                "Online Advertising and Marketing Services must not be bridged "
                "within one disclosed period"
            )
    if not set(frame["pit_class"]).issubset(SUPPORTED_PIT_CLASSES):
        raise ValueError("unsupported pit_class values")
    if not set(frame["value_origin"]).issubset(SUPPORTED_VALUE_ORIGINS):
        raise ValueError("unsupported value_origin values")
    if not set(frame["derivation_method"]).issubset(
        SUPPORTED_DERIVATION_METHODS
    ):
        raise ValueError("unsupported derivation_method values")

    expected_accounting_basis = {
        "GAAP_REPORTED": "IFRS",
        "NON_IFRS_MANAGEMENT": "Non-IFRS management measure",
    }
    for metric_basis, accounting_basis in expected_accounting_basis.items():
        subset = frame.loc[frame["metric_basis"].eq(metric_basis)]
        if not subset["accounting_basis"].eq(accounting_basis).all():
            raise ValueError(
                f"{metric_basis} rows have inconsistent accounting_basis"
            )

    if not frame["accession_no"].str.fullmatch(r"hkexnews:\d+").all():
        raise ValueError("invalid HKEX accession_no")
    if not frame["source_document_id"].str.fullmatch(r"\d{13}").all():
        raise ValueError("invalid HKEX source_document_id")
    if not frame["source_document_sha256"].str.fullmatch(
        r"[0-9a-f]{64}"
    ).all():
        raise ValueError("invalid source_document_sha256")
    if not frame["source_url"].str.fullmatch(
        r"https://www1\.hkexnews\.hk/.+/\d{13}\.pdf"
    ).all():
        raise ValueError("source_url must be an official HKEX statutory PDF")
    if not all(
        document_id in source_url
        for document_id, source_url in zip(
            frame["source_document_id"],
            frame["source_url"],
            strict=True,
        )
    ):
        raise ValueError("source_document_id does not match source_url")
    if frame["source_page_ref"].str.strip().eq("").any():
        raise ValueError("source_page_ref must be present")
    if not frame["timestamp_precision"].eq("minute").all():
        raise ValueError("unsupported timestamp_precision")
    if not frame["source_quality"].eq(SOURCE_QUALITY_OFFICIAL).all():
        raise ValueError("PDF-extracted values must use source_quality=official_body")
    if not frame["period_label"].str.fullmatch(r"[1-4]Q20\d{2}").all():
        raise ValueError("invalid period_label")

    if not frame["version"].apply(
        lambda value: isinstance(value, int) and value >= 1
    ).all():
        raise ValueError("version must be a positive integer")
    expected_actual_ids = frame.apply(
        lambda row: _actual_id(
            entity_id=row["entity_id"],
            accession_no=row["accession_no"],
            metric=row["metric"],
            accounting_basis=row["accounting_basis"],
            metric_basis=row["metric_basis"],
            period_label=row["period_label"],
            value_origin=row["value_origin"],
            version=int(row["version"]),
            revision_reason=row["revision_reason"],
            source_document_id=row["source_document_id"],
            source_document_sha256=row["source_document_sha256"],
            published_at=row["published_at"],
        ),
        axis=1,
    )
    if not frame["actual_id"].eq(expected_actual_ids).all():
        raise ValueError("actual_id does not match the canonical natural key")

    document_consistency = frame.groupby("source_document_id").agg(
        {
            "source_document_sha256": "nunique",
            "source_url": "nunique",
            "accession_no": "nunique",
        }
    )
    if (document_consistency > 1).any().any():
        raise ValueError("source document lineage is inconsistent")


def assess_core_quarter_coverage(frame: pd.DataFrame) -> int:
    """Count distinct periods containing every required canonical core metric."""
    if frame.empty:
        return 0
    relevant = frame.loc[
        frame.apply(
            lambda row: (row["metric"], row["metric_basis"])
            in REQUIRED_CORE_METRICS,
            axis=1,
        )
    ]
    complete = 0
    for _, group in relevant.groupby("period_label", sort=False):
        observed = set(zip(group["metric"], group["metric_basis"], strict=True))
        if REQUIRED_CORE_METRICS.issubset(observed):
            complete += 1
    return complete


def _atomic_write_parquet(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
        frame.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def parse_and_collect_tencent_actuals(
    fixture_path: Path | None = None,
    *,
    as_of_utc: pd.Timestamp | None = None,
    retrieved_at_utc: pd.Timestamp | None = None,
    output_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collect Tencent actuals as known at ``as_of_utc`` and their source state."""
    collection_clock = _utc_timestamp(
        (
            pd.Timestamp.now(tz="UTC")
            if retrieved_at_utc is None
            else retrieved_at_utc
        ),
        field="retrieved_at_utc",
    )
    visibility_cutoff = _utc_timestamp(
        collection_clock if as_of_utc is None else as_of_utc,
        field="as_of_utc",
    )
    if collection_clock < visibility_cutoff:
        raise ValueError("retrieved_at_utc must be on or after as_of_utc")
    disclosures = load_tencent_disclosure_records(fixture_path)
    rows = transform_tencent_disclosures_to_actuals(
        disclosures,
        as_of_utc=visibility_cutoff,
        retrieved_at_utc=collection_clock,
    )
    frame = pd.DataFrame(rows, columns=TENCENT_EARNINGS_ACTUALS_COLUMNS)
    timestamp_columns = (
        "period_start",
        "period_end",
        "filing_at",
        "published_at",
        "retrieved_at_utc",
    )
    for column in timestamp_columns:
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    validate_tencent_actuals(frame)

    complete_core_quarters = assess_core_quarter_coverage(frame)
    observed_quarters = frame["period_label"].nunique()
    if frame.empty:
        status = "no_records"
        period_range = "none"
    else:
        status = (
            "available"
            if complete_core_quarters >= MINIMUM_COMPLETE_CORE_QUARTERS
            else "partial"
        )
        ordered_periods = (
            frame[["period_label", "period_end"]]
            .drop_duplicates()
            .sort_values("period_end")
        )
        period_range = (
            f"{ordered_periods.iloc[0]['period_label']}-"
            f"{ordered_periods.iloc[-1]['period_label']}"
        )

    first_observation = frame["published_at"].min() if not frame.empty else pd.NaT
    latest_observation = frame["published_at"].max() if not frame.empty else pd.NaT
    state = {
        "source_id": "earnings:tencent_hkex_financials",
        "source_kind": "earnings",
        "status": status,
        "detail": (
            f"Tencent official HKEX results: {observed_quarters} disclosed quarters "
            f"({period_range}), {complete_core_quarters} complete core quarters, "
            f"{len(frame)} records; GAAP and Non-IFRS tracks are separate"
        ),
        "row_count": len(frame),
        "first_observation_at": first_observation,
        "latest_observation_at": latest_observation,
        "source_latest_at": latest_observation,
        "retrieved_at_utc": collection_clock,
        "source_url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
        "pit_class": PIT_CLASS_OBSERVED,
        "source_license_class": LICENSE_CLASS,
        "cadence": "quarterly",
    }
    state_frame = pd.DataFrame([state], columns=SOURCE_STATE_COLUMNS)
    for column in (
        "first_observation_at",
        "latest_observation_at",
        "source_latest_at",
        "retrieved_at_utc",
    ):
        state_frame[column] = pd.to_datetime(
            state_frame[column],
            errors="coerce",
            utc=True,
        )

    if output_dir is not None:
        output_path = Path(output_dir)
        _atomic_write_parquet(
            frame,
            output_path / "tencent_earnings_actuals_v1.parquet",
        )
        _atomic_write_parquet(
            state_frame,
            output_path / "tencent_earnings_actuals_state.parquet",
        )

    return frame, state_frame


__all__ = [
    "METRIC_DEFINITIONS",
    "REQUIRED_CORE_METRICS",
    "SUPPORTED_METRIC_BASES",
    "TENCENT_EARNINGS_ACTUALS_COLUMNS",
    "TENCENT_ENTITY_ID",
    "TENCENT_LISTING_ID",
    "assess_core_quarter_coverage",
    "load_tencent_disclosure_records",
    "parse_and_collect_tencent_actuals",
    "transform_tencent_disclosures_to_actuals",
    "validate_tencent_actuals",
]
