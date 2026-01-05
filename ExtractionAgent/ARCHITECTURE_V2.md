# ExtractionAgent v2 아키텍처 및 구현 명세

## 📖 개요

ExtractionAgent v2는 IndexingAgent가 구축한 **PostgreSQL 메타데이터**와 **Neo4j 온톨로지**를 활용하여:
1. 사용자의 **자연어 질의**를 분석
2. 데이터 위치와 접근 방법을 담은 **Execution Plan JSON**을 생성

하는 계획 수립(Planning) 에이전트입니다.

### 핵심 철학

```
"요리(분석)를 위한 완벽한 레시피와 재료 위치를 제공한다"

- 데이터 자체(Values)가 아닌 데이터 핸들(Handle)을 반환
- Analysis Agent가 Plan을 받아 실제 데이터 로드/처리 수행
- Signal 데이터(GB 단위)를 직접 전송하지 않음
```

### IndexingAgent vs ExtractionAgent

| 구분 | IndexingAgent | ExtractionAgent v2 |
|------|---------------|-------------------|
| **역할** | 데이터 → 메타데이터 구축 | 쿼리 → 실행 계획 생성 |
| **DB 접근** | Write + Read | **Read Only** |
| **LLM 사용** | 분류/추론 | 쿼리 이해/매핑 |
| **출력** | PostgreSQL + Neo4j | Execution Plan JSON |

---

## 🔄 전체 워크플로우 아키텍처

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          입력: 자연어 쿼리                                            ┃
┃             "2023년 위암 환자의 심박수(HR) 데이터를 줘"                                ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 1: 쿼리 이해 (LLM-based)                               ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                       ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────┐   ┃
┃   │ [100] query_understanding 🤖 │────▶│ State: intent, extracted_entities       │   ┃
┃   │  • Intent Classification      │     │        resolution_strategy              │   ┃
┃   │  • Entity Extraction (NER)    │     │                                        │   ┃
┃   │  • Resolution Strategy 결정   │     │ Intent: data_retrieval                 │   ┃
┃   └───────────────────────────────┘     │ Entities: [diagnosis, temporal, param] │   ┃
┃                                         └────────────────────────────────────────┘   ┃
┃                                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 2: 시맨틱 해석 (LLM + DB)                              ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                       ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────┐   ┃
┃   │ [200] semantic_resolver 🤖📏 │────▶│ State: resolved_parameters              │   ┃
┃   │  • Neo4j Parameter 검색       │     │        resolved_filters, ambiguities   │   ┃
┃   │  • PostgreSQL parameter 검색  │     │                                        │   ┃
┃   │  • Term → Column 매핑         │     │ "심박수" → [Solar8000/HR, BIS/HR]      │   ┃
┃   │  • 모호성 탐지                │     │ "위암" → diagnosis column              │   ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────┘   ┃
┃                                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 3: 토폴로지 탐색 (Rule-based)                          ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                       ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────┐   ┃
┃   │ [300] topology_navigator 📏  │────▶│ State: data_topology                    │   ┃
┃   │  • Cohort Source 식별         │     │   - cohort_source (clinical_data.csv)  │   ┃
┃   │  • Target Sources 식별        │     │   - target_sources (vital_case_records)│   ┃
┃   │  • Join Path 탐색             │     │   - join_paths (caseid)                │   ┃
┃   │  • FileGroup 해석             │     │                                        │   ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────┘   ┃
┃                                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 4: 코호트 분석 (Rule + LLM)                            ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                       ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────┐   ┃
┃   │ [400] cohort_analyzer 📏🤖   │────▶│ State: cohort_definition                │   ┃
┃   │  • 메타데이터 기반 필터 가능성 │     │   - strategy: partial_metadata          │   ┃
┃   │  • Filter Logic 생성          │     │   - filter_logic: [{col, op, val}]     │   ┃
┃   │  • 스캔 필요 여부 판단        │     │   - estimated_cohort_size: 150         │   ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────┘   ┃
┃                                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 5: 계획 수립 (Rule-based)                              ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                       ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────┐   ┃
┃   │ [500] plan_builder 📏        │────▶│ State: execution_plan                   │   ┃
┃   │  • Execution Plan JSON 조립   │     │   - cohort_source                      │   ┃
┃   │  • File Path 매핑             │     │   - data_sources                       │   ┃
┃   │  • Reader Type 결정           │     │   - join_specification                 │   ┃
┃   │  • Delegated Tasks 정의       │     │   - delegated_tasks                    │   ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────┘   ┃
┃                                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 6: 검증 (Rule + LLM)                                   ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                       ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────┐   ┃
┃   │ [600] plan_validator 📏🤖    │────▶│ State: validated_plan                   │   ┃
┃   │  • 파일 존재 확인             │     │        validation_warnings              │   ┃
┃   │  • Join Path 유효성 검증      │     │        overall_confidence               │   ┃
┃   │  • Confidence 계산            │     │                                        │   ┃
┃   │  • Human Review 필요 판단     │     │ Confidence: 0.92                       │   ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────┘   ┃
┃                                                                                       ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          출력: Execution Plan JSON                                    ┃
┃                                                                                       ┃
┃   {                                                                                   ┃
┃     "intent": "data_retrieval",                                                       ┃
┃     "execution_plan": {                                                               ┃
┃       "cohort_source": { file_path, filter_logic, result_identifier },               ┃
┃       "data_sources": [{ group_id, target_parameters, join_key }],                   ┃
┃       "join_specification": { paths }                                                 ┃
┃     },                                                                                ┃
┃     "validation": { confidence: 0.92 }                                               ┃
┃   }                                                                                   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## 📊 노드별 상세 명세

### 🔷 [100] QueryUnderstandingNode

**역할**: 자연어 쿼리를 구조화된 Intent와 Entity로 변환

