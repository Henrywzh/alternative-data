"""Versioned earnings-actuals collection for Control Tower Batch 3.

Collector-side module only; the offline builder consumes the standardized
local parquet inputs written here.  Values come from the official issuer
disclosure layer, never from an aggregator:

- SEC XBRL companyfacts (``data.sec.gov/api/xbrl/companyfacts``, public and
  unauthenticated with a descriptive User-Agent).  Reported values are kept in
  the source currency and accounting basis; ``normalized_value`` mirrors the
  reported value unless a genuine normalization is applied and documented.
  Every row keeps its accession, filing date, XBRL frame and period, and
  restatement lineage is preserved as explicit versions (``version``,
  ``supersedes_actual_id``, ``is_restatement``) instead of overwriting the
  original observation.
- HKEX-only issuers without SEC XBRL (Tencent, Kuaishou, Bilibili) report an
  honest ``no_records``/``partial`` state unless an approved issuer-IR
  snapshot is supplied; nothing is fabricated from HTML.
- ByteDance is ``not_applicable``: no public company disclosure supplies
  values, and no invented financials are ever produced.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests

from ..sec_edgar_data.client import build_retrying_session
from ..sec_edgar_data.config import resolve_user_agent
from ..sec_edgar_data.storage import EdgarStorage
from .build import EARNINGS_ACTUALS_COLUMNS, EARNINGS_ACTUALS_SCHEMA_ID, SOURCE_STATE_COLUMNS


logger = logging.getLogger(__name__)

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
COMPANYFACTS_INTERVAL_SECONDS = 0.2

PIT_CLASS = "snapshot_from_live_source"
LICENSE_CLASS = "official_public_metadata"

# Every mart-facing ``source_id`` this collector emits is namespaced with an
# "earnings:" prefix so it is byte-for-byte identical to the governing
# ``source_health``/source-state record for the same provider
# ("earnings:sec_companyfacts", "earnings:hkex_issuer_ir", below). The two
# standardized outputs (``earnings_actuals_v1.parquet`` and
# ``earnings_actuals_state.parquet``) are written together by this module, so
# keeping their ``source_id`` spelling identical at the point of collection
# means the offline builder and the Control Tower coverage matrix never have
# to guess which health record governs an actuals row.

# Canonical metric tags in the SEC XBRL taxonomy.  The first tag present in a
# filer's companyfacts payload wins; all tags are US-GAAP/IFRS taxonomy names.
METRIC_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "Revenue",
    ),
    "operating_income": (
        "OperatingIncomeLoss",
        "ProfitLossFromOperatingActivities",
    ),
    "net_income": (
        "NetIncomeLoss",
        "ProfitLoss",
    ),
    "eps_basic": (
        "EarningsPerShareBasic",
        "BasicEarningsLossPerShare",
    ),
    "eps_diluted": (
        "EarningsPerShareDiluted",
        "DilutedEarningsLossPerShare",
    ),
}
INTERESTING_FORMS = frozenset({"20-F", "20-F/A", "10-K", "10-Q", "6-K"})


def _now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _utc(value: object) -> pd.Timestamp | pd.NaT:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return pd.NaT
    if pd.isna(parsed):
        return pd.NaT
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def _blank(value: object) -> bool:
    return value is None or value is pd.NaT or (not isinstance(value, (list, tuple, dict)) and pd.isna(value))


def _text(value: object) -> str:
    if _blank(value):
        return ""
    return str(value).strip()


def _period_label(period_start: date, period_end: date, fp: str) -> str:
    fp_text = _text(fp).upper()
    if fp_text == "FY":
        return f"FY{period_end.year}"
    if fp_text in {"Q1", "Q2", "Q3", "Q4"}:
        return f"{fp_text}{period_end.year}"
    if fp_text in {"H1", "H2"}:
        return f"{fp_text}{period_end.year}"
    days = (period_end - period_start).days
    if 330 <= days <= 380:
        return f"FY{period_end.year}"
    if 150 <= days <= 200:
        return f"1H{period_end.year}"
    return f"period ended {period_end.isoformat()}"


class SecCompanyFactsClient:
    """Thin, source-specific client for the public SEC companyfacts JSON API."""

    def __init__(self, user_agent: str, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = build_retrying_session(user_agent)
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < COMPANYFACTS_INTERVAL_SECONDS:
            time.sleep(COMPANYFACTS_INTERVAL_SECONDS - elapsed)
        self._last_request_at = time.monotonic()

    def fetch_company_facts(self, cik: int) -> dict[str, Any]:
        self._throttle()
        response = self.session.get(
            COMPANYFACTS_URL.format(cik=cik), timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()


def _fact_rows(
    payload: Mapping[str, Any],
    *,
    cik: int,
    entity_id: str,
    listing_id: str,
    canonical_ticker: str,
    as_of_utc: pd.Timestamp,
    filed_cutoff: pd.Timestamp,
    fetched_at: pd.Timestamp,
    max_rows: int,
) -> list[dict[str, Any]]:
    """Extract as-reported fact observations with restatement lineage."""

    facts = payload.get("facts", {})
    rows: list[dict[str, Any]] = []
    for metric, tags in METRIC_TAGS.items():
        covered_periods: set[tuple[date, date]] = set()
        metric_rows: list[dict[str, Any]] = []
        for tag in tags:
            taxonomy = ""
            tag_data: Mapping[str, Any] = {}
            for taxonomy_name in ("us-gaap", "ifrs-full"):
                taxonomy_facts = facts.get(taxonomy_name, {})
                if tag in taxonomy_facts:
                    taxonomy = taxonomy_name
                    tag_data = taxonomy_facts[tag]
                    break
            if not taxonomy:
                continue
            units = tag_data.get("units", {})
            if not units:
                continue
            unit, observations = next(iter(units.items()))
            seen_keys: set[tuple[str, date, date]] = set()
            tag_periods: set[tuple[date, date]] = set()
            for observation in observations:
                start = _utc(observation.get("start")).normalize()
                end = _utc(observation.get("end")).normalize()
                filed = _utc(observation.get("filed")).normalize()
                value = observation.get("val")
                if pd.isna(start) or pd.isna(end) or pd.isna(filed) or value is None:
                    continue
                if end > as_of_utc or filed < filed_cutoff:
                    continue
                accession = _text(observation.get("accn"))
                form = _text(observation.get("form")).upper()
                if form not in INTERESTING_FORMS:
                    continue
                period_start = start.date()
                period_end = end.date()
                period_key = (period_start, period_end)
                if period_key in covered_periods:
                    continue
                key = (accession, period_start, period_end)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                tag_periods.add(period_key)
                metric_rows.append(
                    {
                        "metric": metric,
                        "tag": tag,
                        "taxonomy": taxonomy,
                        "period_start": period_start,
                        "period_end": period_end,
                        "period_fp": _text(observation.get("fp")),
                        "reported_value": float(value),
                        "unit": unit,
                        "filing_at": filed,
                        "published_at": filed,
                        "accession_no": accession,
                        "form": form,
                        "xbrl_frame": _text(observation.get("frame")),
                        "cik": cik,
                        "entity_id": entity_id,
                        "listing_id": listing_id,
                        "canonical_ticker": canonical_ticker,
                        "retrieved_at_utc": fetched_at,
                    }
                )
            covered_periods.update(tag_periods)
        rows.extend(metric_rows)
        if len(rows) >= max_rows:
            break
    return rows[:max_rows]


def _lineage(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assign version/supersede links across filings of the same metric+period.

    Rows sharing (metric, period_start, period_end) are ordered by filing
    date/accession; the latest filing is the current value and every earlier
    filing is preserved as a prior version so restatements are visible rather
    than overwritten.
    """

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            row["metric"],
            row["period_start"].isoformat(),
            row["period_end"].isoformat(),
        )
        grouped.setdefault(key, []).append(row)
    output: list[dict[str, Any]] = []
    for members in grouped.values():
        members.sort(key=lambda row: (row["filing_at"].isoformat(), row["accession_no"]))
        previous: dict[str, Any] | None = None
        for version, row in enumerate(members, start=1):
            actual_id = (
                f"actual:{row['metric']}:{row['period_start'].isoformat()}:"
                f"{row['period_end'].isoformat()}:{row['accession_no']}:{version}"
            )
            currency, separator, unit_suffix = row["unit"].partition("/")
            restated = (
                previous is not None
                and previous["reported_value"] != row["reported_value"]
            )
            output.append(
                {
                    "actual_id": actual_id,
                    "version": version,
                    "supersedes_actual_id": previous["actual_id"] if previous else "",
                    "entity_id": row["entity_id"],
                    "listing_id": row["listing_id"],
                    "canonical_ticker": row["canonical_ticker"],
                    "metric": row["metric"],
                    "period_label": _period_label(
                        row["period_start"], row["period_end"], row["period_fp"]
                    ),
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "reported_value": row["reported_value"],
                    "normalized_value": row["reported_value"],
                    "normalization_note": (
                        "as_reported; no normalization applied"
                    ),
                    "currency": currency or row["unit"],
                    "unit": unit_suffix or row["unit"],
                    "accounting_basis": f"{row['taxonomy']} as reported",
                    "filing_at": row["filing_at"],
                    "published_at": row["published_at"],
                    "retrieved_at_utc": row["retrieved_at_utc"],
                    "source_url": (
                        f"https://www.sec.gov/Archives/edgar/data/{row['cik']}/"
                        f"{row['accession_no'].replace('-', '')}/"
                    ),
                    "accession_no": row["accession_no"],
                    "form": row["form"],
                    "xbrl_frame": row["xbrl_frame"],
                    "revision_reason": (
                        "restatement_or_amended_filing" if restated else "refiled"
                        if previous
                        else "initial_filing"
                    ),
                    "is_restatement": restated,
                    "source_id": "earnings:sec_companyfacts",
                    "source_quality": "official_metadata",
                    "pit_class": PIT_CLASS,
                    "source_license_class": LICENSE_CLASS,
                    "source_note": (
                        "SEC XBRL companyfacts; reported value in source currency "
                        "and accounting basis; filing/announcement time is the XBRL "
                        "filing date (SEC metadata exposes no announcement hour)."
                    ),
                    "registry_version": "v1",
                }
            )
            previous = output[-1]
    return output


