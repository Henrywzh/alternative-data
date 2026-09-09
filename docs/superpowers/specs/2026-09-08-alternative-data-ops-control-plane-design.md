# Alternative Data Operations Control Plane Design

**Date:** 2026-09-08

**Status:** Approved in design discussion; implementation is staged

**Repository:** `Henrywzh/alternative-data`

## 1. Summary

The repository needs an operations control plane that can distinguish workflow execution success from actual data health, create evidence-backed incidents, ask Codex to investigate and repair ordinary failures, and report system health every day.

The selected architecture is cloud-first and locally augmented:

- GitHub-hosted Actions provide the always-on execution and monitoring layer.
- Deterministic code detects execution, freshness, coverage, regression, and publication failures.
- Codex investigates incidents after deterministic detection; it does not decide whether a pipeline is healthy from intuition alone.
- Low-risk operational and code repairs may eventually be committed, pushed, validated, and auto-merged without human involvement.
- High-risk, semantically ambiguous, destructive, security-sensitive, or repeatedly failing repairs require human review.
- Local Codex may run unattended when the user's Mac is awake and may read the repository `.config` and sibling repositories, but it is not part of the availability guarantee.
- GitHub Actions self-hosted runners are prohibited.

Phase 0 implements shadow-mode telemetry for three pilot pipelines. It does not create incidents, invoke Codex, alter merge policy, create scheduled tasks, or replace the current publication mechanism.

## 2. Context and Problem

The repository contains more than forty scheduled workflows covering data collection, normalization, derived marts, dashboards, and publication. It already has strong domain-specific checks, including:

- `scripts/check_dataset_contract.py` for file, schema, natural-key, emptiness, and optional freshness checks.
- `scripts/audit_asia_markets_freshness.py` for expected observation periods and English/Chinese artifact parity.
- Asia Markets artifact guards that retain the previous valid artifact when a producer fails.
- OpenRouter capability-drift detection that updates a deduplicated GitHub issue.
- Raw snapshots and lineage artifacts used for investigation and reproducibility.

These controls are valuable but decentralized. A workflow conclusion currently cannot be treated as a reliable statement of data health:

- `continue-on-error`, tolerant builders, and retained artifacts can leave a workflow green while data is stale, partial, or degraded.
- Multiple workflows directly commit, rebase, and push overlapping generated files to `main`, which can produce publication conflicts and secondary parse errors.
- A scraper's inability to observe an element can be incorrectly escalated into a claim that the upstream source removed the element.
- There is no uniform pipeline registry, run-report schema, incident lifecycle, evidence policy, or autonomy policy.
- Some investigations require local caches, sibling repositories, residential networking, or locally stored credentials.

The control plane must preserve the repository's existing data semantics:

- Missing or not-covered data is not zero.
- Query-scoped absence is not permanent absence.
- Artifact generation time is not the same as source-data freshness.
- Point-in-time and lineage rules cannot be weakened to make a pipeline pass.
- A retained previous artifact is degraded service, not a healthy refresh.

## 3. Goals

The system will eventually:

1. Detect observable pipeline failures within 15 minutes of workflow completion.
2. Detect missed schedules or absent workflow runs within six hours.
3. Identify stale, regressed, partial, missing, or retained data even when GitHub Actions reports success.
4. Deduplicate repeated manifestations of the same incident.
5. Require evidence-scoped Codex conclusions using `observed`, `inferred`, and `unknown`.
6. Automatically retry clear transient failures.
7. Allow Codex to repair, commit, push, and auto-merge low-risk changes after deterministic gates pass.
8. Escalate high-risk or ambiguous changes to the user with a concise evidence package.
9. Produce a daily 09:00 Asia/Taipei operations digest, including a weekly reliability section on Mondays.
10. Permit best-effort local Codex investigation without making Mac availability part of the monitoring SLA.
11. Eliminate concurrent direct publication by migrating to one serialized publisher.

## 4. Non-Goals

The initial system will not:

- Replace all workflows with Airflow, Dagster, Prefect, or another orchestrator.
- Use GitHub Actions self-hosted runners.
- Give cloud jobs access to the user's Mac, local `.config`, or unrelated local data.
- Let an LLM be the sole detector of pipeline health.
- Allow Codex to weaken tests, contracts, freshness thresholds, or point-in-time rules to obtain a green result.
- Automatically approve semantic changes, historical deletion, broad backfills, secret handling, or workflow permission changes.
- Introduce a dedicated incident database in the first implementation.

