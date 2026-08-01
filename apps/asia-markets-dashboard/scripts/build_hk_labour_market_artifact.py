"""Build the local Hong Kong labour-market and talent-policy dashboard artifact.

The labour data layer already owns the official ingestion and audit trail.  This
builder is intentionally read-only: it consumes the latest audited local marts
and normalized C&SD/Immigration Department snapshots, so a dashboard build does
not wait on an external network request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hk_labour_market.marts import load_latest_dataset


PUBLIC_SOURCES: dict[str, dict[str, Any]] = {
    "censtatd_labour_force": {
        "id": "censtatd_labour_force",
        "label": "C&SD Labour Force, Employment, Unemployment & Underemployment",
        "href": "https://www.censtatd.gov.hk/api/get.php?id=210-06101&lang=en&full_series=1",
        "path": "sources/censtatd_labour_force.sql",
        "query": {
            "engine": "official C&SD API",
            "url": "https://www.censtatd.gov.hk/api/get.php?id=210-06101&lang=en&full_series=1",
            "language": "English",
            "description": "Monthly rolling-three-month labour-force, employment, unemployment and underemployment observations; annual estimates are retained separately.",
        },
    },
    "censtatd_labour_demand": {
        "id": "censtatd_labour_demand",
        "label": "C&SD Labour Demand by Industry",
        "href": "https://www.censtatd.gov.hk/api/get.php?id=215-16001&lang=en&full_series=1",
        "path": "sources/censtatd_labour_demand.sql",
        "query": {
            "engine": "official C&SD API",
            "url": "https://www.censtatd.gov.hk/api/get.php?id=215-16001&lang=en&full_series=1",
            "language": "English",
            "description": "Quarterly establishments, persons engaged, vacancies and vacancy rates by industry section; civil-service vacancies are excluded by the source definition.",
        },
    },
    "censtatd_wage_payroll": {
        "id": "censtatd_wage_payroll",
        "label": "C&SD Wage and Payroll Indices",
        "href": "https://www.censtatd.gov.hk/en/web_table.html?id=220-19001",
        "path": "sources/censtatd_wage_payroll.sql",
        "query": {
            "engine": "official C&SD API",
            "url": "https://www.censtatd.gov.hk/en/web_table.html?id=220-19001",
            "language": "English",
            "description": "Nominal/real wage and payroll indices by industry, with the C&SD-published year-on-year series preserved in the mart.",
        },
    },
    "censtatd_earnings": {
        "id": "censtatd_earnings",
        "label": "C&SD Median Employment Earnings",
        "href": "https://www.censtatd.gov.hk/api/get.php?id=210-06316&lang=en&full_series=1",
        "path": "sources/censtatd_earnings.sql",
        "query": {
            "engine": "official C&SD API",
            "url": "https://www.censtatd.gov.hk/api/get.php?id=210-06316&lang=en&full_series=1",
            "language": "English",
            "description": "Monthly rolling-three-month and annual median monthly employment earnings by industry; occupation history is retained in the same data layer.",
        },
    },
    "talent_policy_open_data": {
        "id": "talent_policy_open_data",
        "label": "Labour Department and Immigration Department Talent-policy Open Data",
        "href": "https://www.immd.gov.hk/eng/opendata.html",
        "path": "sources/talent_policy_open_data.sql",
        "query": {
            "engine": "official Labour Department XML and Immigration Department annual CSV open data",
            "url": "https://www.immd.gov.hk/eng/opendata.html",
            "language": "English / official CSV",
            "description": "Annual applications received and approved; QMAS quota-allotted successful selection cases are used as the approval-equivalent display measure. These are policy-flow measures, not a count of people who ultimately arrived, remained employed or entered the labour force.",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _records_json_safe(frame: pd.DataFrame, columns: list[str] | None = None) -> list[dict[str, Any]]:
    selected = frame.copy() if columns is None else frame.loc[:, [c for c in columns if c in frame.columns]].copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _with_dates(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["date"] = pd.to_datetime(result["period_end"], errors="coerce")
    result = result[result["date"].notna()].copy()
    # Month-granularity strings are deliberate: the portable renderer shows
    # the year for these values, avoiding ambiguous Jan/Feb ticks across years.
    result["month"] = result["date"].dt.strftime("%Y-%m")
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    return result


def _latest_date(frame: pd.DataFrame) -> pd.Timestamp:
    dates = pd.to_datetime(frame["period_end"], errors="coerce").dropna()
    if dates.empty:
        raise ValueError("A labour dashboard input has no valid observation dates")
    return dates.max()


def _latest_rows(frame: pd.DataFrame) -> pd.DataFrame:
    latest = _latest_date(frame)
    dates = pd.to_datetime(frame["period_end"], errors="coerce")
    return frame.loc[dates.eq(latest)].copy()


def _value(
    frame: pd.DataFrame,
    *,
    metric_code: str | None = None,
    metric_name: str | None = None,
    sex: str | None = None,
    metric_label: str | None = None,
) -> float | None:
    field = "metric_code" if metric_code is not None else "metric_name"
    key = metric_code if metric_code is not None else metric_name
    if key is None or field not in frame.columns:
        return None
    rows = frame[frame[field].eq(key)].copy()
    if sex is not None and "sex" in rows:
        rows = rows[rows["sex"].eq(sex)]
    if metric_label is not None and "metric_label" in rows:
        rows = rows[rows["metric_label"].eq(metric_label)]
    if rows.empty:
        return None
    value = pd.to_numeric(rows.iloc[-1].get("value"), errors="coerce")
    return None if pd.isna(value) else float(value)


def _percent_points_to_ratio(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else round(float(parsed) / 100, 6)


def _short_industry(value: Any) -> str:
    text = str(value)
    return text.split(":", 1)[1].strip() if ":" in text else text


def _compact_industry(value: Any) -> str:
    text = _short_industry(value)
    return {
        "Transportation, storage, postal and courier services": "Transport, storage & courier",
        "Accommodation and food services": "Accommodation & food",
        "Information and communications": "Information & communications",
        "Professional, scientific and technical services": "Professional/scientific/technical",
        "Professional and business services": "Professional & business services",
        "Administrative and support services": "Administrative & support services",
        "Human health and social work services": "Health & social work",
        "Arts, entertainment and recreation": "Arts, entertainment & recreation",
        "Import/export, wholesale and retail trades": "Import/export, wholesale & retail",
        "Social and personal services": "Social & personal services",
        "Construction sites (manual workers only)": "Construction sites",
        "Transportation, storage, postal and courier services, information and communications": "Transport, storage & ICT",
        "Retail, accommodation and food services": "Retail, accommodation & food",
        "Public administration, social and personal services": "Public admin, social & personal",
        "Real estate and professional and business services": "Real estate & professional/business",
        "Financing, insurance, real estate, professional and business services": "Finance, insurance, real estate & business",
        "Import/export trade and wholesale": "Import/export & wholesale",
        "Financing and insurance": "Finance & insurance",
    }.get(text, text)


VACANCY_HISTORY_SERIES = {
    "Total": "Total",
    "P - S: Social and personal services": "Social",
    "Q: Human health and social work services": "Health",
    "G: Import/export, wholesale and retail trades": "Trade",
    "M & N: Professional and business services": "Prof & biz",
    "K: Financing and insurance": "Finance",
}

EARNINGS_HISTORY_INDUSTRIES = {
    "Total",
    "Retail",
    "Accommodation and food services",
    "Manufacturing",
    "Construction",
    "Financing and insurance",
    "Transportation, storage, postal and courier services, information and communications",
}

OCCUPATION_HISTORY_SERIES = {
    "Total",
    "Managers",
    "Professionals",
    "Associate professionals",
    "Services and sales workers",
    "Elementary occupations",
}

EARNINGS_HISTORY_LABELS = {
    "Total": "Total",
    "Retail": "Retail",
    "Accommodation and food services": "F&B",
    "Manufacturing": "Mfg",
    "Construction": "Const",
    "Financing and insurance": "Fin.",
    "Transportation, storage, postal and courier services, information and communications": "Trans.",
}

OCCUPATION_HISTORY_LABELS = {
    "Total": "Total",
    "Managers": "Mgrs",
    "Professionals": "Prof.",
    "Associate professionals": "Assoc. prof",
    "Services and sales workers": "Sales",
    "Elementary occupations": "Elementary",
}


def _top_level_industry_mask(frame: pd.DataFrame) -> pd.Series:
    # The C&SD table contains both top-level sections and nested divisions such
    # as G45-46 and G47. Keep the section rows for a stable comparison chart.
    return frame["industry"].astype("string").str.match(r"^[A-Z](?: & [A-Z]| - [A-Z])?:", na=False)


def _policy_short_name(value: str) -> str:
    names = {
        "General Employment Policy": "GEP",
        "Admission Scheme for Mainland Talents and Professionals": "ASMTP",
        "Technology Talent Admission Scheme": "TechTAS",
        "Top Talent Pass Scheme": "TTPS",
        "Immigration Arrangements for Non-local Graduates": "IANG",
        "Admission Scheme for the Second Generation of Chinese Hong Kong Permanent Residents": "ASSG",
        "Quality Migrant Admission Scheme": "QMAS",
        "Enhanced Supplementary Labour Scheme": "ESLS",
    }
    return names.get(value, value)


def _add_qmas_approval_equivalent(policy_scheme: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add QMAS quota cases to the approval display without changing raw source labels.

    ImmD's QMAS open-data CSV calls the successful selection count ``quota
    allotted`` rather than ``applications approved``.  The annual review/facts
    surfaces use the latter label for the same successful selection outcome.
    Keep the raw ``quota_allotted`` row and add a display-only approval row with
    explicit basis metadata.  If ImmD ever publishes an actual QMAS approved
    column, prefer that source row and do not double-count the quota.
    """
    display = policy_scheme.copy()
    approved = display[display["metric_name"].eq("applications_approved")].copy()
    approved["approval_basis"] = "applications_approved"

    qmas_actual_approved = approved[approved["scheme"].eq("Quality Migrant Admission Scheme")]
    qmas_quota = display[
        display["scheme"].eq("Quality Migrant Admission Scheme")
        & display["metric_name"].eq("quota_allotted")
        & display["dimension_label"].isin(["All applicants", "Total"])
    ].copy()
    if qmas_actual_approved.empty and not qmas_quota.empty:
        qmas_quota["metric_name"] = "applications_approved"
        qmas_quota["metric_label"] = (
            "Quota allotted under Quality Migrant Admission Scheme "
            "(approval-equivalent successful selection cases)"
        )
        qmas_quota["approval_basis"] = "quota_allotted"
        display = pd.concat([display, qmas_quota], ignore_index=True)
        approved = pd.concat([approved, qmas_quota], ignore_index=True)

    approved = approved.sort_values(["date", "series"]).reset_index(drop=True)
    return display, approved


