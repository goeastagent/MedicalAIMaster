# VitalExtractionAgent 아키텍처 및 구현 명세

## 📖 개요

VitalExtractionAgent는 **VitalDB .vital 파일**에 특화된 경량 Extraction Agent입니다.

### 핵심 특징

```
✅ 동적 스키마 인식
   - Target: Signal 데이터 (FileGroup)
   - Cohort Source: DB 메타데이터에서 동적 식별
   - Join Key: table_relationships에서 자동 파악

✅ 메타데이터 기반 동작
   - 실제 데이터 파일에 접근하지 않음
   - IndexingAgent가 구축한 DB 메타데이터만 사용
   - 어떤 데이터셋이든 동일한 코드로 처리 가능

✅ 3-Node 파이프라인
   - [100] QueryUnderstanding: 동적 컨텍스트 로딩 + 쿼리 이해
   - [200] ParameterResolver: 파라미터 매핑
   - [300] PlanBuilder: 실행 계획 생성
```

### 데이터 구조 (DB 메타데이터 기반)

```
                 PostgreSQL 메타데이터                                VitalExtractionAgent
┌───────────────────────────────────────────────────────┐    ┌───────────────────────────────┐
│                                                       │    │                               │
│  file_catalog                  file_group             │    │  동적 컨텍스트 로딩            │
│  ┌─────────────────────┐      ┌──────────────────┐   │    │  ═══════════════════           │
│  │ [Cohort Source]     │      │ [Signal Group]   │   │    │                               │
│  │ - is_metadata=false │      │ - status=confirm │   │───▶│  1. Cohort Source 식별        │
│  │ - group_id=NULL     │      │ - file_count=N   │   │    │  2. Signal Group 식별         │
│  └─────────────────────┘      └──────────────────┘   │    │  3. Join Relationship 파악    │
│           │                            │              │    │  4. Parameter 카테고리 수집   │
│           │                            │              │    │                               │
│  table_entities                parameter              │    │  → LLM 프롬프트 컨텍스트      │
│  ┌─────────────────────┐      ┌──────────────────┐   │    │                               │
│  │ row_represents      │      │ concept_category │   │    └───────────────────────────────┘
│  │ entity_identifier   │      │ semantic_name    │   │
│  │ (DB에서 동적 조회)  │      │ param_key        │   │
│  └─────────────────────┘      └──────────────────┘   │
│           │                                          │
│  table_relationships                                 │
│  ┌─────────────────────────────────────────────┐    │
│  │ source_file_id → target_group_id            │    │
│  │ source_column, target_column                │    │
│  │ cardinality (1:1, 1:N, etc.)                │    │
│  └─────────────────────────────────────────────┘    │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

## 🔄 워크플로우 아키텍처 (3-Node + 동적 컨텍스트)

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          입력: 자연어 쿼리                                    ┃
┃             "위암 환자의 수술 중 심박수 데이터"                               ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          [100] QueryUnderstanding 🤖📊                        ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                              ┃
┃   ┌─────────────────────────────────────────────────────────────────────┐   ┃
┃   │ Step 1: 동적 컨텍스트 로딩 📊                                        │   ┃
┃   │   • PostgreSQL/Neo4j에서 스키마 메타데이터 조회                       │   ┃
┃   │   • Cohort Sources, Signal Groups, Parameters, Relationships 수집   │   ┃
┃   │   • LLM 프롬프트용 컨텍스트 텍스트 생성                              │   ┃
┃   └─────────────────────────────────────────────────────────────────────┘   ┃
┃                                         │                                    ┃
┃                                         ▼                                    ┃
┃   ┌─────────────────────────────────────────────────────────────────────┐   ┃
┃   │ Step 2: LLM 쿼리 분석 🤖                                             │   ┃
┃   │   • 동적 컨텍스트를 포함한 프롬프트로 LLM 호출                       │   ┃
┃   │   • Intent 분류, Entity 추출, Filter 생성                           │   ┃
┃   └─────────────────────────────────────────────────────────────────────┘   ┃
┃                                                                              ┃
┃   Output:                                                                    ┃
┃     - schema_context: {cohort_sources, signal_groups, parameters, ...}      ┃
┃     - intent: "data_retrieval"                                              ┃
┃     - parameters: ["심박수"]                                                 ┃
┃     - filters: [{column: "diagnosis", op: "LIKE", value: "%Stomach%"}]      ┃
┃     - temporal: {type: "procedure_window"}                                  ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          [200] ParameterResolver 🤖📏                         ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃   • PostgreSQL parameter 테이블 검색                                         ┃
┃   • "심박수" → [Solar8000/HR, BIS/HR, Philips/HR] 매핑                       ┃
┃   • 모호성 처리 (LLM이 ALL/PICK/CLARIFY 결정)                                ┃
┃                                                                              ┃
┃   Output:                                                                    ┃
┃     - resolved_params: [{key: "Solar8000/HR", name: "Heart Rate", ...}]     ┃
┃     - resolution_mode: "all_sources"                                        ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          [300] PlanBuilder 📏                                 ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃   • Execution Plan JSON 조립                                                 ┃
┃   • schema_context에서 토폴로지 정보 사용                                    ┃
┃   • Temporal Alignment 설정 (수술 중 구간 등)                                ┃
┃   • Validation (파일 존재 샘플 확인)                                         ┃
┃                                                                              ┃
┃   Output: Execution Plan JSON                                               ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                             │
                                             ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          출력: Execution Plan JSON                            ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

### 핵심 설계 원칙

```
❌ 하드코딩된 스키마 정보 (기존)
   - 특정 파일명, 컬럼명 등이 코드에 박혀있음
   - 다른 데이터셋에 재사용 불가

✅ 동적 컨텍스트 로딩 (신규)
   - IndexingAgent가 구축한 메타데이터 DB에서 스키마 정보 로드
   - LLM에게 실제 데이터 구조를 컨텍스트로 제공
   - 어떤 데이터셋이든 동일한 코드로 처리 가능
```

---

## 🗄️ 데이터베이스 및 온톨로지 참조 요약

### PostgreSQL 테이블 (Read-Only)

| 테이블 | 설명 | 사용 노드 |
|--------|------|----------|
| `file_catalog` | 파일 메타데이터 (file_path, is_metadata, group_id) | [100], [300] |
| `file_group` | 파일 그룹 정보 (group_name, status, entity_identifier_key) | [100], [200], [300] |
| `column_metadata` | 컬럼 정보 (column_role, value_distribution) | [100], [300] |
| `table_entities` | 테이블 Entity 정보 (row_represents, entity_identifier) | [100] |
| `table_relationships` | 테이블 간 관계 (source, target, join_key, cardinality) | [100], [300] |
| `parameter` | 파라미터 메타데이터 (param_key, semantic_name, unit, concept_category) | [100], [200] |

### Neo4j 온톨로지 (Read-Only)

| 노드/관계 | 설명 | 사용 노드 |
|-----------|------|----------|
| `(:Parameter)` | 파라미터 노드 (key, semantic_name, unit) | [100], [200] |
| `(:ConceptCategory)` | 개념 카테고리 노드 (Vital Signs, etc.) | [100], [200] |
| `(:FileGroup)` | 파일 그룹 노드 | [100], [200] |
| `(:ConceptCategory)-[:CONTAINS]->(:Parameter)` | 카테고리 → 파라미터 관계 | [100], [200] |
| `(:FileGroup)-[:HAS_COMMON_PARAM]->(:Parameter)` | 그룹 → 공통 파라미터 관계 | [100], [200] |

### 노드별 데이터 접근 패턴

```
[100] QueryUnderstanding (동적 컨텍스트 로딩 + 쿼리 분석)
├─ PostgreSQL: ✅ file_catalog, file_group, column_metadata, 
│              table_entities, table_relationships, parameter
├─ Neo4j: ✅ (Optional) Parameter, ConceptCategory for synonym search
└─ LLM: ✅ 쿼리 파싱

[200] ParameterResolver
├─ PostgreSQL: ✅ parameter, file_group
├─ Neo4j: ✅ Parameter, ConceptCategory, FileGroup
└─ LLM: ✅ Resolution Mode 결정

[300] PlanBuilder
├─ PostgreSQL: ✅ file_catalog, file_group, column_metadata
├─ Neo4j: ❌ 없음
└─ LLM: ❌ 없음
└─ 참조: state["schema_context"] (토폴로지 정보)
```

### 컨텍스트 수집 SQL 쿼리 요약

```sql
-- [100] QueryUnderstanding: 동적 컨텍스트 로딩

-- Q1. Cohort Source 후보
SELECT fc.*, te.row_represents, te.entity_identifier
FROM file_catalog fc
JOIN table_entities te ON fc.file_id = te.file_id
WHERE fc.is_metadata = false AND fc.group_id IS NULL;

-- Q2. Signal Group 정보
SELECT group_id, group_name, file_count, row_represents, 
       entity_identifier_key, related_files
FROM file_group WHERE status = 'confirmed';

