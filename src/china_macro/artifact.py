"""Local-only bilingual read contract; publication lag is not fetch failure."""
from datetime import datetime, timezone
import json

import pandas as pd

from .config import ARTIFACT_DIR, DATA_DIR, SERIES, GROUPS
from .calendar import family_for
from .normalize import missing_months
from .storage import atomic_json, load_current


def coverage(frame, manifest, now=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    rows = []
    for metric, spec in SERIES.items():
        history = frame[frame["metric"].eq(metric)]
        latest = history.iloc[-1] if not history.empty else None
        date = latest["date"] if latest is not None else None
        age = (now.date() - pd.Timestamp(date).date()).days if date else None
        captured = latest["retrieved_at"] if latest is not None else None
        capture_age = (now - pd.Timestamp(captured)).total_seconds() / 86400 if captured else None
        limit = 12 if spec["frequency"] == "D" else 150 if spec["frequency"] == "Q" else 75
        status = "Unavailable" if date is None else "Stale" if age > limit or capture_age > 7 else "Available"
        expected = [row["reference_date"] for row in manifest.get("publication_calendar", [])
                    if row["family"] == family_for(metric) and row["release_date"] <= now.strftime("%Y-%m-%d")
                    and (spec["frequency"] != "Q" or pd.Timestamp(row["reference_date"]).month in [3, 6, 9, 12])]
        expected_date = max(expected) if expected else None
        if date and expected_date and date < expected_date:
            status = "Stale"
        if date and metric in {"m1_legacy_yoy", "infrastructure_investment_yoy"}:
            status = "Historical"
        # A failed component must remain visible even if retained history exists.
        if spec["owner"] != "derived" and metric not in manifest.get("refreshed_metrics", []) and status == "Available":
            status = "Retained"
        rows.append(dict(metric=metric, name_en=spec["en"], name_zh=spec["zh"], unit=spec["unit"], frequency=spec["frequency"], scope=spec["scope"],
                         status=status, earliest_observation=history["date"].min() if date else None, latest_observation=date,
                         retrieved_at=captured, records=len(history), source=latest["source"] if date else spec["owner"],
                         source_url=latest["source_url"] if date else None, expected_reference=expected_date,
                         freshness_basis="Official release calendar" if expected_date else "Cadence/age guard (no fixed release day)",
                         missing_reference_months=missing_months(history, metric),
                         dataset=metric, type="Measure", notes=spec["en"]))
    return rows


def build_artifacts(root=DATA_DIR, output=ARTIFACT_DIR):
    observations, signals, manifest = load_current(root)
    if observations.empty:
        raise ValueError("No validated China macro generation; artifacts left unchanged")
    combined = (pd.concat([observations, signals], ignore_index=True) if not signals.empty else observations).sort_values(["metric", "date"])
    health = coverage(combined, manifest)
    urls = sorted(combined["source_url"].dropna().unique().tolist())
    public = combined[["metric", "date", "value", "scope"]].copy()
    public["source_ref"] = combined["source_url"].map({url: index for index, url in enumerate(urls)})
    rows = json.loads(public.to_json(orient="records", date_format="iso"))
    status = "ready" if all(x["status"] in ["Available", "Historical"] for x in health) else "partial"
    for language in ["en", "zh"]:
        artifact = {
            "manifest": {"id": "china-macro", "title": "中国宏观经济" if language == "zh" else "China Macro", "charts": [], "tables": []},
            "snapshot": {"generatedAt": manifest["created_at"], "run_id": manifest["run_id"], "status": status,
                         "datasets": {"observations": rows, "source_health": health, "fetch_results": manifest["source_results"],
                                      "fetch_warnings": manifest.get("fetch_warnings", [])}},
            "publication_calendar": manifest.get("publication_calendar", []),
            "series": SERIES, "groups": GROUPS,
            "source_urls": urls,
            "run_id": manifest["run_id"], "run_consistent": True,
            "sources": [{"id": x["source"], "label": x["source"], "url": x["source_url"]} for x in health if x["source_url"]],
        }
        atomic_json(output / ("china-macro-artifact" + ("-zh" if language == "zh" else "") + ".json"), artifact)
    return artifact
