from __future__ import annotations

from dashboard import remote


def test_latest_data_sha_falls_back_when_streamlit_cache_raises(monkeypatch) -> None:
    def fail_cache(_path_prefix: str) -> str | None:
        raise TypeError("cache materialization failed")

    monkeypatch.setattr(remote, "_latest_data_sha_cached", fail_cache)

    assert remote.latest_data_sha("data/normalized/openrouter") is None


def test_fetch_bytes_falls_back_when_streamlit_cache_raises(monkeypatch) -> None:
    def fail_cache(_rel_path: str, _sha: str) -> bytes | None:
        raise TypeError("cache materialization failed")

    monkeypatch.setattr(remote, "_fetch_bytes_cached", fail_cache)

    assert remote.fetch_bytes("data/normalized/openrouter/example.parquet", "abc123") is None
