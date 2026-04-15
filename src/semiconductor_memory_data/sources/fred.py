from __future__ import annotations

import json
import os

import requests

from semiconductor_memory_data.models import FredPoint, Snapshot
from semiconductor_memory_data.sources.config import FRED_SERIES, USER_AGENT


class FredSource:
    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("FRED_API_KEY") or os.environ.get("SEMICONDUCTOR_FRED_API_KEY", "")
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)

    def fetch_snapshots(self, series_ids: list[str] | None = None) -> list[Snapshot]:
        """Fetch one Snapshot per FRED series."""
        targets = {sid: name for sid, name in FRED_SERIES.items() if series_ids is None or sid in series_ids}
        snapshots: list[Snapshot] = []
        for series_id in targets:
            url = (
                f"{self.BASE_URL}"
                f"?series_id={series_id}"
                f"&api_key={self.api_key}"
                f"&file_type=json"
                f"&observation_start=2020-01-01"
            )
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            snapshots.append(
                Snapshot(
                    name=f"fred_{series_id.lower()}",
                    source_url=self.BASE_URL + f"?series_id={series_id}",
                    body=response.text,
                )
            )
        return snapshots

    def extract(self, snapshots: list[Snapshot]) -> list[FredPoint]:
        """Parse observations from FRED JSON responses; skip missing values ('.')."""
        points: list[FredPoint] = []
        for snapshot in snapshots:
            payload = json.loads(snapshot.body)
            # Derive series_id from snapshot name: "fred_pcu334413334413" -> "PCU334413334413"
            series_id = snapshot.name.removeprefix("fred_").upper()
            series_name = FRED_SERIES.get(series_id, series_id)
            for obs in payload.get("observations", []):
                raw_value = obs.get("value", ".")
                if raw_value == ".":
                    continue
                points.append(
                    FredPoint(
                        date=str(obs["date"]),
                        series_id=series_id,
                        series_name=series_name,
                        value=float(raw_value),
                    )
                )
        return points
