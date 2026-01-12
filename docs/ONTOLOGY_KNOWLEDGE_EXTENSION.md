# Neo4j 온톨로지 확장: Knowledge Layer 추가

## 1. 개요

### 목적
- **점진적 학습(Progressive Learning)** 지원
- 분석 과정에서 얻은 지식을 온톨로지에 저장
- 사용자 피드백을 통한 지식 확장
- 범위별(Dataset, FileGroup, File) 지식 관리

### 배경
현재 시스템은 Signal 데이터의 시간 컬럼 등 일부 정보를 하드코딩에 의존하고 있음.
이를 해결하기 위해 "학습된 지식"을 저장하고 활용할 수 있는 구조가 필요함.

---

## 2. 현재 Neo4j 온톨로지 구조

### 2.1 노드 타입 (Node Types)

| 노드 | 설명 | 주요 속성 |
|------|------|----------|
| `RowEntity` | 테이블/파일 단위 | file_id, file_name, row_represents |
| `FileGroup` | 파일 그룹 | group_id, name, file_count |
| `ConceptCategory` | 개념 카테고리 | name (Vital Signs, Timestamps 등) |
| `Parameter` | 파라미터 (컬럼) | key, name, unit, concept_category |
| `SubCategory` | 세부 카테고리 | name, parent |
| `MedicalTerm` | 의료 표준 용어 | code, system, name |

### 2.2 관계 (Relationships)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              현재 구조                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   FileGroup ──CONTAINS_FILE──▶ RowEntity ──HAS_COLUMN──▶ Parameter          │
│       │                            │                          │             │
│       │                            │                          │             │
│   HAS_COMMON_PARAM            LINKS_TO                   ◀──CONTAINS──      │
│       │                            │                          │             │
│       ▼                            ▼                          │             │
│   Parameter                   RowEntity              ConceptCategory        │
│                                                           │                 │
│                                                    HAS_SUBCATEGORY          │
│                                                           │                 │
│                                                           ▼                 │
│                                                      SubCategory            │
│                                                                              │
│   Parameter ──MAPS_TO──▶ MedicalTerm                                        │
│   Parameter ──DERIVED_FROM──▶ Parameter                                     │
│   Parameter ──RELATED_TO──▶ Parameter                                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 현재 계층

```
(암시적 Dataset) ─── 현재 명시적 노드 없음
    │
    └── FileGroup
            │
            └── RowEntity (파일/테이블)
                    │
                    └── Parameter (컬럼)
```

---

## 3. 제안: 온톨로지 확장

### 3.1 새로운 노드 타입

#### Dataset 노드 (신규)

최상위 레벨 노드로 데이터셋 전체를 대표.

```cypher
(:Dataset {
    dataset_id: String,      // "vitaldb", "mimic-iv"
    name: String,            // "VitalDB"
    path: String,            // "/data/vitaldb"
    description: String,     // 선택
    created_at: DateTime
})
```

#### Knowledge 노드 (신규)

학습된 지식을 저장하는 노드.

```cypher
(:Knowledge {
    knowledge_id: String,    // UUID
    type: String,            // "time_column", "time_unit", "cohort_signal_relation"
    value: Map,              // {column_name: "Time", unit: "seconds", ...}
    source: String,          // "user_feedback", "auto_detected", "default"
    confidence: Float,       // 0.0 ~ 1.0
    created_at: DateTime,
    updated_at: DateTime
})
```

### 3.2 새로운 관계

```cypher
// Dataset → FileGroup 연결
(Dataset)-[:HAS_FILE_GROUP]->(FileGroup)

// Knowledge → 각 레벨 연결 (범위 지정)
(Knowledge)-[:APPLIES_TO]->(Dataset)      // Dataset 전체에 적용
(Knowledge)-[:APPLIES_TO]->(FileGroup)    // 특정 FileGroup에 적용
(Knowledge)-[:APPLIES_TO]->(RowEntity)    // 특정 파일에만 적용
```

### 3.3 확장된 계층 구조

