# ExtractionAgent 책임 및 개선 로드맵

> **문서 목적:** Level1/SVA/Temporal 평가 결과 분석을 바탕으로 ExtractionAgent의 미구현 기능과 버그를 우선순위별로 정리한 공식 TODO 문서  
> **기준일:** 2026-03-31  
> **참고 문서:** `VITALAGENT_TODO.md`, `INDEXING_AGENT_ROADMAP.md`, `EMBEDDING_PARAMETER_SEARCH.md`, `LEVEL1_DATASET.md`  
> **연계 문서:** [`INDEXING_AGENT_ROADMAP.md`](./INDEXING_AGENT_ROADMAP.md) — I-XX 항목은 이 문서와 의존관계에 있음

---

## 1. ExtractionAgent의 핵심 책임 (현재)

ExtractionAgent는 VitalAgent 파이프라인의 **"번역기"** 이다.  
사용자의 자연어를 AnalysisAgent가 실행할 수 있는 정형화된 Execution Plan으로 변환한다.

**핵심 철학: "요리를 위한 완벽한 레시피와 재료 위치를 제공한다"**  
데이터 값(Values)이 아닌 데이터 핸들(Handle)을 반환한다.

### 1.1 현재 파이프라인 (2 Node, 순차)

```
입력: 사용자 자연어 쿼리
                    │
                    ▼
        ┌───────────────────────────────────────┐
        │  [100] query_understanding 🤖          │
        │                                       │
        │  · SchemaContextBuilder로 DB 메타데이터 로딩    │
        │  · LLM으로 intent/parameter/filter 추출        │
        │  · requested_parameters 생성                    │
        │    (term, normalized, candidates,               │
        │     expected_categories, measurement_type_hint) │
        └───────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────────────┐
        │  [200] parameter_resolver 🤖📏         │
        │                                       │
        │  Phase 1: ILIKE 키워드 DB 검색 (순차)  │
        │  Phase 2: LLM Resolver 병렬 호출       │
        │  Post:    measurement_type 필터링      │
        │                                       │
        │  OntologyCache: Neo4j ConceptCategory  │
        │  캐시 (category_query 확장용)          │
        └───────────────────────────────────────┘
                    │
                    ▼
출력: resolved_parameters, ambiguities, execution_plan
```

### 1.2 현재 DB 검색 방식

```python
# node.py _search_parameters() — 현재 방식
SELECT param_key, semantic_name, unit, concept_category
FROM parameter
WHERE (param_key ILIKE %s OR semantic_name ILIKE %s)   -- ← 키워드 부분 일치만
  AND concept_category IN (...)                          -- ← 카테고리 필터
LIMIT 50
```

**한계:** 사용자 표현(자연어)과 DB 필드 값이 부분 일치하지 않으면 0건 반환 →  
`db_matches = []` → Fast Path → `resolution_mode = "not_found"` (LLM 호출 없이 즉시 실패)

### 1.3 Level1 평가 현황 (2026-03-31 기준)

| Query Type | F1 | Perfect% | 주요 실패 원인 |
|---|---|---|---|
| Single-Direct | **100%** | 100% | — |
| Single-Abbreviation | 93.3% | 93.3% | DEX 약어 미매핑 |
| Adversarial | 95.0% | 95.0% | False Positive 1건 |
| Multi-Independent | 93.3% | 80.0% | AND 파라미터 일부 누락 |
| Multi-Conditional | 82.7% | 60.7% | TV/ETCO2 디바이스 혼동 |
| **Single-Semantic** | **59.7%** | **62.5%** | **Semantic 매핑 완전 실패** |

---

## 2. 미구현 기능 목록 (TODO)

> **명명 규칙:** E-XX (ExtractionAgent 고유 작업), I-XX (IndexingAgent 완료 후 가능)  
> **의존성:** I-XX가 표시된 항목은 해당 IndexingAgent 작업이 선행되어야 함

---

### [P0] E-01: Vector Similarity Search (ILIKE 교체)

