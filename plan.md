I think this is the **right initial product scope**. A generic financial-news engine is difficult to differentiate because Bloomberg, Reuters, AlphaSense and numerous aggregators already summarise broad news. A **pod-configurable AI and semiconductor intelligence engine** has a clearer edge:

* the information is fragmented across X, company blogs, research accounts, GitHub, Hugging Face, arXiv, regulatory notices and supply-chain commentary;
* much of the useful information appears before it becomes conventional financial news;
* interpreting it requires sector-specific relationships;
* different pods genuinely care about different implications from the same event.

The important conceptual change is:

> Do not build “a Twitter summariser for semiconductor news.”
> Build a **sector event engine in which X is one discovery source**.

## 1. The product should have three layers

### Shared sector-intelligence layer

This is common across all users and pods:

```text
Sources
→ posts/documents
→ entities and claims
→ events
→ corroboration
→ evolving event state
→ sector impact channels
```

It should understand the AI-compute ecosystem independently of any particular portfolio.

### Pod configuration layer

Each pod defines:

* companies and private competitors it follows;
* subsectors;
* geographies;
* investment horizon;
* event types considered material;
* trusted or distrusted sources;
* immediate-alert thresholds;
* existing theses or key questions.

### Analyst-facing output layer

The same event is then rendered differently depending on the pod:

```text
What happened?
What changed from the previous state?
Which companies are exposed?
Through what economic mechanism?
What is confirmed versus speculative?
What should the analyst investigate next?
```

That is much more useful than a generic summary.

---

# 2. “Importance” must be pod-specific

There should not be one universal news score.

Suppose there is a reported delay in advanced packaging capacity.

For different pods:

| Pod                      | Potential relevance                                 |
| ------------------------ | --------------------------------------------------- |
| GPU designers            | Shipment timing and revenue recognition             |
| Foundries                | Capacity constraints and customer allocation        |
| HBM manufacturers        | Demand timing and inventory implications            |
| Semiconductor equipment  | Potential additional capex or bottleneck resolution |
| Hyperscalers             | AI infrastructure deployment delays                 |
| Software/application pod | Probably low immediate relevance                    |

The underlying event has one shared factual state, but several pod-specific interpretations.

Therefore:

[
\text{AlertPriority}_{e,p}
==========================

f(\text{event }e,\ \text{pod }p)
]

A practical decomposition would be:

[
P_{e,p}
=======

R_{e,p}
\times M_{e,p}
\times N_e
\times U_{e,p}
\times E_e
]

where:

* (R_{e,p}): relevance to the pod;
* (M_{e,p}): potential materiality;
* (N_e): novelty relative to the existing event state;
* (U_{e,p}): urgency for that pod;
* (E_e): evidence strength.

I would keep evidence strength visible separately rather than allowing a low-evidence event to disappear automatically. A highly material rumour may deserve an “emerging/unverified” alert.

---

# 3. Define the sector more carefully

“AI, LLM and semiconductors” is still an extremely large universe. I would organise it hierarchically.

## Level 0: AI ecosystem

## Level 1: major domains

| Domain             | Examples                                               |
| ------------------ | ------------------------------------------------------ |
| Foundation models  | model releases, benchmarks, capabilities, pricing      |
| Developer adoption | GitHub, Hugging Face, APIs, frameworks, usage          |
| AI applications    | enterprise adoption, vertical software, agents         |
| Cloud and compute  | hyperscaler capex, GPU deployment, inference economics |
| Accelerators       | GPUs, ASICs, custom silicon, networking                |
| Memory             | HBM, DRAM, NAND                                        |
| Foundry            | leading-edge capacity, yields, node transitions        |
| Packaging          | CoWoS, advanced packaging, substrates                  |
| Equipment          | lithography, deposition, etch, inspection              |
| Data centres       | power, cooling, construction, interconnect             |
| Regulation         | export controls, model regulation, antitrust           |
| Geopolitics        | Taiwan, China, supply security, strategic materials    |

For the first version, I would choose a coherent chain:

```text
Model development and adoption
        ↓
Compute demand
        ↓
Accelerators and networking
        ↓
HBM and memory
        ↓
Foundry and packaging
        ↓
Semiconductor equipment
        ↓
Data-centre power and infrastructure
```

This gives the system an economic logic. It is preferable to collecting every item containing the word “AI.”

---

# 4. The real differentiator is impact mapping

Summaries and categories are necessary, but they will not be the strongest feature. Most modern tools can generate decent summaries.

The higher-value feature is:

```text
Event
→ affected entity
→ economic channel
→ possible direction
→ time horizon
→ uncertainty
```

