from pathlib import Path

import pandas as pd
import pytest

from src.hk_transport.sources.airline_cargo_demand import (
    OUTPUT_COLUMNS,
    _merge_vintages,
    parse_mofcom_totalmonth_payload,
)


def _payload() -> list[object]:
    return [
        [
            {
                "trade_date": "202606",
                "total_value": 6991.51,
                "total_per": 30.6,
                "export_value": 4123.87,
                "export_per": 27,
                "import_value": 2867.64,
                "import_per": 36,
                "imexgap_value": 1256.23,
                "total_lj_value": 36747.42,
                "export_lj_value": 21253.59,
                "import_lj_value": 15493.83,
                "imexgap_lj_value": 5759.76,
            },
            {
                "trade_date": "202605",
                "total_value": 6000.0,
                "total_per": 10.0,
                "export_value": 3500.0,
                "export_per": 12.0,
                "import_value": 2500.0,
                "import_per": 8.0,
                "imexgap_value": 1000.0,
            },
        ],
        {"chart": "ignored"},
    ]


def test_parse_mofcom_totalmonth_payload_normalizes_month_and_units() -> None:
    result = parse_mofcom_totalmonth_payload(
        _payload(),
        retrieved_at="2026-08-09T12:00:00+00:00",
    )

    assert list(result.columns) == OUTPUT_COLUMNS
    assert result["observation_month"].tolist() == ["2026-05", "2026-06"]
    june = result.loc[result["observation_month"].eq("2026-06")].iloc[0]
    assert june["period_end"] == "2026-06-30"
    assert june["export_value_usd_100m"] == pytest.approx(4123.87)
    assert june["trade_balance_usd_100m"] == pytest.approx(1256.23)
    assert june["total_trade_yoy_pct"] == pytest.approx(30.6)
    assert june["source_release_date"] is None or pd.isna(june["source_release_date"])
    assert june["point_in_time_status"] == "retrieved_vintage_only_latest_snapshot"
    assert june["source_snapshot_date"] == "2026-08-09"


def test_parse_mofcom_rejects_duplicate_months() -> None:
    payload = _payload()
    payload[0].append(dict(payload[0][0]))
    with pytest.raises(ValueError, match="duplicate observation months"):
        parse_mofcom_totalmonth_payload(payload, retrieved_at="2026-08-09T12:00:00+00:00")


def test_merge_vintages_replaces_only_same_day_observation(tmp_path: Path) -> None:
    first = parse_mofcom_totalmonth_payload(
        _payload(), retrieved_at="2026-08-09T10:00:00+00:00"
    )
    second_payload = _payload()
    second_payload[0][0]["export_value"] = 9999.0
    second = parse_mofcom_totalmonth_payload(
        second_payload, retrieved_at="2026-08-09T18:00:00+00:00"
    )
    output = tmp_path / "cargo.csv"
    first.to_csv(output, index=False)
    merged = _merge_vintages(second, output)

    assert len(merged) == len(first)
    june = merged.loc[merged["observation_month"].eq("2026-06")].iloc[0]
    assert june["export_value_usd_100m"] == pytest.approx(9999.0)


def test_parse_mofcom_requires_trade_date_and_values() -> None:
    with pytest.raises(ValueError, match="missing fields"):
        parse_mofcom_totalmonth_payload(
            [[{"trade_date": "202606"}], {}],
            retrieved_at="2026-08-09T12:00:00+00:00",
        )
