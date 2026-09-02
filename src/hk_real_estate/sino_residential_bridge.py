"""Research-only Sino Land Hong Kong residential sales-to-revenue bridge.

The SRPE register is a contract-activity source.  It is not an accounting
revenue source, and this module never labels its output as reported revenue.
It joins the latest Sino transaction facts to Buildings Department occupation
permit evidence where a conservative address match is possible.  For phases
without a usable occupation-permit match, three explicitly estimated lag
scenarios (12/18/24 months) are applied to the observed contract cohorts.

Ownership is equally conservative: an explicit numeric snapshot is used when
available; otherwise the output keeps gross contract value and adds clearly
labelled 50/75/100% low/base/high attribution scenarios.  The latter is a
research assumption, not a legal JV conclusion.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import pandas as pd

from .storage import load_latest_normalized, save_normalized_dataset


PHASE_DATASET = "sino_land_hk_residential_bridge_phase"
SCHEDULE_DATASET = "sino_land_hk_residential_recognition_schedule"
COVERAGE_DATASET = "sino_land_hk_residential_bridge_coverage"

DEFAULT_STAKE_SCENARIOS = {"low": 50.0, "base": 75.0, "high": 100.0}
ESTIMATED_LAG_MONTHS = {"low": 12, "base": 18, "high": 24}

PHASE_COLUMNS = [
    "bridge_id",
    "srpe_development_id",
    "canonical_project_id",
    "project_label",
    "phase_name",
    "sales_period_start",
    "sales_period_end",
    "sales_month_rows",
    "contract_units_gross",
    "contract_sales_value_gross_hkd",
    "contract_sales_value_active_snapshot_hkd",
    "active_units_latest",
    "sales_observation_status",
    "stake_low_pct",
    "stake_base_pct",
    "stake_high_pct",
    "stake_status",
    "stake_source_dataset",
    "bd_occupation_match_status",
    "bd_occupation_observed_month",
    "bd_occupation_units",
    "bd_match_candidate_count",
    "bd_source_urls_json",
    "handover_lag_months_low",
    "handover_lag_months_base",
    "handover_lag_months_high",
    "handover_lag_source",
    "bridge_status",
    "model_use",
    "research_only",
    "source_urls_json",
    "caveat",
]

SCHEDULE_COLUMNS = [
    "bridge_id",
    "srpe_development_id",
    "canonical_project_id",
    "project_label",
    "phase_name",
    "sale_period",
    "contract_units_gross",
    "contract_sales_value_gross_hkd",
    "recognized_period_low",
    "recognized_period_base",
    "recognized_period_high",
    "attributable_contract_value_low_hkd",
    "attributable_contract_value_base_hkd",
    "attributable_contract_value_high_hkd",
    "recognition_lag_months_low",
    "recognition_lag_months_base",
    "recognition_lag_months_high",
    "lag_source",
    "attribution_status",
    "coverage_status",
    "model_use",
    "research_only",
    "caveat",
]

COVERAGE_COLUMNS = [
    "coverage_id",
    "bridge_id",
    "eligible_phase_count",
    "sales_observed_phase_count",
    "transaction_register_gap_phase_count",
    "bd_occupation_observed_phase_count",
    "bd_match_ambiguous_phase_count",
    "numeric_stake_phase_count",
    "estimated_stake_phase_count",
    "schedule_rows",
    "schedule_missing_recognition_period_rows",
    "schedule_negative_value_rows",
    "schedule_invalid_lag_order_rows",
    "data_quality_status",
    "model_use",
    "research_only",
    "source_lineage",
    "caveat",
]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    value = str(value).strip()
    return value or None


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else None


def _period(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_period("M").to_timestamp()


def _json_urls(values: Any) -> str | None:
    if values is None:
        return None
    if isinstance(values, pd.Series):
        values = values.tolist()
    urls = sorted(
        {
            str(value).strip()
            for value in values
            if _text(value) and str(value).strip().startswith(("http://", "https://"))
        }
    )
    return json.dumps(urls, ensure_ascii=False) if urls else None


def _address_tokens(value: Any) -> set[str]:
    """Keep distinctive address fragments for conservative BD matching."""
    text = _text(value)
    if not text:
        return set()
    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    stopwords = {
        "a",
        "and",
        "area",
        "avenue",
        "building",
        "development",
        "district",
        "hong",
        "island",
        "kong",
        "lane",
        "new",
        "no",
        "of",
        "park",
        "phase",
        "place",
        "road",
        "site",
        "street",
        "the",
        "territories",
    }
    return {token for token in normalized.split() if token not in stopwords and len(token) > 1}


def _address_key(value: Any) -> str:
    return "|".join(sorted(_address_tokens(value)))


def _address_number_tokens(value: Any) -> set[str]:
    """Return number-bearing address anchors, including one-digit anchors.

    ``_address_tokens`` intentionally drops one-character fragments because
    they are usually noise (for example the ``A`` in ``Avenue``).  For
    matching an occupation permit, however, a house number such as ``1`` or
    ``1A`` is often the most useful discriminator.  Keep these anchors
    separate so they can be used as a conservative filter without changing
    the general address-key semantics.
    """
    text = _text(value)
    if not text:
        return set()
    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return {
        token
        for token in normalized.split()
        if any(character.isdigit() for character in token)
    }


def _match_bd_occupation(
    address: Any,
    development_id: str,
    all_phase_addresses: dict[str, Any],
    bd_history: pd.DataFrame,
    first_sales_period: pd.Timestamp | None,
) -> dict[str, Any]:
    """Match one phase to OP rows without pretending address is ownership."""
    empty = {
        "status": "not_observed",
        "observed_month": None,
        "units": None,
        "candidate_count": 0,
        "source_urls": [],
    }
    if bd_history is None or bd_history.empty or not _text(address):
        return empty
    if "permit_stage" not in bd_history.columns or "site_address" not in bd_history.columns:
        return empty
    op = bd_history[
        bd_history["permit_stage"].astype(str).str.contains("occupation", case=False, na=False)
    ].copy()
    if op.empty:
        return empty
    source_tokens = _address_tokens(address)
    if len(source_tokens) < 2:
        return {**empty, "status": "address_tokens_insufficient"}
    candidates: list[tuple[int, float, str, int]] = []
    for index, row in op.iterrows():
        target_tokens = _address_tokens(row.get("site_address"))
        overlap = len(source_tokens & target_tokens)
        if overlap < 2:
            continue
        coverage = overlap / max(1, min(len(source_tokens), len(target_tokens)))
        candidates.append((overlap, coverage, _address_key(row.get("site_address")), index))
    if not candidates:
        return {**empty, "status": "no_address_match"}
    # Prefer a shared number-bearing anchor when the source address has one.
    # Without this filter, ``24A Kadoorie Avenue, Ho Man Tin`` can incorrectly
    # match ``13 Ho Man Tin Street`` solely because the street/district words
    # overlap.  If no candidate shares that anchor, keep the match unresolved rather
    # than silently treating a street/district-only overlap as an occupation
    # permit for this phase.
    source_number_tokens = _address_number_tokens(address)
    if source_number_tokens:
        number_candidates = [
            item
            for item in candidates
            if source_number_tokens
            & _address_number_tokens(op.loc[item[3], "site_address"])
        ]
        if not number_candidates:
            return {
                **empty,
                "status": "address_number_anchor_missing",
                "candidate_count": len(candidates),
            }
        candidates = number_candidates
    max_overlap = max(item[0] for item in candidates)
    max_coverage = max(item[1] for item in candidates if item[0] == max_overlap)
    best = [item for item in candidates if item[0] == max_overlap and item[1] == max_coverage]
    best_keys = {item[2] for item in best if item[2]}
    # If the same BD address is shared by multiple Sino phases, no phase can
    # safely claim the permit without an additional lot/ownership crosswalk.
    selected_bd_tokens = set()
    for item in best:
        selected_bd_tokens.update(_address_tokens(op.loc[item[3], "site_address"]))
    shared_phase_ids = {
        str(phase_id)
        for phase_id, phase_address in all_phase_addresses.items()
        if len(selected_bd_tokens & _address_tokens(phase_address)) >= 2
    }
    ambiguous_shared = len(shared_phase_ids) > 1
    if len(best_keys) != 1 or ambiguous_shared:
        return {
            **empty,
            "status": "ambiguous_address_match",
            "candidate_count": len(best),
            "source_urls": [op.loc[item[3], "source_url"] for item in best if "source_url" in op.columns],
        }
    selected = op.loc[[item[3] for item in best]].copy()
    selected["observation_month"] = pd.to_datetime(selected.get("observation_month"), errors="coerce")
    selected = selected[selected["observation_month"].notna()].copy()
    if first_sales_period is not None:
        after = selected[selected["observation_month"] >= first_sales_period]
        if not after.empty:
            selected = after
    if selected.empty:
        return {**empty, "status": "address_match_before_sales_only", "candidate_count": len(best)}
    observed_month = selected["observation_month"].min().to_period("M").to_timestamp()
    same_month = selected[selected["observation_month"].dt.to_period("M").dt.to_timestamp().eq(observed_month)]
    units = pd.to_numeric(same_month.get("domestic_units_count"), errors="coerce").sum(min_count=1)
    return {
        "status": "observed_bd_occupation_match",
        "observed_month": observed_month,
        "units": float(units) if pd.notna(units) else None,
        "candidate_count": len(best),
        "source_urls": same_month.get("source_url", pd.Series(dtype=object)).tolist(),
    }


def _stake_scenarios(identity: pd.DataFrame, development_id: str) -> dict[str, Any]:
    rows = (
        identity.loc[identity.get("srpe_development_id", pd.Series(index=identity.index, dtype="string")).astype(str).eq(str(development_id))]
        if identity is not None and not identity.empty
        else pd.DataFrame()
    )
    numeric = pd.to_numeric(rows.get("ownership_pct_snapshot", pd.Series(dtype=float)), errors="coerce").dropna()
    if not numeric.empty:
        value = float(numeric.iloc[-1])
        source_series = rows.get("source_dataset")
        source = _text(source_series.iloc[-1]) if source_series is not None and not source_series.empty else None
        return {
            "low": value,
            "base": value,
            "high": value,
            "status": "observed_snapshot_not_interval",
            "source": source,
        }
    return {
        "low": DEFAULT_STAKE_SCENARIOS["low"],
        "base": DEFAULT_STAKE_SCENARIOS["base"],
        "high": DEFAULT_STAKE_SCENARIOS["high"],
        "status": "unknown_assumed_50_75_100_scenario",
        "source": None,
    }


def build_sino_residential_bridge(
    signals: pd.DataFrame,
    events: pd.DataFrame,
    queue: pd.DataFrame,
    *,
    identity: pd.DataFrame | None = None,
    bd_history: pd.DataFrame | None = None,
    bridge_id: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Build phase summary, cohort recognition schedule and coverage tables."""
    bridge_id = bridge_id or f"sino-residential-bridge-{uuid.uuid4()}"
    signal_frame = signals.copy() if signals is not None else pd.DataFrame()
    event_frame = events.copy() if events is not None else pd.DataFrame()
    queue_frame = queue.copy() if queue is not None else pd.DataFrame()
    eligible = (
        queue_frame.loc[queue_frame.get("queue_status", pd.Series(index=queue_frame.index, dtype="string")).eq("eligible_for_recent_srpe_queue")]
        .drop_duplicates(subset=["srpe_development_id"], keep="last")
        if not queue_frame.empty
        else pd.DataFrame()
    )
    if signal_frame.empty and event_frame.empty and eligible.empty:
        empty = pd.DataFrame(columns=PHASE_COLUMNS)
        return {"phase": empty, "schedule": pd.DataFrame(columns=SCHEDULE_COLUMNS), "coverage": pd.DataFrame(columns=COVERAGE_COLUMNS)}

    if not signal_frame.empty:
        signal_frame["period"] = signal_frame["period"].map(_period)
        signal_frame = signal_frame[signal_frame["period"].notna()].copy()
    if not event_frame.empty:
        event_frame["pasp_period"] = event_frame["date_of_pasp"].map(_period)
        event_frame = event_frame[event_frame["pasp_period"].notna()].copy()
        event_frame["transaction_price_hkd"] = pd.to_numeric(event_frame["transaction_price_hkd"], errors="coerce").fillna(0)
        if "is_cancelled" in event_frame.columns:
            # Normalized inputs normally contain booleans, but a CSV/Parquet
            # round-trip can yield strings.  Do not let ``bool("False")``
            # silently turn every event into a cancellation.
            cancelled = event_frame["is_cancelled"]
            event_frame["is_cancelled"] = (
                cancelled.astype("string").str.strip().str.casefold().isin({"1", "true", "t", "yes", "y"})
            )
        else:
            event_frame["is_cancelled"] = False

    all_phase_addresses: dict[str, Any] = {}
    for development_id, group in event_frame.groupby("development_id") if not event_frame.empty else []:
        address = group.get("development_address", pd.Series(dtype=object)).dropna()
        if not address.empty:
            all_phase_addresses[str(development_id)] = address.iloc[0]
    for _, row in eligible.iterrows():
        all_phase_addresses.setdefault(str(row.get("srpe_development_id")), None)

    phase_rows: list[dict[str, Any]] = []
    schedule_rows: list[dict[str, Any]] = []
    for _, queue_row in eligible.iterrows():
        development_id = _text(queue_row.get("srpe_development_id"))
        if not development_id:
            continue
        project_id = _text(queue_row.get("canonical_project_id"))
        project_label = _text(queue_row.get("project_label"))
        phase_name = _text(queue_row.get("srpe_phase_name"))
        sig = signal_frame[signal_frame["development_id"].astype(str).eq(development_id)].copy() if not signal_frame.empty else pd.DataFrame()
        ev = event_frame[event_frame["development_id"].astype(str).eq(development_id)].copy() if not event_frame.empty else pd.DataFrame()
        first_period = sig["period"].min() if not sig.empty else (ev["pasp_period"].min() if not ev.empty else None)
        last_period = sig["period"].max() if not sig.empty else (ev["pasp_period"].max() if not ev.empty else None)
        gross_value = float(pd.to_numeric(sig.get("sales_value_gross_hkd", pd.Series(dtype=float)), errors="coerce").sum()) if not sig.empty else 0.0
        gross_units = int(pd.to_numeric(sig.get("sales_units_gross", pd.Series(dtype=float)), errors="coerce").sum()) if not sig.empty else 0
        active_value = float(ev.loc[~ev["is_cancelled"], "transaction_price_hkd"].sum()) if not ev.empty else 0.0
        active_latest = _number(sig.sort_values("period").iloc[-1].get("cumulative_unique_active_units")) if not sig.empty else None
        if phase_name is None and not sig.empty:
            phase_name = _text(sig.iloc[-1].get("phase_name"))
        sales_status = "observed_transactions" if not sig.empty else "no_transaction_register_observed"
        stake = _stake_scenarios(identity if identity is not None else pd.DataFrame(), development_id)
        bd = _match_bd_occupation(
            all_phase_addresses.get(development_id),
            development_id,
            all_phase_addresses,
            bd_history if bd_history is not None else pd.DataFrame(),
            first_period,
        )
        observed_month = bd.get("observed_month")
        if observed_month is not None and first_period is not None:
            observed_lag = max(0, (observed_month.year - first_period.year) * 12 + observed_month.month - first_period.month)
            lag_low, lag_base, lag_high = max(0, observed_lag - 3), observed_lag, observed_lag + 3
            lag_source = "observed_bd_occupation_permit_plus_minus_3m"
        else:
            lag_low, lag_base, lag_high = ESTIMATED_LAG_MONTHS["low"], ESTIMATED_LAG_MONTHS["base"], ESTIMATED_LAG_MONTHS["high"]
            lag_source = "estimated_generic_12_18_24m_lag"
        if sales_status == "no_transaction_register_observed":
            bridge_status = "no_sales_observed_handover_unknown"
        elif bd["status"] == "observed_bd_occupation_match":
            bridge_status = "sales_observed_handover_observed"
        elif bd["status"] == "ambiguous_address_match":
            bridge_status = "sales_observed_handover_match_ambiguous"
        else:
            bridge_status = "sales_observed_handover_estimated"
        sources = []
        if not sig.empty and "source_url" in sig.columns:
            sources.extend(sig["source_url"].tolist())
        if not ev.empty and "source_url" in ev.columns:
            sources.extend(ev["source_url"].tolist())
        phase_rows.append(
            {
                "bridge_id": bridge_id,
                "srpe_development_id": development_id,
                "canonical_project_id": project_id,
                "project_label": project_label,
                "phase_name": phase_name,
                "sales_period_start": first_period.strftime("%Y-%m-%d") if first_period is not None else None,
                "sales_period_end": last_period.strftime("%Y-%m-%d") if last_period is not None else None,
                "sales_month_rows": int(len(sig)),
                "contract_units_gross": gross_units,
                "contract_sales_value_gross_hkd": gross_value,
                "contract_sales_value_active_snapshot_hkd": active_value,
                "active_units_latest": active_latest,
                "sales_observation_status": sales_status,
                "stake_low_pct": stake["low"],
                "stake_base_pct": stake["base"],
                "stake_high_pct": stake["high"],
                "stake_status": stake["status"],
                "stake_source_dataset": stake["source"],
                "bd_occupation_match_status": bd["status"],
                "bd_occupation_observed_month": observed_month.strftime("%Y-%m-%d") if observed_month is not None else None,
                "bd_occupation_units": bd.get("units"),
                "bd_match_candidate_count": bd.get("candidate_count", 0),
                "bd_source_urls_json": _json_urls(bd.get("source_urls")),
                "handover_lag_months_low": lag_low,
                "handover_lag_months_base": lag_base,
                "handover_lag_months_high": lag_high,
                "handover_lag_source": lag_source,
                "bridge_status": bridge_status,
                "model_use": "research_only_contract_to_revenue_timing_scenario",
                "research_only": True,
                "source_urls_json": _json_urls(sources),
                "caveat": "Contract activity is not reported revenue; handover timing and unknown stake are scenario assumptions unless explicitly observed.",
            }
        )
        if sig.empty:
            continue
        for _, signal_row in sig.iterrows():
            sale_period = signal_row["period"]
            sale_value_number = _number(signal_row.get("sales_value_gross_hkd"))
            sale_units_number = _number(signal_row.get("sales_units_gross"))
            sale_value = sale_value_number if sale_value_number is not None else 0.0
            sale_units = int(sale_units_number) if sale_units_number is not None else 0
            recognized_period = sale_period + pd.DateOffset(months=int(lag_base))
            # One row per sale cohort carries all three lag and stake
            # scenarios; this keeps downstream aggregation deterministic.
            schedule_rows.append(
                {
                    "bridge_id": bridge_id,
                    "srpe_development_id": development_id,
                    "canonical_project_id": project_id,
                    "project_label": project_label,
                    "phase_name": phase_name,
                    "sale_period": sale_period.strftime("%Y-%m-%d"),
                    "contract_units_gross": sale_units,
                    "contract_sales_value_gross_hkd": sale_value,
                    "recognized_period_low": (sale_period + pd.DateOffset(months=int(lag_low))).strftime("%Y-%m-%d"),
                    "recognized_period_base": recognized_period.strftime("%Y-%m-%d"),
                    "recognized_period_high": (sale_period + pd.DateOffset(months=int(lag_high))).strftime("%Y-%m-%d"),
                    "attributable_contract_value_low_hkd": sale_value * stake["low"] / 100.0,
                    "attributable_contract_value_base_hkd": sale_value * stake["base"] / 100.0,
                    "attributable_contract_value_high_hkd": sale_value * stake["high"] / 100.0,
                    "recognition_lag_months_low": lag_low,
                    "recognition_lag_months_base": lag_base,
                    "recognition_lag_months_high": lag_high,
                    "lag_source": lag_source,
                    "attribution_status": stake["status"],
                    "coverage_status": bridge_status,
                    "model_use": "research_only_contract_cohort_schedule",
                    "research_only": True,
                    "caveat": "This is a timing proxy, not an accounting recognition entry; use reported revenue for validation.",
                }
            )

    phase = pd.DataFrame(phase_rows, columns=PHASE_COLUMNS)
    schedule = pd.DataFrame(schedule_rows, columns=SCHEDULE_COLUMNS)
    recognition_period_columns = [
        "recognized_period_low",
        "recognized_period_base",
        "recognized_period_high",
    ]
    schedule_missing_recognition_period_rows = (
        int(schedule[recognition_period_columns].isna().any(axis=1).sum())
        if not schedule.empty
        else 0
    )
    value_columns = [
        "contract_sales_value_gross_hkd",
        "attributable_contract_value_low_hkd",
        "attributable_contract_value_base_hkd",
        "attributable_contract_value_high_hkd",
    ]
    schedule_negative_value_rows = (
        int(
            schedule[value_columns]
            .apply(pd.to_numeric, errors="coerce")
            .lt(0)
            .any(axis=1)
            .sum()
        )
        if not schedule.empty
        else 0
    )
    schedule_invalid_lag_order_rows = (
        int(
            (
                (schedule["recognition_lag_months_low"] > schedule["recognition_lag_months_base"])
                | (schedule["recognition_lag_months_base"] > schedule["recognition_lag_months_high"])
            ).sum()
        )
        if not schedule.empty
        else 0
    )
    schedule_quality_ok = not any(
        (
            schedule_missing_recognition_period_rows,
            schedule_negative_value_rows,
            schedule_invalid_lag_order_rows,
        )
    )
    coverage = pd.DataFrame(
        [
            {
                "coverage_id": f"{bridge_id}:coverage",
                "bridge_id": bridge_id,
                "eligible_phase_count": int(len(phase)),
                "sales_observed_phase_count": int(phase["sales_observation_status"].eq("observed_transactions").sum()) if not phase.empty else 0,
                "transaction_register_gap_phase_count": int(phase["sales_observation_status"].eq("no_transaction_register_observed").sum()) if not phase.empty else 0,
                "bd_occupation_observed_phase_count": int(phase["bd_occupation_match_status"].eq("observed_bd_occupation_match").sum()) if not phase.empty else 0,
                "bd_match_ambiguous_phase_count": int(phase["bd_occupation_match_status"].eq("ambiguous_address_match").sum()) if not phase.empty else 0,
                "numeric_stake_phase_count": int(phase["stake_status"].eq("observed_snapshot_not_interval").sum()) if not phase.empty else 0,
                "estimated_stake_phase_count": int(phase["stake_status"].eq("unknown_assumed_50_75_100_scenario").sum()) if not phase.empty else 0,
                "schedule_rows": int(len(schedule)),
                "schedule_missing_recognition_period_rows": schedule_missing_recognition_period_rows,
                "schedule_negative_value_rows": schedule_negative_value_rows,
                "schedule_invalid_lag_order_rows": schedule_invalid_lag_order_rows,
                "data_quality_status": "pass_with_explicit_unknowns" if schedule_quality_ok else "warning_schedule_quality_checks_failed",
                "model_use": "research_only_contract_to_revenue_timing_scenario",
                "research_only": True,
                "source_lineage": json.dumps(
                    [
                        "sino_land_srpe_monthly_signals",
                        "sino_land_srpe_transaction_events",
                        "sino_land_sales_ingestion_queue",
                        "sino_land_project_identity_evidence",
                        "bd_project_lifecycle_history",
                    ],
                    ensure_ascii=False,
                ),
                "caveat": "No phase-level reported revenue allocation is claimed; unknown ownership, BD matching and missing registers remain explicit.",
            }
        ],
        columns=COVERAGE_COLUMNS,
    )
    return {"phase": phase, "schedule": schedule, "coverage": coverage}


