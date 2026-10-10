#!/usr/bin/env python3
"""Export bounded, public research feeds from committed dashboard inputs.

This command is offline. It does not import collectors, load credentials, read
private research marts, calculate investment opinions, or modify its inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jsonschema
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "config/research_agent_feed/sources.v1.json"
SCHEMA = "config/research_agent_feed/investment_feed.v1.schema.json"
DOMAINS = ("asia_markets", "alternative_signals")


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def period_end(value: Any) -> date | None:
    text = str(value or "")
    if re.fullmatch(r"\d{4}-Q[1-4]", text):
        year, quarter = int(text[:4]), int(text[-1])
        month = quarter * 3
        return date(year, month, monthrange(year, month)[1])
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, month = map(int, text.split("-"))
        return date(year, month, monthrange(year, month)[1])
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


class Inputs:
    """Track exact files read; published provenance is bound to a clean commit."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        self.tracked = set(subprocess.check_output(
            ["git", "ls-files"], cwd=root, text=True
        ).splitlines())
        self.paths: dict[str, str] = {}

    def path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Input path escapes repository")
        if relative not in self.tracked:
            raise FileNotFoundError(f"Input is not committed: {relative}")
        if subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative], cwd=self.root
        ).returncode:
            raise ValueError(f"Input differs from source_commit: {relative}")
        self.paths[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def json(self, relative: str) -> dict:
        value = json.loads(self.path(relative).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    def rows(self, relative: str, columns: list[str]) -> list[dict]:
        path = self.path(relative)
        available = set(pq.ParquetFile(path).schema_arrow.names)
        if missing := set(columns) - available:
            raise ValueError(f"Required columns missing: {sorted(missing)}")
        return pq.read_table(path, columns=columns).to_pylist()

    def reference(self, relative: str, url: str) -> dict:
        return {"path": relative, "sha256": self.paths.get(relative), "url": url,
                "artifact_url": f"https://github.com/Henrywzh/alternative-data/blob/{self.commit}/{relative}"}


def freshness(observation: str | None, retrieved: str | None, cadence: str,
              now: datetime, check: dict | None = None) -> dict:
    """Carry native checks; guard evidence age independently of source cadence.

    An unmatched check never certifies another KPI. Guardrails below are broad
    maximum ages, not replacements for an upstream release calendar.
    """
    observed = period_end(observation)
    result = {"status": "unknown", "policy": "export_guardrail.v1",
              "source_check": check, "evidence_as_of": retrieved}
    if observed is None:
        return result
    if observed > now.date():
        result["policy"] = "future_observation_rejected"
        return result
    try:
        captured = datetime.fromisoformat(str(retrieved).replace("Z", "+00:00"))
        if captured.tzinfo is None:
            return result
        age = (now - captured).total_seconds() / 86400
    except (TypeError, ValueError):
        return result
    if age < -1 / 24:
        result["policy"] = "future_capture_rejected"
        return result
    limits = {"daily": 3, "monthly": 100, "quarterly": 180,
              "rolling_three_month": 100, "semiannual": 280, "annual": 460}
    max_capture_age = 3 if cadence == "daily" else 14
    result["max_observation_age_days"] = limits[cadence]
    result["max_capture_age_days"] = max_capture_age
    result["status"] = "current"
    if age > max_capture_age or (now.date() - observed).days > limits[cadence]:
        result["status"] = "stale"
    if check:
        result["policy"] = "upstream_check_plus_evidence_guardrail.v1"
        if check.get("status") == "unknown" and result["status"] == "current":
            result["status"] = "unknown"
        elif check.get("status") not in ("healthy", "unknown"):
            result["status"] = "stale"
        # Some checks audit a historical dataset rather than this exact KPI.
        # Carry them as context, but do not certify a mismatched observation.
        checked = str(check.get("latest_observation") or "")
        metric_period = str(observation or "")
        matched = (checked == metric_period or period_end(checked) == observed or
                   (len(checked) == 7 and metric_period.startswith(checked)))
        result["check_matches_observation"] = matched
        if not matched and result["status"] == "current":
            result["status"] = "unknown"
    return result


def make_record(*, identity: str, label: str, row: dict, fields: dict[str, str],
                observation: str | None, retrieved: str | None, cadence: str,
                provenance: dict, description: str, now: datetime,
                source_status: str | None = None, check: dict | None = None,
                methodology: dict | None = None, published: str | None = None) -> dict:
    metrics = {key: {"value": number(row.get(key)), "unit": unit}
               for key, unit in fields.items()}
    fresh = freshness(observation, retrieved, cadence, now, check)
    issues = []
    if not any(item["value"] is not None for item in metrics.values()):
        issues.append("all_values_missing")
    if any(item["value"] is None for item in metrics.values()):
        issues.append("partial_metric_coverage")
    if row.get("is_provisional"):
        issues.append("source_provisional")
    good = source_status is None or source_status.lower() in ("healthy", "ok", "ready")
    if not good:
        issues.append("upstream_source_degraded")
    status = fresh["status"]
    if "all_values_missing" in issues:
        status = "unavailable"
    elif not good and status == "current":
        status = "degraded"
    return {"id": identity, "label": label, "description": description,
            "observation_as_of": observation, "published_at_utc": published,
            "retrieved_at_utc": retrieved, "cadence": cadence,
            "metrics": metrics, "methodology": methodology or {},
            "provenance": provenance,
            "quality": {"status": status, "source_status": source_status,
                        "freshness": fresh, "issues": issues},
            "previous_observation": None}


def asia_sections(inputs: Inputs, config: dict, now: datetime) -> list[dict]:
    audit_path = "apps/asia-markets-dashboard/.generated/asia-markets-freshness.json"
    try:
        report = inputs.json(audit_path)
    except (OSError, ValueError):
        report = {}
    checks = {c["check_id"]: c for c in report.get("checks", [])}
    sections = []
    for spec in config["asia_sections"]:
        section = {"id": spec["id"], "label": spec["label"], "records": [],
                   "coverage": {"selection": "explicit_public_dataset_and_field_allowlist",
                                "expected_records": len(spec["records"]), "input_rows": 0},
                   "issues": []}
        try:
            artifact = inputs.json(spec["path"])
            ds = artifact["snapshot"]["datasets"]
            generated = artifact["snapshot"].get("generatedAt")
            for item in spec["records"]:
                rows = ds.get(item["dataset"], [])
                if not isinstance(rows, list):
                    raise ValueError("Dataset shape changed")
                section["coverage"]["input_rows"] += len(rows)
                dated = [r for r in rows if isinstance(r, dict) and period_end(r.get(item["date_field"]))]
                row = max(dated, key=lambda r: str(r[item["date_field"]])) if dated else {}
                source_health = next((h for h in ds.get("source_health", [])
                                      if h.get("dataset") == item["health_dataset"]), {})
                upstream = source_health.get("status")
                # Snapshot.ready is a build state; it never substitutes for source health.
                check = checks.get(item["freshness_check"])
                if check:
                    check = {k: check.get(k) for k in (
                        "check_id", "status", "latest_observation", "expected_latest_period")}
                    check["audited_at_utc"] = report.get("auditedAt")
                    if report.get("asOf") != now.date().isoformat():
                        check["status"] = "unknown"
                record = make_record(
                    identity=f"{spec['id']}/{item['id']}", label=item["label"], row=row,
                    fields=item["fields"], observation=row.get(item["date_field"]),
                    retrieved=generated, cadence=item["cadence"], now=now,
                    provenance=inputs.reference(spec["path"], item["source_url"]),
                    description=item["description"], source_status=upstream, check=check,
                    methodology={"dataset": item["dataset"], "source_id": item["source_id"],
                                 "source_period": row.get("period"),
                                 "source_provisional": bool(row.get("is_provisional", False))})
                if any(unit == "index_points" for unit in item["fields"].values()):
                    record["methodology"]["index_baseline"] = "not_recorded_in_artifact; consult original source"
                section["records"].append(record)
        except (OSError, ValueError, KeyError, TypeError):
            section["issues"].append("input_missing_invalid_or_uncommitted")
        sections.append(section)
    return sections


def previous_rows(rows: list[dict], date_field: str, keys: list[str]) -> list[tuple[dict, dict | None]]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        if not period_end(row.get(date_field)):
            continue
        if any(row.get(key) in (None, "") for key in keys):
            raise ValueError("Missing observation identity")
        identity = tuple(row.get(key) for key in keys)
        groups.setdefault(identity, []).append(row)
    result = []
    for identity in sorted(groups, key=str):
        by_date: dict[str, dict] = {}
        for row in sorted(groups[identity], key=lambda r: str(r.get("scraped_at") or "")):
            by_date[str(row[date_field])] = row
        dates = sorted(by_date)
        result.append((by_date[dates[-1]], by_date[dates[-2]] if len(dates) > 1 else None))
    return result


def attach_prior(record: dict, prior: dict | None, date_field: str) -> None:
    if prior:
        record["previous_observation"] = {
            "observation_as_of": prior[date_field],
            "metrics": {k: {"value": number(prior.get(k)), "unit": v["unit"]}
                        for k, v in record["metrics"].items()}}


def alt_sections(inputs: Inputs, now: datetime) -> list[dict]:
    """Explicit adapters; source rows are projected before any export."""
    sections = []
    specs = [
        ("openrouter_economics", "OpenRouter usage economics",
         "data/normalized/marts/openrouter_usage_economics_daily.parquet", "usage_date",
         ["metric_id", "cohort_id"], {"value": "metric_specific"},
         ["rolling_window_days", "pricing_join_status", "included_tokens", "excluded_unpriced_tokens",
          "expected_family_count", "priced_family_count", "observed_model_count", "methodology_version"],
         "https://openrouter.ai/rankings", "daily"),
        ("developer_adoption", "PyPI core SDK downloads (without mirrors)",
         "data/normalized/provider_adoption/pypi_downloads_daily.parquet", "download_date",
         ["provider", "package_name"], {"downloads": "downloads"},
         ["with_mirrors", "package_category"], "https://pypistats.org/", "daily"),
        ("taiwan_semiconductor", "Taiwan semiconductor / AI supply-chain monthly revenue",
         "data/normalized/taiwan_semiconductor_revenue/tw_monthly_revenue.parquet", "revenue_month",
         ["company_code"], {"monthly_revenue_ntd": "TWD_thousand", "yoy_pct": "percent",
                            "mom_pct": "percent", "ytd_revenue_ntd": "TWD_thousand"},
         ["company_name", "industry", "mom_pct_is_derived", "parser_version"],
         "https://mops.twse.com.tw/mops/api/t05st10_ifrs", "monthly"),
    ]
    allowed_metrics = {
        "realized_market_average": "USD_per_million_tokens",
        "realized_sota_price": "USD_per_million_tokens",
        "sota_median_list_price": "USD_per_million_tokens",
        "total_tokens_per_request": "tokens_per_request",
        "prompt_tokens_per_request": "tokens_per_request",
        "completion_tokens_per_request": "tokens_per_request",
    }
    for identity, label, path, date_field, keys, fields, extra, url, cadence in specs:
        section = {"id": identity, "label": label, "records": [],
                   "coverage": {"selection": "explicit_numeric_projection", "input_rows": 0}, "issues": []}
        try:
            columns = list(dict.fromkeys([date_field, *keys, *fields, *extra, "scraped_at", "source_run_id"]))
            rows = inputs.rows(path, columns)
            section["coverage"]["input_rows"] = len(rows)
            if identity == "openrouter_economics":
                rows = [r for r in rows if r["metric_id"] in allowed_metrics]
            elif identity == "developer_adoption":
                rows = [r for r in rows if r["with_mirrors"] is False and r["package_category"] == "core_sdk"]
            for row, prior in previous_rows(rows, date_field, keys):
                group = "/".join(str(row[k]) for k in keys)
                record_fields = dict(fields)
                if identity == "openrouter_economics":
                    record_fields["value"] = allowed_metrics[row["metric_id"]]
                description = {
                    "openrouter_economics": "Existing derived mart; pricing-based metrics are channel list-price proxies, not audited revenue or company ARR. Respect the recorded rolling window and pricing coverage.",
                    "developer_adoption": "Package downloads without mirrors; installs, automation and repeat downloads are included. Not unique developers, active users or revenue.",
                    "taiwan_semiconductor": "Issuer-reported monthly revenue. Source fields named *_ntd contain thousands of TWD; percentage changes use a 0–100 scale. Issuers can publish on different dates.",
                }[identity]
                meta = {k: row.get(k) for k in extra}
                # Only reviewed scalar metadata is ever copied.
                record = make_record(
                    identity=f"{identity}/{group}", label=str(row.get("company_name") or group),
                    row=row, fields=record_fields, observation=row[date_field], retrieved=row.get("scraped_at"),
                    cadence=cadence, now=now, provenance=inputs.reference(path, url),
                    description=description, methodology=meta)
                if identity == "developer_adoption" and row.get("downloads") == 0:
                    record["quality"]["status"] = "unknown"
                    record["quality"]["issues"].append("zero_download_count_requires_upstream_confirmation")
                if identity == "openrouter_economics":
                    coverage = str(row.get("pricing_join_status") or "")
                    if "partial" in coverage or (number(row.get("excluded_unpriced_tokens")) or 0) > 0:
                        record["quality"]["issues"].append("partial_pricing_coverage")
                        if record["quality"]["status"] == "current":
                            record["quality"]["status"] = "degraded"
                attach_prior(record, prior, date_field)
                section["records"].append(record)
        except (OSError, ValueError, KeyError, TypeError):
            section["issues"].append("input_missing_invalid_or_uncommitted")
        if not section["records"]:
            section["issues"].append("no_publishable_observations")
        sections.append(section)
    return sections


def delta(records: dict[str, dict], old: dict[str, dict]) -> list[dict]:
    changes = []
    for identity in sorted(set(records) | set(old)):
        current, previous = records.get(identity), old.get(identity)
        if current is None:
            kind = "unavailable"
        elif previous is None:
            kind = "initial_observation"
        elif current["observation_as_of"] != previous["observation_as_of"]:
            a, b = period_end(current["observation_as_of"]), period_end(previous["observation_as_of"])
            kind = "new_observation" if a and b and a > b else "observation_regressed"
            if kind == "observation_regressed":
                current["quality"]["status"] = "unknown"
                current["quality"]["issues"].append("observation_regressed_vs_previous_feed")
        elif digest(current["metrics"]) != digest(previous["metrics"]):
            kind = "revision"
        elif current["quality"]["status"] != previous["quality"]["status"]:
            kind = "quality_change"
        elif digest(current["methodology"]) != digest(previous["methodology"]):
            kind = "methodology_change"
        else:
            continue
        changes.append({"record_id": identity, "type": kind,
                        "previous_observation_as_of": previous["observation_as_of"] if previous else None,
                        "observation_as_of": current["observation_as_of"] if current else None})
    return changes


def candidates(records: dict[str, dict], rules: list[dict], previous: dict,
               generated: str) -> list[dict]:
    old = {(c["rule_id"], c["record_id"]): c for c in previous.get("research_candidates", [])}
    result = []
    for rule in rules:
        ids = {k for k in records if k == rule.get("record_id") or
               (rule.get("section_id") and k.startswith(rule["section_id"] + "/"))}
        ids |= {record_id for rule_id, record_id in old if rule_id == rule["rule_id"]}
        for identity in sorted(ids):
            prior = old.get((rule["rule_id"], identity))
            record = records.get(identity)
            metric = record["metrics"].get(rule["field"]) if record else None
            eligible = bool(record and record["quality"]["status"] == "current" and metric and
                            metric["unit"] == rule["unit"] and metric["value"] is not None)
            if not eligible:
                if prior and prior["state"] != "resolved":
                    result.append({**prior, "state": "unknown", "last_evaluated_at_utc": generated})
                continue
            value = metric["value"]
            triggered = (abs(value) if rule["operator"] == "abs_ge" else value) >= rule["threshold"]
            if not triggered and (not prior or prior["state"] == "resolved"):
                continue
            continuing = bool(prior and prior["state"] != "resolved")
            first_seen = prior["first_seen_at_utc"] if continuing else generated
            event_id = (prior["candidate_id"] if continuing else
                        digest([rule["rule_id"], identity, record["observation_as_of"], first_seen])[:24])
            result.append({"candidate_id": event_id, "rule_id": rule["rule_id"],
                           "record_id": identity, "state": "continuing" if triggered and continuing else
                           ("new" if triggered else "resolved"),
                           "first_seen_at_utc": first_seen, "last_confirmed_at_utc": generated,
                           "last_evaluated_at_utc": generated, "rationale": rule["rationale"],
                           "evidence": {"field": rule["field"], "value": value, "unit": metric["unit"],
                                        "operator": rule["operator"], "threshold": rule["threshold"],
                                        "observation_as_of": record["observation_as_of"]}})
    return result


def records_by_id(feed: dict) -> dict[str, dict]:
    return {r["id"]: r for s in feed.get("sections", []) for r in s["records"]}


def markdown(feed: dict) -> str:
    lines = [f"# {feed['domain']} research feed", "",
             f"Generated: {feed['generated_at_utc']} · Status: **{feed['pipeline_status']}**", "",
             f"Source commit: `{feed['source_commit']}`", "",
             "Observation dates differ by record. Generated time is not a market-data timestamp.", "",
             "| Section | Record | Observation | Quality | Values |", "|---|---|---|---|---|"]
    for s in feed["sections"]:
        if not s["records"]:
            lines.append(f"| {s['label']} | unavailable | — | unavailable | — |")
        for r in s["records"]:
            values = "; ".join(f"{k}: {v['value']} {v['unit']}" for k, v in r["metrics"].items())
            safe = lambda text: str(text).replace("|", "\\|").replace("\n", " ")
            lines.append("| " + " | ".join(safe(x) for x in (
                s["label"], r["label"], r["observation_as_of"], r["quality"]["status"], values)) + " |")
    lines += ["", "## Rule candidates", ""]
    for c in feed["research_candidates"]:
        lines.append(f"- **{c['state']}** `{c['candidate_id']}`: {c['record_id']} / {c['rule_id']}")
    if not feed["research_candidates"]:
        lines.append("No confirmed rule candidates. Check coverage and quality before interpreting this as no change.")
    lines += ["", "## Changes", ""]
    lines.extend(f"- {c['type']}: {c['record_id']}" for c in feed["changes"])
    lines += ["", "## Excluded coverage", ""]
    lines.extend(f"- {x['id']}: {x['reason']}" for x in feed["excluded_coverage"])
    lines += ["", "Use the JSON for provenance, definitions, methodology, previous observations and quality evidence.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output" / "research-agent-feed")
    parser.add_argument("--previous-dir", type=Path)
    args = parser.parse_args()
    inputs = Inputs(args.base_dir)
    # Code/config changes must be committed before their provenance can be published.
    config = inputs.json(CONFIG)
    schema = inputs.json(SCHEMA)
    inputs.path("scripts/build_research_agent_feeds.py")
    now = datetime.now(timezone.utc)
    generated = utc(now)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    built = {}
    common_inputs = dict(inputs.paths)
    for domain in DOMAINS:
        inputs.paths = dict(common_inputs)
        previous = {}
        if args.previous_dir and (path := args.previous_dir / f"{domain}.json").exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.validate(previous, schema)
            if previous["domain"] != domain or previous["generated_at_utc"] > generated:
                raise ValueError("Previous feed identity/time mismatch")
        sections = (asia_sections(inputs, config, now) if domain == "asia_markets" else
                    alt_sections(inputs, now))
        feed = {"schema_version": "investment_feed.v1", "domain": domain,
                "as_of": None, "generated_at_utc": generated, "source_commit": inputs.commit,
                "pipeline_status": "degraded", "publication": config["publication"],
                "contract_version": config["version"], "contract_sha256": digest(common_inputs),
                "baseline_generated_at_utc": previous.get("generated_at_utc"),
                "baseline_source_commit": previous.get("source_commit"),
                "sections": sections, "research_candidates": [], "changes": [],
                "excluded_coverage": config["exclusions"][domain], "inputs": []}
        current = records_by_id(feed)
        old = records_by_id(previous)
        same_contract = not previous or previous["contract_sha256"] == feed["contract_sha256"]
        feed["changes"] = delta(current, old if same_contract else {})
        if not same_contract:
            feed["changes"].insert(0, {"record_id": "contract", "type": "contract_changed",
                                      "previous_observation_as_of": None, "observation_as_of": None})
        # Snapshot KPIs compare only to a prior feed of the same contract.
        # Keep unavailable prior observations out of numeric comparisons.
        for identity, r in current.items():
            if not r["previous_observation"] and same_contract and identity in old:
                p = old[identity]
                if (p["quality"]["status"] == "current" and p["observation_as_of"] and
                        period_end(p["observation_as_of"]) and p["metrics"] != r["metrics"]):
                    r["previous_observation"] = {"observation_as_of": p["observation_as_of"], "metrics": p["metrics"]}
        feed["research_candidates"] = candidates(current, config["rules"], previous if same_contract else {}, generated)
        states = [r["quality"]["status"] for r in current.values()]
        feed["pipeline_status"] = ("unavailable" if not states or all(s == "unavailable" for s in states) else
                                   "complete" if all(s == "current" for s in states) and not any(s["issues"] for s in sections) else
                                   "degraded")
        dates = [r["observation_as_of"] for r in current.values() if period_end(r["observation_as_of"])]
        feed["as_of"] = max(dates, key=lambda x: period_end(x)) if dates else None
        feed["inputs"] = [{"path": p, "sha256": sha} for p, sha in sorted(inputs.paths.items())]
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(feed)
        body = json.dumps(feed, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        if len(body.encode()) > config["max_bytes_per_feed"]:
            raise ValueError(f"{domain} exceeds feed size budget; refine the allowlist rather than truncate evidence")
        built[domain] = (feed, body)
    # Only replace outputs after both feeds pass validation and size limits.
    for domain, (feed, body) in built.items():
        (args.output_dir / f"{domain}.json").write_text(body, encoding="utf-8")
        (args.output_dir / f"{domain}.md").write_text(markdown(feed), encoding="utf-8")
        print(json.dumps({"domain": domain, "status": feed["pipeline_status"],
                          "records": len(records_by_id(feed)), "bytes": len(body.encode()),
                          "candidates": len(feed["research_candidates"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
