"""Research-only policy-event contracts and primary-source catalogue."""

from __future__ import annotations

import pandas as pd


PRIMARY_POLICY_SOURCES = [
    {
        "source_id": "hkma_press_releases",
        "source_agency": "Hong Kong Monetary Authority",
        "source_url": "https://www.hkma.gov.hk/eng/news-and-media/press-releases/",
        "event_scope": "LTV, DSR, countercyclical buffer, mortgage and banking policy",
        "status": "catalog_only",
    },
    {
        "source_id": "hk_government_press_releases",
        "source_agency": "Hong Kong Government Information Services",
        "source_url": "https://www.info.gov.hk/gia/general/today.htm",
        "event_scope": "Stamp duty, housing policy and official announcements",
        "status": "catalog_only",
    },
    {
        "source_id": "lands_department_land_sales",
        "source_agency": "Lands Department",
        "source_url": "https://www.landsd.gov.hk/en/resources/land-info-stat/land-sale/land-sale-records.html",
        "event_scope": "Land tender, lease modification and land-exchange events",
        "status": "catalog_only",
    },
    {
        "source_id": "hkex_news",
        "source_agency": "HKEXnews",
        "source_url": "https://www1.hkexnews.hk/search/titlesearch.xhtml",
        "event_scope": "Issuer announcements, results, financing and ownership events",
        "status": "catalog_only",
    },
]


def build_primary_policy_sources_catalog() -> pd.DataFrame:
    columns = ["source_id", "source_agency", "source_url", "event_scope", "status"]
    return pd.DataFrame(PRIMARY_POLICY_SOURCES, columns=columns)


def validate_developer_project_registry(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return the curated registry plus contract errors without fuzzy attribution."""
    required = {
        "stock_code", "listed_company_en", "subsidiary_spv_name", "project_name_en",
        "project_aliases", "asset_type", "ownership_pct", "source_document",
        "last_verified_date", "effective_from", "effective_to",
    }
    errors: list[str] = []
    missing = sorted(required - set(frame.columns))
    if missing:
        return frame, [f"missing registry columns: {', '.join(missing)}"]
    result = frame.copy()
    stock_code = result["stock_code"].astype("string").str.strip()
    missing_stock_code = stock_code.isna() | stock_code.eq("") | stock_code.str.lower().eq("nan")
    result["stock_code"] = stock_code.str.zfill(4)
    result["ownership_pct"] = pd.to_numeric(result["ownership_pct"], errors="coerce")
    if missing_stock_code.any():
        errors.append("stock_code contains empty values")
    if result["ownership_pct"].isna().any() or (~result["ownership_pct"].between(0, 100)).any():
        errors.append("ownership_pct must be numeric and between 0 and 100")
    for column in (
        "listed_company_en", "subsidiary_spv_name", "project_name_en", "asset_type", "source_document"
    ):
        values = result[column].astype("string").str.strip()
        if values.isna().any() or values.eq("").any() or values.str.lower().eq("nan").any():
            errors.append(f"{column} contains empty values")
    for column in ("last_verified_date", "effective_from", "effective_to"):
        values = result[column].astype("string").str.strip()
        nonempty = values.notna() & values.ne("") & values.str.lower().ne("nan")
        if column != "effective_to" and (~nonempty).any():
            errors.append(f"{column} contains empty values")
        parsed = pd.to_datetime(values.where(nonempty), errors="coerce")
        if parsed[nonempty].isna().any():
            errors.append(f"{column} contains invalid dates")
    if result.duplicated(subset=["stock_code", "project_name_en", "effective_from"]).any():
        errors.append("duplicate stock/project/effective_from registry keys")
    return result, errors
