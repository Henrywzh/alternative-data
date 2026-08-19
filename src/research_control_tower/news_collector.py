"""Structured news metadata collection for Control Tower Batch 5.

Collector-side module only: nothing here is imported by the Streamlit app, and
the offline builder consumes only the standardized local parquet inputs this
module writes (the ``ai_news_blog_posts_v1`` contract), plus a ``.status.json``
sidecar in the same convention as ``quote_collector.STATUS_SIDECAR_SUFFIX``.

Scope (approved revised design):

- Structured providers (Finnhub company-news, Marketaux news, FMP stock-news)
  are adopted only after an explicit free-tier entitlement probe records
  endpoint, fields, free limits, geography, license class and probe date.  A
  provider that fails the probe is emitted as ``unavailable`` with evidence --
  never as fake coverage.
- The official-IR allowlist adapter classifies ONLY feeds that a probe verifies
  as genuine structured RSS/Atom (content-type plus item count) as ``official``
  news rows; everything else is an honest ``no_records``.  IR HTML is never
  scraped to manufacture official rows.
- Entity resolution reuses the registry crosswalks (``entities.csv`` names and
  ``listings.csv`` verified vendor tickers / ``financial_data_security_id``)
  through ``registries.resolve_news_entities``, with the versioned
  alias/negative-exclusion table under ``config/research_control_tower/``.
  Unmatchable headlines resolve to EMPTY related ids -- never a guessed link.
- No-body policy: headline/url/metadata are stored; article ``body_text``/
  ``description`` are stored only when the provider license allows it (the
  Batch 5 free-tier probes are metadata-only), and a license-independent
  ``content_hash`` is always computed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Sequence
import uuid
import xml.etree.ElementTree as ET

import pandas as pd

from .registries import resolve_news_entities


NEWS_STATUS_SCHEMA = "news_collection_status_v1"
STATUS_SIDECAR_SUFFIX = ".status.json"
PIT_CLASS = "snapshot_from_live_source"

# Standardized input contract matching build._OPTIONAL_COLUMNS[NEWS_SCHEMA_ID]
# (``ai_news_blog_posts_v1``).  ``description``/``body_text``/``content_hash``
# are optional; ``content_hash`` is the provider-license-independent
# fingerprint that is always emitted.
NEWS_INPUT_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "first_seen_at",
    "last_seen_at",
    "source_name",
    "title",
    "link",
    "pub_date",
    "description",
    "body_text",
    "content_hash",
]

NEWS_AGGREGATE_STATUS = Literal["available", "partial", "no_records", "unavailable"]

PROVIDER_SOURCE_IDS = {
    "finnhub": "news_finnhub",
    "marketaux": "news_marketaux",
    "fmp": "news_fmp",
    "official_ir_allowlist": "news_official_ir_allowlist",
}

# No-body policy gate: article ``description``/``body_text`` are emitted ONLY
# for a provider whose license class opts in.  Batch 5 free-tier probes and
# official-IR metadata are all metadata-only, so this stays empty; a future
# licensed provider would add its license class here with review evidence on
# file before bodies are ever stored.
BODY_ALLOWED_LICENSE_CLASSES = frozenset()


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str
    ok: bool


@dataclass(frozen=True, slots=True)
class NewsProbeEvidence:
    provider: str
    endpoint: str
    fields: tuple[str, ...]
    free_limits: str
    geography: str
    license_class: str
    probe_date: pd.Timestamp
    status: Literal["entitled", "pending", "failed", "no_feed"]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["probe_date"] = _iso(self.probe_date)
        payload["fields"] = list(self.fields)
        return payload


@dataclass(frozen=True, slots=True)
class NewsDiagnostic:
    source_id: str
    entity_id: str
    listing_id: str
    symbol: str
    status: Literal["available", "no_records", "failed", "not_verified"]
    reason: str


@dataclass(frozen=True, slots=True)
class NewsCollectionResult:
    source_id: str
    provider: str
    frame: pd.DataFrame
    aggregate_status: NEWS_AGGREGATE_STATUS
    probe: NewsProbeEvidence
    diagnostics: tuple[NewsDiagnostic, ...]
    issues: tuple[str, ...] = ()
    resolved_rows: int = 0


ProviderFetch = Callable[..., FetchResult]


def _requests_fetch(
    url: str,
    *,
    params: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 20.0,
) -> FetchResult:
    import requests

    response = requests.get(
        url,
        params=dict(params or {}),
        headers=dict(headers or {}),
        timeout=timeout,
    )
    return FetchResult(
        url=str(response.url or url),
        status_code=int(response.status_code),
        content_type=str(response.headers.get("Content-Type", "")),
        text=response.text,
        ok=200 <= int(response.status_code) < 400,
    )


def _now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _utc(value: object) -> pd.Timestamp | pd.NaT:
    if value is None or value is pd.NA or value is pd.NaT:
        return pd.NaT
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = pd.Timestamp(parsedate_to_datetime(str(value)))
        except (TypeError, ValueError, OverflowError):
            return pd.NaT
    if pd.isna(parsed):
        return pd.NaT
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def _iso(value: object) -> str:
    parsed = _utc(value)
    return "" if pd.isna(parsed) else parsed.isoformat()


def _blank(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def _text(value: object) -> str:
    return "" if _blank(value) else str(value).strip()


def _content_hash(link: object, title: object, published: object) -> str:
    """License-independent fingerprint over the canonical article identity."""

    identity = "\x1f".join(
        "" if value is None else str(value)
        for value in (link, title, _iso(published))
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _empty_news_frame() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in NEWS_INPUT_COLUMNS})


def news_status_path(output_path: Path) -> Path:
    """Adjacent ``.status.json`` sidecar path for a news input (quote convention)."""

    output = Path(output_path)
    return output.with_name(f"{output.stem}{STATUS_SIDECAR_SUFFIX}")


def _run_id(provider: str, now_utc: pd.Timestamp) -> str:
    return f"news-{now_utc.strftime('%Y%m%dT%H%M%SZ')}-{provider}"


def _row(
    *,
    provider: str,
    endpoint: str,
    run_id: str,
    now_utc: pd.Timestamp,
    title: object,
    link: object,
    published: object,
    license_class: str,
) -> dict[str, Any]:
    title = _text(title)
    link = _text(link)
    published = _utc(published)
    emit_body = str(license_class or "").strip().lower() in BODY_ALLOWED_LICENSE_CLASSES
    return {
        "dataset_id": "ai_news_blog_posts",
        "source_url": endpoint,
        "source_run_id": run_id,
        "scraped_at": now_utc,
        "first_seen_at": now_utc,
        "last_seen_at": now_utc,
        "source_name": provider,
        "title": title,
        "link": link,
        "pub_date": published,
        "description": "" if not emit_body else "",
        "body_text": "" if not emit_body else "",
        "content_hash": _content_hash(link, title, published) if (title or link) else "",
    }


def _sort_and_dedupe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return _empty_news_frame()
    frame = pd.DataFrame(rows)
    frame["pub_date"] = pd.to_datetime(frame["pub_date"], errors="coerce", utc=True)
    frame = frame.drop_duplicates(subset=["link", "title"], keep="first")
    return frame.sort_values(["pub_date"], kind="mergesort", na_position="last").reset_index(drop=True)


def _aggregate_status(row_count: int, diagnostics: Sequence[NewsDiagnostic]) -> NEWS_AGGREGATE_STATUS:
    failed = sum(1 for item in diagnostics if item.status == "failed")
    available = sum(1 for item in diagnostics if item.status == "available")
    queried = len(diagnostics)
    if row_count > 0:
        return "partial" if failed > 0 or available < queried else "available"
    if failed == 0:
        # A probe that passed with no queryable targets, or genuine empty
        # coverage, is an honest ``no_records`` -- not a failed feed.
        return "no_records"
    return "unavailable"


# ---------------------------------------------------------------------------
# Provider symbol resolution (registry crosswalk reuse)
# ---------------------------------------------------------------------------

def _provider_symbol(listing: Mapping[str, Any], provider: str) -> str:
    raw = listing.get("vendor_tickers", "")
    if not _blank(raw):
        for token in str(raw).split(";"):
            name, separator, symbol = token.partition(":")
            if (
                separator
                and name.strip().casefold() == provider.casefold()
                and symbol.strip()
            ):
                return symbol.strip()
    canonical = _text(listing.get("canonical_ticker"))
    if canonical:
        # US providers use bare exchange tickers ("NVDA"); HK codes ("0700.HK")
        # are passed through untouched.
        if canonical.upper().endswith(".US"):
            return canonical[:-3]
        return canonical
    return ""


def resolve_provider_symbols(listings: pd.DataFrame, provider: str) -> list[tuple[str, str, str]]:
    """Verified, collection-eligible listings -> (entity_id, listing_id, symbol)."""

    if listings is None or listings.empty:
        return []
    resolved: list[tuple[str, str, str]] = []
    for _, row in listings.iterrows():
        if str(row.get("mapping_status") or "").strip().lower() != "verified":
            continue
        if not bool(row.get("collection_eligible")):
            continue
        entity_id = _text(row.get("entity_id"))
        listing_id = _text(row.get("listing_id"))
        symbol = _provider_symbol(row, provider)
        if entity_id and listing_id and symbol:
            resolved.append((entity_id, listing_id, symbol))
    # Deterministic order.
    return sorted(resolved, key=lambda item: (item[1], item[2], item[0]))


# ---------------------------------------------------------------------------
# Entitlement probes + structured provider adapters
# ---------------------------------------------------------------------------

FINNHUB_SPEC = {
    "provider": "finnhub",
    "source_id": "news_finnhub",
    "endpoint": "https://finnhub.io/api/v1/company-news",
    "fields": ("category", "datetime", "headline", "id", "image", "related", "source", "summary", "url"),
    "free_limits": "60 API calls/min on the free tier (as documented at probe time)",
    "geography": "Global exchange coverage incl. US/HK/CN tickers",
    "license_class": "free_tier_metadata_only",
}

MARKETAUX_SPEC = {
    "provider": "marketaux",
    "source_id": "news_marketaux",
    "endpoint": "https://api.marketaux.com/v1/news/all",
    "fields": ("uuid", "title", "description", "snippet", "url", "image_url", "language", "published_at", "source", "tickers"),
    "free_limits": "~100 news requests/day on the free tier (as documented at probe time)",
    "geography": "Global news coverage",
    "license_class": "free_tier_metadata_only",
}

FMP_SPEC = {
    "provider": "fmp",
    "source_id": "news_fmp",
    "endpoint": "https://financialmodelingprep.com/api/v3/stock_news",
    "fields": ("symbol", "date", "title", "site", "text", "url", "image"),
    "free_limits": "~250 requests/day on the free tier (as documented at probe time)",
    "geography": "Global exchange coverage incl. HK tickers",
    "license_class": "free_tier_metadata_only",
}


def probe_finnhub(api_key: str | None, *, fetch: ProviderFetch, now_utc: pd.Timestamp, timeout: float) -> NewsProbeEvidence:
    return _probe_structured(FINNHUB_SPEC, api_key, fetch=fetch, now_utc=now_utc, timeout=timeout)


def probe_marketaux(api_key: str | None, *, fetch: ProviderFetch, now_utc: pd.Timestamp, timeout: float) -> NewsProbeEvidence:
    return _probe_structured(MARKETAUX_SPEC, api_key, fetch=fetch, now_utc=now_utc, timeout=timeout)


def probe_fmp(api_key: str | None, *, fetch: ProviderFetch, now_utc: pd.Timestamp, timeout: float) -> NewsProbeEvidence:
    return _probe_structured(FMP_SPEC, api_key, fetch=fetch, now_utc=now_utc, timeout=timeout)


def _probe_structured(
    spec: Mapping[str, object],
    api_key: str | None,
    *,
    fetch: ProviderFetch,
    now_utc: pd.Timestamp,
    timeout: float,
) -> NewsProbeEvidence:
    """Explicit free-tier entitlement probe for one structured provider.

    Records endpoint, fields, free limits, geography, license class and probe
    date.  Without a key, or on a failed/blocked live call, the provider is
    emitted ``failed`` with evidence -- never assumed entitled.
    """

    provider = str(spec["provider"])
    endpoint = str(spec["endpoint"])
    if not api_key:
        return NewsProbeEvidence(
            provider=provider,
            endpoint=endpoint,
            fields=tuple(spec["fields"]),
            free_limits=str(spec["free_limits"]),
            geography=str(spec["geography"]),
            license_class=str(spec["license_class"]),
            probe_date=now_utc,
            status="failed",
            detail="no API key supplied for entitlement probe",
        )
    probe_window = (now_utc - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    params: Mapping[str, object]
    if provider == "finnhub":
        params = {"symbol": "0700.HK", "from": probe_window, "to": now_utc.strftime("%Y-%m-%d"), "token": api_key}
    elif provider == "marketaux":
        params = {"symbols": "0700.HK", "language": "en", "api_token": api_key}
    else:
        params = {"tickers": "0700.HK", "limit": 1, "apikey": api_key}
    try:
        result = fetch(endpoint, params=params, timeout=timeout)
    except Exception as exc:
        return NewsProbeEvidence(
            provider=provider,
            endpoint=endpoint,
            fields=tuple(spec["fields"]),
            free_limits=str(spec["free_limits"]),
            geography=str(spec["geography"]),
            license_class=str(spec["license_class"]),
            probe_date=now_utc,
            status="failed",
            detail=f"entitlement probe call failed: {exc}",
        )
    if not result.ok or result.status_code in {401, 403, 429}:
        return NewsProbeEvidence(
            provider=provider,
            endpoint=endpoint,
            fields=tuple(spec["fields"]),
            free_limits=str(spec["free_limits"]),
            geography=str(spec["geography"]),
            license_class=str(spec["license_class"]),
            probe_date=now_utc,
            status="failed",
            detail=f"entitlement probe rejected (http={result.status_code}, content_type={result.content_type or 'n/a'})",
        )
    return NewsProbeEvidence(
        provider=provider,
        endpoint=endpoint,
        fields=tuple(spec["fields"]),
        free_limits=str(spec["free_limits"]),
        geography=str(spec["geography"]),
        license_class=str(spec["license_class"]),
        probe_date=now_utc,
        status="entitled",
        detail="free-tier entitlement probe passed",
    )


def collect_structured_news(
    spec: Mapping[str, object],
    symbols: Sequence[tuple[str, str, str]],
    *,
    api_key: str | None,
    fetch: ProviderFetch,
    probe: NewsProbeEvidence,
    as_of_utc: pd.Timestamp,
    lookback_days: int,
    max_rows_per_symbol: int,
    timeout: float,
) -> NewsCollectionResult:
    """Collect one structured provider against a resolved symbol universe."""

    provider = str(spec["provider"])
    source_id = str(spec["source_id"])
    endpoint = str(spec["endpoint"])
    if probe.status != "entitled" or not api_key:
        diagnostic = NewsDiagnostic(
            source_id=source_id,
            entity_id="",
            listing_id="",
            symbol="",
            status="failed",
            reason=f"entitlement probe did not pass: {probe.detail}",
        )
        return NewsCollectionResult(
            source_id=source_id,
            provider=provider,
            frame=_empty_news_frame(),
            aggregate_status="unavailable",
            probe=probe,
            diagnostics=(diagnostic,),
            issues=(f"{provider} unavailable: {probe.detail}",),
        )

    probe_reference = probe.probe_date
    now_utc = (
        pd.Timestamp(probe_reference).tz_convert("UTC")
        if not pd.isna(probe_reference)
        else _now_utc()
    )
    rows: list[dict[str, Any]] = []
    diagnostics: list[NewsDiagnostic] = []
    window_from = (as_of_utc - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    window_to = as_of_utc.strftime("%Y-%m-%d")
    for entity_id, listing_id, symbol in symbols or []:
        try:
            articles = _fetch_structured_symbol(
                spec,
                symbol,
                api_key=api_key,
                fetch=fetch,
                now_utc=now_utc,
                window_from=window_from,
                window_to=window_to,
                max_rows=max_rows_per_symbol,
                timeout=timeout,
            )
        except Exception as exc:
            diagnostics.append(
                NewsDiagnostic(
                    source_id=source_id,
                    entity_id=entity_id,
                    listing_id=listing_id,
                    symbol=symbol,
                    status="failed",
                    reason=f"provider call failed: {exc}",
                )
            )
            continue
        if not articles:
            diagnostics.append(
                NewsDiagnostic(
                    source_id=source_id,
                    entity_id=entity_id,
                    listing_id=listing_id,
                    symbol=symbol,
                    status="no_records",
                    reason="provider returned no news items in window",
                )
            )
            continue
        diagnostics.append(
            NewsDiagnostic(
                source_id=source_id,
                entity_id=entity_id,
                listing_id=listing_id,
                symbol=symbol,
                status="available",
                reason=f"articles={len(articles)}",
            )
        )
        rows.extend(articles)

    return NewsCollectionResult(
        source_id=source_id,
        provider=provider,
        frame=_sort_and_dedupe(rows),
        aggregate_status=_aggregate_status(len(rows), diagnostics),
        probe=probe,
        diagnostics=tuple(diagnostics),
    )


def _fetch_structured_symbol(
    spec: Mapping[str, object],
    symbol: str,
    *,
    api_key: str,
    fetch: ProviderFetch,
    now_utc: pd.Timestamp,
    window_from: str,
    window_to: str,
    max_rows: int,
    timeout: float,
) -> list[dict[str, Any]]:
    provider = str(spec["provider"])
    endpoint = str(spec["endpoint"])
    if provider == "finnhub":
        params = {"symbol": symbol, "from": window_from, "to": window_to, "token": api_key}
        result = fetch(endpoint, params=params, timeout=timeout)
        if not result.ok:
            raise RuntimeError(f"finnhub http={result.status_code}")
        payload = json.loads(result.text or "[]")
        items = payload if isinstance(payload, list) else []
        return [
            _row(
                provider="Finnhub",
                endpoint=endpoint,
                run_id=_run_id(provider, now_utc),
                now_utc=now_utc,
                title=item.get("headline"),
                link=item.get("url"),
                published=item.get("datetime"),
                license_class=str(spec["license_class"]),
            )
            for item in items[:max_rows]
        ]
    if provider == "marketaux":
        params = {"symbols": symbol, "language": "en", "api_token": api_key}
        result = fetch(endpoint, params=params, timeout=timeout)
        if not result.ok:
            raise RuntimeError(f"marketaux http={result.status_code}")
        payload = json.loads(result.text or "{}")
        items = payload.get("data") if isinstance(payload, dict) else []
        return [
            _row(
                provider="Marketaux",
                endpoint=endpoint,
                run_id=_run_id(provider, now_utc),
                now_utc=now_utc,
                title=item.get("title"),
                link=item.get("url"),
                published=item.get("published_at"),
                license_class=str(spec["license_class"]),
            )
            for item in (items or [])[:max_rows]
        ]
    # FMP stock-news
    params = {"tickers": symbol, "limit": max_rows, "apikey": api_key}
    result = fetch(endpoint, params=params, timeout=timeout)
    if not result.ok:
        raise RuntimeError(f"fmp http={result.status_code}")
    payload = json.loads(result.text or "[]")
    items = payload if isinstance(payload, list) else []
    return [
        _row(
            provider="FMP",
            endpoint=endpoint,
            run_id=_run_id(provider, now_utc),
            now_utc=now_utc,
            title=item.get("title"),
            link=item.get("url"),
            published=item.get("date"),
            license_class=str(spec["license_class"]),
        )
        for item in items[:max_rows]
    ]


# ---------------------------------------------------------------------------
# Official-IR allowlist adapter (structured feeds verified by probe)
# ---------------------------------------------------------------------------

IR_ALLOWLIST_FILENAME = "news_official_ir_allowlist.csv"


def load_ir_allowlist(path: Path) -> pd.DataFrame:
    """Load the versioned official-IR feed allowlist (Batch 5)."""

    frame = pd.read_csv(path, dtype="string", keep_default_na=False)
    required = {
        "entity_id",
        "listing_id",
        "canonical_ticker",
        "feed_url",
        "feed_format",
        "registry_version",
        "note",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"IR allowlist is missing required columns: {', '.join(missing)}")
    for column in frame.select_dtypes(include=["string"]).columns:
        frame[column] = frame[column].str.strip()
    if frame["feed_url"].map(_blank).any() or frame["entity_id"].map(_blank).any():
        raise ValueError("IR allowlist rows must declare entity_id and feed_url")
    return frame


def _looks_like_structured_feed(content_type: str, body: str) -> bool:
    """Content-type plus body heuristic used by the official-IR probe."""

    ctype = content_type.lower()
    if "text/html" in ctype:
        return False
    if any(token in ctype for token in ("rss", "atom", "xml")):
        return True
    sample = body[:2048].strip()
    if sample.lstrip().startswith(("<?xml", "<rss", "<feed")):
        return True
    return "<rss" in sample or "<feed" in sample


def _parse_feed(body: str) -> list[dict[str, Any]]:
    """Parse RSS 2.0 or Atom items; returns normalized title/link/published."""

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    tag = root.tag.lower()
    items: list[dict[str, Any]] = []
    if tag.endswith("rss"):
        for item in root.iter("item"):
            title = _text(_child_text(item, "title"))
            link = _text(_child_text(item, "link"))
            published = _child_text(item, "pubDate")
            items.append({"title": title, "link": link, "published": published})
    elif tag.endswith("feed"):
        for entry in root.iter("entry"):
            title = _text(_child_text(entry, "title"))
            link = ""
            for link_node in entry.findall("link"):
                href = link_node.get("href")
                if href:
                    link = _text(href)
                    break
            published = _child_text(entry, "published") or _child_text(entry, "updated")
            items.append({"title": title, "link": link, "published": published})
    return [item for item in items if item["title"] or item["link"]]


def _child_text(element: Any, name: str) -> str:
    child = element.find(name)
    if child is None or child.text is None:
        return ""
    return str(child.text).strip()


def collect_official_ir_allowlist(
    allowlist: pd.DataFrame,
    *,
    fetch: ProviderFetch,
    as_of_utc: pd.Timestamp,
    lookback_days: int,
    timeout: float,
) -> NewsCollectionResult:
    """Collect official news rows ONLY from feeds a probe verifies as genuine.

    Every feed URL is probed for content-type and item count.  Only structured
    RSS/Atom feeds pass; every other issuer's IR page is an honest
    ``no_records`` (never scraped HTML manufactured as official).
    """

    source_id = PROVIDER_SOURCE_IDS["official_ir_allowlist"]
    now_utc = _now_utc() if as_of_utc is None else pd.Timestamp(as_of_utc).tz_convert("UTC")
    run_id = _run_id("official_ir_allowlist", now_utc)
    rows: list[dict[str, Any]] = []
    diagnostics: list[NewsDiagnostic] = []
    verified_feeds = 0
    cutoff = now_utc - pd.Timedelta(days=lookback_days)
    aggregate_probe = NewsProbeEvidence(
        provider="official_ir_allowlist",
        endpoint=", ".join(str(row.get("feed_url") or "") for _, row in allowlist.iterrows())[:500],
        fields=("title", "link", "pub_date"),
        free_limits="n/a (issuer published feeds)",
        geography="issuer IR newsrooms (allowlist only)",
        license_class="official_public_metadata",
        probe_date=now_utc,
        status="no_feed",
        detail="no verified structured issuer feed",
    )
    for _, row in allowlist.iterrows():
        feed_url = _text(row.get("feed_url"))
        entity_id = _text(row.get("entity_id"))
        listing_id = _text(row.get("listing_id"))
        canonical_ticker = _text(row.get("canonical_ticker"))
        try:
            result = fetch(feed_url, timeout=timeout)
        except Exception as exc:
            diagnostics.append(
                NewsDiagnostic(
                    source_id=source_id,
                    entity_id=entity_id,
                    listing_id=listing_id,
                    symbol=canonical_ticker or feed_url,
                    status="not_verified",
                    reason=f"official IR probe fetch failed: {exc}",
                )
            )
            continue
        if not result.ok or not _looks_like_structured_feed(result.content_type, result.text):
            diagnostics.append(
                NewsDiagnostic(
                    source_id=source_id,
                    entity_id=entity_id,
                    listing_id=listing_id,
                    symbol=canonical_ticker or feed_url,
                    status="not_verified",
                    reason=(
                        f"official IR feed not structured (http={result.status_code}, "
                        f"content_type={result.content_type or 'n/a'}); HTML IR pages are never scraped"
                    ),
                )
            )
            continue
        items = _parse_feed(result.text)
        if not items:
            diagnostics.append(
                NewsDiagnostic(
                    source_id=source_id,
                    entity_id=entity_id,
                    listing_id=listing_id,
                    symbol=canonical_ticker or feed_url,
                    status="not_verified",
                    reason="official IR feed returned zero parseable items",
                )
            )
            continue
        verified_feeds += 1
        diagnostics.append(
            NewsDiagnostic(
                source_id=source_id,
                entity_id=entity_id,
                listing_id=listing_id,
                symbol=canonical_ticker or feed_url,
                status="available",
                reason=f"official IR feed verified (content_type={result.content_type}, items={len(items)})",
            )
        )
        for item in items:
            published = _utc(item.get("published"))
            if pd.isna(published) or published < cutoff:
                continue
            rows.append(
                _row(
                    provider="Official IR",
                    endpoint=feed_url,
                    run_id=run_id,
                    now_utc=now_utc,
                    title=item.get("title"),
                    link=item.get("link"),
                    published=published,
                    license_class="official_public_metadata",
                )
            )
    if verified_feeds > 0:
        aggregate_probe = NewsProbeEvidence(
            provider="official_ir_allowlist",
            endpoint=aggregate_probe.endpoint,
            fields=("title", "link", "pub_date"),
            free_limits="n/a (issuer published feeds)",
            geography="issuer IR newsrooms (allowlist only)",
            license_class="official_public_metadata",
            probe_date=now_utc,
            status="entitled",
            detail=f"verified_feeds={verified_feeds}",
        )
    return NewsCollectionResult(
        source_id=source_id,
        provider="official_ir_allowlist",
        frame=_sort_and_dedupe(rows),
        aggregate_status="available" if rows else "no_records",
        probe=aggregate_probe,
        diagnostics=tuple(diagnostics),
        issues=(
            ()
            if rows
            else ("no verified structured issuer IR feed; honest no_records",)
        ),
    )


# ---------------------------------------------------------------------------
# Top-level collection entry + atomic writes
# ---------------------------------------------------------------------------

def write_news_input(
    frame: pd.DataFrame,
    output_path: Path,
    *,
    result: NewsCollectionResult,
) -> Path:
    """Write a standardized news parquet + status sidecar atomically."""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    prepared = frame.reindex(columns=NEWS_INPUT_COLUMNS)
    temp_filename = f".{output.name}.{uuid.uuid4().hex}.tmp"
    temporary = output.with_name(temp_filename)
    prepared.to_parquet(temporary, index=False)
    temporary.replace(output)

    sidecar_payload = {
        "schema": NEWS_STATUS_SCHEMA,
        "source_id": result.source_id,
        "provider": result.provider,
        "aggregate_status": result.aggregate_status,
        "row_count": int(len(prepared)),
        "probe": result.probe.to_dict(),
        "diagnostic_count": int(len(result.diagnostics)),
        "diagnostics": [asdict(item) for item in result.diagnostics],
        "issues": list(result.issues),
        "entity_resolution": {"resolved_rows": int(result.resolved_rows), "total_rows": int(len(prepared))},
    }
    sidecar = news_status_path(output)
    sidecar_temp = sidecar.with_name(f".{sidecar.name}.{uuid.uuid4().hex}.tmp")
    sidecar_temp.write_text(
        json.dumps(sidecar_payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sidecar_temp.replace(sidecar)
    return output


def collect_news(
    input_dir: Path,
    as_of_utc: pd.Timestamp | None = None,
    *,
    providers: Sequence[str] | None = None,
    api_keys: Mapping[str, str] | None = None,
    download_fn: ProviderFetch | None = None,
    now_utc: pd.Timestamp | None = None,
    listings: pd.DataFrame | None = None,
    entities: pd.DataFrame | None = None,
    aliases: pd.DataFrame | None = None,
    ir_allowlist: pd.DataFrame | None = None,
    timeout_seconds: float = 20.0,
    lookback_days: int = 45,
    max_rows_per_symbol: int = 200,
) -> tuple[dict[str, Path], list[NewsCollectionResult]]:
    """Collect Batch 5 news metadata and write standardized local inputs.

    Writes one ``<source_id>.parquet`` plus a ``.status.json`` sidecar per
    provider under ``input_dir`` so the offline builder can consume them with
    networking disabled.  ``download_fn``/``api_keys`` are injected; a provider
    that fails its entitlement probe is written as an honest ``unavailable``
    with recorded evidence, never as fake coverage.
    """

    directory = Path(input_dir)
    directory.mkdir(parents=True, exist_ok=True)
    requested = list(providers) if providers else list(PROVIDER_SOURCE_IDS)
    unknown = [name for name in requested if name not in PROVIDER_SOURCE_IDS]
    if unknown:
        raise ValueError(f"unknown news provider(s): {sorted(set(unknown))}")
    keys = dict(api_keys or {})
    fetch = download_fn or _requests_fetch
    reference_utc = _now_utc() if now_utc is None else pd.Timestamp(now_utc).tz_convert("UTC")
    reference_as_of = (
        reference_utc
        if as_of_utc is None
        else pd.Timestamp(as_of_utc).tz_convert("UTC")
    )

    written: dict[str, Path] = {}
    results: list[NewsCollectionResult] = []
    for provider in requested:
        source_id = PROVIDER_SOURCE_IDS[provider]
        output_path = directory / f"{source_id}.parquet"
        result: NewsCollectionResult
        if provider == "official_ir_allowlist":
            if ir_allowlist is None:
                candidate = directory / IR_ALLOWLIST_FILENAME
                if candidate.is_file():
                    ir_allowlist = load_ir_allowlist(candidate)
            if ir_allowlist is None:
                empty_probe = NewsProbeEvidence(
                    provider="official_ir_allowlist",
                    endpoint="",
                    fields=("title", "link", "pub_date"),
                    free_limits="n/a",
                    geography="",
                    license_class="official_public_metadata",
                    probe_date=reference_utc,
                    status="no_feed",
                    detail="no official-IR allowlist configured",
                )
                result = NewsCollectionResult(
                    source_id=source_id,
                    provider=provider,
                    frame=_empty_news_frame(),
                    aggregate_status="no_records",
                    probe=empty_probe,
                    diagnostics=(),
                    issues=("no official-IR allowlist configured; honest no_records",),
                )
            else:
                result = collect_official_ir_allowlist(
                    ir_allowlist,
                    fetch=fetch,
                    as_of_utc=reference_as_of,
                    lookback_days=lookback_days,
                    timeout=timeout_seconds,
                )
        elif provider == "finnhub":
            probe = probe_finnhub(
                keys.get("finnhub"),
                fetch=fetch,
                now_utc=reference_utc,
                timeout=timeout_seconds,
            )
            result = collect_structured_news(
                FINNHUB_SPEC,
                resolve_provider_symbols(listings, "finnhub") if listings is not None else [],
                api_key=keys.get("finnhub"),
                fetch=fetch,
                probe=probe,
                as_of_utc=reference_as_of,
                lookback_days=lookback_days,
                max_rows_per_symbol=max_rows_per_symbol,
                timeout=timeout_seconds,
            )
        elif provider == "marketaux":
            probe = probe_marketaux(
                keys.get("marketaux"),
                fetch=fetch,
                now_utc=reference_utc,
                timeout=timeout_seconds,
            )
            result = collect_structured_news(
                MARKETAUX_SPEC,
                resolve_provider_symbols(listings, "marketaux") if listings is not None else [],
                api_key=keys.get("marketaux"),
                fetch=fetch,
                probe=probe,
                as_of_utc=reference_as_of,
                lookback_days=lookback_days,
                max_rows_per_symbol=max_rows_per_symbol,
                timeout=timeout_seconds,
            )
        else:  # fmp
            probe = probe_fmp(
                keys.get("fmp"),
                fetch=fetch,
                now_utc=reference_utc,
                timeout=timeout_seconds,
            )
            result = collect_structured_news(
                FMP_SPEC,
                resolve_provider_symbols(listings, "fmp") if listings is not None else [],
                api_key=keys.get("fmp"),
                fetch=fetch,
                probe=probe,
                as_of_utc=reference_as_of,
                lookback_days=lookback_days,
                max_rows_per_symbol=max_rows_per_symbol,
                timeout=timeout_seconds,
            )

        result = _attach_entity_resolution(result, entities, listings, aliases)
        written[source_id] = write_news_input(result.frame, output_path, result=result)
        results.append(result)
    return written, results


def _attach_entity_resolution(
    result: NewsCollectionResult,
    entities: pd.DataFrame | None,
    listings: pd.DataFrame | None,
    aliases: pd.DataFrame | None,
) -> NewsCollectionResult:
    """Record how many collected headlines resolve (evidence only, no columns)."""

    if result.frame is None or result.frame.empty or entities is None or listings is None:
        return result
    resolved = 0
    for _, item in result.frame.iterrows():
        entity_ids, _ = resolve_news_entities(
            f"{item.get('title', '')}",
            entities=entities,
            listings=listings,
            aliases=aliases,
        )
        if entity_ids:
            resolved += 1
    note = f"entity resolution matched {resolved}/{int(len(result.frame))} headlines"
    issues = (*result.issues, note) if note not in result.issues else result.issues
    return NewsCollectionResult(
        source_id=result.source_id,
        provider=result.provider,
        frame=result.frame,
        aggregate_status=result.aggregate_status,
        probe=result.probe,
        diagnostics=result.diagnostics,
        issues=issues,
        resolved_rows=resolved,
    )


__all__ = [
    "FINNHUB_SPEC",
    "FMP_SPEC",
    "MARKETAUX_SPEC",
    "NEWS_INPUT_COLUMNS",
    "NEWS_STATUS_SCHEMA",
    "NewsCollectionResult",
    "NewsDiagnostic",
    "NewsProbeEvidence",
    "PROVIDER_SOURCE_IDS",
    "STATUS_SIDECAR_SUFFIX",
    "collect_news",
    "collect_official_ir_allowlist",
    "collect_structured_news",
    "load_ir_allowlist",
    "news_status_path",
    "probe_finnhub",
    "probe_fmp",
    "probe_marketaux",
    "resolve_provider_symbols",
    "write_news_input",
]
