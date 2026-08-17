"""SHKP-wide SRPE transaction signal contract.

The transaction scratch runner intentionally writes one immutable dataset per
batch.  This module is the consolidation boundary: it reads every scratch
batch, removes repeated register-version/smoke-run rows by a semantic event
key, computes phase-month signals, and records the coverage state explicitly.

Nothing here promotes a phase to SHKP ownership.  The output is a
phase-level leading-indicator layer; attributable sales remain null unless a
reviewed, date-bounded ownership interval is present in the candidate gate.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from .config import NORMALIZED_DIR
from .sources.shkp import resolve_strict_ownership_attribution
from .storage import load_latest_normalized, save_normalized_dataset


SCRATCH_TRANSACTION_DATASET = "shkp_srpe_scratch_srpe_pilot_transaction_events"
SCRATCH_AUDIT_DATASET = "shkp_srpe_scratch_srpe_pilot_document_audit"
SCRATCH_PRICE_DATASET = "shkp_srpe_scratch_srpe_pilot_price_list_units"

SIGNAL_DATASET = "shkp_srpe_project_month_signals"
STATUS_DATASET = "shkp_srpe_project_month_status"
EVENT_DATASET = "shkp_srpe_project_transaction_events_dedup"
COVERAGE_DATASET = "shkp_srpe_signal_coverage"
INDICATIVE_OWNERSHIP_DATASET = "shkp_indicative_ownership_roster"
INDICATIVE_SIGNAL_DATASET = "shkp_indicative_project_month_signals"
HISTORICAL_MONTHLY_SIGNAL_DATASET = "shkp_historical_srpe_pilot_developer_monthly_signals"
ALL_HISTORY_SIGNAL_DATASET = "shkp_srpe_project_month_signals_all_history"
ALL_HISTORY_INDICATIVE_SIGNAL_DATASET = "shkp_indicative_project_month_signals_all_history"
ALL_HISTORY_COVERAGE_DATASET = "shkp_indicative_project_month_signals_all_history_coverage"
DATE_GAP_DATASET = "shkp_srpe_transaction_date_gaps"

_PHASE_KEYS = ["srpe_development_id", "development_id"]
_UNIT_COLUMNS = ["block_name", "floor", "unit"]
_EVENT_KEY_COLUMNS = [
    "srpe_development_id",
    "development_id",
    "block_name",
    "floor",
    "unit",
    "date_of_pasp",
    "date_of_asp",
    "date_of_asp_termination",
    "transaction_price_hkd",
    "is_cancelled",
]


def _run_frames(dataset_name: str) -> list[pd.DataFrame]:
    root = NORMALIZED_DIR / dataset_name
    if not root.is_dir():
        return []
    frames: list[pd.DataFrame] = []
    for run_dir in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name):
        path = run_dir / f"{dataset_name}.parquet"
        if path.exists():
            frame = pd.read_parquet(path)
            if not frame.empty:
                frame = frame.copy()
                frame["scratch_run_id"] = run_dir.name
                frames.append(frame)
    return frames


def load_all_shkp_scratch_transactions() -> pd.DataFrame:
    frames = _run_frames(SCRATCH_TRANSACTION_DATASET)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_all_shkp_scratch_audits() -> pd.DataFrame:
    frames = _run_frames(SCRATCH_AUDIT_DATASET)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_all_shkp_scratch_price_lists() -> pd.DataFrame:
    frames = _run_frames(SCRATCH_PRICE_DATASET)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _parse_boolish(values: pd.Series, *, default: bool = False) -> pd.Series:
    """Parse boolean columns without treating the string ``"False"`` as true."""
    if values is None:
        return pd.Series(dtype="bool")
    truthy = {"1", "true", "yes", "y", "t"}
    falsy = {"0", "false", "no", "n", "f", "", "none", "null", "nan"}

    def parse(value: Any) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass
        text = str(value).strip().casefold()
        if text in truthy:
            return True
        if text in falsy:
            return False
        return default

    return values.map(parse).astype(bool)


def _normalise_transactions(transactions: pd.DataFrame) -> pd.DataFrame:
    if transactions is None or transactions.empty:
        return pd.DataFrame()
    tx = transactions.copy()
    for column in _PHASE_KEYS + _UNIT_COLUMNS + ["transaction_id"]:
        if column not in tx.columns:
            tx[column] = ""
        tx[column] = tx[column].fillna("").astype(str).str.strip()
    for column in ("date_of_pasp", "date_of_asp", "date_of_asp_termination"):
        raw_dates = tx[column] if column in tx.columns else pd.Series(pd.NaT, index=tx.index)
        tx[column] = pd.to_datetime(raw_dates, errors="coerce")
    price_values = tx["transaction_price_hkd"] if "transaction_price_hkd" in tx.columns else pd.Series(pd.NA, index=tx.index)
    tx["transaction_price_hkd"] = pd.to_numeric(price_values, errors="coerce")
    # Older/tender SRPE rows can be emitted with collapsed empty property
    # columns: the real price lands in ``unit`` or ``car_parking_space`` while
    # a small column marker lands in ``transaction_price_hkd``. Repair only
    # this narrow source shape (large displaced amount + sub-HKD100k parsed
    # price) before aggregation.
    def shifted_price_candidate(values: pd.Series) -> pd.Series:
        text = values.fillna("").astype(str).str.strip()
        currency = text.str.extract(
            r"(?i)(?:HK)?\$\s*([0-9][0-9,]*(?:\.\d+)?)",
            expand=False,
        )
        plain = text.str.extract(
            r"^\s*([0-9][0-9,]*(?:\.\d+)?)",
            expand=False,
        )
        candidate = currency.astype("string").fillna(plain.astype("string"))
        candidate = pd.to_numeric(candidate.str.replace(",", "", regex=False), errors="coerce")
        return candidate.where(candidate.ge(100_000))

    unit_shifted_price = shifted_price_candidate(tx["unit"])
    parking_shifted_price = shifted_price_candidate(
        tx.get("car_parking_space", pd.Series("", index=tx.index))
    )
    shifted_price = unit_shifted_price.fillna(parking_shifted_price)
    compact_row = shifted_price.notna() & tx["transaction_price_hkd"].fillna(0).lt(100_000)
    tx["parser_quality_status"] = "parsed_standard_row"
    if compact_row.any():
        tx.loc[compact_row, "transaction_price_hkd"] = shifted_price.loc[compact_row]
        unit_source = compact_row & unit_shifted_price.notna()
        parking_source = compact_row & unit_shifted_price.isna() & parking_shifted_price.notna()
        tx.loc[unit_source, "unit"] = ""
        if "car_parking_space" in tx.columns:
            tx.loc[parking_source, "car_parking_space"] = ""
        tx.loc[compact_row, "parser_quality_status"] = "compact_row_price_shift_repaired"
    cancelled_values = tx["is_cancelled"] if "is_cancelled" in tx.columns else pd.Series(False, index=tx.index)
    tx["is_cancelled"] = _parse_boolish(cancelled_values)
    tx["phase_id"] = tx["srpe_development_id"].where(
        tx["srpe_development_id"].ne(""), tx["development_id"]
    )
    tx["project_id"] = tx["phase_id"].map(lambda value: f"shkp-srpe-{value}" if value else "")
    tx["development_group_id"] = tx["development_id"].map(
        lambda value: f"srpe-development-{value}" if value else ""
    )
    tx["unit_key"] = tx[_UNIT_COLUMNS].agg("|".join, axis=1)
    tx.loc[tx["unit_key"].eq("||"), "unit_key"] = tx.loc[
        tx["unit_key"].eq("||"), "transaction_id"
    ]
    tx["date_gap_status"] = "pasp_observed"
    pasp_missing = tx["date_of_pasp"].isna()
    asp_observed = tx["date_of_asp"].notna()
    tx.loc[pasp_missing & asp_observed, "date_gap_status"] = "pasp_missing_asp_observed"
    tx.loc[pasp_missing & ~asp_observed, "date_gap_status"] = "pasp_and_asp_missing"
    tx.loc[~pasp_missing & ~asp_observed, "date_gap_status"] = "pasp_observed_asp_missing"
    # Keep the strict event-period contract anchored to PASP.  Rows with no
    # PASP are quarantined below rather than silently re-dated to ASP.
    tx["event_period"] = tx["date_of_pasp"].dt.to_period("M").dt.to_timestamp()
    tx["cancel_period"] = tx["date_of_asp_termination"].dt.to_period("M").dt.to_timestamp()
    return tx[tx["phase_id"].ne("")].copy()


def deduplicate_shkp_transactions(transactions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Remove repeated rows from register versions and retained smoke runs.

    The semantic key intentionally excludes document ID/hash: the same unit
    event is often repeated in a later register PDF.  Distinct PASP/ASP,
    termination or price values remain separate events, preserving resale and
    contract-update activity for later state reconciliation.
    """
    tx = _normalise_transactions(transactions)
    if tx.empty:
        return tx, {"rows_input": 0, "rows_output": 0, "duplicate_rows": 0}
    for column in _EVENT_KEY_COLUMNS:
        if column not in tx.columns:
            tx[column] = ""
    # Make missing values deterministic before constructing the semantic key.
    key_frame = tx[_EVENT_KEY_COLUMNS].copy()
    for column in key_frame.columns:
        key_frame[column] = key_frame[column].astype(object).where(key_frame[column].notna(), "<NA>")
        key_frame[column] = key_frame[column].astype(str)
    tx["semantic_event_key"] = key_frame.agg("|".join, axis=1)
    duplicate_mask = tx["semantic_event_key"].duplicated(keep="first")
    tx = tx.loc[~duplicate_mask].copy()
    tx = tx.sort_values(["phase_id", "date_of_pasp", "unit_key", "semantic_event_key"], na_position="last")
    return tx.reset_index(drop=True), {
        "rows_input": int(len(transactions)),
        "rows_output": int(len(tx)),
        "duplicate_rows": int(duplicate_mask.sum()),
    }


