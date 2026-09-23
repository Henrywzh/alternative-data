#!/usr/bin/env python3
"""Write sanitized, bounded evidence for an Asia Markets builder failure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--producer-outcome", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from ops_control.sector_builder_evidence import build_sector_builder_evidence

    evidence = build_sector_builder_evidence(
        log_path=args.log,
        roster_path=args.roster,
        producer_outcome=args.producer_outcome,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "Sector builder evidence capture: "
        f"status={evidence['capture_status']} failures={len(evidence['failures'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
