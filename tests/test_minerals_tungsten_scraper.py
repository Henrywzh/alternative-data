from __future__ import annotations

from bs4 import BeautifulSoup

from minerals_signal_data.chinatungsten_scraper import (
    MOLY_PRICE_FIELDS,
    clean_value,
    extract_prices_from_body,
    parse_date_from_article,
    extract_molybdenum_prices_from_body,
    _parse_ocr_text,
    _find_molybdenum_price_image_url,
    _run_tesseract_ocr,
    scrape_range,
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


def test_extract_molybdenum_prices_from_direct_product_pairs() -> None:
    body = (
        "Molybdenum concentrate price is RMB 5,180/ton-degree today. "
        "Ferromolybdenum price is around RMB 325,000/ton. "
        "Ammonium hepta-molybdate price is RMB 320,000 per ton. "
        "Ammonium tetra-molybdate price is RMB 316,000/ton."
    )
    prices = extract_molybdenum_prices_from_body(body)
    assert prices["molybdenum_concentrate"] == 5180.0
    assert prices["ferromolybdenum"] == 325000.0
    assert prices["ammonium_heptamolybdate"] == 320000.0
    assert prices["ammonium_tetramolybdate"] == 316000.0


def test_extract_molybdenum_prices_ignores_monthly_change_amounts() -> None:
    body = (
        "In the first half of May 2026, the price of molybdenum concentrate rose by "
        "approximately 490 RMB per ton-degree, an increase of 10.29%; the price of "
        "ferromolybdenum rose by approximately 35,000 RMB per ton, an increase of 11.67%."
    )
    prices = extract_molybdenum_prices_from_body(body)
    assert prices == {field: "" for field in MOLY_PRICE_FIELDS}


def test_find_molybdenum_price_image_prefers_price_picture_over_trend_chart() -> None:
    html = """
    <div class="item-page">
      <img src="/images/molybdenum-price-trend-chart.jpg" alt="Molybdenum price trend chart">
      <img src="/images/molybdenum-price-picture-06242.jpg" alt="Molybdenum price picture on June 24, 2026">
      <img src="/images/molybdenum-sheet-picture-0624.jpg" alt="Image of molybdenum sheet">
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    assert _find_molybdenum_price_image_url(soup) == (
        "http://news.chinatungsten.com/images/molybdenum-price-picture-06242.jpg"
    )


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


def test_run_tesseract_ocr_tolerates_non_utf8_output(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "moly.jpg"
    image_path.write_bytes(b"fake-image")

    def fake_run(*args, **kwargs):  # noqa: ANN001, ARG001
        assert kwargs["errors"] == "replace"
        image_path.with_suffix(".txt").write_bytes(
            b"\xffFerro Molybdenum 60% 4794.12 USD/MT\n"
            b"Molybdenum Concentrate | 40-45% 761.76 USDIMTU\n"
        )

        class Result:
            returncode = 0

        return Result()

    monkeypatch.setattr("minerals_signal_data.chinatungsten_scraper.subprocess.run", fake_run)

    prices = _run_tesseract_ocr(image_path)
    assert prices["molybdenum_concentrate"] == 5180.0
    assert prices["ferromolybdenum"] == 326000.0


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.content = text.encode("utf-8")


class _FakeSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str, timeout: int) -> _FakeResponse:  # noqa: ARG002
        self.requested.append(url)
        return _FakeResponse(self.pages[url])


def test_scrape_range_since_date_skips_older_articles(tmp_path) -> None:
    category_html = """
    <div class="contentpaneopen">
      <h2 class="contentheading">
        <a href="/en/tungsten-product-news/new.html">Molybdenum Market - June 25, 2026</a>
      </h2>
    </div>
    <div class="contentpaneopen">
      <h2 class="contentheading">
        <a href="/en/tungsten-product-news/old.html">Molybdenum Market - May 1, 2026</a>
      </h2>
    </div>
    """
    new_article = """
    <h2 class="contentheading">Molybdenum Market - June 25, 2026</h2>
    <dd class="published"><span>Thursday, 25 June 2026 16:36</span></dd>
    <div class="item-page">
      Today, molybdenum concentrate price is RMB 5,180/ton-degree.
    </div>
    """
    old_article = """
    <h2 class="contentheading">Molybdenum Market - May 1, 2026</h2>
    <dd class="published"><span>Friday, 01 May 2026 16:36</span></dd>
    <div class="item-page">
      Today, molybdenum concentrate price is RMB 5,000/ton-degree.
    </div>
    """
    session = _FakeSession(
        {
            "http://news.chinatungsten.com/en/tungsten-product-news.html": category_html,
            "http://news.chinatungsten.com/en/tungsten-product-news/new.html": new_article,
            "http://news.chinatungsten.com/en/tungsten-product-news/old.html": old_article,
        }
    )

    scrape_range(tmp_path, max_pages=1, session=session, since_date="2026-06-01")

    assert "http://news.chinatungsten.com/en/tungsten-product-news/new.html" in session.requested
    assert "http://news.chinatungsten.com/en/tungsten-product-news/old.html" in session.requested

    moly_csv = tmp_path / "data/raw/minerals_signal_data/molybdenum_chinatungsten.csv"
    rows = moly_csv.read_text(encoding="utf-8")
    assert "2026-06-25" in rows
    assert "2026-05-01" not in rows
