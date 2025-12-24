# 온톨로지 강화 TODO

## 개요
VitalDB 수준의 데이터 처리는 현재 MVP 온톨로지로 충분하지만, 
복잡한 의료 데이터(OMOP, FHIR 등)를 처리하려면 계층 구조와 용어 매핑이 필요함.

**핵심 원칙**: 모든 것을 LLM이 동적으로 생성한다 (정적 테이블 금지)

---

## Phase 1-A: Value Mappings ✅ 완료

### 목표
- LLM이 데이터 값의 의미를 추론하여 저장
- 예: `sex` 컬럼의 `0` → `Male`, `1` → `Female`

### 구현 완료 항목
- [x] `analyze_columns_with_llm` 프롬프트에 `value_mappings` 요청 추가
- [x] 응답 파싱에 `value_mappings` 추가

### 저장 위치
- PostgreSQL `column_metadata` 테이블의 기존 JSONB 필드 활용

---

## Phase 1-B: Intra-table Hierarchy 🚧 진행중

### 목표
- 테이블 내 ID 컬럼 간의 계층 관계 감지 및 저장
- 예: `subjectid` (환자) → `caseid` (수술) = 1:N 관계
- 이 관계를 모르면 "환자 단위 분석"인지 "수술 단위 분석"인지 혼동

### 하이브리드 저장 전략

| 저장소 | 역할 | 용도 |
|--------|------|------|
| **PostgreSQL** | 물리적 참조 | 빠른 SQL 생성 |
| **Neo4j** | 논리적 족보 | 복잡한 추론 쿼리 |

### 구현 항목

#### 1.1 LLM 프롬프트 강화
- [x] `analyze_columns_with_llm` 프롬프트에 `intra_table_hierarchy` 요청 추가

**프롬프트:**
```
12. intra_table_hierarchy: (ONLY for ID/key columns)
    Analyze if there's a parent-child relationship between ID columns.
    - Look for patterns like: same parent_id appearing with multiple child_ids
    - Example: subjectid=1001 has caseid=[001, 002, 003]
    
    Format:
    {
        "child_column": "caseid",
        "parent_column": "subjectid",
        "cardinality": "N:1",
        "reasoning": "subjectid 1001 appears with multiple caseids"
    }
```

#### 1.2 PostgreSQL column_metadata 확장
- [ ] `parent_column` 필드 추가
- [ ] `cardinality` 필드 추가

```json
{
  "full_name": "Surgery Case ID",
  "description": "...",
  "parent_column": "subjectid",
  "cardinality": "N:1"
}
```

#### 1.3 Neo4j 관계 저장
- [ ] `(:Column) -[:CHILD_OF]-> (:Column)` 관계 저장 메서드 추가

```cypher
(:Column {name: 'caseid', table: 'clinical_data'})
  -[:CHILD_OF {cardinality: 'N:1'}]->
(:Column {name: 'subjectid', table: 'clinical_data'})
```

### 영향받는 파일
- `src/agents/helpers/llm_helpers.py` - 프롬프트 수정
- `src/agents/nodes/analyzer.py` - hierarchy 저장 로직 추가
- `src/utils/ontology_manager.py` - Neo4j CHILD_OF 관계 저장

---

## Phase 2: Concept Layer & Standard Mapping 🔮 나중

### 목표
- 외부 지식 그래프(SNOMED, LOINC 등) 연동
- Column → Concept 매핑
- Concept 간 계층 구조 (IS_A 관계)

### 구조 (Phase 2 완료 후)
```
(:Column {name: 'caseid'}) 
  -[:MAPS_TO]-> 
(:Concept {name: 'Surgery Case'}) 
  -[:PART_OF]-> 
(:Concept {name: 'Patient'})
```

### 필요 사항
- [ ] 외부 KG API 연동 (SNOMED CT, LOINC, OMOP)
- [ ] LLM이 후보 제안 → KG에서 검증

---

## Phase 3: Metadata Enhancement 🔮 나중

### 목표
- 메타데이터 파일 처리 시 계층 구조 추론
- 현재는 flat한 key-value만 저장

### 현재 문제
```python
# 현재: 단순 파싱
definitions["sbp"] = "systolic blood pressure | unit=mmHg"

# 개선 필요: LLM이 계층 추론
{
  "sbp": {
    "definition": "systolic blood pressure",
    "parent_concept": "Blood Pressure",
    "grandparent": "Hemodynamics"
  }
}
```

---

## 저장 위치 정리

| 데이터 | 저장 위치 | 이유 |
|--------|----------|------|
| Value Mappings | PostgreSQL `column_metadata` | 컬럼별 메타데이터 |
| Intra-table Hierarchy | PostgreSQL + Neo4j | 물리적 + 논리적 |
| Inter-table FK | Neo4j `relationships` | 테이블 간 관계 |
| Concept Hierarchy | Neo4j (Phase 2) | 개념적 계층 |

---

## 진행 상태

- [x] Phase 1-A: Value Mappings 프롬프트 추가
- [x] Phase 1-A: Value Mappings 파싱 추가
- [ ] Phase 1-B: Intra-table Hierarchy 프롬프트 추가
- [ ] Phase 1-B: Hierarchy PostgreSQL 저장
- [ ] Phase 1-B: Hierarchy Neo4j 저장
- [ ] Phase 1: 테스트 및 검증
- [ ] Phase 2: Concept Layer 설계
- [ ] Phase 3: Metadata Enhancement

---

## 하지 말아야 할 것 ❌

1. **정적 테이블 생성 금지**
   - `CREATE TABLE concept_hierarchy` ❌
   - `CREATE TABLE vocabulary_mappings` ❌

2. **스키마 고정 금지**
   - JSONB의 유연성 활용
   - LLM이 새로운 필드를 동적으로 추가 가능하게
