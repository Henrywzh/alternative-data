from __future__ import annotations

import pandas as pd

import dashboard.sections.minerals as minerals


class _FakeColumn:
    def __init__(self, store: list[tuple[str, str]]) -> None:
        self._store = store

    def __enter__(self) -> "_FakeColumn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def metric(self, label: str, value: object, **kwargs) -> None:
        self._store.append((label, str(value)))


class _FakeStreamlit:
    def __init__(self) -> None:
        self.captions: list[str] = []
        self.metrics: list[tuple[str, str]] = []
        self.selectbox_options: list[str] = []
        self.multiselect_calls: list[dict[str, object]] = []
        self.figures = []

    def markdown(self, *args, **kwargs) -> None:
        return None

    def caption(self, text: str) -> None:
        self.captions.append(text)

    def warning(self, text: str) -> None:
        self.captions.append(text)

    def info(self, text: str) -> None:
        self.captions.append(text)

    def columns(self, spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn(self.metrics) for _ in range(count)]

    def selectbox(self, label: str, options, index: int = 0):
        self.selectbox_options = list(options)
        return options[index]

    def multiselect(self, label: str, options, default=None, format_func=None):
        self.multiselect_calls.append(
            {"label": label, "options": list(options), "default": list(default or [])}
        )
        return list(default or [])

    def plotly_chart(self, figure, **kwargs) -> None:
        self.figures.append(figure)


def test_render_minerals_section_uses_live_selector_and_proxy_labels(monkeypatch) -> None:
    fake_st = _FakeStreamlit()
    price_universe = pd.DataFrame(
        [
            {
                "normalized_mineral_id": "graphite",
                "mineral_name": "Graphite",
                "trackability_grade": "proxy",
                "price_source_type": "yfinance_futures",
                "price_symbol_or_series_id": "LIT",
                "price_currency": "USD",
                "price_unit": "etf_share",
                "publish_lag_assumption_days": 2,
                "is_active_for_v1": True,
                "proxy_target": "lithium",
                "proxy_type": "etf",
                "proxy_instrument": "LIT",
                "proxy_display_name": "Global X Lithium & Battery Tech ETF",
            }
        ]
    )
    mineral_prices = pd.DataFrame(
        [
            {"date": "2025-01-02", "normalized_mineral_id": "graphite", "mineral_name": "Graphite", "price": 50.0},
            {"date": "2025-01-03", "normalized_mineral_id": "graphite", "mineral_name": "Graphite", "price": 52.0},
        ]
    )
    tungsten_prices = pd.DataFrame(
        [
            {"date": "2025-01-03", "apt": 300000.0, "wolframite_concentrate": 120000.0, "ferrotungsten": 210000.0}
        ]
    )
    molybdenum_prices = pd.DataFrame(
        [
            {"date": "2025-01-03", "molybdenum_concentrate": 2500.0, "ferromolybdenum": 150000.0}
        ]
    )
    stock_mapping = pd.DataFrame(
        [
            {
                "normalized_mineral_id": "graphite",
                "ticker_normalized": "NMG",
                "market": "US",
                "is_primary_exposure": True,
            }
        ]
    )
    stock_prices = pd.DataFrame(
        [
            {"ticker_normalized": "NMG", "market": "US", "date": "2025-01-02", "adj_close": 10.0},
            {"ticker_normalized": "NMG", "market": "US", "date": "2025-01-03", "adj_close": 10.5},
        ]
    )

    datasets = {
        "mineral_price_universe_live": price_universe,
        "mineral_price_series_daily": mineral_prices,
        "tungsten_price_daily": tungsten_prices,
        "molybdenum_price_daily": molybdenum_prices,
        "stock_mapping_expanded_live": stock_mapping,
        "stock_price_series_daily": stock_prices,
    }

    monkeypatch.setattr(minerals, "st", fake_st)
    monkeypatch.setattr(minerals, "_load_minerals_csv", lambda dataset: datasets.get(dataset, pd.DataFrame()))

    minerals.render_minerals_section()

    assert "Graphite" in fake_st.selectbox_options
    assert "Tungsten" in fake_st.selectbox_options
    assert "Molybdenum" in fake_st.selectbox_options
    assert "Cobalt" not in fake_st.selectbox_options
    assert ("Proxy type", "Etf") in fake_st.metrics
    assert ("Tracked instrument", "LIT") in fake_st.metrics
    assert any("Global X Lithium & Battery Tech ETF" in caption for caption in fake_st.captions)
    assert not any("bullish" in caption.lower() for caption in fake_st.captions)
    assert fake_st.figures
    assert all(trace.name != "Bullish week" for trace in fake_st.figures[0].data)
    assert fake_st.figures[0].layout.xaxis.range == fake_st.figures[1].layout.xaxis.range
