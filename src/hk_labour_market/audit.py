"""Final quality audit for the HK labour-market data layer."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import BASE_DIR, MARTS_DIR, NORMALIZED_DIR
from .marts import CORE_DATASETS, POLICY_DATASETS, STAGE_2_DATASETS, STAGE_3_DATASETS, load_latest_dataset
from .quality import validate_frame, validate_policy_frame
from .source_registry import CORE_CENSTATD_TABLES, STAGE_2_CENSTATD_TABLES, STAGE_3_CENSTATD_TABLES
from .sources.immigration_employment import EMPLOYMENT_POLICY_SOURCES
from .sources.labour_department import ESLS_SOURCE_ID


POLICY_SOURCE_TABLE_IDS = {
    "esls_applications_annual": ESLS_SOURCE_ID,
    **{source["dataset_id"]: source["source_table_id"] for source in EMPLOYMENT_POLICY_SOURCES},
}


def _resolve_path(value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else BASE_DIR / path


def _audit_lineage(dataset_id: str, frame: pd.DataFrame, manifest_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read manifest: {exc}"]
    entry = manifest.get("datasets", {}).get(dataset_id, {})
    for field in ("raw_snapshot", "parquet", "lineage"):
        path_value = entry.get(field)
        if not path_value or not _resolve_path(path_value).is_file():
            errors.append(f"missing {field} artifact")
    lineage_value = entry.get("lineage")
    if lineage_value and _resolve_path(lineage_value).is_file():
        try:
            lineage = json.loads(_resolve_path(lineage_value).read_text(encoding="utf-8"))
            if lineage.get("dataset_id") != dataset_id:
                errors.append("lineage dataset_id does not match manifest")
            if lineage.get("run_id") != manifest.get("run_id"):
                errors.append("lineage run_id does not match manifest")
            if lineage.get("records") != len(frame):
                errors.append("lineage record count does not match Parquet")
            if lineage.get("raw_snapshot") and entry.get("raw_snapshot"):
                if _resolve_path(lineage["raw_snapshot"]) != _resolve_path(entry["raw_snapshot"]):
                    errors.append("lineage raw snapshot does not match manifest")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot read lineage: {exc}")
    raw_value = entry.get("raw_snapshot")
    if raw_value and _resolve_path(raw_value).is_file() and not _resolve_path(raw_value).with_suffix(".meta.json").is_file():
        errors.append("raw snapshot metadata is missing")
    if raw_value and _resolve_path(raw_value).is_file():
        raw_path = _resolve_path(raw_value)
        meta_path = raw_path.with_suffix(".meta.json")
        if meta_path.is_file():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                raw_bytes = raw_path.read_bytes()
                if metadata.get("dataset_id") != dataset_id:
                    errors.append("raw snapshot metadata dataset_id does not match")
                if metadata.get("run_id") != manifest.get("run_id"):
                    errors.append("raw snapshot metadata run_id does not match")
                if metadata.get("sha256") != hashlib.sha256(raw_bytes).hexdigest():
                    errors.append("raw snapshot checksum does not match metadata")
                if metadata.get("content_size_bytes") != len(raw_bytes):
                    errors.append("raw snapshot size does not match metadata")
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"cannot read raw snapshot metadata: {exc}")
    return errors


def run_labour_market_audit(*, write_report: bool = True) -> dict[str, Any]:
    """Validate latest source vintages, pointers and analytical marts."""
    report: dict[str, Any] = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "sources": {},
        "marts": {},
        "errors": [],
    }
    specs_by_dataset = {
        spec.dataset_id: spec
        for spec in (*CORE_CENSTATD_TABLES, *STAGE_2_CENSTATD_TABLES, *STAGE_3_CENSTATD_TABLES)
    }
    for dataset_id in (*CORE_DATASETS, *STAGE_2_DATASETS, *STAGE_3_DATASETS):
        try:
            frame, manifest = load_latest_dataset(dataset_id)
            errors = validate_frame(frame, specs_by_dataset[dataset_id])
            errors.extend(_audit_lineage(dataset_id, frame, manifest))
            report["sources"][dataset_id] = {
                "status": "pass" if not errors else "fail",
                "records": len(frame),
                "manifest": str(manifest),
                "first_period": str(frame["period"].min()),
                "latest_period": str(frame.loc[frame["value"].notna(), "period"].max()),
                "errors": errors,
            }
            report["errors"].extend(f"{dataset_id}: {error}" for error in errors)
        except Exception as exc:
            report["sources"][dataset_id] = {"status": "fail", "errors": [str(exc)]}
            report["errors"].append(f"{dataset_id}: {exc}")

    for dataset_id in POLICY_DATASETS:
        try:
            frame, manifest = load_latest_dataset(dataset_id)
            errors = validate_policy_frame(frame, expected_source_table_id=POLICY_SOURCE_TABLE_IDS.get(dataset_id))
            errors.extend(_audit_lineage(dataset_id, frame, manifest))
            report["sources"][dataset_id] = {
                "status": "pass" if not errors else "fail",
                "records": len(frame),
                "manifest": str(manifest),
                "first_period": str(frame["period"].min()),
                "latest_period": str(frame["period"].max()),
                "errors": errors,
            }
            report["errors"].extend(f"{dataset_id}: {error}" for error in errors)
        except FileNotFoundError:
            # A source can be absent in older vintages; current registry
            # entries are expected after a complete stage-4 run.
            report["sources"][dataset_id] = {"status": "missing", "errors": ["no successful normalized vintage"]}
            report["errors"].append(f"{dataset_id}: no successful normalized vintage")
        except Exception as exc:
            report["sources"][dataset_id] = {"status": "fail", "errors": [str(exc)]}
            report["errors"].append(f"{dataset_id}: {exc}")

    mart_manifest_path = MARTS_DIR / "manifest.json"
    try:
        mart_manifest = json.loads(mart_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        mart_manifest = {}
        report["errors"].append(f"cannot read marts manifest: {exc}")
    for name in ("labour_sector_panel", "labour_income_panel", "labour_policy_supply_panel"):
        path = MARTS_DIR / f"{name}.parquet"
        try:
            frame = pd.read_parquet(path)
            errors = []
            if frame.empty:
                errors.append("mart is empty")
            required = {"dataset_id", "period", "metric_name", "value"}
            missing = sorted(required.difference(frame.columns))
            if missing:
                errors.append(f"missing mart columns: {', '.join(missing)}")
            if name == "labour_policy_supply_panel" and frame["value"].isna().any():
                errors.append("policy mart contains null counts")
            mart_entry = mart_manifest.get("marts", {}).get(name, {})
            if not mart_entry:
                errors.append("mart is missing from marts manifest")
            for source_manifest in mart_entry.get("source_manifests", []):
                if not _resolve_path(source_manifest).is_file():
                    errors.append(f"source manifest is missing: {source_manifest}")
            report["marts"][name] = {"status": "pass" if not errors else "fail", "records": len(frame), "errors": errors}
            report["errors"].extend(f"{name}: {error}" for error in errors)
        except Exception as exc:
            report["marts"][name] = {"status": "fail", "errors": [str(exc)]}
            report["errors"].append(f"{name}: {exc}")

    pointer_path = NORMALIZED_DIR / "latest_runs.json"
    expected_stages = {"stage_1", "stage_2", "stage_3", "stage_4"}
    if not pointer_path.exists():
        report["errors"].append("latest_runs.json is missing")
    else:
        try:
            pointers = json.loads(pointer_path.read_text(encoding="utf-8"))
            missing_stages = sorted(expected_stages.difference(pointers))
            if missing_stages:
                report["errors"].append(f"latest_runs.json missing stages: {', '.join(missing_stages)}")
            for stage_name in sorted(expected_stages.intersection(pointers)):
                manifest_value = pointers[stage_name].get("manifest")
                if not manifest_value or not _resolve_path(manifest_value).is_file():
                    report["errors"].append(f"{stage_name} pointer manifest is missing")
                else:
                    try:
                        pointer_manifest = json.loads(_resolve_path(manifest_value).read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        report["errors"].append(f"{stage_name} pointer manifest is unreadable: {exc}")
                    else:
                        if pointer_manifest.get("status") != "success":
                            report["errors"].append(f"{stage_name} pointer does not reference a successful manifest")
        except json.JSONDecodeError as exc:
            report["errors"].append(f"latest_runs.json is invalid JSON: {exc}")

    report["status"] = "pass" if not report["errors"] else "fail"
    if write_report:
        (MARTS_DIR / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
