from __future__ import annotations

import json
import requests

from vercel_ai_data.models import DatasetRecord, RunContext, Snapshot
from vercel_ai_data.sources.base import SourceExtractor


class VercelLeaderboardSource(SourceExtractor):
    name = "vercel_leaderboard"

    # Vercel's leaderboard export is sliced by modality. Fetching each slice
    # backfills full history per modality (the export returns all dates), so the
    # dashboard's modality sub-tabs get complete history, not just today.
    MODALITIES = ("all", "text", "image", "video")
    DATASETS = {
        "vercel_model_leaderboard": "models",
        "vercel_lab_leaderboard": "labs",
    }

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )

    def fetch_snapshots(self) -> list[Snapshot]:
        snapshots: list[Snapshot] = []

        for dataset_id, api_dataset in self.DATASETS.items():
            for modality in self.MODALITIES:
                url = (
                    "https://vercel.com/api/ai/leaderboard-export"
                    f"?dataset={api_dataset}&format=json&modality={modality}"
                )
                try:
                    response = self.session.get(url, timeout=self.timeout)
                    response.raise_for_status()
                    snapshots.append(
                        Snapshot(
                            # Snapshot name encodes the modality so raw files stay
                            # distinct; extract() strips the suffix back to the id.
                            name=f"{dataset_id}__{modality}",
                            source_url=url,
                            body=response.text,
                        )
                    )
                except Exception as exc:
                    print(f"Warning: Failed to fetch Vercel {dataset_id} ({modality}) snapshot: {exc}")

        return snapshots

    def extract(
        self,
        snapshots: list[Snapshot],
        context: RunContext,
    ) -> dict[str, list[DatasetRecord]]:
        extracted: dict[str, list[DatasetRecord]] = {
            "vercel_model_leaderboard": [],
            "vercel_lab_leaderboard": [],
        }

        for snapshot in snapshots:
            # Snapshot names are "<dataset_id>__<modality>"; fixtures/legacy names
            # may be the bare dataset id, in which case modality comes from the row.
            dataset_id, _, modality_from_name = snapshot.name.partition("__")
            if dataset_id not in extracted:
                continue

            try:
                data = json.loads(snapshot.body)
            except Exception as exc:
                print(f"Error parsing JSON from {snapshot.name}: {exc}")
                continue

            rows = data.get("rows", [])
            if not isinstance(rows, list):
                print(f"Warning: Expected 'rows' to be a list in {snapshot.name}")
                continue

            for row in rows:
                if not isinstance(row, dict):
                    continue

                record = DatasetRecord(
                    dataset_id=dataset_id,
                    source_url=snapshot.source_url,
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    date=row.get("date"),
                    group=row.get("group"),
                    name=row.get("name"),
                    metric=row.get("metric"),
                    modality=modality_from_name or row.get("modality"),
                    share_percent=row.get("share_percent"),
                )
                extracted[dataset_id].append(record)

        return extracted