| 항목 | 내용 |
|------|------|
| **Order** | 100 |
| **Type** | 🤖 LLM-based |
| **Input** | `user_query` (자연어 문자열) |
| **Output** | `intent`, `extracted_entities`, `resolution_strategy` |
| **DB 접근** | 없음 |
| **Neo4j 접근** | 없음 |

#### Intent Types

```python
class Intent(Enum):
    DATA_RETRIEVAL = "data_retrieval"      # 데이터 추출 (가장 일반적)
    AGGREGATION = "aggregation"             # 집계/통계 (평균, 최대값 등)
    EXPLORATION = "exploration"             # 탐색 (어떤 데이터가 있는지?)
    RELATIONSHIP = "relationship"           # 관계 탐색 (A와 B의 관계는?)
    METADATA_LOOKUP = "metadata_lookup"     # 메타데이터 조회 (컬럼 정의 등)
```

#### Entity Types

```python
class EntityType(Enum):
    PARAMETER = "parameter"           # 측정 파라미터 (HR, SpO2, BP)
    DIAGNOSIS = "diagnosis"           # 진단명 (위암, 당뇨)
    TEMPORAL = "temporal"             # 시간 조건 (2023년, 최근 24시간)
    DEMOGRAPHIC = "demographic"       # 인구통계 (남성, 60세 이상)
    IDENTIFIER = "identifier"         # 식별자 (caseid=123)
    PROCEDURE = "procedure"           # 시술/수술 (복강경 수술)
    CONDITION = "condition"           # 조건 (SBP < 90)
```

#### Extracted Entity 스키마

```python
@dataclass
class ExtractedEntity:
    type: EntityType
    value: str                           # 원문 텍스트 ("심박수", "2023년")
    normalized: Union[str, Dict]         # 정규화된 값
    condition_type: Optional[str]        # "exact", "like", "range", "comparison"
    operator: Optional[str]              # "<", ">", "BETWEEN", "LIKE"
    confidence: float                    # LLM 신뢰도
```

#### LLM 프롬프트 (query_understanding/prompts.py)

```python
SYSTEM_PROMPT = """
You are a medical data query analyzer for a surgical/clinical database.

Your task is to:
1. Classify the user's intent (what they want to do)
2. Extract entities (medical terms, conditions, parameters)
3. Normalize extracted entities to standard forms

Available Entity Types:
- parameter: Medical measurements (HR, SpO2, Blood Pressure, etc.)
- diagnosis: Disease/condition names (Stomach Cancer, Diabetes, etc.)
- temporal: Time constraints (2023, last 24 hours, during surgery)
- demographic: Patient demographics (male, age > 60)
- identifier: Specific IDs (caseid=123, patient_id=456)
- condition: Value-based conditions (SBP < 90, HR > 100)

Output JSON format:
{
    "intent": "data_retrieval" | "aggregation" | "exploration" | "relationship" | "metadata_lookup",
    "entities": [
        {
            "type": "parameter",
            "value": "심박수",
            "normalized": "Heart Rate",
            "candidates": ["HR", "Heart Rate", "heart_rate"],
            "condition_type": null,
            "confidence": 0.95
        },
        {
            "type": "diagnosis",
            "value": "위암",
            "normalized": "Stomach Cancer",
            "condition_type": "like",
            "confidence": 0.9
        },
        {
            "type": "temporal",
            "value": "2023년",
            "normalized": {"start": "2023-01-01", "end": "2023-12-31"},
            "condition_type": "range",
            "confidence": 0.95
        }
    ],
    "reasoning": "User wants to retrieve Heart Rate data for stomach cancer patients in 2023"
}
"""

USER_PROMPT_TEMPLATE = """
Analyze the following query:

Query: {user_query}

Extract the intent and all entities.
"""
```

#### Resolution Strategy 결정 로직

```python
def _determine_resolution_strategy(self, entities: List[ExtractedEntity]) -> str:
    """
    Entity 특성에 따라 해결 전략 결정
    
    Rules:
    1. 값 범위/비교 조건 (SBP < 90) → scan_required
    2. Categorical 필터만 (diagnosis=위암) → metadata_only 가능
    3. 파라미터 추출만 → metadata_only
    """
    has_value_condition = any(
        e.type == EntityType.CONDITION or 
        e.condition_type in ["comparison", "range"]
        for e in entities
    )
    
    if has_value_condition:
        return "scan_required"
    
    has_filter = any(
        e.type in [EntityType.DIAGNOSIS, EntityType.TEMPORAL, EntityType.DEMOGRAPHIC]
        for e in entities
    )
    
    if has_filter:
        return "partial_metadata"
    
    return "metadata_only"
```

---

### 🔷 [200] SemanticResolverNode

**역할**: 추출된 Entity를 실제 DB 스키마(param_key, column_name)에 매핑

| 항목 | 내용 |
|------|------|
| **Order** | 200 |
| **Type** | 🤖📏 Hybrid (LLM + Rule) |
| **Input** | `extracted_entities` |
| **Output** | `resolved_parameters`, `resolved_filters`, `ambiguities` |
| **DB 접근** | parameter, column_metadata, file_catalog |
| **Neo4j 접근** | Parameter, ConceptCategory 노드 |

#### PostgreSQL 쿼리

