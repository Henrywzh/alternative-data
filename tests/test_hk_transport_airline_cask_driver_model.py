from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_cask_driver_model import (
    build_airline_cask_driver_model,
)


def test_cask_model_covers_all_carriers() -> None:
    df = build_airline_cask_driver_model()
    assert len(df) == 6
    assert df["fuel_price_usd_per_gallon"].notna().all()
    assert df["fuel_efficiency_implied"].notna().all()


def test_fuel_cask_scales_with_price_ratio() -> None:
    df = build_airline_cask_driver_model()
    spring = df[df["company"].eq("Spring Airlines")].iloc[0]
    # FY2025 fuel CASK was ~0.101; 2026 spot fuel (~3.51) is ~66% above the
    # FY2025 average (~2.11), so the driver model must scale fuel CASK UP.
    assert spring["fuel_cask_forecast"] > 0.10
    # The fuel price ratio embedded in the forecast equals now/prior.
    assert spring["fuel_price_usd_per_gallon"] > spring["prior_fuel_price_usd_per_gallon"]


def test_big_three_have_full_cask_forecast() -> None:
    df = build_airline_cask_driver_model()
    big3 = df[df["company"].isin(
        ["China Southern Airlines", "China Eastern Airlines", "Air China"]
    )]
    assert big3["cask_forecast"].notna().all()
    assert (big3["cask_forecast"] > 0.3).all()


def test_driver_labels_are_explicit() -> None:
    df = build_airline_cask_driver_model()
    spring = df[df["company"].eq("Spring Airlines")].iloc[0]
    assert "ask_proxy" in spring["staff_cask_driver"]
    assert "fuel_price_ratio" in spring["fuel_cask_driver"]