def _inventory_by_phase(price_lists: pd.DataFrame) -> pd.DataFrame:
    if price_lists is None or price_lists.empty:
        return pd.DataFrame(columns=["phase_id", "published_inventory_units", "inventory_status"])
    prices = price_lists.copy()
    phase_values = prices["srpe_development_id"] if "srpe_development_id" in prices.columns else prices.get(
        "development_id", pd.Series("", index=prices.index)
    )
    prices["phase_id"] = phase_values.fillna("").astype(str)
    inventory_values = prices["total_residential_properties"] if "total_residential_properties" in prices.columns else pd.Series(pd.NA, index=prices.index)
    prices["published_inventory_units"] = pd.to_numeric(inventory_values, errors="coerce")
    prices = prices[prices["phase_id"].ne("") & prices["published_inventory_units"].notna()]
    if prices.empty:
        return pd.DataFrame(columns=["phase_id", "published_inventory_units", "inventory_status"])
    result = (
        prices.groupby("phase_id", as_index=False)["published_inventory_units"]
        .max()
        .assign(inventory_status="published_price_list")
    )
    return result


def _phase_month_end_state(phase: pd.DataFrame, period: pd.Timestamp) -> int:
    """Return units active at month-end using latest observed unit state."""
    end = period + pd.offsets.MonthEnd(1)
    eligible = phase[phase["date_of_pasp"].notna() & (phase["date_of_pasp"] <= end)].copy()
    if eligible.empty:
        return 0
    # A unit can retain an old open register row alongside a later version
    # carrying its termination.  Select the latest PASP contract for each unit,
    # then let any termination effective by month-end supersede open copies of
    # that same contract.  A later resale has a later PASP and becomes active
    # independently of the cancelled prior contract.
    latest_pasp = eligible.groupby("unit_key")["date_of_pasp"].transform("max")
    latest_contract = eligible[eligible["date_of_pasp"].eq(latest_pasp)].copy()
    terminated = (
        latest_contract["date_of_asp_termination"].le(end)
        .groupby(latest_contract["unit_key"])
        .any()
    )
    return int((~terminated).sum())