```
Level 0: Dataset ⭐ 신규
    │
    ├── HAS_FILE_GROUP
    │       │
    │       ▼
    ├── Level 1: FileGroup
    │       │
    │       ├── CONTAINS_FILE
    │       │       │
    │       │       ▼
    │       └── Level 2: RowEntity
    │               │
    │               ├── HAS_COLUMN
    │               │       │
    │               │       ▼
    │               └── Level 3: Parameter
    │
    └── Knowledge 노드들
            │
            └── APPLIES_TO (각 레벨에 연결)
```

---

## 4. Knowledge 타입 정의

### 4.1 시간 관련 지식

```python
# time_column: Signal 데이터의 시간 컬럼 정보
{
    "type": "time_column",
    "value": {
        "column_name": "Time",
        "unit": "seconds",           # seconds, milliseconds, datetime
        "origin": "processor_generated"  # processor_generated, original
    }
}

# cohort_signal_time_relation: Cohort와 Signal 시간 관계
{
    "type": "cohort_signal_time_relation",
    "value": {
        "relation": "same_relative_axis",  # same_relative_axis, absolute_datetime, offset_based
        "description": "Both use relative seconds from recording start",
        "conversion_required": false
    }
}

# temporal_range_columns: 시간 범위 컬럼 의미
{
    "type": "temporal_range_columns",
    "value": {
        "start_column": "opstart",
        "end_column": "opend",
        "meaning": "surgery_window",
        "unit": "seconds"
    }
}
```

### 4.2 데이터 구조 지식

```python
# identifier_column: 식별자 컬럼
{
    "type": "identifier_column",
    "value": {
        "column_name": "caseid",
        "links_cohort_to_signal": true
    }
}

# file_naming_pattern: 파일명 패턴
{
    "type": "file_naming_pattern",
    "value": {
        "pattern": "{caseid}.vital",
        "caseid_type": "integer"
    }
}
```

### 4.3 향후 확장 가능한 타입

```python
KNOWLEDGE_TYPES = [
    "time_column",              # Signal 시간 컬럼
    "cohort_signal_time_relation",  # Cohort-Signal 시간 관계
    "temporal_range_columns",   # 시간 범위 컬럼
    "identifier_column",        # 식별자 컬럼
    "file_naming_pattern",      # 파일명 패턴
    "data_quality_issue",       # 데이터 품질 문제
    "domain_specific_rule",     # 도메인별 규칙
    # ... 확장 가능
]
```

---

## 5. 지식 조회 로직

### 5.1 우선순위 규칙

**좁은 범위의 지식이 넓은 범위보다 우선**

```
우선순위: RowEntity > FileGroup > Dataset
```

### 5.2 Cypher 쿼리 예시

```cypher
// file_group_id로 time_column 지식 조회 (우선순위 적용)
MATCH (fg:FileGroup {group_id: $file_group_id})

// 1. FileGroup 레벨 지식
OPTIONAL MATCH (k1:Knowledge {type: "time_column"})-[:APPLIES_TO]->(fg)

// 2. Dataset 레벨 지식
OPTIONAL MATCH (fg)<-[:HAS_FILE_GROUP]-(d:Dataset)
OPTIONAL MATCH (k2:Knowledge {type: "time_column"})-[:APPLIES_TO]->(d)

// 가장 구체적인 지식 반환
RETURN COALESCE(k1, k2) as knowledge
```

### 5.3 Python 래퍼

```python
class KnowledgeRepository:
    """Neo4j Knowledge 노드 CRUD"""
    
    def get_knowledge(
        self, 
        knowledge_type: str,
        file_group_id: str = None,
        dataset_id: str = None,
        file_id: str = None
    ) -> Optional[Dict]:
        """
        우선순위에 따라 지식 조회
        file_id > file_group_id > dataset_id
        """
        ...
    
    def save_knowledge(
        self,
        knowledge_type: str,
        value: Dict,
        scope_type: str,      # "dataset", "file_group", "file"
        scope_id: str,
        source: str = "user_feedback"
    ) -> str:
        """지식 저장 및 APPLIES_TO 관계 생성"""
        ...
    
    def list_knowledge(
        self,
        scope_type: str = None,
        scope_id: str = None,
        knowledge_type: str = None
    ) -> List[Dict]:
        """조건에 맞는 지식 목록 조회"""
        ...
```

---

