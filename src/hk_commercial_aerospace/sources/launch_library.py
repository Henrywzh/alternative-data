"""Launch Library 2 API integration.

Provides endpoints for fetching upcoming global launches and specific
agency historical launches.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
import requests
import pandas as pd

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    LAUNCH_LIBRARY_BASE,
    CHINESE_LAUNCH_AGENCIES,
    CHINESE_LAUNCH_AGENCY_IDS,
    STATE_LAUNCH_PROVIDER_IDS,
    LL2_MAX_REQUESTS_PER_HOUR,
    NORMALIZED_DIR,
    RAW_DIR,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "launch_id",
    "name",
    "net_time",
    "status_abbrev",
    "status_name",
    "provider_id",
    "provider_name",
    "rocket_name",
    "rocket_family",
    "pad_name",
    "orbit_abbrev",
    "mission_type",
    "launch_designator",
    "country_code",
    "last_updated",
    "fetched_at",
]

HISTORY_PATH = NORMALIZED_DIR / "launch_events_history.jsonl"

def _parse_launch_results(results: list[dict], fetched_at: str) -> list[dict]:
    parsed = []
    for r in results:
        provider = r.get("launch_service_provider") or {}
        rocket = r.get("rocket") or {}
        configuration = rocket.get("configuration") or {}
        mission = r.get("mission") or {}
        pad = r.get("pad") or {}
        parsed.append({
            # LL2 v2.2 returns `id`; older cached responses used `uuid`.
            "launch_id": r.get("id") or r.get("uuid") or "",
            "name": r.get("name", ""),
            "net_time": r.get("net", ""),
            "status_abbrev": r.get("status", {}).get("abbrev", ""),
            "status_name": r.get("status", {}).get("name", ""),
            "provider_id": provider.get("id"),
            "provider_name": provider.get("name", ""),
            "rocket_name": configuration.get("full_name") or configuration.get("name", ""),
            "rocket_family": configuration.get("family", ""),
            "pad_name": pad.get("name", ""),
            "orbit_abbrev": (mission.get("orbit") or r.get("orbit") or {}).get("abbrev") if (mission.get("orbit") or r.get("orbit")) else None,
            "mission_type": mission.get("type", ""),
            "launch_designator": mission.get("launch_designator") or r.get("launch_designator"),
            "country_code": r.get("country_code"),
            "last_updated": r.get("last_updated", ""),
            "fetched_at": fetched_at,
        })
    return parsed


def _exact_provider_rows(rows: list[dict], *, provider_id: int | None, provider_name: str) -> list[dict]:
    """Keep only rows whose provider is the configured agency.

    The API's broad search endpoint searches mission and payload text too. We
    therefore apply an exact provider guard even when the server-side ID
    filter is used, protecting the sector from cross-agency historical rows.
    """
    exact = []
    for row in rows:
        provider = row.get("launch_service_provider") or {}
        if provider_id is not None and provider.get("id") == provider_id:
            exact.append(row)
        elif provider_id is None and provider.get("name") == provider_name:
            exact.append(row)
    return exact


def _load_cached_agency_payload(agency_name: str) -> dict | None:
    """Load the latest raw agency payload when LL2 throttles a scheduled run."""
    import json

    agency_token = agency_name.replace(" ", "_")
    paths = sorted(
        [
            *RAW_DIR.glob(f"ll2_agency_launches_{agency_token}_*.json"),
            *RAW_DIR.glob(f"ll2_national_launches_{agency_token}_*.json"),
        ],
        reverse=True,
    )
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            candidate = payload.get("data") or payload.get("payload") or payload
            if isinstance(candidate, dict) and isinstance(candidate.get("results"), list):
                return candidate
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _read_launch_history() -> pd.DataFrame:
    if not HISTORY_PATH.exists():
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    rows = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("launch_id"):
                rows.append(row)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed LL2 launch history row")
    if not rows:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    return pd.DataFrame(rows).reindex(columns=SCHEMA_COLUMNS)


def _append_launch_history(frames: dict[str, pd.DataFrame]) -> None:
    """Persist observed LL2 events without rewriting prior history."""
    observed = []
    for frame in frames.values():
        if frame.empty:
            continue
        observed.extend(frame.to_dict(orient="records"))
    if not observed:
        return

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_launch_history()
    known_ids = set(existing["launch_id"].astype(str)) if not existing.empty else set()
    new_rows = []
    for row in observed:
        launch_id = str(row.get("launch_id") or "")
        if not launch_id or launch_id in known_ids:
            continue
        new_rows.append({column: row.get(column) for column in SCHEMA_COLUMNS})
        known_ids.add(launch_id)
    if not new_rows:
        return
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        for row in new_rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _merge_launch_history(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Union persisted events with this run's exact-provider observations."""
    history = _read_launch_history()
    merged: dict[str, pd.DataFrame] = {}
    for agency in CHINESE_LAUNCH_AGENCIES:
        current = frames.get(agency, pd.DataFrame(columns=SCHEMA_COLUMNS))
        current_source = current.attrs.get("source", "unavailable")
        historical = history[history["provider_name"].eq(agency)] if not history.empty else pd.DataFrame(columns=SCHEMA_COLUMNS)
        pieces = [frame for frame in (historical, current) if not frame.empty]
        if pieces:
            frame = pd.concat(pieces, ignore_index=True).drop_duplicates("launch_id", keep="last")
            frame = frame.reindex(columns=SCHEMA_COLUMNS)
        else:
            frame = pd.DataFrame(columns=SCHEMA_COLUMNS)
        if current_source in {"live", "cache"}:
            effective_source = current_source
        elif not historical.empty:
            effective_source = "history"
        else:
            effective_source = "unavailable"
        frame.attrs["source"] = effective_source
        merged[agency] = frame
    return merged


