import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
from typing import Dict, Any, Tuple

from ..config import MIDLAND_MARKET_INSIGHT_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

def fetch_midland_payload() -> Dict[str, Any]:
    response = requests.get(MIDLAND_MARKET_INSIGHT_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()

    raw_path = save_raw_snapshot("midland_market_insight", response.text, file_ext="html", source_url=MIDLAND_MARKET_INSIGHT_URL)

    soup = BeautifulSoup(response.text, 'html.parser')
    script_tag = soup.find('script', id='__NEXT_DATA__')
    if not script_tag or not script_tag.string:
        raise ValueError("Could not find __NEXT_DATA__ script tag on Midland Market Insight page.")

    data = json.loads(script_tag.string)
    page_props = data.get('props', {}).get('pageProps', {})
    # The raw HTML remains associated with the parsed outputs in the pipeline.
    page_props['_raw_snapshot'] = str(raw_path)
    page_props['_source_url'] = MIDLAND_MARKET_INSIGHT_URL
    return page_props

def parse_midland_mhpi(page_props: Dict[str, Any]) -> pd.DataFrame:
    raw_list = page_props.get('mrIndexWeekly', [])
    records = []
    for item in raw_list:
        raw_date = item.get('date', '')
        iso_date = raw_date.split('T')[0] if 'T' in raw_date else raw_date
        records.append({
            'date': iso_date,
            'mhpi_overall': item.get('mr_index'),
            'mhpi_hk_island': item.get('mr_index_hk'),
            'mhpi_kowloon': item.get('mr_index_kln'),
            'mhpi_new_territories': item.get('mr_index_nt'),
            'weekly_change_pct_overall': item.get('weekly_perc'),
            'source_agency': 'Midland Realty'
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values('date').reset_index(drop=True)
    return df


def parse_midland_mhpi_monthly(page_props: Dict[str, Any]) -> pd.DataFrame:
    """Parse Midland's monthly price/volume payload without collapsing fields."""
    raw_list = page_props.get("mrIndex", [])
    rows = []
    for item in raw_list:
        raw_date = item.get("date", "")
        date = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(date):
            continue
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "mhpi_overall": item.get("mr_index"),
                "mhpi_hk_island": item.get("mr_index_hk"),
                "mhpi_kowloon": item.get("mr_index_kln"),
                "mhpi_new_territories": item.get("mr_index_nt"),
                "transaction_count_total": item.get("tx_count"),
                "transaction_count_hk_island": item.get("tx_count_hk"),
                "transaction_count_kowloon": item.get("tx_count_kln"),
                "transaction_count_new_territories": item.get("tx_count_nt"),
                "firsthand_transaction_count_total": item.get("fh_tx_count"),
                "firsthand_transaction_count_hk_island": item.get("fh_tx_count_hk"),
                "firsthand_transaction_count_kowloon": item.get("fh_tx_count_kln"),
                "firsthand_transaction_count_new_territories": item.get("fh_tx_count_nt"),
                "net_ft_price_overall": item.get("net_ft_price"),
                "net_ft_price_hk_island": item.get("net_ft_price_hk"),
                "net_ft_price_kowloon": item.get("net_ft_price_kln"),
                "net_ft_price_new_territories": item.get("net_ft_price_nt"),
                "ft_price_overall": item.get("ft_price"),
                "ft_price_hk_island": item.get("ft_price_hk"),
                "ft_price_kowloon": item.get("ft_price_kln"),
                "ft_price_new_territories": item.get("ft_price_nt"),
                "net_ft_rent_overall": item.get("net_ft_rent"),
                "ft_rent_overall": item.get("ft_rent"),
                "source_agency": "Midland Realty",
            }
        )
    columns = [
        "date", "mhpi_overall", "mhpi_hk_island", "mhpi_kowloon", "mhpi_new_territories",
        "transaction_count_total", "transaction_count_hk_island", "transaction_count_kowloon",
        "transaction_count_new_territories", "firsthand_transaction_count_total",
        "firsthand_transaction_count_hk_island", "firsthand_transaction_count_kowloon",
        "firsthand_transaction_count_new_territories", "net_ft_price_overall", "net_ft_price_hk_island",
        "net_ft_price_kowloon", "net_ft_price_new_territories", "ft_price_overall", "ft_price_hk_island",
        "ft_price_kowloon", "ft_price_new_territories", "net_ft_rent_overall", "ft_rent_overall",
        "source_agency",
    ]
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        result = result.sort_values("date").reset_index(drop=True)
    return result


MIDLAND_ECONOMIC_INDICATORS = {
    "Mortgage_Interest_Rate": "percent",
    "Rental_Yield": "percent",
    "Real_Saving_Interest_Rate": "percent",
    "Hang_Seng_Index": "index_points",
    "US_Dollar_Index": "index_points",
    "Unemployment_Rate": "percent",
    "Affordability_Ratio": "percent",
    "Rental_Affordability_Ratio": "percent",
    "House_Price_to_Income_Ratio": "ratio",
}

# Persisted field/unit metadata for the wide monthly payload and the long
# snapshot contracts.  Consumers should use this dictionary instead of
# inferring units from abbreviated source field names.
MIDLAND_MHPI_FIELD_UNITS = {
    "mhpi_overall": "index_points",
    "mhpi_hk_island": "index_points",
    "mhpi_kowloon": "index_points",
    "mhpi_new_territories": "index_points",
    "transaction_count_total": "transactions",
    "transaction_count_hk_island": "transactions",
    "transaction_count_kowloon": "transactions",
    "transaction_count_new_territories": "transactions",
    "firsthand_transaction_count_total": "transactions",
    "firsthand_transaction_count_hk_island": "transactions",
    "firsthand_transaction_count_kowloon": "transactions",
    "firsthand_transaction_count_new_territories": "transactions",
    "net_ft_price_overall": "HKD_per_sqft_net",
    "net_ft_price_hk_island": "HKD_per_sqft_net",
    "net_ft_price_kowloon": "HKD_per_sqft_net",
    "net_ft_price_new_territories": "HKD_per_sqft_net",
    "ft_price_overall": "HKD_per_sqft_gross",
    "ft_price_hk_island": "HKD_per_sqft_gross",
    "ft_price_kowloon": "HKD_per_sqft_gross",
    "ft_price_new_territories": "HKD_per_sqft_gross",
    "net_ft_rent_overall": "HKD_per_sqft_month_net",
    "ft_rent_overall": "HKD_per_sqft_month_gross",
}

MIDLAND_MARKET_METRIC_UNITS = {
    "avg_ft_price": "HKD_per_sqft_gross",
    "avg_net_ft_price": "HKD_per_sqft_net",
    "avg_ft_rent": "HKD_per_sqft_month_gross",
    "avg_net_ft_rent": "HKD_per_sqft_month_net",
    "max_ft_price": "HKD_per_sqft_gross",
    "max_net_ft_price": "HKD_per_sqft_net",
    "min_ft_price": "HKD_per_sqft_gross",
    "min_net_ft_price": "HKD_per_sqft_net",
    "max_ft_rent": "HKD_per_sqft_month_gross",
    "max_net_ft_rent": "HKD_per_sqft_month_net",
    "min_ft_rent": "HKD_per_sqft_month_gross",
    "min_net_ft_rent": "HKD_per_sqft_month_net",
    "total_tx_count": "transactions",
    "total_rent_tx_count": "transactions",
    "total_tx_amount": "HKD",
    "total_rent_tx_amount": "HKD",
    "circulate_rate": "percent",
    "total_no_of_unit": "units",
    "avg_ft_price_chg": "percent",
    "avg_net_ft_price_chg": "percent",
    "avg_ft_rent_chg": "percent",
    "avg_net_ft_rent_chg": "percent",
}

MIDLAND_TRANSACTION_METRIC_UNITS = {
    "number": "transactions",
    "amount": "HKD_bn",
    "number_chg": "percent",
    "amount_chg": "percent",
}


def build_midland_field_dictionary() -> pd.DataFrame:
    """Return the persisted field/unit dictionary for Midland contracts."""
    rows = []
    for field, unit in MIDLAND_MHPI_FIELD_UNITS.items():
        rows.append({
            "dataset": "midland_mhpi_monthly",
            "field_name": field,
            "metric_group": "monthly_price_volume",
            "unit": unit,
            "source_field": field,
            "description": "Monthly Midland price, rent or transaction measure",
            "source_agency": "Midland Realty",
        })
    for field, unit in MIDLAND_ECONOMIC_INDICATORS.items():
        rows.append({
            "dataset": "midland_economic_indicators_monthly",
            "field_name": "value",
            "metric_group": field,
            "unit": unit,
            "source_field": field,
            "description": "Monthly Midland economic indicator",
            "source_agency": "Midland Realty",
        })
    for field, unit in MIDLAND_MARKET_METRIC_UNITS.items():
        rows.append({
            "dataset": "midland_market_snapshots",
            "field_name": "value",
            "metric_group": field,
            "unit": unit,
            "source_field": field,
            "description": "Midland current or previous rolling-window market statistic",
            "source_agency": "Midland Realty",
        })
    for field, unit in MIDLAND_TRANSACTION_METRIC_UNITS.items():
        rows.append({
            "dataset": "midland_transaction_summary_snapshot",
            "field_name": "value",
            "metric_group": field,
            "unit": unit,
            "source_field": field,
            "description": "Midland current registration summary measure",
            "source_agency": "Midland Realty",
        })
    return pd.DataFrame(rows, columns=[
        "dataset", "field_name", "metric_group", "unit", "source_field", "description", "source_agency"
    ])


def parse_midland_economic_indicators(page_props: Dict[str, Any]) -> pd.DataFrame:
    """Convert Midland's macro block to a long, source-field-preserving table."""
    rows = []
    for item in page_props.get("economicIndicators", []):
        date = pd.to_datetime(item.get("date"), errors="coerce")
        if pd.isna(date):
            continue
        for field, unit in MIDLAND_ECONOMIC_INDICATORS.items():
            value = pd.to_numeric(item.get(field), errors="coerce")
            if pd.isna(value):
                continue
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "indicator_name": field,
                    "value": float(value),
                    "unit": unit,
                    "source_field": field,
                    "source_agency": "Midland Realty",
                }
            )
    columns = ["date", "indicator_name", "value", "unit", "source_field", "source_agency"]
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        result = result.sort_values(["indicator_name", "date"]).reset_index(drop=True)
    return result

