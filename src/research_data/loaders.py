from __future__ import annotations

from pathlib import Path

import pandas as pd

from dashboard import data as dashboard_data


def resolve_base_dir(base_dir: str | Path | None = None) -> Path:
    if base_dir is None:
        return dashboard_data.repo_root()
    return Path(base_dir).resolve()


def load_dataset_result(dataset_id: str, base_dir: str | Path | None = None) -> dashboard_data.DatasetLoadResult:
    return dashboard_data.load_dataset(dataset_id, base_dir=resolve_base_dir(base_dir))


def load_dataset(dataset_id: str, base_dir: str | Path | None = None) -> pd.DataFrame:
    return load_dataset_result(dataset_id, base_dir=base_dir).frame.copy()


def load_domain_results(
    domain: str,
    base_dir: str | Path | None = None,
) -> dict[str, dashboard_data.DatasetLoadResult]:
    return dashboard_data.load_domain_datasets(domain, base_dir=resolve_base_dir(base_dir))


def load_domain(domain: str, base_dir: str | Path | None = None) -> dict[str, pd.DataFrame]:
    return {
        dataset_id: result.frame.copy()
        for dataset_id, result in load_domain_results(domain, base_dir=base_dir).items()
    }
