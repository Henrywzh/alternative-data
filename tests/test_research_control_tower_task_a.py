from __future__ import annotations

from pathlib import Path

from scripts.build_research_control_tower import COLLECTOR_COMMANDS


def test_parent_quote_refresh_command_passes_complete_stage1_registry() -> None:
    command = COLLECTOR_COMMANDS["quote_snapshots"]
    for argument in (
        "--listings config/research_control_tower/listings.csv",
        "--entities config/research_control_tower/entities.csv",
        "--baskets config/research_control_tower/baskets.csv",
        "--basket-memberships config/research_control_tower/basket_memberships.csv",
    ):
        assert argument in command


def test_readme_quote_refresh_is_parameterized_and_complete() -> None:
    readme = Path("apps/research-control-tower/README.md").read_text(encoding="utf-8")
    for argument in (
        "--entities config/research_control_tower/entities.csv",
        "--baskets config/research_control_tower/baskets.csv",
        "--basket-memberships config/research_control_tower/basket_memberships.csv",
    ):
        assert argument in readme
    assert 'RCT_AS_OF_UTC="${RCT_AS_OF_UTC:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"' in readme
    assert "--as-of-utc 2026-08-13T12:00:00Z" not in readme
    assert "--build-id task8-local-20260813" not in readme
    assert "--build-id quote-refresh-20260813T1200Z" not in readme
