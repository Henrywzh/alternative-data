from __future__ import annotations

from bs4 import BeautifulSoup

from minerals_signal_data.chinatungsten_scraper import (
    clean_value,
    extract_prices_from_body,
    parse_date_from_article,
    extract_molybdenum_prices_from_body,
    _parse_ocr_text,
)


def test_clean_value_handles_commas_dollar_and_million() -> None:
    assert clean_value("790,000") == 790000.0
    assert clean_value("$2,900") == 2900.0
    assert clean_value("1.5 million") == 1500000.0
    assert clean_value("RMB 1.480,000") == 1480000.0  # dot-thousands separator
    assert clean_value("") == ""
    assert clean_value("n/a") == ""


def test_extract_prices_from_body_pulls_key_series() -> None:
    body = (
        "China's APT price was RMB 790,000/tonne. "
        "65% wolframite concentrate is priced at RMB 520,000/tonne. "
        "65% scheelite concentrate: RMB 519,000/tonne. "
        "European APT was USD 2,900/mtu. "
        "Ferrotungsten price rose to RMB 780,000/tonne."
    )
    prices = extract_prices_from_body(body)
    assert prices["apt"] == 790000.0
    assert prices["wolframite_concentrate"] == 520000.0
    assert prices["scheelite_concentrate"] == 519000.0
    assert prices["european_apt"] == 2900.0
    assert prices["ferrotungsten"] == 780000.0
    # series not mentioned should come back empty, not error
    assert prices["cobalt_powder"] == ""


def test_parse_date_from_published_meta() -> None:
    html = """
    <dd class="published"><span>Wednesday, 25 June 2026 10:30</span></dd>
    <h2 class="contentheading">Tungsten Prices Stagnant</h2>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert parse_date_from_article(soup, "Tungsten Prices Stagnant") == "2026-06-25"


def test_parse_date_falls_back_to_title() -> None:
    soup = BeautifulSoup("<div>no meta here</div>", "html.parser")
    assert parse_date_from_article(soup, "Tungsten and Cobalt Prices Decline - June 18, 2026") == "2026-06-18"
    # "June. 18, 2026" abbreviated form
    assert parse_date_from_article(soup, "APT Update - June. 18, 2026") == "2026-06-18"


def test_parse_date_returns_empty_when_unresolvable() -> None:
    soup = BeautifulSoup("<div>no date anywhere</div>", "html.parser")
    assert parse_date_from_article(soup, "Generic tungsten market commentary") == ""


def test_extract_molybdenum_prices_from_body() -> None:
    # A typical molybdenum price announcement sentence with 'respectively'
    body = (
        "China molybdenum prices were mixed on June 25, 2026, when molybdenum concentrate, "
        "ferromolybdenum and ammonium heptamolybdate prices were RMB 4,710/ton-degree, "
        "RMB 315,000/ton and RMB 305,000/ton, respectively."
    )
    prices = extract_molybdenum_prices_from_body(body)
    assert prices["molybdenum_concentrate"] == 4710.0
    assert prices["ferromolybdenum"] == 315000.0
    assert prices["ammonium_heptamolybdate"] == 305000.0
    assert prices["ammonium_tetramolybdate"] == ""


def test_parse_ocr_text_extracts_and_corrects() -> None:
    # Real-world OCR text containing typical errors and units
    ocr_text = (
        "Ferro Molybdenum 60% 4794.12 USD/MT\n"
        "Molybdenum Concentrate | 40-45% 761.76 USDIMTU\n"
        "Ammonium Heptamotvbdate | Grade 1 4705882 USD/MT\n"
    )
    prices = _parse_ocr_text(ocr_text)
    
    # Expected calculations (raw_val * 6.80, with correction multiplier/divisor and rounding):
    # - Molybdenum concentrate: 761.76 * 6.8 = 5179.968 => 5180.0
    # - Ferromolybdenum: 4794.12 * 10 (since < 10000) = 47941.2 * 6.8 = 325999.96 => 326000.0
    # - Ammonium heptamolybdate: 4705882 / 100 = 47058.82 * 6.8 = 319999.976 => 320000.0
    
    assert prices["molybdenum_concentrate"] == 5180.0
    assert prices["ferromolybdenum"] == 326000.0
    assert prices["ammonium_heptamolybdate"] == 320000.0
    assert prices["ammonium_tetramolybdate"] is None