For example:

```json
{
  "event": "Major cloud provider introduces lower-priced inference service",
  "impact_paths": [
    {
      "entity_group": "AI application companies",
      "channel": "lower inference cost",
      "direction": "positive",
      "horizon": "near_to_medium_term",
      "confidence": "high"
    },
    {
      "entity_group": "GPU suppliers",
      "channel": "higher inference adoption but lower compute intensity per query",
      "direction": "ambiguous",
      "horizon": "medium_term",
      "confidence": "medium"
    },
    {
      "entity_group": "cloud competitors",
      "channel": "pricing pressure",
      "direction": "negative",
      "horizon": "near_term",
      "confidence": "medium"
    }
  ]
}
```

Notice that the output is not simply “bullish for NVIDIA” or “bearish for NVIDIA.” For many AI-sector developments, the first-order and second-order effects conflict.

The system should therefore support:

* direct effects;
* second-order effects;
* bull and bear interpretations;
* affected KPIs;
* likely time horizon;
* unresolved questions.

That is closer to actual analyst reasoning.

---

# 5. Sector ontology and entity graph

You need enough domain structure to understand relationships such as:

```text
Model company
→ cloud provider
→ accelerator supplier
→ foundry
→ HBM supplier
→ packaging provider
→ equipment supplier
```

But I would not immediately build a huge Neo4j knowledge graph.

A relational model is sufficient initially:

```text
entities
entity_aliases
products
technologies
entity_relationships
events
claims
event_entities
event_impacts
sources
source_lineage
pod_watchlists
pod_event_scores
```

Example relationships:

* supplies;
* customer_of;
* manufactures_for;
* competes_with;
* owns;
* partners_with;
* depends_on;
* exposed_to_technology;
* exposed_to_geography;
* produces_product;
* provides_equipment_for_process.

Entity resolution is especially important in this sector because the same concept may appear as:

```text
TSMC
Taiwan Semiconductor
台积电
2330 TT
TSM
```

Similarly, products and technical terms need aliases:

```text
Blackwell
B100
B200
GB200
NVL72
```

Without this entity layer, pod-level relevance will remain mostly keyword matching.

---

# 6. Source design for this sector

X is valuable here because researchers, engineers, developers, journalists and specialist industry accounts often discuss developments quickly.

But the source hierarchy should include:

### Primary sources

* company announcements;
* model cards;
* technical papers;
* GitHub repositories;
* Hugging Face releases;
* benchmark repositories;
* regulatory publications;
* earnings releases and transcripts;
* official product documentation.

### Specialist secondary sources

* semiconductor journalists;
* supply-chain analysts;
* industry researchers;
* recognised technical accounts;
* regional-language specialists.

### Discovery sources

* X posts;
* Reddit;
* developer forums;
* conference comments;
* reposts and discussions.

The system should preserve the distinction between:

```text
X account links to an official model card
```

and:

```text
X account anonymously claims a model was delayed
```

These may be equally novel but have very different evidence states.

Source quality should also be **topic-specific**. An account might be reliable for GPU architecture and weak for memory pricing.

So instead of one global reputation number:

[
\text{SourceQuality}
====================

f(\text{source},\text{topic},\text{claim type})
]

Eventually, you could track:

* historical accuracy;
* correction rate;
* average lead time;
* frequency of original information;
* percentage of posts that merely aggregate;
* reliability by domain.

---

# 7. Pod configuration

Each pod should effectively have a configuration file or database object.

```yaml
pod:
  name: semiconductor_equipment
  companies:
    - ASML
    - Applied Materials
    - Lam Research
    - KLA
    - Tokyo Electron

  technologies:
    - EUV
    - High-NA EUV
    - advanced packaging
    - gate-all-around
    - backside power delivery

  priority_events:
    - capex_change
    - fab_delay
    - export_control
    - yield_issue
    - equipment_order
    - node_transition

  geographies:
    - Taiwan
    - United States
    - China
    - South Korea
    - Japan

  horizons:
    - current_quarter
    - next_12_months

  alert_thresholds:
    official_material_event: immediate
    credible_unconfirmed_event: emerging
    commentary: digest
```

This makes the platform reusable without hard-coding the same interpretation for every team.

A pod should also be able to define investment questions:

```text
Is advanced-packaging capacity still the limiting constraint?

Is HBM supply loosening faster than expected?

Are hyperscaler capex plans translating into actual GPU deployments?

Is open-source model efficiency reducing or expanding aggregate compute demand?

Are China export controls creating substitution demand for domestic equipment?
```

