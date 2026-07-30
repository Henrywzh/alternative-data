import requests
import pandas as pd
from typing import Any, Dict

from ..config import CENTALINE_CCL_API_URL, CENTALINE_INDEX_API_BASE_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot


CCL_COLUMNS = ['date', 'ccl_index', 'source_agency']
CENTALINE_HISTORY_COLUMNS = ["date", "series_id", "metric", "index_value", "source_agency"]
CENTALINE_SNAPSHOT_COLUMNS = [
    "date", "series_id", "metric", "index_value", "vote_date", "publish_date", "source_agency"
]

_CCI_SERIES_LABELS = {
    "cci": "overall",
    "hk": "hk_island",
    "kln": "kowloon",
    "nte": "new_territories_east",
    "ntw": "new_territories_west",
    "big": "large_units",
    "normal": "small_units",
    "estate": "estates",
}
_CSI_HISTORY_LABELS = {
    "residPrice": "residential_price",
    "residRental": "residential_rental",
}


def parse_centaline_ccl_payload(payload: Dict[str, Any]) -> pd.DataFrame:
    """Parse the documented CCL object returned by Centaline's JSON endpoint.

    This deliberately accepts only the explicit ``ccl.chartData`` arrays.  It
    never evaluates or otherwise executes response content.
    """
    chart_data = payload.get('ccl', {}).get('chartData', {})
    dates = chart_data.get('date', [])
    indices = chart_data.get('index', [])
    if not isinstance(dates, list) or not isinstance(indices, list) or len(dates) != len(indices):
        return pd.DataFrame(columns=CCL_COLUMNS)

    df = pd.DataFrame({'date': dates, 'ccl_index': indices})
    if df.empty:
        return pd.DataFrame(columns=CCL_COLUMNS)
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df['ccl_index'] = pd.to_numeric(df['ccl_index'], errors='coerce')
    df = df.dropna(subset=['date', 'ccl_index'])
    if df['date'].duplicated().any():
        return pd.DataFrame(columns=CCL_COLUMNS)
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    df['source_agency'] = 'Centaline Property Agency'
    return df.sort_values('date').reset_index(drop=True)[CCL_COLUMNS]