```sql
-- Parameter 검색 (semantic_name 또는 param_key로)
SELECT 
    p.param_id,
    p.param_key,
    p.semantic_name,
    p.unit,
    p.concept_category,
    p.source_type,
    p.file_id,
    p.group_id,
    fg.group_name
FROM parameter p
LEFT JOIN file_group fg ON p.group_id = fg.group_id
WHERE (
    p.semantic_name ILIKE '%{term}%' 
    OR p.param_key ILIKE '%{term}%'
)
ORDER BY p.llm_confidence DESC NULLS LAST
LIMIT 10;

-- 필터 컬럼 검색 (diagnosis, op_date 등)
SELECT DISTINCT
    cm.original_name,
    cm.column_type,
    cm.column_role,
    cm.value_distribution,
    fc.file_id,
    fc.file_path
FROM column_metadata cm
JOIN file_catalog fc ON cm.file_id = fc.file_id
WHERE cm.original_name ILIKE '%{column_hint}%'
  AND fc.is_metadata = FALSE;
```

#### Neo4j 쿼리

```cypher
-- Semantic Name으로 Parameter 검색
MATCH (p:Parameter)
WHERE toLower(p.semantic_name) CONTAINS toLower($term)
   OR toLower(p.key) CONTAINS toLower($term)
OPTIONAL MATCH (c:ConceptCategory)-[:CONTAINS]->(p)
OPTIONAL MATCH (fg:FileGroup)-[:HAS_COMMON_PARAM]->(p)
RETURN 
    p.key as param_key,
    p.semantic_name as semantic_name,
    p.unit as unit,
    c.name as concept_category,
    p.source_type as source_type,
    fg.group_id as group_id,
    fg.name as group_name
LIMIT 10;

-- ConceptCategory 기반 검색
MATCH (c:ConceptCategory {name: $category})-[:CONTAINS]->(p:Parameter)
RETURN p.key, p.semantic_name, p.unit
ORDER BY p.semantic_name;
```

#### 모호성 처리 로직

```python
def _resolve_with_ambiguity_check(
    self, 
    entity: ExtractedEntity,
    pg_results: List[Dict],
    neo4j_results: List[Dict]
) -> ResolvedEntity:
    """
    여러 후보 중 최적 매핑 선택, 모호한 경우 표시
    """
    candidates = self._merge_candidates(pg_results, neo4j_results)
    
    if len(candidates) == 0:
        return ResolvedEntity(
            original=entity,
            resolved=None,
            confidence=0.0,
            status="not_found"
        )
    
    if len(candidates) == 1:
        return ResolvedEntity(
            original=entity,
            resolved=candidates[0],
            confidence=0.95,
            status="resolved"
        )
    
    # 여러 후보 → LLM으로 최적 선택 또는 모호성 표시
    if self._are_semantically_similar(candidates):
        # 동일 의미의 다른 키 (Solar8000/HR, BIS/HR 둘 다 Heart Rate)
        return ResolvedEntity(
            original=entity,
            resolved=candidates,  # 모두 포함
            confidence=0.85,
            status="multiple_valid"
        )
    else:
        # 의미가 다른 후보들 → 사용자 확인 필요
        return ResolvedEntity(
            original=entity,
            resolved=candidates,
            confidence=0.5,
            status="ambiguous",
            needs_human_review=True
        )
```

#### Output 스키마

```python
@dataclass
class ResolvedParameter:
    semantic_term: str                   # 원본 검색어 ("심박수")
    param_keys: List[str]                # 매핑된 param_key들 ["Solar8000/HR", "BIS/HR"]
    concept_category: str                # "Vital Signs"
    source_type: str                     # "group_common"
    file_id: Optional[str]               # 개별 파일 파라미터인 경우
    group_id: Optional[str]              # 그룹 파라미터인 경우
    unit: Optional[str]                  # "bpm"
    confidence: float

@dataclass
class ResolvedFilter:
    entity_type: str                     # "diagnosis", "temporal"
    semantic_term: str                   # "위암"
    column_name: str                     # "diagnosis"
    file_id: str                         # 필터가 적용될 파일
    operator: str                        # "LIKE"
    value: Any                           # "%Stomach Cancer%"
    confidence: float
```

---

### 🔷 [300] TopologyNavigatorNode

**역할**: 데이터 소스 간 연결 경로(Join Path) 탐색

| 항목 | 내용 |
|------|------|
| **Order** | 300 |
| **Type** | 📏 Rule-based |
| **Input** | `resolved_parameters`, `resolved_filters` |
| **Output** | `data_topology` |
| **DB 접근** | file_catalog, file_group, table_entities, table_relationships |
| **Neo4j 접근** | RowEntity LINKS_TO 관계 |

#### Cohort Source 식별 로직

```python
def _identify_cohort_source(self, resolved_filters: List[ResolvedFilter]) -> Dict:
    """
    필터 조건이 적용되는 파일(Cohort Source) 식별
    
    Logic:
    1. resolved_filters에서 파일 ID 추출
    2. table_entities에서 해당 파일의 entity 정보 조회
    3. entity_identifier 확인 (Join Key로 사용)
    """
    if not resolved_filters:
        return None
    
    # 필터가 있는 파일 ID
    file_ids = list(set(f.file_id for f in resolved_filters))
    
    # 가장 적합한 Cohort Source 선택
    # (여러 파일에 필터가 있으면 상위 Entity 파일 선택)
    query = """
    SELECT 
        fc.file_id, fc.file_path, fc.file_name,
        te.row_represents, te.entity_identifier
    FROM file_catalog fc
    JOIN table_entities te ON fc.file_id = te.file_id
    WHERE fc.file_id = ANY(%s)
    ORDER BY 
        CASE te.row_represents 
            WHEN 'patient' THEN 1
            WHEN 'surgery' THEN 2
            WHEN 'case' THEN 3
            ELSE 10
        END
    LIMIT 1;
    """
    result = self.db.execute(query, [file_ids])
    
    return {
        "file_id": str(result["file_id"]),
        "file_path": result["file_path"],
        "file_name": result["file_name"],
        "entity_type": result["row_represents"],
        "identifier_column": result["entity_identifier"]
    }
```

#### Join Path 탐색

