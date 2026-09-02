"""Build canonical JSON artifact and Astro status for HK REIT Sector Monitor.

Six HK-listed REITs, all sourced from each trust's own investor-relations
disclosures (see .claude/skills/data-source-deep-dive/references/reit-*.md
for the verification trail per source):

  - Link REIT (0823.HK), Champion REIT (2778.HK), Fortune REIT (0778.HK),
    Prosperity REIT (0808.HK), Sunlight REIT (0435.HK): office/retail
    portfolios reporting NAV/unit, DPU, occupancy, and rental reversion.
  - Regal REIT (1881.HK): a hotel-portfolio REIT reporting NAV/unit and
    DPU like the others, but hotel KPIs (occupancy, ADR, RevPAR) instead
    of office/retail occupancy and rental reversion -- its metric set is
    fundamentally different and is never forced into the same chart as
    the other five.

DPU is a genuinely nil/zero value in some periods for some REITs (Regal
reported a nil per-unit distribution in 1H2025 -- a real disclosed
number, not a fetch failure; see reit-regalreit-01881-findings.md). Any
period/year-over-year comparison here must therefore guard against
division by zero and return `None` rather than raising.
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

from src.hk_reit.sources.linkreit_fundamentals import fetch_linkreit_fundamentals
from src.hk_reit.sources.championreit_fundamentals import fetch_championreit_fundamentals
from src.hk_reit.sources.fortunereit_fundamentals import fetch_fortunereit_fundamentals
from src.hk_reit.sources.prosperityreit_fundamentals import fetch_prosperityreit_fundamentals
from src.hk_reit.sources.sunlightreit_fundamentals import fetch_sunlightreit_fundamentals
from src.hk_reit.sources.regalreit_fundamentals import fetch_regalreit_fundamentals
from src.hk_reit.sources.reit_price import fetch_reit_spot_quotes, fetch_reit_price_history


PUBLIC_SOURCES = {
    "cross_source": {
        "id": "cross_source",
        "label": "Cross-source HK REIT official IR comparison",
        "path": "sources/cross_source.sql",
        "query": {
            "engine": "pandas",
            "language": "Python",
            "description": "Comparison assembled from the six trusts' own investor-relations disclosures; each underlying series retains its individual source ID.",
        },
    },
    "reit_price_akshare": {
        "id": "reit_price_akshare",
        "label": "Hong Kong REITs Daily Spot Quotes & History (akshare)",
        "href": "https://www.hkex.com.hk/",
        "path": "sources/reit_price.sql",
        "query": {
            "engine": "akshare.stock_hk_spot_em",
            "url": "https://www.hkex.com.hk/",
            "language": "API",
            "description": "Daily spot price quotes, percentage change, and OHLC daily history for all 6 HK REITs.",
        },
    },
    "linkreit_fundamentals": {
        "id": "linkreit_fundamentals",
        "label": "Link REIT (0823.HK) Investor Relations Disclosures",
        "href": "https://www.linkreit.com/en/investor-relations/",
        "path": "sources/linkreit_fundamentals.sql",
        "query": {
            "engine": "official IR PDF + HTML",
            "url": "https://www.linkreit.com/en/investor-relations/",
            "language": "PDF/HTML",
            "description": "NAV per unit, DPU, occupancy rate, and rental reversion rate for Link REIT.",
        },
    },
    "championreit_fundamentals": {
        "id": "championreit_fundamentals",
        "label": "Champion REIT (2778.HK) Financial Disclosures",
        "href": "https://www.championreit.com/en/investor-relations/",
        "path": "sources/championreit_fundamentals.sql",
        "query": {
            "engine": "official IR disclosures",
            "url": "https://www.championreit.com/en/investor-relations/",
            "language": "PDF/HTML",
            "description": "Three Garden Road & Langham Place office/retail NAV/unit, DPU, occupancy, and reversion.",
        },
    },
    "fortunereit_fundamentals": {
        "id": "fortunereit_fundamentals",
        "label": "Fortune REIT (0778.HK) Financial Disclosures",
        "href": "https://www.fortunereit.com/en/investor-relations/",
        "path": "sources/fortunereit_fundamentals.sql",
        "query": {
            "engine": "official IR disclosures",
            "url": "https://www.fortunereit.com/en/investor-relations/",
            "language": "PDF/HTML",
            "description": "Suburban HK retail portfolio NAV/unit, DPU, occupancy, and rental reversion.",
        },
    },
    "prosperityreit_fundamentals": {
        "id": "prosperityreit_fundamentals",
        "label": "Prosperity REIT (0808.HK) Financial Disclosures",
        "href": "https://www.prosperityreit.com/en/investor-relations/",
        "path": "sources/prosperityreit_fundamentals.sql",
        "query": {
            "engine": "official IR disclosures",
            "url": "https://www.prosperityreit.com/en/investor-relations/",
            "language": "PDF/HTML",
            "description": "Decentralized office and industrial portfolio NAV/unit, DPU, occupancy, and reversion.",
        },
    },
    "sunlightreit_fundamentals": {
        "id": "sunlightreit_fundamentals",
        "label": "Sunlight REIT (0435.HK) Financial Disclosures",
        "href": "https://www.sunlightreit.com/en/investor-relations/",
        "path": "sources/sunlightreit_fundamentals.sql",
        "query": {
            "engine": "official IR disclosures",
            "url": "https://www.sunlightreit.com/en/investor-relations/",
            "language": "PDF/HTML",
            "description": "Office and retail portfolio NAV/unit, DPU, occupancy, and rental reversion.",
        },
    },
    "regalreit_fundamentals": {
        "id": "regalreit_fundamentals",
        "label": "Regal REIT (1881.HK) Hotel Performance Disclosures",
        "href": "https://www.regalreit.com/en/investor-relations/",
        "path": "sources/regalreit_fundamentals.sql",
        "query": {
            "engine": "official Interim/Annual Report PDF",
            "url": "https://www.regalreit.com/annualrpt.html?if=yes",
            "language": "PDF",
            "description": "Hotel portfolio KPIs: occupancy (%), average daily rate (ADR, HK$), RevPAR (HK$), DPU, and NAV/unit.",
        },
    },
}

# (dataset key, ticker, reit_name, PUBLIC_SOURCES key, is_hotel)
REIT_META: list[tuple[str, str, str, str, bool]] = [
    ("linkreit", "0823.HK", "Link REIT", "linkreit_fundamentals", False),
    ("championreit", "2778.HK", "Champion REIT", "championreit_fundamentals", False),
    ("fortunereit", "0778.HK", "Fortune REIT", "fortunereit_fundamentals", False),
    ("prosperityreit", "0808.HK", "Prosperity REIT", "prosperityreit_fundamentals", False),
    ("sunlightreit", "0435.HK", "Sunlight REIT", "sunlightreit_fundamentals", False),
    ("regalreit", "1881.HK", "Regal REIT", "regalreit_fundamentals", True),
]

# `cross_source` is a derived provenance label for multi-REIT widgets, not an
# additional upstream feed. Keep it out of live/total source counts.
UPSTREAM_SOURCE_IDS = tuple(
    source_id for _key, _ticker, _name, source_id, _is_hotel in REIT_META
) + ("reit_price_akshare",)

# Chart-legend-only shorthand for the two longest full names (see
# reit_spot_price_history_chart construction below for why this exists).
_REIT_LEGEND_SHORT_NAMES = {
    "Champion REIT": "Champ",
    "Prosperity REIT": "Prosper",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _records_json_safe(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records (NaN/NaT -> null, dates -> ISO strings)."""
    selected = frame.copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Parse `date` to datetime and sort ascending.

    The per-REIT fetchers each return rows in whatever order their source
    page/PDF lists them in -- some newest-first, some oldest-first, none
    guaranteed -- and `date` comes back as plain ISO strings, not a
    datetime dtype. Every downstream `iloc[-1]`/`iloc[-2]` "latest"/"prior"
    lookup and every `.strftime()` call depends on this normalization
    having run first.
    """
    if df.empty or "date" not in df.columns:
        return df
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result = result.dropna(subset=["date"])
    return result.sort_values("date").reset_index(drop=True)


def _num(row: pd.Series, column: str) -> float | None:
    if row is None or column not in row.index:
        return None
    value = row[column]
    return float(value) if pd.notna(value) else None


def _ratio_change(latest: float | None, prior: float | None) -> float | None:
    """Period-over-period ratio change, guarded against zero/None division.

    REIT distributions can legitimately be nil in a given period (e.g. Regal
    REIT reported a nil DPU in 1H2025 -- a genuine disclosed figure, not a
    fetch failure). A zero or missing prior value must yield `None`, not a
    ZeroDivisionError.
    """
    if latest is None or prior is None or prior == 0:
        return None
    return round(latest / prior - 1, 6)


def _reit_kpi(df: pd.DataFrame, is_hotel: bool) -> dict[str, Any]:
    if df.empty:
        base = {
            "nav_per_unit_hkd": None,
            "dpu_hkd": None,
            "dpu_period_change": None,
            "observation_date": None,
            "period": None,
        }
        if is_hotel:
            base.update({"hotel_occupancy_pct": None, "average_daily_rate_hkd": None, "revpar_hkd": None})
        else:
            base.update({"occupancy_pct": None, "rental_reversion_pct": None})
        return base

    latest = df.iloc[-1]
    prior = df.iloc[-2] if len(df) > 1 else None
    nav = _num(latest, "nav_per_unit_hkd")
    dpu = _num(latest, "dpu_hkd")
    prior_dpu = _num(prior, "dpu_hkd") if prior is not None else None

    kpi: dict[str, Any] = {
        "nav_per_unit_hkd": nav,
        "dpu_hkd": dpu,
        "dpu_period_change": _ratio_change(dpu, prior_dpu),
        "observation_date": latest["date"].strftime("%Y-%m-%d") if pd.notna(latest.get("date")) else None,
        "period": latest.get("period"),
    }
    if is_hotel:
        kpi.update(
            {
                "hotel_occupancy_pct": _num(latest, "hotel_occupancy_pct"),
                "average_daily_rate_hkd": _num(latest, "average_daily_rate_hkd"),
                "revpar_hkd": _num(latest, "revpar_hkd"),
            }
        )
    else:
        kpi.update(
            {
                "occupancy_pct": _num(latest, "occupancy_pct"),
                "rental_reversion_pct": _num(latest, "rental_reversion_pct"),
            }
        )
    return kpi


def _series_history(df: pd.DataFrame, series_label: str, value_column: str) -> list[dict[str, Any]]:
    """Long-format {date, month, series, value} rows for a multi-series line chart.

    `month` is a "YYYY-MM" string (month-granularity). The portable-chart
    plugin's date-axis formatter always includes the year for
    month-granularity values but omits it by default for day-granularity
    ones, so multi-period charts encode their x axis against `month` to
    stay unambiguous across years (reporting periods here are always
    distinct months, e.g. HY/FY period-end dates, so this loses no
    information).
    """
    if df.empty or value_column not in df.columns:
        return []
    rows = []
    for _, row in df.iterrows():
        value = row.get(value_column)
        date = row.get("date")
        if pd.isna(value) or pd.isna(date):
            continue
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "month": date.strftime("%Y-%m"),
                "series": series_label,
                "value": round(float(value), 4),
            }
        )
    return rows


def _rebase_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebase each series in a long-format {date, month, series, value} list to 100
    at its own first chronological observation, so series with very different
    absolute levels (e.g. NAV/unit across REITs of different unit prices) become
    comparable in relative-movement terms on a shared axis.

    Skips leading zero/negative values when picking the base (a REIT can
    legitimately report a nil DPU in some periods -- see
    test_nil_dpu_period_change_does_not_raise_zero_division), since a zero or
    negative base would make rebasing undefined. If a series has no valid
    positive base at all, it is dropped from the rebased output entirely
    rather than divided by zero or fabricated.
    """
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_series.setdefault(row["series"], []).append(row)

    out: list[dict[str, Any]] = []
    for series, series_rows in by_series.items():
        ordered = sorted(series_rows, key=lambda r: r["date"])
        base = next((r["value"] for r in ordered if r["value"] > 0), None)
        if base is None:
            continue
        for row in ordered:
            out.append(
                {
                    "date": row["date"],
                    "month": row.get("month", row["date"][:7]),
                    "series": series,
                    "value": round(row["value"] / base * 100, 4),
                }
            )
    # Sort (date, series) -- NOT (series, date) -- so the array's globally
    # chronological order is genuinely ascending. See the matching comment
    # above the nav_history/dpu_history/occupancy_history/reversion_history
    # sort calls in build_artifact() for why this ordering matters and why
    # it's safe: the portable dashboard renderer (chart-app-helpers.tsx's
    # rechartsChartFromEncodedSpec) pivots these long-format rows into one
    # row per x-value via a Map keyed by first-encounter order of the x
    # field, then uses that same encounter order as the line chart's
    # category-axis tick order. Each pivoted bucket's per-series value is
    # populated correctly regardless of row order (verified independently),
    # so the ONLY thing row order controls is whether that Map -- and thus
    # the rendered x-axis -- ends up chronological or not. (date, series)
    # gives a chronological Map order for free; (series, date) does not,
    # since it inserts one REIT's whole date run before moving to the next.
    out.sort(key=lambda r: (r["date"], r["series"]))
    return out


