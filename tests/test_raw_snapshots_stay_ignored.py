"""Raw snapshot caches must not become committable by accident.

`!data/raw/*/*/` was added so the per-lane `!data/raw/<lane>/*/manifest.json`
rules could reach a run directory -- git cannot re-include a file whose parent
is excluded. But the wildcard un-ignored every second-level directory under
data/raw, across every lane, which made 180 MB of local PDF and image caches
(hk_transport sell-side reports, MTR SRPE filings, minerals OCR images)
stageable by a plain `git add -A`. Each file sits under the per-file size
budget, so scripts/check_repo_size_budget.py would not have caught it either.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]

# Lanes whose run directories are deliberately reachable, so their manifests --
# which carry the SHA-256 lineage that makes a published panel auditable -- can
# be committed.
MANIFEST_LANES = (
    "bis_macro",
    "hkma_macro",
    "eia_energy",
    "cme_voi",
    "factset_earnings",
    "sp_pmi",
    "msci_reviews",
    "hkex_market_flow",
)

# Local caches that must never be committable. Paths are checked whether or not
# they exist on this machine: `check-ignore --no-index` answers from the rules.
CACHE_PATHS = (
    "data/raw/hk_transport/cathay_pdf_cache/20130117_CX_traffic.pdf",
    "data/raw/hk_transport/cathay_report_cache/2019_annual.pdf",
    "data/raw/hk_transport/airline_sell_side_pdfs/note.pdf",
    "data/raw/hk_transport/mtr_srpe/10486_104178.pdf",
    "data/raw/minerals_signal_data/images/temp_moly_ocr_2025-03-05.jpg",
)


def _is_ignored(relative: str) -> bool:
    return (
        subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", relative], cwd=REPO
        ).returncode
        == 0
    )


@pytest.mark.parametrize("relative", CACHE_PATHS)
def test_local_raw_caches_are_ignored(relative: str) -> None:
    assert _is_ignored(relative), (
        f"{relative} is stageable. A rule under data/raw/ is too broad -- most "
        "likely a wildcard like `!data/raw/*/*/` instead of per-lane entries."
    )


@pytest.mark.parametrize("lane", MANIFEST_LANES)
def test_each_lane_manifest_is_still_committable(lane: str) -> None:
    # The other half of the contract: narrowing the rule must not re-break the
    # provenance it was widened for.
    relative = f"data/raw/{lane}/20260911T000000Z-abcdef01/manifest.json"
    assert not _is_ignored(relative), (
        f"{lane} run manifests are ignored, so a published panel loses the "
        "SHA-256 lineage that makes it auditable."
    )


@pytest.mark.parametrize("lane", MANIFEST_LANES)
def test_lane_payloads_stay_out_of_git(lane: str) -> None:
    # Only the manifest is published; the snapshot bytes it hashes are not.
    relative = f"data/raw/{lane}/20260911T000000Z-abcdef01/payload.json.gz"
    assert _is_ignored(relative), f"{lane} raw payloads would be committed"