**의존:** `I-01` (Parameter Embedding 계산·저장) — 선행 필수  
**해결하는 실패:** Level1 P1 패턴 (10케이스, Single-Semantic F1=0)  
**연관 TODO:** `T-09` (DEX VOL 미검색), `T-08` (waveform 미검색)

**문제:**  
ILIKE 검색이 0건을 반환할 때 LLM 호출 없이 즉시 `not_found`를 반환한다.

```python
# node.py L140-155 — 현재 Fast Path
if not db_matches:
    mode = "clarify" if is_vague else "not_found"
    return idx, resolved  # ← LLM 호출 없이 즉시 실패
```

실패 케이스 분석:

| 쿼리 표현 | 생성된 candidates | 정답 param_key | ILIKE 결과 | 원인 |
|---|---|---|---|---|
| "dexmedetomidine administered" | ["dexmedetomidine"] | `Orchestra/DEX2_VOL` | 0건 | semantic_name에 "DEX2"만 있고 "dexmedetomidine" 없음 |
| "propofol effect-site concentration" | ["propofol", "effect-site"] | `Orchestra/PPF20_CE` | 0건 | "PPF20_CE"와 substring 불일치 |
| "ST segment lead III" | ["ST segment", "lead III"] | `Solar8000/ST_III` | 0건 | "ST_III"와 substring 불일치 |
| "Dex was administered" | ["Dex"] | `Orchestra/DEX2_VOL` | 0건 | category filter + ILIKE 복합 실패 |
| "airway pressure" | ["airway pressure", "AWP"] | `Primus/AWP` | 0건 | expected_categories 필터가 차단 가능 |

**해결책: ILIKE Fallback으로 Vector Search 추가**

```python
# _search_parameters() 수정안
def _search_parameters(self, candidates, expected_categories, schema_context):
    # Step 1: 기존 ILIKE (빠름, 높은 precision)
    results = self._ilike_search(candidates, expected_categories)
    if results:
        return results

    # Step 2: ILIKE fallback — category 없이 재시도
    if expected_categories:
        results = self._ilike_search(candidates, [])
        if results:
            return results

    # Step 3: Vector similarity search (I-01 완료 후 활성화)
    if self._embedding_client and candidates:
        query_text = " ".join(candidates)
        results = self._vector_search(query_text, top_k=10)
        return results

    return []

def _vector_search(self, query_text: str, top_k: int = 10) -> List[Dict]:
    """
    I-01에서 IndexingAgent가 계산한 name_embedding을 사용한 코사인 유사도 검색.
    PostgreSQL pgvector의 <=> 연산자 활용.
    """
    query_embedding = self._embedding_client.embed(query_text)
    conn = self.db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT param_key, semantic_name, unit, concept_category,
               1 - (name_embedding <=> %s::vector) AS similarity
        FROM parameter
        WHERE name_embedding IS NOT NULL
        ORDER BY name_embedding <=> %s::vector
        LIMIT %s
    """, [query_embedding, query_embedding, top_k])
    rows = cursor.fetchall()
    return [
        {"param_key": r[0], "semantic_name": r[1], "unit": r[2],
         "concept_category": r[3], "similarity": r[4]}
        for r in rows if r[4] > 0.75  # similarity threshold
    ]
```

**구현 위치:** `ExtractionAgent/src/agents/nodes/parameter_resolver/node.py`  
**관련 IndexingAgent 작업:** I-01에서 `parameter.name_embedding` 컬럼 및 ivfflat 인덱스 생성

---

### [P0] E-02: measurement_type DB 필드 활용 (OntologyCache 교체)

**의존:** `I-02` (measurement_type 자동 추론·저장) — 선행 필수  
**해결하는 실패:** T-08 (Waveform vs Scalar 오분류), T-09 (Volume vs Rate 오분류)

**문제:**  
현재 OntologyCache가 런타임에 unit 패턴으로 `measurement_type`을 추론한다.  
이 로직은 VitalDB naming convention에 종속적이고, 타 데이터셋에서 오작동한다.

