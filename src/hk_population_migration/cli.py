import argparse
import json
import logging
from .pipeline import run_stage_1_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="HK Population & Migration Pipeline CLI")
    parser.add_argument("--run", action="store_true", help="Run Stage 1 data ingestion")
    args = parser.parse_args()

    if not args.run:
        parser.error("--run is required to execute Stage 1 data ingestion")
    res = run_stage_1_pipeline()
    failed = [name for name, value in res.items() if isinstance(value, dict) and "error" in value]
    print(f"Pipeline completed. Ingested {len(res) - len(failed)} sources; {len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
