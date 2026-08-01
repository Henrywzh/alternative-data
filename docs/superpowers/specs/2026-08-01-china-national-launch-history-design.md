# China National Launch History Design

Date: 2026-08-01
Status: Proposed for implementation review
Scope: HK commercial aerospace sector data pipeline and Cloudflare artifact

## Objective

Add a source-backed Chinese national/state launch history to the Hong Kong
commercial aerospace sector without changing the meaning of the existing
private/commercial-provider series. The deliverable must retain one row per
launch, preserve payload information, enrich records with Launch Library 2
where a reliable match exists, distinguish `national_program`,
`state_owned_commercial`, and `commercial_provider`, and expose comparable
monthly series plus a launch-detail table.

## Current state

The existing Launch Library 2 integration in
`src/hk_commercial_aerospace/sources/launch_library.py` fetches exact provider
IDs for seven Chinese commercial launch providers. It emits a provider/status
monthly summary and a zero-filled commercial total. It does not currently
persist national-program history.

The current artifact therefore keeps two concepts separate:

- `launch_monthly`: provider/status detail for configured commercial providers.
- `launch_monthly_total`: zero-filled monthly total for those commercial
  providers only.

Upcoming LL2 rows already include national and state-owned-commercial providers,
but upcoming discovery is not evidence of a historical launch baseline. Those
rows must not be appended to the historical series merely because their
provider names contain `China`.

## Source contract and authority order

### 1. Official primary baseline

The China Academy of Launch Vehicle Technology (CALT) first-party launch
record is the authoritative event baseline for the Long March and Jielong
families. Its table publishes launch date, launch vehicle, launched
satellite/spacecraft, launch site, series count, and result:

- <https://calt.spacechina.com/n482/n505/index.html>
- <https://calt.spacechina.com/n689/c30035/content.html>
- <https://www.spacechina.com/n25/n2014789/n2014809/c1905825/content.html>

The parser must discover and follow the official archive/pagination links where
available. It must preserve the source page and raw response for every
extraction run. A page that cannot be parsed is recorded as an unparsed source;
it must not produce inferred launch rows.

The official record is the inclusion authority. A launch that appears in LL2
but cannot be matched to the official baseline remains a candidate/cross-check
row and is excluded from the authoritative national monthly total until
verified.

### 2. Structured enrichment and cross-check

Launch Library 2 is used to supply structured fields and to match official
events when possible. Candidate fields include exact launch time, mission name,
launch-service provider, pad, orbit, mission type, status, and LL2 payload
objects. LL2 is rate-limited and may be served from a cached snapshot, so every
match records whether the enrichment came from a live response or cache.

LL2 is never counted as a second launch when an official row already represents
the event. The free-tier request budget remains bounded by the existing
`LL2_MAX_REQUESTS_PER_HOUR` guard.

### 3. Explicit coverage gaps

Kuaizhou/CASIC, other state launch families, military/experimental events, and
future provider names are not silently classified from keywords. They may be
added through additional official source adapters after their source contract
has been verified. Until then, the source-health/status metadata should say
that they are outside the authoritative V1 baseline.

## Classification contract

Classification is an explicit mapping maintained in configuration, not an
inference from launch-site names or the presence of the word “China”.

| `program_class` | V1 meaning | Examples |
|---|---|---|
| `national_program` | State national missions carried by the Long March family | Long March launches whose official task is a national civil-space, crewed, cargo, or state satellite mission |
| `state_owned_commercial` | Commercially operated launch products of a state-owned aerospace group | Jielong/Smart Dragon launches operated by China Rocket Co. |
| `commercial_provider` | Existing configured commercial providers | LandSpace, Galactic Energy, CAS Space, Orienspace, Deep Blue Aerospace, i-Space, Space Pioneer |

The mapping must allow `classification_status = verified|candidate|unknown`.
Unknown or candidate rows remain visible in provenance/debug output but are not
included in the verified comparison series.

## Data model

### Event table: `china_launch_events`

One row represents one rocket launch, regardless of how many payloads it
carries. Required fields:

- `event_id`: stable internal ID; official series number plus normalized date,
  vehicle, and site where no LL2 ID exists.
- `official_sequence`: official Long March/Jielong sequence when published.
- `launch_date`, `launch_time`, `launch_time_precision`.
- `rocket_name`, `rocket_family`, `rocket_variant`.
- `mission_name`, `mission_type`, `target_orbit`.
- `launch_site`, `launch_pad`.
- `outcome`, `outcome_normalized`.
- `program_class`, `classification_status`.
- `payload_summary`, `payload_count`.
- `official_source_url`, `official_source_id`, `ll2_launch_id`.
- `ll2_match_status`, `ll2_match_confidence`.
- `source_snapshot`, `fetched_at`, and `parser_version`.