def fetch_upcoming_launches(limit: int = 100) -> pd.DataFrame:
    """Fetch upcoming launches from Launch Library 2 with fallback to local raw snapshot.

    The returned DataFrame carries `df.attrs["source"]` set to `"live"` or
    `"cache"` so callers can report freshness honestly instead of assuming
    "live" whenever rows are non-empty.
    """
    url = f"{LAUNCH_LIBRARY_BASE}/launch/upcoming/?format=json&limit={limit}"
    fetched_at = datetime.now(timezone.utc).isoformat()
    data = None
    data_source = "live"
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            save_raw_snapshot("ll2_upcoming_launches", data, source_url=url)
    except Exception as e:
        logger.warning(f"Failed to fetch upcoming launches: {e}")

    if not data:
        data_source = "cache"
        snaps = sorted(RAW_DIR.glob("ll2_upcoming_launches_*.json"))
        if snaps:
            for s_path in reversed(snaps):
                try:
                    import json
                    with open(s_path, "r", encoding="utf-8") as f:
                        snap_content = json.load(f)
                        candidate = snap_content.get("data") or snap_content.get("payload")
                        if candidate and isinstance(candidate, dict) and candidate.get("results"):
                            data = candidate
                            logger.info(f"Loaded upcoming launches from snapshot fallback: {s_path.name}")
                            break
                except Exception as e:
                    logger.warning(f"Failed to load snapshot fallback {s_path.name}: {e}")

    if not data or not isinstance(data, dict):
        empty = pd.DataFrame(columns=SCHEMA_COLUMNS)
        empty.attrs["source"] = data_source
        return empty

    results = data.get("results", [])
    parsed = _parse_launch_results(results, fetched_at)
    if not parsed:
        empty = pd.DataFrame(columns=SCHEMA_COLUMNS)
        empty.attrs["source"] = data_source
        return empty
    df = pd.DataFrame(parsed).reindex(columns=SCHEMA_COLUMNS)
    df.attrs["source"] = data_source
    return df


def fetch_agency_launches(agency_name: str, limit: int = 100) -> pd.DataFrame:
    """Fetch previous launches for one exact LL2 launch-service provider."""
    provider_id = CHINESE_LAUNCH_AGENCY_IDS.get(agency_name)
    params = {
        "format": "json",
        "limit": min(limit, 100),
    }
    if provider_id is not None:
        params["lsp__id"] = provider_id
    else:
        # This path is intentionally exact-filtered after the response.
        params["search"] = agency_name
    url = f"{LAUNCH_LIBRARY_BASE}/launch/previous/"
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = _exact_provider_rows(
            data.get("results", []),
            provider_id=provider_id,
            provider_name=agency_name,
        )
    except Exception as e:
        logger.warning(f"Failed to fetch launches for agency {agency_name}: {e}")
        data = _load_cached_agency_payload(agency_name)
        if not data:
            return pd.DataFrame(columns=SCHEMA_COLUMNS)
        results = _exact_provider_rows(
            data.get("results", []),
            provider_id=provider_id,
            provider_name=agency_name,
        )

    save_raw_snapshot(f"ll2_agency_launches_{agency_name.replace(' ', '_')}", data, source_url=url)
    parsed = _parse_launch_results(results, fetched_at)
    if not parsed:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    return pd.DataFrame(parsed).reindex(columns=SCHEMA_COLUMNS)