```python
# ontology_cache.py — 현재 방식 (제거 대상)
_RATE_UNITS = {"/hr", "/min", "/h"}           # ← VitalDB 전용 heuristic
_CUMULATIVE_UNITS = {"ml", "mg", "mcg", "g"}  # ← 타 데이터셋에서 틀릴 수 있음
```

**해결책: DB 필드 직접 조회**

```python
# I-02 완료 후: parameter 테이블에 measurement_type 컬럼 존재
# ontology_cache.py filter_by_measurement_type() 교체

def filter_by_measurement_type(self, params, measurement_type):
    """
    unit 패턴 추론 → DB measurement_type 필드 직접 조회로 교체.
    """
    if not params or not measurement_type:
        return params

    # DB lookup (param_lookup 캐시에 measurement_type 포함되어 있다고 가정)
    filtered = [
        p for p in params
        if self._param_lookup.get(p["param_key"], {}).get("measurement_type") == measurement_type
    ]
    return filtered if filtered else params
```

**DB 쿼리 업데이트 (OntologyCache 로드 시):**

```python
# _load_from_session() 수정
result = session.run("""
    MATCH (c:ConceptCategory)-[:CONTAINS]->(p:Parameter)
    RETURN c.name AS category,
           p.key  AS key,
           p.name AS name,
           p.unit AS unit,
           p.concept AS concept,
           p.measurement_type AS measurement_type   -- ← 추가
    ORDER BY c.name, p.key
""")
```

**또는 PostgreSQL에서 로드 시 measurement_type 포함:**

```python
# _search_parameters() 쿼리에 measurement_type 컬럼 추가
SELECT param_key, semantic_name, unit, concept_category, measurement_type
FROM parameter
WHERE ...
```

**구현 위치:**  
- `ExtractionAgent/src/agents/nodes/parameter_resolver/ontology_cache.py`  
- `ExtractionAgent/src/agents/nodes/parameter_resolver/node.py`  
**정리 대상:** `_RATE_UNITS`, `_CUMULATIVE_UNITS`, `_CONCENTRATION_UNITS`, `_WAVEFORM_UNITS` 상수 제거

---

### [P0] E-03: QU AND 복합 쿼리 분리 추출 강제 규칙

**의존:** 없음 (독립 작업, IndexingAgent 불필요)  
**해결하는 실패:** Level1 P3 패턴 (4케이스, Multi-Independent Recall=0.5)  
**예상 소요:** 30분

**문제:**  
"end-tidal CO2 **and** FiO2" 처럼 두 파라미터를 포함한 쿼리에서 LLM이 확률적으로 하나만 추출한다.

```
// 실패 패턴 (4케이스 모두 Precision=1.0, Recall=0.5)
L1-050: "ETCO2 and FiO2" → retrieved: [ETCO2]  (FiO2 누락)
L1-051: "ETCO2 and FiO2" → retrieved: [FiO2]   (ETCO2 누락)
L1-058: "ETCO2 and FiO2" → retrieved: [ETCO2]  (FiO2 누락)
L1-060: "ETCO2 and FiO2" → retrieved: [FiO2]   (ETCO2 누락)
```

Precision=1.0이므로 잘못된 파라미터를 추가한 것이 아니라, **QU 단계에서 파라미터 자체를 누락**한 것.

**해결책: prompts.py에 AND 분리 규칙 추가**

```python
# prompts.py SYSTEM_PROMPT_TEMPLATE 추가 규칙

# 기존 규칙 10번 다음에 삽입:
"""
11. **AND/OR COMPOUND PARAMETERS**: When the user's query mentions multiple 
    parameters connected with "and", "or", "both", "as well as", "along with",
    "and also", or similar conjunctions, ALWAYS extract EACH parameter as a 
    SEPARATE item in requested_parameters. Never merge them into a single entry.
    
    Examples:
    - "end-tidal CO2 and FiO2" → TWO items: [{term: "end-tidal CO2"}, {term: "FiO2"}]
    - "heart rate as well as SpO2" → TWO items: [{term: "heart rate"}, {term: "SpO2"}]
    - "relationship between tidal volume and end-tidal CO2" → TWO items
    - "variability in ETCO2 and FiO2 percentages" → TWO items
    
    This rule takes priority over all other rules. Even if the parameters seem 
    related or from the same category, they must be separate extraction targets.
"""
```