Events can then be mapped not only to companies, but to active research questions.

That is a powerful product feature.

---

# 8. The event object

A sector event should contain both factual and analytical layers.

## Factual state

* title;
* event type;
* entities;
* first-seen time;
* occurrence time;
* primary claims;
* supporting sources;
* contradicting sources;
* evidence confidence;
* event status;
* latest material update.

## Analytical state

* affected value-chain nodes;
* impact mechanisms;
* direct and second-order effects;
* direction and uncertainty;
* time horizon;
* relevant KPIs;
* pod-specific relevance;
* open questions.

## Event lifecycle

```text
candidate
→ emerging
→ corroborated
→ officially confirmed
→ developing
→ resolved
```

Alternative branches:

```text
emerging → disputed
emerging → retracted
confirmed → corrected
```

The system should update the event rather than generating a new alert every time another account repeats it.

---

# 9. Useful outputs for pods

I would design several distinct outputs.

## Immediate event alert

```text
[Emerging — Medium Evidence]

Reports suggest that advanced-packaging capacity for Product X may be delayed.

Why this matters:
Potential shipment timing impact for GPU suppliers and cloud customers.

Evidence:
Two specialist accounts cite the same upstream source; no company confirmation.

Watch next:
Supplier announcement, customer shipment guidance and packaging lead-time data.
```

## Event update

```text
Update: the supplier has now confirmed a temporary production disruption.
Expected duration remains undisclosed.
```

## Daily sector brief

* new material events;
* meaningful updates to existing events;
* changes in source consensus;
* rising themes;
* unresolved high-impact claims;
* company and technology heatmap.

## Thesis monitor

```text
Thesis: HBM remains structurally supply-constrained.

Supporting developments this week:
- Supplier A raised capacity guidance.
- Packaging lead times remain elevated.
- Cloud provider B increased accelerator deployment targets.

Contradicting developments:
- Spot memory pricing softened.
- Two suppliers indicated faster qualification timelines.
```

## “What changed?” interface

This may be more useful than another general dashboard:

```text
What changed since yesterday?
What changed for my watchlist?
What changed in evidence confidence?
What changed in the market’s apparent narrative?
```

---

# 10. Recommended first MVP

I would make the first version deliberately narrow.

### Universe

* 50–150 high-quality X accounts;
* official company and research feeds;
* perhaps 50–100 public companies;
* a constrained AI-compute value chain.

### Event types

Start with approximately 10–15:

* model release;
* benchmark/capability result;
* model/API pricing change;
* major partnership;
* cloud capex/deployment;
* GPU/accelerator launch;
* production or shipment delay;
* HBM/memory capacity update;
* foundry yield/capacity update;
* advanced-packaging constraint;
* export control/regulation;
* earnings/guidance;
* major outage/security incident;
* major developer-adoption signal.

### AI outputs

For each event:

* event classification;
* entities;
* atomic claims;
* one-line summary;
* evidence state;
* impact channels;
* affected subsectors;
* novelty class;
* pod-specific relevance.

### Alert outputs

Only:

```text
Immediate
Emerging
Digest
Suppress
```

Avoid trying to predict price moves or generate trade recommendations in the first version.

---

# 11. What should be shared versus customised

| Component                 | Shared across pods |          Pod-specific |
| ------------------------- | -----------------: | --------------------: |
| Raw source ingestion      |                Yes |             Sometimes |
| Entity resolution         |                Yes |                    No |
| Event clustering          |                Yes |                    No |
| Claim/evidence ledger     |                Yes |                    No |
| Sector relationship graph |                Yes |          Occasionally |
| Event summary             |             Mostly | Optional presentation |
| Company relevance         |                 No |                   Yes |
| Materiality               |             Partly |                   Yes |
| Alert threshold           |                 No |                   Yes |
| Impact rationale          |             Partly |                   Yes |
| Research questions        |                 No |                   Yes |
| Feedback model            |             Partly |                   Yes |

This separation is crucial. Otherwise every new pod becomes a separate pipeline rather than a configuration of the same engine.

---

# 12. The strongest long-term positioning

The valuable product is not:

> “We use AI to summarise Twitter.”

It is:

> **A configurable sector-intelligence platform that detects emerging events, maintains evidence-linked event state and maps developments onto each investment team’s companies, KPIs and research theses.**

That is credible for different pods because it acknowledges that:

* the facts are shared;
* relevance is portfolio-specific;
* materiality is thesis-specific;
* alert tolerance is user-specific;
* the underlying value chain is sector-specific.

