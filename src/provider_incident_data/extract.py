from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import pandas as pd
from bs4 import BeautifulSoup

from provider_incident_data.models import Snapshot


DATASET_IDS = (
    "provider_incidents",
    "provider_incident_updates",
    "provider_incident_components",
)

GOOGLE_AI_KEYWORDS = re.compile(r"\b(vertex|gemini|generative ai|ai platform)\b", re.IGNORECASE)
RESOLVED_STATUSES = {"resolved", "completed", "postmortem", "available", "operational"}


def _iso(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, str) and "," in value and re.search(r"\b(?:GMT|UTC)\b", value):
        try:
            value = parsedate_to_datetime(value.replace(" UTC", " GMT"))
        except (TypeError, ValueError, OverflowError):
            pass
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _duration_minutes(started_at: str | None, resolved_at: str | None) -> float | None:
    if not started_at or not resolved_at:
        return None
    start = pd.to_datetime(started_at, errors="coerce", utc=True)
    end = pd.to_datetime(resolved_at, errors="coerce", utc=True)
    if pd.isna(start) or pd.isna(end) or end < start:
        return None
    return round((end - start).total_seconds() / 60.0, 1)


def _normalized_status(raw_status: Any, *, resolved_at: str | None = None) -> str:
    value = str(raw_status or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    if resolved_at or value in RESOLVED_STATUSES or any(
        token in value for token in ("resolved", "restored", "fixed", "solved", "operational", "completed", "healthy_again")
    ):
        return "resolved"
    if "monitor" in value:
        return "monitoring"
    if "identif" in value:
        return "identified"
    if "investigat" in value:
        return "investigating"
    if value in {"scheduled", "in_progress", "verifying"}:
        return value
    return "active" if value not in {"unknown", "none"} else "unknown"


def _severity(raw: Any, title: str = "") -> tuple[str, int]:
    value = str(raw or "").strip().lower()
    mapping = {
        "none": 0,
        "available": 0,
        "operational": 0,
        "low": 1,
        "minor": 1,
        "degraded": 1,
        "medium": 2,
        "major": 2,
        "high": 3,
        "critical": 3,
    }
    if value in mapping:
        return value or "unknown", mapping[value]
    inferred = title.lower()
    if any(token in inferred for token in ("critical", "complete outage")):
        return value or "title_inferred", 3
    if any(token in inferred for token in ("unavailable", "outage", "disruption", "errors")):
        return value or "title_inferred", 2
    if any(token in inferred for token in ("degraded", "delays", "latency")):
        return value or "title_inferred", 1
    return value or "unknown", 0


def _incident_type(title: str) -> str:
    lowered = title.lower()
    return "maintenance" if "maintenance" in lowered or "scheduled" in lowered else "incident"


def _base(snapshot: Snapshot, run_id: str, scraped_at: str, dataset_id: str) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "source_url": snapshot.source_url,
        "source_run_id": run_id,
        "scraped_at": scraped_at,
        "provider_id": snapshot.provider_id,
        "provider_name": snapshot.provider_name,
        "source_system": snapshot.source_kind,
    }


