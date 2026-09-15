"""Tests for the Asia Markets Streamlit ETF Heat Maps page."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP_DIR = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "asia-markets-streamlit"
)
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from am.heatmaps import (
    _format_flow_amount,
    _format_ret,
    _format_size_amount,
    render_detail_tab,
    render_flow_tab,
    render_heatmaps,
    render_performance_tab,
)
from am.page_registry import DEFINITION_BY_KEY


def _sample_artifact() -> dict[str, Any]:
    return {
        "manifest": {
            "charts": [],
            "tables": [],
        },
        "snapshot": {
            "datasets": {
                "etf_heatmap_returns": [
                    {
                        "ticker": "SPY",
                        "fund_name": "SPDR S&P 500 ETF",
                        "name_en": "SPDR S&P 500 ETF",
                        "name_zh": "标普500 ETF",
                        "category": "broad_equity",
                        "category_en": "Broad Equity",
                        "category_zh": "宽基股票",
                        "latest_price": 500.0,
                        "size_value": 450_000_000_000.0,
                        "size_basis": "market_cap_proxy",
                        "return_1d_pct": 0.5,
                        "return_1w_pct": 1.2,
                        "return_1m_pct": 2.5,
                        "return_3m_pct": 5.0,
                        "return_1y_pct": 15.0,
                        "return_ytd_pct": 10.0,
                    },
                    {
                        "ticker": "QQQ",
                        "fund_name": "Invesco QQQ",
                        "name_en": "Invesco QQQ",
                        "name_zh": "纳斯达克100 ETF",
                        "category": "broad_equity",
                        "category_en": "Broad Equity",
                        "category_zh": "宽基股票",
                        "latest_price": 400.0,
                        "size_value": 250_000_000_000.0,
                        "size_basis": "market_cap_proxy",
                        "return_1d_pct": -0.8,
                        "return_1w_pct": -1.0,
                        "return_1m_pct": 3.0,
                        "return_3m_pct": 6.0,
                        "return_1y_pct": 20.0,
                        "return_ytd_pct": 12.0,
                    },
                    {
                        "ticker": "GLD",
                        "fund_name": "SPDR Gold Shares",
                        "name_en": "SPDR Gold Shares",
                        "name_zh": "黄金 ETF",
                        "category": "commodity",
                        "category_en": "Commodities",
                        "category_zh": "大宗商品",
                        "latest_price": 200.0,
                        "size_value": 60_000_000_000.0,
                        "size_basis": "market_cap_proxy",
                        "return_1d_pct": 0.2,
                        "return_1w_pct": 0.8,
                        "return_1m_pct": -1.5,
                        "return_3m_pct": 4.0,
                        "return_1y_pct": 12.0,
                        "return_ytd_pct": 8.0,
                    },
                ],
                "etf_heatmap_flows": [
                    {
                        "fund_id": "510300",
                        "ticker": "510300",
                        "fund_name": "沪深300ETF",
                        "category": "broad_equity",
                        "category_en": "Broad Equity",
                        "category_zh": "宽基股票",
                        "coverage_status": "validated",
                        "size_value": 100_000_000_000.0,
                        "size_basis": "nav_estimate",
                        "valid_observations": 10,
                        "first_valid_flow_date": "2026-08-01",
                        "latest_valid_flow_date": "2026-09-14",
                        "flow_1d": 500_000_000.0,
                        "flow_1w": 1_200_000_000.0,
                        "flow_1m": 3_000_000_000.0,
                        "flow_3m": 5_000_000_000.0,
                        "flow_ytd": 8_000_000_000.0,
                    },
                    {
                        "fund_id": "SPY",
                        "ticker": "SPY",
                        "fund_name": "SPDR S&P 500 ETF",
                        "category": "broad_equity",
                        "category_en": "Broad Equity",
                        "category_zh": "宽基股票",
                        "coverage_status": "unavailable",
                        "size_value": 450_000_000_000.0,
                        "size_basis": "market_cap_proxy",
                        "valid_observations": 0,
                        "first_valid_flow_date": None,
                        "latest_valid_flow_date": None,
                        "flow_1d": None,
                        "flow_1w": None,
                        "flow_1m": None,
                        "flow_3m": None,
                        "flow_ytd": None,
                    },
                ],
                "heatmap_etf_price_daily": [
                    {
                        "date": f"2026-01-{(i % 28) + 1:02d}",
                        "ticker": "SPY",
                        "close": 480.0 + i * 0.5,
                        "volume": 1000000,
                    }
                    for i in range(260)
                ]
                + [
                    {
                        "date": f"2026-01-{(i % 28) + 1:02d}",
                        "ticker": "510300",
                        "close": 3.5 + i * 0.01,
                        "volume": 500000,
                    }
                    for i in range(260)
                ],
                "etf_fund_activity_daily": [
                    {
                        "observation_date": f"2026-08-{(i % 28) + 1:02d}",
                        "fund_id": "510300",
                        "ticker": "510300",
                        "flow_status": "validated",
                        "estimated_flow_cny": (i - 10) * 10_000_000.0,
                    }
                    for i in range(20)
                ],
            }
        }
    }


def test_heatmaps_is_a_lazy_market_page():
    definition = DEFINITION_BY_KEY["heatmaps"]
    assert definition.group == "markets"
    assert definition.url_path == "heat-maps"
    assert definition.renderer == "am.heatmaps:render_heatmaps"


def _run_heatmaps_zh():
    import sys
    from pathlib import Path
    app_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from am.heatmaps import render_heatmaps
    from test_asia_markets_streamlit_heatmaps import _sample_artifact

    render_heatmaps(_sample_artifact(), {}, "zh", "1 year")


def _run_heatmaps_en():
    import sys
    from pathlib import Path
    app_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from am.heatmaps import render_heatmaps
    from test_asia_markets_streamlit_heatmaps import _sample_artifact

    render_heatmaps(_sample_artifact(), {}, "en", "1 year")


def _run_heatmaps_empty():
    import sys
    from pathlib import Path
    app_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from am.heatmaps import render_heatmaps

    render_heatmaps({}, {}, "zh", "1 year")


def _run_performance_tab_only():
    import sys
    from pathlib import Path
    import pandas as pd
    app_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from am.heatmaps import render_performance_tab
    from test_asia_markets_streamlit_heatmaps import _sample_artifact

    art = _sample_artifact()
    df = pd.DataFrame(art["snapshot"]["datasets"]["etf_heatmap_returns"])
    render_performance_tab(df, "zh")


def _run_flow_tab_only():
    import sys
    from pathlib import Path
    import pandas as pd
    app_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from am.heatmaps import render_flow_tab
    from test_asia_markets_streamlit_heatmaps import _sample_artifact

    art = _sample_artifact()
    df = pd.DataFrame(art["snapshot"]["datasets"]["etf_heatmap_flows"])
    render_flow_tab(df, "zh")


def _run_detail_tab_only():
    import sys
    from pathlib import Path
    import pandas as pd
    app_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from am.heatmaps import render_detail_tab
    from test_asia_markets_streamlit_heatmaps import _sample_artifact

    art = _sample_artifact()
    returns_df = pd.DataFrame(art["snapshot"]["datasets"]["etf_heatmap_returns"])
    flows_df = pd.DataFrame(art["snapshot"]["datasets"]["etf_heatmap_flows"])
    prices_df = pd.DataFrame(art["snapshot"]["datasets"]["heatmap_etf_price_daily"])
    activity_df = pd.DataFrame(art["snapshot"]["datasets"]["etf_fund_activity_daily"])
    render_detail_tab(returns_df, flows_df, prices_df, activity_df, "zh", "1 year")


def _run_mixed_price_flow_artifact():
    import sys
    from pathlib import Path
    app_dir = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from am.heatmaps import render_heatmaps
    from test_asia_markets_streamlit_heatmaps import _sample_artifact

    art = _sample_artifact()
    art["snapshot"]["datasets"]["etf_price_daily_tail"] = [
        {"date": f"2026-08-{(i%28)+1:02d}", "ticker": "510300", "close": 3.5 + i * 0.01}
        for i in range(30)
    ]
    art["snapshot"]["datasets"]["etf_heatmap_flows"].append({
        "fund_id": "NOPRICE_ETF",
        "ticker": "NOPRICE_ETF",
        "fund_name": "No Price ETF",
        "category": "broad_equity",
        "coverage_status": "validated",
        "size_value": 10_000_000.0,
        "valid_observations": 5,
        "flow_1w": 100.0,
    })
    render_heatmaps(art, {}, "zh", "1 year")


def test_heatmaps_complete_artifact_renders_three_tabs():
    app = AppTest.from_function(_run_heatmaps_zh)
    app.run(timeout=20)
    assert not app.exception
    assert len(app.get("plotly_chart")) >= 3
    assert len(app.dataframe) >= 2


def test_heatmaps_renders_english_cleanly():
    app = AppTest.from_function(_run_heatmaps_en)
    app.run(timeout=20)
    assert not app.exception
    assert len(app.get("plotly_chart")) >= 3


def test_heatmaps_empty_artifact_shows_info():
    app = AppTest.from_function(_run_heatmaps_empty)
    app.run(timeout=20)
    assert not app.exception
    assert any("未包含" in str(info.value) for info in app.info)


def test_performance_tab_renders_treemap_and_table():
    app = AppTest.from_function(_run_performance_tab_only)
    app.run(timeout=20)
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    assert len(app.dataframe) == 1


def test_flow_tab_renders_treemap_and_table():
    app = AppTest.from_function(_run_flow_tab_only)
    app.run(timeout=20)
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    assert len(app.dataframe) == 1


def test_detail_tab_renders_detail_chart():
    app = AppTest.from_function(_run_detail_tab_only)
    app.run(timeout=20)
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1


def test_detail_tab_consumes_both_price_datasets_and_restricts_to_available_prices():
    app = AppTest.from_function(_run_mixed_price_flow_artifact)
    app.run(timeout=20)
    assert not app.exception

    ticker_select = next(sb for sb in app.selectbox if sb.key == "hm_detail_ticker")
    assert "510300" in ticker_select.options or any("510300" in str(opt) for opt in ticker_select.options)
    assert not any("NOPRICE_ETF" in str(opt) for opt in ticker_select.options)


def test_formatting_helpers():
    assert _format_ret(1.234) == "+1.23%"
    assert _format_ret(-0.5) == "-0.50%"
    assert _format_ret(None) == "—"

    assert "亿" in _format_flow_amount(500_000_000.0, "zh")
    assert "M" in _format_flow_amount(500_000_000.0, "en")
    assert _format_flow_amount(None, "zh") == "—"

    assert "亿" in _format_size_amount(100_000_000_000.0, "zh")
    assert "B" in _format_size_amount(100_000_000_000.0, "en")
    assert _format_size_amount(None, "zh") == "—"