def fetch_centaline_ccl() -> pd.DataFrame:
    """
    Fetch Centaline CCL weekly historical index series from first-party JSON.
    Returns normalized DataFrame with columns ['date', 'ccl_index', 'source_agency'].
    """
    response = requests.get(CENTALINE_CCL_API_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    raw_path = save_raw_snapshot(
        "centaline_ccl", response.text, file_ext="json", source_url=CENTALINE_CCL_API_URL,
    )
    df = parse_centaline_ccl_payload(response.json())
    df.attrs['raw_snapshot'] = str(raw_path)
    df.attrs['source_url'] = CENTALINE_CCL_API_URL
    return df


def _empty_centaline(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _parse_chart_data(chart_data: Any, *, series_id: str, metric: str) -> pd.DataFrame:
    if not isinstance(chart_data, dict):
        return _empty_centaline(CENTALINE_HISTORY_COLUMNS)
    dates = chart_data.get("date")
    if not isinstance(dates, list) or not dates:
        return _empty_centaline(CENTALINE_HISTORY_COLUMNS)
    rows: list[dict[str, Any]] = []
    for key, values in chart_data.items():
        if key == "date" or not isinstance(values, list) or len(values) != len(dates):
            continue
        for date, value in zip(dates, values):
            parsed_date = pd.to_datetime(date, errors="coerce")
            parsed_value = pd.to_numeric(value, errors="coerce")
            if pd.isna(parsed_date) or pd.isna(parsed_value):
                continue
            rows.append({
                "date": parsed_date.strftime("%Y-%m-%d"),
                "series_id": _CSI_HISTORY_LABELS.get(key, series_id if key == "index" else key),
                "metric": metric,
                "index_value": float(parsed_value),
                "source_agency": "Centaline Property Agency",
            })
    if not rows:
        return _empty_centaline(CENTALINE_HISTORY_COLUMNS)
    frame = pd.DataFrame(rows, columns=CENTALINE_HISTORY_COLUMNS)
    if frame.duplicated(subset=["date", "series_id", "metric"]).any():
        return _empty_centaline(CENTALINE_HISTORY_COLUMNS)
    return frame.sort_values(["series_id", "date"]).reset_index(drop=True)


def parse_centaline_index_history(payload: Dict[str, Any], index_code: str) -> pd.DataFrame:
    """Parse only dated chart observations; current regional values are separate snapshots."""
    index_code = index_code.upper()
    if index_code == "CSI":
        return _parse_chart_data(payload.get("chartData"), series_id="csi", metric="sentiment")
    root = "cri" if index_code == "CRI" else "cci"
    metric = "rental_index" if index_code == "CRI" else "price_index"
    frames = [_parse_chart_data(payload.get(root, {}).get("chartData"), series_id="overall", metric=metric)]
    if index_code == "CRI":
        frames.append(
            _parse_chart_data(
                payload.get("criYield", {}).get("chartData"),
                series_id="overall",
                metric="rental_yield",
            )
        )
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else _empty_centaline(CENTALINE_HISTORY_COLUMNS)


def parse_centaline_index_snapshots(payload: Dict[str, Any], index_code: str) -> pd.DataFrame:
    """Parse current-period values without treating them as historical points."""
    index_code = index_code.upper()
    rows: list[dict[str, Any]] = []
    if index_code == "CSI":
        fields = {
            "residPrice": "residential_price", "residRental": "residential_rental",
            "officePrice": "office_price", "officeRental": "office_rental",
            "industrialPrice": "industrial_price", "industrialRental": "industrial_rental",
            "retailPrice": "retail_price", "retailRental": "retail_rental",
            "index": "overall",
        }
        root = payload
        metric = "sentiment"
        for field, series_id in fields.items():
            value = pd.to_numeric(root.get(field), errors="coerce")
            if pd.isna(value):
                continue
            vote_timestamp = pd.to_datetime(root.get("voteDate"), errors="coerce")
            if pd.isna(vote_timestamp):
                continue
            rows.append({
                "date": vote_timestamp.strftime("%Y-%m-%d"),
                "series_id": series_id,
                "metric": metric,
                "index_value": float(value),
                "vote_date": root.get("voteDate"),
                "publish_date": root.get("publishDate"),
                "source_agency": "Centaline Property Agency",
            })
    else:
        metric = "rental_index" if index_code == "CRI" else "price_index"
        for key, block in payload.items():
            if not isinstance(block, dict) or "index" not in block or key.endswith("Yield") or key in {"dateRange", "yieldDateRange"}:
                continue
            value = pd.to_numeric(block.get("index"), errors="coerce")
            vote_date = pd.to_datetime(block.get("voteDate"), errors="coerce")
            if pd.isna(value) or pd.isna(vote_date):
                continue
            rows.append({
                "date": vote_date.strftime("%Y-%m-%d"),
                "series_id": _CCI_SERIES_LABELS.get(key, key),
                "metric": metric,
                "index_value": float(value),
                "vote_date": block.get("voteDate"),
                "publish_date": block.get("publishDate"),
                "source_agency": "Centaline Property Agency",
            })
            if index_code == "CRI":
                yield_block = payload.get(f"{key}Yield")
                yield_value = pd.to_numeric(yield_block.get("index"), errors="coerce") if isinstance(yield_block, dict) else None
                if yield_block and not pd.isna(yield_value):
                    rows.append({
                        "date": vote_date.strftime("%Y-%m-%d"),
                        "series_id": _CCI_SERIES_LABELS.get(key, key),
                        "metric": "rental_yield",
                        "index_value": float(yield_value),
                        "vote_date": yield_block.get("voteDate"),
                        "publish_date": yield_block.get("publishDate"),
                        "source_agency": "Centaline Property Agency",
                    })
    if not rows:
        return _empty_centaline(CENTALINE_SNAPSHOT_COLUMNS)
    result = pd.DataFrame(rows, columns=CENTALINE_SNAPSHOT_COLUMNS)
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return result.dropna(subset=["date", "index_value"]).reset_index(drop=True)


def fetch_centaline_index_bundle(index_code: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch one CCI-family endpoint and return history plus current snapshots."""
    index_code = index_code.upper()
    url = f"{CENTALINE_INDEX_API_BASE_URL}/{index_code}"
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    raw_path = save_raw_snapshot(f"centaline_{index_code.lower()}", response.text, file_ext="json", source_url=url)
    payload = response.json()
    history = parse_centaline_index_history(payload, index_code)
    snapshots = parse_centaline_index_snapshots(payload, index_code)
    for frame in (history, snapshots):
        frame.attrs["raw_snapshot"] = str(raw_path)
        frame.attrs["source_url"] = url
    return history, snapshots
