from __future__ import annotations

from bs4 import BeautifulSoup

from minerals_signal_data.chinatungsten_scraper import (
    clean_value,
    extract_prices_from_body,
    parse_date_from_article,
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