```python
def _find_join_paths(
    self, 
    cohort_source: Dict, 
    target_sources: List[Dict]
) -> List[Dict]:
    """
    table_relationships를 사용해 Join Path 탐색
    """
    paths = []
    
    for target in target_sources:
        # PostgreSQL에서 관계 검색
        query = """
        SELECT 
            tr.source_column, tr.target_column, tr.cardinality,
            fc_s.file_name as source_name,
            fc_t.file_name as target_name,
            COALESCE(fg.group_name, fc_t.file_name) as target_display
        FROM table_relationships tr
        JOIN file_catalog fc_s ON tr.source_file_id = fc_s.file_id
        LEFT JOIN file_catalog fc_t ON tr.target_file_id = fc_t.file_id
        LEFT JOIN file_group fg ON fc_t.group_id = fg.group_id
        WHERE fc_s.file_id = %s
          AND (fc_t.file_id = %s OR fc_t.group_id = %s)
        """
        results = self.db.execute(query, [
            cohort_source["file_id"],
            target.get("file_id"),
            target.get("group_id")
        ])
        
        for r in results:
            paths.append({
                "from_file": cohort_source["file_name"],
                "to_target": r["target_display"],
                "source_column": r["source_column"],
                "target_column": r["target_column"],
                "cardinality": r["cardinality"]
            })
    
    # 직접 연결이 없으면 Neo4j에서 간접 경로 탐색
    if not paths:
        paths = self._find_indirect_paths_neo4j(cohort_source, target_sources)
    
    return paths
```

#### Neo4j 간접 경로 탐색

```cypher
-- 2-hop 이내 경로 탐색
MATCH path = shortestPath(
    (source:RowEntity {source_table: $source_file})
    -[:LINKS_TO*1..2]-
    (target:RowEntity)
)
WHERE target.source_table = $target_file 
   OR target.group_name = $target_group
RETURN 
    [node in nodes(path) | node.name] as entities,
    [rel in relationships(path) | {
        type: type(rel),
        cardinality: rel.cardinality,
        join_column: rel.join_column
    }] as relationships,
    length(path) as hops
ORDER BY hops
LIMIT 1;
```

#### Output 스키마

```python
@dataclass
class DataTopology:
    cohort_source: Dict[str, Any]        # Cohort를 정의하는 파일
    # {
    #   "file_id": "uuid",
    #   "file_path": "/data/clinical_data.csv",
    #   "entity_type": "surgery",
    #   "identifier_column": "caseid"
    # }
    
    target_sources: List[Dict[str, Any]] # 데이터를 추출할 소스들
    # [{
    #   "type": "file_group",
    #   "group_id": "uuid",
    #   "group_name": "vital_case_records",
    #   "param_keys": ["Solar8000/HR", "BIS/HR"]
    # }]
    
    join_paths: List[Dict[str, Any]]     # Join 경로
    # [{
    #   "from_file": "clinical_data.csv",
    #   "to_target": "vital_case_records",
    #   "source_column": "caseid",
    #   "target_column": "filename_values.caseid",
    #   "cardinality": "1:N"
    # }]
```

---

### 🔷 [400] CohortAnalyzerNode

**역할**: 코호트 필터의 메타데이터 기반 해결 가능성 분석

| 항목 | 내용 |
|------|------|
| **Order** | 400 |
| **Type** | 📏🤖 Hybrid |
| **Input** | `resolved_filters`, `data_topology` |
| **Output** | `cohort_definition` |
| **DB 접근** | column_metadata (value_distribution, column_info) |
| **Neo4j 접근** | 없음 |

#### 필터 분석 로직

```python
def _analyze_filter_feasibility(
    self, 
    filter_: ResolvedFilter, 
    cohort_source: Dict
) -> Dict:
    """
    개별 필터의 메타데이터 기반 해결 가능성 분석
    
    결정 기준:
    1. Categorical + LIKE/Exact → value_distribution 확인
    2. Range/Comparison → scan 필요
    3. Temporal → column_info의 min/max 확인
    """
    # column_metadata 조회
    query = """
    SELECT column_type, column_info, value_distribution
    FROM column_metadata
    WHERE file_id = %s AND original_name = %s
    """
    meta = self.db.execute_one(query, [
        cohort_source["file_id"], 
        filter_.column_name
    ])
    
    if not meta:
        return {
            "column": filter_.column_name,
            "resolvable_by_metadata": False,
            "requires_scan": True,
            "reason": "Column metadata not found"
        }
    
    column_type = meta["column_type"]
    condition_type = filter_.condition_type
    
    # Case 1: Categorical 컬럼 + exact/like 조건
    if column_type == "categorical" and condition_type in ["exact", "like"]:
        value_dist = meta.get("value_distribution", {})
        unique_values = value_dist.get("unique_values", [])
        
        # 값 존재 여부 확인
        target = filter_.value.replace("%", "")  # LIKE 패턴 제거
        found = any(target.lower() in str(v).lower() for v in unique_values)
        
        if found:
            return {
                "column": filter_.column_name,
                "resolvable_by_metadata": True,
                "requires_scan": False,
                "metadata_hint": f"Value '{target}' found in distribution"
            }
        else:
            # unique_count가 너무 많으면 샘플링되었을 수 있음
            unique_count = value_dist.get("unique_count", 0)
            if unique_count > len(unique_values):
                return {
                    "column": filter_.column_name,
                    "resolvable_by_metadata": False,
                    "requires_scan": True,
                    "reason": f"Distribution sampled ({len(unique_values)}/{unique_count})"
                }
            return {
                "column": filter_.column_name,
                "resolvable_by_metadata": False,
                "requires_scan": True,
                "reason": "Value not in distribution"
            }
    
    # Case 2: Temporal 컬럼 + range 조건
    if column_type == "datetime" and condition_type == "range":
        column_info = meta.get("column_info", {})
        min_date = column_info.get("min")
        max_date = column_info.get("max")
        
        if min_date and max_date:
            # 범위가 완전히 벗어나면 빈 결과 예측
            return {
                "column": filter_.column_name,
                "resolvable_by_metadata": True,
                "requires_scan": True,  # 실제 필터링은 스캔 필요
                "metadata_hint": f"Date range: {min_date} ~ {max_date}"
            }
    
    # Case 3: 비교 조건 (< > <= >=) → 스캔 필요
    if condition_type == "comparison":
        return {
            "column": filter_.column_name,
            "resolvable_by_metadata": False,
            "requires_scan": True,
            "reason": f"Comparison condition ({filter_.operator}) requires scan"
        }
    
    return {
        "column": filter_.column_name,
        "resolvable_by_metadata": False,
        "requires_scan": True,
        "reason": "Unknown condition type"
    }
```

