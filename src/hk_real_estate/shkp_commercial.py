"""SHKP commercial-income and Mainland coverage contracts.

The residential SRPE signal layer is intentionally narrow: it describes
first-hand residential project activity and only applies an indicative SHKP
stake where the existing evidence contract allows it.  This module keeps the
other two research questions separate:

* recurring commercial income (office, retail, hotel and property-investment
  facts), and
* what we actually know about SHKP's Mainland project universe.

Neither contract invents an asset-level rent roll or a Mainland transaction
series.  A coverage row is useful precisely when it makes the missing join or
missing time series explicit.
"""

from __future__ import annotations

import re
from typing import Any, Iterable
import uuid

import pandas as pd

from .shkp_financial_model import (
    SHKP_ASSET_PIPELINE_COLUMNS,
    SHKP_RECURRING_PORTFOLIO_COLUMNS,
    build_shkp_asset_pipeline_capacity,
    build_shkp_recurring_portfolio_facts,
)
from .storage import load_latest_normalized, save_normalized_dataset


SHKP_TICKER = "0016.HK"

COMMERCIAL_FACT_DATASET = "shkp_commercial_recurring_facts"
COMMERCIAL_COVERAGE_DATASET = "shkp_commercial_recurring_coverage"
COMMERCIAL_PIPELINE_DATASET = "shkp_commercial_pipeline_capacity"
COMMERCIAL_MARKET_CONTEXT_DATASET = "shkp_commercial_market_context"
MAINLAND_COVERAGE_DATASET = "shkp_mainland_project_coverage"

COMMERCIAL_FACT_EXTRA_COLUMNS = [
    "commercial_asset_class",
    "asset_level_status",
    "coverage_status",
    "model_use",
    "research_only",
    "source_dataset",
]
COMMERCIAL_FACT_COLUMNS = [
    *SHKP_RECURRING_PORTFOLIO_COLUMNS,
    *COMMERCIAL_FACT_EXTRA_COLUMNS,
]

COMMERCIAL_PIPELINE_EXTRA_COLUMNS = [
    "commercial_asset_class",
    "coverage_status",
    "research_only",
    "source_dataset",
]
COMMERCIAL_PIPELINE_COLUMNS = [
    *SHKP_ASSET_PIPELINE_COLUMNS,
    *COMMERCIAL_PIPELINE_EXTRA_COLUMNS,
]

COMMERCIAL_COVERAGE_COLUMNS = [
    "coverage_id",
    "coverage_scope",
    "asset_class",
    "geography",
    "source_dataset",
    "source_url",
    "source_rows",
    "distinct_asset_count",
    "period_start",
    "period_end",
    "numeric_measure_rows",
    "numeric_value_sum",
    "value_unit",
    "value_currency",
    "coverage_status",
    "project_level_status",
    "model_use",
    "research_only",
    "caveat",
]

MAINLAND_COVERAGE_COLUMNS = [
    "coverage_id",
    "coverage_scope",
    "source_dataset",
    "geography",
    "source_rows",
    "distinct_project_count",
    "period_start",
    "period_end",
    "numeric_gfa_rows",
    "numeric_gfa_sum_sqft",
    "project_level_sales_status",
    "project_level_pipeline_status",
    "identity_join_status",
    "coverage_status",
    "model_use",
    "research_only",
    "caveat",
]

# Quarterly headlines are a dated issuer-event layer, not a quarterly revenue
# series.  ``event_date_semantics`` makes the fallback to the quarter-end label
# visible when the issuer page does not expose a separate publication date.
SHKP_QUARTERLY_EVENT_COLUMNS = [
    "event_id",
    "quarter_label",
    "quarter_end",
    "event_date",
    "event_date_semantics",
    "title",
    "event_type",
    "property_relevance",
    "asset_class",
    "geography",
    "project_label",
    "source_document_type",
    "document_url",
    "source_page_url",
    "source_url",
    "published_date",
    "fetched_at",
    "coverage_status",
    "model_use",
    "research_only",
    "caveat",
]

# One row is an issuer asset observation.  The same asset may have multiple
# rows from different issuer/source layers; ``asset_id`` is the stable join
# key, while ``source_layer`` and ``as_of_date`` preserve the observation
# semantics instead of pretending this is a legal ownership master.
SHKP_COMMERCIAL_ASSET_MASTER_COLUMNS = [
    "asset_id",
    "canonical_name",
    "name_raw",
    "asset_class",
    "asset_subtype",
    "geography",
    "district",
    "location_raw",
    "status",
    "source_layer",
    "source_record_id",
    "group_interest_raw",
    "group_interest_pct",
    "report_period_end",
    "as_of_date",
    "completion_window",
    "residential_gfa_sqft",
    "retail_gfa_sqft",
    "office_gfa_sqft",
    "hotel_gfa_sqft",
    "industrial_gfa_sqft",
    "total_gfa_sqft",
    "external_project_url",
    "source_page_url",
    "source_url",
    "coverage_status",
    "asset_level_operating_data_status",
    "model_use",
    "research_only",
    "caveat",
]


def _frame(value: pd.DataFrame | None, columns: Iterable[str] = ()) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame(columns=list(columns))
    return value.copy()


