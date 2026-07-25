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
    """
    now = datetime.now(timezone.utc)
    if isinstance(content, (dict, list)):
        raw_bytes = json.dumps(content, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    elif isinstance(content, str):
        raw_bytes = content.encode('utf-8')
    elif isinstance(content, bytes):
        raw_bytes = content
    else:
        raw_bytes = json.dumps(content, ensure_ascii=False, indent=2, default=str).encode('utf-8')
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    date_str = now.strftime('%Y-%m-%d')
    timestamp_str = now.strftime('%Y%m%dT%H%M%S_%fZ')
    file_ext_clean = file_ext.lstrip('.').lower()
    # NOTE on the uuid suffix and content_hash below: this house style is
    # append-only / preserve-every-vintage (see also NORMALIZED_DIR being
    # run_id-scoped in save_normalized_dataset, and the raw snapshot dir
    # being date-scoped) -- every fetch gets its own immutable snapshot
    # file, even if the content is byte-identical to a prior fetch, because
    # the *fact that a fetch happened at this timestamp and returned this
    # content* is itself part of the audit trail we want to keep. The
    # uuid4 suffix guarantees the snapshot_id (and therefore the file
    # path) is unique per call, which deliberately defeats hash-based
    # deduplication.
    #
    # content_hash / sha256 here is for content-integrity and audit
    # purposes ONLY (e.g. verifying a snapshot wasn't corrupted or
    # tampered with, or confirming two snapshots are byte-identical after
    # the fact) -- it is NOT a deduplication key. If true dedup (skip
    # writing when content is unchanged) is ever wanted, drop the uuid
    # suffix and check for an existing file whose name starts with
    # "{content_hash[:12]}" under this source's directory before writing.
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
    data_source: Optional[str] = None,
) -> Dict[str, str]:
    """
    Save normalized output as an immutable run-scoped dataset with lineage.

    `data_source` (bug 5 fix) records whether this dataset is real
    ("live") or a synthetic placeholder ("fallback_sample") produced
    because the live fetch failed. Callers should pass this explicitly;
    if omitted, it is inferred from a `data_source` column on `df` (the
    per-source modules stamp every row with one) so the distinction
    survives even if a caller forgets to pass it -- it must never be
    silently lost, since parquet/csv round-trips drop `df.attrs`.
    """
    run_id = run_id or str(uuid.uuid4())
    target_dir = NORMALIZED_DIR / dataset_name / run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    parquet_path = target_dir / f"{dataset_name}.parquet"

    df.to_parquet(parquet_path, index=False)

    if data_source is None and 'data_source' in df.columns and len(df):
        # Uniform per fetch in practice, but if a run genuinely mixed
        # live and fallback rows (e.g. some tickers succeeded, some
        # didn't), be conservative and surface that the run wasn't 100%
        # live rather than picking an arbitrary row's value.
        unique_sources = set(df['data_source'].dropna().unique().tolist())
        if len(unique_sources) == 1:
            data_source = next(iter(unique_sources))
        elif unique_sources:
            data_source = "mixed"

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
            'data_source': data_source,
        }, f, indent=2)

    return {
        'parquet': str(parquet_path),
        'lineage': str(lineage_path),
        'run_id': run_id,
        'raw_snapshot': raw_snapshot,
        'data_source': data_source,
    }