def _statuspage(snapshot: Snapshot, run_id: str, scraped_at: str) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(snapshot.body)
    incidents = payload.get("incidents") if isinstance(payload, dict) else None
    if not isinstance(incidents, list):
        raise ValueError("Statuspage payload is missing an incidents list")
    output = {dataset_id: [] for dataset_id in DATASET_IDS}
    page_root = snapshot.source_url.split("/api/")[0].rstrip("/") + "/"
    for incident in incidents:
        if not isinstance(incident, dict) or not incident.get("id"):
            continue
        incident_id = str(incident["id"])
        title = str(incident.get("name") or "Untitled incident")
        resolved_at = _iso(incident.get("resolved_at"))
        raw_status = str(incident.get("status") or "unknown")
        normalized = _normalized_status(raw_status, resolved_at=resolved_at)
        raw_severity, severity_level = _severity(incident.get("impact"), title)
        updates = [row for row in incident.get("incident_updates", []) if isinstance(row, dict)]
        updates.sort(key=lambda row: str(row.get("created_at") or row.get("updated_at") or ""))
        # ``created_at`` is when the incident record was administratively filed
        # and can postdate the reader-facing ``display_at`` timeline for
        # retroactively backfilled incidents (a late report describing an
        # earlier outage). ``resolved_at`` tracks that display timeline, so
        # derive ``started_at`` the same way to avoid resolved-before-started
        # rows: take the earliest of the record creation time and every
        # update's display time.
        started_candidates = [
            candidate
            for candidate in (
                pd.to_datetime(incident.get("created_at"), errors="coerce", utc=True),
                *(
                    pd.to_datetime(
                        update.get("display_at") or update.get("created_at") or update.get("updated_at"),
                        errors="coerce",
                        utc=True,
                    )
                    for update in updates
                ),
            )
            if pd.notna(candidate)
        ]
        started_at = (
            min(started_candidates).isoformat().replace("+00:00", "Z") if started_candidates else None
        )
        latest_message = str(updates[-1].get("body") or "") if updates else ""
        components = [row for row in incident.get("components", []) if isinstance(row, dict)]
        component_names = sorted({str(row.get("name")) for row in components if row.get("name")})
        output["provider_incidents"].append(
            {
                **_base(snapshot, run_id, scraped_at, "provider_incidents"),
                "source_incident_id": incident_id,
                "incident_url": urljoin(page_root, f"incidents/{incident_id}"),
                "title": title,
                "incident_type": _incident_type(title),
                "raw_status": raw_status,
                "normalized_status": normalized,
                "raw_severity": raw_severity,
                "severity_level": severity_level,
                "started_at": started_at,
                "published_at": started_at,
                "resolved_at": resolved_at,
                "duration_minutes": _duration_minutes(started_at, resolved_at),
                "is_active": normalized != "resolved",
                "affected_components_json": json.dumps(component_names),
                "affected_regions_json": "[]",
                "latest_message": latest_message,
                "source_confidence": "high",
                "rule_version": "provider-incidents-v1",
            }
        )
        for update in updates:
            update_id = str(update.get("id") or _stable_id(incident_id, update))
            output["provider_incident_updates"].append(
                {
                    **_base(snapshot, run_id, scraped_at, "provider_incident_updates"),
                    "source_incident_id": incident_id,
                    "source_update_id": update_id,
                    "update_at": _iso(update.get("display_at") or update.get("created_at") or update.get("updated_at")),
                    "raw_status": str(update.get("status") or "unknown"),
                    "message": str(update.get("body") or ""),
                }
            )
        for component in components:
            name = str(component.get("name") or "").strip()
            if not name:
                continue
            output["provider_incident_components"].append(
                {
                    **_base(snapshot, run_id, scraped_at, "provider_incident_components"),
                    "source_incident_id": incident_id,
                    "component_id": str(component.get("id") or name.lower()),
                    "component_name": name,
                }
            )
    return output