**구현 위치:** `ExtractionAgent/src/agents/nodes/query_understanding/prompts.py`

---

### [P0] E-04: Ambiguity Detection (scope_intent)

**의존:** 없음 (독립 작업)  
**해결하는 실패:** Temporal Ambiguous 50케이스 (0% pass rate) — `T-01` 참조  
**예상 소요:** 2일

**문제:**  
caseid, 시간 범위 등 필수 정보가 없는 쿼리에서 VitalAgent가 clarification 없이 임의값을 반환.

**해결책: 3-Layer 접근 (VITALAGENT_TODO T-01 설계 참조)**

**Layer 1 — QU scope_intent 출력:**

```python
# prompts.py requested_parameters 출력에 추가
{
    "scope_intent": "single_case | population | ambiguous",
    "is_caseid_required": true,
    "is_time_range_specified": false
}
```

**Layer 2 — Orchestrator 분기:**

```python
# 조건: scope_intent == "single_case" + caseid_filter 없음
if scope_intent == "single_case" and not caseid_filter:
    first_caseid = ctx.get_case_ids()[0]
    assumption_note = f"No caseid specified; assuming first case (caseid={first_caseid})"
    # assumption_note를 생성 코드 출력에 포함
```

**Layer 3 — 평가 프롬프트 수정 (temporal_ambiguous 케이스 한정)**

**구현 위치:**  
- `ExtractionAgent/src/agents/nodes/query_understanding/prompts.py` (Layer 1)  
- `OrchestrationAgent/src/orchestrator.py` (Layer 2)

---

### [P1] E-05: concept_priority 기반 Cross-Device Disambiguation

**의존:** `I-03` (concept_priority 컬럼 생성), `I-07` (device_role 분류) — 선행 필수  
**해결하는 실패:** Level1 P2 패턴 (8케이스, TV/ETCO2 디바이스 혼동)  
**연관 TODO:** `T-03` (Cross-Device Disambiguation)

**문제:**  
동일한 생리학적 개념이 두 장비에 존재할 때 LLM이 확률적으로 잘못된 장비를 선택한다.

```
// 실패 패턴 (매우 일관적)
ETCO2: 정답=Solar8000/ETCO2  → 반환=Primus/ETCO2    (8케이스)
TV:    정답=Primus/TV         → 반환=Solar8000/VENT_TV (6케이스)
```

**I-03 완료 후 예상 DB 상태:**

```sql
-- concept_id, concept_priority, device_group 컬럼 추가됨
-- Solar8000/ETCO2:  concept_id='end_tidal_co2', concept_priority=1, device_group='patient_monitor'
-- Primus/ETCO2:     concept_id='end_tidal_co2', concept_priority=2, device_group='anesthesia_machine'
-- Primus/TV:        concept_id='tidal_volume',  concept_priority=1, device_group='anesthesia_machine'
-- Solar8000/VENT_TV:concept_id='tidal_volume',  concept_priority=2, device_group='patient_monitor'
```

**해결책 1: DB 검색에 concept_priority 정렬 추가**

```python
# _search_parameters() 쿼리 수정
query = """
    SELECT DISTINCT ON (concept_id)
           param_key, semantic_name, unit, concept_category,
           concept_id, concept_priority, device_group
    FROM parameter
    WHERE ({keyword_clause}) {category_clause}
    ORDER BY concept_id, concept_priority ASC, param_key  -- ← priority 낮은 것(=1) 우선
    LIMIT %s
"""
```

**해결책 2: LLM Resolver 프롬프트에 device_group 컨텍스트 주입**