For your initial scope, I would centre the engine on the **AI-compute and semiconductor value chain**, while treating general AI application news as a lower-priority adjacent domain. That creates a much cleaner economic graph and a stronger bridge from technical developments to investable implications.



Yes. I would design **three delivery products over the same event database**:

```text
Immediate alert  → “Something material just happened”
Daily brief      → “What changed in the past day?”
Weekly review    → “What does this week mean for the sector and our theses?”
```

The key is that these are not merely different email frequencies. They answer different analytical questions and therefore require different selection and summarisation logic.

# 1. Immediate alerts

An immediate alert should be triggered by a **material event-state transition**, not merely by a high-scoring post.

For example:

```text
rumoured
→ officially announced
→ technical report published
→ weights/API available
→ independently benchmarked
→ major adoption or commercial response
```

Each transition may justify a separate update, but the engine should maintain one event thread rather than sending five disconnected “new stories.”

## Kimi K3 example

This is actually a useful live example. Moonshot’s official API platform currently states that Kimi K3 has been formally released, describes it as its strongest flagship model, and lists a one-million-token context window. ([platform.moonshot.cn][1])

A correctly designed system might issue these alerts:

### Alert 1: release confirmation

```text
[OFFICIAL RELEASE | HIGH PRIORITY]

Moonshot has officially released Kimi K3.

Key facts:
• New flagship Kimi model
• 1M-token context window
• Positioned for software engineering, knowledge work and deep reasoning
• API access and pricing are now available

Why it matters:
Potentially important competitive step for Chinese frontier AI and the
open-model/API ecosystem.

Evidence:
Official Moonshot API platform.

Status:
Officially confirmed; benchmark claims not yet independently validated.
```

### Alert 2: benchmark claim

```text
[PROVIDER-CLAIMED PERFORMANCE UPDATE]

Moonshot reports that Kimi K3 reaches or exceeds frontier performance
on selected coding and reasoning evaluations.

Important qualification:
These are provider-reported results. Comparable settings and independent
replication remain pending.
```

### Alert 3: independent validation

```text
[VALIDATED PERFORMANCE UPDATE]

Independent evaluations now place Kimi K3 near the frontier on agentic coding,
while results are mixed on other task categories.

What changed:
The initial provider claim now has partial independent support.
```

That separation is important. The engine should never convert:

> “The company claims SOTA on several benchmarks”

into:

> “The model is SOTA.”

Benchmark rankings vary by task, evaluation setup and prompt distribution, while a single aggregate leaderboard can conceal meaningful differences between use cases. ([arXiv][2])

## Better status labels

Use explicit evidence labels in the alert headline:

```text
[RUMOUR]
[REPORTED]
[OFFICIAL]
[PROVIDER-CLAIMED]
[INDEPENDENTLY TESTED]
[DISPUTED]
[CORRECTED]
```

This makes a fast alert possible without pretending the system already knows the final truth.

---

# 2. What deserves an immediate alert?

For an AI and semiconductor sector engine, I would define event-specific gates.

## Model releases

Immediate when the release represents at least one major change:

* credible frontier-level capability;
* significant improvement in agentic coding or reasoning;
* materially lower inference cost;
* important open-weight release;
* much longer usable context;
* new multimodal or agent capability;
* licensing change affecting commercial deployment;
* unusually high training or inference-compute requirement;
* major architectural change with hardware implications.

Not immediate merely because:

* the provider says “SOTA”;
* one benchmark improves marginally;
* a model receives a minor version update;
* social-media engagement is high;
* there is no API, weights, technical report or reproducible evidence.

## Semiconductor events

Immediate candidates include:

* material GPU or accelerator launch;
* major HBM qualification, shortage or capacity change;
* foundry yield or production issue;
* advanced-packaging bottleneck;
* large hyperscaler capex revision;
* export controls;
* material equipment restrictions;
* major customer design win or loss;
* unexpected pricing or shipment change.

## Suggested immediate-alert rule

```text
Immediate alert if:

Pod relevance = high
AND potential materiality = high
AND novelty = material state change
AND one of:
    official primary source
    two genuinely independent credible sources
    extreme-impact unconfirmed report
```

The third case should be labelled clearly as an emerging or unverified alert.

---

# 3. Daily email

The daily email should not be a longer list of immediate alerts. It should answer:

> **What materially changed in the sector since the previous brief?**

A useful structure:

## Executive summary

Three to five sentences covering the day’s most important developments.

## Top events

Perhaps three to eight stories, each containing:

```text
Event
What changed today
Evidence status
Affected companies/subsectors
Potential impact channel
What to watch next
```

## Material updates to existing events

This is important. Many days contain no completely new event, but important updates to existing stories:

