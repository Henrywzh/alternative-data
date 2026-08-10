from __future__ import annotations

from src.hk_transport.sources.airline_nbs_demand import (
    _article_text,
    _parse_monthly_economy,
    _parse_pmi,
)


def test_article_text_normalizes_cjk_number_spacing() -> None:
    html = (
        "<html><body><p>6月份，社会消费品零售总额"
        "<span>42691</span>亿元，同比增长1.0% 。</p></body></html>"
    )
    text = _article_text(html.encode("utf-8"))
    assert "6月份，社会消费品零售总额42691亿元，同比增长1.0% 。" in text


def test_monthly_economy_parses_single_month_and_ytd() -> None:
    release = {
        "release_id": "202605_20260518",
        "title": "2026年1—4月份社会消费品零售总额增长1.9%",
        "url": "https://www.stats.gov.cn/sj/zxfb/202605/t20260518_1963727.html",
        "date": "2026-05-18",
    }
    text = (
        "1—4月份，社会消费品零售总额164941亿元，同比增长1.9%。"
        "4月份，社会消费品零售总额37247亿元，同比增长0.2%。"
        "5月份，社会消费品零售总额41090亿元，同比下降0.6%。"
    )
    rows = _parse_monthly_economy(
        release, text, raw_path=None, retrieved="2026-08-10T00:00:00+00:00"
    )
    by_scope = {r["scope"]: r for r in rows}
    assert by_scope["ytd_jan_apr"]["value"] == 164_941.0
    assert by_scope["ytd_jan_apr"]["yoy_pct"] == 1.9
    assert by_scope["month_4"]["value"] == 37_247.0
    assert by_scope["month_4"]["yoy_pct"] == 0.2


def test_monthly_economy_handles_decline_direction() -> None:
    release = {
        "release_id": "202606_20260616",
        "title": "2026年1—5月份社会消费品零售总额增长1.4%",
        "url": "https://www.stats.gov.cn/sj/zxfb/202606/t20260616_1963949.html",
        "date": "2026-06-16",
    }
    text = "5月份，社会消费品零售总额41090亿元，同比下降0.6%。"
    rows = _parse_monthly_economy(
        release, text, raw_path=None, retrieved="2026-08-10T00:00:00+00:00"
    )
    assert rows[0]["scope"] == "month_5"
    assert rows[0]["yoy_pct"] == -0.6


def test_monthly_economy_does_not_double_match_cumulative_range() -> None:
    release = {
        "release_id": "202603_20260316",
        "title": "2026年1—2月份社会消费品零售总额增长2.8%",
        "url": "https://www.stats.gov.cn/sj/zxfb/202603/t20260316_1962786.html",
        "date": "2026-03-16",
    }
    text = "1—2月份，社会消费品零售总额86079亿元，同比增长2.8%。"
    rows = _parse_monthly_economy(
        release, text, raw_path=None, retrieved="2026-08-10T00:00:00+00:00"
    )
    scopes = [r["scope"] for r in rows]
    assert scopes == ["ytd_jan_feb"]


def test_pmi_parses_three_indexes() -> None:
    release = {
        "release_id": "202607_20260731",
        "title": "2026年7月中国采购经理指数运行情况",
        "url": "https://www.stats.gov.cn/sj/zxfb/202607/t20260731_1964253.html",
        "date": "2026-07-31",
    }
    text = (
        "7月份，制造业采购经理指数（PMI）为49.2%，比上月下降0.2个百分点。"
        "非制造业商务活动指数为49.0%，比上月下降0.1个百分点。"
        "服务业商务活动指数为49.3%。"
    )
    rows = _parse_pmi(release, text, raw_path=None, retrieved="2026-08-10T00:00:00+00:00")
    metrics = {r["metric"]: r["value"] for r in rows}
    assert metrics == {
        "manufacturing_pmi": 49.2,
        "non_manufacturing_pmi": 49.0,
        "services_business_activity_index": 49.3,
    }
