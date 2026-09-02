"""Transparent Sino Land H1-to-FY revenue nowcast baselines.

This module is deliberately a small bridge, not a fitted earnings model.  It
keeps two different scopes separate:

* the consolidated group baseline annualises the latest official H1 facts;
* the segment table projects H2 using the immediately prior FY's H1/H2 shape,
  with an explicit +/-20% scenario around that one-year anchor.
* the historical backtest keeps a naive 2x-H1 benchmark beside a prior-H1/FY
  share benchmark so non-stationary timing effects are visible.

The operating-segment note includes the Group's share of associates and joint
ventures, so segment rows are diagnostic context only.  They must not be
added together and presented as consolidated turnover or profit.
"""

from __future__ import annotations

import json
from typing import Any
import uuid

import pandas as pd

from .sino_land_financial_model import (
    SINO_ANNUAL_REPORT_2025_URL,
    SINO_INTERIM_REPORT_2025_26_URL,
    SINO_LAND_TICKER,
    build_sino_land_financial_facts,
)
from .sino_land_h1_history import H1_HISTORY_DATASET
from .sino_residential_bridge import SCHEDULE_DATASET
from .storage import load_latest_normalized, save_normalized_dataset


NOWCAST_DATASET = "sino_land_h1_nowcast"
SEGMENT_SCENARIO_DATASET = "sino_land_h1_segment_scenarios"
QUALITY_DATASET = "sino_land_h1_nowcast_quality"
BACKTEST_DATASET = "sino_land_h1_backtest"
BACKTEST_QUALITY_DATASET = "sino_land_h1_backtest_quality"
RESIDENTIAL_H2_DATASET = "sino_land_h1_residential_h2_scenario"
RESIDENTIAL_H2_QUALITY_DATASET = "sino_land_h1_residential_h2_quality"

GROUP_METRICS = (
    "consolidated_revenue",
    "sales_of_properties",
    "rental_income_operating_leases",
    "hotel_operations_revenue",
    "underlying_profit_attributable",
    "profit_attributable",
)
SEGMENT_COMPONENTS = (
    "property_sales",
    "property_rental",
    "property_management_other_services",
    "hotel_operations",
    "investments_securities",
    "financing",
)
SEGMENT_METRICS = ("segment_revenue", "segment_result")

NOWCAST_COLUMNS = [
    "nowcast_id",
    "ticker",
    "target_fiscal_year_end",
    "latest_h1_period_end",
    "metric",
    "scope",
    "h1_actual_hkd_m",
    "h2_forecast_hkd_m",
    "fy_forecast_hkd_m",
    "model_name",
    "model_status",
    "pit_quality",
    "research_only",
    "source_fact_ids",
    "source_url",
    "caveat",
]

SEGMENT_SCENARIO_COLUMNS = [
    "scenario_id",
    "ticker",
    "target_fiscal_year_end",
    "latest_h1_period_end",
    "component",
    "metric",
    "scope",
    "scenario",
    "h1_actual_hkd_m",
    "anchor_fiscal_year_end",
    "anchor_h1_hkd_m",
    "anchor_fy_hkd_m",
    "anchor_h1_share_pct",
    "anchor_h2_h1_ratio",
    "h2_forecast_hkd_m",
    "fy_forecast_hkd_m",
    "model_name",
    "model_status",
    "pit_quality",
    "research_only",
    "source_fact_ids",
    "source_urls",
    "caveat",
]

QUALITY_COLUMNS = [
    "quality_id",
    "ticker",
    "check_name",
    "observed_value",
    "threshold",
    "status",
    "model_use",
    "caveat",
]

BACKTEST_COLUMNS = [
    "backtest_id",
    "ticker",
    "fiscal_year_end",
    "h1_period_end",
    "backtest_scope",
    "component",
    "metric",
    "scope",
    "h1_actual_hkd_m",
    "actual_fy_hkd_m",
    "forecast_fy_hkd_m",
    "error_hkd_m",
    "error_pct",
    "abs_error_pct",
    "model_name",
    "reference_pair_count",
    "pit_quality",
    "research_only",
    "source_fact_ids",
    "source_urls",
    "caveat",
]

RESIDENTIAL_H2_COLUMNS = [
    "scenario_id",
    "ticker",
    "scope_level",
    "srpe_development_id",
    "project_label",
    "scenario",
    "target_fiscal_year_end",
    "h1_period_end",
    "cohort_cutoff_period",
    "recognition_period_start",
    "recognition_period_end",
    "cohort_rows",
    "cohort_units_gross",
    "contract_value_gross_hkd_m",
    "attributable_contract_value_hkd_m",
    "model_name",
    "pit_quality",
    "research_only",
    "source_urls",
    "caveat",
]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    value = str(value).strip()
    return value or None


