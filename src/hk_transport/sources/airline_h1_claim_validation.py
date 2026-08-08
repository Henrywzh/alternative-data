"""Pre-interim claim validation queue for the airline research pack."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

TREND_PATH = NORMALIZED_DIR / "airline_sector_trend_snapshot.csv"
EXPECTATION_PATH = NORMALIZED_DIR / "airline_expectation_bridge.csv"
PRE_H1_PATH = NORMALIZED_DIR / "airline_pre_h1_scenario_bridge.csv"
SCOPE_PATH = NORMALIZED_DIR / "airline_scope_reconciliation.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_h1_claim_validation_queue.csv"


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _latest_source_date(frames: list[pd.DataFrame | None]) -> str:
    dates: list[str] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in ("snapshot_date", "as_of_date", "source_as_of_date"):
            if column in frame.columns:
                dates.extend(str(value)[:10] for value in frame[column].dropna())
    valid = [date for date in dates if len(date) == 10 and date[4] == "-" and date[7] == "-"]
    return max(valid) if valid else "pending"


def _trend_row(trend: pd.DataFrame, company: str, metric: str) -> pd.Series:
    rows = trend[
        trend["company"].eq(company)
        & trend["scope_type"].eq("company")
        & trend["region"].eq("Total")
        & trend["metric"].eq(metric)
        & trend["current_period"].eq("2026H1")
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _claim(
    *, company: str, operating_entity: str, ticker: str, claim_id: str,
    claim_type: str, metric: str, driver: str, pre_value: float | None,
    pre_unit: str, pre_period: str, pre_source_path: str,
    pre_source_quality: str, scheduled_date: str, status: str,
    validation_rule: str, invalidation_rule: str, source_note: str,
    as_of: str, retrieved: str,
) -> dict[str, object]:
    return {
        "dataset_id": "airline_h1_claim_validation_queue", "as_of_date": as_of,
        "company": company, "operating_entity": operating_entity,
        "parent_group": "Juneyao Airlines" if company == "9 Air" else company,
        "ticker": ticker, "claim_id": claim_id, "claim_type": claim_type,
        "metric": metric, "forecast_assumption_driver": driver,
        "pre_h1_observation_value": pre_value, "pre_h1_observation_unit": pre_unit,
        "pre_h1_observation_period": pre_period, "pre_h1_source_path": pre_source_path,
        "pre_h1_source_quality": pre_source_quality,
        "formal_report_scheduled_date": scheduled_date,
        "formal_report_source": "CNINFO official issuer interim report / filing-watch result",
        "formal_actual_value": None, "formal_actual_unit": pre_unit,
        "formal_actual_period": "1H2026", "validation_status": status,
        "validation_result": None, "validation_rule": validation_rule,
        "invalidation_rule": invalidation_rule, "source_note": source_note,
        "retrieved_at": retrieved,
    }


def build_airline_h1_claim_validation_queue(
    *, trend: pd.DataFrame | None = None,
    expectations: pd.DataFrame | None = None,
    pre_h1: pd.DataFrame | None = None,
    scope: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the pre-event claim contract; formal actuals stay blank."""
    trend = trend if trend is not None else pd.read_csv(TREND_PATH)
    expectations = expectations if expectations is not None else pd.read_csv(EXPECTATION_PATH)
    pre_h1 = pre_h1 if pre_h1 is not None else pd.read_csv(PRE_H1_PATH)
    scope = scope if scope is not None else pd.read_csv(SCOPE_PATH)
    as_of = _latest_source_date([trend, expectations, pre_h1, scope])
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, object]] = []

    for company, ticker, operating_entity in (
        ("Spring Airlines", "601021.SH", "Spring Airlines"),
        ("Juneyao Airlines", "603885.SH", "Juneyao Airlines Mainline"),
    ):
        exp_match = expectations[expectations["company"].eq(company)]
        exp = exp_match.iloc[0] if not exp_match.empty else pd.Series(dtype=object)
        scheduled = str(exp.get("formal_report_scheduled_date", ""))
        operating_specs = (
            ("ask", "ask_growth_pct", "% YoY", "Formal issuer ASK growth should reconcile to the H1 monthly-release sum within report rounding", "Formal ASK growth materially exceeds the scenario or reverses the demand-capacity interpretation"),
            ("rpk", "rpk_growth_pct", "% YoY", "Formal issuer RPK growth should reconcile to the H1 monthly-release sum within report rounding", "Formal RPK growth falls below ASK growth and removes the observed demand advantage"),
            ("passenger_load_factor_pct", "passenger_load_factor_change_pp", "pp YoY", "Formal passenger LF change should be directionally consistent with the monthly weighted diagnostic", "Formal LF and yield both deteriorate versus the operating assumption"),
        )
        for metric, driver, unit, validation, invalidation in operating_specs:
            trend_row = _trend_row(trend, company, metric)
            rows.append(_claim(
                company=company, operating_entity=operating_entity, ticker=ticker,
                claim_id=f"{ticker}__h1_{metric}", claim_type="operating_metric",
                metric=metric, driver=driver, pre_value=_num(trend_row.get("yoy_change_pct")),
                pre_unit=unit, pre_period="2026H1 preliminary monthly releases",
                pre_source_path=str(TREND_PATH), pre_source_quality=str(trend_row.get("source_quality", "pending")),
                scheduled_date=scheduled, status="preliminary_observation_pending_formal_interim",
                validation_rule=validation, invalidation_rule=invalidation,
                source_note="Monthly issuer releases are preliminary/unaudited; formal interim report is the controlling test.",
                as_of=as_of, retrieved=retrieved,
            ))

        financial_specs = (
            ("rask_proxy", "rask_growth_pct_vs_fy2025", "latest_report_rask_native", "RMB/ASK", "Formal interim total revenue divided by ASK should be reconciled to the modelled RASK proxy", "Revenue/ASK or disclosed RASK moves outside the scenario and consensus bridge"),
            ("cask", "cask_growth_pct_vs_fy2025", "latest_report_cask_native", "RMB/ASK", "Formal interim operating cost divided by ASK should be reconciled to the modelled CASK proxy", "Cost/ASK rises while revenue/ASK does not compensate, invalidating the margin case"),
            ("attributable_profit", "consensus_profit_usd_mn", "latest_report_attributable_profit_native_mn", "RMB million", "Formal attributable profit must be compared with the scenario proxy and current FY2026 consensus", "Formal profit materially misses the scenario without a documented one-off explanation"),
        )
        for metric, driver, field, unit, validation, invalidation in financial_specs:
            value = _num(exp.get(field))
            rows.append(_claim(
                company=company, operating_entity=operating_entity, ticker=ticker,
                claim_id=f"{ticker}__h1_{metric}", claim_type="financial_metric",
                metric=metric, driver=driver, pre_value=value, pre_unit=unit,
                pre_period="FY2025 reported baseline" if value is not None else "pending",
                pre_source_path=str(EXPECTATION_PATH), pre_source_quality=str(exp.get("source_quality", "pending")),
                scheduled_date=scheduled, status="formal_interim_value_pending",
                validation_rule=validation, invalidation_rule=invalidation,
                source_note="Current financial field is FY2025 baseline context, not a 1H2026 actual; formal interim disclosure remains pending.",
                as_of=as_of, retrieved=retrieved,
            ))

        if company == "Juneyao Airlines":
            warning = pre_h1[(pre_h1["company"].eq(company)) & pre_h1["scenario"].eq("base")]
            warning = warning.iloc[0] if not warning.empty else pd.Series(dtype=object)
            rows.append(_claim(
                company=company, operating_entity=operating_entity, ticker=ticker,
                claim_id=f"{ticker}__h1_warning_reconciliation", claim_type="preliminary_warning",
                metric="attributable_profit", driver="consensus_profit_usd_mn",
                pre_value=_num(warning.get("warning_profit_mid_native_mn")),
                pre_unit="RMB million", pre_period="2026H1 preliminary warning midpoint",
                pre_source_path=str(PRE_H1_PATH), pre_source_quality=str(warning.get("warning_source_quality", "pending")),
                scheduled_date=scheduled, status="preliminary_warning_pending_formal_interim",
                validation_rule="Formal reported H1 profit should be compared with the preliminary RMB140m–210m warning range and the implied H2 consensus bridge",
                invalidation_rule="Formal H1 result falls outside the warning range without a disclosed scope/accounting explanation",
                source_note="Juneyao's warning is unaudited; the implied H2 amount is arithmetic and not a forecast.",
                as_of=as_of, retrieved=retrieved,
            ))

    nine_scope = scope[scope["metric"].isin({"passengers_9air_standalone", "fleet_9air_standalone"})]
    for metric, unit in (("passengers_9air_standalone", "passengers"), ("fleet_9air_standalone", "aircraft")):
        match = nine_scope[nine_scope["metric"].eq(metric)]
        source = match.iloc[0] if not match.empty else pd.Series(dtype=object)
        rows.append(_claim(
            company="9 Air", operating_entity="9 Air", ticker="603885.SH",
            claim_id=f"603885.SH__9air_{metric}", claim_type="subsidiary_scope", metric=metric,
            driver="9air_standalone_disclosure", pre_value=_num(source.get("reported_value")),
            pre_unit=unit, pre_period="FY2025 reported subsidiary metric", pre_source_path=str(SCOPE_PATH),
            pre_source_quality=str(source.get("source_quality", "pending")), scheduled_date="2026-08-31",
            status="standalone_1h2026_scope_pending",
            validation_rule="Formal Juneyao interim report should preserve or update the separate 9 Air operating disclosure",
            invalidation_rule="9 Air is omitted or scope is silently merged, preventing standalone operating read-through",
            source_note="9 Air is unlisted and has no direct consensus/P&L tape; missing standalone financials are not zero.",
            as_of=as_of, retrieved=retrieved,
        ))
    rows.append(_claim(
        company="9 Air", operating_entity="9 Air", ticker="603885.SH",
        claim_id="603885.SH__9air_standalone_pnl", claim_type="subsidiary_financial_disclosure",
        metric="standalone_profit_and_cost", driver="9air_standalone_disclosure", pre_value=None,
        pre_unit="RMB million", pre_period="not disclosed in covered FY2025 layer",
        pre_source_path=str(SCOPE_PATH), pre_source_quality="pending", scheduled_date="2026-08-31",
        status="standalone_pnl_pending",
        validation_rule="Search the formal interim report footnotes for standalone 9 Air revenue, fuel, operating cost, profit or sufficient segment detail",
        invalidation_rule="No standalone P&L detail is available; keep Juneyao group forecast as consolidated only",
        source_note="This is a disclosure test; missing standalone P&L is not zero revenue or cost.",
        as_of=as_of, retrieved=retrieved,
    ))
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_h1_claim_validation_queue() -> pd.DataFrame:
    return build_airline_h1_claim_validation_queue()
