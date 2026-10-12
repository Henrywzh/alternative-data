"""Refresh with `python -m china_macro.cli`; build never fetches remote data."""
import argparse

from .artifact import build_artifacts
from .pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    if not args.build_only:
        observations, signals, manifest = run_pipeline(backfill=args.backfill, write=not args.no_write)
        print(f"Run {manifest['run_id']}: {len(observations)} observations, {len(signals)} derived values")
    if not args.no_write:
        artifact = build_artifacts()
        print(f"Artifact: {artifact['snapshot']['status']}, run {artifact['run_id']}")


if __name__ == "__main__":
    main()
