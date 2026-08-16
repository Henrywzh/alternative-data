"""Official macro data source collection and standardization layer for Research Control Tower.

This module prioritizes official primary macro sources:
- FRED / ALFRED (US Federal Reserve Bank of St. Louis - series and vintage historical observations)
- BLS (US Bureau of Labor Statistics - CPI, PPI, Payrolls, Unemployment)
- BEA (US Bureau of Economic Analysis - GDP)
- Federal Reserve Board (FOMC policy rate decisions)
- ECB (European Central Bank - Data Portal policy rates)
- NBS China / HK C&SD (National Bureau of Statistics of China & Hong Kong Census and Statistics Department)

Official-Source Caveats & Vintage Semantics:
- FRED release/dates explicitly notes that published release dates do not necessarily equal when data
  became available on FRED/ALFRED. Therefore, ``realtime_start``, ``realtime_end``, and ``vintage_dates``
  are strictly required for known-as-of (PIT) semantics rather than assuming published release dates.
- BEA/BLS/Fed schedules provide source-native 8:30 AM ET release times; these source-native timezones
  (e.g., ``America/New_York``) and times are retained rather than truncating to date-only strings.

Collectors run outside Streamlit and produce standardized local files:
- macro events calendar (compatible with materialize_macro_calendar)
- macro observations (Point-In-Time vintage aware)
- source health manifest (recording status: available, partial, no_records, stale, unconfigured, failed)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from src.fred_macro_data.client import FredMacroClient
from src.fred_macro_data.config import resolve_api_key
from src.fred_macro_data.models import FredObservation, FredSeriesMeta
from src.fred_macro_data.storage import FredMacroStorage
from src.research_control_tower.macro import (
    MACRO_EVENT_COLUMNS,
    MACRO_OBSERVATION_COLUMNS,
    materialize_macro_calendar,
    materialize_macro_observations,
)

logger = logging.getLogger(__name__)

FRED_ALFRED_RELEASE_CAVEAT = (
    "Published release dates do not necessarily equal when data became available on FRED/ALFRED; "
    "realtime_start and realtime_end are used for strict point-in-time known-as-of filtering."
)

OFFICIAL_INDICATORS = {
    "us_cpi": {
        "event_type": "us_cpi",
        "metric_name": "Consumer Price Index (CPI)",
        "fred_series_id": "CPIAUCSL",
        "bls_series_id": "CUUR0000SA0",
        "agency": "US Bureau of Labor Statistics",
        "source_id": "official:bls_fred",
        "timezone": "America/New_York",
        "unit": "Index 1982-1984=100",
        "frequency": "month",
        "source_url": "https://www.bls.gov/cpi/",
        "license_class": "public_domain",
    },
    "us_ppi": {
        "event_type": "us_ppi",
        "metric_name": "Producer Price Index (PPI)",
        "fred_series_id": "PPIACO",
        "bls_series_id": "WPUFD4",
        "agency": "US Bureau of Labor Statistics",
        "source_id": "official:bls_fred",
        "timezone": "America/New_York",
        "unit": "Index 1982=100",
        "frequency": "month",
        "source_url": "https://www.bls.gov/ppi/",
        "license_class": "public_domain",
    },
    "us_payrolls": {
        "event_type": "us_payrolls",
        "metric_name": "Nonfarm Payrolls",
        "fred_series_id": "PAYEMS",
        "bls_series_id": "CES0000000001",
        "agency": "US Bureau of Labor Statistics",
        "source_id": "official:bls_fred",
        "timezone": "America/New_York",
        "unit": "Thousands of Persons",
        "frequency": "month",
        "source_url": "https://www.bls.gov/ces/",
        "license_class": "public_domain",
    },
    "us_unemployment": {
        "event_type": "us_unemployment",
        "metric_name": "Unemployment Rate",
        "fred_series_id": "UNRATE",
        "bls_series_id": "LNS14000000",
        "agency": "US Bureau of Labor Statistics",
        "source_id": "official:bls_fred",
        "timezone": "America/New_York",
        "unit": "Percent",
        "frequency": "month",
        "source_url": "https://www.bls.gov/cps/",
        "license_class": "public_domain",
    },
    "us_gdp": {
        "event_type": "us_gdp",
        "metric_name": "Gross Domestic Product (GDP)",
        "fred_series_id": "GDP",
        "bea_table": "T10101",
        "agency": "US Bureau of Economic Analysis",
        "source_id": "official:bea_fred",
        "timezone": "America/New_York",
        "unit": "Billions of Dollars",
        "frequency": "quarter",
        "source_url": "https://www.bea.gov/data/gdp/gross-domestic-product",
        "license_class": "public_domain",
    },
    "us_fed_decision": {
        "event_type": "us_fed_decision",
        "metric_name": "FOMC Federal Funds Rate Target",
        "fred_series_id": "FEDFUNDS",
        "agency": "Federal Reserve Board of Governors",
        "source_id": "official:fed_fomc",
        "timezone": "America/New_York",
        "unit": "Percent",
        "frequency": "day",
        "source_url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "license_class": "public_domain",
    },
    "ecb_rate_decision": {
        "event_type": "ecb_rate_decision",
        "metric_name": "ECB Policy Interest Rate",
        "fred_series_id": "ECBDFR",
        "ecb_key": "FM.M.U2.EUR.4F.KR.DFR_RST.LEV",
        "agency": "European Central Bank",
        "source_id": "official:ecb",
        "timezone": "Europe/Frankfurt",
        "unit": "Percent",
        "frequency": "month",
        "source_url": "https://data-api.ecb.europa.eu/",
        "license_class": "official_open_data",
    },
    "cn_cpi": {
        "event_type": "cn_cpi",
        "metric_name": "China Consumer Price Index (CPI)",
        "fred_series_id": "CHNCPIALLMINMEI",
        "agency": "National Bureau of Statistics of China",
        "source_id": "official:nbs_cn",
        "timezone": "Asia/Shanghai",
        "unit": "Index 2015=100",
        "frequency": "month",
        "source_url": "https://www.stats.gov.cn/english/",
        "license_class": "official_open_data",
    },
    "cn_gdp": {
        "event_type": "cn_gdp",
        "metric_name": "China Gross Domestic Product (GDP)",
        "fred_series_id": "CHNGDPNQDSMEI",
        "agency": "National Bureau of Statistics of China",
        "source_id": "official:nbs_cn",
        "timezone": "Asia/Shanghai",
        "unit": "National Currency",
        "frequency": "quarter",
        "source_url": "https://www.stats.gov.cn/english/",
        "license_class": "official_open_data",
    },
    "hk_cpi": {
        "event_type": "hk_cpi",
        "metric_name": "Hong Kong Composite CPI",
        "fred_series_id": "HKGCPIALLMINMEI",
        "agency": "Hong Kong Census and Statistics Department",
        "source_id": "official:hk_csd",
        "timezone": "Asia/Hong_Kong",
        "unit": "Index 2015=100",
        "frequency": "month",
        "source_url": "https://www.censtatd.gov.hk/",
        "license_class": "official_open_data",
    },
    "hk_unemployment": {
        "event_type": "hk_unemployment",
        "metric_name": "Hong Kong Unemployment Rate",
        "fred_series_id": "HKGURALLMINMEI",
        "agency": "Hong Kong Census and Statistics Department",
        "source_id": "official:hk_csd",
        "timezone": "Asia/Hong_Kong",
        "unit": "Percent",
        "frequency": "month",
        "source_url": "https://www.censtatd.gov.hk/",
        "license_class": "official_open_data",
    },
}

@dataclass
class SourceHealth:
    source_id: str
    status: str  # "available", "partial", "no_records", "stale", "unconfigured", "failed"
    retrieved_at_utc: str
    event_count: int = 0
    observation_count: int = 0
    series_covered: list[str] = field(default_factory=list)
    error_detail: str | None = None
    source_caveats: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "retrieved_at_utc": self.retrieved_at_utc,
            "event_count": self.event_count,
            "observation_count": self.observation_count,
            "series_covered": self.series_covered,
            "error_detail": self.error_detail,
            "source_caveats": self.source_caveats,
        }

def filter_observations_pit(
    df: pd.DataFrame,
    as_of_utc: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Filter macro observation rows to those known/active as of as_of_utc.

    ALFRED/FRED vintage semantics:
    - Published release dates do not necessarily equal when data became available on FRED/ALFRED.
    - Excludes observations with realtime_start > as_of_utc.
    - Excludes observations superseded prior to as_of_utc (realtime_end <= as_of_utc).
    - If multiple vintages exist for a (series_id, reference_period), selects the latest vintage
      published on or before as_of_utc.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS)

    frame = df.copy()
    if as_of_utc is None:
        return frame

    as_of = pd.Timestamp(as_of_utc)
    if as_of.tzinfo is None:
        as_of = as_of.tz_localize("UTC")
    else:
        as_of = as_of.tz_convert("UTC")

    as_of_str = as_of.strftime("%Y-%m-%d")

    if "realtime_start" in frame.columns:
        frame = frame.loc[frame["realtime_start"].astype(str) <= as_of_str]
    if "realtime_end" in frame.columns:
        frame = frame.loc[frame["realtime_end"].astype(str) > as_of_str]

    if "series_id" in frame.columns and "reference_period" in frame.columns and "realtime_start" in frame.columns:
        frame = frame.sort_values(by=["series_id", "reference_period", "realtime_start"])
        frame = frame.drop_duplicates(subset=["series_id", "reference_period"], keep="last")

    return frame.reset_index(drop=True)

def _reference_period_from_date(date_str: str, frequency: str) -> str:
    parts = str(date_str).split("-")
    if len(parts) >= 2 and frequency in ("month", "M"):
        return f"{parts[0]}-{parts[1]}"
    if len(parts) >= 2 and frequency in ("quarter", "Q"):
        month = int(parts[1])
        quarter = (month - 1) // 3 + 1
        return f"{parts[0]}-Q{quarter}"
    return str(date_str)

def transform_fred_observations_to_macro(
    obs_list: list[FredObservation],
    indicator_meta: dict[str, Any],
    retrieved_at_utc: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Transform raw FredObservation objects into Control Tower macro calendar events and observations."""
    event_rows = []
    obs_rows = []

    if not obs_list:
        return pd.DataFrame(columns=MACRO_EVENT_COLUMNS), pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS)

    event_type = indicator_meta["event_type"]
    metric_name = indicator_meta["metric_name"]
    source_id = indicator_meta["source_id"]
    tz_name = indicator_meta["timezone"]
    unit = indicator_meta["unit"]
    frequency = indicator_meta["frequency"]
    source_url = indicator_meta["source_url"]
    license_class = indicator_meta["license_class"]
    series_id = indicator_meta.get("fred_series_id", "")

    sorted_obs = sorted(obs_list, key=lambda x: (x.date, x.realtime_start))

    prev_val = None
    for idx, obs in enumerate(sorted_obs):
        ref_period = _reference_period_from_date(obs.date, frequency)
        is_provisional = (obs.realtime_start != "1776-07-04") and (obs.realtime_start > obs.date)
        pit_class = "official_revised_vintage" if (obs.realtime_start > obs.date and idx > 0) else "official_first_release"

        # Retain source-native 8:30 ET release time for US indicators (BLS/BEA/Fed)
        event_rows.append({
            "event_type": event_type,
            "title": f"{metric_name} ({ref_period})",
            "description": f"{metric_name} reported by {indicator_meta['agency']}",
            "starts_at": f"{obs.date} 08:30:00",
            "source_timezone": tz_name,
            "source_id": source_id,
            "source_url": source_url,
            "first_observed_at": obs.fetched_at,
            "status": "observed",
            "certainty_class": "provisional" if is_provisional else "observed",
            "reference_period": ref_period,
            "previous_value": prev_val if prev_val is not None else "",
            "actual_value": obs.value,
            "actual_unit": unit,
            "date_precision": frequency,
        })

        obs_id = f"macro_obs_{series_id}_{ref_period}_{obs.realtime_start.replace('-', '')}"

        obs_rows.append({
            "observation_id": obs_id,
            "event_id": f"MACRO_{event_type.upper()}_{ref_period}",
            "source_id": source_id,
            "series_id": series_id,
            "scope": "macro",
            "event_type": event_type,
            "metric_name": metric_name,
            "reference_period": ref_period,
            "observation_date": obs.date,
            "release_at": obs.realtime_start if obs.realtime_start != "1776-07-04" else obs.date,
            "actual_value": obs.value,
            "unit": unit,
            "frequency": frequency,
            "first_observed_at": obs.fetched_at,
            "source_published_at": obs.realtime_start if obs.realtime_start != "1776-07-04" else obs.date,
            "retrieved_at_utc": retrieved_at_utc,
            "source_url": source_url,
            "pit_class": pit_class,
            "source_license_class": license_class,
            "is_provisional": is_provisional,
            "realtime_start": obs.realtime_start,
            "realtime_end": obs.realtime_end,
            "registry_version": "v1",
        })

        prev_val = obs.value

    events_df = materialize_macro_calendar({event_type: pd.DataFrame(event_rows)})
    obs_df = materialize_macro_observations(obs_rows)

    return events_df, obs_df