def run_sino_residential_bridge(*, persist: bool = True) -> dict[str, Any]:
    """Build the latest Sino residential bridge from normalized inputs."""
    run_id = f"sino-residential-bridge-{uuid.uuid4()}"
    signals = load_latest_normalized("sino_land_srpe_monthly_signals")
    events = load_latest_normalized("sino_land_srpe_transaction_events")
    queue = load_latest_normalized("sino_land_sales_ingestion_queue")
    identity = load_latest_normalized("sino_land_project_identity_evidence")
    bd_history = load_latest_normalized("bd_project_lifecycle_history")
    layers = build_sino_residential_bridge(
        signals,
        events,
        queue,
        identity=identity,
        bd_history=bd_history,
        bridge_id=run_id,
    )
    normalized: dict[str, Any] = {}
    if persist:
        for dataset, frame in (
            (PHASE_DATASET, layers["phase"]),
            (SCHEDULE_DATASET, layers["schedule"]),
            (COVERAGE_DATASET, layers["coverage"]),
        ):
            frame.attrs["lineage_metadata"] = {
                "lineage_type": "sino_land_hk_residential_contract_to_revenue_timing_bridge",
                "run_id": run_id,
                "research_only": True,
                "source_datasets": [
                    "sino_land_srpe_monthly_signals",
                    "sino_land_srpe_transaction_events",
                    "sino_land_sales_ingestion_queue",
                    "sino_land_project_identity_evidence",
                    "bd_project_lifecycle_history",
                ],
            }
            normalized[dataset] = save_normalized_dataset(dataset, frame, run_id=run_id, lineage_metadata=frame.attrs["lineage_metadata"])
    return {
        "run_id": run_id,
        "phase_rows": int(len(layers["phase"])),
        "schedule_rows": int(len(layers["schedule"])),
        "coverage_rows": int(len(layers["coverage"])),
        "normalized": normalized,
        "research_only": True,
    }