## 5. Chosen Architecture

```text
Producer workflows on GitHub-hosted runners
        |
        +-- existing domain validators
        +-- standardized run-report.json
        +-- immutable evidence artifacts
        |
        v
Deterministic operations control plane
        |
        +-- pipeline health evaluation
        +-- reconciliation
        +-- incident fingerprinting and lifecycle
        +-- risk and merge policy
        |
        +--------------------+
        |                    |
        v                    v
Cloud Codex triage      Daily cloud digest
        |
        +-- cloud repair and PR
        |
        +-- NEEDS_LOCAL queue
                  |
                  v
        Local Codex when Mac is available
                  |
                  v
        evidence or repair branch
                  |
                  v
        cloud validation and merge
```

The architecture deliberately separates:

- **Data plane:** collect, normalize, validate, and stage data artifacts.
- **Publication plane:** publish validated artifacts through one serialized writer.
- **Control plane:** evaluate health, manage incidents, invoke agents, enforce autonomy policy, and report status.

## 6. Execution and Trust Boundaries

### 6.1 Cloud

Cloud execution uses GitHub-hosted runners only. It owns:

- Pipeline execution.
- Per-run deterministic health evaluation.
- Automatic retry.
- Incident creation and reconciliation.
- Cloud Codex investigation and repair.
- Pull-request checks and policy-based auto-merge.
- Publication.
- Daily and weekly reporting.

Cloud execution must not depend on the user's Mac being online.

### 6.2 Local Codex

Local Codex is permitted to:

- Read the canonical repository `.config`.
- Access the `financial-data` and `quantamental-lab` sibling repositories.
- Use local DuckDB files, retained caches, browsers, and residential networking.
- Edit an isolated task worktree.
- Commit and push a repair branch and create a pull request.
- Upload redacted evidence to the incident control plane.

Local Codex must:

- Treat the canonical working tree as read-only by default.
- Never modify, delete, or commit `.config`.
- Avoid copying `.config` into a scheduled-task worktree.
- Treat sibling repositories as read-only unless a separate task worktree is created for an explicitly scoped cross-repository repair.
- Redact secrets from logs and artifacts.
- Never push code directly to `main`.
- Never act as a generic remote command executor.

Local Codex is best-effort. When the Mac is offline, `NEEDS_LOCAL` incidents remain queued and visible in the daily digest. Each local queue scan queries the full unresolved queue, so correctness does not depend on a missed local schedule being replayed automatically.

### 6.3 Prohibited Mechanism

No personal Mac or other machine will be registered as a GitHub Actions self-hosted runner for this architecture.

## 7. Pipeline Registry

The pipeline registry is the control plane's declarative source of truth. It references existing dataset contracts instead of duplicating them.

Illustrative entry:

```yaml
openrouter-provider-activity:
  workflow: openrouter-provider-activity-daily.yml
  cadence: daily
  criticality: high
  outputs:
    - dataset: openrouter_provider_activity
      contract: dashboard.data.DATASET_REGISTRY
  freshness:
    max_age: 2d
    regression_forbidden: true
  allowed_degradation:
    retain_previous_output: true
    max_consecutive_runs: 1
  capabilities:
    cloud:
      - http
      - browser
    local:
      - residential_network
      - local_cache
  autonomy:
    retry: automatic
    patch: automatic
    merge: low_risk_only
```

Each entry defines:

- Stable pipeline identifier and workflow name.
- Cadence and expected-release behavior.
- Criticality and incident SLA.
- Required and optional outputs.
- Existing contract references.
- Freshness and non-regression requirements.
- Permitted degradation and retention duration.
- Cloud and local investigation capabilities.
- Retry, repair, and merge policy.

Release calendars take precedence over naive wall-clock freshness for monthly, quarterly, or irregular official sources.

## 8. Standard Run Report

Every integrated pipeline emits `run-report.json` even when an earlier workflow step fails. The finalizer runs with `if: always()` and must not change the original workflow conclusion in Phase 0.

The report includes:

```yaml
schema_version: 1
pipeline_id: openrouter-provider-activity
run_id: 123456
commit_sha: abc123
started_at: 2026-09-08T01:30:00Z
finished_at: 2026-09-08T01:38:00Z
execution: success
collection: partial
data_health: stale
publication: retained_previous
evidence_quality: incomplete
checks: []
outputs: []
evidence: []
```

The dimensions are intentionally independent:

