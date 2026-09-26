# SYMBIO Matching & Assessment Engine

The matching engine is the core of SYMBIO. It finds candidate exchanges between
**Resources** (what an organization can provide) and **Requirements** (what an
organization needs), and assesses whether each exchange is practical. It also
explains why each one was surfaced.

It is **deterministic**: the same inputs and configuration always produce the
same scores. AI assists with *retrieval* (semantic similarity) and optional
wording, but it never decides feasibility.

```
apps/backend/app/matching/
  types.py        immutable engine inputs (ResourceProfile, RequirementProfile, parameters, factors)
  components.py   component evaluators (material, properties, quantity, timing, location, processing)
  engine.py       evaluate_pair(): eligibility → components → assessments → composite → confidence
  explanation.py  deterministic, fact-only explanation builder
  profiles.py     ORM → profiles (+ embeddings)
  service.py      candidate retrieval, persistence, lifecycle, org-scoped access
  views.py        per-viewer presentation with privacy redaction
apps/backend/app/assessment/
  economic.py     transparent economic line items
  environmental.py scenario-based environmental assessment
```

## One engine, two directions

`run_for_resource(resource_id)` finds compatible requirements, and
`run_for_requirement(requirement_id)` finds compatible resources. Both call the
same `evaluate_pair()`, so a provider and a demander always see the same
assessment of the same pair. Runs are triggered by domain events: listing
created, updated, activated, paused or archived. They can also be requested
on demand (`POST /matches/search`, `POST /matches/{id}/refresh`).

## Pipeline

| # | Stage | Where | Outcome |
|---|-------|-------|---------|
| 1 | Candidate filtering | SQL | ACTIVE listing, other ACTIVE organization, overlapping date windows, facility inside a coarse bounding box (or unknown coordinates) |
| 2 | Quick relatedness | Python | Same unit family and any material link (exact / application / category / semantic) |
| 3 | Hard constraints | `engine` | Unit family, explicit exclusions, timing overlap, explicit max distance, REQUIRED properties |
| 4 | Material compatibility | `components.evaluate_material` | 5 layers (below) |
| 5 | Property compatibility | `components.evaluate_properties` | REQUIRED / PREFERRED / OPTIONAL |
| 6 | Quantity | `components.evaluate_quantity` | Coverage and utilization on a common per-month basis |
| 7 | Timing | `components.evaluate_timing` | Interval overlap |
| 8 | Location | `components.evaluate_location` | Haversine distance decay |
| 9 | Processing | `components.evaluate_processing` | Direct use / capability / manual review |
| 10 | Economic | `assessment.economic` | Line items with provenance, or INSUFFICIENT_DATA |
| 11 | Environmental | `assessment.environmental` | Baseline vs symbiosis scenario |
| 12 | Composite + confidence + explanation | `engine`, `explanation` | Score, data confidence, feasibility, explanation |

**Hard constraints are never turned into low scores.** A failed mandatory
condition makes the pair ineligible, with an explicit reason. That reason is
also used as the `stale_reason` when an existing match expires.

## Material compatibility (layers)

1. **Exact normalized material:** both listings reference the same canonical `Material` (identity 1.0).
2. **Application compatibility:** the demander states what the material is *for*
   (`intended_application`), and the knowledge base says the provider's material
   serves that application (`MaterialApplication`), subject to its screening
   rules (identity 0.9). **This finds hidden matches**: for example, *steel
   slag* offered, *natural aggregate for road sub-base* requested.
3. **Subcategory / category:** same material family (0.8), or same or accepted category (0.65).
4. **Property constraints:** the demander's technical constraints, evaluated against the provider's values.
5. **Semantic similarity:** cosine similarity of listing embeddings. This is used
   only to *find* candidates that have no structured link. Semantic-only matches
   are capped at 60 %, flagged `requires_manual_review`, and marked
   low-confidence.

```
base            = max(identity, min(semantic, 0.60))
material_score  = base                              (no constraints stated)
                = 0.5 × base + 0.5 × property_score (otherwise)
```

## Property constraints

Each constraint (e.g. `SiO2 ≥ 45 %`) is evaluated against the provider's
**confirmed** values. Unconfirmed AI-extracted values never reach the engine.

| Outcome | When | Credit |
|---|---|---|
| PASS | measured value within bounds | 1.0 |
| FAIL | measured value outside bounds | REQUIRED → hard failure; otherwise `max(0, 1 − 2·relative deviation)` |
| LIKELY | not measured; knowledge-base typical range entirely within bounds | 0.8 |
| UNCERTAIN | not measured; typical range straddles a bound | 0.5 |
| UNKNOWN | no value and no typical range | 0.5 |
| LIKELY_FAIL | not measured; typical range entirely outside bounds | 0.1 |

`property_score` is the importance-weighted mean of the credits
(REQUIRED 1.0, PREFERRED 0.6, OPTIONAL 0.3, all configurable). Typical ranges
are labelled *indicative* in the knowledge base. Using them lowers data
confidence, and a REQUIRED constraint that is only LIKELY/UNCERTAIN/UNKNOWN
triggers manual review.

## Quantity

Quantities are converted to the unit family's base unit (t, m³, MWh) and to a
per-month basis (`DAY × 30.4375`, `WEEK × 30.4375/7`, `YEAR ÷ 12`). One-time lots
are compared as noted in the evidence.

```
exchanged          = min(supply, demand)
demand_coverage    = exchanged / demand
supply_utilization = exchanged / supply
quantity_score     = 0.7 × demand_coverage + 0.3 × supply_utilization   (weight configurable)
```

