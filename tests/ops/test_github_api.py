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


class _FakeOpener:
    def __init__(self, handler) -> None:
        self.handler = handler

    def open(self, request: Request, timeout: int = 30):
        return _github_open(request, timeout)


def _github_open(request: Request, timeout: int = 30):
    url = request.full_url
    auth = request.get_header("Authorization") or request.get_header("authorization")
    CALLS.append(f"{url}|{auth}")
    raise HTTPError(
        url,
        302,
        "Found",
        _FakeHeaders({"Location": "https://objects.githubusercontent.com/signed.zip"}),
        fp=None,
    )


CALLS: list[str] = []


def test_artifact_zip_redirect_does_not_forward_github_bearer(monkeypatch) -> None:
    CALLS.clear()

    def fake_urlopen(request: Request, timeout: int = 30):
        url = request.full_url
        auth = request.get_header("Authorization") or request.get_header("authorization")
        CALLS.append(f"{url}|{auth}")
        assert url.startswith("https://objects.githubusercontent.com/")
        assert auth in {None, ""}
        return _FakeResponse(b"PK\x03\x04artifact")

    monkeypatch.setattr(
        "ops_control.github_api.urllib.request.build_opener",
        lambda *args, **kwargs: _FakeOpener(args[0] if args else None),
    )
    monkeypatch.setattr("ops_control.github_api.urlopen", fake_urlopen)

    payload = request_bytes(
        "https://api.github.com/repos/Henrywzh/alternative-data/actions/artifacts/1/zip",
        token="ghs_test",
    )

    assert payload == b"PK\x03\x04artifact"
    assert CALLS[0].startswith("https://api.github.com/")
    assert "Bearer ghs_test" in CALLS[0]
    assert CALLS[1].startswith("https://objects.githubusercontent.com/")
    assert "Bearer" not in CALLS[1]
