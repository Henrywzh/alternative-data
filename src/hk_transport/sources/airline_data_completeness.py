"""Evidence-coverage contract for the airline long/short research pack."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_research_data_completeness.csv"
FRESHNESS_PATH = NORMALIZED_DIR / "airline_operating_freshness.csv"
SHORT_PROXY_PATH = NORMALIZED_DIR / "airline_short_side_proxies.csv"
SHORT_ELIGIBILITY_PATH = NORMALIZED_DIR / "airline_short_eligibility.csv"
HK_SHORT_POSITION_PATH = NORMALIZED_DIR / "airline_hk_short_positions.csv"
PROCESSED_KPI_PATH = Path(__file__).resolve().parents[3] / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"

OUTPUT_COLUMNS = [
    "dataset_id", "scope", "company", "ticker", "market", "domain",
    "required_for_thesis", "coverage_status", "coverage_count",
    "latest_observation_date", "source_dataset", "source_quality",
    "point_in_time_status", "source_url", "limitation", "as_of_date",
    "retrieved_at",
]


COMPANY_TICKERS = {
    "Cathay Pacific": ("0293.HK", "HK"),
    "Air China": ("601111.SH", "CN_A"),
    "China Southern Airlines": ("600029.SH", "CN_A"),
    "China Eastern Airlines": ("600115.SH", "CN_A"),
    "Spring Airlines": ("601021.SH", "CN_A"),
    "Juneyao Airlines": ("603885.SH", "CN_A"),
    "Hainan Airlines Holdings": ("600221.SH", "CN_A"),
}

AIRLINE_CODES = {
    "Air China": "601111",
    "China Southern Airlines": "600029",
    "China Eastern Airlines": "600115",
    "Spring Airlines": "601021",
    "Juneyao Airlines": "603885",
    "Hainan Airlines Holdings": "600221",
}


def _date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _latest(frame: pd.DataFrame, *columns: str) -> str | None:
    values = []
    for column in columns:
        if column in frame.columns:
            values.extend(pd.to_datetime(frame[column], errors="coerce").dropna().tolist())
    return max(values).strftime("%Y-%m-%d") if values else None


def _first(frame: pd.DataFrame, column: str) -> Any:
    if frame.empty or column not in frame.columns:
        return None
    values = frame[column].dropna()
    return values.iloc[0] if not values.empty else None


def _qualities(frame: pd.DataFrame, column: str = "source_quality") -> str | None:
    if frame.empty or column not in frame.columns:
        return None
    values = sorted({str(value) for value in frame[column].dropna() if str(value).strip()})
    return "+".join(values) if values else None


def _row(
    *,
    scope: str,
    company: str,
    ticker: str,
    market: str,
    domain: str,
    required: bool,
    status: str,
    count: int,
    latest_date: str | None,
    source_dataset: str,
    source_quality: str | None,
    pit_status: str,
    source_url: str | None,
    limitation: str,
    as_of_date: str | None,
    retrieved_at: str,
) -> dict[str, Any]:
    return {
        "dataset_id": "airline_research_data_completeness",
        "scope": scope,
        "company": company,
        "ticker": ticker,
        "market": market,
        "domain": domain,
        "required_for_thesis": required,
        "coverage_status": status,
        "coverage_count": count,
        "latest_observation_date": latest_date,
        "source_dataset": source_dataset,
        "source_quality": source_quality,
        "point_in_time_status": pit_status,
        "source_url": source_url,
        "limitation": limitation,
        "as_of_date": as_of_date,
        "retrieved_at": retrieved_at,
    }


def build_airline_data_completeness(
    *,
    bridge: pd.DataFrame | None = None,
    readiness: pd.DataFrame | None = None,
    guidance: pd.DataFrame | None = None,
    revisions: pd.DataFrame | None = None,
    news: pd.DataFrame | None = None,
    risk: pd.DataFrame | None = None,
    official_watch: pd.DataFrame | None = None,
    kpi: pd.DataFrame | None = None,
    drivers: pd.DataFrame | None = None,
    cathay_trend: pd.DataFrame | None = None,
    operating_freshness: pd.DataFrame | None = None,
    short_proxies: pd.DataFrame | None = None,
    short_eligibility: pd.DataFrame | None = None,
    hk_short_positions: pd.DataFrame | None = None,
    hedging: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build one auditable coverage row per thesis evidence domain."""
    def read(name: str, provided: pd.DataFrame | None) -> pd.DataFrame:
        if provided is not None:
            return provided
        path = NORMALIZED_DIR / name
        return pd.read_csv(path) if path.exists() else pd.DataFrame()

    bridge = read("airline_expectation_bridge.csv", bridge)
    readiness = read("airline_pair_readiness.csv", readiness)
    guidance = read("airline_guidance_coverage.csv", guidance)
    revisions = read("airline_revision_coverage.csv", revisions)
    news = read("airline_news_events.csv", news)
    risk = read("airline_market_risk_metrics.csv", risk)
    official_watch = read("airline_official_filing_watch.csv", official_watch)
    drivers = read("airline_earnings_driver_comparability.csv", drivers)
    cathay_trend = read("airline_cathay_sector_trend_snapshot.csv", cathay_trend)
    operating_freshness = read("airline_operating_freshness.csv", operating_freshness)
    short_proxies = read("airline_short_side_proxies.csv", short_proxies)
    short_eligibility = read("airline_short_eligibility.csv", short_eligibility)
    hk_short_positions = read("airline_hk_short_positions.csv", hk_short_positions)
    hedging = read("airline_hedging_disclosures.csv", hedging)
    public_report_evidence = read("airline_public_report_evidence.csv", None)
    if kpi is None:
        kpi = pd.read_parquet(PROCESSED_KPI_PATH) if PROCESSED_KPI_PATH.exists() else pd.DataFrame()
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []

    for company, (ticker, market) in COMPANY_TICKERS.items():
        bridge_row = bridge.loc[bridge["market_ticker"].eq(ticker)] if not bridge.empty else pd.DataFrame()
        if bridge_row.empty:
            bridge_row = bridge.loc[bridge["company"].eq(company)].head(1) if not bridge.empty else pd.DataFrame()
        b = bridge_row.iloc[0] if not bridge_row.empty else pd.Series(dtype=object)
        readiness_row = readiness.loc[readiness["company"].eq(company)].head(1) if not readiness.empty else pd.DataFrame()
        r = readiness_row.iloc[0] if not readiness_row.empty else pd.Series(dtype=object)
        guidance_row = guidance.loc[guidance["company"].eq(company)].head(1) if not guidance.empty else pd.DataFrame()
        g = guidance_row.iloc[0] if not guidance_row.empty else pd.Series(dtype=object)
        revision_row = revisions.loc[revisions["company"].eq(company)].head(1) if not revisions.empty else pd.DataFrame()
        rev = revision_row.iloc[0] if not revision_row.empty else pd.Series(dtype=object)

        company_kpi = kpi.loc[kpi["airline_code"].astype(str).eq(AIRLINE_CODES.get(company, ""))] if not kpi.empty else pd.DataFrame()
        kpi_source_dataset = "china_airlines_monthly.parquet"
        kpi_source_quality = _qualities(company_kpi)
        kpi_latest_date = _latest(company_kpi, "month")
        kpi_as_of_date = _latest(company_kpi, "announcement_date")
        if company == "Cathay Pacific" and company_kpi.empty and not cathay_trend.empty:
            company_kpi = cathay_trend.copy()
            kpi_source_dataset = "airline_cathay_sector_trend_snapshot.csv"
            kpi_source_quality = _qualities(company_kpi)
            kpi_latest_date = "2026-06-30"
            kpi_as_of_date = _latest(company_kpi, "retrieved_at")
        freshness_row = operating_freshness.loc[
            operating_freshness["company"].eq(company)
        ].sort_values("snapshot_date").iloc[-1] if (
            not operating_freshness.empty and "company" in operating_freshness.columns
            and not operating_freshness.loc[operating_freshness["company"].eq(company)].empty
        ) else pd.Series(dtype=object)
        kpi_month = str(kpi_latest_date)[:7] if kpi_latest_date else None
        kpi_latest_observation_date = (
            pd.Period(kpi_month, freq="M").end_time.strftime("%Y-%m-%d")
            if kpi_month else None
        )
        monthly_status = f"available_through_{kpi_month}" if kpi_month else "missing"
        monthly_pit_status = (
            "release_date_lineage_available"
            if company != "Cathay Pacific" and not company_kpi.empty
            else "monthly_issuer_release_snapshot"
            if company == "Cathay Pacific" and not company_kpi.empty
            else "not_available"
        )
        monthly_source_dataset = kpi_source_dataset
        monthly_source_url = _first(
            company_kpi.sort_values("announcement_date")
            if "announcement_date" in company_kpi.columns and not company_kpi.empty
            else company_kpi,
            "source_pdf_url",
        ) or _first(company_kpi, "source_path")
        monthly_limitation = (
            f"Monthly issuer KPI archive currently reaches {kpi_month}; July data is not yet available in this snapshot."
            if company != "Cathay Pacific"
            else "Cathay is represented by an H1 trend snapshot from issuer monthly releases, not the mainland release registry."
        )
        monthly_as_of_date = kpi_as_of_date
        if company != "Cathay Pacific" and not freshness_row.empty:
            freshness_status = str(freshness_row.get("target_release_status"))
            target_month = str(freshness_row.get("target_month"))
            freshness_snapshot = _date(freshness_row.get("snapshot_date"))
            monthly_source_dataset = f"{kpi_source_dataset} + airline_operating_freshness.csv"
            monthly_source_url = freshness_row.get("source_url") or monthly_source_url
            monthly_as_of_date = freshness_snapshot or monthly_as_of_date
            if freshness_status == "not_found_in_cninfo_window":
                monthly_pit_status = "release_date_lineage_available__target_month_not_published_at_snapshot"
                monthly_limitation = (
                    f"Monthly issuer KPI archive currently reaches {kpi_month}; the CNINFO operating-release query "
                    f"for {target_month} through {freshness_snapshot} found no matching bulletin. This is query-scoped "
                    "absence, not proof of permanent non-disclosure."
                )
            elif freshness_status == "announcement_found":
                monthly_pit_status = "release_date_lineage_available__target_month_announced"
                monthly_limitation = (
                    f"The {target_month} bulletin was found in CNINFO metadata, but it is not yet in the normalized "
                    "KPI archive; rerun the PDF parser before using its metrics."
                )
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="monthly_supply_demand", required=True,
            status=monthly_status,
            count=len(company_kpi), latest_date=kpi_latest_observation_date,
            source_dataset=monthly_source_dataset,
            source_quality=kpi_source_quality,
            pit_status=monthly_pit_status,
            source_url=monthly_source_url,
            limitation=monthly_limitation,
            as_of_date=monthly_as_of_date, retrieved_at=retrieved,
        ))

        company_drivers = drivers.loc[drivers["company"].eq(company)] if not drivers.empty else pd.DataFrame()
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="earnings_driver_actuals", required=True,
            status="available" if not company_drivers.empty else "missing",
            count=len(company_drivers), latest_date=_latest(company_drivers, "information_date"),
            source_dataset="airline_earnings_driver_comparability.csv",
            source_quality=_qualities(company_drivers),
            pit_status="issuer_reported_rows_with_derived_proxies" if not company_drivers.empty else "not_available",
            source_url=_first(company_drivers, "source_url"),
            limitation="Missing issuer metrics remain blank; derived RASK/CASK/fuel-share rows are labelled separately.",
            as_of_date=_latest(company_drivers, "information_date"), retrieved_at=retrieved,
        ))

        company_hedging = hedging.loc[hedging["company"].eq(company)] if not hedging.empty else pd.DataFrame()
        hedging_source_dataset = "airline_hedging_disclosures.csv"
        # Cathay's primary annual/interim driver layers already carry fuel
        # hedge loss/gain and fair-value rows, while the new report-scan layer
        # is intentionally scoped to the six mainland Cninfo PDFs.
        if company == "Cathay Pacific" and company_hedging.empty and not company_drivers.empty:
            company_hedging = company_drivers.loc[
                company_drivers["canonical_metric"].astype(str).str.contains("fuel_hedg", case=False)
            ].copy()
            hedging_source_dataset = (
                "airline_cathay_annual_driver_snapshot.csv + "
                "airline_cathay_interim_driver_snapshot.csv"
            )
            if not company_hedging.empty:
                company_hedging["information_date"] = company_hedging["information_date"]
                company_hedging["source_quality"] = company_hedging["source_quality"].fillna("primary_issuer")
                company_hedging["source_url"] = company_hedging["source_url"]
        explicit_hedging = company_hedging.loc[
            company_hedging["disclosure_type"].ne("scan_result")
        ] if not company_hedging.empty and "disclosure_type" in company_hedging.columns else company_hedging
        hedging_status = (
            "explicit_primary_disclosure"
            if not explicit_hedging.empty
            else "primary_report_scan_completed_no_numeric_anchor"
            if not company_hedging.empty
            else "missing"
        )
        hedging_quality = _qualities(company_hedging)
        hedging_limitation = (
            "Explicit fuel-hedging rows are retained by disclosure type; fair value, notional, policy statements "
            "and no-futures statements are not interchangeable. Missing rows are not imputed as zero."
            if not company_hedging.empty else
            "No cached primary hedging disclosure layer was available."
        )
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="fuel_hedging_disclosure", required=True,
            status=hedging_status, count=len(company_hedging),
            latest_date=_latest(company_hedging, "information_date"),
            source_dataset=hedging_source_dataset,
            source_quality=hedging_quality,
            pit_status=(
                "primary_report_announcement_date_available" if not company_hedging.empty
                else "not_available"
            ),
            source_url=_first(company_hedging, "source_url"),
            limitation=hedging_limitation,
            as_of_date=_latest(company_hedging, "information_date"), retrieved_at=retrieved,
        ))

        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="latest_official_actual", required=True,
            status="available" if bool(r.get("has_official_latest_financial_actual", False)) else "missing",
            count=int(company_drivers["statement_period"].nunique()) if not company_drivers.empty and "statement_period" in company_drivers else 0,
            latest_date=_date(b.get("latest_report_announcement_date")),
            source_dataset="airline_expectation_bridge.csv + primary report drivers",
            source_quality="primary_issuer" if not company_drivers.empty else None,
            pit_status="official_announcement_date_available" if pd.notna(b.get("latest_report_announcement_date")) else "period_only",
            source_url=_first(company_drivers.loc[company_drivers["statement_period"].eq(b.get("latest_financial_period"))] if not company_drivers.empty and "statement_period" in company_drivers else company_drivers, "source_url"),
            limitation="Latest mainland actual is FY2025 until formal 1H2026 reports are published; Cathay reaches 1H2026.",
            as_of_date=_date(b.get("latest_report_announcement_date")), retrieved_at=retrieved,
        ))

        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="guidance_warnings", required=True,
            status=str(g.get("guidance_coverage_status", "missing")),
            count=int(g.get("guidance_event_count", 0) or 0) + int(g.get("warning_event_count", 0) or 0),
            latest_date=_latest(guidance_row, "latest_guidance_date", "latest_warning_date", "latest_financial_result_date"),
            source_dataset="airline_guidance_coverage.csv",
            source_quality="+".join(filter(None, [str(g.get("latest_guidance_source_quality")) if pd.notna(g.get("latest_guidance_source_quality")) else None, str(g.get("latest_warning_source_quality")) if pd.notna(g.get("latest_warning_source_quality")) else None])) or None,
            pit_status="dated_event_rows" if not guidance_row.empty else "not_available",
            source_url=_first(guidance_row, "latest_guidance_source_url"),
            limitation="Guidance absence is explicit; warning-only coverage is not a structured demand forecast.",
            as_of_date=_latest(guidance_row, "latest_guidance_date", "latest_warning_date"), retrieved_at=retrieved,
        ))

        revenue_available = pd.notna(b.get("fy2026_revenue_avg_usd_mn"))
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="revenue_consensus", required=True,
            status=str(b.get("revenue_consensus_scope", "missing")) if revenue_available else "missing",
            count=1 if revenue_available else 0, latest_date=_date(b.get("revenue_consensus_latest_observation_date")),
            source_dataset=str(b.get("revenue_consensus_source_layer", "airline_expectation_bridge.csv")),
            source_quality=str(b.get("revenue_consensus_source_quality")) if pd.notna(b.get("revenue_consensus_source_quality")) else None,
            pit_status="forecast_observation_date_available" if revenue_available else "not_available",
            source_url=_first(bridge_row, "latest_sell_side_revenue_source_url"),
            limitation="Coverage may be direct Yahoo, same-company fallback or missing; it is not a complete low/high broker range for every name.",
            as_of_date=_date(b.get("revenue_consensus_as_of_date")), retrieved_at=retrieved,
        ))

        profit_available = pd.notna(b.get("fy2026_net_profit_avg_usd_mn"))
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="profit_eps_consensus", required=True,
            status="available" if profit_available else "missing",
            count=1 if profit_available else 0, latest_date=_date(b.get("profit_consensus_latest_observation_date")),
            source_dataset=str(b.get("profit_consensus_source_layer", "airline_expectation_bridge.csv")),
            source_quality="discovery_consensus" if profit_available else None,
            pit_status="forecast_observation_date_available" if profit_available else "not_available",
            source_url=_first(bridge_row, "hk_broker_latest_source_url") or None,
            limitation="Profit ranges can cross zero; P/E and profit-based valuation are unstable where flagged.",
            as_of_date=_date(b.get("profit_consensus_as_of_date")), retrieved_at=retrieved,
        ))

        estimate_count = int(rev.get("unified_estimate_revision_count", 0) or 0)
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="dated_revision_evidence", required=True,
            status="available" if estimate_count > 0 else "current_snapshot_only",
            count=estimate_count, latest_date=_date(rev.get("unified_latest_estimate_revision_date")),
            source_dataset="airline_revision_evidence.csv + airline_revision_coverage.csv",
            source_quality="sparse_public_revision_subset",
            pit_status="dated_public_subset" if estimate_count > 0 else "no_dated_revision",
            source_url=None,
            limitation="Public sell-side/Etnet/Cninfo coverage is incomplete and must not be called full consensus vintage history.",
            as_of_date=_date(rev.get("snapshot_date")), retrieved_at=retrieved,
        ))

        company_public_reports = (
            public_report_evidence.loc[public_report_evidence["company"].eq(company)]
            if not public_report_evidence.empty else pd.DataFrame()
        )
        dated_public = company_public_reports.loc[
            company_public_reports["report_date"].notna()
        ] if not company_public_reports.empty else pd.DataFrame()
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="public_report_evidence", required=company != "Cathay Pacific",
            status=(
                "available" if not company_public_reports.empty
                else "not_applicable" if company == "Cathay Pacific"
                else "missing"
            ),
            count=len(company_public_reports),
            latest_date=_latest(company_public_reports, "report_date", "snapshot_date"),
            source_dataset="airline_public_report_evidence.csv",
            source_quality=_qualities(company_public_reports),
            pit_status=(
                "dated_eps_profit_plus_page_snapshot_revenue"
                if not dated_public.empty else "page_snapshot_only"
                if not company_public_reports.empty else "not_available"
            ),
            source_url=_first(company_public_reports, "source_url"),
            limitation=(
                "10jqka structured evidence adds visible institution report dates for EPS/net profit; "
                "institution-level revenue rows lack row dates and remain page-snapshot-only, not a complete broker vintage."
            ),
            as_of_date=_latest(company_public_reports, "report_date", "snapshot_date"),
            retrieved_at=retrieved,
        ))

        rating_count = int(rev.get("cninfo_rating_event_count", 0) or 0)
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="rating_events", required=False,
            status="available" if rating_count > 0 else "missing",
            count=rating_count, latest_date=_date(rev.get("cninfo_rating_latest_event_date")),
            source_dataset="airline_cninfo_rating_events.csv",
            source_quality="cninfo_discovery" if rating_count else None,
            pit_status="queried_public_report_dates" if rating_count else "not_available",
            source_url="https://webapi.cninfo.com.cn/",
            limitation="Queried-date public rating events are partial, not a complete daily rating history.",
            as_of_date=_date(rev.get("cninfo_rating_latest_event_date")), retrieved_at=retrieved,
        ))

        company_news = news.loc[news["company"].eq(company)] if not news.empty else pd.DataFrame()
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="news_events", required=False,
            status="latest_public_window" if not company_news.empty else "missing",
            count=len(company_news), latest_date=_latest(company_news, "published_at"),
            source_dataset="airline_news_events.csv",
            source_quality=_qualities(company_news),
            pit_status="published_timestamp_available" if not company_news.empty else "not_available",
            source_url=_first(company_news, "news_url"),
            limitation="Keyword-based discovery window, not a complete archive or sentiment/alpha model.",
            as_of_date=_latest(company_news, "published_at"), retrieved_at=retrieved,
        ))

        company_risk = risk.loc[risk["company"].eq(company)] if not risk.empty else pd.DataFrame()
        company_short = (
            short_proxies.loc[
                short_proxies["company"].eq(company)
                & short_proxies["market"].eq(market)
            ]
            if not short_proxies.empty and {"company", "market"}.issubset(short_proxies.columns)
            else pd.DataFrame()
        )
        company_sfc_short = (
            hk_short_positions.loc[
                hk_short_positions["company"].eq(company)
                & hk_short_positions["market"].eq(market)
            ]
            if not hk_short_positions.empty
            and {"company", "market"}.issubset(hk_short_positions.columns)
            else pd.DataFrame()
        )
        risk_as_of_dates = [
            value for value in (
                _latest(company_risk, "snapshot_date"),
                _latest(company_short, "observation_date"),
                _latest(company_sfc_short, "reporting_date", "snapshot_date"),
            ) if value
        ]
        risk_as_of = max(risk_as_of_dates) if risk_as_of_dates else None
        risk_source_quality = "+".join(
            value for value in (
                _qualities(company_risk), _qualities(company_short), _qualities(company_sfc_short)
            ) if value
        ) or None
        risk_source_dataset = "airline_market_risk_metrics.csv"
        risk_pit_status = "historical_price_window_as_of_date" if not company_risk.empty else "not_available"
        if not company_short.empty:
            risk_source_dataset += " + airline_short_side_proxies.csv"
            risk_pit_status = (
                "historical_price_window_as_of_date+short_side_proxy_as_of_date"
                if not company_risk.empty else "short_side_proxy_as_of_date"
            )
        if not company_sfc_short.empty:
            risk_source_dataset += " + airline_hk_short_positions.csv"
            risk_pit_status += "+sfc_reportable_short_position_as_of_date"
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="market_risk", required=True,
            status="available" if not company_risk.empty else "missing",
            count=len(company_risk), latest_date=_latest(company_risk, "snapshot_date"),
            source_dataset=risk_source_dataset,
            source_quality=risk_source_quality,
            pit_status=risk_pit_status,
            source_url=(
                _first(company_sfc_short, "source_url")
                or _first(company_short, "source_url")
                or _first(company_risk, "source_url")
            ),
            limitation=(
                "Free beta/volatility/drawdown/liquidity proxies plus public short-side turnover/margin balance; "
                "SFC aggregate reportable short positions add HK crowding context; neither source establishes formal "
                "factor neutrality or borrow feasibility."
            ),
            as_of_date=risk_as_of, retrieved_at=retrieved,
        ))

        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="borrow_feasibility", required=True,
            status="missing_free_source", count=0, latest_date=None,
            source_dataset="airline_market_risk_metrics.csv + airline_short_side_proxies.csv",
            source_quality="short_side_proxy_only", pit_status=(
                "short_side_proxy_available_but_direct_borrow_unavailable"
                if not company_short.empty else "not_available"
            ),
            source_url=_first(company_short, "source_url"),
            limitation=(
                "Public short-side turnover/margin-balance proxies are available, but direct borrow availability, "
                "borrow cost, recall risk and broker-specific short-sale constraints are not available from free sources."
            ),
            as_of_date=_latest(company_short, "observation_date"), retrieved_at=retrieved,
        ))

        company_eligibility = short_eligibility.loc[
            short_eligibility["company"].eq(company)
            & short_eligibility["market"].eq(market)
        ] if not short_eligibility.empty and {"company", "market"}.issubset(short_eligibility.columns) else pd.DataFrame()
        rows.append(_row(
            scope="company", company=company, ticker=ticker, market=market,
            domain="short_eligibility", required=True,
            status="available" if not company_eligibility.empty else "missing",
            count=len(company_eligibility),
            latest_date=_latest(company_eligibility, "eligibility_effective_date", "snapshot_date"),
            source_dataset="airline_short_eligibility.csv",
            source_quality=_qualities(company_eligibility),
            pit_status=(
                "exchange_eligibility_evidence_not_borrow"
                if not company_eligibility.empty else "not_available"
            ),
            source_url=_first(company_eligibility, "source_url"),
            limitation=(
                "Exchange designated-list or margin-detail evidence only; it does not establish locatable borrow, "
                "borrow fee, recall risk or broker-specific execution availability."
            ),
            as_of_date=_latest(company_eligibility, "eligibility_effective_date", "snapshot_date"),
            retrieved_at=retrieved,
        ))

        if company == "Cathay Pacific":
            rows.append(_row(
                scope="company", company=company, ticker=ticker, market=market,
                domain="formal_1H2026_filing", required=True, status="disclosed",
                count=1, latest_date="2026-08-05", source_dataset="airline_cathay_interim_driver_snapshot.csv",
                source_quality="primary_issuer", pit_status="official_announcement_date_available",
                source_url="https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/announcements/en/2026_cx_interim_results_en.pdf",
                limitation="Cathay is covered by its issuer interim report; mainland watch is a separate CNINFO process.",
                as_of_date="2026-08-05", retrieved_at=retrieved,
            ))
        else:
            watch = official_watch.loc[official_watch["company"].eq(company)] if not official_watch.empty else pd.DataFrame()
            w = watch.sort_values("snapshot_date").iloc[-1] if not watch.empty else pd.Series(dtype=object)
            found = str(w.get("official_report_found", "False")).lower() == "true"
            rows.append(_row(
                scope="company", company=company, ticker=ticker, market=market,
                domain="formal_1H2026_filing", required=True,
                status="released" if found else "scheduled_no_official_match",
                count=1 if found else 0, latest_date=_date(w.get("official_disclosure_date")),
                source_dataset="airline_official_filing_watch.csv",
                source_quality="cninfo_official_query" if not watch.empty else None,
                pit_status="official_announcement_date_available" if found else "query_scoped_cninfo_no_match",
                source_url=_first(watch, "report_pdf_url") or "https://www.cninfo.com.cn/new/hisAnnouncement/query",
                limitation="A no-match result is scoped to the CNINFO query cutoff, not a permanent non-disclosure claim.",
                as_of_date=_date(w.get("snapshot_date")), retrieved_at=retrieved,
            ))

    energy = pd.read_parquet(NORMALIZED_DIR / "airline_energy_prices.parquet")
    fx = pd.read_parquet(NORMALIZED_DIR / "airline_fx_rates.parquet")
    surcharge = pd.read_parquet(NORMALIZED_DIR / "airline_fuel_surcharges.parquet")
    external = pd.read_csv(NORMALIZED_DIR / "airline_sector_external_outlook.csv")
    sector_rows = [
        ("energy_fx", len(energy) + len(fx), max(_latest(energy, "observation_date") or "", _latest(fx, "observation_date") or "") or None, "airline_energy_prices.parquet + airline_fx_rates.parquet", "eia_primary+ecb_primary", "observation_dates_and_release_dates_retained", "https://www.eia.gov/dnav/pet/", "Benchmarks and reference FX are not issuer purchase prices or hedge accounting.", max(_latest(energy, "observation_date") or "", _latest(fx, "observation_date") or "") or None),
        ("fuel_surcharge", len(surcharge), _latest(surcharge, "effective_from"), "airline_fuel_surcharges.parquet", _qualities(surcharge), "effective_date_available", _first(surcharge, "source_url"), "Regulated/issuer surcharge schedules are pass-through context, not realized fuel-cost recovery.", _latest(surcharge, "effective_from")),
        ("sector_external_outlook", len(external), _latest(external, "source_document_date"), "airline_sector_external_outlook.csv", _qualities(external), "dated_forecast_and_actual_vintages", _first(external, "source_url"), "IATA/CAAC forecasts, actuals and planned schedules are kept as separate statuses and metric definitions.", _latest(external, "source_document_date")),
    ]
    for domain, count, latest_date, source_dataset, quality, pit_status, url, limitation, as_of in sector_rows:
        rows.append(_row(
            scope="sector", company="Sector / shared driver", ticker="SECTOR", market="SECTOR",
            domain=domain, required=True, status="available" if count else "missing", count=count,
            latest_date=latest_date, source_dataset=source_dataset, source_quality=quality,
            pit_status=pit_status, source_url=url, limitation=limitation, as_of_date=as_of,
            retrieved_at=retrieved,
        ))
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_data_completeness() -> pd.DataFrame:
    result = build_airline_data_completeness()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