- **Execution:** `success`, `failed`, `cancelled`, or `unknown`.
- **Collection:** `complete`, `partial`, `failed`, or `unknown`.
- **Data health:** `fresh`, `stale`, `regressed`, `missing`, `invalid`, or `unknown`.
- **Publication:** `published`, `retained_previous`, `blocked`, `failed`, or `not_applicable`.
- **Evidence quality:** `verified`, `incomplete`, or `conflicting`.

The control plane derives human-facing incident states from these dimensions. It never infers overall health from the Actions conclusion alone.

Run reports are uploaded as GitHub Actions artifacts and are not committed to Git on every run.

## 9. Deterministic Health Evaluation

An incident signal is produced by ordinary code when any registered condition is met:

- Workflow execution failed.
- A required output is absent or empty.
- Schema, type, natural-key, or uniqueness validation failed.
- The latest observation period regressed.
- The source exceeded its release-aware freshness allowance.
- Coverage or row count fell beyond a registered threshold.
- A producer failed and publication retained an older artifact.
- Consecutive degraded runs exceeded the registered allowance.
- Language variants or downstream artifacts disagree.
- The workflow did not run within its expected scheduling window.

Codex does not create the initial signal by interpreting a dashboard or log from scratch. It receives a structured signal and its supporting evidence.

## 10. Evidence and Anti-Assumption Policy

Every Codex diagnosis must separate:

- **Observed:** directly supported by a run log, file, request, rendered page, DOM snapshot, network response, screenshot, or reproducible command.
- **Inferred:** a hypothesis that explains observations but is not directly verified.
- **Unknown:** a material question for which current evidence is insufficient.

Negative claims are scoped to the observation method and timestamp. For example:

```yaml
observed:
  - statement: Static extraction did not find the Meta Activity chart.
    observed_at: 2026-09-04T01:35:00Z
    method: static_http_extractor
inferred:
  - The route, page layout, or rendering behavior may have changed.
unknown:
  - Whether the chart was removed permanently.
  - Whether the chart remained available after client-side rendering.
required_next_evidence:
  - rendered_page
  - dom_snapshot
  - network_responses
```

A permanent-removal claim requires stronger evidence than a single static extraction failure. The agent must escalate from static request to rendered browser and, when needed, DOM and network inspection.

Evidence records include the run URL, commit SHA, timestamps, check identifier, relevant logs, and retained raw or rendered artifacts. All evidence is redacted before leaving the execution environment.

## 11. Incident Lifecycle

Incidents use a stable fingerprint:

```text
pipeline_id + failed_check + normalized_error_class
```

Repeated occurrences update the existing active incident.

```text
DETECTED
  -> RETRYING
  -> TRIAGING_CLOUD
       -> FIXING
       -> NEEDS_LOCAL -> TRIAGING_LOCAL
       -> NEEDS_HUMAN
  -> VALIDATING
  -> RECOVERED
  -> CLOSED
```

Additional rules:

- A merged pull request does not imply recovery.
- Recovery requires a rerun of the original pipeline and restored data health.
- A recurrence reopens the original incident when the fingerprint matches.
- Repeated recovery and recurrence is marked `FLAPPING`.
- Multiple pipelines with one root cause are grouped under a parent incident.
- Unchanged incidents do not generate repetitive notifications.

The initial incident store will be GitHub Issues in a private `alternative-data-ops` repository. The public repository contains code, contracts, and sanitized health summaries; sensitive operational evidence and local-agent queues stay private.

## 12. Autonomous Repair and Merge Policy

### 12.1 Autonomy Levels

| Level | Class | Default action |
| --- | --- | --- |
| L0 | Transient timeout, rate limit, or upstream 5xx | Retry automatically |
| L1 | Deterministic operational repair such as cache cleanup or publication conflict handling | Repair and rerun |
| L2 | Small, single-domain code fix such as a selector or field adapter | Patch, test, push PR, and auto-merge if all gates pass |
| L3 | Semantic, destructive, security-sensitive, broad, or ambiguous change | Require human decision |

### 12.2 Auto-Merge Gates

All of the following must pass:

1. The incident is reproducible or supported by decisive evidence.
2. A regression test fails before the fix and passes after it.
3. The patch is scoped to one registered pipeline or domain.
4. Targeted tests, domain tests, and dataset contracts pass.
5. A live canary writes to a temporary destination and passes freshness, coverage, and non-regression checks.
6. The deterministic risk policy finds no protected change.
7. The original pipeline succeeds after merge.
8. The derived data-health state returns to `HEALTHY`.

### 12.3 Protected Changes

