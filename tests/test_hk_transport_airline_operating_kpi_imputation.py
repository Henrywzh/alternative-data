from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources import airline_operating_kpi_imputation as imputation


def _synthetic_monthly() -> pd.DataFrame:
    rows = []
    for month, ask, rpk in [("2024-01", 10.0, 8.0), ("2024-03", 30.0, 24.0)]:
        for metric, value in [("ask", ask), ("rpk", rpk)]:
            rows.append(
                {
                    "month": month,
                    "airline_code": "601021",
                    "region": "Total",
                    "metric": metric,
                    "value": value,
                    "announcement_date": f"{month}-15",
                    "source_pdf_url": f"https://example.test/{month}/{metric}",
                    "source_quality": "synthetic_observed",
                }
            )
    return pd.DataFrame(rows)


def test_short_gap_is_interpolated_with_lineage_and_future_flag(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(imputation, "OUTPUT_PATH", tmp_path / "imputed.parquet")
    monkeypatch.setattr(imputation, "AUDIT_OUTPUT_PATH", tmp_path / "audit.csv")
    frame, audit = imputation.build_airline_operating_kpi_imputed(
        _synthetic_monthly(), retrieved_at="2026-08-09T00:00:00+00:00"
    )
    ask = frame.loc[
        frame.company.eq("Spring Airlines")
        & frame.month.eq("2024-02")
        & frame.metric.eq("ask")
    ].iloc[0]
    assert ask.value == pytest.approx(20.0)
    assert ask.observation_status == "imputed"
    assert ask.prev_observation_month == "2024-01"
    assert ask.next_observation_month == "2024-03"
    assert bool(ask.uses_future_observation)
    assert not bool(ask.pit_safe_for_h1_event)
    lf = frame.loc[
        frame.company.eq("Spring Airlines")
        & frame.month.eq("2024-02")
        & frame.metric.eq("passenger_load_factor_pct")
    ].iloc[0]
    assert lf.value == pytest.approx(80.0)
    assert lf.observation_status == "derived_from_imputed_levels"
    assert not bool(lf.pit_safe_for_h1_event)
    assert len(audit) >= 1


def test_covid_regime_guard_does_not_interpolate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(imputation, "OUTPUT_PATH", tmp_path / "imputed.parquet")
    monkeypatch.setattr(imputation, "AUDIT_OUTPUT_PATH", tmp_path / "audit.csv")
    source = _synthetic_monthly().replace({"2024-01": "2020-01", "2024-03": "2020-03"})
    frame, _ = imputation.build_airline_operating_kpi_imputed(
        source, retrieved_at="2026-08-09T00:00:00+00:00"
    )
    ask = frame.loc[
        frame.company.eq("Spring Airlines")
        & frame.month.eq("2020-02")
        & frame.metric.eq("ask")
    ].iloc[0]
    assert pd.isna(ask.value)
    assert ask.imputation_method == "not_filled_regime_or_long_gap"