-- Q3. 필터 가능한 컬럼
SELECT fc.file_name, cm.original_name, cm.column_role, cm.value_distribution
FROM column_metadata cm
JOIN file_catalog fc ON cm.file_id = fc.file_id
WHERE fc.is_metadata = false AND cm.column_role IN ('identifier', 'attribute', 'timestamp');

-- Q4. 파라미터 카테고리 요약
SELECT concept_category, array_agg(param_key), array_agg(semantic_name)
FROM parameter WHERE source_type = 'group_common'
GROUP BY concept_category;

-- Q5. 테이블 관계
SELECT source_table, target_table, source_column, target_column, cardinality
FROM table_relationships tr
JOIN file_catalog sf ON tr.source_file_id = sf.file_id
LEFT JOIN file_catalog tf ON tr.target_file_id = tf.file_id;
```

---

## 📊 노드별 상세 명세

### 🔷 [100] QueryUnderstandingNode

**역할**: DB 메타데이터 기반 동적 컨텍스트 생성 + 자연어 쿼리 분석

| 항목 | 내용 |
|------|------|
| **Order** | 100 |
| **Type** | 🤖📊 LLM + DB Context |
| **Input** | `user_query` |
| **Output** | `schema_context`, `intent`, `requested_parameters`, `cohort_filters`, `temporal_context` |
| **PostgreSQL** | ✅ `file_catalog`, `file_group`, `column_metadata`, `table_entities`, `table_relationships`, `parameter` |
| **Neo4j** | ✅ (Optional) `Parameter`, `ConceptCategory` 노드 |
| **LLM** | ✅ OpenAI/Claude (쿼리 파싱) |

---

#### 📊 Step 1: 동적 컨텍스트 로딩

**PostgreSQL 쿼리 (컨텍스트 수집)**:

```sql
-- 1. Cohort Source 후보 식별
SELECT 
    fc.file_id,
    fc.file_name,
    fc.file_path,
    te.row_represents,
    te.entity_identifier,
    fc.file_metadata->'row_count' as row_count
FROM file_catalog fc
JOIN table_entities te ON fc.file_id = te.file_id
WHERE fc.is_metadata = false 
  AND fc.group_id IS NULL;

-- 2. Cohort Source의 필터 가능한 컬럼
SELECT 
    fc.file_name,
    cm.original_name,
    cm.column_type,
    cm.column_role,
    cm.value_distribution
FROM column_metadata cm
JOIN file_catalog fc ON cm.file_id = fc.file_id
WHERE fc.is_metadata = false
  AND fc.group_id IS NULL
  AND cm.column_role IN ('identifier', 'attribute', 'timestamp');

-- 3. Signal Data 그룹 정보
SELECT 
    fg.group_id,
    fg.group_name,
    fg.file_count,
    fg.row_represents,
    fg.entity_identifier_key,
    fg.grouping_criteria,
    fg.related_files
FROM file_group fg
WHERE fg.status = 'confirmed';

-- 4. 파라미터 카테고리 요약
SELECT 
    p.concept_category,
    array_agg(DISTINCT p.param_key ORDER BY p.param_key) as param_keys,
    array_agg(DISTINCT p.semantic_name) as semantic_names
FROM parameter p
WHERE p.source_type = 'group_common'
  AND p.concept_category IS NOT NULL
GROUP BY p.concept_category;

-- 5. 테이블 간 관계
SELECT 
    sf.file_name as source_table,
    COALESCE(tf.file_name, fg.group_name) as target_table,
    tr.source_column,
    tr.target_column,
    tr.cardinality
FROM table_relationships tr
JOIN file_catalog sf ON tr.source_file_id = sf.file_id
LEFT JOIN file_catalog tf ON tr.target_file_id = tf.file_id
LEFT JOIN file_group fg ON tf.group_id = fg.group_id;
```

**Neo4j 쿼리 (선택적 보강)**:

```cypher
-- 파라미터 카테고리별 검색 키워드 (synonym 포함)
MATCH (c:ConceptCategory)-[:CONTAINS]->(p:Parameter)
WHERE EXISTS((fg:FileGroup)-[:HAS_COMMON_PARAM]->(p))
RETURN 
    c.name as category,
    collect(DISTINCT p.key) as param_keys,
    collect(DISTINCT p.semantic_name) as names
ORDER BY c.name;
```

---

#### 🧠 Step 2: 컨텍스트 포맷팅

```python
class SchemaContextBuilder:
    """DB 메타데이터를 LLM용 컨텍스트로 변환"""
    
    def build(self) -> Dict[str, Any]:
        """전체 스키마 컨텍스트 수집"""
        return {
            "cohort_sources": self._load_cohort_sources(),
            "signal_groups": self._load_signal_groups(),
            "parameters": self._load_parameter_summary(),
            "relationships": self._load_relationships(),
            "context_text": self._generate_context_text()
        }
    
    def _generate_context_text(self) -> str:
        """LLM 프롬프트에 주입할 텍스트 생성"""
        # 위의 "생성된 컨텍스트 예시" 형식으로 포맷팅
        ...
```

**schema_context 출력 예시** (DB에서 동적으로 조회된 결과):

```python
{
    "cohort_sources": [
        {
            "file_id": "uuid-...",
            "file_name": "<cohort_file_name>",      # DB에서 조회
            "row_represents": "<entity_type>",       # table_entities에서 조회
            "entity_identifier": "<identifier_col>", # table_entities에서 조회
            "row_count": 0,                          # file_metadata에서 조회
            "filterable_columns": [
                # column_metadata에서 동적 조회
                {"name": "<col_name>", "type": "categorical", "samples": [...]},
                {"name": "<col_name>", "type": "continuous", "range": [...]},
                ...
            ],
            "temporal_columns": [...]  # column_role='timestamp'인 컬럼들
        }
    ],
    "signal_groups": [
        {
            "group_id": "uuid-...",
            "group_name": "<group_name>",           # file_group에서 조회
            "file_count": 0,                        # file_group.file_count
            "file_pattern": "{...}.vital",          # grouping_criteria에서 조회
            "row_represents": "<entity_type>",      # file_group.row_represents
            "entity_identifier_key": "<key>"        # file_group.entity_identifier_key
        }
    ],
    "parameters": {
        # parameter 테이블에서 concept_category별로 그룹핑
        "<category>": ["<param_key>", ...],
        ...
    },
    "relationships": [
        # table_relationships에서 동적 조회
        {"from": "<source>", "to": "<target>", "via": "<column>", "cardinality": "<1:1|1:N>"}
    ],
    "context_text": "### Cohort Sources...\n### Signal Groups...\n..."
}
```

#### Intent (고정)

VitalExtractionAgent는 data_retrieval만 지원:

```python
class Intent(Enum):
    DATA_RETRIEVAL = "data_retrieval"  # .vital 파일에서 파라미터 추출
```

#### Entity Types (축소)

```python
class EntityType(Enum):
    PARAMETER = "parameter"       # 측정 파라미터 (HR, SpO2, BP)
    DIAGNOSIS = "diagnosis"       # 진단명 (위암, 당뇨)
    TEMPORAL = "temporal"         # 시간 조건 (수술 중, 마취 유도 후)
    DEMOGRAPHIC = "demographic"   # 인구통계 (남성, 60세 이상)
    IDENTIFIER = "identifier"     # 식별자 (caseid=123)


class TemporalType(Enum):
    """Vital Signal 슬라이싱용 시간 유형"""
    FULL_RECORD = "full_record"           # 전체 기록
    PROCEDURE_WINDOW = "procedure_window"  # 시술/수술 중 (procedure_start ~ procedure_end)
    TREATMENT_WINDOW = "treatment_window"  # 치료 중 (treatment_start ~ treatment_end)
    CUSTOM_WINDOW = "custom_window"       # 사용자 정의 구간
```

#### 동적 컨텍스트 로딩 (핵심 설계)

**문제점**: 하드코딩된 스키마 정보는 유지보수가 어렵고, 다른 데이터셋에 재사용 불가

**해결책**: IndexingAgent가 생성한 **기존 메타데이터 테이블**에서 동적으로 컨텍스트 로드

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         컨텍스트 로딩 흐름                                   │
│                                                                              │
│  IndexingAgent (이미 완료)                  VitalExtractionAgent             │
│  ─────────────────────────                  ─────────────────────            │
│                                                                              │
│  파이프라인 완료 후 DB에 저장된:            [100] QueryUnderstanding          │
│                                                    │                         │
│  PostgreSQL:                                       ▼                         │
│  ┌─────────────────────────┐              ┌─────────────────┐               │
│  │ file_catalog            │              │ SchemaContext   │               │
│  │ file_group              │ ──────────▶  │ Builder         │               │
│  │ column_metadata         │   SQL 쿼리   │ (5개 쿼리)      │               │
│  │ table_entities          │              └────────┬────────┘               │
│  │ table_relationships     │                       │                         │
│  │ parameter               │                       ▼                         │
│  └─────────────────────────┘              ┌─────────────────┐               │
│                                           │ LLM 프롬프트    │               │
│  Neo4j (Optional 보강):                   │ 컨텍스트 생성   │               │
│  ┌─────────────────────────┐              └─────────────────┘               │
│  │ (:Parameter)            │                                                 │
│  │ (:ConceptCategory)      │                                                 │
│  └─────────────────────────┘                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

**장점**:
- IndexingAgent 수정 불필요 (기존 테이블 그대로 사용)
- 실시간 최신 데이터 반영
- 즉시 구현 가능

---

#### 컨텍스트 로딩 쿼리 (PostgreSQL)

```sql
-- 1. Cohort Source 후보 식별 (is_metadata=false, group_id IS NULL인 파일들)
SELECT 
    fc.file_id,
    fc.file_name,
    fc.file_path,
    te.row_represents,
    te.entity_identifier,
    array_agg(DISTINCT cm.original_name) as columns