def build_artifact(
    raw_labour_force: pd.DataFrame | None = None,
    raw_sector: pd.DataFrame | None = None,
    raw_income: pd.DataFrame | None = None,
    raw_policy: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()

    labour_force = raw_labour_force
    if labour_force is None:
        labour_force, _ = load_latest_dataset("labour_force_monthly")
    sector = raw_sector if raw_sector is not None else pd.read_parquet(ROOT / "data/normalized/hk_labour_market/marts/labour_sector_panel.parquet")
    income = raw_income if raw_income is not None else pd.read_parquet(ROOT / "data/normalized/hk_labour_market/marts/labour_income_panel.parquet")
    policy = raw_policy if raw_policy is not None else pd.read_parquet(ROOT / "data/normalized/hk_labour_market/marts/labour_policy_supply_panel.parquet")

    generated_at = now.isoformat().replace("+00:00", "Z")
    labour_force = labour_force.copy()
    labour_force["period_end"] = pd.to_datetime(labour_force["period_end"], errors="coerce")
    labour_force = labour_force[labour_force["period_end"].notna()].copy()
    labour_force_total = labour_force[labour_force["sex"].eq("Total")].copy()
    lf_latest = _latest_rows(labour_force_total)
    lf_latest_date = _latest_date(labour_force_total)
    lf_kpi = {
        "labour_force_thousands": _value(lf_latest, metric_code="LF", metric_label="No. ('000)"),
        "employed_thousands": _value(lf_latest, metric_code="EM", metric_label="No. ('000)"),
        "unemployed_thousands": _value(lf_latest, metric_code="UE", metric_label="No. ('000)"),
        "unemployment_rate": _percent_points_to_ratio(_value(lf_latest, metric_code="UR", metric_label="(%)")),
        "underemployment_rate": _percent_points_to_ratio(_value(lf_latest, metric_code="UDR", metric_label="(%)")),
        "observation_date": lf_latest_date.strftime("%Y-%m-%d"),
    }

    labour_force_m3m = labour_force_total[labour_force_total["frequency_code"].eq("M3M")].copy()
    lf_count_history = labour_force_m3m[
        labour_force_m3m["metric_code"].isin(["LF", "EM", "UE"])
        & labour_force_m3m["metric_label"].eq("No. ('000)")
    ].copy()
    lf_count_history["series"] = lf_count_history["metric_code"].map({"LF": "Labour force", "EM": "Employed", "UE": "Unemployed"})
    lf_count_history = _with_dates(lf_count_history)
    lf_count_history = lf_count_history[lf_count_history["value"].notna()].sort_values(["series", "date"])
    lf_rate_history = labour_force_m3m[labour_force_m3m["metric_code"].isin(["UR", "UDR"])].copy()
    lf_rate_history["series"] = lf_rate_history["metric_code"].map({"UR": "Unemployment rate", "UDR": "Underemployment rate"})
    lf_rate_history["value"] = lf_rate_history["value"].map(_percent_points_to_ratio)
    lf_rate_history = _with_dates(lf_rate_history)
    lf_rate_history = lf_rate_history[lf_rate_history["value"].notna()].sort_values(["series", "date"])

    sector = _with_dates(sector)
    sector["value"] = pd.to_numeric(sector["value"], errors="coerce")
    demand = sector[sector["dataset_id"].eq("labour_demand_by_industry")].copy()
    demand_total = demand[demand["industry"].eq("Total")].copy()
    demand_latest = _latest_rows(demand_total)
    demand_date = _latest_date(demand_total)
    demand_kpi = {
        "vacancies": _value(demand_latest, metric_name="vacancies"),
        "persons_engaged": _value(demand_latest, metric_name="persons_engaged"),
        "vacancy_rate": _percent_points_to_ratio(_value(demand_latest, metric_name="vacancy_rate")),
        "observation_date": demand_date.strftime("%Y-%m-%d"),
    }

    demand_history = demand_total[demand_total["metric_name"].isin(["persons_engaged", "vacancies"])].copy()
    demand_history["series"] = demand_history["metric_name"].map({"persons_engaged": "Persons engaged", "vacancies": "Vacancies"})
    demand_history = _with_dates(demand_history)
    demand_history = demand_history[demand_history["value"].notna()].sort_values(["series", "date"])
    vacancy_industry_history = demand[
        demand["metric_name"].eq("vacancies")
        & demand["industry"].isin(VACANCY_HISTORY_SERIES)
    ].copy()
    vacancy_industry_history["series"] = vacancy_industry_history["industry"].map(VACANCY_HISTORY_SERIES)
    vacancy_industry_history = _with_dates(vacancy_industry_history)
    vacancy_industry_history = vacancy_industry_history[
        vacancy_industry_history["value"].notna()
    ].sort_values(["series", "date"])
    vacancy_rate_history = demand_total[demand_total["metric_name"].eq("vacancy_rate")].copy()
    vacancy_rate_history["value"] = vacancy_rate_history["value"].map(_percent_points_to_ratio)
    vacancy_rate_history = _with_dates(vacancy_rate_history)
    vacancy_rate_history = vacancy_rate_history[vacancy_rate_history["value"].notna()].sort_values("date")

    demand_industry_latest = demand[
        demand["metric_name"].isin(["vacancies", "vacancy_rate"])
        & _top_level_industry_mask(demand)
    ].copy()
    demand_industry_latest = demand_industry_latest[
        demand_industry_latest["date"].eq(demand_date.strftime("%Y-%m-%d"))
    ].copy()
    demand_industry_latest["industry"] = demand_industry_latest["industry"].map(_compact_industry)
    demand_industry_latest = demand_industry_latest.pivot_table(
        index="industry", columns="metric_name", values="value", aggfunc="first"
    ).reset_index()
    demand_industry_latest = demand_industry_latest.rename(
        columns={"vacancies": "vacancies", "vacancy_rate": "vacancy_rate_points"}
    )
    if "vacancy_rate_points" in demand_industry_latest:
        demand_industry_latest["vacancy_rate"] = demand_industry_latest["vacancy_rate_points"].map(_percent_points_to_ratio)
    demand_industry_latest["vacancies"] = pd.to_numeric(demand_industry_latest.get("vacancies"), errors="coerce")
    demand_industry_latest = demand_industry_latest.sort_values("vacancies").reset_index(drop=True)

    wage_history = sector[
        sector["metric_name"].isin(
            ["nominal_wage_yoy_pct", "real_wage_yoy_pct", "nominal_payroll_yoy_pct", "real_payroll_yoy_pct"]
        )
        & sector["industry"].eq("Total")
    ].copy()
    wage_history["series"] = wage_history["metric_name"].map(
        {
            "nominal_wage_yoy_pct": "Nom wage",
            "real_wage_yoy_pct": "Real wage",
            "nominal_payroll_yoy_pct": "Nom pay",
            "real_payroll_yoy_pct": "Real pay",
        }
    )
    wage_history["value"] = wage_history["value"].map(_percent_points_to_ratio)
    wage_history = _with_dates(wage_history)
    wage_history = wage_history[wage_history["value"].notna()].sort_values(["series", "date"])
    wage_latest = wage_history[wage_history["date"].eq(wage_history["date"].max())].copy()
    wage_kpi = {"observation_date": wage_latest["date"].iloc[0] if not wage_latest.empty else None}
    # The sector mart uses semantic metric_name values rather than the C&SD
    # metric_code, so populate the wage KPI directly from its latest rows.
    for metric_name, field in (
        ("nominal_wage_yoy_pct", "nominal_wage_yoy"),
        ("real_wage_yoy_pct", "real_wage_yoy"),
        ("nominal_payroll_yoy_pct", "nominal_payroll_yoy"),
    ):
        rows = sector[(sector["industry"] == "Total") & sector["metric_name"].eq(metric_name)]
        rows = rows[rows["date"].eq(wage_latest["date"].max())]
        raw_value = rows["value"].iloc[-1] if not rows.empty else None
        wage_kpi[field] = _percent_points_to_ratio(raw_value)
    wage_kpi["observation_date"] = wage_latest["date"].iloc[0] if not wage_latest.empty else None

    earnings = income[
        income["metric_name"].eq("median_monthly_earnings")
        & income["dimension_type"].eq("industry")
        & income["sex"].eq("Total")
    ].copy()
    earnings["date"] = pd.to_datetime(earnings["period_end"], errors="coerce")
    earnings = earnings[earnings["date"].notna()].copy()
    earnings_m3m = earnings[earnings["frequency_code"].eq("M3M")].copy()
    earnings_total_history = earnings_m3m[earnings_m3m["dimension_label"].eq("Total")].copy()
    earnings_total_history["month"] = earnings_total_history["date"].dt.strftime("%Y-%m")
    earnings_total_history["date"] = earnings_total_history["date"].dt.strftime("%Y-%m-%d")
    earnings_latest_date = earnings_m3m["date"].max()
    earnings_latest = earnings_m3m[earnings_m3m["date"].eq(earnings_latest_date)].copy()
    earnings_latest = earnings_latest[["dimension_label", "value"]].rename(
        columns={"dimension_label": "industry", "value": "median_monthly_earnings"}
    )
    earnings_latest["industry"] = earnings_latest["industry"].map(_compact_industry)
    earnings_latest = earnings_latest.sort_values("median_monthly_earnings").reset_index(drop=True)
    earnings_industry_history = earnings_m3m[
        earnings_m3m["dimension_label"].isin(EARNINGS_HISTORY_INDUSTRIES)
    ].copy()
    earnings_industry_history["series"] = earnings_industry_history["dimension_label"].map(EARNINGS_HISTORY_LABELS)
    earnings_industry_history["month"] = earnings_industry_history["date"].dt.strftime("%Y-%m")
    earnings_industry_history["date"] = earnings_industry_history["date"].dt.strftime("%Y-%m-%d")
    # The portable renderer pivots long-form rows in first-seen x order; sort
    # by date first so staggered series cannot append their early months at the
    # far right of the chart.
    earnings_industry_history = earnings_industry_history[
        earnings_industry_history["value"].notna()
    ].sort_values(["date", "series"])
    income_kpi = {
        "median_monthly_earnings": float(
            earnings_latest.loc[earnings_latest["industry"].eq("Total"), "median_monthly_earnings"].iloc[0]
        ),
        "observation_date": earnings_latest_date.strftime("%Y-%m-%d"),
    }
    occupation = income[
        income["metric_name"].eq("median_monthly_earnings")
        & income["dimension_type"].eq("occupation")
        & income["sex"].eq("Total")
        & income["frequency_code"].eq("M3M")
    ].copy()
    occupation["date"] = pd.to_datetime(occupation["period_end"], errors="coerce")
    occupation = occupation[occupation["date"].eq(occupation["date"].max())].copy()
    occupation = occupation[["dimension_label", "value"]].rename(
        columns={"dimension_label": "occupation", "value": "median_monthly_earnings"}
    )
    occupation = occupation.sort_values("median_monthly_earnings").reset_index(drop=True)
    occupation_history = income[
        income["metric_name"].eq("median_monthly_earnings")
        & income["dimension_type"].eq("occupation")
        & income["sex"].eq("Total")
        & income["frequency_code"].eq("M3M")
        & income["dimension_label"].isin(OCCUPATION_HISTORY_SERIES)
    ].copy()
    occupation_history["date"] = pd.to_datetime(occupation_history["period_end"], errors="coerce")
    occupation_history = occupation_history[occupation_history["date"].notna()].copy()
    occupation_history["series"] = occupation_history["dimension_label"].map(OCCUPATION_HISTORY_LABELS)
    occupation_history["month"] = occupation_history["date"].dt.strftime("%Y-%m")
    occupation_history["date"] = occupation_history["date"].dt.strftime("%Y-%m-%d")
    occupation_history = occupation_history[
        occupation_history["value"].notna()
    ].sort_values(["date", "series"])

    policy = policy.copy()
    policy["date"] = pd.to_datetime(policy["period_end"], errors="coerce")
    policy = policy[policy["date"].notna()].copy()
    policy_scheme = policy[policy["breakdown_type"].eq("scheme") & policy["dimension_label"].isin(["All applicants", "Total"])].copy()
    policy_scheme["series"] = policy_scheme["scheme"].map(_policy_short_name)
    policy_scheme["month"] = policy_scheme["date"].dt.strftime("%Y-%m")
    policy_scheme["date"] = policy_scheme["date"].dt.strftime("%Y-%m-%d")
    policy_received = policy_scheme[policy_scheme["metric_name"].eq("applications_received")].copy()
    policy_scheme_display, policy_approved = _add_qmas_approval_equivalent(policy_scheme)
    # Keep the chart legend readable on a 390px viewport. The full set of
    # schemes, including the smaller ASSG/TechTAS flows, remains in the latest
    # annual table below.
    chart_policy_schemes = {"GEP", "ASMTP", "IANG", "TTPS", "QMAS"}
    policy_received = policy_received[policy_received["series"].isin(chart_policy_schemes)].copy()
    policy_approved = policy_approved[policy_approved["series"].isin(chart_policy_schemes)].copy()
    policy_latest_year = policy_scheme["date"].max()[:4]
    policy_latest = policy_scheme_display[policy_scheme_display["date"].str.startswith(policy_latest_year)].copy()
    policy_received_total = policy_latest.loc[policy_latest["metric_name"].eq("applications_received"), "value"].sum()
    policy_approved_total = policy_latest.loc[policy_latest["metric_name"].eq("applications_approved"), "value"].sum()
    qmas_quota = policy_latest.loc[
        policy_latest["scheme"].eq("Quality Migrant Admission Scheme")
        & policy_latest["metric_name"].eq("quota_allotted"),
        "value",
    ]
    policy_kpi = {
        "applications_received": float(policy_received_total),
        "applications_approved": float(policy_approved_total),
        "qmas_quota": float(qmas_quota.iloc[0]) if not qmas_quota.empty else None,
        "observation_date": f"{policy_latest_year}-12-31",
    }
    policy_latest_table = policy_latest.pivot_table(
        index=["scheme", "series"], columns="metric_name", values="value", aggfunc="first"
    ).reset_index()
    policy_latest_table = policy_latest_table.rename(
        columns={
            "applications_received": "applications_received",
            "applications_approved": "applications_approved",
            "quota_allotted": "qmas_quota",
        }
    ).sort_values("applications_received", na_position="last", ascending=False)

    datasets = {
        "kpi_labour_force": [lf_kpi],
        "kpi_labour_demand": [demand_kpi],
        "kpi_wage": [wage_kpi],
        "kpi_income": [income_kpi],
        "kpi_talent_policy": [policy_kpi],
        "labour_force_history": _records_json_safe(lf_count_history, ["month", "date", "series", "value"]),
        "labour_rate_history": _records_json_safe(lf_rate_history, ["month", "date", "series", "value"]),
        "vacancy_history": _records_json_safe(demand_history, ["month", "date", "series", "value"]),
        "vacancy_industry_history": _records_json_safe(vacancy_industry_history, ["month", "date", "series", "value"]),
        "vacancy_rate_history": _records_json_safe(vacancy_rate_history, ["month", "date", "value"]),
        "vacancies_by_industry_latest": _records_json_safe(demand_industry_latest, ["industry", "vacancies", "vacancy_rate"]),
        "wage_yoy_history": _records_json_safe(wage_history, ["month", "date", "series", "value"]),
        "wage_yoy_latest": _records_json_safe(wage_latest, ["industry", "value"]),
        "earnings_history": _records_json_safe(earnings_total_history, ["month", "date", "value"]),
        "earnings_industry_history": _records_json_safe(earnings_industry_history, ["month", "date", "series", "value"]),
        "earnings_by_industry_latest": _records_json_safe(earnings_latest, ["industry", "median_monthly_earnings"]),
        "occupation_earnings_history": _records_json_safe(occupation_history, ["month", "date", "series", "value"]),
        "earnings_by_occupation_latest": _records_json_safe(occupation, ["occupation", "median_monthly_earnings"]),
        "talent_policy_received_history": _records_json_safe(policy_received, ["month", "date", "series", "value"]),
        "talent_policy_approved_history": _records_json_safe(policy_approved, ["month", "date", "series", "value", "approval_basis"]),
        "talent_policy_latest": _records_json_safe(policy_latest_table, ["scheme", "series", "applications_received", "applications_approved", "qmas_quota"]),
    }

    status_rows: list[dict[str, Any]] = []
    dataset_status_specs = [
        ("censtatd_labour_force", "labour_force_monthly", labour_force, "Monthly rolling-three-month series; annual estimates are retained."),
        ("censtatd_labour_demand", "labour_demand_by_industry", demand, "Quarterly labour-demand survey; excludes civil-service vacancies."),
        ("censtatd_wage_payroll", "wage_payroll_indices", sector[sector["dataset_id"].isin(["nominal_wage_index_by_industry", "real_wage_index_by_industry", "nominal_payroll_index_by_industry", "real_payroll_index_by_industry"])], "C&SD-published wage/payroll indices; wage/payroll series are not the same as median earnings."),
        ("censtatd_earnings", "median_earnings_by_industry", earnings, "Median monthly earnings; the dashboard uses the rolling-three-month series for the main trend."),
        ("talent_policy_open_data", "talent_policy_supply_panel", policy, "Applications/approvals and QMAS quota are policy-flow indicators; QMAS quota-allotted successful selection cases are included as the approval-equivalent display measure, not actual arrivals or employment."),
    ]
    for source_id, dataset_id, frame, notes in dataset_status_specs:
        latest = _latest_date(frame)
        status_rows.append(
            {
                "source": PUBLIC_SOURCES[source_id]["label"],
                "dataset": dataset_id,
                "type": "Measure",
                "status": "Healthy" if len(frame) else "Degraded",
                "latest_observation": latest.strftime("%Y-%m-%d"),
                "records": int(len(frame)),
                "freshness": "Live at build time",
                "notes": notes,
            }
        )

    all_dates = [
        _latest_date(labour_force),
        _latest_date(demand),
        _latest_date(wage_history),
        earnings_latest_date,
        pd.Timestamp(f"{policy_latest_year}-12-31"),
    ]
    data_as_of = max(all_dates).strftime("%Y-%m-%d")
    snapshot_id = hashlib.sha256(json.dumps(datasets, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

    cards = [
        {
            "id": "labour_force_card",
            "description": "C&SD monthly rolling-three-month labour-force headline; observation period is shown in the last metric.",
            "dataset": "kpi_labour_force",
            "sourceId": "censtatd_labour_force",
            "metrics": [
                {"label": "Labour force ('000)", "field": "labour_force_thousands", "format": "number"},
                {"label": "Employed ('000)", "field": "employed_thousands", "format": "number"},
                {"label": "Unemployment rate", "field": "unemployment_rate", "format": "percent"},
                {"label": "Underemployment rate", "field": "underemployment_rate", "format": "percent"},
                {"label": "Observation period", "field": "observation_date", "format": "text"},
            ],
        },
        {
            "id": "labour_demand_card",
            "description": "C&SD quarterly establishments/persons-engaged and vacancies survey; observation period is shown in the last metric.",
            "dataset": "kpi_labour_demand",
            "sourceId": "censtatd_labour_demand",
            "metrics": [
                {"label": "Vacancies", "field": "vacancies", "format": "number"},
                {"label": "Persons engaged", "field": "persons_engaged", "format": "number"},
                {"label": "Vacancy rate", "field": "vacancy_rate", "format": "percent"},
                {"label": "Observation period", "field": "observation_date", "format": "text"},
            ],
        },
        {
            "id": "wage_card",
            "description": "C&SD industry wage/payroll indices; YoY measures are percentage changes, while the source period is shown below.",
            "dataset": "kpi_wage",
            "sourceId": "censtatd_wage_payroll",
            "metrics": [
                {"label": "Nominal wage YoY", "field": "nominal_wage_yoy", "format": "percent"},
                {"label": "Real wage YoY", "field": "real_wage_yoy", "format": "percent"},
                {"label": "Nominal payroll YoY", "field": "nominal_payroll_yoy", "format": "percent"},
                {"label": "Observation period", "field": "observation_date", "format": "text"},
            ],
        },
        {
            "id": "income_card",
            "description": "Median monthly employment earnings for all industries, using the latest rolling-three-month observation.",
            "dataset": "kpi_income",
            "sourceId": "censtatd_earnings",
            "metrics": [
                {"label": "Median monthly earnings (HK$)", "field": "median_monthly_earnings", "format": "number"},
                {"label": "Observation period", "field": "observation_date", "format": "text"},
            ],
        },
        {
            "id": "talent_policy_card",
            "description": "Annual policy-flow totals across the schemes; QMAS quota-allotted successful selection cases are included in the approval-equivalent total. Applications are not the same as arrivals or employment.",
            "dataset": "kpi_talent_policy",
            "sourceId": "talent_policy_open_data",
            "metrics": [
                {"label": "Applications received", "field": "applications_received", "format": "number"},
                {"label": "Applications approved", "field": "applications_approved", "format": "number"},
                {"label": "QMAS quota", "field": "qmas_quota", "format": "number"},
                {"label": "Observation year", "field": "observation_date", "format": "text"},
            ],
        },
    ]

    charts = [
        {
            "id": "labour_force_chart",
            "title": "Labour force, employment and unemployment",
            "subtitle": "Monthly rolling-three-month observations, thousand persons; the latest point is not a single-month estimate.",
            "type": "line",
            "intent": "trend",
            "dataset": "labour_force_history",
            "sourceId": "censtatd_labour_force",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "'000 persons"}, "color": {"field": "series", "type": "nominal", "label": "Series"}},
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 900,
        },
        {
            "id": "labour_rates_chart",
            "title": "Unemployment and underemployment rates",
            "subtitle": "Monthly rolling-three-month rates; values are shown as percentage points.",
            "type": "line",
            "intent": "trend",
            "dataset": "labour_rate_history",
            "sourceId": "censtatd_labour_force",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "%"}, "color": {"field": "series", "type": "nominal", "label": "Rate"}},
            "valueFormat": "percent",
            "layout": "full",
            "maxRows": 500,
        },
        {
            "id": "vacancies_by_industry_chart",
            "title": "Vacancies by industry section",
            "subtitle": f"Latest quarterly C&SD comparison ({demand_date.strftime('%Y-%m')}); top-level industry sections only.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "vacancies_by_industry_latest",
            "sourceId": "censtatd_labour_demand",
            "encodings": {"x": {"field": "industry", "type": "nominal", "label": "Industry"}, "y": {"field": "vacancies", "type": "quantitative", "label": "Vacancies"}},
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "vacancy_industry_history_chart",
            "title": "Vacancy history for selected industry sections",
            "subtitle": "Quarterly history from 2000; click the legend to show or hide the total and selected industry series. The latest full industry ranking remains above.",
            "type": "line",
            "intent": "trend",
            "dataset": "vacancy_industry_history",
            "sourceId": "censtatd_labour_demand",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Quarter"}, "y": {"field": "value", "type": "quantitative", "label": "Vacancies"}, "color": {"field": "series", "type": "nominal", "label": "Industry"}},
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 700,
        },
        {
            "id": "vacancy_rate_chart",
            "title": "Overall vacancy rate",
            "subtitle": "Quarterly vacancy rate across the C&SD labour-demand survey universe.",
            "type": "line",
            "intent": "trend",
            "dataset": "vacancy_rate_history",
            "sourceId": "censtatd_labour_demand",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Quarter"}, "y": {"field": "value", "type": "quantitative", "label": "%"}},
            "valueFormat": "percent",
            "layout": "half",
        },
        {
            "id": "wage_yoy_chart",
            "title": "Wage and payroll growth",
            "subtitle": "C&SD industry-index year-on-year changes for the total industry series; nominal and real measures are retained separately.",
            "type": "line",
            "intent": "comparison",
            "dataset": "wage_yoy_history",
            "sourceId": "censtatd_wage_payroll",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Quarter"}, "y": {"field": "value", "type": "quantitative", "label": "YoY change"}, "color": {"field": "series", "type": "nominal", "label": "Measure"}},
            "valueFormat": "percent",
            "layout": "full",
        },
        {
            "id": "earnings_by_industry_chart",
            "title": "Median monthly employment earnings by industry",
            "subtitle": f"Latest rolling-three-month comparison ({earnings_latest_date.strftime('%Y-%m')}); all sexes combined.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "earnings_by_industry_latest",
            "sourceId": "censtatd_earnings",
            "encodings": {"x": {"field": "industry", "type": "nominal", "label": "Industry"}, "y": {"field": "median_monthly_earnings", "type": "quantitative", "label": "HK$"}},
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "earnings_industry_history_chart",
            "title": "Employment earnings history for selected industries",
            "subtitle": "Monthly three-month moving-average history from 2008; click the legend to show or hide selected industry series. Values are HK$ per month.",
            "type": "line",
            "intent": "trend",
            "dataset": "earnings_industry_history",
            "sourceId": "censtatd_earnings",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "HK$ / month"}, "color": {"field": "series", "type": "nominal", "label": "Industry"}},
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 1_600,
        },
        {
            "id": "occupation_earnings_history_chart",
            "title": "Employment earnings history for selected occupations",
            "subtitle": "Monthly three-month moving-average history from 2016; click the legend to show or hide selected occupations. Values are HK$ per month.",
            "type": "line",
            "intent": "trend",
            "dataset": "occupation_earnings_history",
            "sourceId": "censtatd_earnings",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "HK$ / month"}, "color": {"field": "series", "type": "nominal", "label": "Occupation"}},
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 800,
        },
        {
            "id": "talent_policy_received_chart",
            "title": "Talent-policy applications received",
            "subtitle": "Annual applications received by scheme; this is policy demand, not confirmed inflow or employment.",
            "type": "line",
            "intent": "trend",
            "dataset": "talent_policy_received_history",
            "sourceId": "talent_policy_open_data",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Year"}, "y": {"field": "value", "type": "quantitative", "label": "Applications"}, "color": {"field": "series", "type": "nominal", "label": "Scheme"}},
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "talent_policy_approved_chart",
            "title": "Talent-policy applications approved",
            "subtitle": "Annual approvals by scheme; QMAS uses the official quota-allotted successful selection count as the approval-equivalent measure. Approval is not the same as arrival, visa activation or labour-force entry.",
            "type": "line",
            "intent": "trend",
            "dataset": "talent_policy_approved_history",
            "sourceId": "talent_policy_open_data",
            "encodings": {"x": {"field": "month", "type": "temporal", "label": "Year"}, "y": {"field": "value", "type": "quantitative", "label": "Applications approved"}, "color": {"field": "series", "type": "nominal", "label": "Scheme"}},
            "valueFormat": "number",
            "layout": "full",
        },
    ]

    tables = [
        {
            "id": "earnings_by_occupation_table",
            "title": "Median monthly employment earnings by occupation",
            "subtitle": f"Latest rolling-three-month observation ({earnings_latest_date.strftime('%Y-%m')}); all sexes combined.",
            "dataset": "earnings_by_occupation_latest",
            "sourceId": "censtatd_earnings",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "occupation", "label": "Occupation", "type": "text"},
                {"field": "median_monthly_earnings", "label": "Median earnings (HK$)", "format": "number"},
            ],
        },
        {
            "id": "talent_policy_latest_table",
            "title": "Latest annual talent-policy flow by scheme",
            "subtitle": f"Official annual figures for {policy_latest_year}; QMAS approval uses quota-allotted successful selection cases, while the raw QMAS quota remains shown separately.",
            "dataset": "talent_policy_latest",
            "sourceId": "talent_policy_open_data",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "series", "label": "Scheme", "type": "text"},
                {"field": "applications_received", "label": "Applications received", "format": "number"},
                {"field": "applications_approved", "label": "Applications approved", "format": "number"},
            ],
        },
        {
            "id": "source_health_table",
            "title": "Labour-market data-source health",
            "subtitle": "Local audited snapshots used to build this page; dates are observation dates, not fetch dates.",
            "dataset": "source_health",
            "sourceId": "censtatd_labour_force",
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "dataset", "label": "Dataset", "type": "text"},
                {"field": "status", "label": "Status", "type": "text"},
                {"field": "latest_observation", "label": "Latest observation", "type": "text"},
                {"field": "records", "label": "Records", "format": "number"},
                {"field": "freshness", "label": "Refresh mode", "type": "text"},
                {"field": "notes", "label": "Notes", "type": "text"},
            ],
        },
    ]

    sources = list(PUBLIC_SOURCES.values())
    blocks = [
        {"id": "kpi_grid", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
        {"id": "labour_force_chart_block", "type": "chart", "chartId": "labour_force_chart"},
        {"id": "labour_rates_chart_block", "type": "chart", "chartId": "labour_rates_chart"},
        {"id": "vacancies_by_industry_chart_block", "type": "chart", "chartId": "vacancies_by_industry_chart"},
        {"id": "vacancy_industry_history_chart_block", "type": "chart", "chartId": "vacancy_industry_history_chart"},
        {"id": "vacancy_rate_chart_block", "type": "chart", "chartId": "vacancy_rate_chart"},
        {"id": "wage_yoy_chart_block", "type": "chart", "chartId": "wage_yoy_chart"},
        {"id": "earnings_by_industry_chart_block", "type": "chart", "chartId": "earnings_by_industry_chart"},
        {"id": "earnings_industry_history_chart_block", "type": "chart", "chartId": "earnings_industry_history_chart"},
        {"id": "occupation_earnings_history_chart_block", "type": "chart", "chartId": "occupation_earnings_history_chart"},
        {"id": "talent_policy_received_chart_block", "type": "chart", "chartId": "talent_policy_received_chart"},
        {"id": "talent_policy_approved_chart_block", "type": "chart", "chartId": "talent_policy_approved_chart"},
        {"id": "earnings_by_occupation_table_block", "type": "table", "tableId": "earnings_by_occupation_table"},
        {"id": "talent_policy_latest_table_block", "type": "table", "tableId": "talent_policy_latest_table"},
        {"id": "source_health_table_block", "type": "table", "tableId": "source_health_table"},
        {"id": "methodology", "type": "markdown", "body": "## How to read this dashboard\n\nThis page combines official C&SD labour-market series with Labour Department and Immigration Department policy-flow data. Monthly labour-force and earnings observations are rolling-three-month measures; labour demand and wage/payroll indices are quarterly; talent-policy data are annual. QMAS quota-allotted successful selection cases are used as the approval-equivalent display measure, while the raw QMAS quota field is retained separately. Applications, approvals and QMAS quota cases should not be interpreted as confirmed arrivals, employment or labour-force participation."},
        {"id": "snapshot_context", "type": "markdown", "body": f"## Snapshot\n\nData snapshot generated {generated_at}."},
    ]

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong Labour Market & Talent Policy",
            "description": "Hong Kong labour-force conditions, labour demand, wages, employment earnings and official talent-policy flows.",
            "sector": "hk-labour-market",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": blocks,
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": {**datasets, "source_health": status_rows}},
        "sources": sources,
        "package_info": {"originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-labour-market/", "snapshotId": snapshot_id, "dataAsOf": data_as_of},
    }
    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of,
        "overall_status": "Healthy" if all(row["status"] == "Healthy" for row in status_rows) else "Degraded",
        "live_sources": len(status_rows),
        "planned_sources": 0,
        "sources": status_rows,
        "attachment_filename": f"hk-labour-market-dashboard-{now.date().isoformat()}.html",
    }
    return artifact, status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--status-output", type=Path, required=True)
    args = parser.parse_args()
    artifact, status = build_artifact()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    args.status_output.write_text(json.dumps(status, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"], "data_as_of": status["data_as_of"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
