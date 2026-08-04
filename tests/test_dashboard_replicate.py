from __future__ import annotations

import pandas as pd

from dashboard.sections.replicate import compute_run_count_deltas


def _row(snapshot_date, slug, run_count, owner="acme", collection="text-to-image"):
    return {
        "snapshot_date": snapshot_date,
        "slug": slug,
        "owner": owner,
        "name": slug.split("/")[-1],
        "collection": collection,
        "run_count": run_count,
        "is_official": False,
        "latest_version_created_at": "",
        "hardware": "GPU",
        "price": "",
        "description": "",
        "url": f"https://replicate.com/{slug}",
        "scraped_at": f"{snapshot_date}T00:00:00+00:00",
    }


def test_no_data_reports_unavailable():
    result = compute_run_count_deltas(pd.DataFrame())
    assert result == {"available": False, "reason": "no_data"}


def test_single_snapshot_reports_unavailable_with_date():
    catalog = pd.DataFrame([_row("2026-08-04", "acme/model-a", 100)])
    result = compute_run_count_deltas(catalog)
    assert result["available"] is False
    assert result["reason"] == "single_snapshot"
    assert result["snapshot_date"] == "2026-08-04"


def test_two_snapshots_computes_positive_and_negative_delta():
    catalog = pd.DataFrame([
        _row("2026-08-03", "acme/model-a", 100),
        _row("2026-08-03", "acme/model-b", 500),
        _row("2026-08-04", "acme/model-a", 150),  # grew by 50
        _row("2026-08-04", "acme/model-b", 480),  # shrank -- e.g. counter recalibration
    ])
    result = compute_run_count_deltas(catalog)
    assert result["available"] is True
    assert result["latest_date"] == "2026-08-04"
    assert result["previous_date"] == "2026-08-03"

    deltas = result["deltas"].set_index("slug")
    assert deltas.loc["acme/model-a", "delta"] == 50
    assert deltas.loc["acme/model-a", "pct_delta"] == 0.5
    # Negative deltas are surfaced as-is, not clamped to zero.
    assert deltas.loc["acme/model-b", "delta"] == -20
    assert deltas.loc["acme/model-b", "pct_delta"] == -0.04


def test_new_and_removed_models_excluded_from_delta_but_counted():
    catalog = pd.DataFrame([
        _row("2026-08-03", "acme/only-yesterday", 100),
        _row("2026-08-03", "acme/stable", 200),
        _row("2026-08-04", "acme/stable", 220),
        _row("2026-08-04", "acme/only-today", 50),
    ])
    result = compute_run_count_deltas(catalog)
    assert result["new_count"] == 1
    assert result["removed_count"] == 1
    # Only the model present on both days gets a delta row.
    assert list(result["deltas"]["slug"]) == ["acme/stable"]
    assert result["deltas"].iloc[0]["delta"] == 20


def test_zero_previous_run_count_does_not_crash_pct_delta():
    catalog = pd.DataFrame([
        _row("2026-08-03", "acme/brand-new-counter", 0),
        _row("2026-08-04", "acme/brand-new-counter", 10),
    ])
    result = compute_run_count_deltas(catalog)
    deltas = result["deltas"]
    assert deltas.iloc[0]["delta"] == 10
    assert pd.isna(deltas.iloc[0]["pct_delta"])


def test_only_the_two_most_recent_dates_are_compared():
    """A third, older snapshot must not leak into the comparison."""
    catalog = pd.DataFrame([
        _row("2026-08-01", "acme/model-a", 1),  # ancient snapshot, should be ignored
        _row("2026-08-03", "acme/model-a", 100),
        _row("2026-08-04", "acme/model-a", 130),
    ])
    result = compute_run_count_deltas(catalog)
    assert result["previous_date"] == "2026-08-03"
    assert result["deltas"].iloc[0]["delta"] == 30