def _state_row(
    *,
    source_id: str,
    source_kind: str,
    status: str,
    detail: str,
    row_count: int,
    as_of_utc: pd.Timestamp,
    source_url: str = "",
    cadence: str = "",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "status": status,
        "detail": detail,
        "row_count": row_count,
        "first_observation_at": pd.NaT,
        "latest_observation_at": pd.NaT,
        "source_latest_at": pd.NaT,
        "retrieved_at_utc": as_of_utc,
        "source_url": source_url,
        "pit_class": PIT_CLASS,
        "source_license_class": LICENSE_CLASS,
        "cadence": cadence,
    }


def load_source_identity(path: Path) -> pd.DataFrame:
    """Load the official-source identity crosswalk (shared with Batch 2)."""

    frame = pd.read_csv(path, keep_default_na=False)
    required = {"entity_id", "listing_id", "canonical_ticker", "source_kind", "source_native_id"}
    if not required.issubset(set(frame.columns)):
        raise ValueError(f"official source identity is missing columns: {sorted(required - set(frame.columns))}")
    return frame


def collect_earnings_actuals(
    identity: pd.DataFrame,
    *,
    as_of_utc: pd.Timestamp | None = None,
    lookback_days: int = 730,
    max_rows_per_issuer: int = 2000,
    output_dir: Path | None = None,
    ir_snapshot_path: Path | None = None,
    raw_root: Path | None = None,
    user_agent: str | None = None,
    companyfacts_client: SecCompanyFactsClient | None = None,
    timeout: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collect Batch 3 actuals and return (actuals frame, state frame)."""

    fetched_at = _now_utc() if as_of_utc is None else pd.Timestamp(as_of_utc).tz_convert("UTC")
    filed_cutoff = fetched_at - pd.Timedelta(days=lookback_days)
    agent = user_agent or resolve_user_agent(Path.cwd())
    client = companyfacts_client or SecCompanyFactsClient(agent, timeout=timeout)
    storage = EdgarStorage(Path.cwd()) if raw_root is None else EdgarStorage(raw_root)

    rows: list[dict[str, Any]] = []
    sec_errors: list[str] = []
    sec_rows = 0
    hkex_only_entities: list[str] = []
    for _, item in identity.iterrows():
        entity_id = _text(item.get("entity_id"))
        listing_id = _text(item.get("listing_id"))
        canonical_ticker = _text(item.get("canonical_ticker"))
        source_kind = _text(item.get("source_kind"))
        native_id = _text(item.get("source_native_id"))
        if source_kind == "sec_cik":
            try:
                cik = int(native_id)
            except (TypeError, ValueError):
                sec_errors.append(f"{entity_id}: invalid CIK {native_id!r}")
                continue
            try:
                payload = client.fetch_company_facts(cik)
                storage.write_raw_payload(
                    fetched_at.strftime("%Y%m%dT%H%M%SZ"),
                    f"companyfacts_{cik}",
                    payload,
                )
                rows.extend(
                    _lineage(
                        _fact_rows(
                            payload,
                            cik=cik,
                            entity_id=entity_id,
                            listing_id=listing_id,
                            canonical_ticker=canonical_ticker,
                            as_of_utc=fetched_at,
                            filed_cutoff=filed_cutoff,
                            fetched_at=fetched_at,
                            max_rows=max_rows_per_issuer,
                        )
                    )
                )
            except Exception as exc:
                sec_errors.append(f"{entity_id}: {exc}")
        elif source_kind == "hkex_code":
            hkex_only_entities.append(entity_id)
    sec_rows = sum(1 for row in rows if row["source_id"] == "earnings:sec_companyfacts")

    states: list[dict[str, Any]] = []
    if identity["source_kind"].eq("sec_cik").any():
        if sec_errors:
            states.append(
                _state_row(
                    source_id="earnings:sec_companyfacts",
                    source_kind="earnings",
                    status="partial" if sec_rows else "unavailable",
                    detail="; ".join(sec_errors)[:500],
                    row_count=sec_rows,
                    as_of_utc=fetched_at,
                    source_url="https://data.sec.gov/api/xbrl/companyfacts/",
                    cadence="weekly",
                )
            )
        else:
            states.append(
                _state_row(
                    source_id="earnings:sec_companyfacts",
                    source_kind="earnings",
                    status="available",
                    detail=f"sec_companyfacts rows={sec_rows}",
                    row_count=sec_rows,
                    as_of_utc=fetched_at,
                    source_url="https://data.sec.gov/api/xbrl/companyfacts/",
                    cadence="weekly",
                )
            )

    ir_rows: list[dict[str, Any]] = []
    if ir_snapshot_path is not None and Path(ir_snapshot_path).is_file():
        snapshot = (
            pd.read_parquet(ir_snapshot_path)
            if str(ir_snapshot_path).endswith(".parquet")
            else pd.read_csv(Path(ir_snapshot_path), keep_default_na=False)
        )
        if set(EARNINGS_ACTUALS_COLUMNS).issubset(set(snapshot.columns)):
            ir_rows = [
                {**row, "source_id": "earnings:hkex_issuer_ir", "retrieved_at_utc": fetched_at}
                for row in snapshot.to_dict("records")
            ]
            states.append(
                _state_row(
                    source_id="earnings:hkex_issuer_ir",
                    source_kind="earnings",
                    status="available",
                    detail=f"issuer_ir_earnings_snapshot rows={len(ir_rows)}",
                    row_count=len(ir_rows),
                    as_of_utc=fetched_at,
                    cadence="monthly",
                )
            )
        else:
            states.append(
                _state_row(
                    source_id="earnings:hkex_issuer_ir",
                    source_kind="earnings",
                    status="unavailable",
                    detail="issuer_ir_earnings_snapshot schema mismatch; expected earnings_actuals_v1 columns",
                    row_count=0,
                    as_of_utc=fetched_at,
                    cadence="monthly",
                )
            )
    elif hkex_only_entities:
        # Issuer-IR HTML scraping is a deliberate non-goal, not an unfilled
        # query: SEC XBRL companyfacts is the intended source for this
        # concept and HKEX issuers without a CIK simply have no XBRL to
        # consume. ``not_applicable`` is the honest label for a source
        # nobody intends to build (mirrors "earnings:bytedance" below) --
        # ``no_records`` would claim a query executed and came back empty,
        # which never happens here and previously aged this row into a
        # permanent ``review_required`` (see classify_source_health's
        # zero-row + not-execution-completed branch), wrongly capping every
        # entity's earnings_actuals cell at "partial" regardless of real SEC
        # XBRL data. This does NOT manufacture earnings data for the
        # HK-only issuers named below: their entity-level earnings_actuals
        # gap is still visible because no rows exist for them in
        # earnings_actuals_v1.parquet; see _empty_status in coverage.py.
        states.append(
            _state_row(
                source_id="earnings:hkex_issuer_ir",
                source_kind="earnings",
                status="not_applicable",
                detail=(
                    f"HKEX-only issuers without SEC XBRL actuals: {', '.join(sorted(set(hkex_only_entities)))}; "
                    "no machine-readable issuer IR actuals snapshot configured; no values fabricated"
                ),
                row_count=0,
                as_of_utc=fetched_at,
                cadence="",
            )
        )

    states.append(
        _state_row(
            source_id="earnings:bytedance",
            source_kind="earnings",
            status="not_applicable",
            detail=(
                "private company with no public earnings disclosure; "
                "partial/not_applicable unless a reusable public company disclosure exists"
            ),
            row_count=0,
            as_of_utc=fetched_at,
            cadence="",
        )
    )

    rows.extend(ir_rows)
    frame = pd.DataFrame(rows, columns=EARNINGS_ACTUALS_COLUMNS)
    state_frame = pd.DataFrame(states, columns=SOURCE_STATE_COLUMNS)
    # Normalize temporal columns so a mixed ``datetime.date``/``NaT``/tz-aware
    # object column is written as a consistent UTC parquet column instead of
    # failing pyarrow conversion on live data.  The offline builder applies
    # the same coercion when it publishes the date32 mart columns.
    for column in ("period_start", "period_end", "filing_at", "published_at", "retrieved_at_utc"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    for column in ("first_observation_at", "latest_observation_at", "source_latest_at", "retrieved_at_utc"):
        state_frame[column] = pd.to_datetime(state_frame[column], errors="coerce", utc=True)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output_dir / "earnings_actuals_v1.parquet", index=False)
        state_frame.to_parquet(output_dir / "earnings_actuals_state.parquet", index=False)
    return frame, state_frame


__all__ = [
    "EARNINGS_ACTUALS_SCHEMA_ID",
    "SecCompanyFactsClient",
    "collect_earnings_actuals",
    "load_source_identity",
]
