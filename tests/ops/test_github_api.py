from __future__ import annotations

from urllib.error import HTTPError
from urllib.request import Request

from ops_control.github_api import request_bytes


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeHeaders(dict):
    def get_content_charset(self) -> str:  # pragma: no cover
        return "utf-8"


def test_artifact_zip_redirect_does_not_forward_github_bearer(monkeypatch) -> None:
    calls: list[str] = []

    def fake_urlopen(request: Request, timeout: int = 30):
        url = request.full_url
        auth = request.get_header("Authorization") or request.get_header("authorization")
        calls.append(f"{url}|{auth}")
        if url.startswith("https://api.github.com/"):
            raise HTTPError(
                url,
                302,
                "Found",
                _FakeHeaders({"Location": "https://objects.githubusercontent.com/signed.zip"}),
                fp=None,
            )
        assert auth in {None, ""}
        return _FakeResponse(b"PK\x03\x04artifact")

    monkeypatch.setattr("ops_control.github_api.urlopen", fake_urlopen)

    payload = request_bytes(
        "https://api.github.com/repos/Henrywzh/alternative-data/actions/artifacts/1/zip",
        token="ghs_test",
    )

    assert payload == b"PK\x03\x04artifact"
    assert calls[0].startswith("https://api.github.com/")
    assert "Bearer ghs_test" in calls[0]
    assert calls[1].startswith("https://objects.githubusercontent.com/")
    assert "Bearer" not in calls[1]