def _google(snapshot: Snapshot, run_id: str, scraped_at: str) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(snapshot.body)
    if not isinstance(payload, list):
        raise ValueError("Google status payload is not a list")
    output = {dataset_id: [] for dataset_id in DATASET_IDS}
    for incident in payload:
        if not isinstance(incident, dict) or not incident.get("id"):
            continue
        products = [row for row in incident.get("affected_products", []) if isinstance(row, dict)]
        product_names = [str(row.get("title")) for row in products if row.get("title")]
        searchable = " ".join(product_names + [str(incident.get("external_desc") or "")])
        if not GOOGLE_AI_KEYWORDS.search(searchable):
            continue
        incident_id = str(incident["id"])
        description = str(incident.get("external_desc") or incident.get("service_name") or "Google AI incident")
        title = description.split("\n", 1)[0].strip()
        if len(title) > 180:
            title = title[:177].rstrip() + "…"
        started_at = _iso(incident.get("begin"))
        resolved_at = _iso(incident.get("end"))
        updates = [row for row in incident.get("updates", []) if isinstance(row, dict)]
        updates.sort(key=lambda row: str(row.get("when") or row.get("created") or ""))
        raw_status = str((updates[-1].get("status") if updates else None) or incident.get("status_impact") or "unknown")
        normalized = _normalized_status(raw_status, resolved_at=resolved_at)
        raw_severity, severity_level = _severity(incident.get("severity"), title)
        latest_message = str(updates[-1].get("text") or "") if updates else description
        incident_url = urljoin("https://status.cloud.google.com/", str(incident.get("uri") or "incidents"))
        regions = sorted(
            {
                str(region)
                for update in updates
                for region in (update.get("affected_locations") or [])
                if region
            }
        )
        output["provider_incidents"].append(
            {
                **_base(snapshot, run_id, scraped_at, "provider_incidents"),
                "source_incident_id": incident_id,
                "incident_url": incident_url,
                "title": title,
                "incident_type": _incident_type(title),
                "raw_status": raw_status,
                "normalized_status": normalized,
                "raw_severity": raw_severity,
                "severity_level": severity_level,
                "started_at": started_at,
                "published_at": _iso(incident.get("created")),
                "resolved_at": resolved_at,
                "duration_minutes": _duration_minutes(started_at, resolved_at),
                "is_active": normalized != "resolved",
                "affected_components_json": json.dumps(sorted(product_names)),
                "affected_regions_json": json.dumps(regions),
                "latest_message": latest_message,
                "source_confidence": "high",
                "rule_version": "provider-incidents-v1",
            }
        )
        for update in updates:
            update_id = _stable_id(incident_id, update)
            output["provider_incident_updates"].append(
                {
                    **_base(snapshot, run_id, scraped_at, "provider_incident_updates"),
                    "source_incident_id": incident_id,
                    "source_update_id": update_id,
                    "update_at": _iso(update.get("when") or update.get("created") or update.get("modified")),
                    "raw_status": str(update.get("status") or "unknown"),
                    "message": str(update.get("text") or ""),
                }
            )
        for product in products:
            name = str(product.get("title") or "").strip()
            if not name:
                continue
            output["provider_incident_components"].append(
                {
                    **_base(snapshot, run_id, scraped_at, "provider_incident_components"),
                    "source_incident_id": incident_id,
                    "component_id": str(product.get("id") or name.lower()),
                    "component_name": name,
                }
            )
    return output