def build_artifact(
    raw_link: pd.DataFrame | None = None,
    raw_champion: pd.DataFrame | None = None,
    raw_fortune: pd.DataFrame | None = None,
    raw_prosperity: pd.DataFrame | None = None,
    raw_sunlight: pd.DataFrame | None = None,
    raw_regal: pd.DataFrame | None = None,
    raw_spot: pd.DataFrame | None = None,
    raw_hist: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    df_link = _normalize(raw_link if raw_link is not None else fetch_linkreit_fundamentals())
    df_champion = _normalize(raw_champion if raw_champion is not None else fetch_championreit_fundamentals())
    df_fortune = _normalize(raw_fortune if raw_fortune is not None else fetch_fortunereit_fundamentals())
    df_prosperity = _normalize(raw_prosperity if raw_prosperity is not None else fetch_prosperityreit_fundamentals())
    df_sunlight = _normalize(raw_sunlight if raw_sunlight is not None else fetch_sunlightreit_fundamentals())
    df_regal = _normalize(raw_regal if raw_regal is not None else fetch_regalreit_fundamentals())

    generated_at = now.isoformat().replace("+00:00", "Z")

    frames = {
        "linkreit": df_link,
        "championreit": df_champion,
        "fortunereit": df_fortune,
        "prosperityreit": df_prosperity,
        "sunlightreit": df_sunlight,
        "regalreit": df_regal,
    }

    kpis = {key: _reit_kpi(frames[key], is_hotel) for key, _ticker, _name, _source, is_hotel in REIT_META}

    live_count = sum(1 for df in frames.values() if not df.empty)
    latest_dates = [df["date"].max() for df in frames.values() if not df.empty and "date" in df.columns]
    data_as_of = max(latest_dates).strftime("%Y-%m-%d") if latest_dates else now.strftime("%Y-%m-%d")

    # --- Cards: one per REIT, mirroring how the utilities monitor gives one
    # card per source -- these are six genuinely different businesses (five
    # office/retail landlords, one hotel operator), not interchangeable rows
    # of the same metric.
    cards = []
    for key, ticker, name, source_id, is_hotel in REIT_META:
        kpi = kpis[key]
        dataset_key = f"kpi_{key}"
        if is_hotel:
            metrics = [
                {"label": f"{name} NAV (HK$)", "field": "nav_per_unit_hkd", "format": "number"},
                {"label": "DPU (HK$)", "field": "dpu_hkd", "format": "number"},
                {"label": "Hotel Occupancy (%)", "field": "hotel_occupancy_pct", "format": "number"},
                {"label": "RevPAR (HK$)", "field": "revpar_hkd", "format": "number"},
            ]
        else:
            metrics = [
                {"label": f"{name} NAV (HK$)", "field": "nav_per_unit_hkd", "format": "number"},
                {"label": "DPU (HK$)", "field": "dpu_hkd", "format": "number"},
                {"label": "Occupancy (%)", "field": "occupancy_pct", "format": "number"},
                {"label": "Rental Reversion (%)", "field": "rental_reversion_pct", "format": "number"},
            ]
        cards.append(
            {
                "id": f"{key}_card",
                "description": f"{name} ({ticker}) latest NAV/unit, DPU, and {'hotel' if is_hotel else 'occupancy/reversion'} disclosures.",
                "dataset": dataset_key,
                "sourceId": source_id,
                "metrics": metrics,
            }
        )

    # --- Charts: comparable multi-series trends (color = REIT) for NAV and
    # DPU across all six trusts; occupancy and rental reversion across the
    # five office/retail trusts only; Regal's hotel KPIs (occupancy/ADR/
    # RevPAR) get their own dedicated chart since the metric set doesn't
    # belong on the same axis as the other five.
    nav_history: list[dict[str, Any]] = []
    dpu_history: list[dict[str, Any]] = []
    occupancy_history: list[dict[str, Any]] = []
    reversion_history: list[dict[str, Any]] = []
    for key, ticker, _name, _source, is_hotel in REIT_META:
        df = frames[key]
        # Series labels use the bare ticker code (e.g. "0823"), not the full
        # REIT name: the portable dashboard's chart legend does not reliably
        # wrap onto multiple lines at mobile widths, and six full names like
        # "Prosperity REIT" overflow the 390px viewport in a single row.
        # Tickers are already the primary identifier in the comparison table,
        # so they stay unambiguous while keeping the legend narrow.
        short_label = ticker.split(".")[0]
        nav_history.extend(_series_history(df, short_label, "nav_per_unit_hkd"))
        dpu_history.extend(_series_history(df, short_label, "dpu_hkd"))
        if not is_hotel:
            occupancy_history.extend(_series_history(df, short_label, "occupancy_pct"))
            reversion_history.extend(_series_history(df, short_label, "rental_reversion_pct"))
    # Sort by (date, series) -- NOT (series, date).
    #
    # An earlier version of this file sorted (series, date) specifically to
    # keep each series' points contiguous, based on an observation that the
    # portable chart renderer drew a disconnected line when points were
    # interleaved across REITs. Re-verified against the currently pinned
    # portable-artifact-builder plugin
    # (~/.codex/plugins/cache/openai-curated-remote/data-analytics):
    # chart-app-helpers.tsx's rechartsChartFromEncodedSpec() does NOT draw
    # a path by walking this array directly -- it first pivots these
    # long-format {date/month, series, value} rows into one row per
    # x-value via `rowsByX = new Map(); for (row of rows) { ... }`, and
    # only *that* pivoted, one-row-per-period array is what actually gets
    # handed to the line chart. Each pivoted bucket's per-series value is
    # populated correctly no matter what order the source rows arrive in
    # (confirmed by simulating both sort orders against that pivot logic --
    # every series kept its full point count either way). The only thing
    # row order affects is which x-value each Map bucket is created for
    # first, and both ChartRenderer.tsx's categoryXAxisLabels() and the
    # pivot's own Map insertion order use that same "first encounter in the
    # row array" order as the rendered x-axis category domain. (series,
    # date) therefore made the x-axis walk one REIT's entire date range
    # before moving to the next -- exactly the out-of-order axis
    # ("Jun 2021, Jun 2023, Dec 2025, Dec 2022, Mar 2022, ...") seen on the
    # live nav_trend_chart/dpu_trend_chart. (date, series) makes the first
    # encounter of each period chronological, which fixes the x-axis while
    # leaving every series' own values fully intact (verified: no dropped
    # points for any of the 6 tickers under either sort order).
    nav_history.sort(key=lambda row: (row["date"], row["series"]))
    dpu_history.sort(key=lambda row: (row["date"], row["series"]))
    occupancy_history.sort(key=lambda row: (row["date"], row["series"]))
    reversion_history.sort(key=lambda row: (row["date"], row["series"]))

    # NAV/unit and DPU are absolute HK$ values tied to each REIT's arbitrary
    # unit denomination (Link's NAV/unit is ~57.75, Regal's is ~3.9) -- not
    # comparable across REITs on a shared linear axis, since the trusts with
    # naturally smaller unit prices flatten to near-zero next to Link. Rebase
    # each series to 100 at its own first observation so the chart compares
    # relative movement (the actual point of a cross-REIT trend chart) rather
    # than absolute unit price. Absolute values remain available in the
    # comparison table and per-REIT cards above.
    nav_history_rebased = _rebase_series(nav_history)
    dpu_history_rebased = _rebase_series(dpu_history)

    regal_hotel_kpi_history: list[dict[str, Any]] = []
    regal_hotel_kpi_history.extend(_series_history(df_regal, "Occupancy (%)", "hotel_occupancy_pct"))
    regal_hotel_kpi_history.extend(_series_history(df_regal, "ADR (HK$)", "average_daily_rate_hkd"))
    regal_hotel_kpi_history.extend(_series_history(df_regal, "RevPAR (HK$)", "revpar_hkd"))
    # Same (date, series) ordering as nav/dpu/occupancy/reversion above, for
    # the same x-axis-category-domain reason -- currently a no-op in
    # practice since Regal REIT only has one disclosed period on record
    # (see Bug C discussion), but keeps this chart correct once more
    # periods accumulate.
    regal_hotel_kpi_history.sort(key=lambda row: (row["date"], row["series"]))

    charts = [
        {
            "id": "nav_trend_chart",
            "title": "NAV per Unit Across HK REITs (Rebased to 100)",
            "subtitle": "Relative movement in reported net asset value per unit, all six trusts (by ticker), each rebased to 100 at its own first observation -- absolute NAV/unit differs by REIT (see the comparison table and cards above) so raw HK$ values aren't comparable across trusts on one axis.",
            "type": "line",
            "dataset": "nav_history_rebased",
            "sourceId": "cross_source",
            "sourceIds": [source_id for _key, _ticker, _name, source_id, _is_hotel in REIT_META],
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "value", "type": "quantitative", "label": "Rebased (start = 100)"},
                "color": {"field": "series", "type": "nominal", "label": "Ticker"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "dpu_trend_chart",
            "title": "Distribution per Unit Across HK REITs (Rebased to 100)",
            "subtitle": "Relative movement in reported DPU, all six trusts (by ticker), each rebased to 100 at its own first positive observation. Some periods are legitimately nil (e.g. Regal REIT 1H2025) and rebase to 0 rather than being missing data; absolute HK$ DPU is in the comparison table above.",
            "type": "line",
            "dataset": "dpu_history_rebased",
            "sourceId": "cross_source",
            "sourceIds": [source_id for _key, _ticker, _name, source_id, _is_hotel in REIT_META],
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "value", "type": "quantitative", "label": "Rebased (start = 100)"},
                "color": {"field": "series", "type": "nominal", "label": "Ticker"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
        {
            "id": "occupancy_trend_chart",
            "title": "Portfolio Occupancy Across Office/Retail HK REITs (%)",
            "subtitle": "Link (0823), Champion (2778), Fortune (0778), Prosperity (0808), and Sunlight (0435) -- excludes Regal REIT, whose portfolio is hotels, not office/retail.",
            "type": "line",
            "dataset": "occupancy_history",
            "sourceId": "cross_source",
            "sourceIds": [source_id for _key, _ticker, _name, source_id, is_hotel in REIT_META if not is_hotel],
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "value", "type": "quantitative", "label": "Occupancy (%)"},
                "color": {"field": "series", "type": "nominal", "label": "Ticker"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "reversion_trend_chart",
            "title": "Rental Reversion Rate Across Office/Retail HK REITs (%)",
            "subtitle": "Rate achieved on renewed/new leases vs. the prior passing rent, the five office/retail trusts only (by ticker).",
            "type": "line",
            "dataset": "reversion_history",
            "sourceId": "cross_source",
            "sourceIds": [source_id for _key, _ticker, _name, source_id, is_hotel in REIT_META if not is_hotel],
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Period"},
                "y": {"field": "value", "type": "quantitative", "label": "Rental reversion (%)"},
                "color": {"field": "series", "type": "nominal", "label": "Ticker"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "regal_hotel_kpi_chart",
            "title": "Regal REIT Hotel KPIs: Occupancy, ADR & RevPAR",
            "subtitle": (
                "Regal REIT's hotel portfolio has a fundamentally different metric set than the other five office/retail "
                "trusts, so it is never combined with them. Occupancy is in %, ADR and RevPAR are in HK$ -- use the "
                "tooltip for exact values rather than comparing absolute levels across series."
            ),
            "type": "line",
            "dataset": "regal_hotel_kpi_history",
            "sourceId": "regalreit_fundamentals",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Period"},
                "y": {"field": "value", "type": "quantitative", "label": "Value (mixed units)"},
                "color": {"field": "series", "type": "nominal", "label": "Metric"},
            },
            "valueFormat": "number",
            "layout": "full",
        },
    ]

    # --- Table: one row per REIT with a unified occupancy column (hotel
    # occupancy for Regal, portfolio occupancy for the other five) plus
    # nullable reversion / ADR / RevPAR columns depending on business type.
    comparison_rows: list[dict[str, Any]] = []
    for key, ticker, name, _source, is_hotel in REIT_META:
        kpi = kpis[key]
        comparison_rows.append(
            {
                "reit_name": name,
                "ticker": ticker,
                "business_type": "Hotel" if is_hotel else "Office/Retail",
                "nav_per_unit_hkd": kpi.get("nav_per_unit_hkd"),
                "dpu_hkd": kpi.get("dpu_hkd"),
                "occupancy_pct": kpi.get("hotel_occupancy_pct") if is_hotel else kpi.get("occupancy_pct"),
                "rental_reversion_pct": None if is_hotel else kpi.get("rental_reversion_pct"),
                "average_daily_rate_hkd": kpi.get("average_daily_rate_hkd") if is_hotel else None,
                "revpar_hkd": kpi.get("revpar_hkd") if is_hotel else None,
                "as_of_date": kpi.get("observation_date"),
            }
        )

    tables: list[dict[str, Any]] = [
        {
            "id": "reit_comparison_table",
            "title": "HK REIT Fundamentals Comparison",
            "subtitle": (
                "Latest NAV/unit and DPU for all six trusts. Occupancy is unified across business types (hotel "
                "occupancy for Regal REIT); rental reversion and hotel rate columns are null where not applicable "
                "to that REIT's business type."
            ),
            "dataset": "reit_comparison",
            "sourceId": "cross_source",
            "sourceIds": [source_id for _key, _ticker, _name, source_id, _is_hotel in REIT_META],
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "reit_name", "label": "REIT Name", "type": "text"},
                {"field": "ticker", "label": "Ticker", "type": "text"},
                {"field": "nav_per_unit_hkd", "label": "NAV/Unit (HK$)", "format": "number"},
                {"field": "dpu_hkd", "label": "DPU (HK$)", "format": "number"},
                {"field": "occupancy_pct", "label": "Occupancy (%)", "format": "number"},
                {"field": "as_of_date", "label": "As Of", "type": "text"},
            ],
        }
    ]

    df_spot = raw_spot if raw_spot is not None else fetch_reit_spot_quotes()
    df_hist = raw_hist if raw_hist is not None else fetch_reit_price_history()

    status_entries = []
    for key, ticker, name, source_id, is_hotel in REIT_META:
        df = frames[key]
        spec = PUBLIC_SOURCES[source_id]
        status = "success" if not df.empty else "empty"
        max_date = df["date"].max().strftime("%Y-%m-%d") if not df.empty and "date" in df.columns else None
        status_entries.append(
            {
                "source_id": source_id,
                "label": spec["label"],
                "status": status,
                "records": len(df),
                "latest_observation": max_date,
                "freshness": "live" if status == "success" else "stale/unreachable",
                "notes": spec["query"]["description"],
            }
        )

    # Add status for reit_price_akshare. Spot quotes and price history are
    # separate calls; a working quote call must not conceal a failed history
    # call because the dashboard's historical price chart then has no data.
    spot_spec = PUBLIC_SOURCES["reit_price_akshare"]
    spot_available = not df_spot.empty
    history_available = not df_hist.empty
    # Spot quotes and history are one market-feed source in the headline
    # count; only count it as fully live when both calls succeeded.
    if spot_available and history_available:
        live_count += 1
    if spot_available and history_available:
        spot_status = "success"
        spot_freshness = "live"
    elif spot_available:
        spot_status = "partial"
        spot_freshness = "partial: history unavailable"
    elif history_available:
        spot_status = "partial"
        spot_freshness = "partial: spot quotes unavailable"
    else:
        spot_status = "stale/unreachable"
        spot_freshness = "stale/unreachable"
    spot_max_date = df_spot["date"].max().strftime("%Y-%m-%d") if not df_spot.empty and "date" in df_spot.columns else None
    history_max_date = df_hist["date"].max().strftime("%Y-%m-%d") if not df_hist.empty and "date" in df_hist.columns else None
    status_entries.append(
        {
            "source_id": "reit_price_akshare",
            "label": spot_spec["label"],
            "status": spot_status,
            "records": len(df_spot),
            "latest_observation": spot_max_date,
            "freshness": spot_freshness,
            "history_status": "success" if history_available else "empty",
            "history_records": len(df_hist),
            "history_latest_observation": history_max_date,
            "history_freshness": "live" if history_available else "unavailable",
            "notes": spot_spec["query"]["description"],
        }
    )

    if not df_spot.empty:
        df_spot = df_spot.copy()
        if "turnover_hkd" in df_spot.columns:
            df_spot["turnover_hkd_m"] = df_spot["turnover_hkd"].apply(lambda v: round(float(v) / 1e6, 2) if pd.notna(v) else None)
    spot_rows = _records_json_safe(df_spot) if not df_spot.empty else []
    hist_rows = []
    if not df_hist.empty and "date" in df_hist.columns and "close_hkd" in df_hist.columns:
        for _, r in df_hist.iterrows():
            if pd.notna(r.get("close_hkd")) and pd.notna(r.get("date")):
                # Chart legend only: shorten names so all 6 series fit the
                # legend at a 390px mobile viewport without wrapping (the
                # external renderer sizes this legend to its content rather
                # than the container, so it never actually wraps -- confirmed
                # by directly measuring the rendered legend at 390px).
                # Kept as non-numeric strings (not ticker) to avoid the
                # external renderer's Number()-based compact-notation
                # mangling of ticker codes >=1000. Chart title already
                # establishes "REIT" context.
                series_name = str(r.get("company_name", r.get("ticker", "")))
                series_name = _REIT_LEGEND_SHORT_NAMES.get(series_name, series_name)
                if series_name.endswith(" REIT"):
                    series_name = series_name[: -len(" REIT")]
                hist_rows.append({
                    "date": pd.to_datetime(r["date"]).strftime("%Y-%m-%d"),
                    "ticker": str(r.get("ticker", "")),
                    "series": series_name,
                    "value": float(r["close_hkd"]),
                })

    if spot_rows:
        tables.append(
            {
                "id": "reit_spot_summary_table",
                "title": "Hong Kong REITs Market Spot Quotes",
                "subtitle": "Daily spot price quotes, price change %, and turnover ($M HKD) via market feed.",
                "dataset": "reit_spot_quotes",
                "sourceId": "reit_price_akshare",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "company_name", "label": "REIT Name", "type": "text"},
                    {"field": "ticker", "label": "Ticker", "type": "text"},
                    {"field": "latest_price_hkd", "label": "Price (HK$)", "format": "number"},
                    {"field": "change_pct", "label": "Change (%)", "format": "number"},
                    {"field": "turnover_hkd_m", "label": "Turnover ($M)", "format": "number"},
                ],
            }
        )

    if hist_rows:
        charts.append(
            {
                "id": "reit_spot_price_history_chart",
                "title": "HK REITs Daily Closing Price History (HK$)",
                "subtitle": "Daily unit close prices for Hong Kong listed REITs.",
                "type": "line",
                "dataset": "reit_price_history",
                "sourceId": "reit_price_akshare",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Date"},
                    "y": {"field": "value", "type": "quantitative", "label": "Close (HK$)"},
                    "color": {"field": "series", "type": "nominal", "label": "REIT"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    datasets = {
        **{f"kpi_{key}": [kpis[key]] for key, *_ in REIT_META},
        "nav_history": nav_history,
        "dpu_history": dpu_history,
        "nav_history_rebased": nav_history_rebased,
        "dpu_history_rebased": dpu_history_rebased,
        "occupancy_history": occupancy_history,
        "reversion_history": reversion_history,
        "regal_hotel_kpi_history": regal_hotel_kpi_history,
        "reit_comparison": comparison_rows,
        "reit_spot_quotes": spot_rows,
        "reit_price_history": hist_rows,
        **{key: _records_json_safe(frames[key]) for key, *_ in REIT_META},
    }

    fingerprint_payload = {
        "datasets": {k: v for k, v in datasets.items() if k not in {f"kpi_{key}" for key, *_ in REIT_META}},
        "source_urls": [source.get("href") for source in PUBLIC_SOURCES.values() if source.get("href")],
    }
    snapshot_id = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:16]

    blocks = [
        {
            "id": "snapshot_context",
            "type": "markdown",
            "body": (
                f"**Data snapshot:** `{snapshot_id}` · generated {generated_at}.  "
                "Each REIT's figures come from that trust's own investor-relations disclosures "
                "(semi-annual or annual cadence), supplemented by market spot quotes."
            ),
        },
        {"id": "kpi_grid", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
    ]
    if spot_rows:
        blocks.append({"id": "reit_spot_table_block", "type": "table", "tableId": "reit_spot_summary_table"})
    if hist_rows:
        blocks.append({"id": "reit_price_chart_block", "type": "chart", "chartId": "reit_spot_price_history_chart"})

    blocks.extend([
        {"id": "nav_chart", "type": "chart", "chartId": "nav_trend_chart"},
        {"id": "dpu_chart", "type": "chart", "chartId": "dpu_trend_chart"},
        {"id": "occupancy_chart", "type": "chart", "chartId": "occupancy_trend_chart", "layout": "half"},
        {"id": "reversion_chart", "type": "chart", "chartId": "reversion_trend_chart", "layout": "half"},
        {"id": "regal_hotel_chart", "type": "chart", "chartId": "regal_hotel_kpi_chart"},
        {"id": "reit_comparison_table_block", "type": "table", "tableId": "reit_comparison_table"},
        {
            "id": "methodology",
            "type": "markdown",
            "body": (
                "## Reading the dashboard\n\n"
                "Five REITs (Link, Champion, Fortune, Prosperity, Sunlight) are office/retail landlords "
                "reporting occupancy and rental reversion. Regal REIT is a hotel-portfolio trust reporting "
                "occupancy, average daily rate (ADR), and RevPAR instead -- its hotel KPIs are never combined "
                "with the other five REITs' office/retail metrics in the same chart. DPU can be legitimately "
                "nil in a period (a genuine disclosed distribution outcome, not a data gap); period-over-period "
                "changes are left blank rather than divided by zero when this happens. No stock ranking, "
                "forecast, or investment recommendation is produced."
            ),
        },
    ])

    manifest_sources = list(PUBLIC_SOURCES.values())

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong REITs Sector Monitor",
            "description": "NAV/unit, DPU, occupancy, rental reversion, and hotel KPI disclosures for all six HK-listed REITs.",
            "sector": "hk-reit",
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
            "liveSourcesCount": live_count,
            "totalSourcesCount": len(UPSTREAM_SOURCE_IDS),
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": manifest_sources,
            "blocks": blocks,
        },
        "snapshot": {"version": 1, "generatedAt": generated_at, "status": "ready", "datasets": datasets},
        "sources": manifest_sources,
        "source_health": status_entries,
        "package_info": {
            "originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-reit/",
            "sector_id": "hk-reit",
            "sector_name": "Hong Kong REITs Sector Monitor",
            "snapshotId": snapshot_id,
            "generatedAt": generated_at,
            "dataAsOf": data_as_of,
        },
    }

    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": data_as_of,
        "overall_status": "Healthy" if live_count == len(UPSTREAM_SOURCE_IDS) and history_available else "Degraded",
        "live_sources": live_count,
        "planned_sources": 0,
        "sources": [
            {
                "source": entry["label"],
                "dataset": entry["source_id"],
                "type": "Measure",
                "status": "Healthy" if entry["status"] == "success" else "Degraded",
                "latest_observation": entry["latest_observation"] or "—",
                "records": entry["records"],
                "freshness": entry["freshness"],
                "notes": entry["notes"],
            }
            for entry in status_entries
        ],
        "attachment_filename": "hk-reit-monitor.html",
    }
    return artifact, status


def main() -> int:
    parser = argparse.ArgumentParser(description="Build HK REIT sector dashboard artifact.")
    parser.add_argument("--output", type=Path, required=True, help="Path to write JSON artifact.")
    parser.add_argument("--status-output", type=Path, required=True, help="Path to write status JSON.")
    args = parser.parse_args()

    artifact, status = build_artifact()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, separators=(",", ":"), default=str), encoding="utf-8")
    args.status_output.write_text(json.dumps(status, separators=(",", ":"), default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "artifact": str(args.output), "snapshot_id": status["snapshot_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