The event row carries a concise payload summary for the dashboard. It does not
flatten multiple payloads into fake separate launches.

### Payload table: `china_launch_payloads`

One row per payload when the source provides separable payload names:

- `event_id`, `payload_index`, `payload_name`, `payload_type`;
- `operator_or_owner`, `country_or_region`, `orbit` where published;
- `source_url`, `source_snapshot`, `fetched_at`.

When an official source only publishes a combined text string, retain that
string in the event row and leave the child rows empty; do not invent a payload
count from punctuation. A published phrase such as “一箭七星” may provide a
verified count, but the parser should preserve the original text as evidence.

### Monthly comparison table: `china_launch_monthly`

One row per `month × program_class` with zero-filled months between the first
and last verified event. Required fields:

- `month` (`YYYY-MM`);
- `program_class`;
- `launch_count`;
- `successful_launch_count`;
- `failed_launch_count`;
- `unknown_outcome_count`;
- `verified_event_count`;
- `source_coverage_note`.

The existing `launch_monthly` and `launch_monthly_total` datasets remain in the
artifact as the commercial-provider-only views. The new comparison dataset is
additive and must not overwrite those fields.

## Reconciliation and deduplication

1. Parse official rows into a deterministic event key.
2. Match LL2 by exact `ll2_launch_id` when it is already known.
3. Otherwise match only when date, normalized rocket family, and launch site
   agree; use mission/payload text as supporting evidence.
4. Store the match score and match method. Do not silently upgrade a weak
   text-only match to verified.
5. If two official rows appear to describe the same event, retain both raw
   observations and emit one canonical event only when the official sequence,
   date, and vehicle agree.
6. Never aggregate official and LL2 rows independently. Source rows are
   evidence; canonical events are the unit counted in monthly totals.

## Dashboard contract

Add these datasets/charts to the commercial aerospace artifact:

1. `china_launch_monthly` line chart: verified national-program vs
   state-owned-commercial vs existing commercial-provider launches.
2. Rocket-family history: verified launch count by family, with a clear note
   that this is launch count rather than payload count.
3. `china_launch_events` detail table: newest verified launches first, showing
   date, mission, rocket, class, site, payload summary, and outcome.
4. A compact coverage note: official baseline date range, LL2 enrichment
   status, and excluded families such as Kuaizhou/CASIC until separately
   verified.

The existing commercial-only chart title/subtitle must remain explicit. The
new national comparison must not imply that all Chinese launches, military
launches, or every state-owned family are covered unless the source-health
metadata proves that coverage.

## Raw and normalized storage

- Raw official HTML/JSON/PDF responses:
  `data/raw/hk_commercial_aerospace/` with source URL, fetch time, and content
  hash.
- Canonical event history:
  `data/normalized/hk_commercial_aerospace/china_launch_events.jsonl`.
- Payload history:
  `data/normalized/hk_commercial_aerospace/china_launch_payloads.jsonl`.
- Parser/source manifest:
  `data/normalized/hk_commercial_aerospace/china_launch_manifest.json`.

The normal dashboard build may use the latest cached normalized history. A
dedicated backfill command owns the full official archive download and must not
force every routine build to re-download the entire history.

## Verification and acceptance criteria

The implementation is not complete until all of the following are evidenced:

- official Long March and Jielong rows are present with source URLs and raw
  snapshots;
- no LL2-only candidate is counted in the verified national series;
- event IDs are unique and duplicate official/LL2 records collapse to one
  canonical launch;
- payload text/counts are retained without creating extra launches;
- all three program classes exist in the normalized schema, with explicit
  classification status;
- monthly series are zero-filled and reconcile exactly to canonical event
  counts;
- existing commercial-only monthly datasets are unchanged in meaning;
- artifact rebuild passes, focused tests pass, and both Chinese/English pages
  show the new chart and detail table in a real browser;
- source-health/status output states the actual coverage range and unresolved
  families;
- the full dashboard packaging and the existing aerospace tests pass.

## Non-goals for this delivery

- No military launch classification beyond what the official source explicitly
  labels.
- No Kuaizhou/CASIC baseline until a verified first-party historical source is
  found and its parser contract is reviewed.
- No satellite constellation history inferred from launch count.
- No Streamlit redesign in this change; structural artifact changes will be
  recorded for the existing parity reminder workflow.