FROM file_catalog fc
JOIN table_entities te ON fc.file_id = te.file_id
JOIN column_metadata cm ON fc.file_id = cm.file_id
WHERE fc.is_metadata = false 
  AND fc.group_id IS NULL
GROUP BY fc.file_id, fc.file_name, fc.file_path, te.row_represents, te.entity_identifier;

-- 2. FileGroup 요약 (Signal 데이터 그룹)
SELECT 
    fg.group_id,
    fg.group_name,
    fg.file_count,
    fg.row_represents,
    fg.entity_identifier_key,
    fg.grouping_criteria,
    fg.related_files
FROM file_group fg
WHERE fg.status = 'confirmed';

-- 3. 파라미터 카테고리별 요약
SELECT 
    p.concept_category,
    array_agg(DISTINCT p.param_key) as param_keys,
    array_agg(DISTINCT p.semantic_name) as semantic_names,
    array_agg(DISTINCT p.unit) FILTER (WHERE p.unit IS NOT NULL) as units
FROM parameter p
WHERE p.source_type = 'group_common'
GROUP BY p.concept_category
ORDER BY p.concept_category;

-- 4. 테이블 간 관계
SELECT 
    sf.file_name as source_table,
    tf.file_name as target_table,
    tr.source_column,
    tr.target_column,
    tr.cardinality
FROM table_relationships tr
JOIN file_catalog sf ON tr.source_file_id = sf.file_id
JOIN file_catalog tf ON tr.target_file_id = tf.file_id;

-- 5. 컬럼 역할별 요약 (Cohort 필터링 가능한 컬럼)
SELECT 
    fc.file_name,
    cm.original_name,
    cm.column_type,
    cm.column_role,
    cm.value_distribution->'unique_count' as unique_count,
    cm.value_distribution->'unique_values' as sample_values
FROM column_metadata cm
JOIN file_catalog fc ON cm.file_id = fc.file_id
WHERE fc.is_metadata = false
  AND cm.column_role IN ('identifier', 'attribute', 'timestamp')
ORDER BY fc.file_name, cm.column_role;
```

---

#### LLM 프롬프트 (동적 컨텍스트 주입)

```python
SYSTEM_PROMPT_TEMPLATE = """
You are a medical data query analyzer.

Your task is to understand user queries and map them to the available data schema.

## Available Data Schema
{schema_context}

## Your Task
1. Extract requested parameters (vital signs/measurements to retrieve)
2. Extract cohort filters (conditions on the cohort source)
3. Identify temporal context (which time window to extract, if mentioned)

## Output JSON Format
{
    "intent": "data_retrieval",
    "requested_parameters": [
        {
            "term": "<original term from query>",
            "normalized": "<standard name>",
            "candidates": ["<possible param_key matches>"]
        }
    ],
    "cohort_filters": [
        {
            "column": "<column name>",
            "operator": "<LIKE|=|>|<|BETWEEN>",
            "value": "<filter value>"
        }
    ],
    "temporal_context": {
        "type": "<full_record|procedure_window|treatment_window|custom_window>",
        "description": "<description of time context>"
    },
    "reasoning": "<explanation of your understanding>"
}
"""


def build_schema_context(self) -> str:
    """기존 테이블에서 동적으로 스키마 컨텍스트 생성"""
    
    # PostgreSQL 기존 테이블에서 직접 쿼리
    cohort_info = self._load_cohort_sources()
    group_info = self._load_signal_groups()
    param_info = self._load_parameter_summary()
    rel_info = self._load_relationships()
    
    return f"""
### Cohort Sources (Filterable Tables)
{self._format_cohort_sources(cohort_info)}

### Signal Data Groups
{self._format_signal_groups(group_info)}

### Available Parameters by Category
{self._format_parameters(param_info)}

### Data Relationships
{self._format_relationships(rel_info)}
"""


def _format_cohort_sources(self, cohort_info: List[Dict]) -> str:
    """Cohort Source 정보를 LLM용 텍스트로 포맷"""
    lines = []
    for table in cohort_info:
        lines.append(f"**{table['file_name']}** (represents: {table['row_represents']})")
        lines.append(f"  - Identifier: {table['entity_identifier']}")
        lines.append(f"  - Filterable columns:")
        for col in table['filterable_columns']:
            if col['type'] == 'categorical':
                sample = ', '.join(col.get('sample_values', [])[:5])
                lines.append(f"    - {col['name']} (categorical): {sample}...")
            elif col['type'] == 'continuous':
                lines.append(f"    - {col['name']} (numeric): range {col.get('range', 'unknown')}")
            elif col['type'] == 'datetime':
                lines.append(f"    - {col['name']} (datetime)")
        if table.get('temporal_columns'):
            lines.append(f"  - Temporal columns: {', '.join(table['temporal_columns'])}")
    return '\n'.join(lines)


def _format_parameters(self, param_info: Dict) -> str:
    """파라미터 정보를 LLM용 텍스트로 포맷"""
    lines = []
    for category, info in param_info['categories'].items():
        lines.append(f"**{category}**")
        for param in info['parameters'][:10]:  # 카테고리당 최대 10개
            lines.append(f"  - {param['key']}: {param['name']} ({param.get('unit', 'N/A')})")
        if info.get('common_terms'):
            lines.append(f"  - Common terms: {', '.join(info['common_terms'])}")
    return '\n'.join(lines)
```

---

#### 생성된 컨텍스트 예시 (LLM 프롬프트에 주입)

```
### Cohort Sources (Filterable Tables)
**{cohort_file_name}** (represents: {row_represents})
  - Identifier: {entity_identifier}
  - Row count: {row_count}
  - Filterable columns:
    - {col_name} (categorical): {sample_values}...
    - {col_name} (numeric): range {min}-{max}
    - {col_name} (datetime)
  - Temporal columns: {temporal_columns}

### Signal Data Groups
**{group_name}** ({file_count} files)
  - Pattern: {file_pattern}
  - Represents: {row_represents}
  - Join key: {entity_identifier_key} → {cohort_file_name}.{join_column}

### Available Parameters by Category
**{category_name}**
  - {param_key}: {semantic_name} ({unit})
  - ...
  - Common terms: {related_terms}

### Data Relationships
- {source_table} → {target_table} (via {join_column}, {cardinality})
```

> **Note**: 위 템플릿의 모든 `{placeholder}`는 DB 메타데이터에서 동적으로 채워집니다.
> ExtractionAgent는 실제 데이터 파일에 접근하지 않습니다.

#### Output 스키마

```python
@dataclass
class QueryUnderstandingOutput:
    intent: str = "data_retrieval"
    
    requested_parameters: List[Dict]
    # [{
    #     "term": "심박수",           # 원문
    #     "normalized": "Heart Rate", # 정규화
    #     "candidates": ["HR", "Heart Rate"]  # 검색 키워드
    # }]
    
    cohort_filters: List[Dict]
    # [{
    #     "column": "diagnosis",
    #     "operator": "LIKE",
    #     "value": "%Stomach Cancer%"
    # }]
    
    temporal_context: Optional[Dict]
    # {
    #     "type": "procedure_window",
    #     "start_column": "procedure_start",
    #     "end_column": "procedure_end",
    #     "margin_seconds": 300
    # }
    
    reasoning: str
```

---

### 🔷 [200] ParameterResolverNode

**역할**: 요청된 파라미터를 실제 param_key에 매핑

| 항목 | 내용 |
|------|------|
| **Order** | 200 |
| **Type** | 🤖📏 Hybrid (Rule + LLM) |
| **Input** | `requested_parameters` |
| **Output** | `resolved_parameters`, `ambiguities` |
| **PostgreSQL** | ✅ `parameter`, `file_group` |
| **Neo4j** | ✅ `Parameter`, `ConceptCategory`, `FileGroup` |
| **LLM** | ✅ Resolution Mode 결정 |

---

#### 📊 PostgreSQL 접근

**사용 테이블:**

| 테이블 | 용도 | Repository |
|--------|------|------------|
| `parameter` | 파라미터 검색 (param_key, semantic_name, unit) | `ParameterRepository` |
| `file_group` | vital 그룹 정보 (group_id, group_name) | `FileGroupRepository` |

**사용 컬럼 (parameter):**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `param_id` | SERIAL | PK |
| `param_key` | VARCHAR(255) | 원본 파라미터명 (Solar8000/HR) |
| `semantic_name` | VARCHAR(255) | 의미론적 이름 (Heart Rate) |
| `unit` | VARCHAR(100) | 단위 (bpm) |
| `concept_category` | VARCHAR(255) | 카테고리 (Vital Signs) |
| `source_type` | VARCHAR(20) | 소스 타입 (group_common) |
| `group_id` | UUID | FK → file_group |
| `llm_confidence` | FLOAT | LLM 신뢰도 |

**SQL 쿼리:**

```sql
-- 1. Semantic Name으로 파라미터 검색
SELECT 
    p.param_id,
    p.param_key,
    p.semantic_name,
    p.unit,
    p.concept_category,
    p.group_id,
    fg.group_name