def _stable_id(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _element_text(element: ET.Element, *names: str) -> str:
    for child in list(element):
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name in names and child.text:
            return child.text.strip()
    return ""


def _feed_entries(root: ET.Element) -> list[ET.Element]:
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name == "rss":
        return [row for row in root.iter() if row.tag.rsplit("}", 1)[-1] == "item"]
    return [row for row in root.iter() if row.tag.rsplit("}", 1)[-1] == "entry"]


def _feed_link(element: ET.Element) -> str:
    for child in list(element):
        if child.tag.rsplit("}", 1)[-1] != "link":
            continue
        if child.attrib.get("href"):
            return str(child.attrib["href"])
        if child.text:
            return child.text.strip()
    return ""


def _absolute_link(base_url: str, link: str) -> str:
    if not link:
        return base_url
    parsed = urlparse(link)
    if parsed.scheme:
        return link
    if link.startswith("//"):
        return "https:" + link
    base_host = urlparse(base_url).netloc
    if link.startswith(base_host + "/"):
        return "https://" + link
    if "." in link.split("/", 1)[0]:
        return "https://" + link
    return urljoin(base_url, link)


def _feed_timestamp(element: ET.Element) -> str | None:
    raw = _element_text(element, "updated", "published", "pubDate")
    if not raw:
        return None
    try:
        if "," in raw:
            return _iso(parsedate_to_datetime(raw))
    except (TypeError, ValueError, OverflowError):
        pass
    return _iso(raw)


def _feed_status(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    match = re.search(r"\bStatus\s*:\s*([A-Za-z_-]+)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    strong = soup.find("strong")
    return strong.get_text(" ", strip=True) if strong else "unknown"


def _feed_components(title: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    components = {row.get_text(" ", strip=True) for row in soup.find_all("li") if row.get_text(" ", strip=True)}
    for strong in soup.find_all("strong"):
        label = strong.get_text(" ", strip=True)
        if "affected components" not in label.lower():
            continue
        parent_text = strong.parent.get_text(" ", strip=True) if strong.parent else ""
        raw_components = re.sub(r"^.*?affected components\s*:\s*", "", parent_text, flags=re.IGNORECASE)
        components.update(
            value.strip()
            for value in re.split(r"[,，;]", raw_components)
            if value.strip()
        )
    bracket = re.match(r"^\[([^\]]+)\]", title)
    if bracket:
        components.add(bracket.group(1).strip())
    return sorted(components)


def _embedded_feed_updates(html: str, fallback_timestamp: str | None) -> list[dict[str, str | None]]:
    """Extract explicit update timestamps embedded in RSS/Atom HTML bodies.

    Some feeds publish one resolved item whose body contains the complete
    investigating-to-resolution timeline. The entry timestamp alone is not an
    incident start, so prefer those explicit update rows when available.
    """
    soup = BeautifulSoup(html, "html.parser")
    fallback = pd.to_datetime(fallback_timestamp, errors="coerce", utc=True)
    fallback_year = int(fallback.year) if not pd.isna(fallback) else None
    updates: list[dict[str, str | None]] = []
    for timestamp_node in soup.find_all(["small", "strong"]):
        raw_timestamp = timestamp_node.get_text(" ", strip=True)
        if not raw_timestamp:
            continue
        candidate = raw_timestamp
        if fallback_year is not None and not re.search(r"\b\d{4}\b", candidate):
            candidate = f"{candidate} {fallback_year}"
        timestamp = _iso(candidate)
        if timestamp is None:
            continue
        if timestamp_node.name == "small":
            container = timestamp_node.parent
            status_node = container.find("strong") if container else None
        else:
            container = timestamp_node.find_parent("div") or timestamp_node.parent
            status_node = container.find("h3") if container else None
        status = status_node.get_text(" ", strip=True) if status_node else "unknown"
        message = container.get_text(" ", strip=True) if container else ""
        message = message.replace(raw_timestamp, "", 1).strip(" -")
        updates.append({"timestamp": timestamp, "raw_status": status, "message": message})
    updates.sort(key=lambda row: str(row.get("timestamp") or ""))
    return updates


def _feed(snapshot: Snapshot, run_id: str, scraped_at: str) -> dict[str, list[dict[str, Any]]]:
    try:
        root = ET.fromstring(snapshot.body)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed XML feed: {exc}") from exc
    entries = _feed_entries(root)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        title = unescape(_element_text(entry, "title") or "Untitled incident")
        link = _absolute_link(snapshot.source_url, _feed_link(entry))
        incident_id = _element_text(entry, "id", "guid") or link or _stable_id(snapshot.provider_id, title)
        html = _element_text(entry, "summary", "content", "description")
        timestamp = _feed_timestamp(entry)
        raw_status = _feed_status(html)
        message = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        components = _feed_components(title, html)
        embedded = _embedded_feed_updates(html, timestamp)
        if embedded:
            for update in embedded:
                grouped[incident_id].append(
                    {
                        "title": title,
                        "link": link,
                        "timestamp": update["timestamp"],
                        "published_at": timestamp,
                        "raw_status": update["raw_status"],
                        "entry_final_status": raw_status,
                        "message": update["message"],
                        "components": components,
                    }
                )
        else:
            grouped[incident_id].append(
                {
                    "title": title,
                    "link": link,
                    "timestamp": timestamp,
                    "published_at": timestamp,
                    "raw_status": raw_status,
                    "entry_final_status": raw_status,
                    "message": message,
                    "components": components,
                }
            )

    output = {dataset_id: [] for dataset_id in DATASET_IDS}
    for incident_id, incident_updates in grouped.items():
        incident_updates.sort(key=lambda row: str(row.get("timestamp") or ""))
        latest = incident_updates[-1]
        first = incident_updates[0]
        first_status = _normalized_status(first["raw_status"])
        started_at = (
            next((row["timestamp"] for row in incident_updates if row.get("timestamp")), None)
            if first_status != "resolved"
            else None
        )
        latest_at = next((row["timestamp"] for row in reversed(incident_updates) if row.get("timestamp")), None)
        normalized = _normalized_status(latest["raw_status"])
        final_status = str(latest.get("entry_final_status") or latest["raw_status"])
        if normalized != "resolved" and _normalized_status(final_status) == "resolved":
            normalized = "resolved"
            latest = {**latest, "raw_status": final_status}
        resolved_at = latest_at if normalized == "resolved" else None
        raw_severity, severity_level = _severity(latest["raw_status"], str(latest["title"]))
        components = sorted({component for row in incident_updates for component in row["components"]})
        # A single feed item usually reports only its publish/update timestamp,
        # not a trustworthy incident start. Avoid claiming a zero-minute outage.
        duration = _duration_minutes(started_at, resolved_at)
        published_at = next(
            (row.get("published_at") for row in incident_updates if row.get("published_at")),
            latest_at,
        )
        output["provider_incidents"].append(
            {
                **_base(snapshot, run_id, scraped_at, "provider_incidents"),
                "source_incident_id": str(incident_id),
                "incident_url": latest["link"],
                "title": latest["title"],
                "incident_type": _incident_type(str(latest["title"])),
                "raw_status": latest["raw_status"],
                "normalized_status": normalized,
                "raw_severity": raw_severity,
                "severity_level": severity_level,
                "started_at": started_at,
                "published_at": published_at,
                "resolved_at": resolved_at,
                "duration_minutes": duration,
                "is_active": normalized != "resolved",
                "affected_components_json": json.dumps(components),
                "affected_regions_json": "[]",
                "latest_message": latest["message"],
                "source_confidence": "medium",
                "rule_version": "provider-incidents-v1",
            }
        )
        for update in incident_updates:
            update_id = _stable_id(incident_id, update["timestamp"], update["raw_status"], update["message"])
            output["provider_incident_updates"].append(
                {
                    **_base(snapshot, run_id, scraped_at, "provider_incident_updates"),
                    "source_incident_id": str(incident_id),
                    "source_update_id": update_id,
                    "update_at": update["timestamp"],
                    "raw_status": update["raw_status"],
                    "message": update["message"],
                }
            )
        for component in components:
            output["provider_incident_components"].append(
                {
                    **_base(snapshot, run_id, scraped_at, "provider_incident_components"),
                    "source_incident_id": str(incident_id),
                    "component_id": _stable_id(snapshot.provider_id, component),
                    "component_name": component,
                }
            )
    return output


def extract_snapshot(snapshot: Snapshot, *, run_id: str, scraped_at: str) -> dict[str, list[dict[str, Any]]]:
    if snapshot.parser == "statuspage":
        return _statuspage(snapshot, run_id, scraped_at)
    if snapshot.parser == "google":
        return _google(snapshot, run_id, scraped_at)
    if snapshot.parser == "feed":
        return _feed(snapshot, run_id, scraped_at)
    raise ValueError(f"Unknown provider incident parser: {snapshot.parser}")