## 6. 학습 흐름

### 6.1 사용자 피드백 기반 학습

```
┌─────────────────────────────────────────────────────────────────┐
│  User: "Signal 데이터의 시간 컬럼은 'Time'이야"                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  System:                                                         │
│    1. Knowledge 노드 생성                                        │
│       type: "time_column"                                        │
│       value: {column_name: "Time", unit: "seconds"}              │
│       source: "user_feedback"                                    │
│                                                                  │
│    2. APPLIES_TO 관계 생성                                       │
│       → 현재 분석 중인 FileGroup 또는 Dataset에 연결             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  다음 분석 시:                                                   │
│    - Knowledge 조회 → "Time" 컬럼 자동 사용                      │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 분석 실패 시 질문

```
┌─────────────────────────────────────────────────────────────────┐
│  System: "Signal 데이터에서 시간 컬럼을 찾지 못했습니다.         │
│           다음 중 시간 컬럼은 무엇인가요?"                       │
│                                                                  │
│           1. Time                                                │
│           2. timestamp                                           │
│           3. datetime                                            │
│           4. 직접 입력                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  User: "1" (Time 선택)                                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  System:                                                         │
│    1. 현재 분석에 "Time" 사용                                    │
│    2. Knowledge 노드 생성 및 저장                                │
│    3. "이 정보를 저장할까요? (Dataset/FileGroup 레벨)"           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 구현 계획

### Phase 1: Dataset 노드 추가

**변경 파일:**
- `IndexingAgent/src/agents/nodes/relationship_inference/node.py`
- `shared/database/neo4j_connection.py`

**작업 내용:**
1. Dataset 노드 생성 로직 추가
2. FileGroup → Dataset 연결 (HAS_FILE_GROUP)
3. 기존 FileGroup에 Dataset 연결 마이그레이션

### Phase 2: Knowledge 노드 타입 정의

**새로운 파일:**
- `shared/database/repositories/knowledge_repository.py`

**작업 내용:**
1. Knowledge 노드 스키마 정의
2. CRUD 메서드 구현
3. 우선순위 기반 조회 로직

### Phase 3: 학습 트리거 구현

**변경 파일:**
- `shared/data/context.py` (하드코딩 제거)
- `ExtractionAgent/src/agents/context/schema_context_builder.py`

**작업 내용:**
1. Knowledge 조회 → 시간 컬럼 동적 결정
2. 조회 실패 시 사용자 질문 로직
3. 사용자 응답 → Knowledge 저장

### Phase 4: UI/인터페이스

**작업 내용:**
1. 사용자 피드백 수집 인터페이스
2. 저장된 지식 확인/수정 기능
3. 지식 범위 선택 (Dataset vs FileGroup)

---

## 8. 마이그레이션

### 기존 데이터 처리

```cypher
// 1. 기본 Dataset 노드 생성
CREATE (d:Dataset {
    dataset_id: "default",
    name: "Default Dataset",
    created_at: datetime()
})

// 2. 기존 FileGroup을 Dataset에 연결
MATCH (fg:FileGroup)
MATCH (d:Dataset {dataset_id: "default"})
MERGE (d)-[:HAS_FILE_GROUP]->(fg)

// 3. 기본 Knowledge 추가 (선택)
CREATE (k:Knowledge {
    knowledge_id: randomUUID(),
    type: "time_column",
    value: {column_name: "Time", unit: "seconds", origin: "processor_generated"},
    source: "default",
    confidence: 0.9
})
MATCH (d:Dataset {dataset_id: "default"})
MERGE (k)-[:APPLIES_TO]->(d)
```

---

## 9. 관련 문서

- [TEMPORAL_COLUMN_ARCHITECTURE.md](./TEMPORAL_COLUMN_ARCHITECTURE.md) - 시간 컬럼 문제 정의
- [IndexingAgent_ARCHITECTURE.md](./IndexingAgent_ARCHITECTURE.md) - IndexingAgent 전체 구조
- [ExtractionAgent_ARCHITECTURE.md](./ExtractionAgent_ARCHITECTURE.md) - ExtractionAgent 구조

---

*문서 작성일: 2026-01-12*
*상태: 설계 완료, 구현 대기*