def _date(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _fiscal_year_end(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return f"{int(parsed.year) + (1 if int(parsed.month) > 6 else 0)}-06-30"


def _source_ids(frame: pd.DataFrame) -> list[str]:
    return [
        str(value)
        for value in frame.get("fact_id", pd.Series(dtype=object)).dropna().tolist()
    ]


def _source_urls(frame: pd.DataFrame) -> list[str]:
    return sorted(
        {
            str(value)
            for value in frame.get("source_url", pd.Series(dtype=object)).dropna()
            if _text(value)
        }
    )


def _latest_h1(facts: pd.DataFrame) -> tuple[pd.DataFrame, str | None, str | None]:
    frame = facts.copy() if facts is not None else pd.DataFrame()
    if frame.empty:
        return frame, None, None
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    interim = frame.loc[frame["period_type"].eq("interim")].copy()
    if interim.empty or interim["period_end"].dropna().empty:
        return pd.DataFrame(columns=frame.columns), None, None
    period_end = interim["period_end"].max()
    target_end = _fiscal_year_end(period_end)
    return (
        interim.loc[interim["period_end"].eq(period_end)].copy(),
        _date(period_end),
        target_end,
    )


def _quality_row(
    check_name: str,
    observed_value: Any,
    threshold: str,
    status: str,
    model_use: str,
    caveat: str,
    quality_prefix: str = "sino_land_h1_nowcast",
) -> dict[str, Any]:
    return {
        "quality_id": f"{quality_prefix}:{check_name}",
        "ticker": SINO_LAND_TICKER,
        "check_name": check_name,
        "observed_value": observed_value,
        "threshold": threshold,
        "status": status,
        "model_use": model_use,
        "caveat": caveat,
    }


def build_sino_land_h1_nowcast(
    official_facts: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Build group annualisation, segment scenarios and quality checks."""
    facts = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    h1, h1_period_end, target_fy_end = _latest_h1(facts)
    if h1.empty or target_fy_end is None or h1_period_end is None:
        return {
            "nowcast": pd.DataFrame(columns=NOWCAST_COLUMNS),
            "segment_scenarios": pd.DataFrame(columns=SEGMENT_SCENARIO_COLUMNS),
            "quality": pd.DataFrame(columns=QUALITY_COLUMNS),
        }

    nowcast_rows: list[dict[str, Any]] = []
    for metric in GROUP_METRICS:
        row = h1.loc[h1["metric"].eq(metric)]
        if row.empty:
            continue
        fact = row.iloc[0]
        value = pd.to_numeric(fact.get("value"), errors="coerce")
        if pd.isna(value):
            continue
        fact_ids = _source_ids(row)
        nowcast_rows.append(
            {
                "nowcast_id": f"sino_land_h1_nowcast:{metric}:{target_fy_end}",
                "ticker": SINO_LAND_TICKER,
                "target_fiscal_year_end": target_fy_end,
                "latest_h1_period_end": h1_period_end,
                "metric": metric,
                "scope": _text(fact.get("geography_scope")) or "group_all_geographies",
                "h1_actual_hkd_m": float(value),
                "h2_forecast_hkd_m": float(value),
                "fy_forecast_hkd_m": float(value) * 2.0,
                "model_name": "naive_2x_h1",
                "model_status": "benchmark_only",
                "pit_quality": _text(fact.get("availability_quality")) or "unknown",
                "research_only": True,
                "source_fact_ids": json.dumps(fact_ids, ensure_ascii=False),
                "source_url": _text(fact.get("source_url")),
                "caveat": "Latest official H1 actual plus equal H2 run-rate; no seasonality, project handover, scope or margin change is modelled. This is a benchmark, not a formal forecast.",
            }
        )

    annual = facts.loc[
        facts["fact_group"].eq("operating_segments")
        & facts["period_type"].eq("annual")
        & facts["segment"].isin(SEGMENT_COMPONENTS)
        & facts["metric"].isin(SEGMENT_METRICS)
    ].copy()
    annual["period_end_dt"] = pd.to_datetime(annual["period_end"], errors="coerce")
    anchor = annual.loc[annual["period_end_dt"] < pd.Timestamp(target_fy_end)]
    anchor_end = (
        anchor["period_end_dt"].max().strftime("%Y-%m-%d")
        if not anchor.empty and anchor["period_end_dt"].notna().any()
        else None
    )
    anchor = anchor.loc[anchor["period_end_dt"].eq(pd.to_datetime(anchor_end))]
    segment_rows: list[dict[str, Any]] = []
    invalid_ratio_rows = 0
    for component in SEGMENT_COMPONENTS:
        for metric in SEGMENT_METRICS:
            h1_row = h1.loc[
                h1["fact_group"].eq("operating_segments")
                & h1["segment"].eq(component)
                & h1["metric"].eq(metric)
            ]
            anchor_row = anchor.loc[
                anchor["segment"].eq(component) & anchor["metric"].eq(metric)
            ]
            if h1_row.empty or anchor_row.empty:
                continue
            h1_fact = h1_row.iloc[0]
            anchor_fact = anchor_row.iloc[0]
            h1_value = pd.to_numeric(h1_fact.get("value"), errors="coerce")
            anchor_value = pd.to_numeric(anchor_fact.get("value"), errors="coerce")
            if pd.isna(h1_value) or pd.isna(anchor_value) or anchor_value <= 0:
                invalid_ratio_rows += 1
                continue
            # The prior-FY row is an annual total, not its H1.  Use the
            # matching prior interim row when available to derive the actual
            # H2/H1 shape rather than confusing FY with H1.
            prior_h1_end = (
                pd.to_datetime(anchor_end)
                - pd.DateOffset(months=6)
                + pd.offsets.MonthEnd(0)
            )
            prior_h1 = facts.loc[
                facts["fact_group"].eq("operating_segments")
                & facts["period_type"].eq("interim")
                & facts["period_end"].eq(prior_h1_end.strftime("%Y-%m-%d"))
                & facts["segment"].eq(component)
                & facts["metric"].eq(metric)
            ]
            if prior_h1.empty:
                invalid_ratio_rows += 1
                continue
            prior_h1_value = pd.to_numeric(
                prior_h1.iloc[0].get("value"), errors="coerce"
            )
            if pd.isna(prior_h1_value) or prior_h1_value <= 0:
                invalid_ratio_rows += 1
                continue
            h2_anchor = float(anchor_value) - float(prior_h1_value)
            ratio = h2_anchor / float(prior_h1_value)
            if ratio < 0:
                invalid_ratio_rows += 1
                continue
            for scenario, multiplier in (("low", 0.8), ("base", 1.0), ("high", 1.2)):
                h2_forecast = float(h1_value) * ratio * multiplier
                source_frames = pd.concat(
                    [h1_row, prior_h1, anchor_row], ignore_index=True
                )
                segment_rows.append(
                    {
                        "scenario_id": f"sino_land_h1_segment:{component}:{metric}:{scenario}:{target_fy_end}",
                        "ticker": SINO_LAND_TICKER,
                        "target_fiscal_year_end": target_fy_end,
                        "latest_h1_period_end": h1_period_end,
                        "component": component,
                        "metric": metric,
                        "scope": _text(h1_fact.get("attribution_scope"))
                        or "group_plus_jv_segment",
                        "scenario": scenario,
                        "h1_actual_hkd_m": float(h1_value),
                        "anchor_fiscal_year_end": anchor_end,
                        "anchor_h1_hkd_m": float(prior_h1_value),
                        "anchor_fy_hkd_m": float(anchor_value),
                        "anchor_h1_share_pct": float(prior_h1_value)
                        / float(anchor_value)
                        * 100.0,
                        "anchor_h2_h1_ratio": ratio,
                        "h2_forecast_hkd_m": h2_forecast,
                        "fy_forecast_hkd_m": float(h1_value) + h2_forecast,
                        "model_name": "prior_fy_h1_h2_shape_scenario",
                        "model_status": "research_scenario_one_anchor",
                        "pit_quality": _text(h1_fact.get("availability_quality"))
                        or "unknown",
                        "research_only": True,
                        "source_fact_ids": json.dumps(
                            _source_ids(source_frames), ensure_ascii=False
                        ),
                        "source_urls": json.dumps(
                            _source_urls(source_frames), ensure_ascii=False
                        ),
                        "caveat": "Operating-segment figure includes associates/JVs and is not consolidated turnover. The H2 shape comes from only the immediately prior FY/H1 pair; +/-20% is a sensitivity, not a calibrated confidence interval. Do not sum these rows into the group target.",
                    }
                )

    nowcast = pd.DataFrame(nowcast_rows, columns=NOWCAST_COLUMNS)
    segment_scenarios = pd.DataFrame(segment_rows, columns=SEGMENT_SCENARIO_COLUMNS)
    quality_rows = [
        _quality_row(
            "latest_h1_group_metric_coverage",
            len(nowcast),
            str(len(GROUP_METRICS)),
            "pass" if len(nowcast) == len(GROUP_METRICS) else "warn",
            "group_h1_benchmark",
            "All six current H1 group/component benchmark facts are expected before the baseline is used.",
        ),
        _quality_row(
            "segment_anchor_coverage",
            len(segment_scenarios),
            str(len(SEGMENT_COMPONENTS) * len(SEGMENT_METRICS) * 3),
            (
                "pass"
                if len(segment_scenarios)
                == len(SEGMENT_COMPONENTS) * len(SEGMENT_METRICS) * 3
                else "warn"
            ),
            "segment_shape_scenario",
            "The scenario layer needs one current H1, one prior H1 and one prior FY observation for each segment metric.",
        ),
        _quality_row(
            "segment_scope_mismatch_guard",
            (
                int(segment_scenarios["fy_forecast_hkd_m"].notna().sum())
                if not segment_scenarios.empty
                else 0
            ),
            "segment_rows_not_group_sum",
            "pass",
            "scope_guard",
            "Segment/JV rows remain a separate diagnostic table and are never added to consolidated group revenue or profit.",
        ),
        _quality_row(
            "invalid_h2_ratio_rows",
            invalid_ratio_rows,
            "0",
            "pass" if invalid_ratio_rows == 0 else "warn",
            "segment_shape_scenario",
            "Invalid or negative historical H2/H1 ratios are excluded rather than imputed.",
        ),
        _quality_row(
            "research_only_guard",
            int(
                nowcast.get("research_only", pd.Series(dtype=bool)).eq(True).all()
                and segment_scenarios.get("research_only", pd.Series(dtype=bool))
                .eq(True)
                .all()
            ),
            "1",
            "pass",
            "all_nowcasts_research_only",
            "This module creates transparent baselines and scenarios; it does not create a production or PIT-clean forecast.",
        ),
    ]
    quality = pd.DataFrame(quality_rows, columns=QUALITY_COLUMNS)
    return {
        "nowcast": nowcast,
        "segment_scenarios": segment_scenarios,
        "quality": quality,
    }


def build_sino_land_h1_backtest(
    h1_history: pd.DataFrame | None = None,
    official_facts: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Compare the transparent ``2x H1`` baseline with later FY actuals.

    The group rows deliberately use consolidated annual turnover/profit facts.
    The segment rows are a separate diagnostic scope and match the segment
    table's associates/JVs-inclusive figures to the same annual segment facts.
    They must never be summed together or treated as consolidated revenue.
    """
    history = h1_history.copy() if h1_history is not None else pd.DataFrame()
    facts = (
        official_facts.copy()
        if official_facts is not None
        else build_sino_land_financial_facts()
    )
    if history.empty or facts.empty:
        quality = pd.DataFrame(
            [
                _quality_row(
                    "group_backtest_coverage",
                    0,
                    "15",
                    "warn",
                    "h1_historical_backtest",
                    "Historical H1 facts and annual facts are required before the benchmark can be evaluated.",
                )
            ],
            columns=QUALITY_COLUMNS,
        )
        return {
            "backtest": pd.DataFrame(columns=BACKTEST_COLUMNS),
            "quality": quality,
        }

    history["period_end_dt"] = pd.to_datetime(history["period_end"], errors="coerce")
    facts["period_end_dt"] = pd.to_datetime(facts["period_end"], errors="coerce")
    history["target_fiscal_year_end"] = (
        history["period_end_dt"] + pd.DateOffset(months=6)
    ).dt.to_period("M").dt.to_timestamp("M").dt.strftime("%Y-%m-%d")

    rows: list[dict[str, Any]] = []

    def append_backtest_row(
        h1_row: pd.Series,
        annual_row: pd.Series,
        *,
        backtest_scope: str,
        component: str | None,
        metric: str,
        model_name: str,
        caveat: str,
        forecast_value: float | None = None,
        supporting_rows: list[pd.Series] | None = None,
        reference_pair_count: int = 0,
    ) -> None:
        h1_value = pd.to_numeric(h1_row.get("value"), errors="coerce")
        actual_value = pd.to_numeric(annual_row.get("value"), errors="coerce")
        if pd.isna(h1_value) or pd.isna(actual_value):
            return
        forecast = (
            float(h1_value) * 2.0
            if forecast_value is None
            else float(forecast_value)
        )
        error = forecast - float(actual_value)
        error_pct = None if float(actual_value) == 0 else error / float(actual_value) * 100.0
        rows.append(
            {
                "backtest_id": f"sino_land_h1_backtest:{backtest_scope}:{component or 'group'}:{metric}:{annual_row['period_end']}:{model_name}",
                "ticker": SINO_LAND_TICKER,
                "fiscal_year_end": str(annual_row["period_end"]),
                "h1_period_end": str(h1_row["period_end"]),
                "backtest_scope": backtest_scope,
                "component": component,
                "metric": metric,
                "scope": (
                    _text(h1_row.get("attribution_scope"))
                    if backtest_scope == "operating_segment"
                    else _text(h1_row.get("geography_scope"))
                )
                or _text(h1_row.get("geography_scope"))
                or "unknown",
                "h1_actual_hkd_m": float(h1_value),
                "actual_fy_hkd_m": float(actual_value),
                "forecast_fy_hkd_m": forecast,
                "error_hkd_m": error,
                "error_pct": error_pct,
                "abs_error_pct": None if error_pct is None else abs(error_pct),
                "model_name": model_name,
                "reference_pair_count": reference_pair_count,
                "pit_quality": "release_date_verified_time_unverified",
                "research_only": True,
                "source_fact_ids": json.dumps(
                    _source_ids(
                        pd.DataFrame([h1_row, annual_row] + (supporting_rows or []))
                    ),
                    ensure_ascii=False,
                ),
                "source_urls": json.dumps(
                    _source_urls(
                        pd.DataFrame([h1_row, annual_row] + (supporting_rows or []))
                    ),
                    ensure_ascii=False,
                ),
                "caveat": caveat,
            }
        )

    group_metric_map = {
        "consolidated_revenue": "turnover",
        "underlying_profit_attributable": "underlying_profit_attributable",
        "profit_attributable": "profit_attributable",
    }
    group_history = history.loc[
        history["fact_group"].isin(["interim_actuals", "group_summary"])
        & history["metric"].isin(group_metric_map)
    ]
    annual_group = facts.loc[
        facts["fact_group"].eq("group_summary")
        & facts["period_type"].eq("annual")
    ]
    for _, h1_row in group_history.iterrows():
        annual_metric = group_metric_map[str(h1_row["metric"])]
        annual_rows = annual_group.loc[
            annual_group["period_end"].eq(h1_row["target_fiscal_year_end"])
            & annual_group["metric"].eq(annual_metric)
        ]
        if annual_rows.empty:
            continue
        append_backtest_row(
            h1_row,
            annual_rows.iloc[0],
            backtest_scope="consolidated_group",
            component=None,
            metric=str(h1_row["metric"]),
            model_name="naive_2x_h1",
            caveat="Historical benchmark only: consolidated H1 actual annualised at 2x and compared with the later reported FY actual. This does not use information published after the H1 report, but report release time is not verified.",
        )

    # A second benchmark uses the median of the available prior H1/FY shares.
    # It is intentionally a non-stationarity diagnostic rather than a claim
    # that H1/FY is stable.  The first historical pair has no prior share and
    # is therefore omitted; later rows use at most the three immediately
    # preceding pairs, all of which would have been known at that H1 date.
    group_pairs: list[dict[str, Any]] = []
    for _, h1_row in group_history.iterrows():
        annual_metric = group_metric_map[str(h1_row["metric"])]
        annual_rows = annual_group.loc[
            annual_group["period_end"].eq(h1_row["target_fiscal_year_end"])
            & annual_group["metric"].eq(annual_metric)
        ]
        if annual_rows.empty:
            continue
        annual_row = annual_rows.iloc[0]
        h1_value = pd.to_numeric(h1_row.get("value"), errors="coerce")
        actual_value = pd.to_numeric(annual_row.get("value"), errors="coerce")
        if (
            pd.isna(h1_value)
            or pd.isna(actual_value)
            or float(h1_value) <= 0
            or float(actual_value) <= 0
        ):
            continue
        group_pairs.append(
            {
                "metric": str(h1_row["metric"]),
                "fiscal_year_end": str(annual_row["period_end"]),
                "h1_row": h1_row,
                "annual_row": annual_row,
                "share": float(h1_value) / float(actual_value),
            }
        )
    for pair in group_pairs:
        prior_pairs = [
            candidate
            for candidate in group_pairs
            if candidate["metric"] == pair["metric"]
            and candidate["fiscal_year_end"] < pair["fiscal_year_end"]
        ]
        prior_pairs = sorted(
            prior_pairs, key=lambda candidate: candidate["fiscal_year_end"]
        )[-3:]
        if not prior_pairs:
            continue
        share = float(pd.Series([candidate["share"] for candidate in prior_pairs]).median())
        if share <= 0:
            continue
        h1_value = float(pair["h1_row"]["value"])
        append_backtest_row(
            pair["h1_row"],
            pair["annual_row"],
            backtest_scope="consolidated_group",
            component=None,
            metric=pair["metric"],
            model_name="prior_h1_share_median",
            forecast_value=h1_value / share,
            reference_pair_count=len(prior_pairs),
            supporting_rows=[
                row
                for candidate in prior_pairs
                for row in (candidate["h1_row"], candidate["annual_row"])
            ],
            caveat=f"Historical benchmark only: FY forecast is H1 actual divided by the median H1/FY share from the prior {len(prior_pairs)} available pair(s). The share is project-mix driven and may be non-stationary; this is not a calibrated seasonal factor or PIT-clean score.",
        )

    segment_history = history.loc[
        history["fact_group"].eq("operating_segments")
        & history["segment"].isin(SEGMENT_COMPONENTS)
        & history["metric"].isin(SEGMENT_METRICS)
    ]
    annual_segments = facts.loc[
        facts["fact_group"].eq("operating_segments")
        & facts["period_type"].eq("annual")
        & facts["segment"].isin(SEGMENT_COMPONENTS)
        & facts["metric"].isin(SEGMENT_METRICS)
    ]
    for _, h1_row in segment_history.iterrows():
        annual_rows = annual_segments.loc[
            annual_segments["period_end"].eq(h1_row["target_fiscal_year_end"])
            & annual_segments["segment"].eq(h1_row["segment"])
            & annual_segments["metric"].eq(h1_row["metric"])
        ]
        if annual_rows.empty:
            continue
        append_backtest_row(
            h1_row,
            annual_rows.iloc[0],
            backtest_scope="operating_segment",
            component=str(h1_row["segment"]),
            metric=str(h1_row["metric"]),
            model_name="naive_2x_h1_segment",
            caveat="Diagnostic segment benchmark only. The segment figure includes associates/JVs and is matched to the same annual segment scope; it is not consolidated turnover and must not be added to group rows.",
        )

    backtest = pd.DataFrame(rows, columns=BACKTEST_COLUMNS)
    if not backtest.empty:
        backtest = backtest.sort_values(
            ["fiscal_year_end", "backtest_scope", "component", "metric"],
            na_position="last",
        ).reset_index(drop=True)
    group_rows = backtest.loc[backtest["backtest_scope"].eq("consolidated_group")]
    segment_rows = backtest.loc[backtest["backtest_scope"].eq("operating_segment")]
    naive_group_rows = group_rows.loc[group_rows["model_name"].eq("naive_2x_h1")]
    prior_share_group_rows = group_rows.loc[
        group_rows["model_name"].eq("prior_h1_share_median")
    ]
    prior_share_three_year_rows = prior_share_group_rows.loc[
        prior_share_group_rows["reference_pair_count"].eq(3)
    ]
    expected_group_rows = len(group_metric_map) * 5
    expected_prior_share_rows = len(group_metric_map) * 4
    expected_prior_share_three_year_rows = len(group_metric_map) * 2
    expected_segment_rows = len(SEGMENT_COMPONENTS) * len(SEGMENT_METRICS) * 4
    group_scope_ok = (
        not bool(
            group_rows["scope"]
            .astype(str)
            .str.contains("segment|associate|joint|jv", case=False, regex=True)
            .any()
        )
        if not group_rows.empty
        else True
    )
    segment_scope_ok = (
        segment_rows["scope"]
        .astype(str)
        .str.contains("associate|joint|jv", case=False, regex=True)
        .all()
        if not segment_rows.empty
        else True
    )
    quality_rows = [
        _quality_row(
            "group_backtest_coverage",
            len(naive_group_rows),
            str(expected_group_rows),
            "pass" if len(naive_group_rows) == expected_group_rows else "warn",
            "h1_historical_backtest",
            "Expected FY2021-FY2025 for three consolidated metrics; FY2026 is intentionally excluded because its FY actual is not yet available.",
        ),
        _quality_row(
            "prior_h1_share_backtest_coverage",
            len(prior_share_group_rows),
            str(expected_prior_share_rows),
            "pass"
            if len(prior_share_group_rows) == expected_prior_share_rows
            else "warn",
            "h1_prior_share_benchmark",
            "The prior-share benchmark starts once at least one prior H1/FY pair exists; it uses up to three preceding pairs and intentionally has no FY2021 row.",
        ),
        _quality_row(
            "prior_three_year_share_backtest_coverage",
            len(prior_share_three_year_rows),
            str(expected_prior_share_three_year_rows),
            "pass"
            if len(prior_share_three_year_rows)
            == expected_prior_share_three_year_rows
            else "warn",
            "h1_prior_3y_share_benchmark",
            "The strict three-year subset is the only prior-share slice suitable for comparison; shorter one/two-pair slices remain diagnostic and are not treated as stable seasonality.",
        ),
        _quality_row(
            "segment_backtest_coverage",
            len(segment_rows),
            str(expected_segment_rows),
            "pass" if len(segment_rows) == expected_segment_rows else "warn",
            "h1_segment_diagnostic_backtest",
            "Expected FY2022-FY2025 for six operating segments and two segment metrics; annual segment history starts in FY2022.",
        ),
        _quality_row(
            "backtest_scope_guard",
            int(group_scope_ok and segment_scope_ok),
            "1",
            "pass" if group_scope_ok and segment_scope_ok else "fail",
            "scope_guard",
            "Consolidated group and associates/JVs-inclusive segment rows are kept in separate scopes.",
        ),
        _quality_row(
            "backtest_duplicate_guard",
            int(backtest["backtest_id"].is_unique) if not backtest.empty else 1,
            "1",
            "pass" if backtest.empty or backtest["backtest_id"].is_unique else "fail",
            "data_integrity",
            "Each H1/FY/metric/scope combination should have one benchmark row.",
        ),
        _quality_row(
            "backtest_research_only_guard",
            int(backtest["research_only"].eq(True).all()) if not backtest.empty else 1,
            "1",
            "pass",
            "all_h1_backtests_research_only",
            "Historical comparison is transparent research output, not a production PIT-clean forecast score.",
        ),
    ]
    return {
        "backtest": backtest,
        "quality": pd.DataFrame(quality_rows, columns=QUALITY_COLUMNS),
    }


def build_sino_land_h1_residential_h2_scenario(
    schedule: pd.DataFrame | None,
    *,
    latest_h1_period_end: str,
    target_fiscal_year_end: str,
) -> dict[str, pd.DataFrame]:
    """Aggregate PIT-filtered residential contract cohorts for H2.

    The schedule is a research-only contract-to-handover proxy.  Cohorts are
    restricted to sale months on or before the H1 period end so that the
    current H1 nowcast cannot see later transactions.  The output is kept in
    attributable contract-value units (HKD million), never relabelled as
    accounting property-sales revenue.
    """
    frame = schedule.copy() if schedule is not None else pd.DataFrame()
    quality_prefix = "sino_land_h1_residential_h2"
    if frame.empty:
        quality = pd.DataFrame(
            [
                _quality_row(
                    "h2_schedule_coverage",
                    0,
                    "1",
                    "warn",
                    "residential_h2_contract_proxy",
                    "A non-empty residential recognition schedule is required before an H2 cohort proxy can be built.",
                    quality_prefix=quality_prefix,
                )
            ],
            columns=QUALITY_COLUMNS,
        )
        return {
            "scenario": pd.DataFrame(columns=RESIDENTIAL_H2_COLUMNS),
            "quality": quality,
        }

    required = {
        "sale_period",
        "recognized_period_low",
        "recognized_period_base",
        "recognized_period_high",
        "contract_sales_value_gross_hkd",
        "attributable_contract_value_low_hkd",
        "attributable_contract_value_base_hkd",
        "attributable_contract_value_high_hkd",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        quality = pd.DataFrame(
            [
                _quality_row(
                    "h2_schedule_schema",
                    json.dumps(missing, ensure_ascii=False),
                    "[]",
                    "fail",
                    "residential_h2_contract_proxy",
                    "The recognition schedule is missing required cohort/date/value columns; no H2 proxy is produced.",
                    quality_prefix=quality_prefix,
                )
            ],
            columns=QUALITY_COLUMNS,
        )
        return {
            "scenario": pd.DataFrame(columns=RESIDENTIAL_H2_COLUMNS),
            "quality": quality,
        }

    cutoff = pd.to_datetime(latest_h1_period_end, errors="coerce")
    target_end = pd.to_datetime(target_fiscal_year_end, errors="coerce")
    if pd.isna(cutoff) or pd.isna(target_end):
        raise ValueError("latest_h1_period_end and target_fiscal_year_end must be valid dates")
    cutoff = cutoff.to_period("M").to_timestamp("M")
    h2_start = cutoff + pd.offsets.MonthBegin(1)
    frame["sale_period_dt"] = pd.to_datetime(frame["sale_period"], errors="coerce")
    frame["sale_period_dt"] = frame["sale_period_dt"].dt.to_period("M").dt.to_timestamp()
    for column in (
        "recognized_period_low",
        "recognized_period_base",
        "recognized_period_high",
    ):
        frame[f"{column}_dt"] = pd.to_datetime(frame[column], errors="coerce")
        frame[f"{column}_dt"] = frame[f"{column}_dt"].dt.to_period("M").dt.to_timestamp()
    invalid_sale_date_rows = int(frame["sale_period_dt"].isna().sum())
    recognition_date_columns = [
        "recognized_period_low_dt",
        "recognized_period_base_dt",
        "recognized_period_high_dt",
    ]
    missing_recognition_date_rows = int(
        frame[recognition_date_columns].isna().any(axis=1).sum()
    )
    frame = frame.loc[frame["sale_period_dt"].notna()].copy()
    cutoff_rows = frame.loc[frame["sale_period_dt"].le(cutoff)].copy()

    def schedule_urls(rows: pd.DataFrame) -> str:
        urls: set[str] = set()
        for value in rows.get("source_urls", pd.Series(dtype=object)).dropna():
            if isinstance(value, (list, tuple, set)):
                values = value
            else:
                try:
                    decoded = json.loads(str(value))
                    values = decoded if isinstance(decoded, list) else [decoded]
                except (TypeError, ValueError, json.JSONDecodeError):
                    values = [value]
            urls.update(
                str(item).strip()
                for item in values
                if _text(item) and str(item).strip().startswith(("http://", "https://"))
            )
        return json.dumps(sorted(urls), ensure_ascii=False)

    rows: list[dict[str, Any]] = []
    scenario_columns = {
        "low": "attributable_contract_value_low_hkd",
        "base": "attributable_contract_value_base_hkd",
        "high": "attributable_contract_value_high_hkd",
    }

    def append_row(
        selected: pd.DataFrame,
        *,
        scenario: str,
        scope_level: str,
        development_id: str | None,
        project_label: str | None,
    ) -> None:
        recognition_column = f"recognized_period_{scenario}_dt"
        selected = selected.loc[
            selected[recognition_column].ge(h2_start)
            & selected[recognition_column].le(target_end)
        ].copy()
        value_column = scenario_columns[scenario]
        gross = pd.to_numeric(
            selected.get("contract_sales_value_gross_hkd", pd.Series(dtype=float)),
            errors="coerce",
        )
        attributable = pd.to_numeric(
            selected.get(value_column, pd.Series(dtype=float)), errors="coerce"
        )
        units = pd.to_numeric(
            selected.get("contract_units_gross", pd.Series(dtype=float)), errors="coerce"
        )
        rows.append(
            {
                "scenario_id": f"sino_land_h1_residential_h2:{scope_level}:{development_id or 'portfolio'}:{scenario}:{target_fiscal_year_end}",
                "ticker": SINO_LAND_TICKER,
                "scope_level": scope_level,
                "srpe_development_id": development_id,
                "project_label": project_label,
                "scenario": scenario,
                "target_fiscal_year_end": target_fiscal_year_end,
                "h1_period_end": cutoff.strftime("%Y-%m-%d"),
                "cohort_cutoff_period": cutoff.strftime("%Y-%m-%d"),
                "recognition_period_start": (
                    selected[recognition_column].min().strftime("%Y-%m-%d")
                    if not selected.empty
                    else None
                ),
                "recognition_period_end": (
                    selected[recognition_column].max().strftime("%Y-%m-%d")
                    if not selected.empty
                    else None
                ),
                "cohort_rows": int(len(selected)),
                "cohort_units_gross": int(units.sum(min_count=1))
                if units.notna().any()
                else 0,
                "contract_value_gross_hkd_m": float(gross.sum(min_count=1) / 1e6)
                if gross.notna().any()
                else 0.0,
                "attributable_contract_value_hkd_m": float(
                    attributable.sum(min_count=1) / 1e6
                )
                if attributable.notna().any()
                else 0.0,
                "model_name": "pit_filtered_h2_contract_attribution_proxy",
                "pit_quality": "h1_cutoff_filtered_research_only",
                "research_only": True,
                "source_urls": schedule_urls(selected),
                "caveat": "This is attributable SRPE contract value allocated by an estimated/observed handover lag, not accounting revenue. Sale cohorts after the H1 cutoff are excluded; no claim is made that the proxy equals the H2 property-sales line.",
            }
        )

    for scenario in scenario_columns:
        append_row(
            cutoff_rows,
            scenario=scenario,
            scope_level="portfolio",
            development_id=None,
            project_label="All eligible Sino Hong Kong residential phases",
        )
        if "srpe_development_id" not in cutoff_rows.columns:
            continue
        for development_id, project_rows in cutoff_rows.groupby(
            "srpe_development_id", dropna=False
        ):
            development_id_text = _text(development_id)
            if development_id_text is None:
                continue
            project_label = (
                _text(project_rows.get("project_label", pd.Series(dtype=object)).iloc[0])
                if "project_label" in project_rows.columns and not project_rows.empty
                else None
            )
            append_row(
                project_rows,
                scenario=scenario,
                scope_level="phase",
                development_id=development_id_text,
                project_label=project_label,
            )

    scenario_frame = pd.DataFrame(rows, columns=RESIDENTIAL_H2_COLUMNS)
    if not scenario_frame.empty:
        scenario_frame = scenario_frame.sort_values(
            ["scope_level", "srpe_development_id", "scenario"],
            na_position="first",
        ).reset_index(drop=True)
    portfolio = scenario_frame.loc[scenario_frame["scope_level"].eq("portfolio")]
    selected_rows_by_scenario = {
        scenario: int(
            portfolio.loc[portfolio["scenario"].eq(scenario), "cohort_rows"].sum()
        )
        for scenario in scenario_columns
    }
    value_negative = (
        pd.to_numeric(
            scenario_frame["attributable_contract_value_hkd_m"], errors="coerce"
        )
        .lt(0)
        .any()
        if not scenario_frame.empty
        else False
    )
    quality_rows = [
        _quality_row(
            "h2_schedule_schema",
            0,
            "[]",
            "pass",
            "residential_h2_contract_proxy",
            "All required recognition-cohort columns are present.",
            quality_prefix=quality_prefix,
        ),
        _quality_row(
            "h2_cutoff_guard",
            int(
                frame.loc[frame["sale_period_dt"].gt(cutoff)].shape[0]
                + cutoff_rows.shape[0]
                == len(frame)
            ),
            "1",
            "pass"
            if frame.loc[frame["sale_period_dt"].gt(cutoff)].shape[0]
            + cutoff_rows.shape[0]
            == len(frame)
            else "fail",
            "pit_cutoff",
            "Every cohort is either included on/before the H1 cutoff or explicitly excluded as a later sale; later transactions cannot enter this H1 nowcast.",
            quality_prefix=quality_prefix,
        ),
        _quality_row(
            "h2_sale_date_guard",
            invalid_sale_date_rows,
            "0",
            "pass" if invalid_sale_date_rows == 0 else "fail",
            "data_integrity",
            "Cohorts with malformed sale periods cannot be assigned to the H1 information set and are surfaced rather than silently treated as pre-cutoff.",
            quality_prefix=quality_prefix,
        ),
        _quality_row(
            "h2_scenario_coverage",
            int(len(portfolio)),
            "3",
            "pass" if len(portfolio) == 3 else "warn",
            "residential_h2_contract_proxy",
            "One portfolio row is expected for each low/base/high stake scenario.",
            quality_prefix=quality_prefix,
        ),
        _quality_row(
            "h2_negative_value_guard",
            int(not value_negative),
            "1",
            "pass" if not value_negative else "fail",
            "data_integrity",
            "Negative contract attribution values are not economically valid and are not imputed.",
            quality_prefix=quality_prefix,
        ),
        _quality_row(
            "h2_recognition_date_guard",
            missing_recognition_date_rows,
            "0",
            "pass" if missing_recognition_date_rows == 0 else "fail",
            "data_integrity",
            "Every cohort must have low/base/high recognition periods; malformed dates are excluded from the proxy and surfaced here.",
            quality_prefix=quality_prefix,
        ),
        _quality_row(
            "h2_research_only_guard",
            int(
                scenario_frame.get("research_only", pd.Series(dtype=bool))
                .eq(True)
                .all()
            ),
            "1",
            "pass",
            "all_h2_rows_research_only",
            "The H2 layer remains a contract attribution proxy and is not added to the consolidated revenue baseline.",
            quality_prefix=quality_prefix,
        ),
    ]
    # Keep the per-scenario counts visible in the audit without adding a
    # second schema solely for diagnostics.
    quality_rows.append(
        _quality_row(
            "h2_cutoff_cohort_rows_by_scenario",
            sum(selected_rows_by_scenario.values()),
            "nonnegative",
            "pass",
            "coverage_diagnostic",
            "Counts are the post-cutoff, in-window recognition cohorts used for each scenario: "
            + json.dumps(selected_rows_by_scenario, ensure_ascii=False),
            quality_prefix=quality_prefix,
        )
    )
    return {
        "scenario": scenario_frame,
        "quality": pd.DataFrame(quality_rows, columns=QUALITY_COLUMNS),
    }


def run_sino_land_h1_nowcast(
    *,
    persist: bool = True,
    official_facts: pd.DataFrame | None = None,
    h1_history: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build and optionally persist nowcast, scenario and H1/FY backtest tables."""
    run_id = f"sino-land-h1-nowcast-{uuid.uuid4()}"
    frames = build_sino_land_h1_nowcast(official_facts)
    history = (
        h1_history.copy()
        if h1_history is not None
        else load_latest_normalized(H1_HISTORY_DATASET)
    )
    backtest_frames = build_sino_land_h1_backtest(history, official_facts)
    latest_h1_period_end = (
        str(frames["nowcast"]["latest_h1_period_end"].iloc[0])
        if not frames["nowcast"].empty
        else None
    )
    target_fiscal_year_end = (
        str(frames["nowcast"]["target_fiscal_year_end"].iloc[0])
        if not frames["nowcast"].empty
        else None
    )
    residential_schedule = load_latest_normalized(SCHEDULE_DATASET)
    if latest_h1_period_end and target_fiscal_year_end:
        residential_h2_frames = build_sino_land_h1_residential_h2_scenario(
            residential_schedule,
            latest_h1_period_end=latest_h1_period_end,
            target_fiscal_year_end=target_fiscal_year_end,
        )
    else:
        residential_h2_frames = {
            "scenario": pd.DataFrame(columns=RESIDENTIAL_H2_COLUMNS),
            "quality": pd.DataFrame(columns=QUALITY_COLUMNS),
        }
    normalized: dict[str, Any] = {}
    if persist:
        source_urls = [SINO_ANNUAL_REPORT_2025_URL, SINO_INTERIM_REPORT_2025_26_URL]
        raw_snapshots = list(history.attrs.get("raw_snapshots") or [])
        if not history.empty and "source_url" in history.columns:
            source_urls.extend(
                sorted(
                    {
                        str(value)
                        for value in history["source_url"].dropna().tolist()
                        if _text(value)
                    }
                )
            )
        source_urls = sorted(set(source_urls))
        lineage = {
            "lineage_type": "sino_land_h1_nowcast_baseline",
            "run_id": run_id,
            "ticker": SINO_LAND_TICKER,
            "source_urls": source_urls,
            "research_only": True,
            "model_fit_performed": False,
            "scope_guard": "segment scenarios are not added to consolidated group targets",
        }
        for dataset, frame in (
            (NOWCAST_DATASET, frames["nowcast"]),
            (SEGMENT_SCENARIO_DATASET, frames["segment_scenarios"]),
            (QUALITY_DATASET, frames["quality"]),
            (BACKTEST_DATASET, backtest_frames["backtest"]),
            (BACKTEST_QUALITY_DATASET, backtest_frames["quality"]),
            (RESIDENTIAL_H2_DATASET, residential_h2_frames["scenario"]),
            (RESIDENTIAL_H2_QUALITY_DATASET, residential_h2_frames["quality"]),
        ):
            normalized[dataset] = save_normalized_dataset(
                dataset,
                frame,
                run_id=run_id,
                raw_snapshots=raw_snapshots,
                source_urls=source_urls,
                lineage_metadata=lineage,
            )
    return {
        "run_id": run_id,
        "ticker": SINO_LAND_TICKER,
        "nowcast_rows": int(len(frames["nowcast"])),
        "segment_scenario_rows": int(len(frames["segment_scenarios"])),
        "quality_rows": int(len(frames["quality"])),
        "backtest_rows": int(len(backtest_frames["backtest"])),
        "backtest_quality_rows": int(len(backtest_frames["quality"])),
        "residential_h2_rows": int(len(residential_h2_frames["scenario"])),
        "residential_h2_quality_rows": int(len(residential_h2_frames["quality"])),
        "normalized": normalized,
        "model_fit_performed": False,
        "research_only": True,
    }
