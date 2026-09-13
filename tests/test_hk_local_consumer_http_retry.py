"""Transient transport failures must not fail a strict ingest.

On 2026-09-13 the FEHD licensed-premises fetch died with

    requests.exceptions.ChunkedEncodingError: Response ended prematurely

while reading a 4.8 MB chunked XML body. It had no retry, so one dropped
connection failed the whole `--strict` stage-1 ingest, degraded the Asia
Markets dashboard refresh to DEGRADED_RETAINED, and opened a NEEDS_HUMAN
incident.

The important property is that the body read is inside the retry loop. An
adapter-level urllib3.Retry does not cover a body that dies mid-transfer --
requests raises out of send(), past where the adapter could act -- so a test
that only simulates a connection error would pass against the broken code.
"""

from __future__ import annotations

import pytest
import requests

from hk_local_consumer.http import get_with_retry


class _Response:
    def __init__(self, *, body: bytes = b"<ok/>", raise_on_content: Exception | None = None):
        self._body = body
        self._raise_on_content = raise_on_content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    @property
    def content(self) -> bytes:
        if self._raise_on_content is not None:
            raise self._raise_on_content
        return self._body


def _sessions(monkeypatch, responses):
    """Make each attempt return the next scripted response."""
    calls = {"n": 0}

    class _Session:
        def get(self, url, **kwargs):
            index = calls["n"]
            calls["n"] += 1
            item = responses[index]
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr("hk_local_consumer.http._session", lambda: _Session())
    return calls


def test_a_body_that_dies_mid_transfer_is_retried(monkeypatch) -> None:
    # The exact production failure: the response arrives, then the body ends.
    calls = _sessions(
        monkeypatch,
        [
            _Response(raise_on_content=requests.exceptions.ChunkedEncodingError(
                "Response ended prematurely"
            )),
            _Response(body=b"<recovered/>"),
        ],
    )

    response = get_with_retry("https://example.test/big.xml", sleep=lambda _: None)

    assert response.content == b"<recovered/>"
    assert calls["n"] == 2


def test_a_connection_error_is_retried(monkeypatch) -> None:
    calls = _sessions(
        monkeypatch,
        [requests.exceptions.ConnectionError("reset"), _Response(body=b"<ok/>")],
    )

    assert get_with_retry("https://example.test/x", sleep=lambda _: None).content == b"<ok/>"
    assert calls["n"] == 2


def test_it_gives_up_and_raises_the_last_error(monkeypatch) -> None:
    # Retrying forever would hang the pipeline; a source that is really down
    # must still fail, and fail with the reason.
    boom = requests.exceptions.ChunkedEncodingError("Response ended prematurely")
    calls = _sessions(monkeypatch, [_Response(raise_on_content=boom)] * 3)

    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        get_with_retry("https://example.test/x", attempts=3, sleep=lambda _: None)

    assert calls["n"] == 3


def test_a_first_attempt_success_does_not_retry(monkeypatch) -> None:
    calls = _sessions(monkeypatch, [_Response(body=b"<ok/>")])

    assert get_with_retry("https://example.test/x", sleep=lambda _: None).content == b"<ok/>"
    assert calls["n"] == 1


def test_the_backoff_grows_between_attempts(monkeypatch) -> None:
    slept: list[float] = []
    _sessions(
        monkeypatch,
        [
            requests.exceptions.ConnectionError("a"),
            requests.exceptions.ConnectionError("b"),
            _Response(body=b"<ok/>"),
        ],
    )

    get_with_retry("https://example.test/x", backoff_seconds=1.0, sleep=slept.append)

    assert slept == [1.0, 2.0]


def test_the_fehd_source_goes_through_the_retry_path(monkeypatch) -> None:
    # The fix only helps if the caller actually uses it.
    import hk_local_consumer.sources.fehd_licensed_premises as fehd

    seen: dict[str, str] = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        raise RuntimeError("stop here -- the call path is what is under test")

    monkeypatch.setattr(fehd, "get_with_retry", fake_get)
    with pytest.raises(RuntimeError):
        fehd.fetch_fehd_licensed_premises()

    assert seen["url"] == fehd.FEHD_RESTAURANTS_XML_URL


# --- no source may fetch without retries ----------------------------------


def test_no_source_fetches_without_retries() -> None:
    """`--strict` makes every source fatal, so one bare GET is a daily outage.

    run_stage_1_pipeline has no required/optional split: any dataset failure
    raises. With a dozen sources against free public endpoints, a single
    un-retried fetch is enough to keep the Asia Markets refresh permanently in
    DEGRADED_RETAINED and its incident permanently open -- which is how a real
    alert becomes background noise.
    """
    import re
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "src" / "hk_local_consumer"
    offenders = []
    for path in sorted(package.rglob("*.py")):
        if path.name == "http.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\brequests\.(get|post)\s*\(", line):
                offenders.append(f"{path.relative_to(package)}:{number}")

    assert not offenders, (
        "these fetch without retries; route them through "
        "hk_local_consumer.http.get_with_retry: " + ", ".join(offenders)
    )
