# X-Only AI and Semiconductor Intelligence Engine

## 1. Objective

Build a configurable sector-intelligence engine for AI, LLMs and semiconductors.

It should not be positioned as:

> An AI tool that summarises X.

It should be:

> A system that detects emerging sector events on X, tracks how evidence evolves, maps events to companies and value-chain exposures, and delivers different intelligence to different investment pods.

Because the first version uses only X, it can state:

* official X-account announcement;
* provider-reported benchmark claim;
* independently tested by developers on X;
* supported by several apparently independent X sources;
* widely discussed on X.

It should not claim external verification or objective truth.

---

## 2. Core architecture

```text
X API
→ post normalisation and relationship reconstruction
→ relevance filtering
→ entity and claim extraction
→ event clustering
→ evidence and provenance tracking
→ event summarisation
→ sector-impact mapping
→ pod-specific routing
→ alerts and briefs
```

The system has three layers:

### Shared intelligence layer

Common across pods:

* posts;
* entities;
* claims;
* events;
* evidence state;
* sector implications.

### Pod configuration layer

Each pod defines:

* companies and technologies;
* subsectors and geographies;
* suppliers and customers;
* investment horizon;
* priority event types;
* active research theses;
* alert sensitivity.

### Output layer

For each pod, answer:

```text
What happened?
What changed?
What is confirmed or uncertain?
Which companies are affected?
Through what economic channel?
What should the analyst monitor next?
```

---

## 3. Initial sector scope

Focus on the AI-compute value chain:

```text
Model development and adoption
→ cloud and compute demand
→ accelerators and networking
→ HBM and memory
→ foundry and advanced packaging
→ semiconductor equipment
→ data-centre infrastructure
```

Initial topics:

* model releases and benchmarks;
* API pricing and open weights;
* developer adoption;
* hyperscaler capex;
* GPUs and custom accelerators;
* HBM and memory;
* foundry capacity and yields;
* advanced packaging;
* semiconductor equipment;
* export controls and regulation.

---

## 4. X collection strategy

Use three collection methods.

### Curated accounts

Monitor:

* official company and model-lab accounts;
* researchers and engineers;
* benchmark evaluators;
* semiconductor analysts;
* specialist journalists;
* credible pseudonymous accounts;
* fast aggregators.

### Topic streams

Track combinations of:

* company names and tickers;
* model and product names;
* benchmark names;
* semiconductor technologies;
* event terms such as delay, yield, capacity and pricing.

### Search recovery

Streaming connections may fail. Store ingestion checkpoints and use recent search to recover missing posts without duplication.

---

## 5. Source and provenance model

Do not use one universal source-reputation score.

Classify accounts by role:

| Role                 | Function                           |
| -------------------- | ---------------------------------- |
| Official             | Company or provider statement      |
| First-hand technical | Testing or direct observation      |
| Journalist           | Source-based reporting             |
| Industry analyst     | Sector interpretation              |
| Benchmark evaluator  | Model-performance testing          |
| Aggregator           | Fast redistribution                |
| Commentator          | Opinion and reaction               |
| Unknown              | Discovery source requiring caution |

Authority should be topic-specific.

The system must distinguish:

* original post;
* repost;
* quote post;
* reply;
* thread continuation;
* copied or paraphrased information;
* multiple posts derived from one source.

Twenty accounts repeating one official announcement still represent one evidence origin.

---

## 6. Entities and taxonomy

Resolve aliases such as:

```text
TSMC / Taiwan Semiconductor / 台积电 / TSM
NVIDIA / NVDA / 英伟达 / Blackwell / GB200
Moonshot AI / 月之暗面 / Kimi / Kimi K3
```

Start with a compact event taxonomy.

### AI events

* model release;
* benchmark result;
* pricing change;
* API or weight availability;
* technical architecture;
* partnership;
* developer adoption;
* outage or security;
* regulation.

### Semiconductor events

* product launch;
* capacity or capex change;
* production or yield issue;
* shipment or qualification;
* supply constraint;
* design win or loss;
* pricing or demand;
* regulation.

---

## 7. Event and claim engine

Posts are observations; events are the main intelligence objects.

For each new post:

1. retrieve candidate events using embeddings, entities, time, URLs and X relationships;
2. determine whether it starts a new event or updates an existing one;
3. classify the post as:

   * new claim;
   * confirmation;
   * contradiction;
   * correction;
   * analysis;
   * repetition;
4. update the event state only when material information changes.

Example:

```text
Kimi K3 event
→ release rumour
→ official X announcement
→ benchmark claims
→ API and pricing details
→ developer testing
→ contradictory results
```

Each atomic claim should retain:

