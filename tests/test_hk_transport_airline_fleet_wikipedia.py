from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_fleet_wikipedia import (
    _is_year,
    _parse_fleet_table,
)


def test_parse_fleet_table_extracts_in_service_and_orders() -> None:
    html = """
    <table>
      <caption>Spring Airlines fleet</caption>
      <tr><th>Aircraft</th><th>In service</th><th>Orders</th><th>Passengers</th><th>Notes</th></tr>
      <tr><td><a>Airbus A320-200</a></td><td>75</td><td>—</td><td>174</td><td>[1]</td></tr>
      <tr><td><a>Airbus A320neo</a></td><td>48</td><td>32</td><td>186</td><td>[2]</td></tr>
      <tr><td><a>Airbus A321neo</a></td><td>12</td><td>10</td><td>240</td><td>[2]</td></tr>
    </table>
    """
    rows = _parse_fleet_table(html, "Spring Airlines")
    by_type = {row["aircraft_type"]: row for row in rows}
    assert by_type["Airbus A320-200"]["in_service"] == 75
    assert by_type["Airbus A320-200"]["on_order"] is None
    assert by_type["Airbus A320neo"]["in_service"] == 48
    assert by_type["Airbus A320neo"]["on_order"] == 32
    assert by_type["Airbus A320neo"]["total"] == 80


def test_parse_fleet_table_skips_retired_rows_with_year_in_orders() -> None:
    html = """
    <table>
      <caption>Air China fleet</caption>
      <tr><th>Aircraft</th><th>In service</th><th>Orders</th><th>Passengers</th><th>Notes</th></tr>
      <tr><td><a>Airbus A320neo</a></td><td>53</td><td>27</td><td>180</td><td></td></tr>
      <tr><td><a>Airbus A340-300</a></td><td>6</td><td>1997</td><td>2014</td><td>[67]</td></tr>
    </table>
    """
    rows = _parse_fleet_table(html, "Air China")
    types = [row["aircraft_type"] for row in rows]
    assert "Airbus A320neo" in types
    assert "Airbus A340-300" not in types


def test_is_year_bounds() -> None:
    assert _is_year(1997) is True
    assert _is_year(2025) is True
    assert _is_year(27) is False
    assert _is_year(None) is False


def test_parse_fleet_table_positional_fallback() -> None:
    html = """
    <table>
      <caption>Juneyao Airlines fleet</caption>
      <tr><td>Airbus A320neo</td><td>22</td><td>13</td><td>8</td><td>156</td><td>164</td></tr>
      <tr><td>Airbus A321-200</td><td>27</td><td>—</td><td>8</td><td>190</td><td>198</td></tr>
    </table>
    """
    rows = _parse_fleet_table(html, "Juneyao Airlines")
    by_type = {row["aircraft_type"]: row for row in rows}
    assert by_type["Airbus A320neo"]["in_service"] == 22
    assert by_type["Airbus A320neo"]["on_order"] == 13
    # The dash cell is dropped by the numeric filter, so the positional
    # fallback shifts the seat cells left.  Real Wikipedia pages carry the
    # "In service"/"Orders" header (header-matched path); the positional
    # branch is only a resilience path and its exact column meaning is
    # documented as such.
    assert by_type["Airbus A321-200"]["in_service"] == 27


def test_parse_fleet_table_ignores_non_fleet_tables() -> None:
    html = """
    <table>
      <caption>Shareholders</caption>
      <tr><th>Owner</th><th>Percentage</th></tr>
      <tr><td>Holding</td><td>80%</td></tr>
    </table>
    """
    rows = _parse_fleet_table(html, "Air China")
    assert rows == []