def _empty(columns: Iterable[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _normalise_label(value: Any) -> str:
    """Lowercase an issuer label for conservative substring matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _quarter_metadata(document_url: Any, published_date: Any) -> tuple[str | None, str | None, str, str]:
    """Return quarter label/end and explicit date semantics for a PDF URL."""
    haystack = str(document_url or "")
    match = re.search(r"/(20\d{2})q([1-4])(?:/|%20|_)", haystack.casefold())
    if not match:
        match = re.search(r"(20\d{2})q([1-4])", haystack.casefold())
    if not match:
        return None, None, str(published_date or "") or None, "issuer_published_date"
    year, quarter = int(match.group(1)), int(match.group(2))
    month_day = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[quarter]
    quarter_label = f"{year}Q{quarter}"
    quarter_end = f"{year}-{month_day}"
    published = pd.to_datetime(published_date, errors="coerce")
    if pd.notna(published):
        return quarter_label, quarter_end, published.date().isoformat(), "issuer_published_date"
    return quarter_label, quarter_end, quarter_end, "quarter_end_label_proxy"


def _quarterly_event_type(title: str) -> tuple[str, str, str | None]:
    text = str(title or "").casefold()
    if any(token in text for token in ("sales", "well received", "well-received", "market response", "for sale", "market responses")):
        return "sales_response", "property", "residential"
    if any(token in text for token in ("tenant", "anchor", "lease", "leasing", "occupancy")):
        return "leasing_or_occupancy", "property", "office" if "office" in text or "tenant" in text or "anchor" in text else "retail"
    if any(token in text for token in ("completion", "handover", "top out", "tops out", "commences construction", "open", "opening", "officially opens")):
        if any(token in text for token in ("hotel", "andaz", "royal garden", "hkbak", "fbo")):
            asset_class = "hotel"
        elif any(token in text for token in ("mall", "shopping", "retail", "apm", "yata")):
            asset_class = "retail"
        elif any(token in text for token in ("office", "tower", "igc", "icc", "ifc", "commercial")):
            asset_class = "office"
        else:
            asset_class = "residential" if any(token in text for token in ("phase", "residential", "sea", "spark", "garden", "harbour")) else None
        return "completion_or_opening", "property", asset_class
    if any(token in text for token in ("development", "project", "station", "mall", "tower", "centre", "center", "residential")):
        asset_class = "residential" if "residential" in text or "phase" in text else None
        if any(token in text for token in ("mall", "retail")):
            asset_class = "retail"
        if any(token in text for token in ("office", "tower", "commercial", "igc", "icc", "ifc")):
            asset_class = "office" if asset_class is None else "mixed_use"
        return "project_update", "property", asset_class
    if any(token in text for token in ("esg", "foundation", "volunteer", "award", "sponsor", "charity", "scholarship", "university", "reading", "coffee fair", "invention")):
        return "other_corporate", "other", None
    return "corporate_update", "other", None


def _quarterly_project_alias(title: str, property_catalog: pd.DataFrame | None) -> str | None:
    aliases = [
        "Cullinan Harbour",
        "Cullinan Sky",
        "SIERRA SEA",
        "Sierra Sea",
        "YOHO WEST",
        "Lime Spark",
        "IGC",
        "Artist Square Towers",
        "The Royal Garden Kowloon East",
        "Guangzhou South Station ICC",
        "Forest Park",
        "Shanghai ITC",
        "Andaz Shanghai ITC",
        "PARK YOHO",
        "NOVO LAND",
        "Wetland Seasons Bay",
        "Wetland Seasons Park",
        "The Millennity",
        "The Point",
        "Three ITC",
    ]
    catalog = _frame(property_catalog)
    if not catalog.empty and "marketing_name" in catalog.columns:
        aliases.extend(catalog["marketing_name"].dropna().astype(str).tolist())
    normalized_title = _normalise_label(title)
    matches = [alias for alias in set(aliases) if len(_normalise_label(alias)) >= 5 and _normalise_label(alias) in normalized_title]
    return sorted(matches, key=lambda value: len(_normalise_label(value)), reverse=True)[0] if matches else None


def build_shkp_quarterly_events(
    corporate_documents: pd.DataFrame | None,
    *,
    property_catalog: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Normalize SHKP Quarterly article headings into dated event rows.

    The source page exposes article-level PDFs, not a machine-readable event
    table.  This first-stage contract therefore treats the issuer's headline
    as the observed fact and keeps classification/project matching explicitly
    heuristic.  It does not infer sales value, occupancy, ownership or a
    project-month time series.
    """
    documents = _frame(corporate_documents)
    if documents.empty:
        return _empty(SHKP_QUARTERLY_EVENT_COLUMNS)
    documents = documents.loc[
        _text_series(documents, "document_type").eq("quarterly_article")
    ].copy()
    if documents.empty:
        return _empty(SHKP_QUARTERLY_EVENT_COLUMNS)

    rows: list[dict[str, Any]] = []
    for record in documents.to_dict("records"):
        title = re.sub(r"\s+", " ", str(record.get("title") or "")).strip()
        if not title:
            continue
        quarter_label, quarter_end, event_date, date_semantics = _quarter_metadata(
            record.get("document_url"), record.get("published_date")
        )
        event_type, relevance, asset_class = _quarterly_event_type(title)
        project_label = _quarterly_project_alias(title, property_catalog)
        document_url = str(record.get("document_url") or "").strip()
        event_id = _stable_key("shkp-quarterly", document_url or title)
        text = f"{title} {project_label or ''}".casefold()
        if any(token in text for token in ("shanghai", "beijing", "guangzhou", "forest park", "zhongshan", "mainland")):
            geography = "mainland"
        elif relevance == "property" or any(token in text for token in ("hong kong", "kowloon", "sai sha", "tsuen wan", "tuen mun", "sha tin", "yuen long", "west kowloon", "igc", "artist square")):
            geography = "hong_kong"
        else:
            geography = "unknown"
        if asset_class is None and any(token in text for token in ("retail", "mall", "shopping", "yata", "apm")):
            asset_class = "retail"
        if asset_class is None and any(token in text for token in ("hotel", "andaz", "royal garden", "hkbak")):
            asset_class = "hotel"
        rows.append(
            {
                "event_id": event_id,
                "quarter_label": quarter_label,
                "quarter_end": quarter_end,
                "event_date": event_date,
                "event_date_semantics": date_semantics,
                "title": title,
                "event_type": event_type,
                "property_relevance": relevance,
                "asset_class": asset_class,
                "geography": geography,
                "project_label": project_label,
                "source_document_type": record.get("document_type"),
                "document_url": document_url,
                "source_page_url": record.get("source_page_url"),
                "source_url": record.get("source_url") or record.get("source_page_url"),
                "published_date": record.get("published_date"),
                "fetched_at": record.get("fetched_at"),
                "coverage_status": "issuer_headline_event_classified",
                "model_use": "dated_event_context_only",
                "research_only": True,
                "caveat": "Headline-level issuer event; classification and project alias are heuristic and do not imply sales value, legal ownership or asset-level operating KPI.",
            }
        )
    result = pd.DataFrame(rows, columns=SHKP_QUARTERLY_EVENT_COLUMNS)
    if result.empty:
        return _empty(SHKP_QUARTERLY_EVENT_COLUMNS)
    result = result.drop_duplicates(subset=["event_id"]).sort_values(
        ["event_date", "event_id"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)
    source_urls = result["document_url"].dropna().astype(str).drop_duplicates().tolist()
    result.attrs.update(
        source_urls=source_urls,
        lineage_metadata={
            "lineage_type": "derived_shkp_quarterly_headline_events",
            "source_dataset": "shkp_corporate_documents",
            "event_count": int(len(result)),
            "property_event_count": int(result["property_relevance"].eq("property").sum()),
            "classification_policy": "headline_keywords_plus_conservative_project_aliases",
            "sales_or_ownership_inference": False,
        },
    )
    return result


def _commercial_asset_class_from_components(row: pd.Series) -> str | None:
    components = {
        "retail": pd.to_numeric(row.get("retail_gfa_sqft", row.get("shopping_centre_gfa_sqft")), errors="coerce"),
        "office": pd.to_numeric(row.get("office_gfa_sqft"), errors="coerce"),
        "hotel": pd.to_numeric(row.get("hotel_gfa_sqft"), errors="coerce"),
        "industrial": pd.to_numeric(row.get("industrial_gfa_sqft"), errors="coerce"),
    }
    active = [name for name, value in components.items() if pd.notna(value) and float(value) > 0]
    if len(active) == 1:
        return active[0]
    return "mixed_use" if active else None


def _asset_row(**values: Any) -> dict[str, Any]:
    row = {column: None for column in SHKP_COMMERCIAL_ASSET_MASTER_COLUMNS}
    row.update(values)
    row["research_only"] = True
    return row


def build_shkp_commercial_asset_master(
    *,
    property_catalog: pd.DataFrame | None,
    completed_properties: pd.DataFrame | None,
    completion_schedule: pd.DataFrame | None,
) -> pd.DataFrame:
    """Build an HK commercial asset observation master from issuer sources.

    Current SHKP directory rows, annual-report completed-property rows and
    completion-schedule pipeline rows are kept as separate source layers.  A
    repeated name therefore remains auditable rather than being silently
    collapsed into a synthetic legal ownership record.
    """
    rows: list[dict[str, Any]] = []
    catalog = _frame(property_catalog)
    commercial_types = {"shopping_mall", "office", "hotel", "serviced_suite"}
    if not catalog.empty:
        for record in catalog.loc[_text_series(catalog, "asset_type").isin(commercial_types)].to_dict("records"):
            name = str(record.get("marketing_name") or "").strip()
            if not name:
                continue
            asset_type = str(record.get("asset_type") or "")
            asset_class = {
                "shopping_mall": "retail",
                "office": "office",
                "hotel": "hotel",
                "serviced_suite": "hotel",
            }.get(asset_type, "commercial")
            rows.append(_asset_row(
                asset_id="shkp:hk:asset:" + _stable_key(name),
                canonical_name=name,
                name_raw=name,
                asset_class=asset_class,
                asset_subtype=asset_type,
                geography="hong_kong",
                district=record.get("district"),
                location_raw=record.get("district"),
                status="current_website_listing",
                source_layer="issuer_current_directory",
                source_record_id=record.get("source_record_id"),
                as_of_date=record.get("fetched_at"),
                external_project_url=record.get("external_project_url"),
                source_page_url=record.get("source_page_url"),
                source_url=record.get("source_url"),
                coverage_status="current_issuer_catalog",
                asset_level_operating_data_status="not_disclosed_in_directory",
                model_use="commercial_asset_universe_context",
                caveat="Current SHKP directory listing; no asset-level rent, NOI, occupancy or legal ownership interval is inferred.",
            ))

    completed = _frame(completed_properties)
    if not completed.empty:
        for record in completed.to_dict("records"):
            series = pd.Series(record)
            asset_class = _commercial_asset_class_from_components(series)
            if asset_class is None:
                continue
            name = str(record.get("project_label_raw") or "").strip()
            if not name:
                continue
            rows.append(_asset_row(
                asset_id="shkp:hk:asset:" + _stable_key(name),
                canonical_name=name,
                name_raw=name,
                asset_class=asset_class,
                asset_subtype="completed_portfolio_snapshot",
                geography="hong_kong",
                district=record.get("geography"),
                location_raw=record.get("location_raw"),
                status="completed_portfolio_snapshot",
                source_layer="issuer_annual_report_completed",
                source_record_id=record.get("completed_property_id"),
                group_interest_raw=record.get("group_interest_raw"),
                group_interest_pct=record.get("group_interest_pct"),
                report_period_end=record.get("report_period_end"),
                as_of_date=record.get("report_period_end"),
                residential_gfa_sqft=record.get("residential_gfa_sqft"),
                retail_gfa_sqft=record.get("shopping_centre_gfa_sqft"),
                office_gfa_sqft=record.get("office_gfa_sqft"),
                hotel_gfa_sqft=record.get("hotel_gfa_sqft"),
                industrial_gfa_sqft=record.get("industrial_gfa_sqft"),
                total_gfa_sqft=record.get("total_gfa_sqft"),
                source_url=record.get("source_url"),
                coverage_status="report_period_completed_exposure",
                asset_level_operating_data_status="gfa_and_interest_only",
                model_use="commercial_asset_exposure_context",
                caveat=str(record.get("caveat") or "Annual-report GFA/interest snapshot; not rent, NOI, valuation or a legal title interval."),
            ))

    schedule = _frame(completion_schedule)
    if not schedule.empty:
        url_text = _text_series(schedule, "source_url").str.lower()
        hk_mask = url_text.str.contains("hongkong|completion_schedule_hk|schedule_hk", regex=True)
        if hk_mask.any():
            schedule = schedule.loc[hk_mask].copy()
        for record in schedule.to_dict("records"):
            series = pd.Series(record)
            asset_class = _commercial_asset_class_from_components(series)
            if asset_class is None:
                continue
            name = str(record.get("project_label") or record.get("lot_description") or "").strip()
            if not name:
                continue
            rows.append(_asset_row(
                asset_id="shkp:hk:asset:" + _stable_key(name),
                canonical_name=name,
                name_raw=name,
                asset_class=asset_class,
                asset_subtype="completion_schedule_pipeline",
                geography="hong_kong",
                district=None,
                location_raw=record.get("lot_description"),
                status="pipeline_snapshot",
                source_layer="issuer_completion_schedule",
                source_record_id=f"{record.get('schedule_id')}:{record.get('project_row_no')}",
                group_interest_raw=record.get("group_interest_raw"),
                group_interest_pct=record.get("group_interest_pct"),
                as_of_date=record.get("schedule_date"),
                completion_window=record.get("completion_window"),
                residential_gfa_sqft=record.get("residential_gfa_sqft"),
                retail_gfa_sqft=record.get("shops_gfa_sqft"),
                office_gfa_sqft=record.get("office_gfa_sqft"),
                hotel_gfa_sqft=record.get("hotel_gfa_sqft"),
                industrial_gfa_sqft=record.get("industrial_gfa_sqft"),
                total_gfa_sqft=record.get("total_gfa_sqft"),
                source_url=record.get("source_url") or record.get("document_url"),
                coverage_status="issuer_pipeline_capacity_snapshot",
                asset_level_operating_data_status="pipeline_gfa_and_interest_only",
                model_use="commercial_future_capacity_context",
                caveat="SHKP Completion Schedule major-project snapshot; completion window may change and no rent/NOI is inferred.",
            ))
    result = pd.DataFrame(rows, columns=SHKP_COMMERCIAL_ASSET_MASTER_COLUMNS)
    if result.empty:
        return _empty(SHKP_COMMERCIAL_ASSET_MASTER_COLUMNS)
    result = result.drop_duplicates(subset=["asset_id", "source_layer", "source_record_id"]).reset_index(drop=True)
    result.attrs.update(
        source_urls=result["source_url"].dropna().astype(str).drop_duplicates().tolist(),
        lineage_metadata={
            "lineage_type": "derived_shkp_hong_kong_commercial_asset_observation_master",
            "source_layers": sorted(result["source_layer"].dropna().astype(str).unique().tolist()),
            "asset_count": int(result["asset_id"].nunique()),
            "observation_count": int(len(result)),
            "legal_ownership_inference": False,
            "asset_level_income_inference": False,
        },
    )
    return result


def _text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    return frame[column].astype("string").fillna("").str.strip()


def _normalise_asset_class(row: pd.Series) -> str:
    asset = str(row.get("asset_class") or "").strip().lower()
    segment = str(row.get("segment") or "").strip().lower()
    metric = str(row.get("metric") or "").strip().lower()
    combined = " ".join((asset, segment, metric))
    if "hotel" in combined:
        return "hotel"
    if "office" in combined:
        return "office"
    if "retail" in combined or "shopping" in combined or "mall" in combined:
        return "retail"
    if "rental" in combined or "property_investment" in combined:
        return "property_investment"
    return "property_rental_portfolio"


def _date_bounds(frame: pd.DataFrame, columns: Iterable[str]) -> tuple[str | None, str | None]:
    values: list[pd.Series] = []
    for column in columns:
        if column in frame.columns:
            values.append(pd.to_datetime(frame[column], errors="coerce"))
    if not values:
        return None, None
    combined = pd.concat(values, ignore_index=True).dropna()
    if combined.empty:
        return None, None
    return combined.min().date().isoformat(), combined.max().date().isoformat()


def _stable_key(*parts: Any) -> str:
    text = "|".join(str(part or "").strip().lower() for part in parts)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown"


def build_shkp_commercial_recurring_facts(
    recurring_portfolio: pd.DataFrame | None,
) -> pd.DataFrame:
    """Keep the recurring-income facts, while labelling their true grain.

    The source contains group/segment period facts, not an asset-by-month rent
    roll.  Land-bank and GFA capacity rows are intentionally left to the
    pipeline contract rather than mixed into recurring income.
    """
    frame = _frame(recurring_portfolio)
    if frame.empty:
        return _empty(COMMERCIAL_FACT_COLUMNS)
    metric = _text_series(frame, "metric").str.lower()
    asset = _text_series(frame, "asset_class").str.lower()
    segment = _text_series(frame, "segment").str.lower()
    include = (
        asset.str.contains("office|retail|hotel|property_investment|portfolio", regex=True)
        | segment.str.contains("property_rental|hotel", regex=True)
    )
    exclude_capacity = metric.str.contains(
        "gfa|land_bank|under_development|completed_gfa|total_land_bank",
        regex=True,
    )
    frame = frame.loc[include & ~exclude_capacity].copy()
    if frame.empty:
        return _empty(COMMERCIAL_FACT_COLUMNS)
    frame["commercial_asset_class"] = frame.apply(_normalise_asset_class, axis=1)
    frame["asset_level_status"] = "group_or_segment_period_fact_not_asset_level"
    frame["coverage_status"] = "group_period_facts_available_not_asset_level"
    frame["model_use"] = "recurring_income_context_only"
    frame["research_only"] = True
    frame["source_dataset"] = "shkp_financial_model_recurring_portfolio_facts"
    return frame.reindex(columns=COMMERCIAL_FACT_COLUMNS)


def build_shkp_commercial_pipeline_capacity(
    asset_pipeline_capacity: pd.DataFrame | None,
) -> pd.DataFrame:
    """Expose named commercial capacity without converting GFA to rent/NOI."""
    frame = _frame(asset_pipeline_capacity)
    if frame.empty:
        return _empty(COMMERCIAL_PIPELINE_COLUMNS)
    asset = _text_series(frame, "asset_class").str.lower()
    keep = asset.str.contains("office|retail|hotel|shopping|mall", regex=True)
    frame = frame.loc[keep].copy()
    if frame.empty:
        return _empty(COMMERCIAL_PIPELINE_COLUMNS)
    frame["commercial_asset_class"] = frame.apply(_normalise_asset_class, axis=1)
    frame["coverage_status"] = "pipeline_capacity_only"
    frame["research_only"] = True
    frame["source_dataset"] = "shkp_financial_model_asset_pipeline_capacity"
    return frame.reindex(columns=COMMERCIAL_PIPELINE_COLUMNS)


def build_shkp_commercial_market_context(
    office_index: pd.DataFrame | None,
    retail_index: pd.DataFrame | None,
) -> pd.DataFrame:
    """Combine RVD market context while keeping it separate from SHKP assets."""
    frames: list[pd.DataFrame] = []
    for source_name, source_frame, asset_class in (
        ("rvd_office_rental_index_monthly", office_index, "office"),
        ("rvd_retail_index_monthly", retail_index, "retail"),
    ):
        frame = _frame(source_frame)
        if frame.empty:
            continue
        frame["commercial_asset_class"] = asset_class
        frame["source_dataset"] = source_name
        frame["coverage_status"] = "market_context_available_not_shkp_asset"
        frame["model_use"] = "market_context_only"
        frame["research_only"] = True
        frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=[
                "date",
                "segment",
                "metric",
                "value",
                "is_provisional",
                "source_agency",
                "commercial_asset_class",
                "source_dataset",
                "coverage_status",
                "model_use",
                "research_only",
            ]
        )
    return pd.concat(frames, ignore_index=True, sort=False)


def _coverage_row(**values: Any) -> dict[str, Any]:
    row = {column: None for column in COMMERCIAL_COVERAGE_COLUMNS}
    row.update(values)
    row["research_only"] = True
    return row


def build_shkp_commercial_recurring_coverage(
    *,
    property_catalog: pd.DataFrame | None,
    recurring_facts: pd.DataFrame | None,
    completed_properties: pd.DataFrame | None,
    pipeline_capacity: pd.DataFrame | None,
    office_index: pd.DataFrame | None,
    retail_index: pd.DataFrame | None,
) -> pd.DataFrame:
    """Build a compact source-by-source commercial coverage contract."""
    rows: list[dict[str, Any]] = []
    catalog = _frame(property_catalog)
    if not catalog.empty:
        catalog_asset = _text_series(catalog, "asset_type").str.lower()
        class_map = {
            "office": "office",
            "shopping_mall": "retail",
            "hotel": "hotel",
            "serviced_suite": "hotel",
        }
        for source_class, asset_class in class_map.items():
            subset = catalog.loc[catalog_asset.eq(source_class)]
            if subset.empty:
                continue
            rows.append(_coverage_row(
                # ``hotel`` and ``serviced_suite`` are both mapped to the
                # hotel research class but remain separate issuer catalogue
                # rows; keep the source subtype in the key so coverage IDs
                # stay unique.
                coverage_id=f"shkp-commercial:catalog:{_stable_key(source_class)}",
                coverage_scope="issuer_asset_catalog",
                asset_class=asset_class,
                geography="hong_kong",
                source_dataset="shkp_property_catalog",
                source_url=next(iter(subset.get("source_url", pd.Series(dtype="string")).dropna()), None),
                source_rows=int(len(subset)),
                distinct_asset_count=int(_text_series(subset, "marketing_name").replace("", pd.NA).nunique(dropna=True)),
                period_start=_date_bounds(subset, ["fetched_at"])[0],
                period_end=_date_bounds(subset, ["fetched_at"])[1],
                coverage_status="issuer_catalog_current_snapshot",
                project_level_status="asset_names_available_current_snapshot",
                model_use="asset_universe_context_only",
                caveat="Current SHKP website catalogue; it is not a historical asset register and does not contain rent/NOI time series.",
            ))

    recurring = _frame(recurring_facts)
    if not recurring.empty:
        group_columns = ["commercial_asset_class", "geography", "unit", "currency"]
        for keys, subset in recurring.groupby(group_columns, dropna=False):
            asset_class, geography, unit, currency = keys
            period_start, period_end = _date_bounds(subset, ["period_start", "period_end"])
            rows.append(_coverage_row(
                coverage_id="shkp-commercial:recurring:" + _stable_key(*keys),
                coverage_scope="recurring_period_facts",
                asset_class=asset_class,
                geography=geography or "group",
                source_dataset="shkp_financial_model_recurring_portfolio_facts",
                source_url=next(iter(subset.get("source_url", pd.Series(dtype="string")).dropna()), None),
                source_rows=int(len(subset)),
                distinct_asset_count=0,
                period_start=period_start,
                period_end=period_end,
                numeric_measure_rows=int(pd.to_numeric(subset.get("value"), errors="coerce").notna().sum()),
                value_unit=unit,
                value_currency=currency,
                coverage_status="group_period_facts_available_not_asset_level",
                project_level_status="no_asset_id_in_period_fact",
                model_use="recurring_income_context_only",
                caveat="Official period facts include Group/JV/associate scope where stated; they are not an asset-level monthly rent roll and should not be joined to project sales by name.",
            ))

    completed = _frame(completed_properties)
    completed_use_columns = {
        "residential": "residential_gfa_sqft",
        "retail": "shopping_centre_gfa_sqft",
        "office": "office_gfa_sqft",
        "hotel": "hotel_gfa_sqft",
        "industrial": "industrial_gfa_sqft",
    }
    if not completed.empty:
        for asset_class, value_column in completed_use_columns.items():
            values = pd.to_numeric(completed.get(value_column), errors="coerce")
            subset = completed.loc[values.notna()]
            if subset.empty:
                continue
            rows.append(_coverage_row(
                coverage_id=f"shkp-commercial:completed:{asset_class}",
                coverage_scope="completed_property_exposure",
                asset_class=asset_class,
                geography="hong_kong",
                source_dataset="shkp_completed_properties",
                source_url=next(iter(subset.get("source_url", pd.Series(dtype="string")).dropna()), None),
                source_rows=int(len(subset)),
                distinct_asset_count=int(_text_series(subset, "project_label_raw").replace("", pd.NA).nunique(dropna=True)),
                period_start=_date_bounds(subset, ["report_period_end"])[0],
                period_end=_date_bounds(subset, ["report_period_end"])[1],
                numeric_measure_rows=int(values.loc[subset.index].notna().sum()),
                numeric_value_sum=float(values.loc[subset.index].sum()),
                value_unit="sqft",
                coverage_status="completed_exposure_gfa_only",
                project_level_status="named_projects_with_report_period_gfa",
                model_use="exposure_context_only",
                caveat="Report-period Group interest/GFA exposure; not rent, NOI, valuation or a dated legal ownership interval.",
            ))

    pipeline = _frame(pipeline_capacity)
    if not pipeline.empty:
        group_columns = ["commercial_asset_class", "metric", "unit"]
        for keys, subset in pipeline.groupby(group_columns, dropna=False):
            asset_class, metric, unit = keys
            values = pd.to_numeric(subset.get("value"), errors="coerce")
            rows.append(_coverage_row(
                coverage_id="shkp-commercial:pipeline:" + _stable_key(*keys),
                coverage_scope="named_commercial_pipeline_capacity",
                asset_class=asset_class,
                geography="hong_kong",
                source_dataset="shkp_financial_model_asset_pipeline_capacity",
                source_url=next(iter(subset.get("source_url", pd.Series(dtype="string")).dropna()), None),
                source_rows=int(len(subset)),
                distinct_asset_count=int(_text_series(subset, "asset_name").replace("", pd.NA).nunique(dropna=True)),
                period_start=_date_bounds(subset, ["report_period_end", "observation_date"])[0],
                period_end=_date_bounds(subset, ["report_period_end", "observation_date"])[1],
                numeric_measure_rows=int(values.notna().sum()),
                numeric_value_sum=float(values.sum()),
                value_unit=unit,
                coverage_status="pipeline_capacity_only",
                project_level_status="named_capacity_rows_no_rent_or_noi",
                model_use="capacity_only",
                caveat="Named commercial capacity and opening window only; do not convert GFA into rent/NOI without asset-specific assumptions.",
            ))

    for source_dataset, source_frame, asset_class in (
        ("rvd_office_rental_index_monthly", office_index, "office"),
        ("rvd_retail_index_monthly", retail_index, "retail"),
    ):
        market = _frame(source_frame)
        if market.empty:
            continue
        rows.append(_coverage_row(
            coverage_id=f"shkp-commercial:market:{asset_class}",
            coverage_scope="market_context_index",
            asset_class=asset_class,
            geography="hong_kong",
            source_dataset=source_dataset,
            source_rows=int(len(market)),
            distinct_asset_count=0,
            period_start=_date_bounds(market, ["date"])[0],
            period_end=_date_bounds(market, ["date"])[1],
            numeric_measure_rows=int(pd.to_numeric(market.get("value"), errors="coerce").notna().sum()),
            coverage_status="market_context_available_not_shkp_asset",
            project_level_status="market_index_not_company_asset",
            model_use="market_context_only",
            caveat="RVD market-level index is useful for demand/rent context but is not SHKP-specific and cannot be read as SHKP same-store rent growth.",
        ))
    return pd.DataFrame(rows, columns=COMMERCIAL_COVERAGE_COLUMNS)


def _mainland_mask(frame: pd.DataFrame) -> pd.Series:
    geography = _text_series(frame, "geography").str.lower()
    if "geography" in frame.columns:
        return geography.eq("mainland")
    return pd.Series(False, index=frame.index)


def _mainland_row(**values: Any) -> dict[str, Any]:
    row = {column: None for column in MAINLAND_COVERAGE_COLUMNS}
    row.update(values)
    row["geography"] = "mainland"
    row["research_only"] = True
    return row


def _append_mainland_source_row(
    rows: list[dict[str, Any]],
    *,
    scope: str,
    source_dataset: str,
    source_frame: pd.DataFrame | None,
    project_label_column: str = "project_label",
    gfa_column: str = "attributable_gfa_sqft",
    sales_status: str,
    pipeline_status: str,
    identity_status: str,
    coverage_status: str,
    model_use: str,
    caveat: str,
) -> None:
    frame = _frame(source_frame)
    subset = frame.loc[_mainland_mask(frame)].copy() if not frame.empty else frame
    periods = _date_bounds(subset, ["period_start", "period_end", "period_end_date", "report_period_end"])
    labels = _text_series(subset, project_label_column).replace("", pd.NA) if project_label_column in subset.columns else pd.Series(pd.NA, index=subset.index, dtype="string")
    gfa = pd.to_numeric(subset.get(gfa_column), errors="coerce") if gfa_column in subset.columns else pd.Series(dtype="float64")
    rows.append(_mainland_row(
        coverage_id=f"shkp-mainland:{_stable_key(scope, source_dataset)}",
        coverage_scope=scope,
        source_dataset=source_dataset,
        source_rows=int(len(subset)),
        distinct_project_count=int(labels.nunique(dropna=True)) if not subset.empty else 0,
        period_start=periods[0],
        period_end=periods[1],
        numeric_gfa_rows=int(gfa.notna().sum()) if not subset.empty else 0,
        numeric_gfa_sum_sqft=float(gfa.sum()) if not gfa.empty and gfa.notna().any() else 0.0,
        project_level_sales_status=sales_status,
        project_level_pipeline_status=pipeline_status,
        identity_join_status=identity_status,
        coverage_status=coverage_status,
        model_use=model_use,
        caveat=caveat,
    ))


def build_shkp_mainland_project_coverage_audit(
    *,
    annual_report_projects: pd.DataFrame | None,
    historical_annual_report_projects: pd.DataFrame | None,
    recurring_facts: pd.DataFrame | None,
    disclosed_facts: pd.DataFrame | None,
    project_month_signals: pd.DataFrame | None,
    planning_crosswalk: pd.DataFrame | None,
    landsd_consent_facts: pd.DataFrame | None,
    landsd_monthly_observations: pd.DataFrame | None,
    tpb_application_facts: pd.DataFrame | None,
) -> pd.DataFrame:
    """Audit Mainland project-level evidence without fabricating transactions."""
    rows: list[dict[str, Any]] = []
    _append_mainland_source_row(
        rows,
        scope="current_annual_report_projects",
        source_dataset="shkp_annual_report_projects",
        source_frame=annual_report_projects,
        sales_status="not_available",
        pipeline_status="current_project_rows_disclosed",
        identity_status="annual_report_label_only_no_srpe_join",
        coverage_status="partial_project_disclosure_no_sales_register",
        model_use="Mainland_pipeline_and_exposure_context",
        caveat="Current annual-report project rows provide Mainland labels, Group interest and attributable GFA, but no project-month sales register or transaction value series.",
    )
    _append_mainland_source_row(
        rows,
        scope="historical_annual_report_projects",
        source_dataset="shkp_historical_annual_report_projects",
        source_frame=historical_annual_report_projects,
        sales_status="not_available",
        pipeline_status="historical_project_rows_disclosed",
        identity_status="annual_report_label_only_no_srpe_join",
        coverage_status="historical_project_evidence_no_sales_register",
        model_use="Mainland_historical_context_only",
        caveat="Historical annual-report rows materially broaden the Mainland project list, but they are report-vintage snapshots rather than a continuous project-level sales feed.",
    )

    recurring = _frame(recurring_facts)
    recurring_mainland = recurring.loc[_mainland_mask(recurring)].copy() if not recurring.empty else recurring
    periods = _date_bounds(recurring_mainland, ["period_start", "period_end"])
    rows.append(_mainland_row(
        coverage_id="shkp-mainland:recurring-period-facts",
        coverage_scope="mainland_recurring_period_facts",
        source_dataset="shkp_financial_model_recurring_portfolio_facts",
        source_rows=int(len(recurring_mainland)),
        distinct_project_count=0,
        period_start=periods[0],
        period_end=periods[1],
        project_level_sales_status="aggregate_only",
        project_level_pipeline_status="land_bank_and_segment_aggregates",
        identity_join_status="no_asset_or_project_id",
        coverage_status="mainland_rental_and_land_bank_aggregate_only",
        model_use="Mainland_recurring_income_context_only",
        caveat="Mainland rental/revenue and attributable land-bank facts exist at geography/segment period level; unit and currency rows must remain separate and are not project sales.",
    ))

    disclosed = _frame(disclosed_facts)
    disclosed_mainland = disclosed.loc[
        _text_series(disclosed, "metric").str.lower().str.contains("mainland")
    ].copy() if not disclosed.empty else disclosed
    disclosed_periods = _date_bounds(disclosed_mainland, ["period_start", "period_end", "target_period_end"])
    rows.append(_mainland_row(
        coverage_id="shkp-mainland:disclosed-backlog",
        coverage_scope="mainland_disclosed_backlog_and_land_bank",
        source_dataset="shkp_financial_model_disclosed_facts",
        source_rows=int(len(disclosed_mainland)),
        distinct_project_count=0,
        period_start=disclosed_periods[0],
        period_end=disclosed_periods[1],
        project_level_sales_status="aggregate_backlog_only",
        project_level_pipeline_status="aggregate_disclosed_backlog_only",
        identity_join_status="no_project_id",
        coverage_status="mainland_backlog_aggregate_not_project_level",
        model_use="directional_financial_anchor_only",
        caveat="Official Mainland contracted-sales backlog is useful as a directional financial anchor, but it cannot be allocated to individual projects from the current facts.",
    ))

    signals = _frame(project_month_signals)
    signal_has_mainland = bool(not signals.empty and "geography" in signals.columns and _mainland_mask(signals).any())
    rows.append(_mainland_row(
        coverage_id="shkp-mainland:srpe-project-month-signals",
        coverage_scope="mainland_project_month_transactions",
        source_dataset="shkp_indicative_project_month_signals_all_history",
        source_rows=int(_mainland_mask(signals).sum()) if signal_has_mainland else 0,
        distinct_project_count=int(_text_series(signals.loc[_mainland_mask(signals)], "phase_id").replace("", pd.NA).nunique(dropna=True)) if signal_has_mainland else 0,
        project_level_sales_status="not_available_mainland_scope",
        project_level_pipeline_status="not_available_mainland_scope",
        identity_join_status="srpe_layer_is_hong_kong_first_hand_residential_scope",
        coverage_status="not_covered",
        model_use="do_not_use_as_mainland_sales",
        caveat="The SRPE transaction layer currently covers Hong Kong first-hand residential routing; absence of Mainland rows is a scope gap, not zero Mainland sales.",
    ))

    for source_dataset, source_frame in (
        ("shkp_planning_evidence_crosswalk", planning_crosswalk),
        ("shkp_landsd_consent_facts", landsd_consent_facts),
        ("shkp_landsd_monthly_consent_observations", landsd_monthly_observations),
        ("shkp_tpb_application_facts", tpb_application_facts),
    ):
        rows.append(_mainland_row(
            coverage_id=f"shkp-mainland:{_stable_key(source_dataset)}",
            coverage_scope="hong_kong_planning_source_not_mainland",
            source_dataset=source_dataset,
            source_rows=0,
            distinct_project_count=0,
            project_level_sales_status="not_applicable",
            project_level_pipeline_status="not_applicable",
            identity_join_status="hong_kong_official_source",
            coverage_status="not_applicable_hong_kong_only_source",
            model_use="do_not_use_for_mainland",
            caveat="This repository's planning/LandsD/TPB source is Hong Kong-specific; it cannot establish Mainland project pipeline coverage.",
        ))
    return pd.DataFrame(rows, columns=MAINLAND_COVERAGE_COLUMNS)


def run_shkp_commercial_recurring_contract() -> dict[str, Any]:
    """Persist the commercial recurring and Mainland coverage research layers."""
    run_id = f"shkp-commercial-coverage-{uuid.uuid4()}"
    recurring_raw = load_latest_normalized("shkp_financial_model_recurring_portfolio_facts")
    if recurring_raw.empty:
        recurring_raw = build_shkp_recurring_portfolio_facts()
    pipeline_raw = load_latest_normalized("shkp_financial_model_asset_pipeline_capacity")
    if pipeline_raw.empty:
        pipeline_raw = build_shkp_asset_pipeline_capacity()
    catalog = load_latest_normalized("shkp_property_catalog")
    completed = load_latest_normalized("shkp_completed_properties")
    office = load_latest_normalized("rvd_office_rental_index_monthly")
    retail = load_latest_normalized("rvd_retail_index_monthly")
    recurring = build_shkp_commercial_recurring_facts(recurring_raw)
    pipeline = build_shkp_commercial_pipeline_capacity(pipeline_raw)
    market = build_shkp_commercial_market_context(office, retail)
    coverage = build_shkp_commercial_recurring_coverage(
        property_catalog=catalog,
        recurring_facts=recurring,
        completed_properties=completed,
        pipeline_capacity=pipeline,
        office_index=office,
        retail_index=retail,
    )

    annual = load_latest_normalized("shkp_annual_report_projects")
    historical_annual = load_latest_normalized("shkp_historical_annual_report_projects")
    disclosed = load_latest_normalized("shkp_financial_model_disclosed_facts")
    signals = load_latest_normalized("shkp_indicative_project_month_signals_all_history")
    mainland = build_shkp_mainland_project_coverage_audit(
        annual_report_projects=annual,
        historical_annual_report_projects=historical_annual,
        recurring_facts=recurring_raw,
        disclosed_facts=disclosed,
        project_month_signals=signals,
        planning_crosswalk=load_latest_normalized("shkp_planning_evidence_crosswalk"),
        landsd_consent_facts=load_latest_normalized("shkp_landsd_consent_facts"),
        landsd_monthly_observations=load_latest_normalized("shkp_landsd_monthly_consent_observations"),
        tpb_application_facts=load_latest_normalized("shkp_tpb_application_facts"),
    )

    lineage = {
        "lineage_type": "shkp_commercial_recurring_and_mainland_coverage",
        "run_id": run_id,
        "ticker": SHKP_TICKER,
        "research_only": True,
        "residential_signal_scope": "Hong Kong first-hand residential SRPE only",
        "commercial_policy": "period_facts_and_capacity_are_not_asset_level_rent_or_noi",
        "mainland_policy": "aggregate_disclosures_are_not_project_level_sales",
        "source_datasets": [
            "shkp_property_catalog",
            "shkp_financial_model_recurring_portfolio_facts",
            "shkp_financial_model_asset_pipeline_capacity",
            "shkp_completed_properties",
            "rvd_office_rental_index_monthly",
            "rvd_retail_index_monthly",
            "shkp_annual_report_projects",
            "shkp_historical_annual_report_projects",
            "shkp_financial_model_disclosed_facts",
            "shkp_indicative_project_month_signals_all_history",
            "shkp_planning_evidence_crosswalk",
            "shkp_landsd_consent_facts",
            "shkp_landsd_monthly_consent_observations",
            "shkp_tpb_application_facts",
        ],
    }
    frames = {
        COMMERCIAL_FACT_DATASET: recurring,
        COMMERCIAL_PIPELINE_DATASET: pipeline,
        COMMERCIAL_MARKET_CONTEXT_DATASET: market,
        COMMERCIAL_COVERAGE_DATASET: coverage,
        MAINLAND_COVERAGE_DATASET: mainland,
    }
    normalized = {
        name: save_normalized_dataset(
            name,
            frame,
            run_id=run_id,
            lineage_metadata={**lineage, "contract_dataset": name},
        )
        for name, frame in frames.items()
    }
    return {
        "mode": "shkp_commercial_recurring_and_mainland_coverage",
        "run_id": run_id,
        "ticker": SHKP_TICKER,
        "dataset_counts": {name: int(len(frame)) for name, frame in frames.items()},
        "commercial_coverage_rows": int(len(coverage)),
        "mainland_coverage_rows": int(len(mainland)),
        "mainland_project_transaction_rows": int(
            mainland.loc[mainland["coverage_scope"].eq("mainland_project_month_transactions"), "source_rows"].sum()
        ) if not mainland.empty else 0,
        "normalized": normalized,
    }
