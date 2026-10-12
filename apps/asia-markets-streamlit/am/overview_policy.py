"""Bounded, offline overview selection; never infer a release from a build."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import OVERVIEW_PULSE_CONFIG
from .core import frame_for_dataset, latest_metric_reading, latest_row


ECONOMIC_SECTORS = ("real_estate", "transport", "labour", "population")
RELEASE_FIELDS = ("release_date", "publication_date", "announcement_date", "published_at")


def economic_observation_rows(
    artifacts: dict[str, dict[str, Any]], language: str, *, now: Any = None,
) -> list[dict[str, Any]]:
    """One core observation per economic page, ordered by known recent release.

    Only explicit publication fields on that metric's own row can promote it.
    Mixed-cadence dataAsOf/generatedAt and daily migration traffic are not
    population releases. Missing publication evidence stays visibly unknown.
    """
    today = pd.Timestamp(now if now is not None else pd.Timestamp.now(tz="UTC"))
    today = pd.to_datetime(today, utc=True).normalize()
    rows = []
    for key in ECONOMIC_SECTORS:
        if key not in artifacts:
            continue
        metric = OVERVIEW_PULSE_CONFIG[key]["metrics"][0]
        artifact = artifacts[key]
        frame = frame_for_dataset(artifact, metric["dataset"])
        row = latest_row(frame) if not frame.empty else {}
        label, value, observed = latest_metric_reading(
            artifact, metric["dataset"], metric["field"], metric["format"],
            label_en=metric["label_en"], label_zh=metric["label_zh"], language=language,
        )
        release = pd.NaT
        # No usable measure => no release promotion, even if metadata exists.
        if value != "—":
            for field in RELEASE_FIELDS:
                candidate = pd.to_datetime(row.get(field), errors="coerce", utc=True)
                if not pd.isna(candidate) and candidate.normalize() <= today:
                    release = candidate
                    break
        recent = not pd.isna(release) and 0 <= (today - release.normalize()).days <= 30
        rows.append({
            "sector": key, "label": label, "value": value,
            "observation": observed, "release": release, "recent_release": recent,
        })
    return sorted(
        rows,
        key=lambda item: (
            not item["recent_release"],
            -item["release"].value if item["recent_release"] else 0,
            ECONOMIC_SECTORS.index(item["sector"]),
        ),
    )