* source post;
* supporting text;
* author;
* provider claim or independent observation;
* supporting and contradicting sources;
* evidence status;
* timestamps.

Evidence labels:

```text
E0 — unknown single source
E1 — established specialist
E2 — multiple apparently independent sources
E3 — official X-account statement
E4 — official statement plus independent X-based observations
```

---

## 8. Summary and impact mapping

A summary should separate:

```text
What happened
What changed
Official statements
Provider claims
Independent X observations
Contradictions
Unknowns
Affected entities
Impact channels
```

The higher-value feature is impact mapping:

```text
Event
→ affected company or value-chain node
→ economic channel
→ direction
→ time horizon
→ uncertainty
```

For example, a more efficient model could imply:

* lower compute cost per task;
* higher AI adoption;
* more aggregate inference demand;
* pricing pressure for model providers;
* ambiguous accelerator-demand impact.

The engine should preserve ambiguity rather than force a bullish or bearish conclusion.

---

## 9. Pod-specific routing

There should not be one universal news score.

Shared event features:

* novelty;
* evidence state;
* event type;
* source authority;
* independent-source breadth;
* discussion acceleration.

Pod-specific features:

* company overlap;
* technology overlap;
* value-chain relevance;
* thesis relevance;
* investment horizon;
* alert tolerance.

Route each event as:

```text
Immediate
Daily
Weekly
Suppress
```

Example:

| Event                  | AI pod    | Semiconductor pod | China-tech pod |
| ---------------------- | --------- | ----------------- | -------------- |
| Kimi K3 frontier claim | Immediate | Daily             | Immediate      |
| HBM capacity update    | Daily     | Immediate         | Daily          |
| Minor API feature      | Daily     | Suppress          | Daily          |

---

## 10. Delivery system

Use four outputs from the same event database.

### Immediate alert

Trigger when:

```text
Pod relevance is high
AND materiality is high
AND the event state changed materially
AND the evidence is official, independently supported,
or extremely important despite being unconfirmed
```

Subject labels should show evidence status:

```text
[RUMOUR]
[OFFICIAL X ANNOUNCEMENT]
[PROVIDER-CLAIMED]
[INDEPENDENTLY TESTED ON X]
[DISPUTED]
[CORRECTED]
```

Immediate alerts should contain:

* what happened;
* why it matters;
* what is supported;
* what remains uncertain;
* affected entities;
* key X sources;
* what to watch next.

### Event update

Send when an alerted event receives:

* official confirmation;
* correction or denial;
* benchmark evidence;
* API, weight or pricing availability;
* major technical details;
* customer or deployment confirmation.

### Daily brief

Answer:

> What materially changed today?

Include:

* executive summary;
* top events;
* updates to existing events;
* pod watchlist implications;
* unverified but noteworthy reports.

### Weekly review

Answer:

> Which sector narratives strengthened or weakened?

Include:

* major event clusters;
* emerging themes;
* value-chain implications;
* thesis-supporting and contradicting evidence;
* next week’s catalysts.

Core principle:

> Immediate alerts report events; daily briefs report changes; weekly reviews report meaning.

---

## 11. Data, evaluation and infrastructure

Core data objects:

```text
posts
post_relationships
sources
entities
claims
events
event_versions
event_impacts
themes
pod_profiles
pod_routes
alerts
briefs
feedback
model_runs
```

Store separate timestamps for:

* X publication;
* ingestion;
* processing;
* event update;
* alert delivery.

Evaluation should measure:

* event merge and split accuracy;
* duplicate-event rate;
* unsupported summary claims;
* missed material facts;
* alert precision and latency;
* duplicate alerts;
* pod usefulness.

Feedback options:

```text
Useful
Relevant but not urgent
Duplicate
Irrelevant
Misleading summary
Should have alerted sooner
Wrong delivery tier
```

Initial infrastructure:

```text
X API
→ Python async ingestion
→ lightweight durable queue
→ PostgreSQL and pgvector
→ background workers
→ external embedding and LLM APIs
→ email delivery
```

Kafka, Flink, GraphRAG and self-hosted large models are unnecessary for the first version.

---

## 12. MVP

The first version should:

1. monitor 100–300 selected X accounts;
2. run narrow AI and semiconductor topic rules;
3. reconstruct repost, quote, reply and thread relationships;
4. resolve major entities and aliases;
5. cluster posts into evolving events;
6. extract claims and evidence state;
7. generate evidence-aware summaries;
8. map events to sector impact channels;
9. route events by pod;
10. send immediate, daily and weekly emails;
11. collect analyst feedback;
12. support historical replay.

The core product is:

```text
X posts
→ provenance
→ claims
→ evolving events
→ evidence state
→ sector implications
→ pod-specific delivery
```
