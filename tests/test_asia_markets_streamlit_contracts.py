"""Smoke tests for Streamlit pages against published artifact contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "apps" / "asia-markets-streamlit" / "app.py"


@pytest.mark.parametrize("page", ["transport", "crypto"])
@pytest.mark.parametrize("language_choice", ["English", "中文"])
def test_transport_and_crypto_pages_render_when_optional_data_is_missing(
    page: str, language_choice: str
) -> None:
    app = AppTest.from_file(str(APP_PATH), default_timeout=120)
    app.session_state["page"] = page
    app.session_state["language_choice"] = language_choice
    app.run()

    assert not app.exception, [str(error) for error in app.exception]
