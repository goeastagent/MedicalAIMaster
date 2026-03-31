# IndexingAgent 책임 및 개선 로드맵

> **문서 목적:** IndexingAgent의 현재 책임 범위를 정의하고, 전체 시스템 문서에서 도출된 미구현 기능들을 우선순위별로 정리한 공식 TODO 문서  
> **기준일:** 2026-03-31  
> **참고 문서:** `FUTURE_WORK.md`, `EMBEDDING_PARAMETER_SEARCH.md`, `ONTOLOGY_KNOWLEDGE_EXTENSION.md`, `TEMPORAL_COLUMN_ARCHITECTURE.md`, `VITALAGENT_TODO.md`, `architecture_evolution.html`  
> **연계 문서:** [`ExtractionAgent_ROADMAP.md`](./ExtractionAgent_ROADMAP.md) — 이 문서의 I-XX 항목은 해당 문서의 E-XX 항목과 의존관계에 있음

---

## 1. IndexingAgent의 핵심 책임 (현재)

IndexingAgent는 VitalAgent 전체 파이프라인의 **"지식 공장"** 이다.  
분석 시점에 어떤 데이터를 다루는지 ExtractionAgent가 알 수 있으려면, IndexingAgent가 미리 충분한 메타데이터를 구축해야 한다.

**핵심 철학: "Rule Prepares, LLM Decides"**  
규칙 기반 로직이 데이터를 전처리하고 후보를 추출하면, LLM이 최종 판단(의미 해석, 관계 추론)을 내린다.

### 1.1 현재 파이프라인 (3 Phase, 9 Nodes)

```
입력: 의료 데이터 디렉토리 (CSV, .vital, Signal Files)
                    │
                    ▼
        ┌───────────────────────────────────────┐
        │  PHASE 1: 메타데이터 수집 (Rule-based) │
        │                                       │
        │  [100] directory_catalog              │
        │         디렉토리 구조 스캔             │
        │  [200] file_catalog                   │
        │         파일별 컬럼/타입/통계          │
        │  [250] file_grouping_prep             │
        │         그룹 후보 식별                 │
        │  [300] schema_aggregation             │
        │         LLM 배치 입력 준비             │
        └───────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────────────┐
        │  PHASE 2: 의미 분석 (LLM-based)       │
        │                                       │
        │  [350] file_grouping                  │
        │         동일 스키마 파일 그룹화        │
        │  [400] file_classification            │
        │         metadata vs data 분류         │
        │  [420] column_classification          │
        │         컬럼 역할 분류 + parameter 생성│
        │  [500] metadata_semantic              │
        │         data_dictionary 추출          │
        │  [600] parameter_semantic             │
        │         semantic_name, unit,          │
        │         concept_category 추론         │
        │  [700] directory_pattern              │
        │         파일명 패턴 분석              │
        └───────────────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────────────┐
        │  PHASE 3: 관계 추론 (LLM + Neo4j)     │
        │                                       │
        │  [800] entity_identification          │
        │         Entity 정의 (row_represents)  │
        │  [900] relationship_inference         │
        │         테이블 간 FK 관계 추론         │
        └───────────────────────────────────────┘
                    │
                    ▼
출력: PostgreSQL (12개 테이블) + Neo4j (온톨로지)
```

### 1.2 현재 출력 (PostgreSQL 테이블)

| 테이블 | 주요 컬럼 | 역할 |
|--------|----------|------|
| `directory_catalog` | dir_path, file_count, filename_pattern | 디렉토리 메타데이터 |
| `file_group` | group_name, row_represents, entity_identifier_key | 파일 그룹 정의 |
| `file_catalog` | file_path, processor_type, is_metadata | 파일 메타데이터 |
| `column_metadata` | original_name, column_role, data_type | 컬럼 분류 |
| `parameter` | param_key, semantic_name, unit, concept_category | **핵심: 파라미터 정보** |
| `data_dictionary` | parameter_key, parameter_desc, parameter_unit | 파라미터 정의 사전 |
| `table_entities` | row_represents, entity_identifier_key | Entity 정의 |
| `table_relationships` | source_table, target_table, join_key | FK 관계 |

### 1.3 현재 출력 (Neo4j 온톨로지)

