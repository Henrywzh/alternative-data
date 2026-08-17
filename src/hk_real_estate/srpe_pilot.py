"""Bounded SRPE PDF backfill for the residential-developer pilot.

This runner deliberately operates on an explicit phase-level registry.  It
does not attempt to discover or download every Hong Kong development.  The
registry is the auditable boundary for the pilot and can be expanded only
after the parser and attribution checks pass.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from .config import DEFAULT_HEADERS, REGISTRY_DIR
from .sources.srpe import (
    SRPE_API_BASE,
    SRPE_DOWNLOAD_ACTIONS,
    SRPEDocumentDownloadError,
    download_srpe_document,
)
from .sources.srpe_pdf import (
    PRICE_LIST_COLUMNS,
    TRANSACTION_COLUMNS,
    build_srpe_sales_signals,
    parse_srpe_price_list_pdf,
    parse_srpe_transaction_pdf,
)
from .sources.shkp import _record_has_phase_specific_effective_interval
from .storage import RAW_DIR, save_normalized_dataset, save_raw_snapshot


logger = logging.getLogger("hk_real_estate_srpe_pilot")

SRPE_PROJECT_REGISTRY_PATH = REGISTRY_DIR / "hk_srpe_project_registry.csv"
SRPE_DETAIL_ENDPOINT = f"{SRPE_API_BASE}/DevBldgSearch/getSelectedDevResult"

REGISTRY_REQUIRED_COLUMNS = {
    "project_id",
    "stock_code",
    "ownership_pct",
    "srpe_dev_id",
    "srpe_development_id",
    "development_name",
    "phase_name",
    "phase_no",
    "development_address",
    "pilot_group",
}

REGISTRY_OPTIONAL_GATE_COLUMNS = {
    "ownership_effective_from",
    "ownership_effective_to",
    "ownership_interval_evidence_type",
    "ownership_attribution_decision_id",
    "ownership_interval_promotion_status",
    "ownership_attribution_ready",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().casefold() in {"true", "1", "yes", "y"}

AUDIT_COLUMNS = [
    "run_id",
    "project_id",
    "stock_code",
    "srpe_dev_id",
    "document_category",
    "document_id",
    "document_serial_no",
    "file_name",
    "submission_time",
    "date_of_printing",
    "expected_file_size_bytes",
    "actual_file_size_bytes",
    "document_hash",
    "raw_snapshot_path",
    "download_endpoint",
    "parse_status",
    "source_rows",
    "rows_emitted",
    "error",
]


def load_srpe_project_registry(path: Path = SRPE_PROJECT_REGISTRY_PATH) -> pd.DataFrame:
    """Load and validate the explicit phase-level SRPE pilot boundary."""
    frame = pd.read_csv(path, dtype=str)
    missing = sorted(REGISTRY_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(f"SRPE project registry missing columns: {', '.join(missing)}")
    if frame["project_id"].duplicated().any():
        raise ValueError("SRPE project registry contains duplicate project_id values")
    for column in ("project_id", "srpe_dev_id", "srpe_development_id", "development_name", "phase_name"):
        if frame[column].astype("string").str.strip().eq("").any():
            raise ValueError(f"SRPE project registry contains blank {column}")
    frame["stock_code"] = frame["stock_code"].astype("string").str.strip().str.zfill(4)
    frame["ownership_pct"] = pd.to_numeric(frame["ownership_pct"], errors="coerce")
    if frame["ownership_pct"].isna().any() or (~frame["ownership_pct"].between(0, 100)).any():
        raise ValueError("SRPE project registry ownership_pct must be between 0 and 100")
    frame["srpe_dev_id"] = frame["srpe_dev_id"].astype("string").str.strip()
    frame["srpe_development_id"] = frame["srpe_development_id"].astype("string").str.strip()
    for column in REGISTRY_OPTIONAL_GATE_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame["ownership_attribution_ready"] = frame.apply(
        lambda row: _as_bool(row.get("ownership_attribution_ready"))
        and _record_has_phase_specific_effective_interval(row.to_dict()),
        axis=1,
    )
    # Keep the derived status available to the monthly-signal join even when
    # the registry CSV predates this column.  The effective-interval check is
    # the only route to the approved value; a legacy snapshot percentage is
    # never enough.
    frame["sales_attribution_status"] = frame["ownership_attribution_ready"].map(
        {
            True: "approved_phase_specific_interval",
            False: "blocked_phase_specific_interval",
        }
    )
    return frame


def select_srpe_projects(
    registry: pd.DataFrame,
    projects: Iterable[str] | None = None,
    pilot_group: str = "core_pilot",
) -> pd.DataFrame:
    """Select projects by stable project_id or use one explicit pilot group."""
    selected = registry.copy()
    if projects:
        requested = {str(value).strip() for value in projects if str(value).strip()}
        selected = selected[selected["project_id"].isin(requested)]
        missing = sorted(requested - set(selected["project_id"]))
        if missing:
            raise ValueError(f"SRPE project ids not found: {', '.join(missing)}")
    else:
        selected = selected[selected["pilot_group"].eq(pilot_group)]
    if selected.empty:
        raise ValueError("SRPE project selection is empty")
    return selected.reset_index(drop=True)


def fetch_srpe_project_detail(
    srpe_dev_id: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    """Fetch the full SRPE document manifest for one selected development."""
    client = session or requests.Session()
    client.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://www.srpe.gov.hk",
            "Referer": "https://www.srpe.gov.hk/opip/",
        }
    )
    # Use an explicit connect/read tuple.  A scalar timeout is normally
    # sufficient, but the SRPE endpoint has occasionally left a pooled TLS
    # connection waiting indefinitely during a multi-phase batch; a bounded
    # read timeout keeps one unavailable manifest from blocking all later
    # phases.
    bounded_timeout = max(float(timeout), 1.0)
    response = client.post(
        SRPE_DETAIL_ENDPOINT,
        json={"timeStamp": int(time.time() * 1000), "devId": str(srpe_dev_id)},
        timeout=(bounded_timeout, bounded_timeout),
    )
    response.raise_for_status()
    result = response.json().get("resultData") or {}
    return result.get("devInfoResp") or {}


def _document_date(document: dict[str, Any]) -> pd.Timestamp:
    file_info = document.get("file") or {}
    return pd.to_datetime(
        document.get("dateOfPrinting")
        or file_info.get("submissionTime")
        or document.get("submissionTime"),
        errors="coerce",
        utc=True,
    )


def select_price_documents(
    documents: list[dict[str, Any]],
    *,
    since: pd.Timestamp | None = None,
    until: pd.Timestamp | None = None,
    selection: str = "first_latest",
    max_documents: int = 0,
) -> list[dict[str, Any]]:
    """Select a bounded price-list history without losing the initial/latest pair."""
    dated = sorted(documents, key=lambda item: (pd.isna(_document_date(item)), _document_date(item)))
    eligible: list[dict[str, Any]] = []
    for document in dated:
        date = _document_date(document)
        if since is not None and not pd.isna(date) and date < since:
            continue
        if until is not None and not pd.isna(date) and date > until:
            continue
        eligible.append(document)
    if selection not in {"all", "first_latest"}:
        raise ValueError("price selection must be 'all' or 'first_latest'")
    if selection == "all":
        chosen = eligible
    elif len(eligible) <= 2:
        chosen = eligible
    else:
        chosen = [eligible[0], eligible[-1]]
    if max_documents > 0:
        if len(chosen) > max_documents:
            chosen = chosen[-max_documents:]
    unique: dict[str, dict[str, Any]] = {}
    for document in chosen:
        key = str(document.get("id") or (document.get("file") or {}).get("fileName"))
        unique[key] = document
    return list(unique.values())


def select_transaction_documents(
    documents: list[dict[str, Any]],
    *,
    all_transaction_documents: bool = False,
) -> list[dict[str, Any]]:
    """Select transaction-register versions without losing chronology.

    The default remains the bounded pilot's latest-register behavior.  Full
    history mode returns every metadata row in printing/submission order;
    downstream unit-state reconciliation is responsible for collapsing
    revisions and cancellations.
    """
    dated = sorted(documents or [], key=lambda item: (pd.isna(_document_date(item)), _document_date(item)))
    if all_transaction_documents:
        return dated
    return dated[-1:] if dated else []


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _reuse_or_save_pdf(
    source_name: str,
    content: bytes,
    *,
    source_url: str,
    run_id: str,
) -> tuple[Path, bool]:
    """Save a PDF once per content hash and return (path, reused)."""
    import hashlib

    digest = hashlib.sha256(content).hexdigest()
    source_dir = RAW_DIR / source_name
    if source_dir.exists():
        for meta_path in source_dir.rglob("*.meta.json"):
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("sha256") == digest:
                raw_name = meta_path.name.removesuffix(".meta.json")
                raw_path = meta_path.with_name(raw_name)
                if raw_path.exists():
                    return raw_path, True
    return save_raw_snapshot(source_name, content, file_ext="pdf", source_url=source_url, run_id=run_id), False


def _project_fields(project: pd.Series) -> dict[str, Any]:
    attribution_ready = _as_bool(project.get("ownership_attribution_ready")) and _record_has_phase_specific_effective_interval(project.to_dict())
    return {
        "project_id": project["project_id"],
        "stock_code": project["stock_code"],
        "ownership_pct": float(project["ownership_pct"]),
        "srpe_dev_id": project["srpe_dev_id"],
        "srpe_development_id": project["srpe_development_id"],
        "project_phase_no": project["phase_no"],
        "ownership_attribution_ready": attribution_ready,
        "ownership_effective_from": project.get("ownership_effective_from"),
        "ownership_effective_to": project.get("ownership_effective_to"),
        "ownership_interval_evidence_type": project.get("ownership_interval_evidence_type"),
        "ownership_attribution_decision_id": project.get("ownership_attribution_decision_id"),
        "ownership_interval_promotion_status": project.get("ownership_interval_promotion_status"),
        "sales_attribution_status": (
            "approved_phase_specific_interval"
            if attribution_ready
            else "blocked_phase_specific_interval"
        ),
    }


def _with_project_fields(frame: pd.DataFrame, project: pd.Series) -> pd.DataFrame:
    result = frame.copy()
    for column, value in _project_fields(project).items():
        result[column] = value
    attribution_ready = bool(result.get("ownership_attribution_ready", pd.Series(dtype=bool)).iloc[0]) if not result.empty else False
    if "transaction_price_hkd" in result.columns:
        result["transaction_value_attributable_hkd"] = float("nan")
        if attribution_ready:
            result["transaction_value_attributable_hkd"] = (
                result["transaction_price_hkd"] * result["ownership_pct"] / 100
            )
    if "price_hkd" in result.columns:
        result["price_value_attributable_hkd"] = float("nan")
        if attribution_ready:
            result["price_value_attributable_hkd"] = result["price_hkd"] * result["ownership_pct"] / 100
    return result


def _filter_transactions(
    frame: pd.DataFrame,
    *,
    since: pd.Timestamp | None,
    until: pd.Timestamp | None,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    dates = pd.to_datetime(result["date_of_pasp"], errors="coerce", utc=True)
    if since is not None:
        result = result.loc[dates >= since].copy()
        dates = dates.loc[result.index]
    if until is not None:
        result = result.loc[dates <= until].copy()
    return result.reset_index(drop=True)


def _audit_row(
    run_id: str,
    project: pd.Series,
    category: str,
    document: dict[str, Any],
    *,
    status: str,
    source_rows: int = 0,
    rows_emitted: int = 0,
    raw_path: str | None = None,
    actual_size: int | None = None,
    document_hash: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    file_info = document.get("file") or {}
    return {
        "run_id": run_id,
        "project_id": project["project_id"],
        "stock_code": project["stock_code"],
        "srpe_dev_id": project["srpe_dev_id"],
        "document_category": category,
        "document_id": document.get("id") or file_info.get("id"),
        "document_serial_no": document.get("serialNo"),
        "file_name": file_info.get("fileName"),
        "submission_time": file_info.get("submissionTime"),
        "date_of_printing": document.get("dateOfPrinting"),
        "expected_file_size_bytes": file_info.get("fileSize"),
        "actual_file_size_bytes": actual_size,
        "document_hash": document_hash,
        "raw_snapshot_path": raw_path,
        "download_endpoint": f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS[category]}",
        "parse_status": status,
        "source_rows": source_rows,
        "rows_emitted": rows_emitted,
        "error": error,
    }


def run_srpe_pilot(
    *,
    run_id: str | None = None,
    registry_path: Path = SRPE_PROJECT_REGISTRY_PATH,
    projects: Iterable[str] | None = None,
    pilot_group: str = "core_pilot",
    since: str | None = None,
    until: str | None = None,
    price_selection: str = "first_latest",
    max_price_documents: int = 0,
    all_transaction_documents: bool = False,
    transactions_only: bool = False,
    dataset_prefix: str = "",
    request_delay: float = 0.2,
    timeout: float = 30,
) -> dict[str, Any]:
    """Run the bounded SRPE project backfill and persist four datasets."""
    if dataset_prefix and not dataset_prefix.endswith("_"):
        dataset_prefix = f"{dataset_prefix}_"
    dataset_name = lambda base: f"{dataset_prefix}{base}"
    run_id = run_id or str(uuid.uuid4())
    registry = load_srpe_project_registry(registry_path)
    selected = select_srpe_projects(registry, projects, pilot_group)
    since_ts = pd.Timestamp(since, tz="UTC") if since else None
    until_ts = pd.Timestamp(until, tz="UTC") if until else None

    registry_raw = save_raw_snapshot(
        "srpe_pilot_registry",
        registry.to_csv(index=False),
        file_ext="csv",
        source_url=str(registry_path),
        run_id=run_id,
    )
    raw_snapshots = [str(registry_raw)]
    source_urls = [str(registry_path), SRPE_DETAIL_ENDPOINT]
    transactions: list[pd.DataFrame] = []
    prices: list[pd.DataFrame] = []
    audit: list[dict[str, Any]] = []
    project_results: list[dict[str, Any]] = []
    session = requests.Session()

    for _, project in selected.iterrows():
        project_result: dict[str, Any] = {
            "project_id": project["project_id"],
            "stock_code": project["stock_code"],
            "srpe_dev_id": project["srpe_dev_id"],
            "status": "success",
            "errors": [],
            "transaction_rows": 0,
            "price_rows": 0,
            "ownership_attribution_ready": bool(project.get("ownership_attribution_ready")),
            "sales_attribution_status": project.get("sales_attribution_status"),
        }
        try:
            detail = fetch_srpe_project_detail(project["srpe_dev_id"], session=session, timeout=timeout)
            detail_raw = save_raw_snapshot(
                f"srpe_pilot_manifest_{project['project_id']}",
                json.dumps(detail, ensure_ascii=False),
                file_ext="json",
                source_url=SRPE_DETAIL_ENDPOINT,
                run_id=run_id,
            )
            raw_snapshots.append(str(detail_raw))
            dev_info = detail.get("dev") or {}
            # The original bounded pilot intentionally parsed only the latest
            # register.  Full-history scratch runs can opt into every
            # register version; raw hashes and unit-state reconciliation keep
            # revisions from being mistaken for new sales.
            transaction_docs = select_transaction_documents(
                detail.get("transactions") or [],
                all_transaction_documents=all_transaction_documents,
            )
            price_docs = [] if transactions_only else select_price_documents(
                detail.get("prices") or [],
                since=since_ts,
                until=until_ts,
                selection=price_selection,
                max_documents=max_price_documents,
            )

            documents = [("register_of_transactions", doc) for doc in transaction_docs]
            documents.extend(("price_list", doc) for doc in price_docs)
            for category, document in documents:
                document_id = document.get("id") or (document.get("file") or {}).get("id")
                if not document_id:
                    audit.append(_audit_row(run_id, project, category, document, status="error", error="missing document id"))
                    project_result["errors"].append(f"{category}: missing document id")
                    continue
                try:
                    content = download_srpe_document(
                        category,
                        document_id,
                        project["srpe_dev_id"],
                        seq=(document.get("file") or {}).get("seq"),
                        session=session,
                        timeout=timeout,
                    )
                    endpoint = f"{SRPE_API_BASE}/download/{SRPE_DOWNLOAD_ACTIONS[category]}"
                    raw_path, reused = _reuse_or_save_pdf(
                        f"srpe_pilot_{category}",
                        content,
                        source_url=endpoint,
                        run_id=run_id,
                    )
                    raw_snapshots.append(str(raw_path))
                    source_urls.append(endpoint)
                    if category == "register_of_transactions":
                        parsed = parse_srpe_transaction_pdf(
                            content,
                            development_id=project["srpe_dev_id"],
                            development_name=project["development_name"],
                            phase_name=project["phase_name"],
                            development_address=project["development_address"],
                            document_id=str(document_id),
                            document_serial_no=document.get("serialNo"),
                            source_document=(document.get("file") or {}).get("fileName"),
                        )
                        parsed = _filter_transactions(parsed, since=since_ts, until=until_ts)
                        parsed = _with_project_fields(parsed, project)
                        parsed["raw_snapshot_path"] = str(raw_path)
                        transactions.append(parsed)
                    else:
                        parsed = parse_srpe_price_list_pdf(
                            content,
                            development_id=project["srpe_dev_id"],
                            development_name=project["development_name"],
                            phase_name=project["phase_name"],
                            development_address=project["development_address"],
                            document_id=str(document_id),
                            document_serial_no=document.get("serialNo"),
                            source_document=(document.get("file") or {}).get("fileName"),
                        )
                        parsed = _with_project_fields(parsed, project)
                        parsed["raw_snapshot_path"] = str(raw_path)
                        prices.append(parsed)
                    audit.append(
                        _audit_row(
                            run_id,
                            project,
                            category,
                            document,
                            status="success" if not parsed.empty else "empty",
                            source_rows=len(parsed),
                            rows_emitted=len(parsed),
                            raw_path=str(raw_path),
                            actual_size=len(content),
                            document_hash=parsed["document_hash"].iloc[0] if not parsed.empty else None,
                        )
                    )
                    project_result["transaction_rows"] += len(parsed) if category == "register_of_transactions" else 0
                    project_result["price_rows"] += len(parsed) if category == "price_list" else 0
                except (SRPEDocumentDownloadError, requests.RequestException, ValueError, RuntimeError) as exc:
                    message = str(exc)
                    audit.append(_audit_row(run_id, project, category, document, status="error", error=message))
                    project_result["errors"].append(f"{category} {document_id}: {message}")
            if project_result["errors"]:
                project_result["status"] = "partial"
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            message = str(exc)
            project_result["status"] = "error"
            project_result["errors"].append(f"manifest: {message}")
        project_results.append(project_result)
        if request_delay:
            time.sleep(request_delay)

    transactions = [frame for frame in transactions if not frame.empty]
    prices = [frame for frame in prices if not frame.empty]
    transaction_frame = pd.concat(transactions, ignore_index=True) if transactions else _empty_frame(TRANSACTION_COLUMNS)
    price_frame = pd.concat(prices, ignore_index=True) if prices else _empty_frame(PRICE_LIST_COLUMNS)
    signal_frame = build_srpe_sales_signals(transaction_frame, price_frame)
    if not signal_frame.empty:
        mapping = selected.set_index("srpe_dev_id")
        signal_frame["project_id"] = signal_frame["development_id"].map(mapping["project_id"])
        signal_frame["stock_code"] = signal_frame["development_id"].map(mapping["stock_code"])
        signal_frame["ownership_pct"] = signal_frame["development_id"].map(mapping["ownership_pct"])
        signal_frame["srpe_development_id"] = signal_frame["development_id"].map(mapping["srpe_development_id"])
        signal_frame["ownership_attribution_ready"] = signal_frame["development_id"].map(mapping["ownership_attribution_ready"]).fillna(False).astype(bool)
        signal_frame["sales_attribution_status"] = signal_frame["development_id"].map(mapping["sales_attribution_status"])
        signal_frame["sales_value_attributable_hkd"] = float("nan")
        ready_mask = signal_frame["ownership_attribution_ready"]
        signal_frame.loc[ready_mask, "sales_value_attributable_hkd"] = (
            signal_frame.loc[ready_mask, "sales_value_gross_hkd"]
            * signal_frame.loc[ready_mask, "ownership_pct"]
            / 100
        )
    signal_frame = signal_frame.reindex(columns=list(signal_frame.columns) + ["project_id"] if "project_id" not in signal_frame.columns else signal_frame.columns)
    audit_frame = pd.DataFrame(audit, columns=AUDIT_COLUMNS)
    lineage_metadata = {
        "lineage_type": "srpe_bounded_pdf_pilot",
        "project_count": len(selected),
        "price_selection": price_selection,
        "all_transaction_documents": all_transaction_documents,
        "transactions_only": transactions_only,
        "dataset_prefix": dataset_prefix,
        "since": since,
        "until": until,
        "attribution_policy": "only approved phase-specific bounded interval may populate attributable values; legacy snapshot percentages remain review-only",
    }
    stored = {
        dataset_name("srpe_pilot_transaction_events"): save_normalized_dataset(
            dataset_name("srpe_pilot_transaction_events"),
            transaction_frame,
            run_id=run_id,
            raw_snapshots=raw_snapshots,
            source_urls=sorted(set(source_urls)),
            lineage_metadata=lineage_metadata,
        ),
        dataset_name("srpe_pilot_price_list_units"): save_normalized_dataset(
            dataset_name("srpe_pilot_price_list_units"),
            price_frame,
            run_id=run_id,
            raw_snapshots=raw_snapshots,
            source_urls=sorted(set(source_urls)),
            lineage_metadata=lineage_metadata,
        ),
        dataset_name("srpe_pilot_developer_monthly_signals"): save_normalized_dataset(
            dataset_name("srpe_pilot_developer_monthly_signals"),
            signal_frame,
            run_id=run_id,
            raw_snapshots=raw_snapshots,
            source_urls=sorted(set(source_urls)),
            lineage_metadata=lineage_metadata,
        ),
        dataset_name("srpe_pilot_document_audit"): save_normalized_dataset(
            dataset_name("srpe_pilot_document_audit"),
            audit_frame,
            run_id=run_id,
            raw_snapshots=raw_snapshots,
            source_urls=sorted(set(source_urls)),
            lineage_metadata=lineage_metadata,
        ),
    }
    return {
        "run_id": run_id,
        "registry_path": str(registry_path),
        "project_count": len(selected),
        "projects": project_results,
        "records": {
            "transaction_events": len(transaction_frame),
            "price_list_units": len(price_frame),
            "developer_monthly_signals": len(signal_frame),
            "document_audit": len(audit_frame),
        },
        "normalized": stored,
        "raw_snapshots": raw_snapshots,
    }
