import io
import logging
import pandas as pd
import requests
from ..config import IMMD_DAILY_TRAFFIC_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

LAND_CONTROL_POINTS = [
    "Lo Wu",
    "Lok Ma Chau Spur Line",
    "Shenzhen Bay",
    "Heung Yuen Wai",
    "Hong Kong-Zhuhai-Macao Bridge",
    "Express Rail Link West Kowloon",
    "Lok Ma Chau",
    "Man Kam To",
    "Sha Tau Kok",
]


def fetch_immd_daily_traffic() -> pd.DataFrame:
    """
    Fetch HK Immigration Department daily passenger traffic statistics (2021-present).
    Computes:
    - hk_resident_departures & arrivals
    - mainland_visitor_arrivals & departures
    - hk_resident_net_flow (arrivals - departures, positive = net return/inflow, negative = net outflow)
    - mainland_visitor_net_retention (arrivals - departures, positive = net stay)
    - 7d and 30d moving averages
    """
    try:
        resp = requests.get(IMMD_DAILY_TRAFFIC_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        raw_path = save_raw_snapshot("immd_daily_traffic", resp.content, file_ext="csv", source_url=IMMD_DAILY_TRAFFIC_URL)

        csv_text = resp.content.decode("utf-8-sig")
        df = pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:
        logger.warning(f"Failed to fetch ImmD daily passenger traffic: {exc}")
        return pd.DataFrame()

    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()

    # Parse date DD-MM-YYYY
    df["date"] = pd.to_datetime(df["Date"], format="%d-%m-%Y", errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    # Clean numeric columns
    for col in ["Hong Kong Residents", "Mainland Visitors", "Other Visitors", "Total"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce").fillna(0)

    # Pivot/aggregate by date
    pivoted = df.groupby(["date", "Arrival / Departure"])[["Hong Kong Residents", "Mainland Visitors", "Other Visitors", "Total"]].sum().unstack("Arrival / Departure")

    records = []
    for dt, group in df.groupby("date"):
        dt_str = dt.strftime("%Y-%m-%d")
        arr = group[group["Arrival / Departure"] == "Arrival"]
        dep = group[group["Arrival / Departure"] == "Departure"]

        hk_arr = float(arr["Hong Kong Residents"].sum()) if not arr.empty else 0.0
        hk_dep = float(dep["Hong Kong Residents"].sum()) if not dep.empty else 0.0
        ml_arr = float(arr["Mainland Visitors"].sum()) if not arr.empty else 0.0
        ml_dep = float(dep["Mainland Visitors"].sum()) if not dep.empty else 0.0
        oth_arr = float(arr["Other Visitors"].sum()) if not arr.empty else 0.0
        oth_dep = float(dep["Other Visitors"].sum()) if not dep.empty else 0.0

        records.append({
            "date": dt_str,
            "hk_resident_arrivals": hk_arr,
            "hk_resident_departures": hk_dep,
            "hk_resident_net_flow": hk_arr - hk_dep,
            "mainland_visitor_arrivals": ml_arr,
            "mainland_visitor_departures": ml_dep,
            "mainland_visitor_net_retention": ml_arr - ml_dep,
            "other_visitor_arrivals": oth_arr,
            "other_visitor_departures": oth_dep,
            "total_arrivals": hk_arr + ml_arr + oth_arr,
            "total_departures": hk_dep + ml_dep + oth_dep,
        })

    res_df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)

    # Compute 7d and 30d moving averages
    for col in ["hk_resident_departures", "mainland_visitor_arrivals", "hk_resident_net_flow", "mainland_visitor_net_retention"]:
        res_df[f"{col}_7d_ma"] = res_df[col].rolling(window=7, min_periods=1).mean().round(1)
        res_df[f"{col}_30d_ma"] = res_df[col].rolling(window=30, min_periods=1).mean().round(1)

    res_df.attrs.update(raw_snapshot=str(raw_path), source_url=IMMD_DAILY_TRAFFIC_URL)
    return res_df