```python
# build_resolution_prompt() 수정 — db_matches에 device_group 포함 시
# 프롬프트에 추가:
"""
DEVICE PRIORITY RULE:
When multiple parameters represent the same concept from different devices,
prefer the parameter with concept_priority=1 (primary device).
- concept_priority=1: Primary measurement source (authoritative)
- concept_priority=2: Secondary/derived measurement (use only if explicitly requested)
"""
```

**구현 위치:**  
- `ExtractionAgent/src/agents/nodes/parameter_resolver/node.py`  
- `ExtractionAgent/src/agents/nodes/parameter_resolver/prompts.py`

---

### [P1] E-06: Behavior Classification 로직 수정 (clarify ↔ retrieve 역전)

**의존:** 없음 (독립 작업)  
**해결하는 실패:** behavior_match 실패 케이스 (Multi-Conditional), `T-05` 참조  
**예상 소요:** 1일

**문제:**  
조건이 명확히 명시된 쿼리에서 `clarify`를 반환하고, 반대로 caseid 없는 모호한 쿼리에서 `retrieve`를 반환한다.

```
Q: "During elevated ETCO2, how does tidal volume adjust?"
Expected behavior: retrieve  →  Detected: clarify  (역전)
```

**해결책: Resolver 프롬프트에 behavior 분류 기준 명시**

```python
# build_resolution_prompt() 수정

"""
RESOLUTION MODE RULES:
- Use "retrieve": When the parameter is identifiable from the query, even if the 
  query is complex or multi-conditional. Presence of conditional clauses ("when X > Y", 
  "during Z", "if W") does NOT make a query ambiguous.
- Use "clarify": ONLY when the parameter itself is genuinely ambiguous or cannot be 
  uniquely identified (e.g., "the numbers", "some cardiac stuff").
- Use "not_found": When the requested parameter does not exist in the provided DB matches.

CRITICAL: Complex/conditional queries should use "retrieve", NOT "clarify".
"""
```

**구현 위치:** `ExtractionAgent/src/agents/nodes/parameter_resolver/prompts.py`

---

### [P1] E-07: OntologyCache Category 확장 강화

**의존:** `I-01` (Embedding) — 선행 권장  
**해결하는 실패:** SVA `ontology_based` resolution 50%, `category_aggregate` 12.5% — `T-02` 참조

**문제:**  
`category_query` 타입 쿼리에서 Neo4j 카테고리 확장이 작동하나, 세부 의학 카테고리 (vasopressor, neurological 등)가 `_CATEGORY_ALIASES`에 없으면 확장이 안 된다.

```python
# ontology_cache.py — 현재 aliases (불완전)
_CATEGORY_ALIASES = {
    "vital": "Vital Signs",
    "drug": "Medication",
    ...  # vasopressor, inotrope, NMBA 등 세부 카테고리 없음
}
```

**해결책: aliases 확장 + Embedding 기반 카테고리 매칭**

```python
# 추가할 aliases (임상 세부 카테고리)
_CATEGORY_ALIASES.update({
    "vasopressor": "Medication",
    "vasopressors": "Medication",
    "inotrope": "Medication",
    "inotropes": "Medication",
    "neuromuscular": "Medication",
    "nmba": "Medication",
    "opioid": "Medication",
    "volatile": "Anesthesia",
    "volatile anesthetic": "Anesthesia",
    "cardiac output": "Hemodynamics",
    "hemodynamic": "Hemodynamics",
    "eeg": "Neurological",
    "bispectral": "Neurological",
    "ecg": "Vital Signs",
    "electrocardiogram": "Vital Signs",
})

# I-01 완료 후 추가 가능: category term → embedding similarity로 ConceptCategory 매핑
def _find_category_by_embedding(self, term: str) -> Optional[str]:
    """term embedding과 ConceptCategory 이름 embedding의 유사도로 카테고리 찾기."""
    ...
```