* rumour became official;
* benchmark was independently tested;
* pricing became available;
* technical report revealed architecture;
* company clarified deployment timing;
* an earlier claim was contradicted.

## Pod watchlist

```text
Directly relevant:
NVDA, TSMC, SK Hynix, ASML

Indirectly relevant:
AMD, Broadcom, hyperscalers

No material change:
Other watchlist companies
```

## Unverified but noteworthy

Keep rumours separate from confirmed developments.

## Low-priority information

Optionally include a compact “other developments” section, rather than silently dropping everything.

### The daily brief should emphasise change

Bad:

> Moonshot released Kimi K3, a new language model.

Better:

> Moonshot officially released Kimi K3 after earlier reports of an imminent launch. New confirmed information includes API availability, one-million-token context and published pricing; independent benchmark validation remains limited. ([platform.moonshot.cn][1])

The database therefore needs:

```text
previous_event_state
current_event_state
material_changes
```

rather than just a collection of recent articles.

---

# 4. Weekly email

The weekly review should move from **news summarisation to sector interpretation**.

It should answer:

> What narratives strengthened or weakened this week?

A strong weekly structure would be:

## Week in one paragraph

The dominant sector development and why it matters.

## Major event clusters

Not every article—only the main evolving stories.

## Emerging themes

For example:

* Chinese models closing the frontier capability gap;
* open-weight models gaining commercial relevance;
* inference price competition accelerating;
* agentic coding becoming the main capability battleground;
* context length increasing faster than demonstrated practical usefulness;
* AI demand shifting from training toward inference;
* advanced packaging remaining a binding constraint.

## Value-chain implications

```text
Model capability
→ adoption potential
→ inference demand
→ accelerator demand
→ HBM/networking/packaging implications
```

## Thesis tracker

```text
Thesis: Open models will materially pressure closed-model API pricing

Supporting evidence:
• New competitive release
• Lower equivalent API pricing
• Growing developer adoption

Contradicting evidence:
• Frontier gap remains on selected private evaluations
• Enterprise adoption remains limited
```

## Company exposure table

| Development               | Potential beneficiaries      | Potentially challenged     | Confidence    |
| ------------------------- | ---------------------------- | -------------------------- | ------------- |
| Lower-cost frontier model | AI applications, cloud users | premium API providers      | Medium        |
| Higher inference demand   | GPU/HBM/networking           | —                          | Medium        |
| Improved model efficiency | adopters                     | compute intensity per task | Low/ambiguous |

## Next week’s catalysts

* announced model releases;
* conferences;
* earnings;
* benchmark publication;
* regulatory decisions;
* expected technical reports;
* product availability dates.

The weekly report should permit more synthesis and ambiguity. It does not need the low latency or conservative brevity of an immediate alert.

---

# 5. One event, several communications

The email layer should not mark an event as “sent” and then forget it.

Use something like:

```text
event_id: kimi_k3_release

communications:
  - immediate_release_alert
  - immediate_benchmark_update
  - daily_digest_summary
  - weekly_theme_analysis
```

Each communication should record:

```text
event_state_version
sent_at
recipient/pod
delivery_type
facts_included
```

This prevents both duplicate alerts and stale summaries.

It also supports a useful line in later updates:

> **Since our previous alert:** Moonshot has published pricing and API access, but independent benchmark validation is still pending.

---

# 6. Cooldowns and update thresholds

You need two different controls.

## Cooldown

Prevents multiple messages about the same event over a short period.

Example:

```text
Normal event: 2-hour alert cooldown
Critical event: 20-minute cooldown
Daily brief: unaffected
```

## Material-update threshold

A cooldown should be overridden when something significant changes:

* official confirmation;
* correction or denial;
* benchmark results;
* weights/API becoming available;
* pricing disclosure;
* licence disclosure;
* major customer announcement;
* material technical-detail publication.

A new tweet repeating the release should not override the cooldown.

---

# 7. Email subject-line system

The subject should communicate both priority and evidence state:

```text
[AI ALERT][OFFICIAL] Moonshot releases Kimi K3
[AI ALERT][CLAIMED SOTA] Kimi K3 reports frontier coding results
[AI UPDATE][VALIDATED] Independent tests support Kimi K3 coding gains
[SEMIS ALERT][EMERGING] Reported HBM qualification delay
[AI DAILY] Kimi K3 launch, inference pricing and three other developments
[AI WEEKLY] Open-model competition intensifies
```

This allows a PM or analyst to decide whether to open the email without reading a vague headline.

---

# 8. Immediate-alert content should be short

The alert email is not the place for a full research report.

