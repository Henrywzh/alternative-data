from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import requests

from llm_benchmark_data.models import BenchmarkPoint, Snapshot


class ZeroEvalSource:
    BASE_URL = "https://api.zeroeval.com/leaderboard/models/full"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "alternative-data-llm-benchmarks/0.1")

    def fetch_snapshots(self) -> list[Snapshot]:
        response = self.session.get(self.BASE_URL, timeout=30)
        response.raise_for_status()
        
        return [
            Snapshot(
                name="zeroeval_full",
                source_url=self.BASE_URL,
                body=response.text,
            )
        ]

    def extract(self, snapshots: list[Snapshot], run_id: str) -> list[BenchmarkPoint]:
        points: list[BenchmarkPoint] = []
        scraped_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        dataset_id = "llm_benchmarks"

        for snapshot in snapshots:
            try:
                data = json.loads(snapshot.body)
            except json.JSONDecodeError:
                continue

            # ZeroEval returns a list of model objects
            if not isinstance(data, list):
                continue

            for item in data:
                model_id = item.get("model_id")
                if not model_id:
                    continue

                # Extract specific benchmarks requested: GPQA and SWE-bench
                # Using the actual fields found in the JSON
                gpqa = item.get("gpqa_score")
                swe_bench = item.get("swe_bench_verified_score") or item.get("swe_bench_score")

                points.append(
                    BenchmarkPoint(
                        model_id=model_id,
                        name=item.get("name") or model_id,
                        organization=item.get("organization") or "unknown",
                        release_date=item.get("release_date"),
                        context_window=item.get("context"),
                        gpqa=float(gpqa) if gpqa is not None else None,
                        swe_bench=float(swe_bench) if swe_bench is not None else None,
                        scraped_at=scraped_at,
                        source_url=snapshot.source_url,
                        dataset_id=dataset_id,
                        source_run_id=run_id,
                    )
                )

        return points
