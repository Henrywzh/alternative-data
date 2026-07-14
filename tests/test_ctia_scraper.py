from __future__ import annotations

import json
import os
import time

from bs4 import BeautifulSoup
from minerals_signal_data.chinatungsten_scraper import (
    _get_ctia_url,
    clean_chinese_val,
    extract_tungsten_chinese,
    extract_molybdenum_chinese,
    _parse_rare_earth_ocr,
    _find_ctia_price_image_url,
    _parse_chinese_moly_ocr,
)


def test_clean_chinese_val() -> None:
    assert clean_chinese_val("41.5", "万元/标吨") == 415000.0
    assert clean_chinese_val("980", "元/千克") == 980.0
    assert clean_chinese_val("5,280", "元/吨度") == 5280.0
    assert clean_chinese_val("333,000", "元/吨") == 333000.0
    assert clean_chinese_val("", "元/吨") == ""


def test_extract_tungsten_chinese() -> None:
    html = """
    <p>65%黑钨精矿价格41.5万元/标吨，自高位回落60.5%，较年初跌9.8%。</p>
    <p>65%白钨精矿价格41.4万元/标吨，较年初跌9.8%。</p>
    <p>仲钨酸铵（APT）价格60万元/吨，较年初跌10.5%。</p>
    <p>欧洲APT价格3000-3265美元/吨度（折合人民币179.9-195.8万元/吨）。</p>
    <p>钨粉价格980元/千克，碳化钨粉价格930元/千克。</p>
    <p>钴粉价格485元/千克，70钨铁价格67万元/吨，废钨棒材价格735元/千克。</p>
    """
    res = extract_tungsten_chinese(html)
    assert res["wolframite_concentrate"] == 415000.0
    assert res["scheelite_concentrate"] == 414000.0
    assert res["apt"] == 600000.0
    assert res["european_apt"] == 3000.0
    assert res["tungsten_powder"] == 980.0
    assert res["tungsten_carbide_powder"] == 930.0
    assert res["ferrotungsten"] == 670000.0
    assert res["cobalt_powder"] == 485.0
    assert res["scrap_carbide_rod"] == 735.0


def test_extract_molybdenum_chinese_respectively() -> None:
    html = """
    <p>今日，钼精矿、钼铁与七钼酸铵价格分别约为5,280元/吨度、333,000元/吨和326,000元/吨。</p>
    """
    res = extract_molybdenum_chinese(html)
    assert res["molybdenum_concentrate"] == 5280.0
    assert res["ferromolybdenum"] == 333000.0
    assert res["ammonium_heptamolybdate"] == 326000.0
    assert res["ammonium_tetramolybdate"] == ""


def test_extract_molybdenum_chinese_direct() -> None:
    html = """
    <p>钼精矿市场上，商家报价在5,180元/吨度左右。</p>
    <p>钼铁价格在31.8万元/吨度左右，或者说钼铁报价在318,000元/吨左右。</p>
    """
    res = extract_molybdenum_chinese(html)
    assert res["molybdenum_concentrate"] == 5180.0
    assert res["ferromolybdenum"] == 318000.0


def test_parse_rare_earth_ocr() -> None:
    ocr_text = (
        "La2O3/TREO 99.5-99.9% 5,800.00 =\n"
        "Eu203/TREO 99.95-99.99% 175.00 =\n"
        "Pr6O11/TREO 99.0-99.9% 820,000.00 =\n"
        "Nd203/TREO 99.0-99.9% 815,000.00 =\n"
        "Tb407/TREO 99.95-99.99% 7,000,000.00 =\n"
        "Dy203/TREO 99.5-99.9% 1,420,000.00 =\n"
    )
    res = _parse_rare_earth_ocr(ocr_text)
    assert res["lanthanum_oxide"] == 5800.0
    assert res["europium_oxide"] == 175000.0
    assert res["praseodymium_oxide"] == 820000.0
    assert res["neodymium_oxide"] == 815000.0
    assert res["terbium_oxide"] == 7000000.0
    assert res["dysprosium_oxide"] == 1420000.0
    assert res["yttrium_oxide"] == ""


def test_find_ctia_price_image_url() -> None:
    html = """
    <div>
      <img src="http://www.ctia.com.cn/wp-content/uploads/2026/07/rare-earth-price-trend-0713.jpg" alt="trend">
      <img src="http://www.ctia.com.cn/wp-content/uploads/2026/07/rare-earth-price-picture-07131.jpg" alt="price">
    </div>
    """
    url = _find_ctia_price_image_url(html, ["rare-earth-price", "稀土价格"])
    assert url == "http://www.ctia.com.cn/wp-content/uploads/2026/07/rare-earth-price-picture-07131.jpg"


def test_parse_chinese_moly_ocr() -> None:
    ocr_text = (
        "Bek Mo60 245,000.00 t 1,000 ar\n"
        "Hie 40-45% 3,730.00 = TEE\n"
        "ia) 298% 174,000.00 t 1,000 FE\n"
        "3g | DOHBSER RS 234,000.00 t 1,000 Fen\n"
        "| CHR RS 239,000.00 t 1,000 Fen\n"
    )
    res = _parse_chinese_moly_ocr(ocr_text)
    assert res["molybdenum_concentrate"] == 3730.0
    assert res["ferromolybdenum"] == 245000.0
    assert res["ammonium_tetramolybdate"] == 234000.0
    assert res["ammonium_heptamolybdate"] == 239000.0


def test_ctia_cache_expires_for_all_pages(tmp_path) -> None:
    class Response:
        status_code = 200

        def json(self):
            return [{"fresh": True}]

    class Session:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url, timeout):
            self.calls += 1
            return Response()

    url = "https://www.ctia.com.cn/wp-json/wp/v2/posts?categories=18&per_page=10&page=2"
    cache_file = tmp_path / "stale.json"
    cache_file.write_text(json.dumps([{"stale": True}]), encoding="utf-8")
    os.utime(cache_file, (time.time() - 7200, time.time() - 7200))

    # Match the production cache filename without depending on its implementation.
    import hashlib

    expected_cache_file = tmp_path / f"{hashlib.md5(url.encode('utf-8')).hexdigest()}.json"
    cache_file.replace(expected_cache_file)
    session = Session()

    assert _get_ctia_url(session, url, cache_dir=tmp_path) == [{"fresh": True}]
    assert session.calls == 1