I would limit it to:

```text
1. What happened
2. Why the pod should care
3. What is confirmed
4. What remains uncertain
5. Affected entities
6. Primary-source links
7. What the engine is watching next
```

Approximately 150–250 words is enough. The event page or dashboard can contain the complete timeline and all supporting sources.

---

# 9. Different pods can receive different treatment

The same Kimi K3 event might produce:

### AI-model pod

Immediate alert because the competitive frontier has changed.

### AI-application pod

Immediate only if pricing, latency or deployment terms materially change application economics.

### Semiconductor pod

Possibly daily rather than immediate—unless the technical report implies unusually high inference compute, a new hardware dependency or meaningful accelerator/HBM demand.

### China technology pod

Immediate because it affects Chinese AI competitiveness, domestic technology capability and regulatory positioning.

Therefore, delivery is also pod-specific:

```text
event → pod relevance → delivery channel → timing
```

not simply:

```text
event score > 80 → email everyone
```

# Recommended initial delivery design

I would launch with four outputs:

| Output              | Trigger                                     | Purpose                     |
| ------------------- | ------------------------------------------- | --------------------------- |
| Immediate alert     | Material event-state transition             | Rapid awareness             |
| Event update        | Material new evidence on an alerted event   | Prevent stale understanding |
| Daily morning brief | All meaningful changes over 24 hours        | Complete sector awareness   |
| Weekly review       | Themes, theses and value-chain implications | Investment interpretation   |

The strongest design principle is:

> **Immediate alerts report events; daily briefs report changes; weekly reviews report meaning.**

That hierarchy would make the engine genuinely useful to sector pods rather than merely another high-volume AI newsletter.

[1]: https://platform.moonshot.cn/ "Kimi API 开放平台"
[2]: https://arxiv.org/abs/2604.21769?utm_source=chatgpt.com "Who Defines \"Best\"? Towards Interactive, User-Defined Evaluation of LLM Leaderboards"

We have covered the **high-level architecture**, **event-centric design**, **pod customisation**, **impact mapping**, and **delivery/alerts**. The major areas still not properly designed are below.

## 1. Source strategy and coverage

We have said “X plus primary sources,” but not decided:

* which accounts, websites and feeds to monitor;
* how accounts are discovered and promoted into the source universe;
* which sources are authoritative for each subsector;
* how much coverage should come from English, Chinese, Korean, Japanese and Taiwanese sources;
* how to capture GitHub, Hugging Face, arXiv, company blogs, model cards and benchmark sites;
* whether to monitor replies, quoted posts, lists, cashtags or keyword streams;
* how to avoid dependence on X API availability and pricing.

This is probably the first practical design question. For AI and semiconductors, the value of the system will depend heavily on the source universe.

A useful source structure might be:

```text
Official sources
Specialist journalists
Researchers and engineers
Industry analysts
Supply-chain accounts
Developers and benchmarkers
Aggregators
Unverified discovery accounts
```

Each source should have domain-specific reliability rather than one global reputation score.

---

## 2. Taxonomy and ontology design

We discussed categories conceptually, but not the actual controlled vocabulary.

You need to define:

* event types;
* technologies;
* products;
* entities;
* value-chain nodes;
* impact channels;
* KPIs;
* geographic exposures;
* evidence states;
* time horizons.

For example, is an NVIDIA announcement classified as:

```text
product_launch
accelerator
inference
networking
cloud_deployment
semiconductor_demand
```

It may need all of them, but with a primary event type and secondary tags.

A poor taxonomy will make categorisation inconsistent and pod filters difficult. A taxonomy that is too detailed will be impossible to maintain.

---

## 3. Entity resolution

This has been mentioned but not designed.

The engine must know that these refer to the same entity or product:

```text
TSMC
Taiwan Semiconductor
台积电
TSM
2330 TT
```

And distinguish closely related concepts:

```text
Kimi K3
Kimi K3 Thinking
Kimi API
Moonshot AI
Moonshot platform
```

Entity resolution involves:

* aliases;
* tickers;
* subsidiaries;
* products;
* model versions;
* people;
* private companies;
* research laboratories;
* suppliers and customers.

This is particularly difficult for AI models because names, checkpoints and version labels change quickly.

---

## 4. Event detection and lifecycle mechanics

We agreed on events rather than posts, but have not specified how the event engine actually works.

Open questions include:

* when does a post create a new event?
* when is it attached to an existing event?
* when is it a sub-event?
* when should two events merge?
* when should one event split?
* how long does an event remain active?
* what counts as a material state change?
* how are corrections and retractions handled?

