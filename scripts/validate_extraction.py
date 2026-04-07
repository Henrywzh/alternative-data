#!/usr/bin/env python3
"""
Utility script to validate OpenRouter data extraction against raw snapshots.
This script scans the data/raw/openrouter directory and attempts to extract
data from existing HTML snapshots to verify the parser's correctness.
"""

from pathlib import Path
import sys
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openrouter_data.pipeline import RankingsPipeline, AppsPipeline
from openrouter_data.models import RunContext, Snapshot

def validate_extraction():
    base_dir = Path(__file__).resolve().parent.parent
    raw_root = base_dir / "data" / "raw" / "openrouter"
    
    if not raw_root.exists():
        print(f"Error: Raw root {raw_root} does not exist.")
        return

    rankings_pipe = RankingsPipeline(base_dir)
    apps_pipe = AppsPipeline(base_dir)

    print("=== OpenRouter Extraction Validator ===\n")

    run_dirs = sorted(raw_root.glob("*"))
    if not run_dirs:
        print("No raw run directories found.")
        return

    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
            
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            print(f"Skipping {run_dir.name}: No manifest.json")
            continue

        print(f"Processing Run: {run_dir.name}")
        
        try:
            # Check for rankings snapshots
            rankings_html = run_dir / "rankings.html"
            prog_html = run_dir / "rankings_programming.html"
            
            if rankings_html.exists():
                print(f"  Validating Rankings...")
                results = rankings_pipe.validate(
                    fixture_html=rankings_html.read_text(encoding="utf-8"),
                    fixture_programming_html=prog_html.read_text(encoding="utf-8") if prog_html.exists() else None
                )
                for ds, count in results.items():
                    print(f"    - {ds}: {count} records extracted")

            # Check for Apps snapshots
            apps_dir_html = run_dir / "apps_directory.html"
            apps_detail_html = run_dir / "app_openclaw.html"
            if apps_dir_html.exists():
                print(f"  Validating Apps...")
                results = apps_pipe.validate(
                    directory_fixture_html=apps_dir_html.read_text(encoding="utf-8"),
                    app_fixture_html=apps_detail_html.read_text(encoding="utf-8") if apps_detail_html.exists() else None
                )
                for ds, count in results.items():
                    print(f"    - {ds}: {count} records extracted")

        except Exception as e:
            print(f"  Error validating {run_dir.name}: {e}")
        print("-" * 40)

if __name__ == "__main__":
    validate_extraction()