def fetch_chinese_commercial_launches() -> dict[str, pd.DataFrame]:
    """Fetch all configured Chinese commercial launches from LL2.

    CRITICAL: This function is designed for a SINGLE scheduled run (daily/weekly),
    not for interactive ad hoc querying. Total HTTP requests across all agencies must
    stay under LL2_MAX_REQUESTS_PER_HOUR (15) — the free tier hard limit.

    If HTTP 429 is received, we stop immediately and return whatever has been
    collected so far. Partial results are honest; never retry immediately.
    """
    results: dict[str, pd.DataFrame] = {}
    requests_made = 0

    def _agency_frame(parsed: list[dict], source: str) -> pd.DataFrame:
        frame = pd.DataFrame(parsed, columns=SCHEMA_COLUMNS)
        frame.attrs["source"] = source
        return frame

    for agency_index, agency in enumerate(CHINESE_LAUNCH_AGENCIES):
        if requests_made >= LL2_MAX_REQUESTS_PER_HOUR - 2:  # Leave margin for upcoming_launches call
            logger.warning(
                "LL2 rate limit margin reached after %d requests — stopping agency fetch. "
                "Remaining agencies will be fetched on next scheduled run.",
                requests_made,
            )
            break

        provider_id = CHINESE_LAUNCH_AGENCY_IDS.get(agency)
        url = f"{LAUNCH_LIBRARY_BASE}/launch/previous/"
        params = {"format": "json", "limit": 100}
        if provider_id is not None:
            params["lsp__id"] = provider_id
        else:
            params["search"] = agency
        fetched_at = datetime.now(timezone.utc).isoformat()
        requests_made += 1

        try:
            resp = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 429:
                logger.warning(
                    "LL2 rate limit (HTTP 429) hit after %d requests — stopping. "
                    "Partial results returned. Will resume on next scheduled run.",
                    requests_made,
                )
                cached = _load_cached_agency_payload(agency)
                if cached:
                    exact_cached = _exact_provider_rows(
                        cached.get("results", []),
                        provider_id=provider_id,
                        provider_name=agency,
                    )
                    parsed_cached = _parse_launch_results(exact_cached, fetched_at)
                    results[agency] = _agency_frame(parsed_cached, "cache")
                else:
                    results[agency] = _agency_frame([], "unavailable")
                for remaining_agency in CHINESE_LAUNCH_AGENCIES[agency_index + 1:]:
                    remaining_id = CHINESE_LAUNCH_AGENCY_IDS.get(remaining_agency)
                    remaining_cached = _load_cached_agency_payload(remaining_agency)
                    remaining_exact = _exact_provider_rows(
                        remaining_cached.get("results", []) if remaining_cached else [],
                        provider_id=remaining_id,
                        provider_name=remaining_agency,
                    )
                    remaining_parsed = _parse_launch_results(remaining_exact, fetched_at)
                    results[remaining_agency] = _agency_frame(
                        remaining_parsed,
                        "cache" if remaining_parsed else "unavailable",
                    )
                break
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError:
            logger.warning("HTTP error fetching LL2 agency launches for %s.", agency)
            cached = _load_cached_agency_payload(agency)
            exact_cached = _exact_provider_rows(cached.get("results", []), provider_id=provider_id, provider_name=agency) if cached else []
            parsed_cached = _parse_launch_results(exact_cached, fetched_at)
            results[agency] = _agency_frame(parsed_cached, "cache" if parsed_cached else "unavailable")
            continue
        except Exception as exc:
            logger.warning("Failed to fetch LL2 agency launches for %s: %s", agency, exc)
            cached = _load_cached_agency_payload(agency)
            exact_cached = _exact_provider_rows(cached.get("results", []), provider_id=provider_id, provider_name=agency) if cached else []
            parsed_cached = _parse_launch_results(exact_cached, fetched_at)
            results[agency] = _agency_frame(parsed_cached, "cache" if parsed_cached else "unavailable")
            continue

        save_raw_snapshot(
            f"ll2_agency_launches_{agency.replace(' ', '_')}",
            data,
            source_url=url,
        )
        exact_results = _exact_provider_rows(
            data.get("results", []),
            provider_id=provider_id,
            provider_name=agency,
        )
        parsed = _parse_launch_results(exact_results, fetched_at)
        results[agency] = _agency_frame(parsed, "live")

    _append_launch_history(results)
    return _merge_launch_history(results)