FROM parameter p
JOIN file_group fg ON p.group_id = fg.group_id
WHERE p.source_type = 'group_common'
  AND fg.group_id = $signal_group_id  -- schema_context에서 동적 조회
  AND (
      p.semantic_name ILIKE '%' || $term || '%'
      OR p.param_key ILIKE '%' || $term || '%'
  )
ORDER BY p.llm_confidence DESC NULLS LAST
LIMIT 20;

-- 2. ConceptCategory로 파라미터 검색
SELECT p.param_key, p.semantic_name, p.unit
FROM parameter p
WHERE p.concept_category = $category  -- 파라미터화
  AND p.source_type = 'group_common'
  AND p.group_id = $signal_group_id   -- schema_context에서 동적 조회
ORDER BY p.param_key;

-- 3. 전체 group_common 파라미터 목록 (프롬프트용)
SELECT DISTINCT p.param_key, p.semantic_name, p.unit, p.concept_category
FROM parameter p
WHERE p.source_type = 'group_common'
  AND p.group_id = $signal_group_id  -- schema_context에서 동적 조회
ORDER BY p.concept_category, p.param_key;
```

---

#### 🔗 Neo4j 접근

**사용 노드:**

| 노드 라벨 | 속성 | 설명 |
|-----------|------|------|
| `Parameter` | key, semantic_name, unit, is_identifier | 파라미터 노드 |
| `ConceptCategory` | name | 개념 카테고리 (Vital Signs 등) |
| `FileGroup` | group_id, name | 파일 그룹 |

**사용 관계:**

| 관계 | 설명 |
|------|------|
| `(:ConceptCategory)-[:CONTAINS]->(:Parameter)` | 카테고리가 파라미터 포함 |
| `(:FileGroup)-[:HAS_COMMON_PARAM]->(:Parameter)` | 그룹의 공통 파라미터 |

**Cypher 쿼리:**

```cypher
-- 1. Semantic Name으로 Parameter 검색
-- $signal_group_id는 schema_context에서 동적으로 조회
MATCH (fg:FileGroup {group_id: $signal_group_id})-[:HAS_COMMON_PARAM]->(p:Parameter)
WHERE toLower(p.semantic_name) CONTAINS toLower($term)
   OR toLower(p.key) CONTAINS toLower($term)
OPTIONAL MATCH (c:ConceptCategory)-[:CONTAINS]->(p)
RETURN 
    p.key as param_key,
    p.semantic_name as semantic_name,
    p.unit as unit,
    c.name as concept_category
LIMIT 20;

-- 2. ConceptCategory 기반 검색
-- $signal_group_id와 $category는 파라미터로 전달
MATCH (c:ConceptCategory {name: $category})-[:CONTAINS]->(p:Parameter)
MATCH (fg:FileGroup {group_id: $signal_group_id})-[:HAS_COMMON_PARAM]->(p)
RETURN p.key, p.semantic_name, p.unit
ORDER BY p.semantic_name;

-- 3. FileGroup의 모든 공통 파라미터
-- $signal_group_id는 schema_context에서 동적으로 조회
MATCH (fg:FileGroup {group_id: $signal_group_id})-[:HAS_COMMON_PARAM]->(p:Parameter)
OPTIONAL MATCH (c:ConceptCategory)-[:CONTAINS]->(p)
RETURN 
    p.key as param_key,
    p.semantic_name as semantic_name,
    p.unit as unit,
    c.name as concept_category
ORDER BY c.name, p.key;
```

---

#### 🤖 LLM 사용

#### Resolution Mode (LLM 결정)

```python
class ResolutionMode(Enum):
    ALL_SOURCES = "all_sources"      # 동일 개념의 모든 소스 (기본값)
    SPECIFIC = "specific"            # 특정 소스만
    NEEDS_CLARIFICATION = "clarify"  # 사용자 확인 필요
```

#### LLM Resolution 프롬프트

```python
RESOLUTION_PROMPT = """
User requested: "{term}" (normalized: {normalized})

Found multiple candidates in .vital files:
{candidates_json}

Determine the resolution mode:

1. "ALL" - Include all candidates
   Use when: Same vital sign from different monitoring devices
   Example: Solar8000/HR and BIS/HR both measure heart rate
   
2. "PICK" - Select specific candidate(s)
   Use when: User specified a particular device/source
   
3. "CLARIFY" - Need user clarification
   Use when: Candidates represent different concepts

Respond in JSON:
{
    "mode": "ALL" | "PICK" | "CLARIFY",
    "selected": [<param_keys if PICK>],
    "reason": "<brief explanation>",
    "question": "<clarification question if CLARIFY>"
}
"""
```

#### Output 스키마

```python
@dataclass
class ResolvedParameter:
    term: str                    # 원본 검색어
    param_keys: List[str]        # 매핑된 param_key들
    semantic_name: str           # 대표 이름
    unit: str                    # 단위
    concept_category: str        # 카테고리
    resolution_mode: str         # all_sources | specific
    confidence: float

@dataclass
class ParameterResolverOutput:
    resolved_parameters: List[ResolvedParameter]
    ambiguities: List[Dict]      # 사용자 확인 필요한 항목
    has_ambiguity: bool
```

---

### 🔷 [300] PlanBuilderNode

**역할**: Execution Plan JSON 조립 및 검증

| 항목 | 내용 |
|------|------|
| **Order** | 300 |
| **Type** | 📏 Rule-based |
| **Input** | 모든 이전 노드 결과 |
| **Output** | `execution_plan`, `validation`, `confidence` |
| **PostgreSQL** | ✅ `file_catalog`, `file_group`, `column_metadata` |
| **Neo4j** | ❌ 없음 |
| **LLM** | ❌ 없음 |

---

#### 📊 PostgreSQL 접근

**사용 테이블:**

| 테이블 | 용도 | Repository |
|--------|------|------------|
| `file_catalog` | Cohort/Vital 파일 경로, filename_values | `FileRepository` |
| `file_group` | Vital 그룹 정보, 파일 수 | `FileGroupRepository` |
| `column_metadata` | Cohort 컬럼 정보 (필터 검증용) | `ColumnRepository` |

**사용 컬럼 (file_catalog):**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `file_id` | UUID | PK |
| `file_path` | TEXT | 파일 전체 경로 |
| `file_name` | VARCHAR(255) | 파일명 |
| `group_id` | UUID | FK → file_group |
| `filename_values` | JSONB | 파일명에서 추출된 값 (caseid 등) |

**사용 컬럼 (file_group):**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `group_id` | UUID | PK |
| `group_name` | VARCHAR(255) | 그룹 이름 (DB에서 조회) |
| `file_count` | INTEGER | 그룹 내 파일 수 |
| `base_path` | TEXT | 그룹 기본 경로 |

**사용 컬럼 (column_metadata):**

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `col_id` | SERIAL | PK |
| `file_id` | UUID | FK → file_catalog |
| `original_name` | VARCHAR(255) | 컬럼명 |
| `column_type` | VARCHAR(50) | 컬럼 타입 (categorical, continuous, datetime) |
| `value_distribution` | JSONB | 값 분포 (unique_values 등) |

**SQL 쿼리:**

```sql
-- 1. Cohort 파일 조회 (schema_context["cohort_sources"][0]["file_id"] 사용)
SELECT file_id, file_path, file_name
FROM file_catalog
WHERE file_id = $cohort_file_id;

-- 2. Signal 그룹 정보 조회 (schema_context["signal_groups"][0]["group_id"] 사용)
SELECT group_id, group_name, file_count, grouping_criteria
FROM file_group
WHERE group_id = $signal_group_id;

-- 3. Signal 파일 샘플 경로 조회 (Validation용)
SELECT file_path
FROM file_catalog
WHERE group_id = $signal_group_id
ORDER BY file_name
LIMIT 10;

-- 4. Cohort 컬럼 정보 조회 (Filter 검증용)
SELECT cm.original_name, cm.column_type, cm.value_distribution
FROM column_metadata cm
WHERE cm.file_id = $cohort_file_id;

-- 5. Cohort 파일의 특정 컬럼 값 분포 확인
SELECT cm.value_distribution->'unique_values' as unique_values
FROM column_metadata cm
WHERE cm.file_id = $cohort_file_id
  AND cm.original_name = $filter_column;