Outcomes: `EXCESS_SUPPLY` (≥ 105 % of demand), `FULL_COVERAGE` (≥ 95 %),
`PARTIAL_COVERAGE` (≥ 25 %), `INSUFFICIENT_SUPPLY`. Unequal quantities are
**never** rejected. Example: 2,000 t/month supply against 1,500 t/month demand
gives 100 % demand coverage and 75 % supply utilization.

## Timing

```
timing_score = overlap(supply window, required window) / required window length
```

Open-ended windows are assessed over a configurable horizon (365 days). No
overlap is a hard failure.

## Location / logistics

```
distance_km    = haversine(provider facility, demander facility)
location_score = max(0, 1 − distance_km / max_distance_km)
```

`max_distance_km` is the demander's explicit limit (exceeding it is a hard
failure) or the platform default (300 km, where exceeding it gives score 0 but
the pair is kept). Straight-line distance understates road distance; the
explanation says so. Road routing, transport mode and freight quotes are
future extensions.

## Processing

| Outcome | Score |
|---|---|
| DIRECT_USE: no processing needed | 1.0 |
| DEMANDER_CAN_PROCESS: all required processing within the demander's capabilities | 0.85 |
| PROCESSING_ARRANGED: provider declared a processing cost | 0.65 |
| PARTIAL_CAPABILITY | 0.55 |
| UNSPECIFIED | 0.5 |
| NO_CAPABILITY: **blocker**, manual review | 0.2 |

"Processing required" never means "not feasible" on its own.

## Economic assessment

```
potential_net_value = avoided virgin purchase   (demander's price, USER_PROVIDED)
                    + avoided disposal cost      (provider's cost, USER_PROVIDED)
                    − transport cost             (distance × rate, PLATFORM_ASSUMPTION)
                    − processing cost            (provider's cost, USER_PROVIDED)
```

- Every line item carries its `basis` and `provided_by`.
- If neither benefit input exists, the result is `INSUFFICIENT_DATA`. The
  economic score is then **unavailable** and excluded from the composite; it
  is never invented.
- Direction: `POSITIVE_POTENTIAL` (net > 10 % of gross), `NEGATIVE_POTENTIAL` (< −10 %), else `UNCERTAIN`.
- `economic_score = clamp(0.5 + 0.5 × net / gross, 0, 1)`.
- The asking price is a transfer between the parties, so it is excluded from
  combined value and reported for negotiation.
- Prices are converted per base unit (a price per kg becomes a price per tonne).

## Environmental assessment

```
Baseline  = virgin material displaced × virgin production factor
          + waste diverted × disposal factor (current disposition)
Symbiosis = exchanged × distance × transport factor + exchanged × processing factor
Net potential benefit = Baseline − Symbiosis

environmental_score = 0.5 × diversion share + 0.5 × clamp(0.5 + 0.5 × net/baseline, 0, 1)
```

- Waste diverted and virgin material avoided are quantity metrics and need no factors.
- CO₂e uses only stored `EmissionFactor` rows (source, unit, geography,
  methodology, version, validity). The factor ids and versions are copied into
  the match snapshot.
- If a required factor is missing, CO₂e (and the score) are reported as
  unavailable.
- Seeded factors are **illustrative demo values** (`is_demo_value = true`).
  Every result that uses them says so. Replace them through the admin API
  before relying on CO₂e.
- All figures are *potential* until an exchange records verified outcomes.

## Composite score, caps and feasibility

```
overall = Σ wᵢ · scoreᵢ / Σ wᵢ     over components whose score is available
```

The default weights come from the specification and are stored as data in
`MatchingConfig` v1.0: material 30 %, quantity 20 %, location 15 %, timing
10 %, processing 10 %, economic 10 %, environmental 5 %. New weights mean a new
config version, and each match records `matching_version` and
`methodology_version`.

Caps:
- A processing blocker or negative economics caps the score at 55 %.
- A semantic-only material link caps it at 60 %.

Feasibility is `HIGH` (≥ 75 %, no manual review), `MEDIUM`, or `LOW` (< 50 % or
a blocker). Matches below `min_overall_score` (35 %) are not surfaced.

## Score ≠ truth: data confidence

Every match reports **compatibility** (the score) and **data confidence**
separately. Confidence rewards a normalized material, measured technical
values, known coordinates, complete economic inputs, and complete non-demo
environmental factors. It penalizes semantic-only links. Missing items are
listed as `confidence.gaps`, for example *"Some technical constraints are not
backed by measured values."*

## Explanations

`explanation.build_explanation()` produces the headline ("Potential
opportunity"), summary, strengths, considerations, per-component
level/headline/evidence, property checks, confidence gaps, caps and a
disclaimer. Every sentence is derived from computed values. An optional AI
layer may rephrase the summary, but it is stored separately and never replaces
these facts.

## Lifecycle and staleness

```
DISCOVERED → VIEWED → INTERESTED → CONNECTION_REQUESTED → CONNECTED → NEGOTIATING → ACTIVE_EXCHANGE → COMPLETED
alternative exits: REJECTED · EXPIRED · CANCELLED        EXPIRED → DISCOVERED (re-surfaced)
```

Early-stage matches expire automatically when a listing is paused, archived or
expired; when a re-evaluation fails; or when their TTL passes. A later
re-evaluation can re-surface them. Connected matches are never silently
expired; they receive a `stale_reason` instead. `assessment_snapshot` stores the
exact inputs, parameters and factors behind the current scores.

## Scaling path

The MVP runs the semantic stage in Python over the SQL-filtered candidate set.
At scale:

- Store embeddings in a pgvector column with an IVFFlat/HNSW index and move
  semantic retrieval into SQL.
- Replace the bounding box with PostGIS `ST_DWithin` on a geography index.
- Run full re-matching in background workers backed by Redis; the job functions already take ids only.
