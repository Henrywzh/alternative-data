"""On-demand company refresh for Control Tower Evidence.

This is a labelled overlay path, not the offline builder. A Company-page
button may call it to fetch the latest HKEXnews metadata plus vendor
headlines for one entity, then merge into local marts under
``data/normalized/marts/``. Published generation artifacts are never
rewritten. Article bodies are not stored.

Rate-limit stance: one Marketaux request (preferred HK listing), one
Finnhub request only when a verified US ADR exists, and one short-window
HKEXnews title search. Callers should enforce a UI cooldown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any, Mapping
import uuid

import pandas as pd
import requests

from .news_collector import (
    FINNHUB_SPEC,
    MARKETAUX_SPEC,
    NEWS_INPUT_COLUMNS,
    NewsProbeEvidence,
    _provider_symbol,
    _requests_fetch,
    collect_structured_news,
    write_news_input,
)
from .news_overlay import default_news_mart_dir
from .official_filings import _classify_hkex_title, _hkex_announcement_rows, load_source_identity
from .registries import load_registry_bundle


DEFAULT_COOLDOWN_SECONDS = 60
# A second guard with a different job. The per-company cooldown stops someone
# re-clicking one issuer; it does nothing about cycling through issuers, and
# vendor quota is per API key, not per company. Marketaux's free tier is 100
# requests a day, so ten companies clicked in ten seconds is a tenth of the
# day's budget with the per-company timer never once firing.
DEFAULT_GLOBAL_COOLDOWN_SECONDS = 15
HKEX_LIVE_MART_NAME = "hkexnews_live.parquet"
COOLDOWN_STATE_NAME = "news_refresh_cooldown.json"
CONFIG_KEY_MAP = {
    "finnhub": "FINNHUB_API_KEY",
    "marketaux": "MARKETAUX_API_KEY",
}


@dataclass(frozen=True, slots=True)
class SourceRefreshResult:
    source_id: str
    status: str
    detail: str
    new_rows: int = 0
    total_rows: int = 0
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class CompanyRefreshResult:
    entity_id: str
    fetched_at_utc: pd.Timestamp
    sources: tuple[SourceRefreshResult, ...]
    issues: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "fetched_at_utc": self.fetched_at_utc.isoformat(),
            "sources": [asdict(item) for item in self.sources],
            "issues": list(self.issues),
        }


def default_mart_dir(repo_root: Path | None = None) -> Path:
    return default_news_mart_dir(repo_root)


def hkex_live_mart_path(repo_root: Path | None = None) -> Path:
    return default_mart_dir(repo_root) / HKEX_LIVE_MART_NAME


def cooldown_state_path(repo_root: Path | None = None, mart_dir: Path | None = None) -> Path:
    base = Path(mart_dir) if mart_dir is not None else default_mart_dir(repo_root)
    return base / COOLDOWN_STATE_NAME


def _read_cooldown_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def refresh_cooldown_remaining(
    entity_id: str,
    *,
    now_utc: pd.Timestamp | None = None,
    repo_root: Path | None = None,
    mart_dir: Path | None = None,
) -> tuple[float, str]:
    """Seconds still to wait, and which cooldown is holding.

    Deliberately on disk rather than in Streamlit's session_state. Session
    state dies with the browser session, so reloading the page or opening a
    second tab handed out a fresh allowance -- against a vendor quota that is
    per API key and shared by every session on the deployment.
    """
    now = _now_utc() if now_utc is None else pd.Timestamp(now_utc).tz_convert("UTC")
    state = _read_cooldown_state(cooldown_state_path(repo_root, mart_dir))
    checks = (
        ("this company", state.get("entities", {}).get(str(entity_id)), DEFAULT_COOLDOWN_SECONDS),
        ("any company", state.get("global"), DEFAULT_GLOBAL_COOLDOWN_SECONDS),
    )
    worst = (0.0, "")
    for scope, stamp, window in checks:
        if not stamp:
            continue
        try:
            elapsed = (now - pd.Timestamp(stamp)).total_seconds()
        except (TypeError, ValueError):
            continue
        # A clock that moved backwards must not grant an unbounded wait.
        remaining = window - elapsed if elapsed >= 0 else window
        if remaining > worst[0]:
            worst = (float(remaining), scope)
    return worst


def record_refresh(
    entity_id: str,
    *,
    now_utc: pd.Timestamp,
    repo_root: Path | None = None,
    mart_dir: Path | None = None,
) -> None:
    """Persist the refresh time for both cooldown scopes."""
    path = cooldown_state_path(repo_root, mart_dir)
    state = _read_cooldown_state(path)
    entities = dict(state.get("entities") or {})
    stamp = pd.Timestamp(now_utc).tz_convert("UTC").isoformat()
    entities[str(entity_id)] = stamp
    payload = {"global": stamp, "entities": entities}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # Losing the stamp costs a cooldown, never the refresh the user asked for.
        pass


def _now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _text(value: object) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def load_news_api_keys(repo_root: Path | None = None) -> dict[str, str]:
    """Load Finnhub/Marketaux keys from env, repo ``.config``, then Streamlit secrets.

    Values are never logged. Missing keys are omitted so HKEX can still run.
    """

    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    file_values = _read_dotenv(root / ".config")
    keys: dict[str, str] = {}
    for provider, env_name in CONFIG_KEY_MAP.items():
        value = (os.environ.get(env_name) or file_values.get(env_name) or "").strip()
        if value:
            keys[provider] = value
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets:
            for provider, env_name in CONFIG_KEY_MAP.items():
                if provider in keys:
                    continue
                secret = secrets.get(env_name)
                if secret:
                    keys[provider] = str(secret).strip()
    except Exception:
        pass
    return keys


def _news_key(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="string")
    hashed = frame.get("content_hash", pd.Series("", index=frame.index)).astype("string").fillna("")
    fallback = (
        frame.get("link", pd.Series("", index=frame.index)).astype("string").fillna("")
        + "\x1f"
        + frame.get("title", pd.Series("", index=frame.index)).astype("string").fillna("")
    )
    return hashed.where(hashed.str.len() > 0, fallback)


def merge_news_frames(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame | None,
    *,
    now_utc: pd.Timestamp,
) -> pd.DataFrame:
    """Keep historical headlines; only first_seen_at is sticky."""

    empty = pd.DataFrame({column: pd.Series(dtype="object") for column in NEWS_INPUT_COLUMNS})
    incoming = empty if incoming is None or incoming.empty else incoming.copy()
    existing = empty if existing is None or existing.empty else existing.copy()
    if incoming.empty:
        return existing.reindex(columns=NEWS_INPUT_COLUMNS)
    incoming["scraped_at"] = now_utc
    incoming["last_seen_at"] = now_utc
    if existing.empty:
        incoming["first_seen_at"] = pd.to_datetime(
            incoming.get("first_seen_at", now_utc), errors="coerce", utc=True
        ).fillna(now_utc)
        return incoming.reindex(columns=NEWS_INPUT_COLUMNS)
    existing["_merge_key"] = _news_key(existing)
    incoming["_merge_key"] = _news_key(incoming)
    first_seen = {
        _text(key): seen
        for key, seen in zip(existing["_merge_key"], existing["first_seen_at"], strict=False)
        if _text(key)
    }
    incoming["first_seen_at"] = [
        first_seen.get(_text(key), now_utc) for key in incoming["_merge_key"]
    ]
    combined = pd.concat(
        [existing.drop(columns=["_merge_key"]), incoming.drop(columns=["_merge_key"])],
        ignore_index=True,
    )
    combined["_merge_key"] = _news_key(combined)
    combined["last_seen_at"] = pd.to_datetime(combined["last_seen_at"], errors="coerce", utc=True)
    combined = combined.sort_values("last_seen_at", ascending=False, na_position="last")
    combined = combined.drop_duplicates(subset=["_merge_key"], keep="first")
    return combined.drop(columns=["_merge_key"]).reindex(columns=NEWS_INPUT_COLUMNS)


def merge_hkex_frames(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame | None,
) -> pd.DataFrame:
    if incoming is None or incoming.empty:
        return existing.copy() if existing is not None and not existing.empty else pd.DataFrame()
    if existing is None or existing.empty:
        return incoming.copy()
    combined = pd.concat([existing, incoming], ignore_index=True)
    combined["retrieved_at_utc"] = pd.to_datetime(
        combined.get("retrieved_at_utc"), errors="coerce", utc=True
    )
    combined = combined.sort_values("retrieved_at_utc", ascending=False, na_position="last")
    return combined.drop_duplicates(subset=["document_id"], keep="first").reset_index(drop=True)


def _load_parquet(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def _is_us_listing(row: Mapping[str, Any]) -> bool:
    exchange = _text(row.get("exchange")).upper()
    ticker = _text(row.get("canonical_ticker")).upper()
    listing_id = _text(row.get("listing_id")).upper()
    return (
        exchange in {"NYSE", "NASDAQ", "AMEX", "ARCA"}
        or ticker.endswith(".US")
        or listing_id.endswith("_US")
    )


def _is_hk_listing(row: Mapping[str, Any]) -> bool:
    exchange = _text(row.get("exchange")).upper()
    ticker = _text(row.get("canonical_ticker")).upper()
    listing_id = _text(row.get("listing_id")).upper()
    return (
        exchange in {"HKEX", "SEHK", "HKSE"}
        or ticker.endswith(".HK")
        or listing_id.endswith("_HK")
    )


def _entity_listings(listings: pd.DataFrame, entity_id: str) -> pd.DataFrame:
    if listings is None or listings.empty:
        return pd.DataFrame()
    return listings.loc[listings["entity_id"].astype("string").eq(entity_id)].copy()


def _preferred_listing(listings: pd.DataFrame, *, hk: bool) -> pd.Series | None:
    if listings is None or listings.empty:
        return None
    ranked = listings.copy()
    ranked["_hk"] = ranked.apply(_is_hk_listing, axis=1)
    ranked["_us"] = ranked.apply(_is_us_listing, axis=1)
    if "primary_listing" in ranked.columns:
        ranked["_primary"] = ranked["primary_listing"].fillna(False).astype(bool)
    else:
        ranked["_primary"] = False
    subset = ranked.loc[ranked["_hk"] if hk else ranked["_us"]]
    if subset.empty:
        return None
    if "collection_eligible" in subset.columns:
        subset = subset.loc[subset["collection_eligible"].fillna(False).astype(bool)]
    if subset.empty:
        return None
    if "mapping_status" in subset.columns:
        subset = subset.loc[subset["mapping_status"].astype("string").str.lower().eq("verified")]
    if subset.empty:
        return None
    subset = subset.sort_values(["_primary", "listing_id"], ascending=[False, True])
    return subset.iloc[0]


def load_local_hkex_overlay(
    *,
    entity_id: str,
    listing_id: str | None = None,
    repo_root: Path | None = None,
    mart_dir: Path | None = None,
) -> pd.DataFrame:
    path = (Path(mart_dir) / HKEX_LIVE_MART_NAME) if mart_dir is not None else hkex_live_mart_path(repo_root)
    if not path.is_file():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    if frame.empty:
        return frame
    wanted_entity = str(entity_id or "").strip()
    wanted_listing = str(listing_id or "").strip()
    rows = frame.loc[frame["entity_id"].astype("string").eq(wanted_entity)].copy()
    if wanted_listing and "listing_id" in rows.columns:
        scoped = rows.loc[rows["listing_id"].astype("string").eq(wanted_listing)]
        if not scoped.empty:
            rows = scoped
    if rows.empty:
        return rows
    rows["published_at"] = pd.to_datetime(rows.get("published_at"), errors="coerce", utc=True)
    rows["event_class"] = rows["headline"].map(lambda title: _classify_hkex_title(str(title or "")).get("event_class") or "general")
    return rows.sort_values("published_at", ascending=False, na_position="last").reset_index(drop=True)


def refresh_company_news(
    entity_id: str,
    *,
    repo_root: Path | None = None,
    listing_id: str | None = None,
    api_keys: Mapping[str, str] | None = None,
    now_utc: pd.Timestamp | None = None,
    hkex_lookback_days: int = 14,
    hkex_max_rows: int = 40,
    news_lookback_days: int = 7,
    marketaux_max_rows: int = 3,
    finnhub_max_rows: int = 20,
    timeout_seconds: float = 20.0,
    hkex_session: requests.Session | None = None,
    download_fn=None,
    mart_dir: Path | None = None,
) -> CompanyRefreshResult:
    """Fetch latest official HKEX metadata and vendor headlines for one entity."""

    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    fetched_at = _now_utc() if now_utc is None else pd.Timestamp(now_utc).tz_convert("UTC")
    keys = dict(api_keys) if api_keys is not None else load_news_api_keys(root)
    registries = load_registry_bundle(root / "config" / "research_control_tower")
    listings = _entity_listings(registries.listings, entity_id)
    if listing_id:
        selected = listings.loc[listings["listing_id"].astype("string").eq(str(listing_id))]
        if not selected.empty:
            listings = pd.concat([selected, listings], ignore_index=True).drop_duplicates("listing_id")
    mart_dir = Path(mart_dir) if mart_dir is not None else default_mart_dir(root)
    mart_dir.mkdir(parents=True, exist_ok=True)
    fetch = download_fn or _requests_fetch
    sources = [
        _refresh_hkex(
            entity_id,
            repo_root=root,
            fetched_at=fetched_at,
            lookback_days=hkex_lookback_days,
            max_rows=hkex_max_rows,
            timeout=int(timeout_seconds),
            session=hkex_session,
            mart_dir=mart_dir,
        ),
        _refresh_vendor(
            "marketaux",
            entity_id=entity_id,
            listings=listings,
            keys=keys,
            mart_dir=mart_dir,
            fetched_at=fetched_at,
            lookback_days=news_lookback_days,
            max_rows=marketaux_max_rows,
            timeout=timeout_seconds,
            prefer_hk=True,
            fetch=fetch,
        ),
        _refresh_vendor(
            "finnhub",
            entity_id=entity_id,
            listings=listings,
            keys=keys,
            mart_dir=mart_dir,
            fetched_at=fetched_at,
            lookback_days=news_lookback_days,
            max_rows=finnhub_max_rows,
            timeout=timeout_seconds,
            prefer_hk=False,
            fetch=fetch,
        ),
    ]
    issues = [
        f"{item.source_id}: {item.detail}"
        for item in sources
        if item.status in {"failed", "unavailable"}
    ]
    return CompanyRefreshResult(
        entity_id=entity_id,
        fetched_at_utc=fetched_at,
        sources=tuple(sources),
        issues=tuple(issues),
    )


def _refresh_hkex(
    entity_id: str,
    *,
    repo_root: Path,
    fetched_at: pd.Timestamp,
    lookback_days: int,
    max_rows: int,
    timeout: int,
    session: requests.Session | None = None,
    mart_dir: Path | None = None,
) -> SourceRefreshResult:
    identity_path = repo_root / "config" / "research_control_tower" / "official_source_identity.csv"
    identity = load_source_identity(identity_path)
    rows = identity.loc[
        identity["entity_id"].astype("string").eq(entity_id)
        & identity["source_kind"].astype("string").eq("hkex_code")
    ]
    if rows.empty:
        return SourceRefreshResult(
            source_id="hkexnews",
            status="not_applicable",
            detail="no HKEX listing identity for this entity",
            skipped=True,
        )
    hkex_session = session or requests.Session()
    incoming_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for _, item in rows.iterrows():
        try:
            mapped, state = _hkex_announcement_rows(
                hkex_session,
                ticker=_text(item.get("source_native_id")),
                entity_id=_text(item.get("entity_id")),
                listing_id=_text(item.get("listing_id")),
                canonical_ticker=_text(item.get("canonical_ticker")),
                as_of_utc=fetched_at,
                lookback_days=lookback_days,
                fetched_at=fetched_at,
                timeout=timeout,
                max_rows=max_rows,
            )
            incoming_rows.extend(mapped)
            if state == "unavailable":
                errors.append(f"{item.get('listing_id')}: HKEXnews unavailable")
        except Exception as exc:
            errors.append(f"{item.get('listing_id')}: {type(exc).__name__}")
    incoming = pd.DataFrame(incoming_rows)
    path = (Path(mart_dir) / HKEX_LIVE_MART_NAME) if mart_dir is not None else hkex_live_mart_path(repo_root)
    existing = _load_parquet(path)
    before_ids = set(existing.get("document_id", pd.Series(dtype="string")).astype("string")) if not existing.empty else set()
    merged = merge_hkex_frames(existing, incoming)
    if not merged.empty:
        _atomic_parquet(merged, path)
    new_ids = set()
    if not incoming.empty and "document_id" in incoming.columns:
        new_ids = set(incoming["document_id"].astype("string")) - before_ids
    if errors and incoming.empty:
        return SourceRefreshResult(
            source_id="hkexnews",
            status="unavailable",
            detail="; ".join(errors)[:300],
            new_rows=0,
            total_rows=int(len(merged)),
        )
    return SourceRefreshResult(
        source_id="hkexnews",
        status="available" if not incoming.empty else "no_records",
        detail=(
            f"announcements={len(incoming)}; new={len(new_ids)}"
            + (f"; {errors[0]}" if errors else "")
        ),
        new_rows=int(len(new_ids)),
        total_rows=int(len(merged)),
    )


def _refresh_vendor(
    provider: str,
    *,
    entity_id: str,
    listings: pd.DataFrame,
    keys: Mapping[str, str],
    mart_dir: Path,
    fetched_at: pd.Timestamp,
    lookback_days: int,
    max_rows: int,
    timeout: float,
    prefer_hk: bool,
    fetch,
) -> SourceRefreshResult:
    spec = MARKETAUX_SPEC if provider == "marketaux" else FINNHUB_SPEC
    source_id = str(spec["source_id"])
    api_key = (keys.get(provider) or "").strip()
    if not api_key:
        return SourceRefreshResult(
            source_id=source_id,
            status="unavailable",
            detail=f"{provider} API key not configured",
            skipped=True,
        )
    chosen = _preferred_listing(listings, hk=prefer_hk)
    if chosen is None:
        return SourceRefreshResult(
            source_id=source_id,
            status="skipped",
            detail=(
                "no US ADR listing; Finnhub free tier 403s *.HK"
                if provider == "finnhub"
                else "no matching listing for this provider"
            ),
            skipped=True,
        )
    if provider == "finnhub" and not _is_us_listing(chosen):
        return SourceRefreshResult(
            source_id=source_id,
            status="skipped",
            detail="Finnhub free tier 403s HK symbols; US ADR not registered",
            skipped=True,
        )
    symbol = _provider_symbol(chosen, provider)
    if not symbol:
        return SourceRefreshResult(
            source_id=source_id,
            status="skipped",
            detail="listing has no provider symbol",
            skipped=True,
        )
    # Skip the live entitlement probe on the hot path: it would spend a
    # Marketaux request just to confirm the key still works. 401/403 from
    # collect_structured_news are recorded as unavailable instead.
    evidence = NewsProbeEvidence(
        provider=provider,
        endpoint=str(spec["endpoint"]),
        fields=tuple(spec["fields"]),
        free_limits=str(spec["free_limits"]),
        geography=str(spec["geography"]),
        license_class=str(spec["license_class"]),
        probe_date=fetched_at,
        status="entitled",
        detail="on-demand refresh skipped live entitlement probe",
    )
    result = collect_structured_news(
        spec,
        [(entity_id, _text(chosen.get("listing_id")), symbol)],
        api_key=api_key,
        fetch=fetch,
        probe=evidence,
        as_of_utc=fetched_at,
        lookback_days=lookback_days,
        max_rows_per_symbol=max_rows,
        timeout=timeout,
    )
    path = mart_dir / f"{source_id}.parquet"
    existing = _load_parquet(path)
    before = set(_news_key(existing)) if not existing.empty else set()
    incoming_frame = result.frame if result.frame is not None else None
    incoming_empty = incoming_frame is None or incoming_frame.empty
    if incoming_empty and not existing.empty:
        return SourceRefreshResult(
            source_id=source_id,
            status=result.aggregate_status,
            detail="; ".join(item.reason for item in result.diagnostics) or result.probe.detail,
            new_rows=0,
            total_rows=int(len(existing)),
        )
    merged = merge_news_frames(existing, incoming_frame, now_utc=fetched_at)
    write_news_input(merged, path, result=result)
    incoming_keys = set(_news_key(incoming_frame)) if not incoming_empty else set()
    return SourceRefreshResult(
        source_id=source_id,
        status=result.aggregate_status,
        detail="; ".join(item.reason for item in result.diagnostics) or result.probe.detail,
        new_rows=int(len(incoming_keys - before)),
        total_rows=int(len(merged)),
    )