```

---

#### 동적 토폴로지 (schema_context 기반)

```python
class DynamicTopology:
    """schema_context에서 동적으로 토폴로지 추출"""
    
    def __init__(self, schema_context: Dict[str, Any]):
        # Cohort Source (DB에서 조회된 첫 번째 항목)
        cohort = schema_context["cohort_sources"][0]
        self.cohort_file_id = cohort["file_id"]
        self.cohort_file_name = cohort["file_name"]
        self.cohort_identifier = cohort["entity_identifier"]
        self.filterable_columns = cohort.get("filterable_columns", [])
        self.temporal_columns = cohort.get("temporal_columns", [])
        
        # Signal Group (DB에서 조회된 첫 번째 항목)
        group = schema_context["signal_groups"][0]
        self.signal_group_id = group["group_id"]
        self.signal_group_name = group["group_name"]
        self.signal_file_pattern = group.get("file_pattern", "")
        self.signal_entity_key = group["entity_identifier_key"]
        
        # Join 정보 (DB에서 조회된 첫 번째 항목)
        rel = schema_context["relationships"][0]
        self.join_source_column = rel["source_column"]
        self.join_target_column = rel["target_column"]
        self.join_cardinality = rel["cardinality"]
    
    def get_temporal_window_columns(self, window_type: str) -> Optional[Tuple[str, str]]:
        """temporal_context에서 시작/종료 컬럼 추출 (DB 메타데이터 기반)"""
        # column_metadata에서 column_role='timestamp'인 컬럼들을 분석
        # 또는 컬럼명 패턴 매칭 (_start, _end 등)
        ...
```

#### Plan 조립 로직

```python
def build_plan(self, state: VitalExtractionState) -> Dict:
    # schema_context에서 동적으로 토폴로지 추출
    topology = DynamicTopology(state["schema_context"])
    
    return {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "agent": "VitalExtractionAgent",
        "original_query": state["user_query"],
        
        "execution_plan": {
            "cohort_source": {
                "type": "tabular_file",
                "file_id": topology.cohort_file_id,           # DB에서 동적 조회
                "file_name": topology.cohort_file_name,       # DB에서 동적 조회
                "file_path": self._get_file_path(topology.cohort_file_id),
                "reader": "pandas_csv",
                "filter_expression": self._build_filter_expression(state),
                "result_identifier": topology.cohort_identifier,
            },
            
            "signal_source": {
                "type": "file_group",
                "group_id": topology.signal_group_id,         # DB에서 동적 조회
                "group_name": topology.signal_group_name,     # DB에서 동적 조회
                "reader": "vitaldb_reader",
                "file_pattern": topology.signal_file_pattern,
                "file_count": self._get_group_file_count(topology.signal_group_id),
                "target_parameters": state["resolved_parameters"],
                "join_key": {
                    "source": topology.join_source_column,    # DB에서 동적 조회
                    "target": topology.signal_entity_key,     # DB에서 동적 조회
                },
                "temporal_alignment": self._build_temporal_alignment(state, topology),
            },
        },
        
        "validation": self._validate_plan(state),
    }
```

#### Temporal Alignment 빌드

```python
def _build_temporal_alignment(self, state: Dict) -> Optional[Dict]:
    """시간 동기화 설정 생성"""
    temporal = state.get("temporal_context")
    
    if not temporal:
        return None
    
    temporal_type = temporal.get("type")
    
    if temporal_type == "full_record":
        return None  # 전체 기록, 슬라이싱 불필요
    
    if temporal_type == "procedure_window":
        return {
            "type": "relative_window",
            "start_column": temporal.get("start_column", "procedure_start"),
            "end_column": temporal.get("end_column", "procedure_end"),
            "margin_seconds": temporal.get("margin_seconds", 0),
        }
    
    if temporal_type == "treatment_window":
        return {
            "type": "relative_window",
            "start_column": temporal.get("start_column", "treatment_start"),
            "end_column": temporal.get("end_column", "treatment_end"),
            "margin_seconds": temporal.get("margin_seconds", 0),
        }
    
    # custom_window
    return {
        "type": "custom",
        "start_column": temporal.get("start_column"),
        "end_column": temporal.get("end_column"),
        "margin_seconds": temporal.get("margin_seconds", 0),
    }
```

#### Validation 로직

```python
def _validate_plan(self, state: Dict) -> Dict:
    """Plan 검증"""
    warnings = []
    
    # 1. 파라미터 존재 확인
    if not state.get("resolved_parameters"):
        warnings.append({
            "type": "no_parameters",
            "severity": "high",
            "message": "No parameters resolved"
        })
    
    # 2. Cohort 파일 존재 확인
    cohort_path = self._get_cohort_file_path()
    if not os.path.exists(cohort_path):
        warnings.append({
            "type": "cohort_file_missing",
            "severity": "high",
            "message": f"Cohort file not found: {cohort_path}"
        })
    
    # 3. Vital 파일 샘플 확인 (10개)
    vital_paths = self._get_sample_vital_paths(10)
    missing = sum(1 for p in vital_paths if not os.path.exists(p))
    if missing > 0:
        warnings.append({
            "type": "vital_files_partial",
            "severity": "low",
            "message": f"Sample check: {missing}/10 vital files missing"
        })
    
    # Confidence 계산
    confidence = 1.0
    for w in warnings:
        if w["severity"] == "high":
            confidence -= 0.3
        elif w["severity"] == "medium":
            confidence -= 0.1
        else:
            confidence -= 0.05
    
    return {
        "warnings": warnings,
        "confidence": max(0.0, confidence),
        "validated_at": datetime.now().isoformat(),
    }
```

---

## 📊 VitalExtractionState 스키마

```python
from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator


class VitalExtractionState(TypedDict):
    """VitalExtractionAgent 워크플로우 상태"""
    
    # ═══════════════════════════════════════════════════════════════════
    # Input
    # ═══════════════════════════════════════════════════════════════════
    user_query: str
    
    # ═══════════════════════════════════════════════════════════════════
    # [100] QueryUnderstanding Output
    # ═══════════════════════════════════════════════════════════════════
    query_understanding_result: Optional[Dict[str, Any]]
    
    schema_context: Optional[Dict[str, Any]]
    # {
    #     "cohort_sources": [...],
    #     "signal_groups": [...],
    #     "parameters": {...},
    #     "relationships": [...],
    #     "context_text": "..."
    # }
    
    intent: str  # always "data_retrieval"
    
    requested_parameters: List[Dict[str, Any]]
    # [{
    #     "term": "심박수",
    #     "normalized": "Heart Rate",
    #     "candidates": ["HR", "Heart Rate"]
    # }]
    
    cohort_filters: List[Dict[str, Any]]
    # [{
    #     "column": "diagnosis",
    #     "operator": "LIKE",
    #     "value": "%Stomach Cancer%"
    # }]
    
    temporal_context: Optional[Dict[str, Any]]
    # {
    #     "type": "procedure_window",
    #     "start_column": "procedure_start",
    #     "end_column": "procedure_end"
    # }
    
    # ═══════════════════════════════════════════════════════════════════
    # [200] ParameterResolver Output
    # ═══════════════════════════════════════════════════════════════════
    parameter_resolver_result: Optional[Dict[str, Any]]
    
    resolved_parameters: List[Dict[str, Any]]
    # [{
    #     "term": "심박수",
    #     "param_keys": ["Solar8000/HR", "BIS/HR"],
    #     "semantic_name": "Heart Rate",
    #     "unit": "bpm",
    #     "resolution_mode": "all_sources"
    # }]
    
    ambiguities: List[Dict[str, Any]]
    
    # ═══════════════════════════════════════════════════════════════════
    # [300] PlanBuilder Output
    # ═══════════════════════════════════════════════════════════════════
    plan_builder_result: Optional[Dict[str, Any]]
    
    execution_plan: Optional[Dict[str, Any]]  # 최종 Plan JSON
    
    validation: Optional[Dict[str, Any]]
    # {
    #     "warnings": [],
    #     "confidence": 0.95,
    #     "validated_at": "..."
    # }
    
    # ═══════════════════════════════════════════════════════════════════
    # Human-in-the-Loop
    # ═══════════════════════════════════════════════════════════════════
    needs_human_review: bool
    human_question: Optional[str]
    human_feedback: Optional[str]
    
    # ═══════════════════════════════════════════════════════════════════
    # System
    # ═══════════════════════════════════════════════════════════════════
    logs: Annotated[List[str], operator.add]
    error_message: Optional[str]