For example:

```text
Kimi K3 rumoured
Kimi K3 officially announced
API pricing released
Technical report released
Independent benchmark published
Open weights released
```

Is this one event, six sub-events or a parent event with several milestones?

This needs a formal event-state model.

---

## 5. Claim extraction and evidence ledger

This is one of the biggest missing pieces.

Instead of treating a document as one block of information, the system should extract individual claims:

```text
Claim 1: Kimi K3 has a 1M-token context window.
Claim 2: Kimi K3 is SOTA on coding.
Claim 3: Kimi K3 is cheaper than Model X.
Claim 4: Kimi K3 uses architecture Y.
```

Each claim should have:

* source;
* publication time;
* event time;
* exact supporting passage;
* status;
* supporting sources;
* contradicting sources;
* last updated time.

Without a claim ledger, summaries can mix confirmed facts, provider claims and speculation.

---

## 6. Verification and corroboration workflow

We discussed evidence labels but not the operational process.

The engine needs rules for:

* identifying the original source;
* recognising that ten accounts copied one article;
* detecting circular reporting;
* retrieving primary documents;
* comparing conflicting claims;
* distinguishing provider benchmarks from independent benchmarks;
* checking whether a screenshot or chart is old or miscaptioned;
* deciding when evidence is sufficient to upgrade an event.

For model releases, verification might involve:

```text
Official announcement
→ model card
→ technical report
→ API/weights availability
→ benchmark methodology
→ independent evaluations
→ developer feedback
```

This is a separate subsystem, not merely another LLM prompt.

---

## 7. Benchmark and “SOTA” evaluation

Your Kimi K3 example reveals a major missing module: how the system decides whether a model genuinely reaches SOTA.

It needs to understand:

* which benchmarks matter;
* whether the benchmark is saturated;
* whether results are provider-reported;
* whether test-time compute differs;
* whether tool use is allowed;
* whether results use pass@1, pass@k or majority voting;
* whether the comparison uses the same model category;
* whether the model is open-weight, API-only or proprietary;
* whether performance improvements are economically meaningful.

A release may be SOTA in:

```text
agentic coding
```

but not in:

```text
general reasoning
multilingual tasks
long-context retrieval
latency
cost efficiency
```

The engine should produce a **capability profile**, not one universal ranking.

---

## 8. Sector impact model

We discussed impact mapping, but not how it will be produced consistently.

Questions still open:

* should impacts be generated from rules, relationships or LLM reasoning?
* how do we distinguish direct from second-order impacts?
* how are contradictory effects represented?
* how do we map events to revenue, margins, capex, utilisation or market share?
* how are impacts linked to specific time horizons?
* how should confidence be calibrated?

For example:

```text
More efficient AI model
```

could imply:

```text
Lower compute per query
Higher application adoption
Higher aggregate inference volume
Pricing pressure for model providers
Potentially higher or lower accelerator demand
```

The system must preserve this ambiguity rather than force a bullish/bearish conclusion.

---

## 9. Pod configuration and research-thesis tracking

We described pod profiles but not the operational format.

A pod configuration may need:

* company universe;
* private competitors;
* technologies;
* suppliers/customers;
* active theses;
* important KPIs;
* event priorities;
* excluded topics;
* preferred sources;
* alert tolerance;
* geographic focus;
* investment horizon.

The more interesting extension is thesis monitoring:

```text
Thesis:
Open-weight frontier models will pressure proprietary API pricing.

Supporting evidence:
...

Contradicting evidence:
...

Current confidence:
...

Recent change:
...
```

This would make the system much more valuable than a news feed.

---

## 10. Scoring calibration

We have discussed scoring conceptually, but not how to calibrate it.

You need to determine:

* initial rules and weights;
* whether scoring is event-level or pod-event-level;
* how thresholds are selected;
* how to handle rare but extreme events;
* how scores change as evidence develops;
* how user feedback updates the system;
* whether to train a supervised ranking model later.

The correct target is probably not:

```text
How important is this news?
```

It is:

```text
Would this pod have wanted to know immediately,
in the daily brief, in the weekly review, or not at all?
```

That is a ranking and routing problem.

---

## 11. Evaluation framework

This is one of the most important unaddressed topics.

You need metrics for:

### Event detection

* event precision;
* event recall;
* duplicate-event rate;
* incorrect merge rate;
* incorrect split rate.

### Summarisation

* factual precision;
* unsupported claims;
* missing material facts;
* temporal accuracy;
* correct uncertainty labels.

### Alerts

* immediate-alert precision;
* missed important events;
* alert latency;
* duplicate alerts;
* alert fatigue;
* upgrade/downgrade accuracy.