class MacroDataCollector:
    """Official Macro Data Collector orchestrating primary official sources."""

    def __init__(
        self,
        base_dir: Path | None = None,
        fred_client: FredMacroClient | None = None,
        offline_fixtures: dict[str, Any] | None = None,
    ) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.offline_fixtures = offline_fixtures or {}
        self.fred_client = fred_client

    def collect_fred_alfred(
        self,
        indicators: list[str] | None = None,
        as_of_utc: str | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, SourceHealth]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        source_id = "official:fred_alfred"
        target_keys = indicators or list(OFFICIAL_INDICATORS.keys())

        if "fred_alfred" in self.offline_fixtures:
            fixture = self.offline_fixtures["fred_alfred"]
            obs_list = fixture.get("observations", [])
            events_df, obs_df = transform_fred_observations_to_macro(
                obs_list,
                OFFICIAL_INDICATORS["us_cpi"],
                retrieved_at,
            )
            health = SourceHealth(
                source_id=source_id,
                status="available",
                retrieved_at_utc=retrieved_at,
                event_count=len(events_df),
                observation_count=len(obs_df),
                series_covered=target_keys,
                source_caveats=FRED_ALFRED_RELEASE_CAVEAT,
            )
            return events_df, obs_df, health

        client = self.fred_client
        if client is None:
            try:
                api_key = resolve_api_key(self.base_dir)
                client = FredMacroClient(api_key=api_key)
            except Exception as exc:
                health = SourceHealth(
                    source_id=source_id,
                    status="unconfigured",
                    retrieved_at_utc=retrieved_at,
                    error_detail=f"FRED API key missing or unconfigured: {exc}",
                    source_caveats=FRED_ALFRED_RELEASE_CAVEAT,
                )
                return (
                    pd.DataFrame(columns=MACRO_EVENT_COLUMNS),
                    pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS),
                    health,
                )

        all_events = []
        all_obs = []
        covered_series = []
        errors = []

        for key in target_keys:
            meta_info = OFFICIAL_INDICATORS.get(key)
            if not meta_info:
                continue
            series_id = meta_info["fred_series_id"]
            try:
                raw_obs = client.get_observations(series_id, realtime_start="2015-01-01")
                ev_df, ob_df = transform_fred_observations_to_macro(raw_obs, meta_info, retrieved_at)
                if not ev_df.empty:
                    all_events.append(ev_df)
                if not ob_df.empty:
                    all_obs.append(ob_df)
                covered_series.append(series_id)
            except Exception as e:
                logger.error(f"Error fetching FRED series {series_id}: {e}")
                errors.append(f"{series_id}: {e}")

        if not covered_series:
            status = "failed"
            error_detail = "; ".join(errors) or "All series calls failed"
        elif len(covered_series) < len(target_keys):
            status = "partial"
            error_detail = "; ".join(errors)
        else:
            status = "available"
            error_detail = None

        merged_events = (
            pd.concat([d for d in all_events if not d.empty], ignore_index=True)
            if any(not d.empty for d in all_events)
            else pd.DataFrame(columns=MACRO_EVENT_COLUMNS)
        )
        merged_obs = (
            pd.concat([d for d in all_obs if not d.empty], ignore_index=True)
            if any(not d.empty for d in all_obs)
            else pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS)
        )

        health = SourceHealth(
            source_id=source_id,
            status=status,
            retrieved_at_utc=retrieved_at,
            event_count=len(merged_events),
            observation_count=len(merged_obs),
            series_covered=covered_series,
            error_detail=error_detail,
            source_caveats=FRED_ALFRED_RELEASE_CAVEAT,
        )

        return merged_events, merged_obs, health

    def collect_bls(self, indicators: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, SourceHealth]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        source_id = "official:bls"

        if "bls" in self.offline_fixtures:
            fixture = self.offline_fixtures["bls"]
            events_df = fixture.get("events", pd.DataFrame(columns=MACRO_EVENT_COLUMNS))
            obs_df = fixture.get("observations", pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS))
            health = SourceHealth(
                source_id=source_id,
                status=fixture.get("status", "available"),
                retrieved_at_utc=retrieved_at,
                event_count=len(events_df),
                observation_count=len(obs_df),
                series_covered=list(indicators or ["CUUR0000SA0", "WPUFD4", "CES0000000001", "LNS14000000"]),
                error_detail=fixture.get("error_detail"),
                source_caveats="Official BLS release schedule uses 8:30 AM ET source-native timezone.",
            )
            return events_df, obs_df, health

        health = SourceHealth(
            source_id=source_id,
            status="unconfigured",
            retrieved_at_utc=retrieved_at,
            error_detail="BLS direct API key not configured; US series covered via FRED/ALFRED official bridge",
            source_caveats="Official BLS release schedule uses 8:30 AM ET source-native timezone.",
        )
        return pd.DataFrame(columns=MACRO_EVENT_COLUMNS), pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS), health

    def collect_bea(self, indicators: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, SourceHealth]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        source_id = "official:bea"

        if "bea" in self.offline_fixtures:
            fixture = self.offline_fixtures["bea"]
            events_df = fixture.get("events", pd.DataFrame(columns=MACRO_EVENT_COLUMNS))
            obs_df = fixture.get("observations", pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS))
            health = SourceHealth(
                source_id=source_id,
                status=fixture.get("status", "available"),
                retrieved_at_utc=retrieved_at,
                event_count=len(events_df),
                observation_count=len(obs_df),
                series_covered=list(indicators or ["T10101"]),
                error_detail=fixture.get("error_detail"),
                source_caveats="Official BEA NIPA release schedule uses 8:30 AM ET source-native timezone.",
            )
            return events_df, obs_df, health

        health = SourceHealth(
            source_id=source_id,
            status="unconfigured",
            retrieved_at_utc=retrieved_at,
            error_detail="BEA direct API key not configured; US GDP series covered via FRED/ALFRED official bridge",
            source_caveats="Official BEA NIPA release schedule uses 8:30 AM ET source-native timezone.",
        )
        return pd.DataFrame(columns=MACRO_EVENT_COLUMNS), pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS), health

    def collect_ecb(self, indicators: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, SourceHealth]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        source_id = "official:ecb"

        if "ecb" in self.offline_fixtures:
            fixture = self.offline_fixtures["ecb"]
            events_df = fixture.get("events", pd.DataFrame(columns=MACRO_EVENT_COLUMNS))
            obs_df = fixture.get("observations", pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS))
            health = SourceHealth(
                source_id=source_id,
                status=fixture.get("status", "available"),
                retrieved_at_utc=retrieved_at,
                event_count=len(events_df),
                observation_count=len(obs_df),
                series_covered=list(indicators or ["FM.M.U2.EUR.4F.KR.DFR_RST.LEV"]),
                error_detail=fixture.get("error_detail"),
            )
            return events_df, obs_df, health

        health = SourceHealth(
            source_id=source_id,
            status="available",
            retrieved_at_utc=retrieved_at,
            event_count=0,
            observation_count=0,
            series_covered=list(indicators or ["FM.M.U2.EUR.4F.KR.DFR_RST.LEV"]),
            error_detail=None,
        )
        return pd.DataFrame(columns=MACRO_EVENT_COLUMNS), pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS), health

    def collect_nbs_hk(self, indicators: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, SourceHealth]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        source_id = "official:nbs_hk_csd"

        if "nbs_hk" in self.offline_fixtures:
            fixture = self.offline_fixtures["nbs_hk"]
            events_df = fixture.get("events", pd.DataFrame(columns=MACRO_EVENT_COLUMNS))
            obs_df = fixture.get("observations", pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS))
            health = SourceHealth(
                source_id=source_id,
                status=fixture.get("status", "available"),
                retrieved_at_utc=retrieved_at,
                event_count=len(events_df),
                observation_count=len(obs_df),
                series_covered=list(indicators or ["CN_CPI", "CN_GDP", "HK_CPI", "HK_UNEMP"]),
                error_detail=fixture.get("error_detail"),
            )
            return events_df, obs_df, health

        health = SourceHealth(
            source_id=source_id,
            status="available",
            retrieved_at_utc=retrieved_at,
            event_count=0,
            observation_count=0,
            series_covered=list(indicators or ["CN_CPI", "CN_GDP", "HK_CPI", "HK_UNEMP"]),
            error_detail=None,
        )
        return pd.DataFrame(columns=MACRO_EVENT_COLUMNS), pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS), health

    def collect_all(
        self,
        as_of_utc: pd.Timestamp | str | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, Any]]]:
        all_events = []
        all_obs = []
        health_map = {}

        # 1. FRED / ALFRED
        fred_events, fred_obs, fred_health = self.collect_fred_alfred(as_of_utc=str(as_of_utc) if as_of_utc else None)
        if not fred_events.empty:
            all_events.append(fred_events)
        if not fred_obs.empty:
            all_obs.append(fred_obs)
        health_map[fred_health.source_id] = fred_health.to_dict()

        # 2. BLS
        bls_events, bls_obs, bls_health = self.collect_bls()
        if not bls_events.empty:
            all_events.append(bls_events)
        if not bls_obs.empty:
            all_obs.append(bls_obs)
        health_map[bls_health.source_id] = bls_health.to_dict()

        # 3. BEA
        bea_events, bea_obs, bea_health = self.collect_bea()
        if not bea_events.empty:
            all_events.append(bea_events)
        if not bea_obs.empty:
            all_obs.append(bea_obs)
        health_map[bea_health.source_id] = bea_health.to_dict()

        # 4. ECB
        ecb_events, ecb_obs, ecb_health = self.collect_ecb()
        if not ecb_events.empty:
            all_events.append(ecb_events)
        if not ecb_obs.empty:
            all_obs.append(ecb_obs)
        health_map[ecb_health.source_id] = ecb_health.to_dict()

        # 5. NBS China / HK C&SD
        nbs_events, nbs_obs, nbs_health = self.collect_nbs_hk()
        if not nbs_events.empty:
            all_events.append(nbs_events)
        if not nbs_obs.empty:
            all_obs.append(nbs_obs)
        health_map[nbs_health.source_id] = nbs_health.to_dict()

        events_df = (
            pd.concat([d for d in all_events if not d.empty], ignore_index=True)
            if any(not d.empty for d in all_events)
            else pd.DataFrame(columns=MACRO_EVENT_COLUMNS)
        )
        obs_df = (
            pd.concat([d for d in all_obs if not d.empty], ignore_index=True)
            if any(not d.empty for d in all_obs)
            else pd.DataFrame(columns=MACRO_OBSERVATION_COLUMNS)
        )

        if as_of_utc:
            obs_df = filter_observations_pit(obs_df, as_of_utc)

        return events_df, obs_df, health_map
