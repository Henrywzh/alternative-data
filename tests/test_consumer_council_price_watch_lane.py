"""The Online Price Watch lane must read the format the source publishes.

CONSUMER_COUNCIL_PRICE_WATCH_URL ends in `pricewatch_en.csv` and answers
`Content-Type: text/csv`. This lane called `.json()` on it, so every run raised

    Expecting value: line 1 column 1 (char 0)

returned an empty frame, and -- because run_stage_1_pipeline is `--strict` and
has no required/optional split -- failed the entire stage-1 ingest. That kept
the Asia Markets dashboard refresh in DEGRADED_RETAINED with a permanently
open NEEDS_HUMAN incident. Against the live source the lane now returns ~7,700
rows; it had been returning none.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hk_local_consumer.sources import consumer_council


def _csv_frame() -> pd.DataFrame:
    # The shape consumer_council_pricewatch returns from the real CSV.
    return pd.DataFrame(
        [
            {
                "date": "2026-09-13",
                "category_1": "Bakery",
                "category_2": "Bread",
                "category_3": "Sliced",
                "product_code": "P000003983",
                "brand": "Baker's Choice",
                "product_name": "CRUSTLESS WHEAT SANDWICH BREAD",
                "supermarket_code": "PARKNSHOP",
                "price": 10.9,
                "offers": "",
                "data_source": "live",
            },
            {
                "date": "2026-09-13",
                "category_1": "Bakery",
                "category_2": "Bread",
                "category_3": "Sliced",
                "product_code": "P000003984",
                "brand": "Baker's Choice",
                "product_name": "HIGH GRADE SANDWICH BREAD",
                "supermarket_code": "PARKNSHOP",
                "price": 12.5,
                "offers": "Buy 2 get 1",
                "data_source": "live",
            },
        ]
    )


@pytest.fixture()
def csv_source(monkeypatch):
    monkeypatch.setattr(
        "hk_local_consumer.sources.consumer_council_pricewatch.fetch_consumer_council_pricewatch",
        _csv_frame,
    )


def test_the_lane_returns_rows_from_the_published_csv(csv_source) -> None:
    frame = consumer_council.fetch_consumer_council_prices()

    assert len(frame) == 2
    assert frame["product_id"].tolist() == ["P000003983", "P000003984"]
    assert frame["price_hkd"].tolist() == [10.9, 12.5]


def test_the_lane_satisfies_its_declared_contract(csv_source) -> None:
    # pipeline.py declares these required; a null in any of them fails the run.
    from hk_local_consumer.pipeline import QUALITY_SPECS

    required = QUALITY_SPECS["consumer_council_price_watch_daily"]["required"]
    frame = consumer_council.fetch_consumer_council_prices()

    for column in required:
        assert column in frame.columns, column
        assert frame[column].notna().all(), column


def test_a_field_the_source_does_not_publish_is_left_empty(csv_source) -> None:
    # The CSV has an "offers" note but no pre-discount figure. Deriving one
    # would be fabricating data the source never gave.
    frame = consumer_council.fetch_consumer_council_prices()

    assert frame["original_price_hkd"].isna().all()
    assert frame["is_on_sale"].tolist() == [False, True]


def test_an_empty_upstream_does_not_fabricate_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        "hk_local_consumer.sources.consumer_council_pricewatch.fetch_consumer_council_pricewatch",
        lambda: pd.DataFrame(),
    )

    frame = consumer_council.fetch_consumer_council_prices()

    assert frame.empty
