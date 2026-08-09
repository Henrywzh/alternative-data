import pandas as pd
import pytest

from src.hk_transport.sources.airline_postal_demand import (
    OUTPUT_COLUMNS,
    parse_spb_postal_html,
)


def _article_html() -> str:
    # Include the site's navigation keyword before the article body.  The
    # parser must not treat that keyword as the metric row, and revenue/volume
    # rows deliberately use different Chinese units.
    return """
    <html><body>
      搜索热词：快递业务量
      6月份，邮政行业业务收入完成1543.6亿元，同比增长9.7%。
      其中，快递业务收入完成1263.2亿元，同比增长9.0%。
      6月份，邮政行业寄递业务量完成183.3亿件，同比增长13.7%。
      其中，快递业务量完成168.7亿件，同比增长15.8%。
      上半年，邮政行业业务收入累计完成8730.9亿元，同比增长8.3%。
      其中，快递业务收入累计完成7187.8亿元，同比增长10.1%。
      上半年，邮政行业寄递业务量累计完成1045.1亿件，同比增长16.9%。
      其中，快递业务量累计完成956.4亿件，同比增长19.3%。
      上半年，同城快递业务量累计完成78.8亿件，同比增长6.2%；
      异地快递业务量累计完成857.4亿件，同比增长20.6%；
      国际/港澳台快递业务量累计完成20.2亿件，同比增长22.5%。
    </body></html>
    """


def test_parse_spb_normalizes_revenue_and_volume_units() -> None:
    result = parse_spb_postal_html(
        _article_html(),
        observation_period="2025-H1",
        observation_month="2025-06",
        period_end="2025-06-30",
        source_release_date="2025-07-16",
        source_url="https://example.test/spb",
        retrieved_at="2026-08-09T12:00:00+00:00",
    )

    assert list(result.columns) == OUTPUT_COLUMNS
    cumulative = result.loc[result["period_type"].eq("cumulative")].set_index("metric")
    assert cumulative.loc["postal_business_revenue", "value"] == pytest.approx(873090.0)
    assert cumulative.loc["postal_business_revenue", "unit"] == "RMB million"
    assert cumulative.loc["express_delivery_volume", "value"] == pytest.approx(95640.0)
    assert cumulative.loc["express_delivery_volume", "unit"] == "million parcels"
    assert cumulative.loc["express_delivery_volume", "yoy_pct"] == pytest.approx(19.3)


def test_parse_spb_rejects_wrong_unit_match() -> None:
    # A misleading revenue row appears after the express-volume label.  The
    # volume parser must keep searching for 亿件/万件 rather than accepting 元.
    html = """
    <body>
      快递业务量累计完成999.0亿元，同比增长99.0%。
      快递业务量累计完成956.4亿件，同比增长19.3%。
      邮政行业业务收入累计完成8730.9亿元，同比增长8.3%。
      快递业务收入累计完成7187.8亿元，同比增长10.1%。
      邮政行业寄递业务量累计完成1045.1亿件，同比增长16.9%。
    </body>
    """
    result = parse_spb_postal_html(
        html,
        observation_period="2025-H1",
        observation_month="2025-06",
        period_end="2025-06-30",
        source_release_date="2025-07-16",
        source_url="https://example.test/spb",
    )
    row = result.loc[
        result["metric"].eq("express_delivery_volume") & result["period_type"].eq("cumulative")
    ].iloc[0]
    assert row["value"] == pytest.approx(95640.0)
    assert row["unit"] == "million parcels"


def test_parse_spb_requires_core_cumulative_metrics() -> None:
    with pytest.raises(ValueError, match="all core cumulative metrics"):
        parse_spb_postal_html(
            "邮政行业业务收入累计完成8730.9亿元，同比增长8.3%。",
            observation_period="2025-H1",
            observation_month="2025-06",
            period_end="2025-06-30",
            source_release_date="2025-07-16",
            source_url="https://example.test/spb",
        )
