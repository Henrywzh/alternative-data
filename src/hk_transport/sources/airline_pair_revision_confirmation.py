"""Point-in-time consensus-revision confirmation for provisional pair directions."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

WORKING_PATH = NORMALIZED_DIR / "airline_pair_thesis_working_set.csv"
TRADE_PATH = NORMALIZED_DIR / "airline_pair_trade_thesis_scenarios.csv"
REVISION_PATH = NORMALIZED_DIR / "airline_revision_evidence.csv"
PULSE_PATH = NORMALIZED_DIR / "airline_consensus_revision_pulse.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_pair_revision_confirmation.csv"


def _row(frame: pd.DataFrame, **criteria: object) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=object)
    mask = pd.Series(True, index=frame.index)
    for column, value in criteria.items():
        if column not in frame.columns:
            return pd.Series(dtype=object)
        mask &= frame[column].eq(value)
    rows = frame.loc[mask]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _signal_summary(revisions: pd.DataFrame, company: str, *, fiscal_year: float = 2026.0) -> dict[str, object]:
    rows = revisions[
        revisions.company.eq(company)
        & revisions.evidence_type.eq("vendor_revision_signal")
        & pd.to_numeric(revisions.fiscal_year, errors="coerce").eq(fiscal_year)
    ].copy()
    if rows.empty:
        return {
            "date": None, "window": "missing", "up": 0, "down": 0, "flat": 0,
            "no_signal": 0, "direction": "missing", "source_quality": "missing",
        }
    rows["evidence_date_parsed"] = pd.to_datetime(rows["evidence_date"], errors="coerce")
    latest_date = rows.evidence_date_parsed.max()
    same_date = rows[rows.evidence_date_parsed.eq(latest_date)]
    # Prefer the shorter signal window for the event-risk decision, while
    # retaining the 30d result if a 7d signal is unavailable.
    window = "7d" if same_date.signal_window.astype(str).eq("7d").any() else "30d"
    same_window = same_date[same_date.signal_window.astype(str).eq(window)]
    counts = same_window.direction.astype(str).value_counts().to_dict()
    up, down = int(counts.get("up", 0)), int(counts.get("down", 0))
    flat, no_signal = int(counts.get("flat", 0)), int(counts.get("no_signal", 0))
    if up > down and down == 0:
        direction = "up"
    elif down > up and up == 0:
        direction = "down"
    elif up == down == 0 and no_signal > 0:
        direction = "no_signal"
    else:
        direction = "mixed"
    return {
        "date": latest_date.date().isoformat() if pd.notna(latest_date) else None,
        "window": window, "up": up, "down": down, "flat": flat,
        "no_signal": no_signal, "direction": direction,
        "source_quality": ";".join(sorted(set(same_window.source_quality.dropna().astype(str)))) or "missing",
    }


def _numeric_pulse_summary(pulse: pd.DataFrame, company: str) -> dict[str, object]:
    rows = pulse[
        pulse.company.eq(company)
        & pd.to_numeric(pulse.fiscal_year, errors="coerce").eq(2026.0)
        & pulse.estimate_metric.astype(str).eq("eps")
    ].copy()
    if rows.empty:
        return {"date": None, "direction": "missing", "change_pct": None}
    rows["event_date_parsed"] = pd.to_datetime(rows["event_date"], errors="coerce")
    row = rows.sort_values("event_date_parsed").iloc[-1]
    change = pd.to_numeric(row.get("median_change_pct"), errors="coerce")
    return {
        "date": row["event_date_parsed"].date().isoformat() if pd.notna(row["event_date_parsed"]) else None,
        "direction": "up" if pd.notna(change) and change > 0 else "down" if pd.notna(change) and change < 0 else "flat_or_missing",
        "change_pct": float(change) if pd.notna(change) else None,
    }


def build_airline_pair_revision_confirmation(
    *,
    working: pd.DataFrame | None = None,
    trade: pd.DataFrame | None = None,
    revisions: pd.DataFrame | None = None,
    pulse: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    working = working if working is not None else pd.read_csv(WORKING_PATH)
    trade = trade if trade is not None else pd.read_csv(TRADE_PATH)
    revisions = revisions if revisions is not None else pd.read_csv(REVISION_PATH)
    pulse = pulse if pulse is not None else pd.read_csv(PULSE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for _, pair in working.iterrows():
        pair_id = str(pair["pair_id"])
        t = _row(trade, pair_id=pair_id, scenario="base")
        if t.empty:
            continue
        long_company, short_company = str(t["long_leg"]), str(t["short_leg"])
        long_signal = _signal_summary(revisions, long_company)
        short_signal = _signal_summary(revisions, short_company)
        long_numeric = _numeric_pulse_summary(pulse, long_company)
        short_numeric = _numeric_pulse_summary(pulse, short_company)
        if long_signal["direction"] == "up" and short_signal["direction"] == "down":
            confirmation = "supports_model_direction"
        elif long_signal["direction"] == "down" and short_signal["direction"] == "up":
            confirmation = "contradicts_model_direction"
        elif long_signal["direction"] == "missing" or short_signal["direction"] == "missing":
            confirmation = "not_confirmed_missing_leg_signal"
        elif "no_signal" in {long_signal["direction"], short_signal["direction"]}:
            confirmation = "not_confirmed_no_signal"
        else:
            confirmation = "mixed_or_indeterminate"
        rows.append(
            {
                "dataset_id": "airline_pair_revision_confirmation",
                "pair_id": pair_id,
                "selection_bucket": pair["selection_bucket"],
                "model_long_leg": long_company,
                "model_short_leg": short_company,
                "long_latest_signal_date": long_signal["date"],
                "long_latest_signal_window": long_signal["window"],
                "long_latest_signal_direction": long_signal["direction"],
                "long_signal_up_count": long_signal["up"],
                "long_signal_down_count": long_signal["down"],
                "short_latest_signal_date": short_signal["date"],
                "short_latest_signal_window": short_signal["window"],
                "short_latest_signal_direction": short_signal["direction"],
                "short_signal_up_count": short_signal["up"],
                "short_signal_down_count": short_signal["down"],
                "revision_confirmation_status": confirmation,
                "long_latest_numeric_pulse_date": long_numeric["date"],
                "long_latest_numeric_pulse_direction": long_numeric["direction"],
                "long_latest_numeric_pulse_change_pct": long_numeric["change_pct"],
                "short_latest_numeric_pulse_date": short_numeric["date"],
                "short_latest_numeric_pulse_direction": short_numeric["direction"],
                "short_latest_numeric_pulse_change_pct": short_numeric["change_pct"],
                "point_in_time_status": "latest_vendor_signal_as_of_2026_08_07;numeric_revision_pulse_is_older_and_not_substituted",
                "source_quality": "yfinance_vendor_short_horizon_signal_plus_dated_revision_pulse",
                "source_paths": f"{REVISION_PATH};{PULSE_PATH};{TRADE_PATH}",
                "source_note": "Vendor EPS revision signals have no broker identity or exact update timestamp and are not equivalent to a dated broker-vintage estimate revision.",
                "retrieved_at": retrieved,
            }
        )
    return pd.DataFrame(rows)


def fetch_airline_pair_revision_confirmation() -> pd.DataFrame:
    result = build_airline_pair_revision_confirmation()
    result.to_csv(OUTPUT_PATH, index=False)
    return result
