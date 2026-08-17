import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import uuid
import pandas as pd
from typing import Any, Dict, Mapping, Optional, Union

from .config import RAW_DIR, NORMALIZED_DIR


def load_latest_normalized(dataset_name: str) -> pd.DataFrame:
    """Load the most recently written normalized snapshot for a dataset that
    actually has rows.

    Used when a source is deliberately skipped in an environment where its
    live fetch can't succeed (see HK_RE_SKIP_MIDLAND) — falls back to the
    last real data actually fetched, rather than fabricating a value. A run
    whose live fetch legitimately returned zero rows (upstream outage, schema
    change) still gets a fresh timestamped directory, so picking by mtime
    alone would let that empty run permanently shadow the last good snapshot.
    Skip empty runs and fall back to the newest non-empty one instead.
    """
    dataset_dir = NORMALIZED_DIR / dataset_name
    if not dataset_dir.is_dir():
        return pd.DataFrame()
    run_dirs = [d for d in dataset_dir.iterdir() if d.is_dir()]
    if not run_dirs:
        return pd.DataFrame()
    def _sort_key(candidate: Path) -> tuple[float, float, str]:
        # Directory mtimes have only second-level resolution on some
        # filesystems, so several immutable snapshots can tie (especially
        # during a bounded historical backfill).  Prefer the persisted
        # lineage timestamp, then mtime/name as deterministic fallbacks.
        created_at = ""
        lineage_path = candidate / "lineage.json"
        if lineage_path.exists():
            try:
                created_at = str(json.loads(lineage_path.read_text(encoding="utf-8")).get("created_at") or "")
            except (OSError, ValueError, TypeError):
                created_at = ""
        try:
            created_epoch = datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp() if created_at else 0.0
        except ValueError:
            created_epoch = 0.0
        return (created_epoch, candidate.stat().st_mtime, candidate.name)

    for candidate in sorted(run_dirs, key=_sort_key, reverse=True):
        parquet_path = candidate / f"{dataset_name}.parquet"
        if not parquet_path.exists():
            continue
        frame = pd.read_parquet(parquet_path)
        if not frame.empty:
            # Preserve the immutable source lineage when a normalized frame is
            # reused as an input to a derived contract.  Pandas does not store
            # DataFrame.attrs in Parquet, so restore the metadata explicitly
            # from the sibling lineage.json instead of making downstream
            # datasets appear to have no raw provenance.
            lineage_path = candidate / "lineage.json"
            if lineage_path.exists():
                try:
                    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
                    frame.attrs["raw_snapshot"] = lineage.get("raw_snapshot")
                    frame.attrs["raw_snapshots"] = lineage.get("raw_snapshots") or (
                        [lineage.get("raw_snapshot")] if lineage.get("raw_snapshot") else []
                    )
                    frame.attrs["source_url"] = lineage.get("source_url")
                    frame.attrs["source_urls"] = lineage.get("source_urls") or (
                        [lineage.get("source_url")] if lineage.get("source_url") else []
                    )
                    frame.attrs["lineage_metadata"] = lineage
                except (OSError, ValueError, TypeError):
                    # A malformed sidecar must not make the data loader fail;
                    # the normalizer/quality gate will still surface missing
                    # lineage when this frame is persisted again.
                    pass
            return frame
    return pd.DataFrame()

def save_raw_snapshot(
    source_name: str,
    content: Union[str, bytes, Dict[str, Any]],
    file_ext: str = "json",
    *,
    source_url: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Path:
    """
    Save an immutable raw snapshot and its provenance metadata.

    The content hash and a UUID make separate fetches collision-resistant even
    when they occur within the same microsecond.  Raw content is intentionally
    kept separate from normalized output so downstream data can be traced.
    """
    now = datetime.now(timezone.utc)
    if isinstance(content, dict):
        raw_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8')
    elif isinstance(content, str):
        raw_bytes = content.encode('utf-8')
    else:
        raw_bytes = content
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    date_str = now.strftime('%Y-%m-%d')
    timestamp_str = now.strftime('%Y%m%dT%H%M%S_%fZ')
    file_ext_clean = file_ext.lstrip('.').lower()
    snapshot_id = f"{timestamp_str}_{content_hash[:12]}_{uuid.uuid4().hex[:8]}"
    target_dir = RAW_DIR / source_name / date_str
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_path = target_dir / f"{snapshot_id}.{file_ext_clean}"
    meta_path = target_dir / f"{snapshot_id}.meta.json"

    with open(raw_path, 'wb') as f:
        f.write(raw_bytes)

    metadata = {
        'source_name': source_name,
        'fetched_at': now.isoformat(),
        'run_id': run_id,
        'source_url': source_url,
        'file_extension': file_ext_clean,
        'content_size_bytes': len(raw_bytes),
        'sha256': content_hash
    }

    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    return raw_path

def save_normalized_dataset(
    dataset_name: str,
    df: pd.DataFrame,
    *,
    run_id: Optional[str] = None,
    raw_snapshot: Optional[str] = None,
    source_url: Optional[str] = None,
    raw_snapshots: Optional[list[str]] = None,
    source_urls: Optional[list[str]] = None,
    lineage_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Save normalized output as an immutable run-scoped dataset with lineage.
    """
    run_id = run_id or str(uuid.uuid4())
    target_dir = NORMALIZED_DIR / dataset_name / run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    parquet_path = target_dir / f"{dataset_name}.parquet"

    # pyarrow's pandas conversion tries to infer a numeric type for object
    # columns.  A single evidence column can mix plain numeric strings (e.g.
    # "58.0") with JSON-array strings (e.g. "[2.0, 58.0]") when a source
    # prints several candidate percentages for one project.  That mixed
    # column makes inference attempt a double cast and abort with
    # ArrowInvalid ("Could not convert '[...]' with type str").  Pin such
    # evidence columns to a string dtype before writing so the full pipeline
    # is not blocked by one source's formatting.  Purely numeric columns are
    # left untouched.
    for column in df.columns:
        if df[column].dtype == object and df[column].map(
            lambda value: isinstance(value, str) and value.strip().startswith("["),
            na_action="ignore",
        ).any():
            df[column] = df[column].astype("string")

    df.to_parquet(parquet_path, index=False)

    lineage_path = target_dir / "lineage.json"
    lineage = {
            'dataset_name': dataset_name,
            'run_id': run_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'raw_snapshot': raw_snapshot,
            'source_url': source_url,
            'raw_snapshots': raw_snapshots if raw_snapshots is not None else ([raw_snapshot] if raw_snapshot else []),
            'source_urls': source_urls if source_urls is not None else ([source_url] if source_url else []),
            'records': len(df),
            'columns': list(df.columns),
        }
    if lineage_metadata:
        lineage.update(dict(lineage_metadata))
    with open(lineage_path, 'w', encoding='utf-8') as f:
        json.dump(lineage, f, indent=2)

    return {
        'parquet': str(parquet_path),
        'lineage': str(lineage_path),
        'run_id': run_id,
        'raw_snapshot': raw_snapshot,
        'raw_snapshots': raw_snapshots if raw_snapshots is not None else ([raw_snapshot] if raw_snapshot else []),
        'source_urls': source_urls if source_urls is not None else ([source_url] if source_url else []),
    }
