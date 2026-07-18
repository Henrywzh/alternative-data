from __future__ import annotations

import argparse
from pathlib import Path

from provider_incident_data.pipeline import ProviderIncidentPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect official provider-reported AI service incidents")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    parser.add_argument("command", choices=("update",), nargs="?", default="update")
    args = parser.parse_args()
    written = ProviderIncidentPipeline(Path(args.base_dir).resolve()).run_update()
    for dataset_id, row_count in written.items():
        print(f"{dataset_id}: {row_count} rows")


if __name__ == "__main__":
    main()
