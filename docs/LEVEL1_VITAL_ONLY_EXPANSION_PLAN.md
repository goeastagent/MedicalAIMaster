# Level1 Vital-Only Expansion Plan

> Updated: 2026-04-10
>
> Scope: regenerate the Level1 benchmark using `vital_only` and `adversarial` cases only.

---

## 1. Goal

This document defines the current regeneration strategy for the Level1 benchmark after narrowing the scope to:

- `vital_only`
- `adversarial`

The immediate goal is to produce a stable first-pass dataset with good diversity and filter survival, then expand it in a second phase if needed.

---

## 2. Current Direction

The current pipeline is intentionally configured for:

- vital signal parameter keys only (`Device/Signal` format)
- normal retrieval cases plus adversarial cases
- multi-provider generation using both OpenAI and Claude

Clinical and lab parameters are explicitly excluded from generation, labeling, and final validation.

---

## 3. First-Pass Generation Target

### 3.1 Recommended target

The first-pass target is:

- Normal cases: `180`
- Adversarial cases: `30`
- Total: `210`

### 3.2 Planned distribution

| Query Type | Doctor | Data Scientist | Layperson | Total |
| :--- | ---: | ---: | ---: | ---: |
| Single-Direct | 8 | 8 | 8 | 24 |
| Single-Semantic | 10 | 10 | 14 | 34 |
| Single-Abbreviation | 9 | 9 | 8 | 26 |
| Multi-Independent | 10 | 10 | 12 | 32 |
| Multi-Conditional | 20 | 20 | 24 | 64 |
| Adversarial | - | - | - | 30 |
| **Total** |  |  |  | **210** |

### 3.3 Why this is the right first step

This target is large enough to:

- improve parameter coverage beyond the previous small benchmark
- stress semantic and multi-parameter retrieval
- exercise `layperson` phrasing more heavily
- validate the new OpenAI/Claude alternating generation path

At the same time, it is still small enough to:

- keep quality auditing tractable
- avoid overfitting the current limited multi-pair inventory
- reveal the real bottlenecks before committing to a 500-case build

---

## 4. Why Not Jump Directly to 500

The current implementation can generate more text, but a high-quality `500`-case dataset is still bottlenecked by structure, not only by LLM throughput.

### 4.1 Main constraints

1. `MULTI_PAIRS` is still limited.
2. `MAX_CASES_PER_PARAM` is conservative.
3. Stage 4 deduplication removes many semantically similar queries.
4. Style caps prevent one style from dominating.
5. A larger pool of generated text does not automatically create broader parameter coverage.

### 4.2 Practical implication

Using OpenAI and Claude in alternation helps increase linguistic diversity and Stage 4 survival, but it does **not** by itself solve:

- insufficient pair diversity
- repeated use of the same high-frequency parameters
- limited structural coverage in `Multi-*` cases

Therefore:

- `210` is the recommended first-pass target
- `300` is likely reachable with modest pair expansion
- `500` should be treated as a second-phase expansion target

---

## 5. Multi-Provider Generation Strategy

The pipeline now supports alternating generation providers.

### 5.1 Current policy

- Stage 1 synonym generation: OpenAI / Claude round-robin
- Stage 2 normal query generation: OpenAI / Claude round-robin
- Stage 5 adversarial generation: OpenAI / Claude round-robin
- On failure, the router falls back to the next configured backend

### 5.2 Expected benefit

This helps by increasing:

- paraphrase diversity
- persona/style diversity
- survival after dedup filtering
- adversarial phrasing diversity

### 5.3 What it does not solve

This does not replace the need for:

- more medically relevant multi-parameter pairs
- broader parameter coverage
- better coverage-aware sampling

---

## 6. First-Pass Success Criteria

The first regeneration should be considered successful if it achieves:

- total dataset size near the configured target
- only `vital_only` and `adversarial` categories present
- improved unique parameter coverage
- balanced style distribution
- usable numbers of `Single-Semantic`, `Multi-Conditional`, and `layperson` cases

Recommended review points after the run:

- `validation_report.json`
- Stage 4 rejection counts
- per-query-type counts
- per-style counts
- examples of generated queries from both OpenAI and Claude

---

## 7. Second-Phase Expansion Path

If the first regeneration is healthy, the next expansion should proceed in this order.

### 7.1 Expand pair inventory first

Add substantially more `MULTI_PAIRS`, especially for:

- respiratory management
- hemodynamic-drug response
- anesthesia depth
- waveform-scalar combinations

This is the most important prerequisite for moving toward `300+` and eventually `500`.

### 7.2 Loosen per-parameter caps carefully

Raise `MAX_CASES_PER_PARAM` gradually rather than drastically.

Recommended order:

- first inspect the actual coverage distribution
- then increase the cap only if bottlenecks are confirmed

### 7.3 Add coverage-aware sampling

The next useful generator improvement is to prioritize underused parameters and pairs rather than sampling uniformly.

This would improve:

- parameter coverage
- pair coverage
- overall dataset efficiency

### 7.4 Then consider a 500-case build

A `500`-case target becomes much more realistic after:

- larger pair inventory
- better coverage-aware generation
- verified first-pass filter survival

---

## 8. Execution Plan

### Step 1

Run the first full regeneration with the current vital-only configuration.

### Step 2

Inspect:

- Stage 4 rejection stats
- final dataset size
- parameter coverage
- style balance
- provider diversity markers in `generation_notes`

### Step 3

If results are healthy, plan a second-phase expansion toward `300+`.

### Step 4

Only after pair expansion and coverage analysis, evaluate whether `500` is worth building.

---

## 9. Recommended Current Decision

Proceed with:

- `vital_only + adversarial` only
- full regeneration from Stage 1
- first-pass target of `210`
- post-run analysis before any attempt to push toward `500`