Codex may investigate and prepare a pull request, but it must not auto-merge:

- `.config`, token, credential, or secret-handling changes.
- GitHub workflow permission, authentication, or runner changes.
- Dataset schema, natural key, metric definition, or release-calendar semantics.
- Point-in-time, lineage, or look-ahead behavior.
- Historical deletion, rewriting, or broad backfill.
- Cross-repository interface changes.
- Conversion of missing or not-covered observations into zero.
- Claims or code paths that treat extraction absence as permanent source removal.
- Reduced quality thresholds, removed tests, or new error suppression.

Ordinary workflow changes may later be auto-merged only through explicitly approved declarative parameters or templates. Arbitrary workflow YAML changes remain protected.

### 12.4 Loop Limits

Each incident permits:

- One deterministic retry.
- At most two Codex patch attempts.
- At most one automatic revert.

Exhaustion, conflicting evidence, or a new regression changes the incident to `NEEDS_HUMAN`.

Code changes follow:

```text
branch -> commit -> push -> pull request -> policy checks -> auto-merge
```

Codex does not push code directly to `main`. Validated routine data publication may eventually commit to `main`, but only through the serialized publisher.

## 13. Publication Plane

The current pattern allows multiple workflows to modify overlapping generated files and independently run `git pull --rebase && git push`. The target architecture replaces this with:

```text
producer workflows
  -> validated immutable artifacts
  -> publication queue
  -> one serialized publisher
  -> one publication commit
```

The publisher:

- Uses one concurrency group.
- Revalidates artifacts against the current publication base.
- Rejects stale or conflicting artifacts instead of resolving them implicitly.
- Commits only the validated publication set.
- Records source run IDs in the publication report.

Phase 0 does not change existing publication behavior. Publisher migration occurs only after shadow telemetry and incident handling are validated.

## 14. Scheduling and Triggering

Only two Codex scheduled tasks are planned:

1. **Cloud Ops Brief:** daily at 09:00 Asia/Taipei. Monday's run includes the weekly reliability section.
2. **Local Incident Worker:** every two hours while the Mac and Codex application are available. It remains silent when the `NEEDS_LOCAL` queue is empty.

Other activity is not implemented as Codex scheduled tasks:

| Action | Mechanism |
| --- | --- |
| Pipeline health evaluation | Final step in each integrated GitHub workflow |
| Automatic retry | GitHub Actions workflow logic |
| Cloud Codex triage | Incident-driven GitHub workflow or API invocation |
| Global reconciliation | GitHub Actions cron every six hours |
| Daily and weekly reporting | One cloud Codex scheduled task |
| Local queue processing | One local Codex scheduled task |

The local worker always scans the complete unresolved queue. The architecture does not assume that a schedule missed while the Mac is offline will be replayed.

## 15. Reporting and Notification

The daily report contains:

- Healthy pipeline count.
- New and open incidents.
- Automatically recovered incidents.
- Stale, regressed, partial, or retained datasets.
- Incidents waiting for local Codex.
- Incidents requiring human input.
- Evidence links and concise recovery summaries.

Even when all pipelines are healthy, the daily report emits a short confirmation because the user explicitly requested daily reporting.

Immediate notification is reserved for:

- Possible data corruption or deletion.
- Multiple critical pipeline failures.
- Failed automatic revert.
- Secret, permission, schema, semantic, or backfill decisions.
- Conflicting evidence that prevents a safe conclusion.
- Incident SLA breach.

Successful retries, completed low-risk repairs, unchanged known incidents, and non-critical `NEEDS_LOCAL` work appear in the daily report without immediate interruption.

## 16. Repository Layout

The planned layout is:

```text
alternative-data/
├── config/ops/
│   ├── pipelines.yaml
│   └── autonomy.yaml
├── schemas/ops/
│   ├── run-report.schema.json
│   └── incident.schema.json
├── src/ops_control/
│   ├── health.py
│   ├── evidence.py
│   ├── incidents.py
│   ├── risk_policy.py
│   ├── publisher.py
│   └── reporting.py
├── scripts/ops/
│   ├── finalize_pipeline.py
│   └── reconcile_all.py
├── tests/ops/
│   └── fixtures/
└── .github/workflows/
    ├── ops-reconcile.yml
    ├── ops-incident-triage.yml
    └── ops-publish.yml
```

Existing domain validators remain in place initially and are invoked through adapters. This minimizes migration risk and avoids unrelated refactoring.

## 17. Rollout

### Phase 0: Shadow Telemetry

