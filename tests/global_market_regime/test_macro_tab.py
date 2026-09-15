"""Macro tab commodity returns and inflation panel."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from global_market_regime.pipeline import source_health_rows
from global_market_regime.presentation import (
    build_inflation_release_panel,
    build_macro_commodity_returns,
)


def test_source_health_treats_missing_macro_as_unavailable_not_crash() -> None:
    health = source_health_rows(
        fred=pd.DataFrame(),
        mpt=pd.DataFrame(),
        fred_errors={},
        mpt_error=None,
        now=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )
    by_id = health.set_index("series_id")
    assert by_id.loc["macro_commodities", "status"] == "Unavailable"
    assert by_id.loc["inflation_panel", "status"] == "Unavailable"
