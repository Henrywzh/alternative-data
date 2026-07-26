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
CARRIERS = {
    "601111": "Air China",
    "600029": "China Southern",
    "600115": "China Eastern",
    "601021": "Spring Airlines",
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


# --- metric header classification, including the mid-keyword line wrap ---


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("可用座位公里（百万）", "ask"),
        ("可利用座公里", "ask"),
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
    ],
)
def test_classify_metric_header(header: str, expected: str) -> None:
    assert _scraper()._classify_metric_header(header) == expected


@pytest.mark.parametrize(
    "header",
    [
        "",
        "指标",
        "可用货运吨公里（ATK）",  # cargo capacity: deliberately not a target metric
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


# --- invariants over the committed parquet ---


@pytest.fixture(scope="module")
def traffic() -> pd.DataFrame:
    if not PARQUET.exists():
        pytest.skip(f"{PARQUET} not present")
    return pd.read_parquet(PARQUET)


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
