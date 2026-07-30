import io
import logging
import pandas as pd
import requests
from ..config import (
    DEFAULT_HEADERS,
    TD_CROSS_BOUNDARY_PASSENGER_URL,
    TD_HZMB_VEHICULAR_TRAFFIC_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)


def fetch_td_cross_border_traffic() -> pd.DataFrame:
    """
    Fetch Transport Department monthly cross-boundary traffic from the
    official Monthly Traffic and Transport Digest CSVs (data.gov.hk):
    - table81e: HZMB vehicular traffic by vehicle class and bound
      (VEHICLE_CLASS_CODE 36 = HK private cars under the "Northbound Travel
      for Hong Kong Vehicles" (港车北上) scheme; BOUND_CODE "OB" = outbound
      from HK, i.e. the northbound leg)
    - table82: cross-boundary passenger traffic by control point, including
      ERLWK (Express Rail Link West Kowloon)
    """
    vehicle_response = requests.get(TD_HZMB_VEHICULAR_TRAFFIC_URL, headers=DEFAULT_HEADERS, timeout=30)
    vehicle_response.raise_for_status()
    save_raw_snapshot("td_hzmb_vehicular_traffic", vehicle_response.content, file_ext="csv", source_url=TD_HZMB_VEHICULAR_TRAFFIC_URL)
    vehicles = pd.read_csv(io.BytesIO(vehicle_response.content))

    passenger_response = requests.get(TD_CROSS_BOUNDARY_PASSENGER_URL, headers=DEFAULT_HEADERS, timeout=30)
    passenger_response.raise_for_status()
    save_raw_snapshot("td_cross_boundary_passengers", passenger_response.content, file_ext="csv", source_url=TD_CROSS_BOUNDARY_PASSENGER_URL)
    passengers = pd.read_csv(io.BytesIO(passenger_response.content))

    hzmb_total = vehicles.groupby("YR_MTH")["NO_VEHICLE"].sum().rename("hzmb_vehicular_traffic")
    hzmb_northbound = (
        vehicles[(vehicles["VEHICLE_CLASS_CODE"] == 36) & (vehicles["BOUND_CODE"] == "OB")]
        .groupby("YR_MTH")["NO_VEHICLE"]
        .sum()
        .rename("hzmb_northbound_hk_vehicles")
    )
    erlwk_total = (
        passengers[passengers["CONTROL_POINT_CODE"] == "ERLWK"]
        .groupby("YR_MTH")["NO_PAX"]
        .sum()
        .rename("express_rail_passengers")
    )

    combined = pd.concat([hzmb_total, hzmb_northbound, erlwk_total], axis=1).reset_index()
    combined = combined.rename(columns={"YR_MTH": "month"})
    combined["month"] = combined["month"].astype(str).str.replace(r"^(\d{4})(\d{2})$", r"\1-\2", regex=True)
    combined["hzmb_northbound_hk_vehicles"] = combined["hzmb_northbound_hk_vehicles"].fillna(0)
    for column in ("hzmb_vehicular_traffic", "hzmb_northbound_hk_vehicles", "express_rail_passengers"):
        combined[column] = pd.to_numeric(combined[column], errors="coerce")
    combined = combined.dropna(subset=["hzmb_vehicular_traffic", "express_rail_passengers"]).sort_values("month").reset_index(drop=True)
    combined.attrs.update(source_url=TD_HZMB_VEHICULAR_TRAFFIC_URL)
    return combined
