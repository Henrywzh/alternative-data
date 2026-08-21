"""Build auditable valuation and internal-estimate parquet outputs offline."""

from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import pyarrow as pa

from src.research_control_tower.valuation import (
    INTERNAL_ESTIMATES_ARROW_SCHEMA,
    SUPPORTED_PIT_CLASSES,
    VALUATION_SNAPSHOTS_ARROW_SCHEMA,
    ValuationInput,
    build_valuation_snapshot_row,
    canonicalize_metric_basis,
    empty_frame,
    frame_from_rows,
    load_internal_estimates_csv,
    validate_internal_estimates_df,
    validate_valuation_snapshots_df,
    write_parquet_atomic,
)


logger = logging.getLogger(__name__)

QUOTE_REQUIRED_COLUMNS = frozenset(
    {
        "quote_id",
        "listing_id",
        "quote_timestamp",
        "retrieved_at_utc",
        "last_price",
        "currency",
        "source_id",
        "source_url",
        "pit_class",
    }
)
CONSENSUS_REQUIRED_COLUMNS = frozenset(
    {
        "snapshot_id",
        "provider",
        "listing_id",
        "metric",
        "fiscal_period",
        "fiscal_year",
        "snapshot_at",
        "provider_asof",
        "retrieved_at_utc",
        "value",
        "statistic",
        "currency",
        "unit",
        "accounting_basis",
        "source_url",
        "pit_class",
    }
)
CONSENSUS_HEALTH_REQUIRED_COLUMNS = frozenset(
    {
        "provider",
        "status",
        "mapped_row_count",
        "latest_snapshot_at",
        "as_of",
        "entitlement_status",
        "entitlement_ref",
    }
)
FX_REQUIRED_COLUMNS = frozenset(
    {
        "observation_date",
        "base_currency",
        "quote_currency",
        "value",
        "retrieved_at",
        "source_name",
        "source_url",
    }
)


def _read_frame(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"unsupported local input format: {path}")


def _as_utc_series(frame: pd.DataFrame, column: str) -> pd.Series:
    parsed: list[pd.Timestamp | pd.NaT] = []
    for value in frame[column]:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            timestamp = pd.NaT
        parsed.append(
            pd.NaT
            if pd.isna(timestamp) or timestamp.tzinfo is None
            else timestamp.tz_convert("UTC")
        )
    return pd.Series(
        pd.to_datetime(parsed, utc=True, errors="coerce"),
        index=frame.index,
    )


def _finite_positive(value: Any) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and numeric > 0


