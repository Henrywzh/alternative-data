import requests
import pandas as pd
from typing import Any, Dict

from ..config import CENTALINE_CCL_API_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot


CCL_COLUMNS = ['date', 'ccl_index', 'source_agency']


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
