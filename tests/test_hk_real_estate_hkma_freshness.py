"""Regression tests for the HKMA normalized-cache freshness gate.

Build f97e0672 (2026-08-20) served a 2026-07-23 May-only local cache instead
of the live API and regressed three published dashboard series from 2026-06
back to 2026-05.  The cache short-circuit had no freshness condition at all,
so every one of these cases previously resolved to "return the cache".
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "apps" / "asia-markets-dashboard" / "scripts"


def _load_builder():
    module_name = "hk_real_estate_builder_hkma_freshness_test"
    spec = importlib.util.spec_from_file_location(
        module_name, SCRIPTS / "build_hk_real_estate_artifact.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Frozen dataclasses at module scope resolve their own module during
    # class creation, so the module has to be registered before it executes.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()


def _survey_frame(last_month: str) -> pd.DataFrame:
    months = pd.date_range("2016-12-01", last_month, freq="MS")
    return pd.DataFrame(
        {
            "observation_date": months.strftime("%Y-%m-%d"),
            "new_applications_count": range(len(months)),
            "delinquency_ratio_pct": 0.11,
        }
    )


@pytest.mark.parametrize(
    ("label", "cache_month", "today", "expected_current"),
    [
        # The regression itself: on the incident day a May-only cache must
        # not be treated as current, because June was already published.
        ("may cache on the incident day", "2026-05-01", "2026-08-20", False),
        # ...while the June cache it should have been holding is current.
        ("june cache on the incident day", "2026-06-01", "2026-08-20", True),
        # June is due ~25 days after June ends; a May cache is stale by then.
        ("may cache once june is due", "2026-05-01", "2026-07-26", False),
        # A cache holding the newest published month is ~55 days old on the
        # day it is published.  A flat 45-day age gate rejected this.
        ("june cache the day june lands", "2026-06-01", "2026-07-26", True),
        # Once July is due, June stops being current.
        ("june cache once july is due", "2026-06-01", "2026-08-27", False),
    ],
)
def test_monthly_cache_currency_tracks_publication_cadence(
    label, cache_month, today, expected_current
):
    assert (
        BUILDER._monthly_cache_is_current(
            pd.Timestamp(cache_month),
            publication_lag_days=BUILDER.HKMA_PUBLICATION_LAG_DAYS,
            margin_days=BUILDER.HKMA_PUBLICATION_MARGIN_DAYS,
            now=pd.Timestamp(today),
        )
        is expected_current
    ), label


def test_stale_cache_does_not_shadow_a_newer_live_fetch():
    """The f97e0672 regression: May cache + June on the wire must yield June."""
    stale = _survey_frame("2026-05-01")
    live = _survey_frame("2026-06-01")

    with patch.object(BUILDER, "load_latest_normalized", return_value=stale), patch.object(
        BUILDER, "fetch_hkma_residential_mortgage_survey", return_value=live
    ), patch.object(BUILDER, "save_normalized_dataset") as saved, patch.object(
        BUILDER.pd.Timestamp, "now", staticmethod(lambda *a, **k: pd.Timestamp("2026-08-20"))
    ):
        result = BUILDER._load_hkma_with_fallback()

    assert result["observation_date"].max() == "2026-06-01"
    assert len(result) == len(live)
    # A build that had to go live is exactly the build that should leave a
    # fresher vintage behind for the next one.
    assert saved.call_count == 1


def test_current_cache_short_circuits_without_a_live_fetch():
    cache = _survey_frame("2026-06-01")

    with patch.object(BUILDER, "load_latest_normalized", return_value=cache), patch.object(
        BUILDER, "fetch_hkma_residential_mortgage_survey"
    ) as fetch, patch.object(BUILDER, "save_normalized_dataset") as saved, patch.object(
        BUILDER.pd.Timestamp, "now", staticmethod(lambda *a, **k: pd.Timestamp("2026-08-01"))
    ):
        result = BUILDER._load_hkma_with_fallback()

    fetch.assert_not_called()
    saved.assert_not_called()
    assert result["observation_date"].max() == "2026-06-01"


def test_failed_fetch_falls_back_to_the_stale_cache():
    """Stale beats empty; the committed-artifact fallback stays a last resort."""
    stale = _survey_frame("2026-05-01")

    with patch.object(BUILDER, "load_latest_normalized", return_value=stale), patch.object(
        BUILDER,
        "fetch_hkma_residential_mortgage_survey",
        side_effect=RuntimeError("HKMA API unreachable"),
    ), patch.object(
        BUILDER, "_load_hkma_from_committed_artifact"
    ) as committed, patch.object(
        BUILDER.pd.Timestamp, "now", staticmethod(lambda *a, **k: pd.Timestamp("2026-08-20"))
    ):
        result = BUILDER._load_hkma_with_fallback()

    committed.assert_not_called()
    assert result["observation_date"].max() == "2026-05-01"


def test_truncated_fetch_does_not_overwrite_a_longer_cache():
    """A short upstream response is a fault, not a correction."""
    cache = _survey_frame("2026-05-01")
    truncated = _survey_frame("2026-05-01").tail(12).reset_index(drop=True)

    with patch.object(BUILDER, "load_latest_normalized", return_value=cache), patch.object(
        BUILDER, "fetch_hkma_residential_mortgage_survey", return_value=truncated
    ), patch.object(BUILDER, "save_normalized_dataset") as saved, patch.object(
        BUILDER.pd.Timestamp, "now", staticmethod(lambda *a, **k: pd.Timestamp("2026-08-20"))
    ):
        result = BUILDER._load_hkma_with_fallback()

    assert len(result) == len(cache)
    saved.assert_not_called()


def test_unchanged_fetch_does_not_write_a_duplicate_vintage():
    """save_normalized_dataset writes an immutable run dir on every call."""
    cache = _survey_frame("2026-06-01")

    with patch.object(BUILDER, "load_latest_normalized", return_value=cache), patch.object(
        BUILDER, "fetch_hkma_residential_mortgage_survey", return_value=_survey_frame("2026-06-01")
    ), patch.object(BUILDER, "save_normalized_dataset") as saved, patch.object(
        BUILDER.pd.Timestamp, "now", staticmethod(lambda *a, **k: pd.Timestamp("2026-08-27"))
    ):
        result = BUILDER._load_hkma_with_fallback()

    saved.assert_not_called()
    assert result["observation_date"].max() == "2026-06-01"