#### Output 스키마

```python
@dataclass
class CohortDefinition:
    strategy: str                        # "metadata_resolvable" | "scan_required"
    filter_logic: List[Dict[str, Any]]   # Analysis Agent가 적용할 필터
    # [{
    #   "column": "diagnosis",
    #   "operator": "LIKE",
    #   "value": "%Stomach Cancer%"
    # }]
    
    filter_analyses: List[Dict[str, Any]]  # 각 필터의 분석 결과
    estimated_cohort_size: Optional[int]   # 추정 코호트 크기
    scan_reason: Optional[str]             # 스캔이 필요한 이유
```

---

### 🔷 [500] PlanBuilderNode

**역할**: 최종 Execution Plan JSON 조립

| 항목 | 내용 |
|------|------|
| **Order** | 500 |
| **Type** | 📏 Rule-based |
| **Input** | 모든 이전 노드 결과 |
| **Output** | `execution_plan` |
| **DB 접근** | file_catalog (파일 경로 조회) |
| **Neo4j 접근** | 없음 |

#### Execution Plan 조립

```python
def execute(self, state: ExtractionAgentState) -> Dict[str, Any]:
    plan = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "intent": state["intent"],
        "original_query": state["user_query"],
        
        "entities": self._build_entities_section(state),
        
        "execution_plan": {
            "cohort_source": self._build_cohort_source(
                state["data_topology"],
                state["cohort_definition"]
            ),
            "data_sources": self._build_data_sources(
                state["resolved_parameters"],
                state["data_topology"]
            ),
            "join_specification": self._build_join_spec(
                state["data_topology"]
            )
        },
        
        "resolution_strategy": state["cohort_definition"]["strategy"],
        "delegated_tasks": self._build_delegated_tasks(
            state["cohort_definition"],
            state["resolved_parameters"]
        )
    }
    
    return {
        "plan_builder_result": {"status": "success"},
        "execution_plan": plan
    }
```

#### Reader Type 결정

```python
READER_MAP = {
    ".csv": "pandas_csv",
    ".parquet": "pandas_parquet",
    ".xlsx": "pandas_excel",
    ".vital": "vitaldb_reader",
    ".edf": "pyedflib_reader",
    ".wfdb": "wfdb_reader",
    ".json": "json_reader",
}

def _get_reader_type(self, file_info: Dict) -> str:
    """파일 확장자 또는 processor_type 기반 Reader 결정"""
    # file_catalog.processor_type 확인
    if file_info.get("processor_type") == "signal":
        ext = file_info.get("file_extension", "").lower()
        return READER_MAP.get(ext, "generic_signal_reader")
    else:
        ext = file_info.get("file_extension", "").lower()
        return READER_MAP.get(ext, "pandas_csv")
```

#### Delegated Tasks 정의

```python
def _build_delegated_tasks(
    self, 
    cohort_def: CohortDefinition,
    params: List[ResolvedParameter]
) -> List[Dict]:
    """
    Analysis Agent가 수행할 작업 정의
    """
    tasks = []
    
    # Task 1: Cohort 필터링 (스캔 필요 시)
    if cohort_def.strategy == "scan_required":
        tasks.append({
            "task_id": "filter_cohort",
            "task_type": "file_scan_filter",
            "description": "파일을 스캔하여 조건에 맞는 ID 추출",
            "input": "cohort_source",
            "filter_logic": cohort_def.filter_logic,
            "output": "cohort_ids"
        })
    
    # Task 2: 데이터 로드
    tasks.append({
        "task_id": "load_target_data",
        "task_type": "data_load",
        "description": "지정된 파라미터 데이터 로드",
        "input": "data_sources",
        "parameters": [p.param_keys for p in params],
        "join_with": "cohort_ids",
        "output": "extracted_data"
    })
    
    return tasks
```

---

### 🔷 [600] PlanValidatorNode

**역할**: 생성된 Plan의 유효성 검증 및 신뢰도 평가

| 항목 | 내용 |
|------|------|
| **Order** | 600 |
| **Type** | 📏🤖 Hybrid |
| **Input** | `execution_plan` |
| **Output** | `validated_plan`, `validation_warnings`, `overall_confidence` |
| **DB 접근** | file_catalog (파일 존재 확인) |
| **Neo4j 접근** | 없음 |

#### 검증 항목

