"""Regression tests for the China listed-airlines PDF parser.

The four bugs fixed in 5f65a6e all corrupted data *silently* -- no crash, no
empty frame, just wrong numbers reaching the dashboard (Spring Airlines' ASK
stored 100x too large, whole metric breakdowns dropped, a load factor above
100%). Nothing here was covered by a test, and this is the bug class that
comes back unnoticed the next time someone edits the row loop.

Two of the four fixes live in pure string functions and are tested directly.
The other two (positional region inference, first-wins de-dup) live inside
parse_airline_pdf's pdfplumber loop and would need a PDF fixture that
reproduces page-break extraction artifacts. They are covered instead by
invariant tests over the committed parquet, which is where their damage
actually surfaced -- a wrong unit scale or a dropped region row cannot hold
those invariants.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
EVENT_PARQUET = ROOT / "data" / "processed" / "airline_traffic" / "china_airlines_operating_events.parquet"
PDF_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "airline_pdfs" / "603885"
CARRIERS = {
    "601111": "Air China",
    "600029": "China Southern",
    "600115": "China Eastern",
    "601021": "Spring Airlines",
    "600221": "Hainan Airlines Holdings",
    "603885": "Juneyao Airlines",
}


def _scraper():
    spec = importlib.util.spec_from_file_location(
        "cn_airline_scraper", ROOT / "scripts" / "scrape_cn_airline_traffic.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- unit scale: Spring states ASK/RPK 100x smaller than the other carriers ---


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        # Air China / China Southern / China Eastern: millions.
        ("可用座位公里（百万）", 1.0),
        ("客运人公里（RPK）（百万）", 1.0),
        # Spring Airlines: ten-thousands, i.e. 100x smaller.
        ("可利用座公里（万座公里）", 0.01),
        ("收入客公里（万人公里）", 0.01),
        # China Eastern wraps the unit annotation across a line break that
        # lands inside "百万"; the newline-to-space cleanup upstream leaves
        # "百 万". Because "百万" contains "万", a naive check falls through to
        # the ten-thousands branch and shrinks China Eastern's RPK 100x.
        ("客运人公里（RPK）（百 万）", 1.0),
        ("可用座位公里 （百 万）", 1.0),
        # No unit annotation at all: assume the common millions basis.
        ("可用座位公里", 1.0),
        ("", 1.0),
    ],
)
def test_ask_rpk_unit_scale(header: str, expected: float) -> None:
    assert _scraper()._ask_rpk_unit_scale(header) == expected


def test_hundred_million_is_not_read_as_ten_thousand() -> None:
    """Guard the substring trap directly: "百万" must never match the "万" branch."""
    scale = _scraper()._ask_rpk_unit_scale
    assert scale("（百万）") == scale("（百 万）") == 1.0
    assert scale("（万）") == 0.01


@pytest.mark.parametrize(
    ("header", "metric", "expected"),
    [
        ("可利用货邮吨公里（万吨公里）", "aftk", 0.01),
        ("可利用吨公里——货邮运（百万）", "aftk", 1.0),
        ("可用货运吨公里（百万）", "aftk", 1.0),
        ("收入货运吨公里（万吨公里）", "rftk", 0.01),
        ("收入吨公里——货邮运（百万）", "rftk", 1.0),
        ("货运及邮运量（千吨）", "cargo_tonnes", 1000.0),
        ("货邮载运量（公斤）（百万）", "cargo_tonnes", 1000.0),
        ("货物及邮件数量（吨）", "cargo_tonnes", 1.0),
    ],
)
def test_auxiliary_metric_unit_scale(header: str, metric: str, expected: float) -> None:
    scraper = _scraper()
    assert scraper._metric_unit_scale(header, metric) == expected


# --- metric header classification, including the mid-keyword line wrap ---


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("可用座位公里（百万）", "ask"),
        ("可利用座公里", "ask"),
        # China Southern's own pre-2019-03 ASK header (座 seat -> 客
        # passenger); it switched to "可利用座公里" from March 2019 onward,
        # matching every other carrier. Missing this dropped ASK for 38
        # months across 2016-2019.
        ("可利用客公里（ASK）（百万）", "ask"),
        ("收入客公里", "rpk"),
        ("旅客周转量", "rpk"),
        ("乘客人数（千）", "passengers"),
        ("载运旅客人次", "passengers"),
        ("客座利用率（%）", "passenger_load_factor_pct"),
        ("客座率", "passenger_load_factor_pct"),
        # China Eastern wraps its passenger header inside the keyword
        # ("载运旅客人" + newline + "次（千）"), leaving a stray space that
        # broke plain substring matching and dropped the whole metric.
        ("载运旅客人 次（千）", "passengers"),
        ("可用货邮吨公里（万吨公里）", "aftk"),
        ("可用货邮吨公", "aftk"),
        ("可利用吨公里——货邮运（百万）", "aftk"),
        ("收入吨公里——货邮运（百万）", "rftk"),
        ("货运及邮运量（千吨）", "cargo_tonnes"),
        ("货物及邮件载运率", "freight_load_factor_pct"),
        ("总体载运率（RTK/ATK）", "overall_load_factor_pct"),
        ("可用吨公里（ATK）（百万）", "atk"),
        ("收入吨公里（RTK）（百万）", "rtk"),
    ],
)
def test_classify_metric_header(header: str, expected: str) -> None:
    assert _scraper()._classify_metric_header(header) == expected


@pytest.mark.parametrize(
    "header",
    [
        "",
        "指标",
        "货运吨公里（RTK）",
        "载货量（吨）",
        "2026年6月",
    ],
)
def test_non_target_headers_are_not_classified(header: str) -> None:
    """Anything unrecognized must return None.

    The parser has no explicit ignore list -- an unrecognized header ends the
    active section. A false positive here would attach cargo values to a
    passenger metric.
    """
    assert _scraper()._classify_metric_header(header) is None


def test_region_order_matches_the_positional_inference_assumption() -> None:
    """The blank-label fallback infers region by position, so the order matters."""
    assert _scraper()._REGION_ORDER == ("Domestic", "International", "Regional")


def test_fleet_and_route_event_parser_keeps_events_separate_from_metrics() -> None:
    scraper = _scraper()
    text = (
        "本月引进 3 架 A320NEO、3 架 B737-8MAX、1 架 C909 飞机，"
        "退出 3 架 B737-800 飞机。截至2026年6月底，本集团合计运营 367 架飞机。"
        "新开海口=重庆=马德里航线。"
    )
    events = scraper.parse_airline_event_text(text, "600221", "2026-06")
    values = {row["event_type"]: row["value"] for row in events}
    assert values == {
        "fleet_added_aircraft": 7,
        "fleet_retired_aircraft": 3,
        "fleet_total_aircraft": 367,
        "new_route_event_count": 1,
    }
    assert all(set(row) == set(scraper.AIRLINE_EVENT_COLUMNS) for row in events)


def test_route_section_heading_is_not_counted_as_a_route_event() -> None:
    scraper = _scraper()
    assert scraper.parse_airline_event_text("新增主要航线情况。", "600029", "2019-06") == []


def test_route_event_parser_counts_numeric_route_disclosure() -> None:
    scraper = _scraper()
    events = scraper.parse_airline_event_text(
        "2016年6月下旬新开至圣彼得堡、布拉格、阿姆斯特丹及马德里4条欧洲航线。",
        "600115",
        "2016-06",
    )
    assert {row["event_type"]: row["value"] for row in events} == {
        "new_route_event_count": 4,
    }


def test_route_event_parser_records_explicit_no_route_as_zero() -> None:
    scraper = _scraper()
    events = scraper.parse_airline_event_text(
        "2017年2月，公司未新开航线。", "600115", "2017-02"
    )
    assert {row["event_type"]: row["value"] for row in events} == {
        "new_route_event_count": 0,
    }


def test_fleet_event_parser_uses_aircraft_table_total_not_freighter_subtotal() -> None:
    scraper = _scraper()
    text = (
        "飞机机队情况如下：货机合计 - 2 7 9。"
        "合 计 215 224 132 571。"
    )
    events = scraper.parse_airline_event_text(text, "600115", "2017-02")
    totals = [row for row in events if row["event_type"] == "fleet_total_aircraft"]
    assert [(row["value"], row["detail"]) for row in totals] == [(571, "合计 215 224 132 571")]


def test_fleet_table_total_precedes_parent_company_subtotal() -> None:
    scraper = _scraper()
    text = (
        "公司运营93架飞机。机队规模：自购 A320 35，融资租赁 A320 23，"
        "经营租赁 A320 35，合计 — 130。"
    )
    events = scraper.parse_airline_event_text(text, "603885", "2026-06")
    totals = [row for row in events if row["event_type"] == "fleet_total_aircraft"]
    assert [(row["value"], row["detail"]) for row in totals] == [(130, "合计 — 130")]


def test_rftk_unit_on_continuation_row_is_applied() -> None:
    scraper = _scraper()
    pdf = PDF_FIXTURE_DIR / "1203519532.PDF"
    rows = scraper.parse_airline_pdf(pdf.read_bytes(), "603885", "2017-04")
    rftk_total = [
        row["value"]
        for row in rows
        if row["metric"] == "rftk" and row["region"] == "Total"
    ]
    assert rftk_total == pytest.approx([11.4455])


def test_southern_2019_06_pdf_shift_recovery_restores_source_values() -> None:
    scraper = _scraper()
    pdf = ROOT / "data" / "raw" / "airline_pdfs" / "600029" / "1206446698.PDF"
    if not pdf.exists():
        pytest.skip(f"cached source PDF not present: {pdf}")
    rows = scraper.parse_airline_pdf(pdf.read_bytes(), "600029", "2019-06")
    values = {
        (row["metric"], row["region"]): row["value"]
        for row in rows
        if row.get("recovery_method")
    }
    assert values[("rpk", "Domestic")] == pytest.approx(15453.20)
    assert values[("rpk", "Regional")] == pytest.approx(314.09)
    assert values[("rpk", "International")] == pytest.approx(6995.79)
    assert values[("rpk", "Total")] == pytest.approx(22763.08)
    assert values[("ask", "Total")] == pytest.approx(27466.80)
    assert values[("cargo_tonnes", "Total")] == pytest.approx(141920.0)
    assert values[("passenger_load_factor_pct", "Total")] == pytest.approx(82.87)
    assert values[("overall_load_factor_pct", "Domestic")] == pytest.approx(64.50)


@pytest.mark.parametrize(
    ("code", "month", "filename", "metric", "expected_total"),
    [
        ("603885", "2019-12", "1207249027.PDF", "ask", 3421.0648),
        ("603885", "2020-02", "1207383601.PDF", "rpk", 667.4558),
    ],
)
def test_juneyao_page_split_ask_rpk_recovery(
    code: str,
    month: str,
    filename: str,
    metric: str,
    expected_total: float,
) -> None:
    scraper = _scraper()
    pdf = ROOT / "data" / "raw" / "airline_pdfs" / code / filename
    if not pdf.exists():
        pytest.skip(f"cached source PDF not present: {pdf}")
    rows = scraper.parse_airline_pdf(pdf.read_bytes(), code, month)
    metric_rows = [row for row in rows if row["metric"] == metric]
    assert {row["region"] for row in metric_rows} == {
        "Domestic", "International", "Regional", "Total",
    }
    assert sum(
        row["value"] for row in metric_rows if row["region"] != "Total"
    ) == pytest.approx(expected_total)
    assert next(row["value"] for row in metric_rows if row["region"] == "Total") == pytest.approx(expected_total)


@pytest.mark.parametrize(
    ("code", "month", "metric", "region", "expected"),
    [
        ("603885", "2020-12", "aftk", "Total", 93.5201),
        ("600115", "2025-05", "aftk", "Total", 854.54),
        ("601111", "2023-10", "rftk", "Total", 326.3),
        ("601021", "2016-04", "freight_load_factor_pct", "Domestic", 58.36),
    ],
)
def test_known_modern_and_column_shift_repairs_are_source_values(
    code: str, month: str, metric: str, region: str, expected: float
) -> None:
    scraper = _scraper()
    registry = pd.read_csv(
        ROOT / "data" / "normalized" / "hk_transport" / "airline_operating_release_registry.csv",
        dtype={"airline_code": str},
    )
    release = registry.loc[
        registry["airline_code"].astype(str).str.zfill(6).eq(code)
        & registry["month"].eq(month)
    ].iloc[0]
    pdf = ROOT / "data" / "raw" / "airline_pdfs" / code / f"{int(release['announcement_id'])}.PDF"
    if not pdf.exists():
        pytest.skip(f"cached source PDF not present: {pdf}")
    rows = scraper.parse_airline_pdf(pdf.read_bytes(), code, month)
    matches = [
        row for row in rows
        if row["metric"] == metric and row["region"] == region
    ]
    assert len(matches) == 1
    assert matches[0]["value"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("filename", "month"),
    [
        ("1216817425.PDF", "2023-04"),
        ("1217530839.PDF", "2023-07"),
        ("1220051128.PDF", "2024-04"),
        ("1222035427.PDF", "2024-11"),
    ],
)
def test_juneyao_split_passenger_header_preserves_region_rows(
    filename: str, month: str
) -> None:
    """A passenger header split across pages must not erase the next rows."""
    scraper = _scraper()
    pdf = PDF_FIXTURE_DIR / filename
    rows = scraper.parse_airline_pdf(pdf.read_bytes(), "603885", month)
    passengers = [row for row in rows if row["metric"] == "passengers"]
    assert {row["region"] for row in passengers} == {
        "Domestic", "International", "Regional",
    }


def test_juneyao_explicit_zero_regional_passenger_is_retained() -> None:
    """A source dash means zero service, not an absent observation."""
    scraper = _scraper()
    pdf = PDF_FIXTURE_DIR / "1212921911.PDF"
    rows = scraper.parse_airline_pdf(pdf.read_bytes(), "603885", "2022-03")
    regional = [
        row for row in rows
        if row["metric"] == "passengers" and row["region"] == "Regional"
    ]
    assert regional == [
        {
            "month": "2022-03",
            "date": "2022-03-01",
            "airline_code": "603885",
            "region": "Regional",
            "metric": "passengers",
            "value": 0.0,
        }
    ]


def test_event_parser_deduplicates_headline_fleet_totals_and_supports_spring_format() -> None:
    scraper = _scraper()
    text = (
        "本月引进8架飞机（包含3架A320、2架A321、1架B787、1架B737、1架C919），"
        "退出4架飞机（包含1架A321、1架B787、1架B737、1架B737）。"
        "本月新增4架空客A320neo飞机。截至本月末，公司共运营138架飞机。"
        "本月新增航线：深圳=雅加达、广州=雅加达。"
    )
    events = scraper.parse_airline_event_text(text, "601021", "2026-06")
    values = {row["event_type"]: row["value"] for row in events}
    assert values["fleet_added_aircraft"] == 8
    assert values["fleet_retired_aircraft"] == 4
    assert values["fleet_total_aircraft"] == 138
    assert values["new_route_event_count"] == 2


def test_cninfo_announcement_metadata_uses_china_local_publication_date() -> None:
    scraper = _scraper()
    metadata = scraper._announcement_metadata(
        {
            "announcement_id": "1225425218",
            "announcement_time_epoch_ms": 1784044800000,
            "title": "中国国际航空股份有限公司2026年6月主要运营数据公告",
            "url": "http://static.cninfo.com.cn/finalpage/2026-07-15/1225425218.PDF",
        },
        retrieved_at="2026-08-06T00:00:00+00:00",
    )
    assert metadata["announcement_date"] == "2026-07-15"
    assert metadata["announcement_time"].startswith("2026-07-15T00:00:00+08:00")
    assert metadata["announcement_id"] == "1225425218"
    assert metadata["source_quality"] == "issuer_cninfo_operating_release"


def test_china_eastern_queries_both_title_variants() -> None:
    """Cninfo's server-side searchkey filter is narrower than the client-side
    title check (which already accepts both "运营数据" and "经营数据") --
    querying only "运营数据" returned zero announcements for Dec 2016 - Mar
    2019, the exact window China Eastern titled its bulletin "经营数据"
    before reverting. Every carrier's searchkey must be a tuple so a rename
    like this can be covered by adding a variant, not swapping a string.
    """
    airlines = {a["name"]: a for a in _scraper().AIRLINES}
    for info in airlines.values():
        assert isinstance(info["searchkey"], tuple)
    assert "经营数据" in airlines["China Eastern"]["searchkey"]
    assert "运营数据" in airlines["China Eastern"]["searchkey"]


# --- invariants over the committed parquet ---


@pytest.fixture(scope="module")
def traffic() -> pd.DataFrame:
    if not PARQUET.exists():
        pytest.skip(f"{PARQUET} not present")
    return pd.read_parquet(PARQUET)


@pytest.fixture(scope="module")
def operating_events() -> pd.DataFrame:
    if not EVENT_PARQUET.exists():
        pytest.skip(f"{EVENT_PARQUET} not present")
    return pd.read_parquet(EVENT_PARQUET)


def test_operating_event_artifact_has_six_carrier_codes(operating_events: pd.DataFrame) -> None:
    assert set(operating_events.columns) == set(
        _scraper().AIRLINE_EVENT_COLUMNS + _scraper().PIT_METADATA_COLUMNS
    )
    assert set(operating_events["airline_code"]) == set(CARRIERS)
    assert set(operating_events["event_type"]).issubset({
        "fleet_added_aircraft", "fleet_retired_aircraft", "fleet_total_aircraft",
        "new_route_event_count",
    })
    assert (operating_events["value"] >= 0).all()


def test_no_load_factor_exceeds_100(traffic: pd.DataFrame) -> None:
    """A >100% load factor is the symptom the unit and dropped-row bugs produced."""
    lf = traffic[traffic["metric"] == "passenger_load_factor_pct"]
    over = lf[lf["value"] > 100]
    assert over.empty, (
        "load factor above 100%:\n"
        + over.assign(carrier=over["airline_code"].map(CARRIERS))[
            ["carrier", "month", "region", "value"]
        ].to_string(index=False)
    )


def test_rpk_never_exceeds_ask(traffic: pd.DataFrame) -> None:
    """Revenue passenger-km cannot exceed available seat-km for the same slice.

    This is the invariant a per-carrier unit-scale error breaks: scaling one of
    the two 100x relative to the other pushes the ratio past 1.
    """
    pivot = traffic[traffic["metric"].isin(["ask", "rpk"])].pivot_table(
        index=["airline_code", "month", "region"], columns="metric", values="value"
    )
    pivot = pivot.dropna(subset=["ask", "rpk"])
    violations = pivot[pivot["rpk"] > pivot["ask"]]
    assert violations.empty, f"RPK > ASK in {len(violations)} rows:\n{violations.head(10)}"


@pytest.mark.parametrize("code", sorted(CARRIERS))
def test_ask_per_passenger_is_plausible_for_every_carrier(
    traffic: pd.DataFrame, code: str
) -> None:
    """Cross-carrier sanity check on the ASK unit basis.

    Domestic ASK-per-passenger sits in a tight band across all four carriers
    (observed medians 1.73-1.95). Spring Airlines reports ASK/RPK in
    ten-thousands rather than millions, so if that unit conversion regresses
    its ratio jumps by ~100x while the other three stay put -- which no
    per-carrier assertion on absolute magnitude would catch.
    """
    domestic = traffic[(traffic["airline_code"] == code) & (traffic["region"] == "Domestic")]
    pivot = domestic.pivot_table(index="month", columns="metric", values="value")
    if not {"ask", "passengers"}.issubset(pivot.columns):
        pytest.skip(f"{CARRIERS[code]} has no Domestic ask/passengers overlap")
    ratio = (pivot["ask"] / pivot["passengers"]).dropna()
    assert not ratio.empty, f"no ASK/passenger overlap for {CARRIERS[code]}"
    median = float(ratio.median())
    assert 1.0 <= median <= 5.0, (
        f"{CARRIERS[code]} Domestic ASK per passenger median is {median:.2f}, outside 1.0-5.0 "
        "-- the ASK unit basis is probably wrong for this carrier"
    )


def test_merged_header_annotation_detection(traffic: pd.DataFrame) -> None:
    """The merged-header-annotation corruption check must not over-trigger.

    A China Eastern PDF (2023-06) line-wraps a passengers value mid-number
    inside its own header row's cell ("10,031.2\\n3" = "10,031.23"). That
    value is always discarded regardless (header rows never contribute their
    own row's figure), so it must not poison the correctly-labeled region
    rows below it -- unlike China Southern's 2019-06 case, where the merged
    cell holds actual unit-annotation text ("(ASK)(百万)") before the value,
    the real signal that the rows below are unsafe.
    """
    ce_passengers = traffic[
        (traffic["airline_code"] == "600115")
        & (traffic["month"] == "2023-06")
        & (traffic["metric"] == "passengers")
    ]
    assert set(ce_passengers["region"]) == {"Domestic", "International", "Regional"}, (
        "China Eastern 2023-06 passengers should have all 3 regions -- a "
        "regression here means the merged-annotation check is over-triggering "
        "on a benign mid-number line wrap"
    )


def test_china_eastern_fleet_history_has_table_totals_not_freighter_subtotals(
    operating_events: pd.DataFrame,
) -> None:
    totals = operating_events[
        (operating_events["airline_code"] == "600115")
        & (operating_events["event_type"] == "fleet_total_aircraft")
    ].sort_values("month")
    assert len(totals) == 115
    assert totals.iloc[0]["month"] == "2016-12"
    assert totals.iloc[0]["value"] == 581
    assert totals["value"].min() >= 500


def test_route_history_distinguishes_explicit_zero_from_undisclosed_month(
    operating_events: pd.DataFrame,
) -> None:
    routes = operating_events[
        (operating_events["airline_code"] == "600115")
        & (operating_events["event_type"] == "new_route_event_count")
    ]
    explicit_zero = routes[routes["month"] == "2017-02"]
    assert len(explicit_zero) == 1
    assert explicit_zero.iloc[0]["value"] == 0
    assert not routes["value"].isna().any()


# A source PDF can be present while one metric family used to be unsafe to
# recover. The repaired parser now recovers this South China block; the source
# recovery audit retains the PDF evidence and the raw layer's current parser
# refresh makes the recovered rows visible here.
KNOWN_UNRECOVERABLE_MONTHS: dict[str, dict[str, str]] = {}
KNOWN_PARSER_RECOVERABLE_METRICS: dict[str, dict[str, tuple[str, ...]]] = {
    "600029": {
        "2019-06": (
            "ask", "rpk", "passengers", "passenger_load_factor_pct",
        ),
    },
}


@pytest.mark.parametrize("code", sorted(CARRIERS))
def test_no_month_gap_in_carrier_history(traffic: pd.DataFrame, code: str) -> None:
    """No carrier should be missing a whole month's PDF within its own history,
    except the documented, deliberate exceptions in KNOWN_UNRECOVERABLE_MONTHS.

    An undocumented gap here is a discovery-level miss (Cninfo returned
    nothing for that month), distinct from a within-PDF extraction miss --
    China Eastern hit this when it renamed its bulletin title for a
    28-month stretch and the scraper only queried the old title.
    """
    months = sorted(traffic.loc[traffic["airline_code"] == code, "month"].unique())
    assert months, f"no data at all for {CARRIERS[code]}"
    expected = pd.period_range(months[0], months[-1], freq="M").astype(str)
    missing = sorted(set(expected) - set(months))
    known = set(KNOWN_UNRECOVERABLE_MONTHS.get(code, {}))
    unexpected = sorted(set(missing) - known)
    assert not unexpected, f"{CARRIERS[code]} is missing whole months: {unexpected}"
    assert known <= set(missing), (
        f"{CARRIERS[code]}: KNOWN_UNRECOVERABLE_MONTHS lists a month that isn't "
        "actually missing -- remove the stale entry"
    )


def test_repaired_metric_gaps_are_present_in_the_refreshed_parser_layer(
    traffic: pd.DataFrame,
) -> None:
    """Known parser gaps remain covered after the parser repair."""
    for code, month_map in KNOWN_PARSER_RECOVERABLE_METRICS.items():
        for month, metrics in month_map.items():
            observed = set(
                traffic.loc[
                    (traffic["airline_code"] == code) & (traffic["month"] == month),
                    "metric",
                ]
            )
            assert set(metrics) <= observed, (
                f"{CARRIERS[code]} {month}: repaired parser gap regressed; "
                f"re-audit the PDF: observed={sorted(observed)}"
            )


def test_juneyao_regional_history_distinguishes_pdf_blanks_from_explicit_zero(
    traffic: pd.DataFrame,
) -> None:
    juneyao = traffic[
        (traffic["airline_code"] == "603885")
        & (traffic["metric"] == "passengers")
        & traffic["month"].between("2021-01", "2025-12")
    ]
    # These source tables leave the Regional passenger cell blank; the
    # normalized layer must not invent a zero for an undisclosed value.
    for month in ("2021-02", "2021-05"):
        assert juneyao.loc[juneyao["month"] == month, "region"].tolist() == [
            "Domestic", "International",
        ]
    # The 2022-03 to 2022-07 PDFs explicitly print a dash for Regional
    # passengers, which is a reported zero and should remain visible.
    for month in ("2022-03", "2022-04", "2022-05", "2022-06", "2022-07"):
        regional = juneyao[
            (juneyao["month"] == month) & (juneyao["region"] == "Regional")
        ]
        assert len(regional) == 1
        assert regional.iloc[0]["value"] == 0.0
    for month in ("2023-04", "2023-07", "2024-04", "2024-11"):
        assert set(juneyao.loc[juneyao["month"] == month, "region"]) == {
            "Domestic", "International", "Regional",
        }
