from __future__ import annotations

from datetime import datetime, timezone
import io
import logging
import zipfile

import pandas as pd
import requests

from .config import BIS_CREDIT_GAP_BULK_URL, BIS_SDMX_BASE_URL, DEFAULT_HEADERS, DEFAULT_TARGET_AREAS
from .models import BisObservation, BisSeriesMeta

logger = logging.getLogger(__name__)


class BisMacroClient:
    def __init__(
        self,
        base_url: str = BIS_SDMX_BASE_URL,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch_dataset_csv(self, dataset_id: str, query_filter: str = "") -> pd.DataFrame:
        url = f"{self.base_url}/{dataset_id}/{query_filter}?format=csv"
        response = self.session.get(url, headers=DEFAULT_HEADERS, timeout=self.timeout_seconds)
        response.raise_for_status()
        return pd.read_csv(io.StringIO(response.text))

    def fetch_credit_gap_bulk(self, url: str = BIS_CREDIT_GAP_BULK_URL) -> bytes:
        """Fetch BIS's current full-history flat CSV ZIP.

        The public BIS portal's older SDMX API route is not stable enough for
        a reproducible backfill.  The bulk ZIP is the official full-topic
        artifact and retains all BIS dimensions in the raw snapshot.
        """
        response = self.session.get(url, headers=DEFAULT_HEADERS, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.content

    @staticmethod
    def read_credit_gap_bulk(payload: bytes) -> pd.DataFrame:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_members:
                raise ValueError("BIS credit-gap ZIP contains no CSV member")
            with archive.open(csv_members[0]) as handle:
                return pd.read_csv(handle)

    @staticmethod
    def _short_code(value: object) -> str:
        return str(value).split(":", 1)[0].strip()

    @classmethod
    def _normalize_bulk_columns(cls, df: pd.DataFrame) -> pd.DataFrame:
        normalized = df.copy()
        normalized.columns = [cls._short_code(column) for column in normalized.columns]
        return normalized

    def parse_credit_gap_records(
        self,
        df: pd.DataFrame,
        target_areas: list[str] | None = None,
    ) -> tuple[list[BisSeriesMeta], list[BisObservation]]:
        fetched_at = datetime.now(timezone.utc).isoformat()
        areas = target_areas or DEFAULT_TARGET_AREAS
        meta_list: list[BisSeriesMeta] = []
        obs_list: list[BisObservation] = []
        if df.empty:
            return meta_list, obs_list

        normalized = self._normalize_bulk_columns(df)
        # The legacy SDMX shape calls this dimension REF_AREA.  The current
        # flat bulk shape calls it BORROWERS_CTY and stores ``US: United
        # States`` style labels.  Keep only the published actual-trend gap
        # (C) for the private non-financial sector/all-lenders slice; without
        # this filter the actual level, HP trend, and gap would collide in the
        # old one-value-per-country schema.
        area_column = "REF_AREA" if "REF_AREA" in normalized.columns else "BORROWERS_CTY"
        if area_column not in normalized.columns:
            return meta_list, obs_list
        area_codes = normalized[area_column].astype(str).map(self._short_code)
        filtered = normalized[area_codes.isin(areas)].copy()
        if "CG_DTYPE" in filtered.columns:
            dtype_codes = filtered["CG_DTYPE"].astype(str).map(self._short_code)
            if (dtype_codes == "C").any():
                filtered = filtered[dtype_codes == "C"]
        for dimension, expected in (("TC_BORROWERS", "P"), ("TC_LENDERS", "A")):
            if dimension in filtered.columns:
                codes = filtered[dimension].astype(str).map(self._short_code)
                if (codes == expected).any():
                    filtered = filtered[codes == expected]
        filtered["_area_code"] = filtered[area_column].astype(str).map(self._short_code)
        for area, group in filtered.groupby("_area_code"):
            series_id = f"BIS_CREDIT_GAP_{area}"
            meta_list.append(
                BisSeriesMeta(
                    series_id=series_id,
                    country=str(area),
                    indicator="Credit-to-GDP Gap",
                    title=f"BIS Credit-to-GDP Gap ({area})",
                    frequency="Q",
                    units="Percent",
                    fetched_at=fetched_at,
                )
            )
            for _, row in group.iterrows():
                period = str(row.get("TIME_PERIOD", ""))
                raw = row.get("OBS_VALUE")
                value = float(raw) if pd.notna(raw) else None
                if period and period.lower() != "nan":
                    obs_list.append(
                        BisObservation(
                            period=period,
                            series_id=series_id,
                            country=str(area),
                            value=value,
                            release_date=self._derive_quarterly_release_date(period),
                            fetched_at=fetched_at,
                        )
                    )
        return meta_list, obs_list

    @staticmethod
    def _derive_quarterly_release_date(period: str) -> str:
        if "-Q" not in period:
            return period
        year_s, quarter_s = period.split("-Q", 1)
        try:
            year = int(year_s)
            quarter = int(quarter_s)
        except ValueError:
            return period
        mapping = {1: f"{year}-06-30", 2: f"{year}-09-30", 3: f"{year}-12-31", 4: f"{year + 1}-03-31"}
        return mapping.get(quarter, period)