```python
def execute(self, state: ExtractionAgentState) -> Dict[str, Any]:
    plan = state["execution_plan"]
    warnings = []
    
    # 1. 파일 존재 여부 확인
    file_warnings = self._validate_file_existence(plan)
    warnings.extend(file_warnings)
    
    # 2. Join Path 유효성 확인
    join_warnings = self._validate_join_paths(plan)
    warnings.extend(join_warnings)
    
    # 3. Parameter 커버리지 확인
    param_warnings = self._validate_parameter_coverage(plan, state)
    warnings.extend(param_warnings)
    
    # 4. 데이터 타입 호환성 확인
    type_warnings = self._validate_data_types(plan)
    warnings.extend(type_warnings)
    
    # 5. Confidence 계산
    confidence = self._calculate_confidence(plan, warnings, state)
    
    # 6. Human Review 필요 여부 판단
    needs_review = (
        confidence < 0.7 or 
        any(w["severity"] == "high" for w in warnings) or
        len(state.get("ambiguities", [])) > 0
    )
    
    return {
        "plan_validator_result": {"status": "success"},
        "validated_plan": {**plan, "validation": {...}},
        "validation_warnings": warnings,
        "overall_confidence": confidence,
        "needs_human_review": needs_review,
        "human_review_type": self._get_review_type(warnings, state) if needs_review else None,
        "human_question": self._generate_review_question(warnings, state) if needs_review else None
    }
```

#### 신뢰도 계산

```python
def _calculate_confidence(
    self, 
    plan: Dict, 
    warnings: List[Dict], 
    state: Dict
) -> float:
    """
    전체 신뢰도 계산 (0.0 ~ 1.0)
    
    감점 요소:
    - High severity warning: -0.3
    - Medium severity warning: -0.1
    - Low severity warning: -0.05
    - 모호한 매핑: -0.1 per ambiguity
    - Join 경로 없음: -0.2
    """
    confidence = 1.0
    
    # 경고에 따른 감점
    severity_penalty = {
        "high": 0.3,
        "medium": 0.1,
        "low": 0.05
    }
    for w in warnings:
        confidence -= severity_penalty.get(w["severity"], 0.05)
    
    # 모호성에 따른 감점
    ambiguities = state.get("ambiguities", [])
    confidence -= len(ambiguities) * 0.1
    
    # Join 경로 없으면 감점
    if not plan.get("execution_plan", {}).get("join_specification", {}).get("paths"):
        confidence -= 0.2
    
    return max(0.0, min(1.0, confidence))
```

---

## 📊 ExtractionAgentState 전체 스키마

```python
from typing import TypedDict, List, Dict, Any, Optional, Literal, Annotated
import operator


class ExtractionAgentState(TypedDict):
    """
    ExtractionAgent 워크플로우 전체 상태
    """
    
    # ═══════════════════════════════════════════════════════════════════════
    # Input
    # ═══════════════════════════════════════════════════════════════════════
    user_query: str                           # 원본 자연어 쿼리
    
    # ═══════════════════════════════════════════════════════════════════════
    # [100] query_understanding
    # ═══════════════════════════════════════════════════════════════════════
    query_understanding_result: Optional[Dict[str, Any]]  # 노드 실행 결과 요약
    
    intent: Optional[Literal[
        "data_retrieval", "aggregation", "exploration", 
        "relationship", "metadata_lookup"
    ]]
    
    extracted_entities: List[Dict[str, Any]]
    # [{
    #   "type": "parameter",
    #   "value": "심박수",
    #   "normalized": "Heart Rate",
    #   "candidates": ["HR", "Heart Rate"],
    #   "condition_type": null,
    #   "confidence": 0.95
    # }]
    
    resolution_strategy: Optional[Literal[
        "metadata_only", "partial_metadata", "scan_required"
    ]]
    
    # ═══════════════════════════════════════════════════════════════════════
    # [200] semantic_resolver
    # ═══════════════════════════════════════════════════════════════════════
    semantic_resolver_result: Optional[Dict[str, Any]]
    
    resolved_parameters: List[Dict[str, Any]]
    # [{
    #   "semantic_term": "심박수",
    #   "param_keys": ["Solar8000/HR", "BIS/HR"],
    #   "concept_category": "Vital Signs",
    #   "source_type": "group_common",
    #   "group_id": "uuid-...",
    #   "unit": "bpm",
    #   "confidence": 0.9
    # }]
    
    resolved_filters: List[Dict[str, Any]]
    # [{
    #   "entity_type": "diagnosis",
    #   "semantic_term": "위암",
    #   "column_name": "diagnosis",
    #   "file_id": "uuid-...",
    #   "operator": "LIKE",
    #   "value": "%Stomach Cancer%",
    #   "confidence": 0.85
    # }]
    
    ambiguities: List[Dict[str, Any]]
    # [{
    #   "type": "parameter",
    #   "term": "BP",
    #   "candidates": [
    #     {"key": "NIBP", "name": "Non-Invasive BP"},
    #     {"key": "ABP", "name": "Arterial BP"}
    #   ],
    #   "reason": "Multiple BP types available"
    # }]
    
    # ═══════════════════════════════════════════════════════════════════════
    # [300] topology_navigator
    # ═══════════════════════════════════════════════════════════════════════
    topology_navigator_result: Optional[Dict[str, Any]]
    
    data_topology: Optional[Dict[str, Any]]
    # {
    #   "cohort_source": {
    #     "file_id": "uuid",
    #     "file_path": "/data/clinical_data.csv",
    #     "entity_type": "surgery",
    #     "identifier_column": "caseid"
    #   },
    #   "target_sources": [{
    #     "type": "file_group",
    #     "group_id": "uuid",
    #     "group_name": "vital_case_records"
    #   }],
    #   "join_paths": [{
    #     "from_file": "clinical_data.csv",
    #     "to_target": "vital_case_records",
    #     "source_column": "caseid",
    #     "target_column": "filename_values.caseid",
    #     "cardinality": "1:N"
    #   }]
    # }
    
    # ═══════════════════════════════════════════════════════════════════════
    # [400] cohort_analyzer
    # ═══════════════════════════════════════════════════════════════════════
    cohort_analyzer_result: Optional[Dict[str, Any]]
    
    cohort_definition: Optional[Dict[str, Any]]
    # {
    #   "strategy": "partial_metadata",
    #   "filter_logic": [
    #     {"column": "diagnosis", "operator": "LIKE", "value": "%Stomach Cancer%"}
    #   ],
    #   "estimated_cohort_size": 150,
    #   "scan_reason": null
    # }
    
    # ═══════════════════════════════════════════════════════════════════════
    # [500] plan_builder
    # ═══════════════════════════════════════════════════════════════════════
    plan_builder_result: Optional[Dict[str, Any]]
    
    execution_plan: Optional[Dict[str, Any]]   # 최종 Execution Plan JSON
    
    # ═══════════════════════════════════════════════════════════════════════
    # [600] plan_validator
    # ═══════════════════════════════════════════════════════════════════════
    plan_validator_result: Optional[Dict[str, Any]]
    
    validated_plan: Optional[Dict[str, Any]]   # 검증 완료된 Plan
    validation_warnings: List[Dict[str, Any]]  # 경고 목록
    overall_confidence: float                   # 전체 신뢰도 (0.0 ~ 1.0)
    
    # ═══════════════════════════════════════════════════════════════════════
    # Human-in-the-Loop
    # ═══════════════════════════════════════════════════════════════════════
    needs_human_review: bool
    human_review_type: Optional[Literal[
        "ambiguous_parameter",
        "ambiguous_join_path",
        "low_confidence",
        "missing_data_source"
    ]]
    human_question: Optional[str]
    human_feedback: Optional[str]
    
    # ═══════════════════════════════════════════════════════════════════════
    # System
    # ═══════════════════════════════════════════════════════════════════════
    logs: Annotated[List[str], operator.add]
    error_message: Optional[str]
    retry_count: int
```

