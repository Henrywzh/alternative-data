"""Regressions for bugs that shipped silently in the Phase 1-4 source lanes.

Every one of these produced plausible-looking output rather than an error, and
the original per-source tests passed throughout. The fixtures are deliberately
shaped like the real upstream documents -- the earlier tests used synthetic
inputs so minimal that the defects could not appear in them.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cme_voi_data.client import CmeBulletinClient
from eia_energy_data.storage import EiaEnergyStorage
from hkex_market_flow_data.client import HkexMarketFlowClient
from hkex_market_flow_data.storage import HkexMarketFlowStorage
from hkma_macro_data.models import AGGREGATOR, OFFICIAL_API, HkmaObservation
from hkma_macro_data.storage import HkmaMacroStorage
from sp_pmi_data.client import SpPmiClient

# A Eurozone manufacturing release that also mentions the US in passing and
# carries the site's own navigation -- i.e. a real page, not a bare fixture.
EUROZONE_RELEASE = """<html>
<h1>HCOB Eurozone Manufacturing PMI falls to 47.1 in August 2026</h1>
<nav>Home | Composite PMI | Services PMI | Global</nav>
<p>Embargoed until August 22, 2026.</p>
<p>The Eurozone Manufacturing PMI posted 47.1. New Orders Index at 45.9.
Output Index at 46.8. Employment Index 48.2. Input Prices Index 55.0.
Output Prices Index 51.0. Stocks of Finished Goods 49.4.</p>
<p>By comparison, the U.S. manufacturing sector expanded.</p>
</html>"""


def test_pmi_region_comes_from_the_headline_not_a_passing_mention() -> None:
    # Region candidates were scanned in list order over the whole page, so a
    # "U.S." aside outranked the actual subject of the release.
    observation = SpPmiClient.parse_release_html(EUROZONE_RELEASE, "https://example.invalid")
    assert observation is not None
    assert observation.region == "EUROZONE"


def test_pmi_sector_comes_from_the_headline_not_the_navigation() -> None:
    # _sector_code ran over the entire page text, and almost every S&P PMI page
    # contains the word "composite" somewhere.
    observation = SpPmiClient.parse_release_html(EUROZONE_RELEASE, "https://example.invalid")
    assert observation is not None
    assert observation.sector == "MANUFACTURING"


def test_pmi_vendor_branding_is_not_mistaken_for_a_region() -> None:
    # "S&P Global US Services PMI" is a US release; the GLOBAL in the vendor's
    # own name appears earlier in the string.
    html = "<html><h1>S&P Global US Services PMI rises to 54.2 in August 2026</h1><p>posted 54.2.</p></html>"
    observation = SpPmiClient.parse_release_html(html, "https://example.invalid")
    assert observation is not None
    assert observation.region == "US"
    assert observation.sector == "SERVICES"


def test_pmi_output_index_does_not_absorb_the_output_prices_figure() -> None:
    # "output" is a prefix of "output prices", and the label window was wide
    # enough that the shorter label captured its neighbour's number.
    observation = SpPmiClient.parse_release_html(EUROZONE_RELEASE, "https://example.invalid")
    assert observation is not None
    assert observation.output_index == 46.8
    assert observation.output_prices_index == 51.0
    assert observation.input_prices_index == 55.0
    # Both advertised derived signals are computable once the inputs are right.
    assert observation.orders_to_inventory_ratio is not None
    assert observation.price_pass_through_spread == pytest.approx(-4.0)


def test_cme_flow_regime_reports_unknown_when_price_is_unavailable() -> None:
    # The Summary Volume and Open Interest bulletin has no settlement prices,
    # so every parsed row had price_change=None. Collapsing that into NEUTRAL
    # made an unmeasurable row look like a real classification.
    text = (
        "Wed, Sep 10, 2026\n"
        "ES   E-MINI S&P 500      1,234,567   2,345,678   45,678   1,111,111   2,222,222\n"
    )
    records = CmeBulletinClient.parse_bulletin_products(text)
    assert records and {r.flow_regime for r in records} == {"UNKNOWN"}


@pytest.mark.parametrize(
    ("price_change", "oi_change", "expected"),
    [
        (None, 100, "UNKNOWN"),
        (1.0, None, "UNKNOWN"),
        (0.0, 100, "NEUTRAL"),
        (1.0, 100, "BULLISH_INFLOW"),
        (-1.0, 100, "BEARISH_INFLOW"),
        (1.0, -100, "SHORT_COVERING"),
        (-1.0, -100, "LONG_LIQUIDATION"),
    ],
)
def test_cme_every_regime_is_reachable(price_change, oi_change, expected) -> None:
    assert CmeBulletinClient.classify_positioning_flow(price_change, oi_change) == expected


def test_hkex_same_day_files_merge_instead_of_overwriting(tmp_path: Path) -> None:
    # The daily flow file and the short-selling file are fetched separately. A
    # keep="last" dedupe on trade_date let the second upsert null every column
    # the first had populated.
    storage = HkexMarketFlowStorage(tmp_path)
    storage.upsert_observations([
        HkexMarketFlowClient.derive_flow_metrics("2026-09-10", 5000.0, 4000.0, None, None, 120000.0, None)
    ])
    merged = storage.upsert_observations([
        HkexMarketFlowClient.derive_flow_metrics("2026-09-10", None, None, None, None, None, 900.0)
    ])

    assert len(merged) == 1
    row = merged.iloc[0]
    assert row["southbound_buy_turnover_hkd_mln"] == 5000.0
    assert row["total_market_turnover_hkd_mln"] == 120000.0
    assert row["short_selling_turnover_hkd_mln"] == 900.0


def test_hkma_official_wins_over_the_aggregator_mirror(tmp_path: Path) -> None:
    # Both land under the same HKMA_HIBOR_* series. Deduping on (series_id,
    # date) with keep="last" let whichever ran last win, so a third-party
    # mirror could silently overwrite an official reading.
    for first, second in ((AGGREGATOR, OFFICIAL_API), (OFFICIAL_API, AGGREGATOR)):
        storage = HkmaMacroStorage(tmp_path / f"{first}-{second}")
        values = {AGGREGATOR: 4.11, OFFICIAL_API: 4.09}
        for tier in (first, second):
            storage.upsert_observations([
                HkmaObservation("2026-09-10", "HKMA_HIBOR_ON", values[tier], "t", f"https://{tier}", tier)
            ])
        row = storage.load_observations().iloc[0]
        assert row["source_tier"] == OFFICIAL_API
        assert row["value"] == 4.09


def test_hkma_a_later_revision_from_the_same_tier_still_wins(tmp_path: Path) -> None:
    # Ranking by publisher must not freeze the first value ever seen.
    storage = HkmaMacroStorage(tmp_path)
    storage.upsert_observations([
        HkmaObservation("2026-09-10", "HKMA_AGGREGATE_BALANCE", 44850.0, "t1", "https://api", OFFICIAL_API)
    ])
    merged = storage.upsert_observations([
        HkmaObservation("2026-09-10", "HKMA_AGGREGATE_BALANCE", 45000.0, "t2", "https://api", OFFICIAL_API)
    ])
    assert merged.iloc[0]["value"] == 45000.0


def test_eia_hourly_rows_partition_by_day_not_by_hour(tmp_path: Path) -> None:
    # The partition column is an hourly label. Keying on the raw value would
    # write one file per hour -- about 67,000 for the committed backfill.
    from eia_energy_data.models import EiaGridHourlyObservation

    storage = EiaEnergyStorage(tmp_path)
    storage.upsert_grid_hourly([
        EiaGridHourlyObservation("2026-01-01T00", "PJM", "NG", 100.0, "t"),
        EiaGridHourlyObservation("2026-01-01T13", "PJM", "NG", 110.0, "t"),
        EiaGridHourlyObservation("2026-01-02T04", "PJM", "NG", 120.0, "t"),
    ])

    names = {path.name for path in storage.partition_store().paths()}
    assert names == {"2026-01-01.parquet", "2026-01-02.parquet"}
    assert len(storage.load_grid_hourly()) == 3


def test_eia_rewriting_unchanged_days_produces_no_new_bytes(tmp_path: Path) -> None:
    # A byte-identical parquet is still a new git blob, which is the whole
    # reason this table is partitioned.
    from eia_energy_data.models import EiaGridHourlyObservation

    storage = EiaEnergyStorage(tmp_path)
    storage.upsert_grid_hourly([EiaGridHourlyObservation("2026-01-01T00", "PJM", "NG", 100.0, "t")])
    store = storage.partition_store()
    assert store.write(storage.load_grid_hourly()) == []


def test_no_storage_layer_writes_a_csv_twin() -> None:
    # `*.csv` is gitignored repo-wide, so a twin was never published -- it only
    # cost local disk (151 MB against a 12 MB parquet for EIA).
    lanes = [
        "bis_macro", "hkma_macro", "eia_energy", "cme_voi",
        "factset_earnings", "sp_pmi", "msci_index_review", "hkex_market_flow",
    ]
    root = Path(__file__).resolve().parents[1] / "src"
    offenders = [
        lane for lane in lanes
        if ".to_csv(" in (root / f"{lane}_data" / "storage.py").read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.mark.parametrize(
    ("module", "attribute"),
    [
        ("cme_voi_data.pipeline", "CmeVoiPipeline"),
        ("factset_earnings_data.pipeline", "FactsetEarningsPipeline"),
        ("sp_pmi_data.pipeline", "SpPmiPipeline"),
        ("msci_index_review_data.pipeline", "MsciIndexReviewPipeline"),
        ("hkex_market_flow_data.pipeline", "HkexMarketFlowPipeline"),
    ],
)
def test_a_pipeline_without_a_collector_fails_instead_of_reporting_success(
    module: str, attribute: str, tmp_path: Path
) -> None:
    # These used to return {"observations_written": 0, "errors": {}}, which the
    # CLI printed as a clean run that collected nothing.
    import importlib

    pipeline = getattr(importlib.import_module(module), attribute)(base_dir=tmp_path)
    with pytest.raises(NotImplementedError, match="backfill_free_institutional_data"):
        pipeline.run()


def test_factset_beat_rate_matches_the_reports_actual_sentence_order() -> None:
    """The report writes the subject first, then the figure.

    The original pattern expected "X% of S&P 500 companies have reported ...
    above EPS estimates", so eps_beat_rate filled on 6 of 218 rows and both
    revenue fields on none. Verified against the 3,274 retained articles.
    """
    from factset_earnings_data.client import FactsetEarningsClient

    text = (
        "To date, 92% of the companies in the S&P 500 have reported actual results for "
        "Q2 2026. Of these companies, 86% have reported actual EPS above estimates, which "
        "is above the 5-year average of 78%. In aggregate, companies are reporting earnings "
        "that are 18.2% above estimates. In terms of revenues, 76% of S&P 500 companies "
        "have reported actual revenues above estimates. In aggregate, companies are "
        "reporting revenues that are 2.1% above estimates. The forward 12-month P/E ratio "
        "for the S&P 500 is 22.4. This P/E ratio is above the 10-year average (18.6)."
    )
    obs = FactsetEarningsClient.parse_summary_metrics(text, "2026-08-15", "2026Q2")
    assert obs.eps_beat_rate == 86.0
    assert obs.eps_surprise_pct == 18.2
    assert obs.revenue_beat_rate == 76.0
    assert obs.revenue_surprise_pct == 2.1
    assert obs.forward_12m_pe == 22.4
    assert obs.forward_12m_pe_10y_avg == 18.6


def test_factset_report_date_prefers_the_article_slug() -> None:
    # extract_article_metadata takes the first date in the page text, which can
    # belong to a sidebar teaser -- one row came out a year off that way.
    from factset_earnings_data.client import FactsetEarningsClient

    assert FactsetEarningsClient.report_date_from_url(
        "https://insight.factset.com/sp-500-earnings-season-update-january-16-2025"
    ) == "2025-01-16"
    assert FactsetEarningsClient.report_date_from_url("https://insight.factset.com/topic/earnings") == ""


def test_pmi_release_payloads_are_detected_as_pdf() -> None:
    """S&P serves press releases as PDF with HTTP 200, not as HTML.

    Feeding those bytes to BeautifulSoup produced an empty parse that was
    recorded as a WAF block, so 11 successfully captured releases were never
    read and every sub-index column stayed null.
    """
    from sp_pmi_data.client import SpPmiClient

    assert SpPmiClient.looks_like_pdf(b"%PDF-1.7\n...") is True
    assert SpPmiClient.looks_like_pdf(b"<html><body>hi</body></html>") is False


def test_pmi_release_year_is_anchored_on_the_release_date() -> None:
    # Deriving the year from datetime.now() makes an archived snapshot parse
    # into a different period months later, defeating the point of keeping it.
    from sp_pmi_data.client import SpPmiClient

    assert SpPmiClient._year_for_release("2026-01-05", "December") == 2025
    assert SpPmiClient._year_for_release("2026-09-03", "August") == 2026
    assert SpPmiClient._year_for_release("", "August") is None


def test_pmi_card_regions_and_sectors_are_normalized() -> None:
    # 38 of 53 stored rows read raw country names, and a bare "PMI" card -- the
    # whole-economy index for economies with no sector split -- stored
    # sector="PMI", which is not a sector.
    from sp_pmi_data.client import SpPmiClient

    assert SpPmiClient._region_code("Hong Kong") == "HK"
    assert SpPmiClient._region_code("Czech Republic") == "CZ"
    assert SpPmiClient._region_code("United Arab Emirates") == "AE"
    assert SpPmiClient._sector_code("PMI") == "WHOLE_ECONOMY"
    assert SpPmiClient._sector_code("Whole Economy PMI") == "WHOLE_ECONOMY"
    assert SpPmiClient._sector_code("Manufacturing PMI") == "MANUFACTURING"
