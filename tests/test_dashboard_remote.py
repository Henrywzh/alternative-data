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


def test_sidecar_parquet_is_fetched_at_the_pinned_sha(tmp_path, monkeypatch) -> None:
    """Sidecars must follow the pinned commit, not the frozen local checkout.

    A Streamlit Cloud container runs against a checkout frozen at the last
    deploy.  A sidecar read from disk there shows whatever was true when the
    container started and never moves again -- and a stale parquet reads exactly
    like a fresh one, so the catalog silently stops updating until a reboot.
    """
    import io

    import pandas as pd

    from dashboard.data import load_sidecar_parquet

    stale = tmp_path / "data" / "normalized" / "compute_availability"
    stale.mkdir(parents=True)
    pd.DataFrame([{"model_id": "stale-model"}]).to_parquet(
        stale / "raw_openrouter_models_current.parquet", index=False
    )

    fresh = io.BytesIO()
    pd.DataFrame([{"model_id": "fresh-model"}]).to_parquet(fresh, index=False)

    requested: list[tuple[str, str]] = []

    def _fetch(rel_path: str, sha: str):
        requested.append((rel_path, sha))
        return fresh.getvalue()

    monkeypatch.setattr("dashboard.data.remote.remote_enabled", lambda: True)
    monkeypatch.setattr("dashboard.data.remote.fetch_bytes", _fetch)

    frame = load_sidecar_parquet.__wrapped__(
        "raw_openrouter_models",
        "raw_openrouter_models_current.parquet",
        tmp_path,
        (),
        data_sha="deadbeef",
    )

    assert requested == [
        (
            "data/normalized/compute_availability/raw_openrouter_models_current.parquet",
            "deadbeef",
        )
    ]
    assert list(frame["model_id"]) == ["fresh-model"]


def test_sidecar_parquet_falls_back_to_the_local_checkout(tmp_path, monkeypatch) -> None:
    """A sidecar that is not committed yet must still resolve locally."""
    import pandas as pd

    from dashboard.data import load_sidecar_parquet

    local = tmp_path / "data" / "normalized" / "compute_availability"
    local.mkdir(parents=True)
    pd.DataFrame([{"model_id": "local-model"}]).to_parquet(
        local / "openrouter_catalog_size.parquet", index=False
    )

    monkeypatch.setattr("dashboard.data.remote.remote_enabled", lambda: True)
    monkeypatch.setattr("dashboard.data.remote.fetch_bytes", lambda *_a, **_k: None)

    frame = load_sidecar_parquet.__wrapped__(
        "raw_openrouter_models",
        "openrouter_catalog_size.parquet",
        tmp_path,
        (),
        data_sha="deadbeef",
    )

    assert list(frame["model_id"]) == ["local-model"]


def test_missing_sidecar_is_an_empty_frame_not_an_error(tmp_path, monkeypatch) -> None:
    """Absence is a normal state: the caller derives the value the long way."""
    from dashboard.data import load_sidecar_parquet

    monkeypatch.setattr("dashboard.data.remote.remote_enabled", lambda: False)

    frame = load_sidecar_parquet.__wrapped__(
        "raw_openrouter_models", "nope.parquet", tmp_path, (), data_sha=None
    )

    assert frame.empty
