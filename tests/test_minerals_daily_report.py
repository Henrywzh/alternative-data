from __future__ import annotations

from minerals_signal_data.daily_report import (
    MINERAL_PRICE_FRESHNESS_DAYS,
    REPORT_SPECS,
    _build_email_html,
    _load_config,
    _mineral_freshness_notice,
    _mineral_price_age_days,
    _source_summary,
)


def test_daily_report_email_keeps_titles_outside_chart_images() -> None:
    html = _build_email_html(
        REPORT_SPECS[0],
        report_date="2026-07-20",
        mineral_date="2026-07-20",
        stock_date="2026-07-20",
        source_summary="Tencent, Yahoo Finance",
        mineral_cid="mineral-cid",
        stock_cid="stock-cid",
    )

    assert "钨每日图表简报" in html
    assert "钨产品价格走势" in html
    assert "cid:mineral-cid" in html
    assert "cid:stock-cid" in html
    assert "手机图表" not in html
    assert "高清附件" not in html


def test_mineral_quote_freshness_marks_stale_prices() -> None:
    age_days = _mineral_price_age_days("2026-10-07", "2026-09-29")
    html = _build_email_html(
        REPORT_SPECS[1],
        report_date="2026-10-07",
        mineral_date="2026-09-29",
        stock_date="2026-10-07",
        source_summary="Tencent",
        mineral_cid="mineral-cid",
        stock_cid="stock-cid",
    )

    assert age_days == 8
    assert "报价截至 2026-09-29" in html
    assert "数据滞后 8 天" in html
    assert _mineral_freshness_notice("2026-10-07", "2026-10-03") == ""


def test_mineral_quote_freshness_threshold_is_seven_days() -> None:
    assert MINERAL_PRICE_FRESHNESS_DAYS == 7
    assert _mineral_price_age_days("2026-10-07", "2026-09-30") == 7
    assert _mineral_freshness_notice("2026-10-07", "2026-09-30") == ""
    assert _mineral_price_age_days("2026-10-07", "—") is None


def test_daily_report_source_summary_prioritizes_same_day_sources() -> None:
    import pandas as pd

    prices = pd.DataFrame({"price_source": ["yfinance", "tencent", "akshare_eastmoney"]})

    assert _source_summary(prices) == "Tencent, AKShare/Eastmoney, Yahoo Finance"


def test_load_config_supports_multiple_recipients(tmp_path, monkeypatch) -> None:
    for key in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD", "GMAIL_RECIPIENT", "GMAIL_RECIPIENTS"):
        monkeypatch.delenv(key, raising=False)

    (tmp_path / ".config").write_text(
        "GMAIL_SENDER=sender@gmail.com\n"
        "GMAIL_APP_PASSWORD=test-password\n"
        "GMAIL_RECIPIENT=one@gmail.com\n"
        "GMAIL_RECIPIENTS=one@gmail.com, two@qq.com;three@263.net\n",
        encoding="utf-8",
    )

    config = _load_config(tmp_path)

    assert config["GMAIL_RECIPIENTS"] == "one@gmail.com"
    production_config = _load_config(tmp_path, production=True)
    assert production_config["GMAIL_RECIPIENTS"] == "one@gmail.com, two@qq.com, three@263.net"