def _accepted_consensus_providers(
    frame: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    max_age_days: int,
) -> frozenset[str]:
    """Return providers admitted by the Task 3 provider-policy sidecar."""

    if max_age_days < 0:
        raise ValueError("max_consensus_age_days must be non-negative")
    missing = CONSENSUS_HEALTH_REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(
            "consensus health has invalid schema; missing "
            + ", ".join(sorted(missing))
        )
    health = frame.copy()
    health["provider_key"] = (
        health["provider"].fillna("").astype(str).str.strip().str.casefold()
    )
    duplicate_providers = health.loc[
        health["provider_key"].ne("")
        & health["provider_key"].duplicated(keep=False),
        "provider_key",
    ]
    if not duplicate_providers.empty:
        raise ValueError(
            "consensus health has duplicate providers: "
            + ", ".join(sorted(set(duplicate_providers)))
        )
    health["latest_snapshot_at"] = _as_utc_series(
        health, "latest_snapshot_at"
    )
    health["health_as_of"] = _as_utc_series(health, "as_of")
    health["mapped_row_count"] = pd.to_numeric(
        health["mapped_row_count"], errors="coerce"
    )
    status = health["status"].fillna("").astype(str).str.strip().str.casefold()
    entitlement_status = (
        health["entitlement_status"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.casefold()
    )
    entitlement_ref = (
        health["entitlement_ref"].fillna("").astype(str).str.strip()
    )
    maximum_age = pd.Timedelta(days=max_age_days)
    usable = health.loc[
        health["provider_key"].ne("")
        & status.eq("available")
        & health["mapped_row_count"].gt(0)
        & health["latest_snapshot_at"].notna()
        & health["health_as_of"].notna()
        & health["latest_snapshot_at"].le(health["health_as_of"])
        & health["health_as_of"].le(as_of)
        & health["latest_snapshot_at"].le(as_of)
        & (as_of - health["latest_snapshot_at"]).le(maximum_age)
        & entitlement_status.isin(
            {"terms_unverified", "permitted_local_private"}
        )
        & entitlement_ref.str.startswith("task3-provider-policy:")
    ]
    return frozenset(usable["provider_key"])


def _latest_quote(
    frame: pd.DataFrame | None, *, listing_id: str, as_of: pd.Timestamp
) -> pd.Series | None:
    if frame is None or frame.empty or not QUOTE_REQUIRED_COLUMNS.issubset(frame.columns):
        return None
    candidates = frame.loc[frame["listing_id"].eq(listing_id)].copy()
    candidates["quote_timestamp"] = _as_utc_series(candidates, "quote_timestamp")
    candidates["retrieved_at_utc"] = _as_utc_series(
        candidates, "retrieved_at_utc"
    )
    candidates["last_price"] = pd.to_numeric(
        candidates["last_price"], errors="coerce"
    )
    candidates = candidates.loc[
        candidates["quote_timestamp"].notna()
        & candidates["retrieved_at_utc"].notna()
        & candidates["quote_timestamp"].le(as_of)
        & candidates["retrieved_at_utc"].le(as_of)
        & candidates["last_price"].map(_finite_positive)
        & candidates["quote_id"].fillna("").astype(str).str.strip().ne("")
        & candidates["currency"].fillna("").astype(str).str.strip().ne("")
        & candidates["source_id"].fillna("").astype(str).str.strip().ne("")
        & candidates["source_url"].fillna("").astype(str).str.strip().ne("")
        & candidates["pit_class"].isin(SUPPORTED_PIT_CLASSES)
        & candidates["quote_timestamp"].le(candidates["retrieved_at_utc"])
    ]
    if candidates.empty:
        return None
    return candidates.sort_values(
        ["quote_timestamp", "retrieved_at_utc", "quote_id"],
        kind="mergesort",
    ).iloc[-1]


def _latest_consensus_eps(
    frame: pd.DataFrame | None,
    *,
    listing_id: str,
    as_of: pd.Timestamp,
    fiscal_period: str,
    fiscal_year: int | None,
    statistic: str,
) -> pd.Series | None:
    if (
        frame is None
        or frame.empty
        or not CONSENSUS_REQUIRED_COLUMNS.issubset(frame.columns)
    ):
        return None
    candidates = frame.loc[
        frame["listing_id"].eq(listing_id)
        & frame["metric"].eq("eps")
        & frame["fiscal_period"].eq(fiscal_period)
        & frame["statistic"].eq(statistic)
        & frame["unit"].eq("currency_per_share")
    ].copy()
    candidates["fiscal_year"] = pd.to_numeric(
        candidates["fiscal_year"], errors="coerce"
    )
    for column in ("snapshot_at", "provider_asof", "retrieved_at_utc"):
        candidates[column] = _as_utc_series(candidates, column)
    candidates["value"] = pd.to_numeric(candidates["value"], errors="coerce")
    candidates = candidates.loc[
        candidates["snapshot_at"].notna()
        & candidates["provider_asof"].notna()
        & candidates["retrieved_at_utc"].notna()
        & candidates["snapshot_at"].le(as_of)
        & candidates["provider_asof"].le(as_of)
        & candidates["retrieved_at_utc"].le(as_of)
        & candidates["value"].map(_finite_positive)
        & candidates["snapshot_id"].fillna("").astype(str).str.strip().ne("")
        & candidates["accounting_basis"].fillna("").astype(str).str.strip().ne("")
        & candidates["currency"].fillna("").astype(str).str.strip().ne("")
        & candidates["provider"].fillna("").astype(str).str.strip().ne("")
        & candidates["source_url"].fillna("").astype(str).str.strip().ne("")
        & candidates["pit_class"].isin(SUPPORTED_PIT_CLASSES)
        & candidates["snapshot_at"].le(candidates["retrieved_at_utc"])
        & candidates["provider_asof"].le(candidates["retrieved_at_utc"])
    ]
    if fiscal_year is not None:
        candidates = candidates.loc[candidates["fiscal_year"].eq(fiscal_year)]
    else:
        eligible_years = candidates.loc[
            candidates["fiscal_year"].ge(as_of.year), "fiscal_year"
        ]
        if eligible_years.empty:
            return None
        candidates = candidates.loc[
            candidates["fiscal_year"].eq(eligible_years.min())
        ]
    if candidates.empty:
        return None
    return candidates.sort_values(
        [
            "fiscal_year",
            "snapshot_at",
            "provider_asof",
            "retrieved_at_utc",
            "snapshot_id",
        ],
        kind="mergesort",
    ).iloc[-1]


def _prepare_fx(frame: pd.DataFrame | None, as_of: pd.Timestamp) -> pd.DataFrame:
    if frame is None or frame.empty or not FX_REQUIRED_COLUMNS.issubset(frame.columns):
        return pd.DataFrame()
    prepared = frame.copy()
    prepared["base_currency"] = (
        prepared["base_currency"].fillna("").astype(str).str.strip().str.upper()
    )
    prepared["quote_currency"] = (
        prepared["quote_currency"].fillna("").astype(str).str.strip().str.upper()
    )
    prepared["observation_at"] = pd.to_datetime(
        prepared["observation_date"], utc=True, errors="coerce"
    )
    prepared["retrieved_at_utc"] = _as_utc_series(prepared, "retrieved_at")
    prepared["value"] = pd.to_numeric(prepared["value"], errors="coerce")
    return prepared.loc[
        prepared["observation_at"].notna()
        & prepared["retrieved_at_utc"].notna()
        & prepared["observation_at"].le(as_of)
        & prepared["retrieved_at_utc"].le(as_of)
        & prepared["value"].map(_finite_positive)
        & prepared["base_currency"].ne("")
        & prepared["quote_currency"].ne("")
        & prepared["source_name"].fillna("").astype(str).str.strip().ne("")
        & prepared["source_url"].fillna("").astype(str).str.strip().ne("")
        & prepared["observation_at"].le(prepared["retrieved_at_utc"])
    ].copy()


def _fx_result(
    *,
    factor: float,
    denominator_currency: str,
    numerator_currency: str,
    rows: Sequence[pd.Series],
    label: str,
) -> dict[str, Any]:
    snapshot = max(pd.Timestamp(row["observation_at"]) for row in rows)
    retrieved = max(pd.Timestamp(row["retrieved_at_utc"]) for row in rows)
    source_names = sorted({str(row["source_name"]).strip() for row in rows})
    source_urls = sorted({str(row["source_url"]).strip() for row in rows})
    return {
        "fx_rate_applied": factor,
        "fx_base_currency": denominator_currency,
        "fx_quote_currency": numerator_currency,
        "fx_source": f"{label}:{'+'.join(source_names)}",
        "fx_source_url": ";".join(source_urls),
        "fx_snapshot_at_utc": snapshot.to_pydatetime(),
        "fx_retrieved_at_utc": retrieved.to_pydatetime(),
    }


def resolve_fx_factor(
    frame: pd.DataFrame | None,
    *,
    denominator_currency: str,
    numerator_currency: str,
    as_of: pd.Timestamp,
) -> dict[str, Any] | None:
    """Resolve denominator-to-numerator FX, including same-day cross rates."""

    denominator = denominator_currency.strip().upper()
    numerator = numerator_currency.strip().upper()
    if denominator == numerator:
        return {}
    prepared = _prepare_fx(frame, as_of)
    if prepared.empty:
        return None

    direct = prepared.loc[
        prepared["base_currency"].eq(denominator)
        & prepared["quote_currency"].eq(numerator)
    ]
    if not direct.empty:
        row = direct.sort_values(
            ["observation_at", "retrieved_at_utc"], kind="mergesort"
        ).iloc[-1]
        return _fx_result(
            factor=float(row["value"]),
            denominator_currency=denominator,
            numerator_currency=numerator,
            rows=[row],
            label=f"{denominator}_TO_{numerator}",
        )

    reverse = prepared.loc[
        prepared["base_currency"].eq(numerator)
        & prepared["quote_currency"].eq(denominator)
    ]
    if not reverse.empty:
        row = reverse.sort_values(
            ["observation_at", "retrieved_at_utc"], kind="mergesort"
        ).iloc[-1]
        return _fx_result(
            factor=1.0 / float(row["value"]),
            denominator_currency=denominator,
            numerator_currency=numerator,
            rows=[row],
            label=f"{denominator}_TO_{numerator}_INVERSE",
        )

    denominator_legs = prepared.loc[
        prepared["quote_currency"].eq(denominator)
    ].copy()
    numerator_legs = prepared.loc[prepared["quote_currency"].eq(numerator)].copy()
    if denominator_legs.empty or numerator_legs.empty:
        return None
    joined = denominator_legs.merge(
        numerator_legs,
        on=["base_currency", "observation_at"],
        suffixes=("_den", "_num"),
    )
    if joined.empty:
        return None
    joined["retrieved_max"] = joined[
        ["retrieved_at_utc_den", "retrieved_at_utc_num"]
    ].max(axis=1)
    selected = joined.sort_values(
        ["observation_at", "retrieved_max", "base_currency"], kind="mergesort"
    ).iloc[-1]
    denominator_row = pd.Series(
        {
            "observation_at": selected["observation_at"],
            "retrieved_at_utc": selected["retrieved_at_utc_den"],
            "source_name": selected["source_name_den"],
            "source_url": selected["source_url_den"],
        }
    )
    numerator_row = pd.Series(
        {
            "observation_at": selected["observation_at"],
            "retrieved_at_utc": selected["retrieved_at_utc_num"],
            "source_name": selected["source_name_num"],
            "source_url": selected["source_url_num"],
        }
    )
    factor = float(selected["value_num"]) / float(selected["value_den"])
    return _fx_result(
        factor=factor,
        denominator_currency=denominator,
        numerator_currency=numerator,
        rows=[denominator_row, numerator_row],
        label=(
            f"{denominator}_TO_{numerator}_VIA_{selected['base_currency']}"
        ),
    )


def compute_tencent_valuation_snapshots(
    quote_snapshots_df: pd.DataFrame | None,
    consensus_snapshots_df: pd.DataFrame | None,
    earnings_actuals_df: pd.DataFrame | None = None,
    fx_rates_df: pd.DataFrame | None = None,
    as_of_utc: datetime | str | pd.Timestamp | None = None,
    *,
    consensus_health_df: pd.DataFrame | None = None,
    max_consensus_age_days: int = 14,
    fiscal_period: str = "annual",
    fiscal_year: int | None = None,
    statistic: str = "mean",
) -> pd.DataFrame:
    """Compute Tencent forward P/E from causal quote, EPS, and FX vintages.

    Automated consensus must be accompanied by its Task 3 provider-policy
    health sidecar. Raw normalized exports are never selected without an
    available, non-stale, entitlement-admitted provider row.
    """

    del earnings_actuals_df
    if as_of_utc is None:
        raise ValueError("as_of_utc is required for deterministic PIT selection")
    as_of = pd.Timestamp(as_of_utc)
    if as_of.tzinfo is None:
        raise ValueError("as_of_utc must be timezone-aware")
    as_of = as_of.tz_convert("UTC")
    filtered_consensus = consensus_snapshots_df
    if consensus_snapshots_df is not None and not consensus_snapshots_df.empty:
        if consensus_health_df is None:
            raise ValueError(
                "consensus health is required for automated valuation derivation"
            )
        accepted_providers = _accepted_consensus_providers(
            consensus_health_df,
            as_of=as_of,
            max_age_days=max_consensus_age_days,
        )
        provider_keys = (
            consensus_snapshots_df["provider"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
            if "provider" in consensus_snapshots_df.columns
            else pd.Series("", index=consensus_snapshots_df.index)
        )
        filtered_consensus = consensus_snapshots_df.loc[
            provider_keys.isin(accepted_providers)
        ].copy()
    quote = _latest_quote(
        quote_snapshots_df, listing_id="0700_HK", as_of=as_of
    )
    consensus = _latest_consensus_eps(
        filtered_consensus,
        listing_id="0700_HK",
        as_of=as_of,
        fiscal_period=fiscal_period,
        fiscal_year=fiscal_year,
        statistic=statistic,
    )
    if quote is None or consensus is None:
        return empty_frame(VALUATION_SNAPSHOTS_ARROW_SCHEMA)

    numerator_currency = str(quote["currency"]).strip().upper()
    denominator_currency = str(consensus["currency"]).strip().upper()
    fx = resolve_fx_factor(
        fx_rates_df,
        denominator_currency=denominator_currency,
        numerator_currency=numerator_currency,
        as_of=as_of,
    )
    if fx is None:
        return empty_frame(VALUATION_SNAPSHOTS_ARROW_SCHEMA)

    accounting_basis = str(consensus["accounting_basis"]).strip()
    pit_class = str(consensus["pit_class"]).strip()
    input_row = ValuationInput(
        listing_id="0700_HK",
        valuation_at=as_of.to_pydatetime(),
        metric_name="forward_pe",
        accounting_basis=accounting_basis,
        metric_basis=canonicalize_metric_basis(accounting_basis),
        numerator_value=float(quote["last_price"]),
        numerator_currency=numerator_currency,
        numerator_ref=str(quote["quote_id"]),
        numerator_source_id=str(quote["source_id"]),
        numerator_source_url=str(quote["source_url"]),
        numerator_pit_class=str(quote["pit_class"]),
        numerator_at_utc=pd.Timestamp(quote["quote_timestamp"]).to_pydatetime(),
        numerator_retrieved_at_utc=pd.Timestamp(
            quote["retrieved_at_utc"]
        ).to_pydatetime(),
        denominator_value=float(consensus["value"]),
        denominator_currency=denominator_currency,
        denominator_ref=str(consensus["snapshot_id"]),
        denominator_source_id=f"consensus:{consensus['provider']}",
        denominator_source_url=str(consensus["source_url"]),
        denominator_pit_class=pit_class,
        denominator_at_utc=pd.Timestamp(consensus["snapshot_at"]).to_pydatetime(),
        denominator_provider_asof_utc=pd.Timestamp(
            consensus["provider_asof"]
        ).to_pydatetime(),
        denominator_retrieved_at_utc=pd.Timestamp(
            consensus["retrieved_at_utc"]
        ).to_pydatetime(),
        source_url=str(consensus["source_url"]),
        retrieved_at_utc=as_of.to_pydatetime(),
        pit_class="repository_captured",
        **fx,
    )
    row = build_valuation_snapshot_row(input_row)
    result = frame_from_rows([row], VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    issues = validate_valuation_snapshots_df(result)
    if issues:
        raise ValueError(f"valuation output validation failed: {issues}")
    return result


def build_explicit_valuation_inputs(frame: pd.DataFrame | None) -> pd.DataFrame:
    """Build any supported metric from fully explicit, audited local inputs."""

    if frame is None or frame.empty:
        return empty_frame(VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    expected = [field.name for field in fields(ValuationInput)]
    if list(frame.columns) != expected:
        raise ValueError("valuation inputs have invalid exact schema")
    rows = [
        build_valuation_snapshot_row(ValuationInput(**row))
        for row in frame.to_dict("records")
    ]
    return frame_from_rows(rows, VALUATION_SNAPSHOTS_ARROW_SCHEMA)


def _combine_valuations(*frames: pd.DataFrame) -> pd.DataFrame:
    nonempty = [frame for frame in frames if not frame.empty]
    if not nonempty:
        return empty_frame(VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    combined = pd.concat(nonempty, ignore_index=True)
    duplicate_ids = combined.loc[
        combined["valuation_id"].duplicated(keep=False), "valuation_id"
    ]
    if not duplicate_ids.empty:
        raise ValueError(
            "duplicate valuation_id values: "
            + ", ".join(sorted(set(duplicate_ids.astype(str))))
        )
    combined = combined.sort_values("valuation_id", kind="mergesort")
    return pa.Table.from_pandas(
        combined,
        schema=VALUATION_SNAPSHOTS_ARROW_SCHEMA,
        preserve_index=False,
    ).to_pandas()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build local valuation_snapshots and internal_estimates marts"
    )
    parser.add_argument("--quotes", type=Path)
    parser.add_argument("--consensus", type=Path)
    parser.add_argument(
        "--consensus-health",
        type=Path,
        help=(
            "Task 3 provider-policy health sidecar required whenever "
            "--consensus is populated"
        ),
    )
    parser.add_argument(
        "--max-consensus-age-days",
        type=int,
        default=14,
        help="Maximum age of the admitted provider's latest snapshot",
    )
    parser.add_argument("--earnings-actuals", type=Path)
    parser.add_argument("--fx-rates", type=Path)
    parser.add_argument("--valuation-inputs", type=Path)
    parser.add_argument(
        "--internal-estimates",
        type=Path,
        default=Path("config/research_control_tower/internal_estimates.csv"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--fiscal-period", default="annual")
    parser.add_argument("--fiscal-year", type=int)
    parser.add_argument("--statistic", default="mean")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    as_of = pd.Timestamp(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of must include a timezone")

    quotes = _read_frame(args.quotes)
    consensus = _read_frame(args.consensus)
    consensus_health = _read_frame(args.consensus_health)
    earnings = _read_frame(args.earnings_actuals)
    fx_rates = _read_frame(args.fx_rates)
    explicit_inputs = _read_frame(args.valuation_inputs)
    internal_estimates = load_internal_estimates_csv(args.internal_estimates)
    internal_issues = validate_internal_estimates_df(internal_estimates)
    if internal_issues:
        raise ValueError(f"internal estimates validation failed: {internal_issues}")

    derived = compute_tencent_valuation_snapshots(
        quotes,
        consensus,
        earnings,
        fx_rates,
        as_of,
        consensus_health_df=consensus_health,
        max_consensus_age_days=args.max_consensus_age_days,
        fiscal_period=args.fiscal_period,
        fiscal_year=args.fiscal_year,
        statistic=args.statistic,
    )
    explicit = build_explicit_valuation_inputs(explicit_inputs)
    valuations = _combine_valuations(derived, explicit)
    valuation_issues = validate_valuation_snapshots_df(valuations)
    if valuation_issues:
        raise ValueError(f"valuation validation failed: {valuation_issues}")

    valuation_path = args.output_dir / "valuation_snapshots.parquet"
    estimates_path = args.output_dir / "internal_estimates.parquet"
    write_parquet_atomic(
        valuations, VALUATION_SNAPSHOTS_ARROW_SCHEMA, valuation_path
    )
    write_parquet_atomic(
        internal_estimates, INTERNAL_ESTIMATES_ARROW_SCHEMA, estimates_path
    )
    logger.info(
        "wrote valuation_snapshots=%d internal_estimates=%d to %s",
        len(valuations),
        len(internal_estimates),
        args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