**구현 위치:** `ExtractionAgent/src/agents/nodes/parameter_resolver/ontology_cache.py`

---

### [P2] E-08: Adversarial False Positive 방지

**의존:** 없음 (독립 작업)  
**해결하는 실패:** Level1 P4 패턴 (1케이스, L1-ADV-013)

**문제:**  
"detailed respiratory mechanics waveform"처럼 유사하지만 존재하지 않는 개념을 요청할 때,  
Resolver가 가장 유사한 `Primus/AWP`를 반환 (False Positive).

```
L1-ADV-013: "detailed respiratory mechanics waveform"
Expected: None (데이터 없음)
Retrieved: Primus/AWP  ← 유사하지만 다른 개념
```

**해결책: Resolver 프롬프트에 "유사 ≠ 동일" 원칙 강화**

```python
# build_resolution_prompt() 추가

"""
ADVERSARIAL DETECTION RULE:
Do NOT map a parameter simply because it is the "closest match" to the query term.
The parameter must semantically satisfy EXACTLY what the user is requesting.

Examples of what NOT to do:
- "respiratory mechanics waveform" ≠ Airway Waveform Pressure (AWP)
  (AWP is a specific pressure signal, not a comprehensive mechanics waveform)
- "complete cardiac monitoring package" ≠ Solar8000/HR
  (HR is only one aspect; no single parameter satisfies "complete package")

When in doubt between a close-but-not-exact match and not_found, prefer not_found.
Use "not_found" when the query asks for a concept that requires data beyond what 
any single parameter provides.
"""
```

**구현 위치:** `ExtractionAgent/src/agents/nodes/parameter_resolver/prompts.py`

---

### [P2] E-09: OntologyCache 중복 로직 제거 (I-02 완료 후)

**의존:** `I-02` (measurement_type DB 저장) — 선행 필수  
**예상 소요:** 0.5일 (E-02 구현의 정리 작업)

**문제:**  
E-02 구현 후 `ontology_cache.py`의 unit-기반 추론 로직은 중복이 된다.

**해결책:**

```python
# 제거 대상 (I-02 + E-02 완료 후)
_RATE_UNITS = ...         # 삭제
_CUMULATIVE_UNITS = ...   # 삭제
_CONCENTRATION_UNITS = ...# 삭제
_WAVEFORM_CONCEPTS = ...  # 삭제 (DB concept_category 필드로 대체)
_WAVEFORM_UNITS = ...     # 삭제

# _matches_type() → DB measurement_type 조회로 완전 교체
```

**구현 위치:** `ExtractionAgent/src/agents/nodes/parameter_resolver/ontology_cache.py`

---

## 3. 구현 우선순위 요약

| 우선순위 | ID | 기능 | 예상 기간 | I-XX 의존 | 해결하는 케이스 | 구현 위치 |
|---------|-----|------|----------|----------|--------------|---------|
| **P0** | E-01 | Vector Similarity Search | 1일 | I-01 필수 | P1 Semantic ~9건 | `parameter_resolver/node.py` |
| **P0** | E-02 | measurement_type DB 활용 | 0.5일 | I-02 필수 | T-08, T-09 | `ontology_cache.py` |
| **P0** | E-03 | QU AND 복합 파라미터 분리 | 30분 | **없음** | P3 Multi-Indep 4건 | `query_understanding/prompts.py` |
| **P0** | E-04 | Ambiguity Detection | 2일 | **없음** | Temporal Ambig 50건 | `prompts.py` + Orchestrator |
| **P1** | E-05 | concept_priority Disambiguation | 1일 | I-03, I-07 필수 | P2 TV/ETCO2 ~7건 | `node.py` + `prompts.py` |
| **P1** | E-06 | Behavior Classification 수정 | 1일 | **없음** | T-05 behavior_match | `parameter_resolver/prompts.py` |
| **P1** | E-07 | OntologyCache 카테고리 확장 | 0.5일 | I-01 권장 | SVA category ~5건 | `ontology_cache.py` |
| **P2** | E-08 | Adversarial FP 방지 | 2시간 | **없음** | P4 1건 | `parameter_resolver/prompts.py` |
| **P2** | E-09 | OntologyCache 중복 제거 | 0.5일 | I-02 필수 | 코드 정리 | `ontology_cache.py` |

