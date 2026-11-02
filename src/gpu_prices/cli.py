"""Refresh the local GPU price dashboard draft."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gpu_prices.pipeline import refresh


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = refresh(args.base_dir.resolve())
    print(json.dumps(report, indent=2))
    if any(source["status"] != "ok" for source in report["sources"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
