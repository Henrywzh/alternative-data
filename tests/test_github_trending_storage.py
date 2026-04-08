from __future__ import annotations

from pathlib import Path

import pandas as pd

from github_trending_data.models import TrendingRepo
from github_trending_data.storage import GithubTrendingStorage


def _repo(*, scrape_date: str, period: str, author: str, name: str) -> TrendingRepo:
    return TrendingRepo(
        scrape_date=scrape_date,
        period=period,
        author=author,
        name=name,
        link=f"https://github.com/{author}/{name}",
        description="Test repository",
        stars_today=42,
        total_stars=700,
    )


def test_enforce_retention_handles_arrow_backed_unique_dates(tmp_path: Path) -> None:
    storage = GithubTrendingStorage(tmp_path)

    # Write multiple days so save() has to reload from parquet and enforce retention
    # against the Arrow-backed dtype used in CI.
    for day in ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05", "2026-04-06"]:
        storage.save("daily", [_repo(scrape_date=day, period="daily", author="openai", name=f"repo-{day}")])

    path = tmp_path / "normalized" / "github_trending" / "github_trending_daily.parquet"
    saved = pd.read_parquet(path)

    kept_dates = sorted(saved["scrape_date"].astype(str).unique().tolist())
    assert kept_dates == ["2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05", "2026-04-06"]
    assert len(saved) == 5