def parse_midland_confidence(page_props: Dict[str, Any]) -> pd.DataFrame:
    raw_list = page_props.get('confidenceIndex', [])
    records = []
    for item in raw_list:
        raw_date = item.get('date', '')
        iso_date = raw_date.split('T')[0] if 'T' in raw_date else raw_date
        records.append({
            'date': iso_date,
            'confidence_index': item.get('confidence_index'),
            'confidence_avg_index': item.get('confidence_avg_index'),
            'weekly_change_pct': item.get('weekly_perc'),
            'source_agency': 'Midland Realty'
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values('date').reset_index(drop=True)
    return df

def parse_midland_estate_counts(page_props: Dict[str, Any]) -> pd.DataFrame:
    result_obj = page_props.get('estatesTransactionCount', {})
    items = result_obj.get('result', []) if isinstance(result_obj, dict) else []

    records = []
    for item in items:
        estate_id = item.get('id')
        estate_name = item.get('name')
        region_name = item.get('region', {}).get('name') if isinstance(item.get('region'), dict) else None
        district_name = item.get('district', {}).get('name') if isinstance(item.get('district'), dict) else None

        market_stat = item.get('market_stat', {})
        tx_count = market_stat.get('tx_count') if isinstance(market_stat, dict) else None
        if tx_count is None and isinstance(market_stat, dict):
            tx_count = market_stat.get('monthly', {}).get('tx_count')

        records.append({
            'estate_id': estate_id,
            'estate_name': estate_name,
            'region_name': region_name,
            'district_name': district_name,
            'transaction_count': tx_count,
            'source_agency': 'Midland Realty'
        })
    return pd.DataFrame(records)

def run_midland_ingestion() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    props = fetch_midland_payload()
    outputs = parse_midland_mhpi(props), parse_midland_confidence(props), parse_midland_estate_counts(props)
    for df in outputs:
        df.attrs.update(raw_snapshot=props.get('_raw_snapshot'), source_url=props.get('_source_url'))
    return outputs


def run_midland_monthly_ingestion() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch one page and return the Tranche 2 monthly contracts."""
    props = fetch_midland_payload()
    outputs = parse_midland_mhpi_monthly(props), parse_midland_economic_indicators(props)
    for df in outputs:
        df.attrs.update(raw_snapshot=props.get("_raw_snapshot"), source_url=props.get("_source_url"))
    return outputs


_MARKET_SNAPSHOT_METRICS = (
    "avg_ft_price", "avg_net_ft_price", "avg_ft_rent", "avg_net_ft_rent",
    "max_ft_price", "max_net_ft_price", "min_ft_price", "min_net_ft_price",
    "total_tx_count", "total_rent_tx_count", "total_tx_amount", "total_rent_tx_amount",
    "circulate_rate", "total_no_of_unit",
    "avg_ft_price_chg", "avg_net_ft_price_chg", "avg_ft_rent_chg", "avg_net_ft_rent_chg",
)


def parse_midland_market_snapshots(page_props: Dict[str, Any]) -> pd.DataFrame:
    """Parse current/previous rolling-window market stats with window metadata."""
    rows = []
    for source_key, scope_type in (("marketStatAll", "all"), ("marketStatRegion", "region"), ("marketStatDistrict", "district")):
        for item in page_props.get(source_key, []) or []:
            if not isinstance(item, dict) or not isinstance(item.get("daily"), dict):
                continue
            daily = item["daily"]
            date = pd.to_datetime(daily.get("date"), errors="coerce")
            if pd.isna(date):
                continue
            scope_id = str(item.get("id", ""))
            scope_name = item.get("name", "All Hong Kong")
            for period_type, prefix in (("current", ""), ("previous_window", "pre_")):
                for metric in _MARKET_SNAPSHOT_METRICS:
                    value = pd.to_numeric(daily.get(f"{prefix}{metric}"), errors="coerce")
                    if pd.isna(value):
                        continue
                    window_start = daily.get(
                        f"{prefix}window_start",
                        daily.get(f"{prefix}period_start", daily.get(f"{prefix}start_date")),
                    )
                    window_end = daily.get(
                        f"{prefix}window_end",
                        daily.get(f"{prefix}period_end", daily.get(f"{prefix}end_date")),
                    )
                    if period_type == "previous_window":
                        window_start = window_start or daily.get("previous_window_start")
                        window_end = window_end or daily.get("previous_window_end")
                    rows.append(
                        {
                            "date": date.strftime("%Y-%m-%d"),
                            "as_of_date": date.strftime("%Y-%m-%d"),
                            "scope_type": scope_type,
                            "scope_id": scope_id,
                            "scope_name": scope_name,
                            "period_type": period_type,
                            "window_start": window_start,
                            "window_end": window_end,
                            "metric": metric,
                            "value": float(value),
                            "unit": MIDLAND_MARKET_METRIC_UNITS.get(metric),
                            "source_field": f"{prefix}{metric}",
                            "source_agency": "Midland Realty",
                        }
                    )
    columns = [
        "date", "as_of_date", "scope_type", "scope_id", "scope_name", "period_type",
        "window_start", "window_end", "metric", "value", "unit", "source_field", "source_agency",
    ]
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        result = result.sort_values(["scope_type", "scope_id", "period_type", "metric"]).reset_index(drop=True)
    return result


def parse_midland_transaction_summary_snapshot(page_props: Dict[str, Any]) -> pd.DataFrame:
    """Expand the current transaction summary without treating it as history."""
    records = page_props.get("langRegRecords", []) or []
    columns = [
        "date", "as_of_date", "update_date", "asset_class", "metric", "value", "unit", "source_field", "source_agency"
    ]
    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        date = pd.to_datetime(record.get("as_of_date"), errors="coerce")
        if pd.isna(date):
            continue
        update_date = pd.to_datetime(record.get("update_date"), errors="coerce", utc=True)
        update_value = update_date.isoformat() if not pd.isna(update_date) else None
        for asset_class, values in record.items():
            if asset_class in {"as_of_date", "update_date"} or not isinstance(values, dict):
                continue
            for metric in ("number", "amount", "number_chg", "amount_chg"):
                value = pd.to_numeric(values.get(metric), errors="coerce")
                if pd.isna(value):
                    continue
                rows.append(
                    {
                        "date": date.strftime("%Y-%m-%d"),
                        "as_of_date": date.strftime("%Y-%m-%d"),
                        "update_date": update_value,
                        "asset_class": asset_class,
                        "metric": metric,
                        "value": float(value),
                        "unit": MIDLAND_TRANSACTION_METRIC_UNITS[metric],
                        "source_field": f"{asset_class}.{metric}",
                        "source_agency": "Midland Realty",
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def parse_midland_property_event_hints(page_props: Dict[str, Any]) -> pd.DataFrame:
    """Keep Midland property events as research hints until primary sourcing."""
    columns = ["event_date", "event_id", "description", "source_url", "status", "source_agency"]
    rows = []
    for item in page_props.get("propertyEvent", []) or []:
        if not isinstance(item, dict):
            continue
        event_date = pd.to_datetime(item.get("post_date"), errors="coerce")
        if pd.isna(event_date) or not item.get("description"):
            continue
        rows.append(
            {
                "event_date": event_date.strftime("%Y-%m-%d"),
                "event_id": str(item.get("id", "")),
                "description": str(item.get("description")),
                "source_url": "https://www.midland.com.hk/zh-hk/market-insight",
                "status": "research_only",
                "source_agency": "Midland Realty",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def run_midland_snapshot_ingestion() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    props = fetch_midland_payload()
    outputs = (
        parse_midland_market_snapshots(props),
        parse_midland_transaction_summary_snapshot(props),
        parse_midland_property_event_hints(props),
    )
    for df in outputs:
        df.attrs.update(raw_snapshot=props.get("_raw_snapshot"), source_url=props.get("_source_url"))
    return outputs