---

## 4. IndexingAgent 의존성 매트릭스

| ExtractionAgent 작업 | 의존하는 IndexingAgent 작업 | 의존 유형 | 설명 |
|---------------------|---------------------------|---------|------|
| **E-01** Vector Search | **I-01** Parameter Embedding | **필수** | `parameter.name_embedding` 컬럼 없으면 E-01 불가 |
| **E-02** measurement_type 활용 | **I-02** measurement_type 추론 | **필수** | `parameter.measurement_type` 컬럼 없으면 E-02 불가 |
| **E-05** concept_priority | **I-03** Concept Clustering | **필수** | `parameter.concept_id/priority` 없으면 E-05 불가 |
| **E-05** concept_priority | **I-07** device_group 분류 | 보완 | device_role이 I-03 priority 결정에 사용됨 |
| **E-07** 카테고리 확장 | **I-01** Parameter Embedding | 권장 | alias 수동 확장은 I-01 없이도 가능 |
| **E-09** 중복 제거 | **I-02** measurement_type 추론 | **필수** | I-02 미완료 시 E-09 수행하면 기능 손실 |
| **E-03, E-04, E-06, E-08** | — | **없음** | ExtractionAgent 독립 작업 |

---

## 5. Level1 평가 개선 예상 효과

> 기준: `level1_eval_20260331_152045.xlsx` (F1 현재 84.4%, 실패 28건)

| 작업 | 예상 추가 해결 케이스 | 예상 F1 개선 | 비고 |
|------|-------------------|-----------|------|
| E-03 (AND 분리 규칙) | +4건 (P3 전부) | +3.5% | IndexingAgent 불필요, 즉시 가능 |
| E-01 (Vector Search) | +7~9건 (P1 대부분) | +6~8% | I-01 선행 후 |
| E-05 (concept_priority) | +6~7건 (P2 대부분) | +5~6% | I-03, I-07 선행 후 |
| E-06 (behavior 수정) | behavior_match +3~5건 | F1 직접 영향 없음 | behavior_acc 지표 개선 |
| E-08 (Adversarial FP) | +1건 (P4) | +0.9% | 즉시 가능 |
| **전체 합산** | **+18~21건** | **+90%+ 달성 예상** | |

---

## 6. 완료된 항목 (참고)

| ID | 내용 | 완료일 |
|----|------|--------|
| T-04 | `DataFrame.dtype` AttributeError 버그 수정 | 2026-03-30 |
| T-06 | Trailing Backslash 버그 수정 (`rstrip("\\")`) | 2026-03-30 |
| T-07 | Float Precision 비교 기준 완화 | 2026-03-30 |

---

## 7. 파일 수정 맵

```
ExtractionAgent/src/agents/nodes/
├── query_understanding/
│   ├── prompts.py          ← E-03 (AND 규칙), E-04 (scope_intent)
│   └── node.py             ← E-04 (응답 파싱)
│
└── parameter_resolver/
    ├── node.py             ← E-01 (vector search), E-05 (concept_priority 정렬)
    ├── prompts.py          ← E-05 (device priority 규칙), E-06 (behavior 기준),
    │                          E-08 (adversarial 원칙)
    └── ontology_cache.py   ← E-02 (measurement_type 조회), E-07 (alias 확장),
                               E-09 (중복 로직 제거)

OrchestrationAgent/src/
└── orchestrator.py         ← E-04 (scope_intent 분기, Layer 2)
```

---

*문서 작성일: 2026-03-31*  
*기반 평가: `level1_eval_20260331_152045.xlsx` (114케이스, 28건 실패 분석)*  
*상태: 설계 완료, 구현 대기*  
*다음 검토일: 구현 완료 후*
