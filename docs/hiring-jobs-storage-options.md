# hiring_jobs storage: why it is still a single file

`data/normalized/ai_hiring/hiring_jobs.parquet` is the largest remaining
source of repository growth: **80.4 MB of git history over 90 days**, across
56 blobs, for a file that is 2.8 MB on disk. Parquet is compressed binary that
git cannot delta, so every daily run stores a complete new copy.

It was deliberately **not** partitioned when `openrouter_task_spend` and
`hiring_job_events` were. This records the measurements behind that, so the
question does not get re-opened from scratch.

## Why partitioning does not work here

Partitioning pays off when a run rewrites few partitions. Measured across two
consecutive commits (2026-09-08 -> 2026-09-09, 16,346 -> 16,533 rows):

| partition key | partitions | rewritten | avg rows/file |
|---|---|---|---|
| `first_seen_at` | 56 | 51 (91%) | 295 |
| `company_id` | 70 | 55 (79%) | 236 |
| `country_code` | 12 | 12 (100%) | 1,377 |
| `role_family` | 8 | 8 (100%) | 2,066 |
| `status` | 3 | 3 (100%) | 5,511 |

No key works. `hiring_jobs` is a **mutable state table**, not an append-only
log: 12.2% of carried-over rows change every run, and they scatter across
every dimension, so nearly every partition contains at least one changed row.
That earns all of the file-count overhead and none of the benefit.

## What actually changes

Column-level churn on the 16,346 carried-over rows:

| column | rows changed |
|---|---|
| `source_run_id`, `scraped_at`, `last_changed_at` | 1,997 (12.2%) |
| `content_hash` | 1,699 (10.4%) |
| `source_updated_at` | 1,653 (10.1%) |
| `status`, `consecutive_missing_runs` | 318 (1.9%) |
| `title`, `team`, `location_raw`, and all other job content | 5-32 (0.0-0.2%) |

The churn is bookkeeping, not job content. But bookkeeping is enough: any
changed row changes the file, and git stores the whole file.

## Size is dominated by one column

Bytes each column adds on top of the two key columns:

| column | added | distinct values |
|---|---|---|
| `content_hash` | **1,082 KB** | 16,533 |
| `source_updated_at` | 62 KB | 5,570 |
| `source_run_id`, `scraped_at`, `last_changed_at` | 12 KB each | 53 each |
| `status`, `consecutive_missing_runs` | 1 KB each | 3 each |

`content_hash` is 39% of the whole 2.74 MB table. It is a per-row SHA-256, so
it has one distinct value per row and cannot dictionary-compress -- unlike
`scraped_at`, which changes on 12% of rows but costs 12 KB because it only has
53 distinct values.

## Option A -- derive `content_hash` instead of storing it (rejected)

`extract._content_hash` hashes 16 fields, and every one of them is already a
stored column, so the hash looks derivable on read. It is not:

```
recomputed == stored:                       16,344 / 16,533  (98.9%)
after normalising pandas NA and numpy bool: 16,344 / 16,533  (98.9%)
```

The 189 stragglers differ on `employment_type` and `is_ai_role`, which are
modified by the classifier *after* the hash is taken. So the stored hash does
not correspond to the stored field values for ~1.1% of rows.

Deriving it would mark those rows changed on the first run and, worse, leave
change detection depending on a reconstruction that can drift silently
whenever a downstream step mutates a hashed field. A wrong `content_hash`
does not raise -- it makes the pipeline believe every job changed, which
triggers exactly the mass rewrite this work exists to prevent. Not worth 39%.

## Option B -- split stable columns from volatile ones (viable, 48%)

Write job content and light bookkeeping to one file, and the volatile columns
(`source_run_id`, `scraped_at`, `last_changed_at`, `content_hash`,
`source_updated_at`, `status`, `consecutive_missing_runs`) to another:

```
single table:          2.74 MB   rewritten in full every run
  stable  (26 cols):   1.56 MB   only 79 of 16,346 rows differ (0.48%)
  volatile ( 7 cols):  1.42 MB   rewritten in full every run
per-run cost: 2.74 MB -> 1.42 MB  (48% reduction)
```

Real, but it needs a schema change, a migration, dual-table reads through
`HiringStorage.load`, and updates to every consumer -- for half the benefit
that partitioning gave the append-only datasets. Worth doing as its own
project, not as a tail-end change.

## Option C -- shorten the stored hash (small, low risk)

Storing 16 hex characters instead of 64 keeps collision probability
negligible at this scale (~7e-12 across 16.5k rows) and cuts `content_hash`
from 1,082 KB to roughly 270 KB, about 30% off the table. One migration
rewrite, then permanently cheaper, and it does not change what the hash
*means* -- only its width. It still touches change-detection, so it needs the
same care as Option B, with less payoff and less risk.

## Recommendation

Leave it single-file for now. If it becomes the top offender again after the
other lanes are partitioned, do **Option B** as a scoped change with its own
migration and tests. Do not do Option A.