---

## 📄 최종 Output: Execution Plan JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ExtractionAgent Execution Plan",
  "type": "object",
  "required": ["version", "intent", "execution_plan"],
  "properties": {
    "version": {
      "type": "string",
      "const": "1.0"
    },
    "generated_at": {
      "type": "string",
      "format": "date-time"
    },
    "intent": {
      "type": "string",
      "enum": ["data_retrieval", "aggregation", "exploration", "relationship", "metadata_lookup"]
    },
    "original_query": {
      "type": "string"
    },
    
    "entities": {
      "type": "object",
      "description": "추출된 Entity들의 정리된 형태",
      "additionalProperties": true
    },
    
    "execution_plan": {
      "type": "object",
      "required": ["cohort_source", "data_sources"],
      "properties": {
        "cohort_source": {
          "type": "object",
          "required": ["type", "file_id", "file_path"],
          "properties": {
            "type": {"type": "string", "enum": ["tabular_file", "file_group"]},
            "file_id": {"type": "string", "format": "uuid"},
            "file_path": {"type": "string"},
            "file_name": {"type": "string"},
            "reader": {"type": "string"},
            "filter_logic": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "column": {"type": "string"},
                  "operator": {"type": "string"},
                  "value": {},
                  "values": {"type": "array"}
                }
              }
            },
            "result_identifier": {"type": "string"},
            "estimated_rows": {"type": "integer"}
          }
        },
        
        "data_sources": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "type": {"type": "string", "enum": ["file_group", "single_file"]},
              "group_id": {"type": "string", "format": "uuid"},
              "group_name": {"type": "string"},
              "file_id": {"type": "string", "format": "uuid"},
              "file_path": {"type": "string"},
              "reader": {"type": "string"},
              "file_pattern": {"type": "string"},
              "file_count": {"type": "integer"},
              "sample_paths": {"type": "array", "items": {"type": "string"}},
              "target_parameters": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "param_key": {"type": "string"},
                    "semantic_name": {"type": "string"},
                    "unit": {"type": "string"}
                  }
                }
              },
              "join_key": {
                "type": "object",
                "properties": {
                  "source": {"type": "string"},
                  "target": {"type": "string"}
                }
              }
            }
          }
        },
        
        "join_specification": {
          "type": "object",
          "properties": {
            "paths": {
              "type": "array",
              "items": {
                "type": "object",
                "properties": {
                  "from": {"type": "string"},
                  "to": {"type": "string"},
                  "via": {"type": "string"},
                  "cardinality": {"type": "string"}
                }
              }
            }
          }
        }
      }
    },
    
    "resolution_strategy": {
      "type": "string",
      "enum": ["metadata_only", "partial_metadata", "scan_required"]
    },
    
    "delegated_tasks": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "task_id": {"type": "string"},
          "task_type": {"type": "string"},
          "description": {"type": "string"},
          "input": {"type": "string"},
          "output": {"type": "string"}
        }
      }
    },
    
    "validation": {
      "type": "object",
      "properties": {
        "validated_at": {"type": "string", "format": "date-time"},
        "warnings": {"type": "array"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
      }
    }
  }
}
```

---

## 🎯 예시 시나리오

### 시나리오 1: 기본 데이터 추출

**쿼리**: "2023년 위암 환자의 심박수(HR) 데이터를 줘"

```
[100] query_understanding
├─ Intent: data_retrieval
├─ Entities:
│   ├─ diagnosis: "위암" → "Stomach Cancer"
│   ├─ temporal: "2023년" → {2023-01-01 ~ 2023-12-31}
│   └─ parameter: "심박수" → "Heart Rate"
└─ Strategy: partial_metadata

[200] semantic_resolver
├─ Parameters:
│   └─ "심박수" → [Solar8000/HR, BIS/HR] (group_common)
├─ Filters:
│   ├─ diagnosis → column "diagnosis" in clinical_data.csv
│   └─ op_date → column "op_date" in clinical_data.csv
└─ Ambiguities: []

