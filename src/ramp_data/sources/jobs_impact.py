"""Ramp AI Jobs-Impact source (Playwright).

The event-study table on ``ramp.com/data/ai-jobs-impact`` (headcount effect after
AI adoption for high- vs low-intensity firms, month -12..24, with 95% CIs) is
NOT in the server HTML — Ramp renders it client-side from JS chunks. So we drive
a real browser (Playwright/chromium), let the page hydrate, and read the fully
rendered accessible ``<table>`` from the DOM. Values are read via ``textContent``
(not ``innerText``) so they resolve even when the table is off-screen.

This is a static annual research artifact (the Revelio paper), so it runs
on-demand rather than on a schedule.

The browser render (``fetch_snapshots``) is separated from parsing (``extract``):
the render emits a JSON snapshot of the raw tables, and ``extract`` is a pure
function over that JSON, so it can be unit-tested against a fixture without a
browser.
"""
from __future__ import annotations

import json
import re

from ramp_data.models import GenericRecord, RunContext, Snapshot
from ramp_data.schemas import JOBS_IMPACT_DATASET
from ramp_data.sources.base import SourceExtractor

JOBS_IMPACT_URL = "https://ramp.com/data/ai-jobs-impact"
SNAPSHOT_NAME = "jobs_impact_tables"
UNITS = "log points x 100"

# JS run in the page: capture every data table as {caption, headers, rows} using
# textContent so hidden/off-screen cells still resolve.
_TABLE_JS = """() => {
  return [...document.querySelectorAll('table')].map(t => {
    const cap = t.querySelector('caption');
    const headers = [...t.querySelectorAll('thead th, thead td')].map(e => e.textContent.trim());
    const rows = [...t.querySelectorAll('tbody tr')].map(
      tr => [...tr.querySelectorAll('th, td')].map(td => td.textContent.trim())
    );
    return { caption: cap ? cap.textContent.trim() : '', headers, rows };
  });
}"""


def _figure_from_caption(caption: str) -> str:
    """"…: Total Headcount: estimates…" -> "total_headcount". Falls back safely."""
    parts = [p.strip() for p in caption.split(":")]
    label = parts[1] if len(parts) >= 3 else (caption or "figure")
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return slug or "figure"


def _to_float(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_int(text: str) -> int | None:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _is_jobs_impact_table(headers: list[str]) -> bool:
    """Guard against grabbing an unrelated table: expect the 7-column event study."""
    if len(headers) != 7:
        return False
    joined = " ".join(headers).lower()
    return "high-intensity" in joined and "low-intensity" in joined and "adoption" in joined


class RampJobsImpactSource(SourceExtractor):
    name = "ramp_jobs_impact"

    def __init__(self, timeout_ms: int = 60000, settle_ms: int = 3000) -> None:
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms

    def fetch_snapshots(self) -> list[Snapshot]:
        # Imported lazily so importing this module (e.g. in tests) does not require
        # a browser to be installed.
        from playwright.sync_api import sync_playwright

        tables: list[dict] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(JOBS_IMPACT_URL, wait_until="networkidle", timeout=self.timeout_ms)
                page.wait_for_timeout(self.settle_ms)
                tables = page.evaluate(_TABLE_JS) or []
            finally:
                browser.close()

        return [
            Snapshot(
                name=SNAPSHOT_NAME,
                source_url=JOBS_IMPACT_URL,
                body=json.dumps(tables),
            )
        ]

    def extract(
        self,
        snapshots: list[Snapshot],
        context: RunContext,
    ) -> dict[str, list[GenericRecord]]:
        extracted: dict[str, list[GenericRecord]] = {JOBS_IMPACT_DATASET: []}

        body = next((s.body for s in snapshots if s.name == SNAPSHOT_NAME), "")
        if not body:
            return extracted
        try:
            tables = json.loads(body)
        except json.JSONDecodeError as exc:
            print(f"Warning: bad jobs-impact snapshot JSON: {exc}")
            return extracted

        for table in tables:
            headers = table.get("headers", [])
            if not _is_jobs_impact_table(headers):
                continue
            figure = _figure_from_caption(table.get("caption", ""))
            for row in table.get("rows", []):
                if len(row) != 7:
                    continue
                month = _to_int(row[0])
                if month is None:
                    continue
                extracted[JOBS_IMPACT_DATASET].append(
                    GenericRecord(
                        dataset_id=JOBS_IMPACT_DATASET,
                        source_url=JOBS_IMPACT_URL,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        payload={
                            "figure": figure,
                            "month_relative_to_adoption": month,
                            "high_intensity_effect": _to_float(row[1]),
                            "high_intensity_ci_low": _to_float(row[2]),
                            "high_intensity_ci_high": _to_float(row[3]),
                            "low_intensity_effect": _to_float(row[4]),
                            "low_intensity_ci_low": _to_float(row[5]),
                            "low_intensity_ci_high": _to_float(row[6]),
                            "units": UNITS,
                        },
                    )
                )

        return extracted
