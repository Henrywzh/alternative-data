from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any

import pandas as pd

from ai_hiring_data.classify import classify_role, classify_seniority
from ai_hiring_data.models import Snapshot, SourceSpec


def _iso(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    parsed = pd.to_datetime(value, format="mixed", errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def extract_indeed(snapshot: Snapshot, *, run_id: str, scraped_at: str) -> list[dict[str, Any]]:
    if snapshot.body is None:
        return []
    frame = pd.read_csv(io.StringIO(snapshot.body))
    required = {"date", "jobcountry", "AI_share_postings"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Indeed AI tracker missing columns: {sorted(required - set(frame.columns))}")
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        share = pd.to_numeric(record.get("AI_share_postings"), errors="coerce")
        rows.append(
            {
                "dataset_id": "indeed_ai_posting_share_daily",
                "source_url": snapshot.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
                "date": str(record.get("date") or ""),
                "jobcountry": str(record.get("jobcountry") or "").upper(),
                "ai_share_pct": float(share) if not pd.isna(share) else None,
                "source_frequency": "daily observations",
                "source_refresh_cadence": "monthly",
                "license": "CC-BY-4.0",
            }
        )
    return rows


COUNTRY_ALIASES = {
    "USA": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "CANADA": "CA",
    "UNITED KINGDOM": "GB",
    "UK": "GB",
    "FRANCE": "FR",
    "GERMANY": "DE",
    "IRELAND": "IE",
    "NETHERLANDS": "NL",
    "AUSTRALIA": "AU",
    "SINGAPORE": "SG",
    "INDIA": "IN",
    "JAPAN": "JP",
}


def _country_code(raw: str, structured: Any = None) -> str | None:
    if structured:
        value = str(structured).strip().upper()
        if len(value) == 2:
            return value
        if value in COUNTRY_ALIASES:
            return COUNTRY_ALIASES[value]
    text = str(raw or "").upper()
    for label, code in COUNTRY_ALIASES.items():
        if label in text:
            return code
    for token, code in (("NEW YORK", "US"), ("SAN FRANCISCO", "US"), ("SEATTLE", "US"), ("WASHINGTON, DC", "US"), ("LONDON", "GB"), ("PARIS", "FR"), ("BERLIN", "DE"), ("TORONTO", "CA"), ("VANCOUVER", "CA")):
        if token in text:
            return code
    return None


def _content_hash(row: dict[str, Any]) -> str:
    substantive = {
        key: row.get(key)
        for key in (
            "source_job_id", "source_requisition_id", "title", "department", "team", "location_raw",
            "country_code", "workplace_type", "employment_type", "published_at", "source_updated_at",
            "job_url", "apply_url", "role_family", "seniority", "is_ai_role",
        )
    }
    payload = json.dumps(substantive, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ashby_jobs(payload: dict[str, Any], spec: SourceSpec) -> list[dict[str, Any]]:
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Ashby payload is missing jobs list")
    rows: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("isListed") is False:
            continue
        source_job_id = str(job.get("id") or "").strip()
        title = str(job.get("title") or "").strip()
        if not source_job_id or not title:
            continue
        address = job.get("address") if isinstance(job.get("address"), dict) else {}
        postal = address.get("postalAddress") if isinstance(address.get("postalAddress"), dict) else {}
        location = str(job.get("location") or "").strip()
        department = str(job.get("department") or "").strip() or None
        team = str(job.get("team") or "").strip() or None
        role_family, is_ai_role, confidence, classifier_version = classify_role(title, department, team)
        row = {
            "company_id": spec.company_id,
            "company_name": spec.company_name,
            "company_segment": spec.company_segment,
            "source_platform": spec.source_platform,
            "board_token": spec.board_token,
            "source_job_id": source_job_id,
            "source_requisition_id": source_job_id,
            "title": title,
            "department": department,
            "team": team,
            "location_raw": location or None,
            "country_code": _country_code(location, postal.get("addressCountry")),
            "workplace_type": str(job.get("workplaceType") or ("Remote" if job.get("isRemote") else "")).strip() or None,
            "employment_type": str(job.get("employmentType") or "").strip() or None,
            "published_at": _iso(job.get("publishedAt")),
            "source_updated_at": None,
            "job_url": str(job.get("jobUrl") or "").strip(),
            "apply_url": str(job.get("applyUrl") or "").strip() or None,
            "role_family": role_family,
            "seniority": classify_seniority(title),
            "is_ai_role": is_ai_role,
            "ai_role_confidence": confidence,
            "classifier_version": classifier_version,
        }
        row["content_hash"] = _content_hash(row)
        rows.append(row)
    return rows


def _greenhouse_jobs(payload: dict[str, Any], spec: SourceSpec) -> list[dict[str, Any]]:
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Greenhouse payload is missing jobs list")
    rows: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        source_job_id = str(job.get("id") or "").strip()
        title = str(job.get("title") or "").strip()
        if not source_job_id or not title:
            continue
        location_obj = job.get("location") if isinstance(job.get("location"), dict) else {}
        location = str(location_obj.get("name") or "").strip()
        workplace = "Remote" if re.search(r"\bremote\b", location, re.I) else None
        role_family, is_ai_role, confidence, classifier_version = classify_role(title)
        row = {
            "company_id": spec.company_id,
            "company_name": spec.company_name,
            "company_segment": spec.company_segment,
            "source_platform": spec.source_platform,
            "board_token": spec.board_token,
            "source_job_id": source_job_id,
            "source_requisition_id": str(job.get("internal_job_id") or job.get("requisition_id") or source_job_id),
            "title": title,
            "department": None,
            "team": None,
            "location_raw": location or None,
            "country_code": _country_code(location),
            "workplace_type": workplace,
            "employment_type": None,
            "published_at": _iso(job.get("first_published")),
            "source_updated_at": _iso(job.get("updated_at")),
            "job_url": str(job.get("absolute_url") or "").strip(),
            "apply_url": str(job.get("absolute_url") or "").strip() or None,
            "role_family": role_family,
            "seniority": classify_seniority(title),
            "is_ai_role": is_ai_role,
            "ai_role_confidence": confidence,
            "classifier_version": classifier_version,
        }
        row["content_hash"] = _content_hash(row)
        rows.append(row)
    return rows


def extract_board(snapshot: Snapshot, spec: SourceSpec) -> list[dict[str, Any]]:
    if snapshot.body is None:
        return []
    payload = json.loads(snapshot.body)
    if not isinstance(payload, dict):
        raise ValueError(f"{spec.source_platform} board payload is not an object")
    if spec.source_platform == "ashby":
        return _ashby_jobs(payload, spec)
    if spec.source_platform == "greenhouse":
        return _greenhouse_jobs(payload, spec)
    raise ValueError(f"Unsupported hiring source platform: {spec.source_platform}")
