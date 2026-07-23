import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import uuid
import pandas as pd
from typing import Any, Dict, Optional, Union

from .config import RAW_DIR, NORMALIZED_DIR

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
) -> Dict[str, str]:
    """
    Save normalized output as an immutable run-scoped dataset with lineage.
    """
    run_id = run_id or str(uuid.uuid4())
    target_dir = NORMALIZED_DIR / dataset_name / run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    parquet_path = target_dir / f"{dataset_name}.parquet"
    csv_path = target_dir / f"{dataset_name}.csv"

    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)

    lineage_path = target_dir / "lineage.json"
    with open(lineage_path, 'w', encoding='utf-8') as f:
        json.dump({
            'dataset_name': dataset_name,
            'run_id': run_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'raw_snapshot': raw_snapshot,
            'source_url': source_url,
            'records': len(df),
            'columns': list(df.columns),
        }, f, indent=2)

    return {
        'parquet': str(parquet_path),
        'csv': str(csv_path),
        'lineage': str(lineage_path),
        'run_id': run_id,
        'raw_snapshot': raw_snapshot,
    }
