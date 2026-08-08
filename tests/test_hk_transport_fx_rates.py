from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.fx_rates import FX_RATE_COLUMNS, parse_ecb_reference_rates_csv


def test_parse_ecb_reference_rates_derives_usd_crosses() -> None:
    frame = pd.DataFrame(
        [
            {"TIME_PERIOD": "2026-08-05", "CURRENCY": "USD", "CURRENCY_DENOM": "EUR", "OBS_VALUE": 1.1},
            {"TIME_PERIOD": "2026-08-05", "CURRENCY": "CNY", "CURRENCY_DENOM": "EUR", "OBS_VALUE": 7.7},
            {"TIME_PERIOD": "2026-08-05", "CURRENCY": "HKD", "CURRENCY_DENOM": "EUR", "OBS_VALUE": 8.6},
        ]
    )
    result = parse_ecb_reference_rates_csv(
        frame.to_csv(index=False).encode(),
        source_url="https://example.test/ecb.csv",
        retrieved_at="2026-08-06T00:00:00+00:00",
    )

    assert list(result.columns) == FX_RATE_COLUMNS
    assert set(result["pair"]) == {"USD_CNY", "USD_HKD"}
    assert result.loc[result["pair"].eq("USD_CNY"), "value"].item() == 7.0
    assert result.loc[result["pair"].eq("USD_HKD"), "value"].item() == 8.6 / 1.1
    assert result["source_reference_currency"].eq("EUR").all()

