import logging
import pandas as pd
import requests
from ..config import CSD_POPULATION_ESTIMATES_API_URL, CSD_VITAL_EVENTS_API_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)


def _fetch_table(url: str, dataset_name: str) -> list[dict]:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    response.raise_for_status()
    save_raw_snapshot(dataset_name, response.content, file_ext="json", source_url=url)
    return response.json().get("dataSet", [])


def fetch_csd_population_estimates() -> pd.DataFrame:
    """
    Fetch C&SD half-yearly population estimates, natural change and net
    movement (110-01001: population by sex/age; 110-01003: vital events and
    net movement split between One-way Permit holders and others).

    Half-yearly, not annual: C&SD publishes these as of end-June and
    end-December each year, so `period` is "YYYY-06"/"YYYY-12" rather than
    a single yearly figure.
    """
    pop_rows = _fetch_table(CSD_POPULATION_ESTIMATES_API_URL, "csd_population_estimates")
    vital_rows = _fetch_table(CSD_VITAL_EVENTS_API_URL, "csd_vital_events")

    population: dict[str, float] = {}
    for item in pop_rows:
        if (
            item.get("sv") == "POP"
            and item.get("SEX", "") == ""
            and item.get("AGE", "") == ""
            and "Number" in str(item.get("svDesc", ""))
        ):
            figure = item.get("figure")
            if isinstance(figure, (int, float)):
                population[str(item["period"])] = float(figure)

    natural_growth: dict[str, float] = {}
    net_movement: dict[str, float] = {}
    for item in vital_rows:
        period = str(item.get("period", ""))
        figure = item.get("figure")
        if not isinstance(figure, (int, float)):
            continue
        if item.get("sv") == "NC":
            natural_growth[period] = float(figure)
        elif item.get("sv") == "NM" and item.get("TYPE_INFLOW", "") == "":
            # TYPE_INFLOW == "" is the Total row; "one-way" and "others" are
            # the same total's own breakdown, not additional periods.
            net_movement[period] = float(figure)

    periods = sorted(set(population) | set(natural_growth) | set(net_movement))
    records = [
        {
            "period": f"{period[:4]}-{period[4:6]}",
            "mid_year_population_thousands": population.get(period),
            "natural_growth_thousands": natural_growth.get(period),
            "net_movement_thousands": net_movement.get(period),
        }
        for period in periods
    ]
    df = pd.DataFrame(records)
    df.attrs.update(source_url=CSD_POPULATION_ESTIMATES_API_URL)
    return df