def _ownership_interval_endpoint(
    record: dict[str, Any],
    primary: str,
    fallback: str,
) -> pd.Timestamp:
    value = record.get(primary)
    if value is None or not str(value).strip():
        value = record.get(fallback)
    return pd.to_datetime(value, errors="coerce")


def _ownership_applies_to_period(
    ownership: dict[str, Any],
    events: pd.DataFrame,
    period: pd.Timestamp,
) -> bool:
    """Return whether one unambiguous strict interval covers this month."""
    if not ownership.get("ready"):
        return False
    start = ownership.get("effective_from")
    end = ownership.get("effective_to")
    if pd.isna(start) or pd.isna(end):
        return False
    if not events.empty:
        event_dates = pd.to_datetime(events["date_of_pasp"], errors="coerce")
        return bool(
            event_dates.notna().all()
            and event_dates.between(start, end, inclusive="both").all()
        )
    month_end = period + pd.offsets.MonthEnd(1)
    return bool(start <= period and month_end <= end)


def build_shkp_project_month_signals(
    transactions: pd.DataFrame,
    *,
    price_lists: pd.DataFrame | None = None,
    candidates: pd.DataFrame | None = None,
    audits: pd.DataFrame | None = None,
    ownership_registry: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build signal rows, month-status rows and phase coverage diagnostics."""
    tx, dedup_stats = deduplicate_shkp_transactions(transactions)
    if tx.empty:
        empty = pd.DataFrame()
        return empty, empty, empty
    inventory = _inventory_by_phase(price_lists if price_lists is not None else pd.DataFrame())
    candidate_map = pd.DataFrame(columns=["phase_id", "candidate_status", "candidate_tier"])
    if candidates is not None and not candidates.empty:
        candidate_map = candidates.copy()
        candidate_map["phase_id"] = candidate_map["srpe_development_id"].fillna("").astype(str)
        candidate_map = candidate_map.drop_duplicates("phase_id")
    audit_map: dict[str, str] = {}
    if audits is not None and not audits.empty and "srpe_dev_id" in audits.columns:
        audit_tmp = audits.copy()
        audit_tmp["phase_id"] = audit_tmp["srpe_dev_id"].fillna("").astype(str)
        audit_map = audit_tmp.groupby("phase_id")["parse_status"].apply(
            lambda values: "success" if values.astype(str).eq("success").all() else "parser_gap"
        ).to_dict()
    ownership_map: dict[str, dict[str, Any]] = {}
    if ownership_registry is not None and not ownership_registry.empty and "srpe_development_id" in ownership_registry.columns:
        ownership_tmp = ownership_registry.copy()
        ownership_tmp["phase_id"] = ownership_tmp["srpe_development_id"].fillna("").astype(str)
        for phase_id, group in ownership_tmp.groupby("phase_id", sort=False):
            records = group.to_dict("records")
            # The canonical registry should contain one phase row. Multiple
            # interval rows require an explicit interval-aware model; never
            # select one by row order.
            if len(records) != 1:
                ownership_map[str(phase_id)] = {
                    "ready": False,
                    "ownership_pct": None,
                    "effective_from": pd.NaT,
                    "effective_to": pd.NaT,
                }
                continue
            row = records[0]
            ready, ownership_pct = resolve_strict_ownership_attribution(row)
            ownership_map[str(phase_id)] = {
                "ready": ready,
                "ownership_pct": ownership_pct,
                "effective_from": _ownership_interval_endpoint(
                    row, "ownership_effective_from", "effective_from"
                ),
                "effective_to": _ownership_interval_endpoint(
                    row, "ownership_effective_to", "effective_to"
                ),
            }

    signal_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    valid_periods = pd.concat(
        [tx["event_period"], tx["cancel_period"]], ignore_index=True
    ).dropna()
    global_latest_period = valid_periods.max() if not valid_periods.empty else pd.NaT
    for phase_id, phase in tx.groupby("phase_id", sort=True):
        phase = phase.copy()
        phase_all = phase.copy()
        date_gap_events = phase_all[phase_all["date_gap_status"].ne("pasp_observed")]
        date_gap_count = int(len(date_gap_events))
        date_gap_status = (
            ";".join(sorted(date_gap_events["date_gap_status"].astype(str).unique()))
            if date_gap_count
            else "none"
        )
        phase = phase[phase["event_period"].notna()].copy()
        if phase.empty:
            # Keep a phase-level breadcrumb when every event lacks PASP.  It
            # is intentionally absent from the month grid and therefore cannot
            # enter the indicative sales model until a date is repaired.
            development_id = str(phase_all["development_id"].iloc[0])
            phase_candidate = candidate_map.loc[candidate_map["phase_id"].eq(str(phase_id))]
            candidate_status = phase_candidate["candidate_status"].iloc[0] if not phase_candidate.empty else "not_in_candidate_queue"
            candidate_tier = phase_candidate["candidate_tier"].iloc[0] if not phase_candidate.empty else None
            audit_status = audit_map.get(str(phase_id), "audit_not_found")
            ownership = ownership_map.get(
                str(phase_id),
                {
                    "ready": False,
                    "ownership_pct": None,
                    "effective_from": pd.NaT,
                    "effective_to": pd.NaT,
                },
            )
            ownership_ready = bool(ownership["ready"])
            coverage_rows.append(
                {
                    "phase_id": str(phase_id),
                    "project_id": f"shkp-srpe-{phase_id}",
                    "development_group_id": f"srpe-development-{development_id}",
                    "srpe_development_id": str(phase_id),
                    "candidate_status": candidate_status,
                    "candidate_tier": candidate_tier,
                    "audit_status": audit_status,
                    "ownership_review_status": "approved_interval" if ownership_ready else "blocked_interval_missing",
                    "raw_event_rows": int((transactions.get("srpe_development_id", pd.Series(dtype="string")).astype(str) == str(phase_id)).sum()) if transactions is not None and not transactions.empty and "srpe_development_id" in transactions.columns else None,
                    "dedup_event_rows": int(len(phase_all)),
                    "date_gap_event_rows": date_gap_count,
                    "date_gap_status": date_gap_status,
                    "signal_exclusion_reason": "pasp_missing_not_in_month_grid",
                    "coverage_start": None,
                    "coverage_end": None,
                    "covered_months": 0,
                    "observed_transaction_months": 0,
                    "observed_zero_months": 0,
                    "not_covered_months": 0,
                    "parser_gap": True,
                    "ownership_attribution_ready": ownership_ready,
                    "sales_attribution_status": "approved_phase_specific_interval" if ownership_ready else "blocked_phase_specific_interval",
                    "dedup_duplicate_rows_total": int(dedup_stats["duplicate_rows"]),
                }
            )
            continue
        development_id = str(phase["development_id"].iloc[0])
        development_group_id = f"srpe-development-{development_id}"
        phase = phase.sort_values(["date_of_pasp", "unit_key", "semantic_event_key"], na_position="last")
        phase_start = phase["event_period"].min()
        latest_event_period = phase["event_period"].max()
        latest_cancel_period = phase["cancel_period"].max()
        phase_end = latest_event_period if pd.isna(latest_cancel_period) else max(latest_event_period, latest_cancel_period)
        # Extend every phase to the latest observed month in the consolidated
        # register set.  Months after a phase's last observed register row are
        # explicitly ``not_covered`` rather than silently disappearing from
        # the cross-phase grid and looking like inventory was sold down.
        periods = pd.date_range(phase_start, global_latest_period, freq="MS")
        covered_periods = pd.date_range(phase_start, phase_end, freq="MS")
        event_by_period = phase.groupby("event_period")
        cancel_by_period = phase[phase["cancel_period"].notna()].groupby("cancel_period")
        first_unit_period = (
            phase.sort_values(["unit_key", "date_of_pasp", "semantic_event_key"])
            .drop_duplicates("unit_key", keep="first")
            .groupby("event_period")
            .size()
            .to_dict()
        )
        phase_candidate = candidate_map.loc[candidate_map["phase_id"].eq(str(phase_id))]
        candidate_status = phase_candidate["candidate_status"].iloc[0] if not phase_candidate.empty else "not_in_candidate_queue"
        candidate_tier = phase_candidate["candidate_tier"].iloc[0] if not phase_candidate.empty else None
        audit_status = audit_map.get(str(phase_id), "audit_not_found")
        ownership = ownership_map.get(
            str(phase_id),
            {
                "ready": False,
                "ownership_pct": None,
                "effective_from": pd.NaT,
                "effective_to": pd.NaT,
            },
        )
        phase_ownership_ready = bool(ownership["ready"])
        phase_ownership_review_status = (
            "approved_interval" if phase_ownership_ready else "blocked_interval_missing"
        )
        inv_row = inventory.loc[inventory["phase_id"].eq(str(phase_id))]
        inventory_units = float(inv_row["published_inventory_units"].iloc[0]) if not inv_row.empty else None
        inventory_status = "published_price_list" if inventory_units is not None else "not_available"
        for period in periods:
            covered = period <= phase_end
            events = event_by_period.get_group(period) if covered and period in event_by_period.groups else phase.iloc[0:0]
            cancellations = cancel_by_period.get_group(period) if covered and period in cancel_by_period.groups else phase.iloc[0:0]
            prices = pd.to_numeric(events["transaction_price_hkd"], errors="coerce")
            gross_units = int(len(events)) if covered else None
            gross_value = float(prices.sum(min_count=1)) if covered and prices.notna().any() else (0.0 if covered else None)
            active_units = _phase_month_end_state(phase, period) if covered else None
            ownership_ready = (
                _ownership_applies_to_period(ownership, events, period)
                if covered
                else False
            )
            ownership_review_status = (
                "approved_interval"
                if ownership_ready
                else "blocked_interval_missing_or_out_of_range"
            )
            month_status = (
                "observed_transactions" if gross_units else "observed_zero_transactions"
            ) if covered else "not_covered"
            status_rows.append(
                {
                    "phase_id": str(phase_id),
                    "project_id": f"shkp-srpe-{phase_id}",
                    "development_group_id": development_group_id,
                    "srpe_development_id": str(phase_id),
                    "period": period.strftime("%Y-%m-%d"),
                    "month_status": month_status,
                    "transaction_event_rows": gross_units,
                    "cancelled_event_rows": int(len(cancellations)) if covered else None,
                    "audit_status": audit_status,
                    "ownership_review_status": ownership_review_status,
                    "candidate_status": candidate_status,
                    "candidate_tier": candidate_tier,
                    "coverage_start": phase_start.strftime("%Y-%m-%d"),
                    "coverage_end": phase_end.strftime("%Y-%m-%d"),
                }
            )
            signal_rows.append(
                {
                    "phase_id": str(phase_id),
                    "project_id": f"shkp-srpe-{phase_id}",
                    "development_group_id": development_group_id,
                    "srpe_development_id": str(phase_id),
                    "development_id": str(phase["development_id"].iloc[0]),
                    "development_name": phase["development_name"].iloc[0] if "development_name" in phase else None,
                    "phase_name": phase["phase_name"].iloc[0] if "phase_name" in phase else None,
                    "period": period.strftime("%Y-%m-%d"),
                    "sales_units_gross": gross_units,
                    "sales_units_first_observed": int(first_unit_period.get(period, 0)) if covered else None,
                    "sales_value_gross_hkd": gross_value,
                    "cancelled_units": int(len(cancellations)) if covered else None,
                    # Cancellations are often registered months after PASP.
                    # Use a bounded same-month activity mix rather than
                    # pretending this is a cohort cancellation probability.
                    "cancellation_rate": float(len(cancellations) / (gross_units + len(cancellations)))
                    if covered and gross_units + len(cancellations)
                    else None,
                    "active_units_eom": active_units,
                    "cumulative_distinct_units_seen": int(phase.loc[phase["event_period"] <= period, "unit_key"].nunique()) if covered else None,
                    "published_inventory_units": inventory_units if covered else None,
                    "inventory_status": inventory_status if covered else "not_covered",
                    "sell_through_pct_eom": float(active_units / inventory_units * 100) if covered and active_units is not None and inventory_units else None,
                    "median_transaction_price_hkd": float(prices.median()) if covered and prices.notna().any() else None,
                    "weighted_avg_transaction_price_hkd": float(prices.mean()) if covered and prices.notna().any() else None,
                    "month_status": month_status,
                    "coverage_start": phase_start.strftime("%Y-%m-%d"),
                    "coverage_end": phase_end.strftime("%Y-%m-%d"),
                    "candidate_status": candidate_status,
                    "candidate_tier": candidate_tier,
                    "ownership_pct": ownership["ownership_pct"],
                    "ownership_attribution_ready": ownership_ready,
                    "ownership_review_status": ownership_review_status,
                    "sales_attribution_status": "approved_phase_specific_interval" if ownership_ready else "blocked_phase_specific_interval",
                    "sales_value_attributable_hkd": gross_value * float(ownership["ownership_pct"]) / 100.0 if ownership_ready and pd.notna(ownership["ownership_pct"]) else None,
                }
            )
        observed_periods = int((phase["event_period"].dropna().nunique()))
        coverage_rows.append(
            {
                "phase_id": str(phase_id),
                "project_id": f"shkp-srpe-{phase_id}",
                "development_group_id": development_group_id,
                "srpe_development_id": str(phase_id),
                "candidate_status": candidate_status,
                "candidate_tier": candidate_tier,
                "audit_status": audit_status,
                "ownership_review_status": phase_ownership_review_status,
                "raw_event_rows": int((transactions.get("srpe_development_id", pd.Series(dtype="string")).astype(str) == str(phase_id)).sum()) if transactions is not None and not transactions.empty and "srpe_development_id" in transactions.columns else None,
                "dedup_event_rows": int(len(phase)),
                "coverage_start": phase_start.strftime("%Y-%m-%d"),
                "coverage_end": phase_end.strftime("%Y-%m-%d"),
                "covered_months": int(len(covered_periods)),
                "observed_transaction_months": observed_periods,
                "observed_zero_months": int(len(covered_periods) - observed_periods),
                "not_covered_months": int(len(periods) - len(covered_periods)),
                "date_gap_event_rows": date_gap_count,
                "date_gap_status": date_gap_status,
                "signal_exclusion_reason": "pasp_missing_rows_quarantined" if date_gap_count else "none",
                "parser_gap": audit_status != "success",
                "ownership_attribution_ready": phase_ownership_ready,
                "sales_attribution_status": "approved_phase_specific_interval" if phase_ownership_ready else "blocked_phase_specific_interval",
                "dedup_duplicate_rows_total": int(dedup_stats["duplicate_rows"]),
            }
        )
    return pd.DataFrame(signal_rows), pd.DataFrame(status_rows), pd.DataFrame(coverage_rows)


def run_shkp_srpe_signal_contract() -> dict[str, Any]:
    """Consolidate all persisted SHKP scratch batches into signal datasets."""
    run_id = f"shkp-srpe-signals-{uuid.uuid4()}"
    raw_transactions = load_all_shkp_scratch_transactions()
    audits = load_all_shkp_scratch_audits()
    prices = load_all_shkp_scratch_price_lists()
    candidates = load_latest_normalized("shkp_srpe_phase_candidates")
    ownership_registry = load_latest_normalized("shkp_project_registry")
    events, stats = deduplicate_shkp_transactions(raw_transactions)
    signals, statuses, coverage = build_shkp_project_month_signals(
        raw_transactions,
        price_lists=prices,
        candidates=candidates,
        audits=audits,
        ownership_registry=ownership_registry,
    )
    lineage = {
        "lineage_type": "shkp_srpe_scratch_signal_contract",
        "source_datasets": [SCRATCH_TRANSACTION_DATASET, SCRATCH_AUDIT_DATASET, SCRATCH_PRICE_DATASET],
        "raw_transaction_rows": int(len(raw_transactions)),
        "dedup_transaction_rows": int(len(events)),
        "duplicate_rows_removed": int(stats["duplicate_rows"]),
        "candidate_rows": int(len(candidates)),
        "ownership_inference": False,
        "attributable_sales_policy": "blocked_phase_specific_interval",
        "status_semantics": ["observed_transactions", "observed_zero_transactions", "parser_gap", "not_covered", "date_gap_quarantined"],
        "date_gap_policy": "rows_without_PASP_are_quarantined and excluded from the strict month grid; ASP is not used as a silent PASP fallback",
    }
    date_gaps = events[events["date_gap_status"].ne("pasp_observed")].copy() if not events.empty else pd.DataFrame()
    if not date_gaps.empty:
        date_gaps["date_gap_dataset_status"] = "quarantined_pasp_missing"
        date_gaps["strict_signal_inclusion"] = False
        date_gaps["indicative_sales_model_inclusion"] = False
    stored = {
        EVENT_DATASET: save_normalized_dataset(EVENT_DATASET, events, run_id=run_id, lineage_metadata=lineage),
        SIGNAL_DATASET: save_normalized_dataset(SIGNAL_DATASET, signals, run_id=run_id, lineage_metadata=lineage),
        STATUS_DATASET: save_normalized_dataset(STATUS_DATASET, statuses, run_id=run_id, lineage_metadata=lineage),
        COVERAGE_DATASET: save_normalized_dataset(COVERAGE_DATASET, coverage, run_id=run_id, lineage_metadata=lineage),
        DATE_GAP_DATASET: save_normalized_dataset(DATE_GAP_DATASET, date_gaps, run_id=run_id, lineage_metadata=lineage),
    }
    return {
        "run_id": run_id,
        "raw_transaction_rows": int(len(raw_transactions)),
        "dedup_transaction_rows": int(len(events)),
        "duplicate_rows_removed": int(stats["duplicate_rows"]),
        "phase_rows": int(coverage["phase_id"].nunique()) if not coverage.empty else 0,
        "signal_rows": int(len(signals)),
        "status_rows": int(len(statuses)),
        "date_gap_rows": int(len(date_gaps)),
        "ownership_ready_rows": int(signals.get("ownership_attribution_ready", pd.Series(dtype=bool)).fillna(False).sum()),
        "normalized": stored,
    }


def build_shkp_indicative_project_month_signals(
    project_month_signals: pd.DataFrame,
    indicative_ownership: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the approximate ownership layer to phase-month gross signals.

    The output is deliberately separate from ``shkp_srpe_project_month_signals``.
    Numeric snapshots produce an indicative contract-sales estimate; SHKP-linked
    JVs without a percentage remain unquantified instead of being filled with
    100%.  Strict ownership fields are copied for comparison and never changed.
    """
    if project_month_signals is None or project_month_signals.empty:
        return pd.DataFrame()
    signals = project_month_signals.copy()
    ownership = indicative_ownership.copy() if indicative_ownership is not None else pd.DataFrame()
    key = "srpe_development_id"
    if key not in signals.columns:
        signals[key] = signals.get("phase_id", "").astype(str)
    if not ownership.empty and key in ownership.columns:
        ownership = ownership.drop_duplicates(key, keep="last")
        ownership_columns = [
            key,
            "indicative_owner_status",
            "indicative_ownership_pct",
            "indicative_ownership_pct_low",
            "indicative_ownership_pct_high",
            "indicative_numeric_consistency_status",
            "indicative_confidence",
            "indicative_evidence_basis",
            "indicative_sales_use_status",
            "strict_ownership_attribution_ready",
            "high_recall_status",
            "high_recall_identity_evidence_status",
            "high_recall_confidence",
            "high_recall_match_score",
            "high_recall_match_method",
            "high_recall_evidence_source_types",
            "high_recall_evidence_rows",
            "high_recall_evidence_urls_json",
            "high_recall_next_step",
            "identity_evidence_status",
        ]
        ownership = ownership[[column for column in ownership_columns if column in ownership.columns]]
        signals[key] = signals[key].fillna("").astype(str)
        ownership[key] = ownership[key].fillna("").astype(str)
        signals = signals.merge(ownership, on=key, how="left", suffixes=("", "_ownership"))
        if "indicative_ownership_pct_low" not in signals.columns:
            signals["indicative_ownership_pct_low"] = pd.NA
        if "indicative_ownership_pct_high" not in signals.columns:
            signals["indicative_ownership_pct_high"] = pd.NA
        if "indicative_numeric_consistency_status" not in signals.columns:
            signals["indicative_numeric_consistency_status"] = "not_observed"
    else:
        signals["indicative_owner_status"] = "not_observed"
        signals["indicative_ownership_pct"] = pd.NA
        signals["indicative_ownership_pct_low"] = pd.NA
        signals["indicative_ownership_pct_high"] = pd.NA
        signals["indicative_numeric_consistency_status"] = "not_observed"
        signals["indicative_confidence"] = "none"
        signals["indicative_evidence_basis"] = "no_indicative_roster"
        signals["indicative_sales_use_status"] = "not_covered"
        signals["strict_ownership_attribution_ready"] = False

    pct = pd.to_numeric(signals.get("indicative_ownership_pct"), errors="coerce")
    gross_value = pd.to_numeric(signals.get("sales_value_gross_hkd"), errors="coerce")
    gross_units = pd.to_numeric(signals.get("sales_units_gross"), errors="coerce")
    signals["indicative_sales_value_hkd"] = gross_value * pct / 100.0
    signals["indicative_sales_units"] = gross_units * pct / 100.0
    signals["indicative_attribution_status"] = "not_observed"
    numeric_mask = pct.notna() & signals["indicative_owner_status"].astype(str).str.startswith("likely_shkp")
    jv_mask = signals["indicative_owner_status"].astype(str).eq("likely_shkp_jv_unquantified")
    review_mask = signals["indicative_owner_status"].astype(str).isin({
        "possible_shkp_review",
        "likely_shkp_unquantified",
        "likely_shkp_high_recall_unquantified",
        "possible_shkp_high_recall",
    })
    signals.loc[numeric_mask, "indicative_attribution_status"] = "indicative_numeric_snapshot"
    signals.loc[jv_mask, "indicative_attribution_status"] = "indicative_jv_unquantified"
    signals.loc[review_mask, "indicative_attribution_status"] = "indicative_identity_only"
    signals["indicative_sales_caveat"] = signals["indicative_attribution_status"].map({
        "indicative_numeric_snapshot": "gross contract activity multiplied by point-in-time/grouped indicative stake; not legal attribution",
        "indicative_jv_unquantified": "SHKP-linked JV activity observed; no percentage applied",
        "indicative_identity_only": "phase identity evidence only; no sales amount estimated",
        "not_observed": "no indicative SHKP evidence",
    }).fillna("indicative layer only")
    return signals


def _normalise_historical_month_signals(
    historical_month_signals: pd.DataFrame,
) -> pd.DataFrame:
    """Adapt the sparse historical backfill to the current phase-month schema.

    The historical pilot emits only months present in a retained register.  We
    preserve that sparse grain instead of filling absent months with zero; a
    missing historical row is not evidence of no sale.
    """
    if historical_month_signals is None or historical_month_signals.empty:
        return pd.DataFrame()
    required = {
        "srpe_development_id",
        "development_id",
        "development_name",
        "phase_name",
        "period",
        "sales_units_gross",
        "sales_value_gross_hkd",
        "cancelled_units",
    }
    missing = sorted(required - set(historical_month_signals.columns))
    if missing:
        raise ValueError(
            "historical month signals missing required columns: " + ", ".join(missing)
        )
    frame = historical_month_signals.copy()
    frame["srpe_development_id"] = frame["srpe_development_id"].fillna("").astype(str).str.strip()
    frame = frame[frame["srpe_development_id"].ne("")].copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame = frame[frame["period"].notna()].copy()
    for column in (
        "sales_units_gross",
        "sales_value_gross_hkd",
        "cancelled_units",
        "cumulative_unique_active_units",
        "cumulative_net_sell_through_pct",
        "total_residential_properties",
        "median_transaction_price_hkd",
        "weighted_avg_transaction_price_hkd",
    ):
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["phase_id"] = frame["srpe_development_id"]
    frame["project_id"] = frame.get(
        "project_id",
        frame["phase_id"].map(lambda value: f"shkp-historical-srpe-{value}"),
    )
    frame["development_group_id"] = frame["development_id"].fillna("").astype(str).map(
        lambda value: f"srpe-development-{value}" if value else ""
    )
    frame["month_status"] = frame["sales_units_gross"].fillna(0).gt(0).map(
        {True: "observed_transactions", False: "observed_zero_transactions"}
    )
    frame["sales_units_first_observed"] = pd.NA
    frame["active_units_eom"] = frame["cumulative_unique_active_units"]
    frame["cumulative_distinct_units_seen"] = frame["cumulative_unique_active_units"]
    frame["published_inventory_units"] = frame["total_residential_properties"]
    frame["inventory_status"] = frame["published_inventory_units"].notna().map(
        {True: "published_price_list", False: "not_available"}
    )
    frame["sell_through_pct_eom"] = frame["cumulative_net_sell_through_pct"]
    denominator = frame["sales_units_gross"].fillna(0) + frame["cancelled_units"].fillna(0)
    frame["cancellation_rate"] = (frame["cancelled_units"] / denominator).where(denominator.gt(0))
    phase_ranges = frame.groupby("phase_id")["period"].agg(["min", "max"])
    frame["coverage_start"] = frame["phase_id"].map(phase_ranges["min"]).dt.strftime("%Y-%m-%d")
    frame["coverage_end"] = frame["phase_id"].map(phase_ranges["max"]).dt.strftime("%Y-%m-%d")
    frame["candidate_status"] = "historical_manifest_routing"
    frame["candidate_tier"] = "historical_backfill"
    frame["ownership_review_status"] = "blocked_historical_manifest_routing"
    frame["sales_attribution_status"] = frame.get(
        "sales_attribution_status", "blocked_phase_specific_interval"
    )
    frame["signal_scope"] = "historical_inactive_backfill"
    frame["coverage_semantics"] = "sparse_historical_register_months"
    return frame


def build_shkp_all_history_project_month_signals(
    current_signals: pd.DataFrame,
    historical_month_signals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Merge current candidate and historical routed phase-month signals.

    Current candidate rows take precedence for a duplicate phase-month key
    (the known overlap is phase 4285).  The historical layer remains routing-
    only; it does not open the strict ownership gate.
    """
    current = current_signals.copy() if current_signals is not None else pd.DataFrame()
    historical = _normalise_historical_month_signals(historical_month_signals)
    if current.empty and historical.empty:
        return pd.DataFrame(), pd.DataFrame()
    if not current.empty:
        current["srpe_development_id"] = current["srpe_development_id"].fillna("").astype(str)
        current["phase_id"] = current.get("phase_id", current["srpe_development_id"]).astype(str)
        current["signal_scope"] = "current_candidate_signal"
        current["coverage_semantics"] = current.get("month_status", "current_candidate_month_grid")
    if not historical.empty:
        historical["srpe_development_id"] = historical["srpe_development_id"].astype(str)
    all_columns = list(dict.fromkeys([*historical.columns.tolist(), *current.columns.tolist()]))
    for column in all_columns:
        if column not in historical.columns:
            historical[column] = pd.NA
        if column not in current.columns:
            current[column] = pd.NA
    # Drop columns that are entirely missing in both source layers before the
    # concat.  This avoids pandas' all-NA dtype warning without discarding any
    # field that has an observed value in either layer.
    concat_columns = [
        column
        for column in all_columns
        if not (historical[column].isna().all() and current[column].isna().all())
    ]
    # Do not pass an all-NA column from one side into ``concat`` when the
    # other side carries the observed values.  Pandas currently emits a
    # FutureWarning for that mixed-grain case (and its future dtype choice is
    # not stable); omitting the absent side lets concat perform the same union
    # without changing any observed value.
    historical_concat_columns = [
        column for column in concat_columns if not historical[column].isna().all()
    ]
    current_concat_columns = [
        column for column in concat_columns if not current[column].isna().all()
    ]
    combined = pd.concat(
        [historical[historical_concat_columns], current[current_concat_columns]],
        ignore_index=True,
        sort=False,
    )
    combined["_source_priority"] = combined["signal_scope"].map(
        {"historical_inactive_backfill": 0, "current_candidate_signal": 1}
    ).fillna(0)
    combined["period"] = pd.to_datetime(combined["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    combined = combined.sort_values(
        ["srpe_development_id", "period", "_source_priority"],
        na_position="last",
    )
    combined = combined.drop_duplicates(["srpe_development_id", "period"], keep="last")
    combined = combined.drop(columns=["_source_priority"]).sort_values(
        ["period", "srpe_development_id"], na_position="last"
    ).reset_index(drop=True)
    combined["period"] = combined["period"].dt.strftime("%Y-%m-%d")
    combined["all_history_strict_gate"] = False
    combined["all_history_caveat"] = (
        "Merged current candidate and sparse historical routed registers; duplicate phase-months prefer current "
        "candidate rows; absent historical months are not zero-filled; strict ownership remains blocked."
    )
    coverage = (
        combined.groupby("signal_scope", dropna=False)
        .agg(
            rows=("phase_id", "size"),
            phases=("srpe_development_id", "nunique"),
            period_min=("period", "min"),
            period_max=("period", "max"),
            gross_sales_value_hkd=("sales_value_gross_hkd", "sum"),
            gross_sales_units=("sales_units_gross", "sum"),
        )
        .reset_index()
    )
    coverage["duplicate_precedence"] = "current_candidate_signal_over_historical_inactive_backfill"
    coverage["strict_ownership_promotion"] = False
    coverage["research_only"] = True
    return combined, coverage


def run_shkp_all_history_signal_contract() -> dict[str, Any]:
    """Persist a merged current+historical SHKP project-month signal layer."""
    run_id = f"shkp-all-history-signals-{uuid.uuid4()}"
    current = load_latest_normalized(SIGNAL_DATASET)
    historical = load_latest_normalized(HISTORICAL_MONTHLY_SIGNAL_DATASET)
    ownership = load_latest_normalized(INDICATIVE_OWNERSHIP_DATASET)
    if current.empty:
        raise RuntimeError("current strict phase-month signals are missing; run run-shkp-srpe-signals first")
    if historical.empty:
        raise RuntimeError(
            "historical transaction backfill signals are missing; run run-shkp-historical-transaction-backfill first"
        )
    strict_all_history, coverage = build_shkp_all_history_project_month_signals(current, historical)
    indicative_all_history = build_shkp_indicative_project_month_signals(strict_all_history, ownership)
    indicative_all_history["signal_scope"] = strict_all_history["signal_scope"].values
    indicative_all_history["coverage_semantics"] = strict_all_history["coverage_semantics"].values
    lineage = {
        "lineage_type": "shkp_current_plus_historical_project_month_signals",
        "source_datasets": [SIGNAL_DATASET, HISTORICAL_MONTHLY_SIGNAL_DATASET, INDICATIVE_OWNERSHIP_DATASET],
        "historical_sparse_month_policy": "absent_months_not_zero_filled",
        "duplicate_phase_month_policy": "current_candidate_signal_precedes_historical_inactive_backfill",
        "strict_ownership_promotion": False,
        "indicative_only": True,
    }
    normalized = {
        ALL_HISTORY_SIGNAL_DATASET: save_normalized_dataset(
            ALL_HISTORY_SIGNAL_DATASET,
            strict_all_history,
            run_id=run_id,
            lineage_metadata={**lineage, "indicative_only": False},
        ),
        ALL_HISTORY_INDICATIVE_SIGNAL_DATASET: save_normalized_dataset(
            ALL_HISTORY_INDICATIVE_SIGNAL_DATASET,
            indicative_all_history,
            run_id=run_id,
            lineage_metadata=lineage,
        ),
        ALL_HISTORY_COVERAGE_DATASET: save_normalized_dataset(
            ALL_HISTORY_COVERAGE_DATASET,
            coverage,
            run_id=run_id,
            lineage_metadata=lineage,
        ),
    }
    return {
        "run_id": run_id,
        "current_rows": int(len(current)),
        "historical_rows": int(len(historical)),
        "merged_rows": int(len(strict_all_history)),
        "merged_phases": int(strict_all_history["srpe_development_id"].nunique()),
        "indicative_status_counts": indicative_all_history["indicative_attribution_status"].value_counts().to_dict(),
        "normalized": normalized,
        "strict_ownership_promotion": False,
    }


def run_shkp_indicative_signal_contract() -> dict[str, Any]:
    """Persist approximate SHKP phase-month sales alongside strict signals."""
    run_id = f"shkp-indicative-signals-{uuid.uuid4()}"
    signals = load_latest_normalized(SIGNAL_DATASET)
    ownership = load_latest_normalized(INDICATIVE_OWNERSHIP_DATASET)
    if signals.empty:
        raise RuntimeError("strict SHKP phase-month signals are missing; run run-shkp-srpe-signals first")
    indicative = build_shkp_indicative_project_month_signals(signals, ownership)
    lineage = {
        "lineage_type": "shkp_indicative_project_month_signals",
        "source_datasets": [SIGNAL_DATASET, INDICATIVE_OWNERSHIP_DATASET],
        "indicative_only": True,
        "strict_ownership_promotion": False,
        "numeric_semantics": "gross contract activity multiplied by indicative point-in-time/grouped stake",
    }
    normalized = save_normalized_dataset(
        INDICATIVE_SIGNAL_DATASET,
        indicative,
        run_id=run_id,
        lineage_metadata=lineage,
    )
    return {
        "run_id": run_id,
        "rows": int(len(indicative)),
        "phases": int(indicative["srpe_development_id"].nunique()) if not indicative.empty and "srpe_development_id" in indicative.columns else 0,
        "status_counts": indicative["indicative_attribution_status"].value_counts().to_dict(),
        "numeric_rows": int(indicative["indicative_sales_value_hkd"].notna().sum()),
        "normalized": normalized,
        "strict_ownership_promotion": False,
    }
