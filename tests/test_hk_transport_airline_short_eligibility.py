from __future__ import annotations

from pathlib import Path

import pandas as pd

from hk_transport.sources.airline_short_eligibility import (
    candidate_hkex_detail_urls,
    normalize_sse_eligibility,
    parse_hkex_eligibility,
)


def test_candidate_hkex_detail_urls_respects_point_in_time_cutoff() -> None:
    html = """
    <a href="/eng/market/sec_tradinfo/ds20260808.htm">future</a>
    <a href="/eng/market/sec_tradinfo/ds20260626.htm">latest</a>
    <a href="/eng/market/sec_tradinfo/ds20260618.htm">prior</a>
    """
    result = candidate_hkex_detail_urls(html, cutoff_date="2026-08-07")
    assert result == [
        ("2026-06-26", "https://www.hkex.com.hk/eng/market/sec_tradinfo/ds20260626.htm"),
        ("2026-06-18", "https://www.hkex.com.hk/eng/market/sec_tradinfo/ds20260618.htm"),
    ]


def test_parse_hkex_eligibility_keeps_designated_status_separate_from_borrow() -> None:
    html = """
    <table>
      <tr><th>No.</th><th>Stock Code</th><th>Stock Short Name</th><th>Tick Rule Exemption</th></tr>
      <tr><td>1</td><td>293</td><td>CATHAY PAC AIR</td><td></td></tr>
      <tr><td>2</td><td>753</td><td>AIR CHINA</td><td></td></tr>
    </table>
    """
    result = parse_hkex_eligibility(
        html,
        effective_date="2026-06-26",
        snapshot_date="2026-08-07",
        source_url="https://example.test/ds20260626.htm",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 4
    assert result["eligibility_status"].eq("designated_security_eligible").sum() == 2
    assert result["borrow_data_available"].eq(False).all()


def test_normalize_sse_eligibility_preserves_missingness_and_not_borrow() -> None:
    raw = pd.DataFrame([{"标的证券代码": "601111"}])
    result = normalize_sse_eligibility(
        raw,
        observation_date="2026-08-06",
        snapshot_date="2026-08-07",
        retrieved_at="2026-08-07T00:00:00+00:00",
    )
    assert len(result) == 6
    assert result.loc[result["security_code"].eq("601111"), "eligibility_status"].item() == "margin_security_observed"
    assert result.loc[result["security_code"].eq("603885"), "eligibility_status"].item() == "not_observed_in_margin_detail"
    assert result["borrow_data_available"].eq(False).all()


def test_current_short_eligibility_snapshot_covers_target_universe() -> None:
    frame = pd.read_csv(Path("data/normalized/hk_transport/airline_short_eligibility.csv"))
    assert len(frame) == 10
    assert set(frame["market"]) == {"HK", "CN_A"}
    assert frame["snapshot_date"].eq("2026-08-07").all()
    assert frame["borrow_data_available"].eq(False).all()
    assert frame.loc[frame["market"].eq("HK"), "eligibility_status"].eq(
        "designated_security_eligible"
    ).all()
    assert frame.loc[frame["market"].eq("CN_A"), "eligibility_status"].eq(
        "margin_security_observed"
    ).all()