### Pod usefulness

* opened alerts;
* clicked sources;
* saved events;
* marked useful;
* included in analyst notes;
* subsequent research initiated.

Without this, it will be difficult to know whether architecture changes actually improve the engine.

---

## 12. Human feedback and analyst interaction

We have mostly treated the user as a passive recipient. The system should probably allow analysts to:

* mark an alert useful or irrelevant;
* correct an entity;
* merge or split events;
* promote or demote a source;
* add a company to a watchlist;
* attach an event to a thesis;
* request deeper research;
* ask follow-up questions against the event evidence;
* change the delivery tier.

This feedback should update both the pod configuration and future scoring.

---

## 13. User interface and workflow integration

We discussed email, but not the core interface.

Possible views include:

### Live event feed

Current events ordered by pod relevance.

### Event page

Timeline, claims, evidence, affected entities and changes.

### Sector map

Events grouped by value-chain node.

### Company page

Recent events, current theses and exposure relationships.

### Theme dashboard

Examples:

```text
Inference pricing
HBM supply
Advanced packaging
Chinese model competitiveness
AI capex
Model efficiency
Export controls
```

### Search and question-answering

For example:

> What has changed regarding HBM supply over the past month?

Email alone will eventually be insufficient because analysts need to inspect history and evidence.

---

## 14. Data model and storage

We have not designed the schema properly.

Important objects include:

```text
documents
posts
sources
entities
products
relationships
claims
events
event_versions
event_claims
event_impacts
pod_profiles
pod_watchlists
pod_event_scores
alerts
briefs
feedback
model_runs
```

Versioning is important because the system must reconstruct:

* what it knew at a given time;
* what evidence was available;
* why an alert was triggered;
* whether a later correction changed the event.

This also matters for future backtesting.

---

## 15. Backtesting and historical replay

You may eventually want to answer:

* Would the engine have detected major past model releases?
* How quickly would it have alerted?
* How many false alerts would it have generated?
* Which signals preceded conventional news coverage?
* Did certain source types consistently lead the event?
* Did event types correspond to meaningful price or estimate reactions?

Historical replay requires strict separation between:

* publication time;
* ingestion time;
* event occurrence time;
* processing time;
* later revisions.

This should be designed early even if market prediction is not part of the MVP.

---

## 16. Cost, latency and model routing

We have discussed cascades generally, but not the actual operating policy.

You need decisions such as:

```text
Which posts receive embeddings?
Which posts receive entity extraction?
Which clusters receive an LLM call?
Which events receive external verification?
Which events receive a strong reasoning model?
Which outputs can be cached?
```

You also need:

* per-source cost;
* per-event model cost;
* budget limits;
* fallback providers;
* rate-limit handling;
* model failure behaviour;
* retry and idempotency rules.

The model router is part of the product architecture, not just infrastructure.

---

## 17. Reliability and observability

A news engine must be able to tell you when it is failing silently.

Monitor:

* source ingestion gaps;
* API disconnections;
* abnormal fall in document volume;
* queue backlog;
* model latency;
* malformed structured outputs;
* rising “unknown entity” rate;
* clustering drift;
* duplicate-alert rate;
* cost spikes;
* brief-generation failures.

A system that generates excellent summaries but misses six hours of X data is not reliable.

---

## 18. Compliance and data governance

This is less exciting but still important, especially if the engine is intended for investment teams.

Questions include:

* what X data can be stored and for how long;
* how deletions and edits are synchronised;
* whether full post text can be redistributed internally;
* licensing of news and benchmark data;
* handling of private or restricted information;
* audit trails for generated claims;
* prompt-injection risks from source content;
* access control across pods;
* whether pod watchlists and theses should be isolated.

For a multi-pod firm, pod-level access control could become important because portfolio information itself may be sensitive.

---

# The most important missing areas

I would prioritise the next discussions in this order:

1. **Source universe and ingestion strategy**
2. **Taxonomy, entities and sector ontology**
3. **Event and claim data model**
4. **Event detection and lifecycle**
5. **Verification and source provenance**
6. **Model-release/SOTA evaluation methodology**
7. **Pod impact and thesis mapping**
8. **Evaluation and feedback framework**
9. **Interface and workflow**
10. **Infrastructure, costs and reliability**

The biggest gap is currently the middle of the system:

```text
Raw sources
→ claims
→ events
→ evidence
→ sector implications
```

We have discussed the input at a high level and the output/alerts in detail, but not yet specified how the engine converts noisy sector information into a reliable, evolving piece of investment intelligence.