```

---

## 📄 Execution Plan JSON 스키마

```json
{
    "version": "1.0",
    "generated_at": "2026-01-06T10:30:00.000Z",
    "agent": "VitalExtractionAgent",
    "original_query": "<user_query>",
    
    "execution_plan": {
        "cohort_source": {
            "type": "tabular_file",
            "file_id": "<cohort_file_id>",           // schema_context에서 동적 조회
            "file_name": "<cohort_file_name>",       // schema_context에서 동적 조회
            "file_path": "<cohort_file_path>",       // file_catalog에서 조회
            "reader": "pandas_csv",
            "filter_expression": "<filter_expr>",    // 쿼리 분석 결과
            "result_identifier": "<entity_id>",      // table_entities에서 조회
            "estimated_rows": null                   // 실행 전에는 알 수 없음
        },
        
        "signal_source": {
            "type": "file_group",
            "group_id": "<group_id>",                // schema_context에서 동적 조회
            "group_name": "<group_name>",            // schema_context에서 동적 조회
            "reader": "vitaldb_reader",
            "file_pattern": "<pattern>",             // file_group.grouping_criteria에서 조회
            "file_count": 0,                         // file_group.file_count에서 조회
            "target_parameters": [
                {
                    "param_key": "<param_key>",      // ParameterResolver 결과
                    "semantic_name": "<name>",
                    "unit": "<unit>"
                }
            ],
            "join_key": {
                "source": "<join_column>",           // table_relationships에서 조회
                "target": "<entity_key>"             // file_group.entity_identifier_key
            },
            "temporal_alignment": {
                "type": "<window_type>",             // 쿼리 분석 결과
                "start_column": "<start_col>",       // temporal_columns에서 매핑
                "end_column": "<end_col>",
                "margin_seconds": 0
            }
        }
    },
    
    "validation": {
        "warnings": [],
        "confidence": 0.95,
        "validated_at": "<timestamp>"
    }
}

// Note: 모든 <placeholder>는 DB 메타데이터에서 동적으로 채워집니다.
```

---

## 🎯 사용 예시

### 예시 1: 기본 데이터 추출

**쿼리**: "위암 환자의 심박수 데이터"

```
[100] QueryUnderstanding
├─ Schema Context: 로드됨 (cohort_sources, signal_groups, parameters, relationships)
├─ Intent: data_retrieval
├─ Parameters: ["심박수"]
├─ Filters: [{column: "diagnosis", op: "LIKE", value: "%Stomach Cancer%"}]
└─ Temporal: null (전체 기록)

[200] ParameterResolver
├─ "심박수" → [Solar8000/HR, BIS/HR, Philips/HR] (DB에서 검색)
├─ Resolution Mode: ALL_SOURCES
└─ Reason: "Same vital sign from different devices"

[300] PlanBuilder
├─ Cohort: {cohort_file_name} (diagnosis LIKE '%Stomach Cancer%')  ← DB에서 동적 조회
├─ Target: {signal_group_name} (HR parameters)  ← DB에서 동적 조회
├─ Temporal Alignment: null
└─ Confidence: 0.95
```

### 예시 2: 수술 중 구간 추출

**쿼리**: "당뇨 환자의 시술 중 혈압"

```
[100] QueryUnderstanding
├─ Intent: data_retrieval
├─ Parameters: ["혈압"]
├─ Filters: [{column: "diagnosis", op: "LIKE", value: "%Diabetes%"}]
└─ Temporal: {type: "procedure_window"}

[200] ParameterResolver
├─ "혈압" → [Solar8000/NIBP_SBP, Solar8000/NIBP_DBP, Solar8000/ART_SBP, ...]
├─ Resolution Mode: ALL_SOURCES
└─ Reason: "Including both NIBP and invasive arterial BP"

[300] PlanBuilder
├─ Cohort: {cohort_file_name} (diagnosis LIKE '%Diabetes%')  ← DB에서 동적 조회
├─ Target: {signal_group_name} (BP parameters)  ← DB에서 동적 조회
├─ Temporal Alignment: {type: "relative_window", start: "{start_col}", end: "{end_col}"}
└─ Confidence: 0.92
```

### 예시 3: 특정 Identifier

**쿼리**: "{entity_identifier} 1234의 BIS 데이터"

```
[100] QueryUnderstanding
├─ Schema Context: 로드됨
├─ Intent: data_retrieval
├─ Parameters: ["BIS"]
├─ Filters: [{column: "{entity_identifier}", op: "=", value: 1234}]  ← DB에서 동적 파악
└─ Temporal: null

[200] ParameterResolver
├─ "BIS" → [BIS/BIS] (DB에서 검색)
├─ Resolution Mode: SPECIFIC
└─ Reason: "BIS index is a specific parameter"

[300] PlanBuilder
├─ Cohort: {cohort_file_name} ({entity_identifier} = 1234)  ← 모두 DB에서 동적 조회
├─ Target: {matched_signal_file}
├─ Temporal Alignment: null
└─ Confidence: 0.98
```

---

## 📁 파일 구조

```
ExtractionAgent/
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── graph.py                    # LangGraph 워크플로우 (3-node)
│   │   ├── state.py                    # VitalExtractionState
│   │   ├── registry.py                 # NodeRegistry
│   │   ├── config.py                   # VitalTopology, Config 클래스들
│   │   ├── base/
│   │   │   ├── __init__.py
│   │   │   └── node.py                 # BaseNode
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── enums.py                # Intent, EntityType, TemporalType
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── query_understanding/
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── parameter_resolver/
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       └── plan_builder/
│   │           ├── __init__.py
│   │           └── node.py
│   │
│   └── config.py
│
├── tests/
│   ├── test_query_understanding.py
│   ├── test_parameter_resolver.py
│   ├── test_plan_builder.py
│   └── test_full_pipeline.py
│
├── examples/
│   └── basic_extraction.py
│
├── ARCHITECTURE_VitalExtraction.md     # 이 문서
├── requirements.txt
└── README.md
```

---

## ⚙️ 설정

```python
# src/agents/config.py

# NOTE: 토폴로지 정보는 하드코딩하지 않습니다.
# 모든 정보는 schema_context에서 동적으로 로드됩니다.

class QueryUnderstandingConfig:
    MAX_PARAMETERS = 10
    CONFIDENCE_THRESHOLD = 0.7


class ParameterResolverConfig:
    MAX_CANDIDATES = 20
    AMBIGUITY_THRESHOLD = 0.5


class PlanBuilderConfig:
    FILE_VALIDATION_SAMPLE_SIZE = 10
    CONFIDENCE_THRESHOLD_FOR_WARNING = 0.7


# DynamicTopology는 schema_context에서 런타임에 생성됩니다.
# 아래는 DynamicTopology 클래스의 구조만 정의합니다.

class DynamicTopology:
    """
    schema_context에서 동적으로 토폴로지 추출.
    
    하드코딩된 파일명/컬럼명 없음.
    모든 정보는 IndexingAgent가 생성한 DB 메타데이터에서 조회.
    """
    
    def __init__(self, schema_context: Dict[str, Any]):
        # Cohort Source (DB에서 조회된 정보)
        self.cohort_file_id: str
        self.cohort_file_name: str
        self.cohort_identifier: str
        self.filterable_columns: List[Dict]
        self.temporal_columns: List[str]
        
        # Signal Group (DB에서 조회된 정보)
        self.signal_group_id: str
        self.signal_group_name: str
        self.signal_file_pattern: str
        self.signal_entity_key: str
        
        # Join 정보 (DB에서 조회된 정보)
        self.join_source_column: str
        self.join_target_column: str
        self.join_cardinality: str
```

---

## 🔗 shared 패키지 의존성

### 전체 의존성 맵

```python
# VitalExtractionAgent에서 사용하는 shared 컴포넌트

# === Database Connection ===
from shared.database import get_db_manager
from shared.database import get_neo4j_connection

# === Repositories (Read-Only) ===
from shared.database.repositories import (
    ParameterRepository,    # [200] group_common 파라미터 검색
    FileRepository,         # [300] file_path 조회
    FileGroupRepository,    # [200], [300] vital 그룹 정보
    ColumnRepository,       # [300] 컬럼 메타데이터
)

# === LLM ===
from shared.llm import get_llm_client

# === Models/Enums ===
from shared.models import (
    SourceType,           # group_common
    ConceptCategory,      # Vital Signs, etc.
    ColumnRole,           # identifier, parameter_name, etc.
)

# === Config ===
from shared.config import (
    DatabaseConfig,       # PostgreSQL 설정
    Neo4jConfig,          # Neo4j 설정
    LLMConfig,            # LLM 설정
)
```

### 노드별 Repository 사용

#### [100] QueryUnderstandingNode

```python
# 사용 Repository: FileRepository, FileGroupRepository, ParameterRepository, 
#                 EntityRepository, ColumnRepository
# Neo4j: Parameter, ConceptCategory (Optional 보강)
# LLM: 쿼리 분석

from shared.database import get_db_manager, get_neo4j_connection
from shared.database.repositories import (
    FileRepository, FileGroupRepository, ParameterRepository,
    EntityRepository, ColumnRepository
)
from shared.llm import get_llm_client

