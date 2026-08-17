import pandas as pd
import pytest

from src.hk_transport.sources import airline_caac_sector_proxy_validation as validation


def _operating() -> pd.DataFrame:
    rows = []
    for code, year, multiplier in (
        ("601111", 2020, 100.0),
        ("601111", 2021, 120.0),
    ):
        for month in range(1, 7):
            for metric in ("passengers", "cargo_tonnes", "ask", "rpk"):
                rows.append(
                    {
                        "airline_code": code,
                        "scope": "company_total",
                        "metric": metric,
                        "month": f"{year}-{month:02d}",
                        "value": multiplier,
                        "observation_status": "observed",
                        "announcement_date": f"{year}-{month + 1:02d}-20",
                    }
                )
    return pd.DataFrame(rows)


def _caac() -> pd.DataFrame:
    rows = []
    for month, passenger_yoy, cargo_yoy in (("2020-06", -10.0, -5.0), ("2021-06", 10.0, 15.0)):
        for metric, yoy in (("passenger_volume", passenger_yoy), ("cargo_mail_volume", cargo_yoy)):
            rows.append(
                {
                    "observation_month": month,
                    "period_type": "ytd",
                    "scope": "total",
                    "metric": metric,
                    "value": 100.0,
                    "yoy_pct": yoy,
                    "source_release_date": f"{month[:4]}-07-20",
                    "point_in_time_status": "release_date_safe_observation",
                }
            )
    return pd.DataFrame(rows)


def test_validation_compares_company_and_caac_growth(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(validation, "OUTPUT_PATH", tmp_path / "validation.csv")
    monkeypatch.setattr(validation, "SUMMARY_OUTPUT_PATH", tmp_path / "summary.csv")
    result, summary = validation.build_airline_caac_sector_proxy_validation(
        operating=_operating(),
        caac=_caac(),
        years=(2021,),
        periods=("H1",),
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    spring = result.loc[result["company"].eq("Air China")].iloc[0]
    assert spring["company_passenger_yoy_pct"] == pytest.approx(20.0)
    assert spring["caac_passenger_volume_yoy_pct"] == pytest.approx(10.0)
    assert spring["passenger_growth_error_pp"] == pytest.approx(10.0)
    assert spring["company_cargo_tonnes_yoy_pct"] == pytest.approx(20.0)
    assert spring["caac_cargo_mail_volume_yoy_pct"] == pytest.approx(15.0)
    assert spring["cargo_growth_error_pp"] == pytest.approx(5.0)
    assert spring["company_observed_only"]
    assert summary.iloc[0]["passenger_mae_pp"] == pytest.approx(10.0)
    assert summary.iloc[0]["cargo_mae_pp"] == pytest.approx(5.0)