Pilot pipelines:

1. OpenRouter Provider Activity Daily.
2. Asia Markets Dashboard Data Refresh Daily.
3. Semiconductor Memory Monthly.

Deliverables:

- Pipeline registry entries for the three pilots.
- Versioned run-report JSON Schema.
- Typed run-report parsing and validation.
- Deterministic health evaluation using existing validators.
- Shadow finalizer integration with `if: always()`.
- Uploaded run reports and evidence manifests.
- Unit tests, schema fixtures, and fixtures representing known historical failures.

Phase 0 behavior:

- It does not create or update incidents.
- It does not call Codex.
- It does not retry failed pipelines.
- It does not modify merge policy.
- It does not create scheduled tasks.
- It does not change publication.
- Shadow telemetry failures are visible but do not alter the original pipeline conclusion.

### Phase 1: Incident Mode

- Add deterministic retries.
- Add private incident storage and fingerprinting.
- Add six-hour reconciliation.
- Add the daily cloud digest.
- Codex investigates but does not merge repairs.

### Phase 2: Repair Mode

- Codex prepares repair branches and pull requests.
- All repairs require review while real incidents calibrate the policy.
- Protected-path and regression-test gates run in enforcement mode.

### Phase 3: Autonomous Mode

- Enable L0 through L2 autonomous handling.
- Auto-merge qualifying low-risk repairs.
- Rerun original pipelines and automatically revert failed fixes.

### Phase 4: Publication Migration

- Introduce the serialized publisher.
- Migrate workflows in small domain groups.
- Remove direct overlapping publication only after parity checks pass.

### Phase 5: Full Coverage

- Register remaining pipelines.
- Enable the Local Codex `NEEDS_LOCAL` worker.
- Add parent-incident correlation and weekly reliability trends.

## 18. Testing Strategy

The control plane requires:

- JSON Schema validation for run reports and incidents.
- Registry validation for duplicate IDs, missing workflows, invalid contract references, and impossible cadence settings.
- Unit tests for every derived health state.
- Golden fixtures for:
  - Green workflow with stale data.
  - Partial collection with retained publication.
  - Observation-period regression.
  - Missing required provider.
  - Publication conflict followed by secondary parse failure.
  - Missed schedule.
  - Incomplete and conflicting evidence.
- Risk-policy tests proving protected changes cannot auto-merge.
- Secret-redaction tests for logs and evidence manifests.
- End-to-end shadow runs for all three pilots.
- Publication concurrency tests before Phase 4.

Historical incident fixtures should preserve the original evidence semantics without embedding credentials or sensitive payloads.

## 19. Phase 0 Acceptance Criteria

Phase 0 is complete when:

1. All three pilot pipelines have valid registry entries.
2. Each pilot emits a schema-valid run report on success and failure.
3. Run reports independently represent execution, collection, data health, publication, and evidence quality.
4. Known stale, retained, regressed, and missing-provider fixtures produce the expected health result.
5. The shadow finalizer cannot mask or replace the original workflow conclusion.
6. No run report or evidence artifact contains values from `.config` or registered secret patterns.
7. Existing pipeline outputs and publication behavior remain unchanged.
8. No self-hosted runner, incident automation, Codex invocation, scheduled task, or auto-merge rule is introduced.

## 20. Alternatives Considered

### GitHub Actions Overlay Only

Adding a watcher and daily summary without a standardized control plane would be quicker, but direct publication conflicts, inconsistent data-health semantics, and evidence quality would remain unresolved.

### Full Orchestrator Migration

Moving immediately to Airflow, Dagster, Prefect, or a similar platform would provide richer orchestration but require a high-risk migration of more than forty workflows. The current design keeps that option open without making it a prerequisite.

### GitHub Actions Self-Hosted Runner on the User's Mac

This was rejected. The repository is public, the Mac contains local credentials and data, and the user explicitly prohibited self-hosted runners. Local Codex provides the needed local context without exposing the Mac as a GitHub job executor.

## 21. Final Decisions

- Cloud-first operations with best-effort Local Codex augmentation.
- No GitHub Actions self-hosted runners.
- Deterministic detection before agent reasoning.
- Multi-dimensional health instead of treating workflow success as pipeline health.
- Evidence-scoped claims with explicit unknowns.
- Policy-controlled autonomous repair and auto-merge.
- One daily cloud report and one best-effort local queue task.
- Serialized publication as a later migration.
- Three-pipeline shadow-mode pilot before incident or repair automation.
