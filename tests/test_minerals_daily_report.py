from __future__ import annotations

from minerals_signal_data.daily_report import REPORT_SPECS, _build_email_html, _load_config, _source_summary


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


def test_daily_report_source_summary_prioritizes_same_day_sources() -> None:
    import pandas as pd

    prices = pd.DataFrame({"price_source": ["yfinance", "tencent", "akshare_eastmoney"]})

    assert _source_summary(prices) == "Tencent, AKShare/Eastmoney, Yahoo Finance"


def test_load_config_supports_multiple_recipients(tmp_path) -> None:
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