def fetch_state_launch_enrichment(limit: int = 100) -> pd.DataFrame:
    """Fetch recent LL2 rows for state/national providers as enrichment only.

    These rows are deliberately not merged into the existing commercial
    history. The official CALT/CASC event table decides which launches count;
    callers join these structured fields onto already verified events.
    """
    frames: list[pd.DataFrame] = []
    sources: set[str] = set()
    for provider_name, provider_id in STATE_LAUNCH_PROVIDER_IDS.items():
        url = f"{LAUNCH_LIBRARY_BASE}/launch/previous/"
        params = {"format": "json", "limit": min(limit, 100), "lsp__id": provider_id}
        fetched_at = datetime.now(timezone.utc).isoformat()
        data = None
        source = "unavailable"
        try:
            response = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
            if response.status_code == 429:
                logger.warning("LL2 rate limit reached while fetching state provider %s", provider_name)
            else:
                response.raise_for_status()
                data = response.json()
                save_raw_snapshot(
                    f"ll2_national_launches_{provider_name.replace(' ', '_')}",
                    data,
                    source_url=response.url,
                )
                source = "live"
        except Exception as exc:
            logger.warning("Failed to fetch LL2 state provider %s: %s", provider_name, exc)

        if not data:
            data = _load_cached_agency_payload(provider_name)
            if data:
                source = "cache"
        results = _exact_provider_rows(
            (data or {}).get("results", []),
            provider_id=provider_id,
            provider_name=provider_name,
        )
        parsed = _parse_launch_results(results, fetched_at)
        frame = pd.DataFrame(parsed, columns=SCHEMA_COLUMNS)
        frame.attrs["source"] = source
        frame.attrs["provider_name"] = provider_name
        frames.append(frame)
        sources.add(source)

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=SCHEMA_COLUMNS)
    if not combined.empty:
        combined = combined.drop_duplicates("launch_id").reset_index(drop=True)
    combined.attrs["source"] = "live" if "live" in sources else "cache" if "cache" in sources else "unavailable"
    return combined


def _normalized_launch_month_frame(launches: pd.DataFrame) -> pd.DataFrame:
    """Return deduplicated launch events with a normalized calendar month."""
    if launches.empty:
        return pd.DataFrame(columns=["launch_id", "month", "provider_name", "status_abbrev"])
    frame = launches.copy()
    frame["launch_id"] = frame["launch_id"].astype(str)
    frame = frame[frame["launch_id"].ne("")].drop_duplicates("launch_id")
    frame["month"] = pd.to_datetime(frame["net_time"], errors="coerce", utc=True).dt.strftime("%Y-%m")
    return frame[frame["month"].notna()].copy()


def build_monthly_launch_summary(launches: pd.DataFrame) -> pd.DataFrame:
    """Aggregate exact launch events into provider/month/status counts."""
    columns = ["month", "provider", "status", "launch_count"]
    frame = _normalized_launch_month_frame(launches)
    if frame.empty:
        return pd.DataFrame(columns=columns)
    summary = (
        frame.groupby(["month", "provider_name", "status_abbrev"], dropna=False)
        .size()
        .reset_index(name="launch_count")
        .rename(columns={"provider_name": "provider", "status_abbrev": "status"})
    )
    return summary[columns].sort_values(["month", "provider", "status"]).reset_index(drop=True)


def build_monthly_launch_total_summary(launches: pd.DataFrame) -> pd.DataFrame:
    """Aggregate exact launch events into a zero-filled monthly total series."""
    columns = ["month", "launch_count"]
    frame = _normalized_launch_month_frame(launches)
    if frame.empty:
        return pd.DataFrame(columns=columns)

    counts = frame.groupby("month").size()
    months = pd.period_range(frame["month"].min(), frame["month"].max(), freq="M").strftime("%Y-%m")
    return pd.DataFrame({
        "month": months,
        "launch_count": counts.reindex(months, fill_value=0).astype(int).to_numpy(),
    })