[300] topology_navigator
├─ Cohort Source: clinical_data.csv (identifier: caseid)
├─ Target Sources: vital_case_records (FileGroup)
└─ Join Path: clinical_data.caseid → vital.filename_values.caseid

[400] cohort_analyzer
├─ Strategy: partial_metadata
├─ Filter Logic: [diagnosis LIKE, op_date BETWEEN]
└─ Estimated Size: ~150 cases

[500] plan_builder
└─ Execution Plan JSON 생성

[600] plan_validator
├─ Warnings: []
└─ Confidence: 0.92
```

### 시나리오 2: 값 조건 포함

**쿼리**: "수술 중 저혈압(SBP < 90)이 발생한 환자의 Vital 파일"

```
[100] query_understanding
├─ Intent: data_retrieval
├─ Entities:
│   ├─ condition: "SBP < 90" → {column: SBP, operator: <, value: 90}
│   └─ parameter: "Vital" → (all vital signs)
└─ Strategy: scan_required  ← 값 조건이므로 스캔 필요

[400] cohort_analyzer
├─ Strategy: scan_required
├─ Scan Reason: "Value comparison (SBP < 90) requires file scan"
└─ Delegated Task: "Scan vital files, filter by SBP < 90"
```

---

## 📁 파일 구조

```
ExtractionAgent/
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── graph.py                        # LangGraph 워크플로우 빌더
│   │   ├── state.py                        # ExtractionAgentState
│   │   ├── registry.py                     # NodeRegistry (shared에서 import 가능)
│   │   ├── base/
│   │   │   ├── __init__.py
│   │   │   ├── node.py                     # BaseNode
│   │   │   └── mixins.py                   # LLMMixin, DatabaseMixin
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── enums.py                    # Intent, EntityType, etc.
│   │   │   ├── llm_responses.py            # LLM 응답 Pydantic 모델
│   │   │   └── execution_plan.py           # ExecutionPlan 스키마
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── query_understanding/        # [100]
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── semantic_resolver/          # [200]
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── topology_navigator/         # [300]
│   │       │   ├── __init__.py
│   │       │   └── node.py
│   │       ├── cohort_analyzer/            # [400]
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── plan_builder/               # [500]
│   │       │   ├── __init__.py
│   │       │   └── node.py
│   │       └── plan_validator/             # [600]
│   │           ├── __init__.py
│   │           ├── node.py
│   │           └── prompts.py
│   │
│   └── config.py
│
├── tests/
│   ├── test_query_understanding.py
│   ├── test_semantic_resolver.py
│   ├── test_topology_navigator.py
│   ├── test_full_pipeline.py
│   └── fixtures/
│       └── sample_queries.json
│
├── examples/
│   ├── basic_extraction.py
│   ├── complex_query.py
│   └── example_outputs/
│
├── ARCHITECTURE_V2.md                      # 이 문서
├── requirements.txt
└── README.md
```

---

## ⚙️ 설정

### Node별 설정

```python
# src/config.py

class QueryUnderstandingConfig:
    """[100] QueryUnderstanding 노드 설정"""
    MAX_ENTITIES = 10                    # 최대 추출 Entity 수
    CONFIDENCE_THRESHOLD = 0.7           # 최소 신뢰도


class SemanticResolverConfig:
    """[200] SemanticResolver 노드 설정"""
    MAX_CANDIDATES = 10                  # 최대 후보 수
    AMBIGUITY_THRESHOLD = 0.6            # 모호성 판단 기준
    CACHE_ENABLED = True                 # 캐싱 활성화
    CACHE_TTL = 3600                     # 캐시 유효 시간 (초)


class TopologyNavigatorConfig:
    """[300] TopologyNavigator 노드 설정"""
    MAX_JOIN_HOPS = 3                    # 최대 Join 홉 수


class CohortAnalyzerConfig:
    """[400] CohortAnalyzer 노드 설정"""
    VALUE_DISTRIBUTION_SAMPLE_THRESHOLD = 100  # 이 이상이면 샘플링됨


class PlanBuilderConfig:
    """[500] PlanBuilder 노드 설정"""
    MAX_SAMPLE_PATHS = 5                 # 샘플 파일 경로 수


class PlanValidatorConfig:
    """[600] PlanValidator 노드 설정"""
    CONFIDENCE_THRESHOLD_FOR_REVIEW = 0.7  # Human Review 기준
    VERIFY_FILE_EXISTENCE = True           # 파일 존재 확인 여부
```

---

## 🔗 shared 패키지 의존성

ExtractionAgent는 다음 shared 컴포넌트를 사용합니다:

```python
# Database (Read Only)
from shared.database import (
    get_db_manager,
    ParameterReader,          # Read-only, cached
    TopologyReader,           # Read-only
    FileRepository,           # Read-only 메서드만 사용
)

# Neo4j
from shared.neo4j import (
    get_neo4j_connection,
    ParameterQueryBuilder,
    TopologyQueryBuilder,
)

# Models
from shared.models import (
    ConceptCategory,
    SourceType,
    ColumnRole,
)

# LLM
from shared.llm import (
    get_llm_client,
)

# Config
from shared.config import (
    DatabaseConfig,
    Neo4jConfig,
    LLMConfig,
)
```

---

## 📝 변경 이력

### v2.0 (Current)
- 완전히 새로운 아키텍처로 재설계
- Text-to-SQL 방식에서 **Execution Plan 생성** 방식으로 변경
- 6개 노드 파이프라인 (query_understanding → plan_validator)
- shared 패키지 사용으로 IndexingAgent와 인프라 공유
- Read-Only Repository 패턴 도입

### v1.0 (Legacy)
- Text-to-SQL 에이전트
- 직접 데이터 반환 방식
- 별도의 database/ 모듈 보유 (중복)

