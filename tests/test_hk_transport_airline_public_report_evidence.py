from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_public_report_evidence import (
    PUBLIC_REPORT_PAGES,
    build_airline_public_report_evidence,
    merge_public_report_evidence_history,
    parse_10jqka_report_evidence,
)


HTML_FIXTURE = """
<table class="m_table m_hl posi_table"><tbody>
<tr><th>机构名称</th><td>研究员</td><td>EPS26</td><td>EPS27</td><td>EPS28</td><td>NP26</td><td>NP27</td><td>NP28</td><td>报告日期</td></tr>
<tr><th>测试证券</th><td>测试分析师</td><td><s class="down"></s>0.10</td><td>0.20</td><td>0.30</td><td><s class="down"></s>1.20亿</td><td>2.40亿</td><td>3.60亿</td><td>2026-07-21</td></tr>
</tbody></table>
<table class="m_table ggintro organData"><tbody>
<tr>
  <th>营业收入(元)</th><td>100亿</td><td>110亿</td><td>120亿</td>
  <td><table><tbody><tr><th>研究机构</th><th>研究员</th><th>预测值</th><th>评级</th></tr><tr><td>测试证券</td><td>测试分析师</td><td>130亿</td><td>-</td></tr></tbody></table></td>
  <td><table><tbody><tr><th>研究机构</th><th>研究员</th><th>预测值</th><th>评级</th></tr><tr><td>测试证券</td><td>测试分析师</td><td>140亿</td><td>买入</td></tr></tbody></table></td>
  <td><table><tbody><tr><th>研究机构</th><th>研究员</th><th>预测值</th><th>评级</th></tr><tr><td>测试证券</td><td>测试分析师</td><td>150亿</td><td>-</td></tr></tbody></table></td>
</tr>
</tbody></table>
"""


def test_parser_keeps_dated_eps_profit_separate_from_undated_revenue() -> None:
    result = parse_10jqka_report_evidence(
        HTML_FIXTURE,
        page=PUBLIC_REPORT_PAGES[0],
        snapshot_date="2026-08-07",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )

    assert len(result) == 9
    dated = result.loc[result["metric"].isin({"eps", "net_profit"})]
    assert dated["report_date"].eq("2026-07-21").all()
    assert dated["information_scope"].eq("institution_report_date").all()
    assert dated.loc[dated["metric"].eq("eps"), "revision_flag"].iloc[0] == "down"
    assert dated.loc[dated["metric"].eq("net_profit"), "forecast_value_native"].iloc[0] == 1.2

    revenue = result.loc[result["metric"].eq("revenue")]
    assert len(revenue) == 3
    assert revenue["report_date"].isna().all()
    assert revenue["information_scope"].eq("page_snapshot_only").all()
    assert revenue.loc[revenue["fiscal_year"].eq(2027), "rating"].iloc[0] == "买入"


def test_build_uses_supplied_page_bodies_without_network() -> None:
    result = build_airline_public_report_evidence(
        {"601111": HTML_FIXTURE},
        snapshot_date="2026-08-07",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert result["company"].eq("Air China").all()
    assert result["source_url"].str.contains("601111/worth.html").all()
    assert result["forecast_value_native"].notna().all()
    assert pd.api.types.is_integer_dtype(result["fiscal_year"])


def test_merge_public_report_history_is_append_only_and_idempotent_by_pit_key() -> None:
    prior = build_airline_public_report_evidence(
        {"601111": HTML_FIXTURE},
        snapshot_date="2026-08-06",
        retrieved_at="2026-08-06T00:00:00+00:00",
    )
    current = prior.copy()
    current["snapshot_date"] = "2026-08-07"
    current.loc[current["metric"].eq("eps"), "forecast_value_native"] = 0.11
    merged = merge_public_report_evidence_history(prior, current)
    assert len(merged) == len(prior) * 2
    assert set(merged["snapshot_date"]) == {"2026-08-06", "2026-08-07"}

    corrected = current.copy()
    corrected.loc[corrected["metric"].eq("eps"), "forecast_value_native"] = 0.12
    rerun = merge_public_report_evidence_history(merged, corrected)
    assert len(rerun) == len(merged)
    latest_eps = rerun.loc[
        rerun["snapshot_date"].eq("2026-08-07") & rerun["metric"].eq("eps")
    ]
    assert latest_eps["forecast_value_native"].eq(0.12).all()
