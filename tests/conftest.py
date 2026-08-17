from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

for path in (ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def require_local_normalized(*dataset_names: str) -> None:
    """Skip when a gitignored normalized dataset this test needs is absent.

    ``data/normalized/hk_real_estate/`` holds ~215 pipeline-output datasets
    (~400 MB) that the repository deliberately does not track.  Tests that read
    them therefore pass only on a machine that has generated them.  Rather than
    let CI report a data-availability gap as a code failure -- or silently pass
    -- these tests skip with the specific dataset named, so the reason is
    visible in the run output instead of inferred.
    """

    import pytest

    root = ROOT / "data" / "normalized" / "hk_real_estate"
    missing = [name for name in dataset_names if not (root / name).is_dir()]
    if missing:
        pytest.skip(
            "requires locally generated datasets not tracked by git: "
            + ", ".join(missing)
            + f" (expected under {root.relative_to(ROOT)}/)"
        )