```
FileGroup ──CONTAINS_FILE──▶ RowEntity ──HAS_COLUMN──▶ Parameter
                                                             │
                                                        CONTAINS
                                                             │
                                                             ▼
                                                     ConceptCategory
                                                             │
                                                      HAS_SUBCATEGORY
                                                             │
                                                             ▼
                                                        SubCategory

Parameter ──MAPS_TO──▶ MedicalTerm
Parameter ──DERIVED_FROM──▶ Parameter
Parameter ──RELATED_TO──▶ Parameter
```

---

## 2. 미구현 기능 목록 (TODO)

> **왜 이것들이 IndexingAgent의 책임인가?**  
> 아래 기능들은 모두 "ExtractionAgent가 런타임에 VitalDB 전용 규칙으로 추론하던 것들"을 인덱싱 시점에 데이터로부터 자동 계산해 저장하는 것이다. IndexingAgent가 한 번 계산하면, ExtractionAgent는 어느 데이터셋에서도 동일 코드로 작동한다.

---

### [P0] I-01: Parameter Embedding 계산 및 저장

**출처:** `EMBEDDING_PARAMETER_SEARCH.md` (설계 완료)  
**연관 TODO:** `T-02`, `T-03`, `T-05`, `T-08`, `T-09`, `T-10`  
**ExtractionAgent 대응:** [`E-01` Vector Similarity Search](./ExtractionAgent_ROADMAP.md#p0-e-01-vector-similarity-search-ilike-교체) — I-01 없이 E-01 불가

**문제:**  
현재 ParameterResolver는 ILIKE 키워드 검색에만 의존한다. 동의어, 하이픈, 임상 개념 표현 불일치로 매칭 실패가 발생한다.

```
"effect site concentration" ≠ "Effect-site Concentration" → ILIKE 0건
"amount of propofol"        ≠ "Propofol Infused Volume"   → ILIKE 0건
"consciousness level"       ≠ "BIS (Bispectral Index)"    → ILIKE 0건
```

**해결책: [600] parameter_semantic 노드에서 임베딩 동시 계산**

```python
# [600] parameter_semantic 노드 출력에 추가할 내용
def build_embedding_text(param: dict) -> str:
    parts = []
    if param.get("param_key"):
        parts.append(f"Key: {param['param_key']}")
    if param.get("semantic_name"):
        parts.append(f"Name: {param['semantic_name']}")
    if param.get("concept_category"):
        parts.append(f"Category: {param['concept_category']}")
    if param.get("unit"):
        parts.append(f"Unit: {param['unit']}")
    if param.get("description"):
        parts.append(f"Description: {param['description']}")
    return " | ".join(parts)

# 예시: "Key: Orchestra/PPF20_CE | Name: Propofol (20 mg/mL) Effect-site Concentration | Category: Medication | Unit: mcg/mL"
```

**DB 변경:**

```sql
-- parameter 테이블에 컬럼 추가
ALTER TABLE parameter
    ADD COLUMN IF NOT EXISTS name_embedding vector(1536),
    ADD COLUMN IF NOT EXISTS embedding_model varchar(100),
    ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz;

-- 인덱스 생성 (259개 → IVFFlat 충분)
CREATE INDEX IF NOT EXISTS idx_parameter_embedding
    ON parameter USING ivfflat (name_embedding vector_cosine_ops)
    WITH (lists = 10);
```

**파일 캐시 (재시작 시 API 재호출 방지):**

```python
# IndexingAgent/data/parameter_embeddings.npz
# 캐시 무효화 조건: MAX(parameter.updated_at) > 캐시 파일 수정시간
```

**비용:** 259개 파라미터 × `text-embedding-3-small` = **$0.001 이하, 1회성**

**구현 위치:** `IndexingAgent/src/agents/nodes/parameter_semantic/node.py`

---

### [P0] I-02: measurement_type 자동 추론 및 저장

**출처:** `architecture_evolution.html`, `VITALAGENT_TODO.md (T-08, T-09)`  
**연관 TODO:** `T-08` (Waveform vs Scalar), `T-09` (Volume vs Rate)  
**ExtractionAgent 대응:** [`E-02` measurement_type DB 활용](./ExtractionAgent_ROADMAP.md#p0-e-02-measurement_type-db-필드-활용-ontologycache-교체), [`E-09` OntologyCache 중복 제거](./ExtractionAgent_ROADMAP.md#p2-e-09-ontologycache-중복-로직-제거-i-02-완료-후) — I-02 없이 E-02, E-09 불가

**문제:**  
ExtractionAgent의 OntologyCache가 런타임에 unit 패턴으로 measurement_type을 추론한다. 이 로직이 ExtractionAgent에 있으면 인덱싱 후 데이터셋이 달라져도 다시 추론해야 한다. IndexingAgent가 한 번 계산해 DB에 저장하는 것이 올바른 위치다.

**현재 위치 (잘못됨):** `ExtractionAgent/src/agents/nodes/parameter_resolver/ontology_cache.py`

```python
# 현재 ExtractionAgent에 있는 로직 → IndexingAgent로 이전해야 함
_RATE_UNITS = {"/hr", "/min", "/h"}
_CUMULATIVE_UNITS = {"ml", "mg", "mcg", "g"}
_CONCENTRATION_UNITS = {"mcg/ml", "ng/ml", "mg/ml", "%"}
_WAVEFORM_UNITS = {"uv", "mv"}
```

**해결책: [600] parameter_semantic 노드에서 동시 계산**

```python
def infer_measurement_type(unit: str, concept_category: str = "") -> str:
    """
    SI 국제표준 unit 패턴으로 measurement_type 추론.
    어떤 데이터셋이든 단위 체계는 공통이므로 dataset-agnostic.
    """
    unit_lower = (unit or "").lower().strip()

    # Waveform: Neo4j concept 또는 전기 신호 단위
    if concept_category in {"Waveform/Signal"} or any(u in unit_lower for u in ["uv", "mv"]):
        return "waveform"

    # Rate: 시간당 투여량 또는 속도
    if any(s in unit_lower for s in ["/hr", "/min", "/h", "/sec", "hz"]):
        return "rate"

    # Cumulative: 누적 투여량 (단순 부피/질량 단위)
    unit_stripped = unit_lower.replace(" ", "")
    if unit_stripped in {"ml", "mg", "mcg", "g", "u", "mmol", "iu", "l"}:
        return "cumulative"

    # Concentration: 농도
    if unit_stripped in {"mcg/ml", "ng/ml", "mg/ml", "mg/dl", "mmol/l", "%"}:
        return "concentration"

    return "scalar"
```

**DB 변경:**

```sql
ALTER TABLE parameter
    ADD COLUMN IF NOT EXISTS measurement_type varchar(30)
        CHECK (measurement_type IN ('scalar', 'rate', 'cumulative', 'waveform', 'concentration'));
```

**구현 위치:** `IndexingAgent/src/agents/nodes/parameter_semantic/node.py`  
**정리 필요:** `ExtractionAgent/src/agents/nodes/parameter_resolver/ontology_cache.py`의 중복 로직 제거 후 DB 필드 조회로 교체

---

### [P1] I-03: Parameter Concept Clustering (concept_id, concept_priority)

**출처:** `architecture_evolution.html`, `FUTURE_WORK.md (A-4 Layer 1: PCO)`  
**연관 TODO:** `T-03` (Cross-Device Disambiguation)  
**ExtractionAgent 대응:** [`E-05` concept_priority 기반 Disambiguation](./ExtractionAgent_ROADMAP.md#p1-e-05-concept_priority-기반-cross-device-disambiguation) — I-03 없이 E-05 불가

**문제:**  
동일한 생리학적 개념이 여러 장비에 존재할 때 어떤 것을 선택할지 프롬프트 규칙에 의존한다. LLM은 확률적이므로 같은 쿼리에서도 결과가 달라진다.

```
Expected: Solar8000/ETCO2   →   Retrieved: Primus/ETCO2    (잘못됨)
Expected: Primus/TV         →   Retrieved: Solar8000/VENT_TV (잘못됨)
```

**해결책: 인덱싱 시점에 임베딩 클러스터링으로 concept_id 자동 생성**

```python
# [600] parameter_semantic 이후 새 노드로 추가 또는 post-processing
# 임베딩 기반 클러스터링: 코사인 유사도 > 0.92이면 같은 concept

from sklearn.cluster import AgglomerativeClustering
import numpy as np

def compute_concept_clusters(embeddings: np.ndarray, threshold: float = 0.92) -> list[int]:
    """
    임베딩 유사도 기반 계층적 클러스터링.
    비지도 학습 → 레이블 없이 자동 생성.
    """
    distance_matrix = 1 - (embeddings @ embeddings.T)
    clustering = AgglomerativeClustering(
        n_clusters=None,
        metric="precomputed",
        linkage="complete",
        distance_threshold=1 - threshold
    )
    return clustering.fit_predict(distance_matrix)
```

**concept_priority 자동 결정 규칙:**

```
concept_priority 규칙 (같은 concept_id 내에서):
1. variant_type = 'measured' → priority 1 (실측값 우선)
2. variant_type = 'target_setting' → priority 2 (설정값 차순위)
3. variant_type = 'derived' → priority 3 (파생값 최하위)
4. 동일 variant_type 내: file_group의 is_primary_device 필드 기준
```

**DB 변경:**

```sql
ALTER TABLE parameter
    ADD COLUMN IF NOT EXISTS concept_id varchar(100),
    ADD COLUMN IF NOT EXISTS concept_priority int DEFAULT 1,
    ADD COLUMN IF NOT EXISTS variant_type varchar(30)
        CHECK (variant_type IN ('measured', 'target_setting', 'derived', 'waveform', 'scalar')),
    ADD COLUMN IF NOT EXISTS device_group varchar(100);

-- concept_id 기준 조회 최적화
CREATE INDEX IF NOT EXISTS idx_parameter_concept_id ON parameter (concept_id);
```

**구현 위치:** `IndexingAgent/src/agents/nodes/parameter_concept/node.py` (신규 노드 [650])

---

### [P1] I-04: Dataset 노드 추가 및 FileGroup 연결

**출처:** `ONTOLOGY_KNOWLEDGE_EXTENSION.md (Section 3)`  
**연관 TODO:** 다중 데이터셋 지원, 자율형 에이전트 전환

**문제:**  
현재 Neo4j에 `Dataset` 레벨 노드가 없다. FileGroup이 최상위 노드여서 여러 데이터셋을 동시에 관리하거나 데이터셋 단위 지식을 저장할 수 없다.

**해결책:**

```cypher
// Dataset 노드 생성
CREATE (:Dataset {
    dataset_id: String,        // "vitaldb", "mimic-iv", uuid
    name: String,              // "VitalDB"
    path: String,              // "/data/vitaldb"
    description: String,
    created_at: DateTime,
    indexed_at: DateTime,
    param_count: Int,
    file_count: Int
})

// FileGroup → Dataset 연결
(Dataset)-[:HAS_FILE_GROUP]->(FileGroup)
```

**구현 위치:**
- `IndexingAgent/src/agents/nodes/relationship_inference/node.py` — Dataset 노드 생성 추가
- `shared/database/repositories/` — `DatasetRepository` 신규 클래스

---

### [P1] I-05: Knowledge 노드 (Progressive Learning Layer)

**출처:** `ONTOLOGY_KNOWLEDGE_EXTENSION.md (전체)`, `TEMPORAL_COLUMN_ARCHITECTURE.md`  
**연관 TODO:** Signal 시간 컬럼 하드코딩 제거, Cohort-Signal 시간 관계

**문제:**  
시스템이 학습한 지식(시간 컬럼 이름, Cohort-Signal 관계 등)을 저장하지 않는다. 분석할 때마다 하드코딩에 의존하거나 사용자가 반복해서 알려줘야 한다.

```python
# 현재 하드코딩 (shared/data/context.py)
if "Time" in signals_df.columns:  # ← 제거 대상
    ...
```

**해결책: Neo4j Knowledge 노드**

```cypher
(:Knowledge {
    knowledge_id: String,    // UUID
    type: String,
    value: Map,
    source: String,          // "auto_detected" | "user_feedback" | "default"
    confidence: Float,
    created_at: DateTime,
    updated_at: DateTime
})-[:APPLIES_TO]->(Dataset | FileGroup | RowEntity)
```

**Knowledge 타입 정의:**

| type | 저장 내용 | 예시 |
|------|----------|------|
| `time_column` | Signal 데이터의 시간 컬럼 정보 | `{column_name: "Time", unit: "seconds"}` |
| `cohort_signal_time_relation` | 두 시간 체계의 관계 | `{relation: "same_relative_axis"}` |
| `temporal_range_columns` | 시간 범위 컬럼 의미 | `{start: "opstart", end: "opend", meaning: "surgery_window"}` |
| `identifier_column` | Entity 식별자 컬럼 | `{column_name: "caseid", links_cohort_to_signal: true}` |
| `file_naming_pattern` | 파일명 패턴 | `{pattern: "{caseid}.vital", id_type: "integer"}` |
| `data_quality_issue` | 데이터 품질 문제 | `{issue: "duplicate_timestamps", affected_ratio: 0.02}` |

**조회 우선순위:** `RowEntity > FileGroup > Dataset`

**구현 위치:**
- `shared/database/repositories/knowledge_repository.py` (신규)
- `IndexingAgent/src/agents/nodes/relationship_inference/node.py` — 기본 Knowledge 자동 저장
- `shared/data/context.py` — 하드코딩 제거 후 KnowledgeRepository 조회로 교체

---

### [P2] I-06: Signal 시간 컬럼 메타데이터 자동 감지

**출처:** `TEMPORAL_COLUMN_ARCHITECTURE.md (Section 2.2, 4.3)`

**문제:**  
`.vital` 파일 로드 시 SignalProcessor가 생성하는 "Time" 컬럼이 어디에도 기록되지 않는다. IndexingAgent는 원본 파일에 해당 컬럼이 없어서 인덱싱할 수 없었다.

```
.vital 원본 파일: [HR, SpO2, ABP, ...]  ← Time 컬럼 없음
SignalProcessor 로드 후: [Time, HR, SpO2, ABP, ...]  ← Time 추가됨
IndexingAgent: Time 컬럼을 알 수 없음 ← 단절!
```

**해결책:**  
[600] parameter_semantic 또는 [200] file_catalog 노드에서 SignalProcessor 설정을 읽어 Knowledge 노드로 저장.

```python
# file_catalog [200] 에서 Signal 파일 처리 시
if processor_type == "signal":
    # SignalProcessor의 time_column 설정을 Knowledge로 저장
    knowledge = {
        "type": "time_column",
        "value": {
            "column_name": signal_processor.time_column_name,  # "Time"
            "unit": "seconds",
            "origin": "processor_generated",
            "resample_interval": signal_processor.resample_interval
        },
        "source": "auto_detected",
        "confidence": 1.0
    }
    # Neo4j Knowledge 노드로 저장
    knowledge_repo.save(knowledge, scope="file_group", scope_id=group_id)
```

**구현 위치:** `IndexingAgent/src/agents/nodes/file_catalog/node.py`

---

### [P2] I-07: device_group 자동 분류

**출처:** `architecture_evolution.html`, `FUTURE_WORK.md (A-2 이슈1)`  
**연관 TODO:** `T-03` Cross-Device Disambiguation  
**ExtractionAgent 대응:** [`E-05` concept_priority 기반 Disambiguation](./ExtractionAgent_ROADMAP.md#p1-e-05-concept_priority-기반-cross-device-disambiguation) — I-03과 함께 E-05에서 활용

**문제:**  
"Solar8000"과 "Primus"가 어떤 역할의 장비인지 IndexingAgent가 판단하지 않는다. 역할 정보 없이는 Cross-device disambiguation을 데이터 기반으로 할 수 없다.

**해결책: file_group 메타데이터에서 역할 추론 (LLM)**

```python
# [350] file_grouping 노드에서 추가
DEVICE_ROLE_PROMPTS = """
file_group 이름과 포함된 param_key 패턴을 보고 장비 역할을 분류하세요.
- patient_monitor: 환자 바이탈 모니터링 장비 (Solar8000 등)
- anesthesia_machine: 마취기 (Primus 등)
- infusion_pump: 약물 주입 펌프 (Orchestra 등)
- ventilator: 인공호흡기
- neurological_monitor: 신경 모니터 (BIS 등)
- other: 분류 불가
"""
```

**DB 변경:**

```sql
-- file_group 테이블에 추가
ALTER TABLE file_group
    ADD COLUMN IF NOT EXISTS device_role varchar(50),
    ADD COLUMN IF NOT EXISTS is_primary_device boolean DEFAULT false;

-- parameter 테이블에 device_group 컬럼 추가 (file_group.device_role 복사)
-- I-03에서 이미 포함됨
```

**구현 위치:** `IndexingAgent/src/agents/nodes/file_grouping/node.py`

---

### [P2] I-08: 증분 인덱싱 (Incremental Indexing)

**출처:** `FUTURE_WORK.md (B-2 한계점 1)`

**문제:**  
현재 IndexingAgent는 전체 디렉토리를 매번 처음부터 재인덱싱한다. 새 파일이 추가되거나 일부 파일만 변경된 경우에도 전체 파이프라인을 재실행해야 한다.

**해결책:**

```python
# directory_catalog [100] 노드에서 변경 감지
def detect_changed_files(directory: str, db: DatabaseManager) -> dict:
    """
    파일별 수정 시간(mtime)을 비교하여 변경된 파일만 반환.
    - new: 새로 추가된 파일
    - modified: 수정된 파일
    - deleted: 삭제된 파일
    """
    current_files = {f: os.path.getmtime(f) for f in glob(directory)}
    indexed_files = {r.file_path: r.indexed_at for r in db.query(FileCatalog)}

    return {
        "new": [f for f in current_files if f not in indexed_files],
        "modified": [f for f in current_files if f in indexed_files
                     and current_files[f] > indexed_files[f].timestamp()],
        "deleted": [f for f in indexed_files if f not in current_files],
    }
```

**구현 위치:** `IndexingAgent/src/agents/nodes/directory_catalog/node.py`

---

### [P3] I-09: Embedding 캐시 무효화 자동화

**출처:** `EMBEDDING_PARAMETER_SEARCH.md (Section 6)`

**문제:**  
I-01에서 계산된 임베딩 캐시(`parameter_embeddings.npz`)가 파라미터가 추가/수정되어도 자동으로 갱신되지 않는다.

**해결책:**

```python
# IndexingAgent가 parameter_semantic [600] 완료 후 자동 실행
def invalidate_embedding_cache(db: DatabaseManager):
    """
    parameter 테이블의 MAX(updated_at)와 캐시 파일 mtime 비교.
    캐시가 오래됐으면 embedding 재계산 트리거.
    """
    latest_param_update = db.query("SELECT MAX(updated_at) FROM parameter").scalar()
    cache_path = Path("IndexingAgent/data/parameter_embeddings.npz")

    if not cache_path.exists() or cache_path.stat().st_mtime < latest_param_update.timestamp():
        rebuild_embedding_cache(db)
        logger.info("Embedding cache rebuilt due to parameter updates")
```

**구현 위치:** `IndexingAgent/src/post_processing/embedding_cache_manager.py` (신규)

---

## 3. 구현 우선순위 요약

| 우선순위 | ID | 기능 | 예상 기간 | 해결하는 TODO | ExtractionAgent 대응 | 구현 위치 |
|---------|-----|------|----------|--------------|---------------------|---------|
| **P0** | I-01 | Parameter Embedding 계산 | 1일 | T-02, T-03, T-05, T-08, T-09 | **E-01** Vector Search | `[600] parameter_semantic` |
| **P0** | I-02 | measurement_type 자동 추론 | 0.5일 | T-08, T-09 | **E-02** measurement_type 활용, **E-09** 중복 제거 | `[600] parameter_semantic` |
| **P1** | I-03 | Concept Clustering (concept_id, priority) | 2일 | T-03 | **E-05** concept_priority Disambiguation | `[650] parameter_concept` (신규) |
| **P1** | I-04 | Dataset 노드 추가 | 1일 | 다중 데이터셋 지원 | — | `[900] relationship_inference` |
| **P1** | I-05 | Knowledge 노드 (Progressive Learning) | 3일 | 시간 컬럼 하드코딩 제거 | `context.py` 하드코딩 제거 | 신규 repository + 노드 |
| **P2** | I-06 | Signal 시간 컬럼 메타데이터 | 1일 | 시간 하드코딩 제거 | `context.py` 하드코딩 제거 | `[200] file_catalog` |
| **P2** | I-07 | device_group 자동 분류 | 1일 | T-03 보완 | **E-05** (I-03과 함께) | `[350] file_grouping` |
| **P2** | I-08 | 증분 인덱싱 | 2일 | 운영 효율성 | — | `[100] directory_catalog` |
| **P3** | I-09 | Embedding 캐시 자동 무효화 | 0.5일 | 운영 안정성 | — | 신규 post-processing |

---

## 4. DB 스키마 변경 요약 (DDL)

> 모든 컬럼은 `IF NOT EXISTS`로 추가하여 기존 데이터에 영향 없음.

```sql
-- parameter 테이블 확장 (I-01, I-02, I-03)
ALTER TABLE parameter
    -- I-01: Embedding
    ADD COLUMN IF NOT EXISTS name_embedding vector(1536),
    ADD COLUMN IF NOT EXISTS embedding_model varchar(100),
    ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz,
    -- I-02: Measurement type
    ADD COLUMN IF NOT EXISTS measurement_type varchar(30)
        CHECK (measurement_type IN ('scalar', 'rate', 'cumulative', 'waveform', 'concentration')),
    -- I-03: Concept clustering
    ADD COLUMN IF NOT EXISTS concept_id varchar(100),
    ADD COLUMN IF NOT EXISTS concept_priority int DEFAULT 1,
    ADD COLUMN IF NOT EXISTS variant_type varchar(30)
        CHECK (variant_type IN ('measured', 'target_setting', 'derived', 'waveform', 'scalar')),
    ADD COLUMN IF NOT EXISTS device_group varchar(100);

-- file_group 테이블 확장 (I-07)
ALTER TABLE file_group
    ADD COLUMN IF NOT EXISTS device_role varchar(50),
    ADD COLUMN IF NOT EXISTS is_primary_device boolean DEFAULT false;

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_parameter_embedding
    ON parameter USING ivfflat (name_embedding vector_cosine_ops)
    WITH (lists = 10);

CREATE INDEX IF NOT EXISTS idx_parameter_concept_id
    ON parameter (concept_id);

CREATE INDEX IF NOT EXISTS idx_parameter_measurement_type
    ON parameter (measurement_type);
```

---

## 5. Neo4j 스키마 변경 요약 (I-04, I-05)

```cypher
// Dataset 노드 (I-04)
CREATE CONSTRAINT dataset_id IF NOT EXISTS
    FOR (d:Dataset) REQUIRE d.dataset_id IS UNIQUE;

// Knowledge 노드 (I-05)
CREATE CONSTRAINT knowledge_id IF NOT EXISTS
    FOR (k:Knowledge) REQUIRE k.knowledge_id IS UNIQUE;

// 관계
// (Dataset)-[:HAS_FILE_GROUP]->(FileGroup)
// (Knowledge)-[:APPLIES_TO]->(Dataset | FileGroup | RowEntity)
```

---

## 6. ExtractionAgent와의 인터페이스 계약

> **전체 연계 설계:** [`ExtractionAgent_ROADMAP.md`](./ExtractionAgent_ROADMAP.md) 참조

IndexingAgent가 위 기능을 구현하면, ExtractionAgent에서 수행해야 하는 대응 작업:

| IndexingAgent 작업 | ExtractionAgent 대응 작업 | 제거/교체 대상 | 참조 |
|-------------------|--------------------------|--------------|------|
| **I-01** `parameter.name_embedding` 컬럼 생성 | **E-01** `_search_parameters()`에 vector cosine search 추가 | ILIKE 단독 사용 → fallback으로 유지 | [E-01](./ExtractionAgent_ROADMAP.md#p0-e-01-vector-similarity-search-ilike-교체) |
| **I-02** `parameter.measurement_type` 컬럼 생성 | **E-02** `OntologyCache.filter_by_measurement_type()` DB 필드 조회로 교체 | `_RATE_UNITS`, `_CUMULATIVE_UNITS` 등 상수 | [E-02](./ExtractionAgent_ROADMAP.md#p0-e-02-measurement_type-db-필드-활용-ontologycache-교체) |
| **I-03** `concept_id`, `concept_priority` 컬럼 생성 | **E-05** Resolver DB 쿼리에 `ORDER BY concept_priority` 추가, 프롬프트에 디바이스 우선순위 규칙 주입 | Cross-device 규칙 하드코딩 프롬프트 | [E-05](./ExtractionAgent_ROADMAP.md#p1-e-05-concept_priority-기반-cross-device-disambiguation) |
| **I-07** `file_group.device_role` 컬럼 생성 | **E-05** (I-03과 함께 사용) | — | [E-05](./ExtractionAgent_ROADMAP.md#p1-e-05-concept_priority-기반-cross-device-disambiguation) |
| **I-05, I-06** Knowledge 노드 (시간 컬럼) | `shared/data/context.py`의 `if "Time" in df.columns` 하드코딩 제거 | `KnowledgeRepository.get("time_column")`으로 교체 | — |

### ExtractionAgent 독립 작업 (IndexingAgent 불필요)

아래 항목들은 IndexingAgent와 무관하게 즉시 구현 가능:

| ExtractionAgent 작업 | 예상 효과 | 예상 기간 |
|---------------------|---------|---------|
| **E-03** QU AND 복합 쿼리 분리 규칙 (`prompts.py`) | Level1 P3 4케이스 해결 | 30분 |
| **E-04** Ambiguity Detection (`scope_intent`) | Temporal Ambiguous 50케이스 | 2일 |
| **E-06** Behavior Classification 수정 | behavior_acc 지표 개선 | 1일 |
| **E-08** Adversarial FP 방지 | Level1 P4 1케이스 | 2시간 |

---

## 7. 자율형 에이전트 전환 시 IndexingAgent 역할 변화

**현재 (필수 사전 단계):**
```
사용자 → [IndexingAgent 완료 필수] → ExtractionAgent → AnalysisAgent
```

**장기 목표 (FUTURE_WORK.md Part B):**
```
사용자 → Orchestrator (ReAct Loop)
              │
              ├─ [필요시] IndexingAgent.run(directory)  ← 백그라운드 도구로 전환
              ├─ list_files(directory)                   ← 즉시 탐색
              └─ peek_file(file_path)                    ← 즉시 스키마 파악
```

이 전환을 가능하게 하려면 IndexingAgent가:
1. **디렉토리 단위 API**로 호출 가능해야 함 (현재 지원)
2. **증분 인덱싱** 지원으로 빠른 응답 가능 (I-08)
3. **Semantic Index 완성**으로 최초 1회 인덱싱만으로 무기한 사용 가능 (I-01~I-03)

---

---

## 8. 전체 시스템 의존성 다이어그램

> IndexingAgent(I-XX) → ExtractionAgent(E-XX) 구현 순서 및 의존 관계

```
[즉시 가능 — IndexingAgent 불필요]
─────────────────────────────────────────────────────
E-03  QU AND 분리 규칙         (30분) ──→ Level1 P3 +4건
E-04  Ambiguity Detection       (2일)  ──→ Temporal +50건
E-06  Behavior Classification   (1일)  ──→ behavior_acc 개선
E-08  Adversarial FP 방지       (2시간) ──→ Level1 P4 +1건

[IndexingAgent P0 완료 후 가능]
─────────────────────────────────────────────────────
I-01 Parameter Embedding (1일)
  └──→ E-01 Vector Search (1일) ──→ Level1 P1 +7~9건

I-02 measurement_type (0.5일)
  └──→ E-02 measurement_type 활용 (0.5일) ──→ T-08, T-09 해결
  └──→ E-09 OntologyCache 중복 제거 (0.5일) ──→ 코드 정리

[IndexingAgent P1 완료 후 가능]
─────────────────────────────────────────────────────
I-03 Concept Clustering (2일)
  └──→  ┐
I-07 device_group (1일)         ├──→ E-05 Disambiguation (1일) ──→ Level1 P2 +6~7건
        ┘

I-05, I-06 Knowledge 노드 (3+1일)
  └──→ shared/data/context.py 하드코딩 제거

─────────────────────────────────────────────────────
예상 누적 Level1 F1: 84.4% → 90%+ (E-03,E-01,E-05 모두 완료 시)
```

---

*문서 작성일: 2026-03-31*  
*상태: 설계 완료, 구현 대기*  
*연계 문서: [ExtractionAgent_ROADMAP.md](./ExtractionAgent_ROADMAP.md)*  
*다음 검토일: 구현 완료 후*
