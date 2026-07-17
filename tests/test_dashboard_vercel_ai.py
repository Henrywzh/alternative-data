from __future__ import annotations

from pathlib import Path

from dashboard.data import (
    dataset_source_for_domain,
    domain_dataset_ids,
    load_domain_datasets,
)
from dashboard.sections.vercel_ai import (
    _available_metrics,
    _pivot,
    compute_vercel_ai_views,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_vercel_ai_domain_registered() -> None:
    assert dataset_source_for_domain("vercel_ai") == "vercel_ai"
    assert "vercel_model_leaderboard" in domain_dataset_ids("vercel_ai")


def test_leaderboard_loads_with_custom_columns_intact() -> None:
    """The generic loader filters to EXPECTED_COLUMNS; the VERCEL_AI_LOAD_COLUMNS
    override must keep share_percent/metric/modality from being dropped."""
    datasets = load_domain_datasets("vercel_ai", base_dir=REPO_ROOT)
    result = datasets["vercel_model_leaderboard"]
    assert not result.frame.empty
    for column in ("date", "name", "metric", "modality", "share_percent"):
        assert column in result.frame.columns
    assert "tokens" in set(result.frame["metric"])


def test_compute_views_builds_entity_frames_and_kpis() -> None:
    datasets = load_domain_datasets("vercel_ai", base_dir=REPO_ROOT)
    views = compute_vercel_ai_views(datasets)

    frames = views["frames"]
    assert not frames["Top Models"].empty
    assert not frames["Top Labs"].empty

    kpis = views["kpis"]["Top Models"]
    assert kpis["leader"]
    assert 0.0 <= kpis["share"] <= 100.5


def test_modality_and_metric_availability() -> None:
    datasets = load_domain_datasets("vercel_ai", base_dir=REPO_ROOT)
    frame = compute_vercel_ai_views(datasets)["frames"]["Top Models"]

    # Only the three usage metrics are user-facing; counts are excluded.
    assert _available_metrics(frame, "all") == ["tokens", "requests", "spend"]
    assert "tokens" in _available_metrics(frame, "text")
    # Vercel reports no token counts for video models.
    assert "tokens" not in _available_metrics(frame, "video")
    assert set(_available_metrics(frame, "video")) <= {"tokens", "requests", "spend"}

    pivot = _pivot(frame, "text", "tokens")
    assert not pivot.empty
    assert pivot.index.name == "date"


def test_stacked_display_sums_to_100() -> None:
    from dashboard.sections.vercel_ai import (
        TOP_N_BY_ENTITY,
        _others_label,
        _stacked_display,
    )

    datasets = load_domain_datasets("vercel_ai", base_dir=REPO_ROOT)
    frame = compute_vercel_ai_views(datasets)["frames"]["Top Models"]
    others = _others_label("Top Models")
    display = _stacked_display(_pivot(frame, "all", "tokens"), TOP_N_BY_ENTITY["Top Models"], others)

    assert others in display.columns
    row_totals = display.sum(axis=1)
    assert ((row_totals - 100.0).abs() < 1e-6).all()
    # Residual is real (Vercel truncates), so it should carry meaningful weight.
    assert display[others].mean() > 0
    # Match Vercel's public layout: nine named models plus the residual band.
    assert TOP_N_BY_ENTITY["Top Models"] == 9
    assert display.shape[1] == 10


def test_labs_show_up_to_top_20() -> None:
    from dashboard.sections.vercel_ai import (
        TOP_N_BY_ENTITY,
        _others_label,
        _stacked_display,
    )

    datasets = load_domain_datasets("vercel_ai", base_dir=REPO_ROOT)
    frame = compute_vercel_ai_views(datasets)["frames"]["Top Labs"]
    others = _others_label("Top Labs")
    display = _stacked_display(_pivot(frame, "all", "tokens"), TOP_N_BY_ENTITY["Top Labs"], others)

    # 20 named labs + the residual band.
    assert TOP_N_BY_ENTITY["Top Labs"] == 20
    assert others == "Others (smaller labs)"
    assert display.shape[1] == 21
    assert ((display.sum(axis=1) - 100.0).abs() < 1e-6).all()


def test_residual_color_never_collides_with_named_series() -> None:
    from dashboard.sections.vercel_ai import (
        NAMED_PALETTE,
        OTHERS_COLOR,
        TOP_N_BY_ENTITY,
        _column_colors,
    )

    # OTHERS grey must be reserved: not in the named rotation.
    assert OTHERS_COLOR not in NAMED_PALETTE
    # The palette must hold enough distinct hues for the largest top-N.
    max_top_n = max(TOP_N_BY_ENTITY.values())
    assert len(NAMED_PALETTE) >= max_top_n

    others_label = "Others (smaller labs)"
    columns = [f"Series {i}" for i in range(max_top_n)] + [others_label]
    colors = _column_colors(columns, others_label)
    named = colors[:-1]
    assert colors[-1] == OTHERS_COLOR
    assert OTHERS_COLOR not in named
    # A full top-N slate must be collision-free among real series too.
    assert len(set(named)) == len(named)


def test_compute_views_empty_on_missing_dataset() -> None:
    assert compute_vercel_ai_views({}) == {}