class SchemaContextBuilder:
    """DB 메타데이터에서 LLM용 컨텍스트 생성"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self.file_repo = FileRepository(db_manager)
        self.group_repo = FileGroupRepository(db_manager)
        self.param_repo = ParameterRepository(db_manager)
        self.entity_repo = EntityRepository(db_manager)
        self.col_repo = ColumnRepository(db_manager)
    
    def build_context(self) -> Dict[str, Any]:
        """전체 스키마 컨텍스트 수집"""
        cohort_sources = self._get_cohort_sources()
        signal_groups = self._get_signal_groups()
        parameters = self._get_parameter_summary()
        relationships = self._get_relationships()
        
        return {
            "cohort_sources": cohort_sources,
            "signal_groups": signal_groups,
            "parameters": parameters,
            "relationships": relationships,
            "context_text": self._build_context_text(
                cohort_sources, signal_groups, parameters, relationships
            )
        }
    
    def _get_cohort_sources(self) -> List[Dict]:
        """Cohort Source 후보 (is_metadata=false, group_id IS NULL)"""
        # table_entities와 조인하여 row_represents, entity_identifier 포함
        ...
    
    def _build_context_text(self, cohort, groups, params, rels) -> str:
        """LLM 프롬프트용 텍스트 포맷팅"""
        lines = ["### Cohort Sources (Filterable Tables)"]
        for table in cohort:
            lines.append(f"**{table['file_name']}** (represents: {table['row_represents']})")
            lines.append(f"  - Identifier: {table['entity_identifier']}")
            # ... 컬럼 정보
        # ... signal_groups, params, relationships
        return '\n'.join(lines)


class QueryUnderstandingNode(BaseNode):
    def execute(self, state):
        db = get_db_manager()
        llm = get_llm_client()
        
        # Step 1: 동적 컨텍스트 로딩
        context_builder = SchemaContextBuilder(db)
        schema_context = context_builder.build_context()
        
        # Step 2: LLM 호출 (동적 컨텍스트 포함)
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            schema_context=schema_context["context_text"]
        )
        response = llm.ask_json(prompt + f"\n\nUser Query: {state['user_query']}")
        
        return {
            "schema_context": schema_context,
            "intent": response["intent"],
            "requested_parameters": response["requested_parameters"],
            "cohort_filters": response["cohort_filters"],
            "temporal_context": response.get("temporal_context"),
        }
```

#### [200] ParameterResolverNode

```python
# 사용 Repository: ParameterRepository, FileGroupRepository
# Neo4j: Parameter, ConceptCategory 노드 검색

from shared.database import get_db_manager, get_neo4j_connection
from shared.database.repositories import ParameterRepository, FileGroupRepository
from shared.llm import get_llm_client

class ParameterResolverNode(BaseNode):
    def execute(self, state):
        db = get_db_manager()
        neo4j = get_neo4j_connection()
        llm = get_llm_client()
        
        param_repo = ParameterRepository(db)
        schema_context = state["schema_context"]
        
        # schema_context에서 signal_group_id 추출 (동적)
        signal_group_id = schema_context["signal_groups"][0]["group_id"]
        
        # PostgreSQL 검색 (group_id로 파라미터화)
        candidates = param_repo.search_by_semantic_name(
            term, 
            group_id=signal_group_id  # 하드코딩 X, DB에서 동적 조회
        )
        
        # Neo4j 검색 (보조) - group_id로 파라미터화
        neo4j_results = neo4j.execute_query("""
            MATCH (fg:FileGroup {group_id: $group_id})-[:HAS_COMMON_PARAM]->(p:Parameter)
            WHERE toLower(p.semantic_name) CONTAINS toLower($term)
            RETURN p.key, p.semantic_name, p.unit
        """, {"group_id": signal_group_id, "term": term})
        
        # LLM으로 Resolution Mode 결정
        resolution = llm.ask_json(resolution_prompt)
        ...
```

#### [300] PlanBuilderNode

```python
# 사용 Repository: FileRepository, FileGroupRepository, ColumnRepository
# Neo4j: 없음
# LLM: 없음
# 참조: state["schema_context"]에서 토폴로지 정보 사용

from shared.database import get_db_manager
from shared.database.repositories import FileRepository, FileGroupRepository, ColumnRepository

class PlanBuilderNode(BaseNode):
    def execute(self, state):
        db = get_db_manager()
        schema_context = state["schema_context"]
        
        file_repo = FileRepository(db)
        group_repo = FileGroupRepository(db)
        col_repo = ColumnRepository(db)
        
        # schema_context에서 토폴로지 정보 추출 (하드코딩 X)
        cohort_source = schema_context["cohort_sources"][0]  # 첫 번째 Cohort Source
        signal_group = schema_context["signal_groups"][0]    # 첫 번째 Signal Group
        relationship = schema_context["relationships"][0]    # Join 정보
        
        # Cohort 파일 조회 (동적)
        cohort_file = file_repo.get_file_by_id(cohort_source["file_id"])
        
        # Signal 그룹 정보 (동적)
        group = group_repo.get_group_by_id(signal_group["group_id"])
        
        # Join Key 추출 (동적)
        join_key = relationship["source_column"]  # e.g., "caseid"
        
        # 샘플 파일 경로 (Validation)
        sample_files = file_repo.get_files_by_group(group["group_id"], limit=10)
        
        # 컬럼 정보 (Filter 검증)
        columns = col_repo.get_columns_by_file(cohort_file["file_id"])
        
        # Execution Plan 생성
        plan = {
            "cohort_source": {
                "file_name": cohort_file["file_name"],
                "file_path": cohort_file["file_path"],
                "entity_identifier": cohort_source["entity_identifier"],
                "filter_expression": self._build_filter_expr(state["cohort_filters"])
            },
            "signal_group": {
                "group_name": group["group_name"],
                "file_pattern": group["grouping_criteria"].get("pattern"),
                "join_key": join_key
            },
            "parameters": state["resolved_parameters"],
            "temporal_alignment": state.get("temporal_context")
        }
        ...
```

### Repository 메서드 참조

#### ParameterRepository (Read-Only 메서드)

| 메서드 | 용도 | 노드 |
|--------|------|------|
| `get_parameters_by_category(concept_category)` | 카테고리별 파라미터 조회 | [100], [200] |
| `get_group_common_params_for_neo4j()` | 그룹 공통 파라미터 목록 | [100], [200] |
| `get_all_parameters_for_ontology()` | 전체 파라미터 (중복 제거) | [100], [200] |
| `search_by_semantic_name(term, group_name)` | 시맨틱 이름으로 검색 | [200] |

#### FileRepository (Read-Only 메서드)

| 메서드 | 용도 | 노드 |
|--------|------|------|
| `get_file_by_id(file_id)` | ID로 파일 조회 | [100], [300] |
| `get_file_by_path(file_path)` | 경로로 파일 조회 | [300] |
| `get_files_by_group(group_id, limit)` | 그룹 내 파일 목록 | [300] |
| `get_data_files_with_details()` | 데이터 파일 상세 정보 | [100], [300] |
| `get_cohort_source_candidates()` | Cohort Source 후보 조회 | [100] (신규) |

#### FileGroupRepository (Read-Only 메서드)

| 메서드 | 용도 | 노드 |
|--------|------|------|
| `get_confirmed_groups()` | 확정된 그룹 목록 | [100] |
| `get_group_by_id(group_id)` | ID로 그룹 조회 | [300] |
| `get_group_by_name(group_name)` | 이름으로 그룹 조회 | [200], [300] |
| `get_group_file_count(group_id)` | 그룹 내 파일 수 | [300] |

#### EntityRepository (Read-Only 메서드)

| 메서드 | 용도 | 노드 |
|--------|------|------|
| `get_entity_by_file(file_id)` | 파일의 Entity 정보 | [100] |
| `get_relationships()` | 테이블 간 관계 목록 | [100] |
| `get_relationships_for_file(file_id)` | 특정 파일의 관계 | [100], [300] |

#### ColumnRepository (Read-Only 메서드)

| 메서드 | 용도 | 노드 |
|--------|------|------|
| `get_columns_by_file(file_id)` | 파일의 컬럼 목록 | [100], [300] |
| `get_filterable_columns(file_id)` | 필터 가능한 컬럼 | [100] (신규) |
| `get_column_value_distribution(file_id, column_name)` | 컬럼 값 분포 | [100], [300] |

---

## 📅 구현 일정

| Phase | 기간 | 작업 내용 |
|-------|------|----------|
| 0 | Day 1 | 기본 인프라 (state, base, registry, config) |
| 1 | Day 1-2 | **SchemaContextBuilder** 클래스 구현 |
| 2 | Day 2-3 | [100] QueryUnderstandingNode (동적 컨텍스트 + LLM) |
| 3 | Day 3-4 | [200] ParameterResolverNode |
| 4 | Day 4-5 | [300] PlanBuilderNode |
| 5 | Day 5-6 | 통합 테스트 및 예제 |

**총 예상 기간: 6일**

---

## ExtractionAgent v2 대비 차이점

| 항목 | ExtractionAgent v2 | VitalExtractionAgent |
|------|-------------------|---------------------|
| **노드 수** | 6개 | 3개 |
| **토폴로지** | 동적 탐색 | 메타데이터 기반 |
| **Target Source** | 모든 파일 타입 | Signal 데이터 (FileGroup) |
| **Join Path** | Neo4j/PostgreSQL 탐색 | table_relationships 조회 |
| **Cohort Analysis** | 별도 노드 | PlanBuilder에 통합 |
| **Validation** | 별도 노드 | PlanBuilder에 통합 |
| **스키마 정보** | 하드코딩 | DB 메타데이터 동적 로드 |
| **IndexingAgent 확장** | 필요 | ❌ 불필요 (기존 테이블 사용) |
| **복잡도** | 높음 | 낮음 |
| **구현 기간** | ~14일 | ~6일 |

---

## 🔧 IndexingAgent 메타데이터 의존성

VitalExtractionAgent는 **실제 데이터 파일에 접근하지 않고**, IndexingAgent가 이미 생성한 메타데이터만 사용합니다.

### IndexingAgent가 생성하는 메타데이터 (기존 - 수정 불필요)

| 테이블 | 내용 | VitalExtractionAgent 활용 |
|--------|------|---------------------------|
| `file_catalog` | 파일 기본 정보 | ✅ Cohort Source 식별 |
| `file_group` | 파일 그룹 정보 | ✅ Signal Group 식별 |
| `column_metadata` | 컬럼 상세 정보 | ✅ 필터 가능 컬럼 파악 |
| `table_entities` | 테이블이 나타내는 Entity | ✅ row_represents, entity_identifier |
| `table_relationships` | 테이블 간 관계 | ✅ Join 정보 |
| `parameter` | 파라미터 정보 | ✅ 검색 및 매핑 |
| Neo4j `Parameter` | 파라미터 노드 | ✅ 시맨틱 검색 |
| Neo4j `ConceptCategory` | 카테고리 노드 | ✅ 카테고리별 검색 |

### SchemaContextBuilder 구현

기존 테이블에서 직접 쿼리하여 LLM 컨텍스트를 생성합니다.

```python
class SchemaContextBuilder:
    """기존 테이블에서 스키마 컨텍스트 수집 (IndexingAgent 수정 불필요)"""
    
    def __init__(self, db_manager):
        self.db = db_manager
    
    def build_context(self) -> Dict[str, Any]:
        """전체 스키마 컨텍스트 수집"""
        cohort_sources = self._get_cohort_sources()
        signal_groups = self._get_signal_groups()
        parameters = self._get_parameter_summary()
        relationships = self._get_relationships()
        
        return {
            "cohort_sources": cohort_sources,
            "signal_groups": signal_groups,
            "parameters": parameters,
            "relationships": relationships,
            "context_text": self._build_context_text(
                cohort_sources, signal_groups, parameters, relationships
            ),
        }
    
    def _get_cohort_sources(self) -> List[Dict]:
        """Cohort Source 후보 (is_metadata=false, group_id IS NULL)"""
        return self.db.execute_query("""
            SELECT 
                fc.file_id, fc.file_name, fc.file_path,
                te.row_represents, te.entity_identifier,
                fc.file_metadata->'row_count' as row_count
            FROM file_catalog fc
            JOIN table_entities te ON fc.file_id = te.file_id
            WHERE fc.is_metadata = false AND fc.group_id IS NULL
        """)
    
    def _get_signal_groups(self) -> List[Dict]:
        """Confirmed Signal Group"""
        return self.db.execute_query("""
            SELECT group_id, group_name, file_count, 
                   row_represents, entity_identifier_key,
                   grouping_criteria, related_files
            FROM file_group WHERE status = 'confirmed'
        """)
    
    def _get_filterable_columns(self, file_id: str) -> List[Dict]:
        """필터 가능한 컬럼 정보"""
        return self.db.execute_query("""
            SELECT 
                original_name, column_type, column_role,
                value_distribution->'unique_count' as unique_count,
                value_distribution->'unique_values' as sample_values
            FROM column_metadata
            WHERE file_id = %s
              AND column_role IN ('identifier', 'attribute', 'timestamp')
        """, [file_id])
    
    def _get_parameter_summary(self) -> Dict[str, List]:
        """카테고리별 파라미터 요약"""
        rows = self.db.execute_query("""
            SELECT 
                concept_category,
                array_agg(DISTINCT param_key ORDER BY param_key) as param_keys,
                array_agg(DISTINCT semantic_name) as semantic_names,
                array_agg(DISTINCT unit) FILTER (WHERE unit IS NOT NULL) as units
            FROM parameter
            WHERE source_type = 'group_common'
              AND concept_category IS NOT NULL
            GROUP BY concept_category
        """)
        return {row['concept_category']: row for row in rows}
    
    def _get_relationships(self) -> List[Dict]:
        """테이블 간 관계"""
        return self.db.execute_query("""
            SELECT 
                sf.file_name as source_table,
                COALESCE(tf.file_name, fg.group_name) as target_table,
                tr.source_column, tr.target_column, tr.cardinality
            FROM table_relationships tr
            JOIN file_catalog sf ON tr.source_file_id = sf.file_id
            LEFT JOIN file_catalog tf ON tr.target_file_id = tf.file_id
            LEFT JOIN file_group fg ON tr.target_group_id = fg.group_id
        """)
    
    def _build_context_text(self, cohort, groups, params, rels) -> str:
        """LLM 프롬프트용 텍스트 포맷팅"""
        lines = []
        
        # Cohort Sources
        lines.append("### Cohort Sources (Filterable Tables)")
        for table in cohort:
            lines.append(f"**{table['file_name']}** (represents: {table['row_represents']})")
            lines.append(f"  - Identifier: {table['entity_identifier']}")
            lines.append(f"  - Row count: {table.get('row_count', 'unknown')}")
            
            # 필터 가능 컬럼 추가
            filterable = self._get_filterable_columns(table['file_id'])
            if filterable:
                lines.append(f"  - Filterable columns:")
                for col in filterable:
                    col_info = f"    - {col['original_name']} ({col['column_type']})"
                    if col.get('sample_values'):
                        samples = col['sample_values'][:5] if isinstance(col['sample_values'], list) else []
                        if samples:
                            col_info += f": {', '.join(str(s) for s in samples)}..."
                    lines.append(col_info)
        
        # Signal Groups
        lines.append("\n### Signal Data Groups")
        for g in groups:
            pattern = g.get('grouping_criteria', {}).get('pattern', 'N/A')
            lines.append(f"**{g['group_name']}** ({g['file_count']} files)")
            lines.append(f"  - Pattern: {pattern}")
            lines.append(f"  - Represents: {g.get('row_represents', 'N/A')}")
            lines.append(f"  - Entity key: {g.get('entity_identifier_key', 'N/A')}")
        
        # Parameters
        lines.append("\n### Available Parameters by Category")
        for category, info in params.items():
            lines.append(f"**{category}**")
            for key, name in zip(info['param_keys'][:10], info['semantic_names'][:10]):
                lines.append(f"  - {key}: {name}")
        
        # Relationships
        lines.append("\n### Data Relationships")
        for rel in rels:
            lines.append(f"- {rel['source_table']} → {rel['target_table']} (via {rel['source_column']}, {rel['cardinality']})")
        
        return '\n'.join(lines)
```

---

## 📋 구현 체크리스트

### Phase 0: 기본 인프라

- [ ] `VitalExtractionState` TypedDict 정의
- [ ] `BaseNode` 클래스 (IndexingAgent에서 복사/수정)
- [ ] `NodeRegistry` (IndexingAgent에서 복사)
- [ ] `config.py` (LLM, DB 설정)

### Phase 1: SchemaContextBuilder

- [ ] `SchemaContextBuilder` 클래스
  - [ ] `_get_cohort_sources()`: Cohort Source 식별
  - [ ] `_get_signal_groups()`: Signal Group 정보
  - [ ] `_get_filterable_columns()`: 필터 가능 컬럼
  - [ ] `_get_parameter_summary()`: 카테고리별 파라미터
  - [ ] `_get_relationships()`: 테이블 관계
  - [ ] `_build_context_text()`: LLM 프롬프트용 텍스트

### Phase 2: Nodes

- [ ] **[100] QueryUnderstandingNode**
  - [ ] SchemaContextBuilder 통합
  - [ ] LLM 프롬프트 템플릿 (동적 컨텍스트 주입)
  - [ ] Output 파싱

- [ ] **[200] ParameterResolverNode**
  - [ ] PostgreSQL parameter 검색
  - [ ] Neo4j 보조 검색 (Optional)
  - [ ] LLM Resolution Mode 결정

- [ ] **[300] PlanBuilderNode**
  - [ ] schema_context에서 토폴로지 정보 사용
  - [ ] Execution Plan JSON 생성
  - [ ] Validation (샘플 파일 확인)

### Phase 3: 통합

- [ ] LangGraph 워크플로우 빌드
- [ ] End-to-end 테스트
- [ ] 예제 쿼리 테스트

---

## 🚀 Future Enhancement (Optional)

성능 최적화가 필요한 경우, 다음을 고려할 수 있습니다:

1. **캐싱**: SchemaContextBuilder 결과를 메모리 캐시 (TTL 기반)
2. **Precomputed Context**: IndexingAgent에 schema_context 테이블 추가하여 사전 계산된 컨텍스트 저장
3. **Incremental Update**: 메타데이터 변경 시 컨텍스트 증분 업데이트

