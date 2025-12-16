# 온톨로지와 Multi-level Anchor 관계 분석

**작성일:** 2025-12-16  
**목적:** 의료 데이터 인덱싱 시스템에서 온톨로지 구축이 Multi-level Anchor 문제를 해결할 수 있는지 분석

---

## 1. 배경 및 현재 문제점

### 1.1 VitalDB 데이터 구조

```
Open_VitalDB_1.0.0/
├── clinical_data.csv       # caseid(PK), subjectid, 74개 컬럼
├── lab_data.csv           # caseid(FK), dt, name, result
├── clinical_parameters.csv # 메타데이터: clinical_data 컬럼 설명
├── lab_parameters.csv     # 메타데이터: lab_data 파라미터 설명
└── track_names.csv        # 메타데이터: vital signal 트랙 설명
```

### 1.2 발견된 문제

#### 문제 1: Multi-level Identifier 존재
```csv
# clinical_data.csv
caseid, subjectid, ...
1,      5955,      ...    # 케이스 1은 환자 5955
2,      2487,      ...    # 케이스 2는 환자 2487

# lab_data.csv
caseid, dt, name, result
1,      ..., alb, 2.9     # 케이스 1의 검사 (subjectid 없음!)
```

**현상:**
- `subjectid` (환자 ID) ≠ `caseid` (수술 케이스 ID)
- `lab_data`는 `caseid`만 가지고 있어 `subjectid`로 직접 JOIN 불가
- 현재 시스템은 `subjectid`를 Master Anchor로 설정했으나, `lab_data` 처리 시 매칭 실패

#### 문제 2: 메타데이터 파일 처리 미흡
```csv
# clinical_parameters.csv
Parameter,  Data Source, Description,              Unit
caseid,     Random,      Case ID; Random number,   
subjectid,  EMR,         Subject ID; Hospital ID,
```

**현상:**
- 메타데이터 파일이 일반 데이터로 처리됨
- Anchor를 찾으려 하다가 실패하고 Human Review 요청
- 온톨로지 정보가 활용되지 않음

---

## 2. 핵심 개념 정리

### 2.1 온톨로지 (Ontology / Data Dictionary)

**정의:** 데이터의 의미, 구조, 관계를 정의하는 메타데이터

**예시:**
```json
{
  "caseid": {
    "description": "Case ID; Random number between 00001 and 06388",
    "type": "identifier",
    "scope": "case",
    "data_source": "Random"
  },
  "subjectid": {
    "description": "Subject ID; Deidentified hospital ID of patient",
    "type": "identifier",
    "scope": "patient",
    "data_source": "EMR"
  },
  "alb": {
    "category": "Chemistry",
    "description": "Albumin",
    "unit": "g/dL",
    "reference_range": "3.3~5.2"
  }
}
```

**온톨로지가 제공하는 정보:**
- ✅ 컬럼의 의미 (Description)
- ✅ 데이터 타입 및 단위
- ✅ 식별자 여부 및 범위 (case/patient)
- ✅ 참조 값 범위

**온톨로지가 제공하지 않는 정보:**
- ❌ 테이블 간 JOIN 방법
- ❌ Primary Key / Foreign Key 관계
- ❌ 계층 구조 (Hierarchy)

---

### 2.2 Multi-level Anchor

**정의:** 여러 레벨의 식별자가 계층적으로 존재하는 구조

**VitalDB 예시:**
```
Level 1 (Case): caseid
  ↓ (매핑: clinical_data 테이블)
Level 2 (Patient): subjectid

관계:
- 한 환자(patient)는 여러 케이스(case)를 가질 수 있음
- 모든 데이터는 caseid로 연결됨
- 환자별 분석을 위해서는 caseid → subjectid 변환 필요
```

**데이터 관계:**
```sql
clinical_data (
    caseid PK,          -- Level 1: Primary Key
    subjectid,          -- Level 2: Grouping Key
    ...
)

lab_data (
    caseid FK,          -- Foreign Key → clinical_data.caseid
    dt,
    name,
    result
)

-- 환자별 검사 결과를 보려면:
SELECT l.*, c.subjectid
FROM lab_data l
JOIN clinical_data c ON l.caseid = c.caseid
WHERE c.subjectid = 5955;
```

---

## 3. 온톨로지가 Multi-level Anchor 해결에 도움이 되는가?

### 3.1 결론

**부분적으로 가능하지만 불충분함**

온톨로지 단독으로는 Multi-level Anchor 문제를 완전히 해결할 수 없으나,  
**온톨로지 + 데이터 구조 분석 + LLM 추론**을 결합하면 자동 해결 가능

---

### 3.2 온톨로지의 기여

#### 기여 1: 식별자 후보 파악
```
온톨로지 정보:
- caseid: "Case ID" (type: identifier, scope: case)
- subjectid: "Patient ID" (type: identifier, scope: patient)

→ 두 식별자가 다른 레벨임을 인식 가능
```

#### 기여 2: LLM 추론의 힌트 제공
```python
# LLM에게 제공하는 컨텍스트
prompt = f"""
[Ontology Information]
- caseid: Case-level identifier
- subjectid: Patient-level identifier

[Data Structure]
- clinical_data: has both caseid and subjectid
- lab_data: has only caseid

[Question]
How should we establish the relationship between these tables?
What is the anchor hierarchy?
"""

# LLM이 추론 가능:
# "lab_data는 caseid를 통해 clinical_data와 JOIN하고,
#  subjectid는 clinical_data를 통해 간접적으로 접근"
```

#### 기여 3: 데이터 품질 검증
```python
# 온톨로지 정의
ontology['caseid']['range'] = '1~6388'

# 실제 데이터 검증
if not (1 <= data['caseid'] <= 6388):
    raise ValueError("caseid out of range")
```

---

### 3.3 온톨로지의 한계

#### 한계 1: 관계 정보 부재
```
온톨로지는 "lab_data.caseid가 clinical_data.caseid를 
참조한다"는 정보를 제공하지 않음

→ 데이터 구조 분석이 추가로 필요
```

#### 한계 2: 계층 구조 명시 불가
```
온톨로지는 "caseid와 subjectid 중 어느 것이 
우선순위(Primary Anchor)인지" 명시하지 않음

→ 비즈니스 로직 기반 결정 필요
```

---

## 4. 제안: 온톨로지 기반 통합 솔루션

### 4.1 Enhanced Ontology 구조

기존 Data Dictionary + 관계 정보 추가

```json
{
  "tables": {
    "clinical_data": {
      "description": "Clinical data for each surgical case",
      "columns": {
        "caseid": {
          "description": "Case ID",
          "type": "identifier",
          "role": "primary_key",
          "range": "1~6388"
        },
        "subjectid": {
          "description": "Patient ID",
          "type": "identifier", 
          "role": "grouping_key"
        }
      }
    },
    "lab_data": {
      "description": "Laboratory test results",
      "columns": {
        "caseid": {
          "description": "Case ID",
          "type": "identifier",
          "role": "foreign_key",
          "references": "clinical_data.caseid"
        }
      }
    }
  },
  
  "relationships": {
    "lab_to_clinical": {
      "type": "many_to_one",
      "foreign_key": "lab_data.caseid",
      "primary_key": "clinical_data.caseid",
      "description": "Lab results belong to a case"
    }
  },
  
  "anchor_hierarchy": {
    "primary_anchor": {
      "name": "caseid",
      "scope": "case",
      "description": "Direct JOIN key for all tables"
    },
    "secondary_anchor": {
      "name": "subjectid",
      "scope": "patient",
      "mapping_table": "clinical_data",
      "mapping_via": "caseid",
      "description": "Patient-level grouping via clinical_data"
    }
  }
}
```

---

### 4.2 자동화 파이프라인

```
┌──────────────────────────────────────────────────────────┐
│ Step 1: 메타데이터 파일 감지 및 온톨로지 구축              │
├──────────────────────────────────────────────────────────┤
│ Input:  clinical_parameters.csv, lab_parameters.csv      │
│ Output: ontology_db.json (컬럼 의미, 타입, 범위)          │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 2: 실제 데이터 테이블 구조 스캔                       │
├──────────────────────────────────────────────────────────┤
│ • clinical_data.csv: [caseid, subjectid, ...]            │
│ • lab_data.csv: [caseid, dt, name, result]               │
│                                                           │
│ 샘플 데이터 추출:                                          │
│ - clinical_data: caseid=1, subjectid=5955                │
│ - lab_data: caseid=1                                     │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 3: LLM 기반 관계 추론 (온톨로지 + 데이터 구조)        │
├──────────────────────────────────────────────────────────┤
│ Input:                                                    │
│ - Ontology: caseid (case-level), subjectid (patient)     │
│ - Structure: clinical has both, lab has only caseid      │
│                                                           │
│ LLM 추론:                                                 │
│ → caseid는 PK (clinical) / FK (lab)                      │
│ → subjectid는 grouping key                               │
│ → lab_data는 clinical_data의 child table                 │
│ → Hierarchy: caseid (L1) → subjectid (L2)                │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 4: Multi-level Anchor 자동 설정                      │
├──────────────────────────────────────────────────────────┤
│ primary_anchor: caseid (직접 JOIN용)                     │
│ secondary_anchor: subjectid (환자별 분석용)               │
│ mapping: clinical_data를 통해 caseid→subjectid 변환       │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 5: 스키마 생성 및 인덱싱                              │
├──────────────────────────────────────────────────────────┤
│ CREATE TABLE clinical_data (                             │
│   caseid INT PRIMARY KEY,                                │
│   subjectid INT,                                         │
│   ...                                                    │
│ );                                                       │
│                                                          │
│ CREATE TABLE lab_data (                                 │
│   caseid INT,                                           │
│   ...                                                   │
│   FOREIGN KEY (caseid) REFERENCES clinical_data(caseid) │
│ );                                                      │
└──────────────────────────────────────────────────────────┘
```

---

## 5. 구현 옵션

### 옵션 A: 간단한 버전 (빠른 구현, 1-2일)

**특징:**
- 메타데이터 파일 감지 → 인덱싱 스킵
- caseid를 Master Anchor로 고정
- 온톨로지는 참고용으로만 저장

**장점:**
- ✅ 빠른 구현
- ✅ 기존 코드 최소 수정

**단점:**
- ❌ 환자별 분석 어려움 (수동 JOIN 필요)
- ❌ 확장성 제한

**코드 예시:**
```python
# nodes.py
def load_data_node(state):
    if is_metadata_file(file_path):
        save_to_ontology(file_path)
        return {"skip_indexing": True}
    
    # 일반 데이터는 caseid를 Anchor로
    project_context["primary_anchor"] = "caseid"
```

---

### 옵션 B: 완전 자동화 버전 (권장, 1주일)

**특징:**
- 메타데이터 → Enhanced Ontology 구축
- LLM이 테이블 관계 자동 추론
- Multi-level Anchor 자동 설정
- JOIN 쿼리 자동 생성

**장점:**
- ✅ 완전 자동화
- ✅ 다른 데이터셋에도 적용 가능
- ✅ 환자별/케이스별 분석 모두 지원

**단점:**
- ❌ 구현 시간 소요
- ❌ LLM 호출 비용 증가

**코드 예시:**
```python
# 1. 메타데이터 처리
ontology_builder = OntologyBuilder()
ontology = ontology_builder.build_from_files(metadata_files)

# 2. 관계 추론
relationship_inferencer = RelationshipInferencer(llm)
relationships = relationship_inferencer.infer(tables, ontology)

# 3. Anchor 설정
project_context.update({
    "primary_anchor": relationships["primary_anchor"],
    "secondary_anchors": relationships["secondary_anchors"],
    "hierarchy": relationships["hierarchy"],
    "join_paths": relationships["join_paths"]
})
```

---

## 6. 권장사항

### 6.1 단계별 접근 (Phased Approach)

#### Phase 1: 메타데이터 처리 (즉시)
```python
# 메타데이터 파일 감지 및 스킵
if is_metadata_file(file_path):
    ontology_db.add(parse_metadata(file_path))
    return {"skip_indexing": True}
```

**예상 효과:**
- 불필요한 Human Review 제거
- 온톨로지 정보 축적

---

#### Phase 2: 관계 추론 (1주 후)
```python
# 온톨로지 + 데이터 구조 → 관계 추론
relationships = infer_relationships(
    tables=all_tables,
    ontology=ontology_db
)
```

**예상 효과:**
- caseid/subjectid 관계 자동 파악
- JOIN 경로 자동 생성

---

#### Phase 3: Multi-level Anchor (2주 후)
```python
# 계층적 Anchor 지원
project_context = {
    "anchors": {
        "case": {"column": "caseid", "level": 1},
        "patient": {
            "column": "subjectid", 
            "level": 2,
            "via": "clinical_data.caseid"
        }
    }
}
```

**예상 효과:**
- 환자별/케이스별 분석 모두 지원
- 복잡한 JOIN 자동 생성

---

### 6.2 VitalDB 특화 설정 (임시)

당장의 문제 해결을 위한 하드코딩:

```python
# config.py
VITALDB_SCHEMA = {
    "primary_anchor": "caseid",
    "secondary_anchor": "subjectid",
    "mapping_table": "clinical_data",
    "metadata_files": [
        "*_parameters.csv",
        "track_names.csv"
    ]
}
```

---

## 7. 예상 효과

### Before (현재)
```
clinical_data.csv → Anchor: subjectid ✅
lab_data.csv → Anchor 매칭 실패 ❌ (Human Review 요청)
clinical_parameters.csv → Anchor 없음 ❌ (Human Review 요청)
```

### After (옵션 B 구현 시)
```
clinical_parameters.csv → 메타데이터 감지 → 온톨로지 구축 ✅

clinical_data.csv → Anchor: caseid (primary) ✅
                  → grouping: subjectid (secondary) ✅
                  
lab_data.csv → Anchor: caseid (FK) ✅
            → Auto-join: via clinical_data ✅
            
환자별 분석:
SELECT * FROM lab_data l
JOIN clinical_data c ON l.caseid = c.caseid
WHERE c.subjectid = 5955;  -- 자동 생성 ✅
```

---

## 8. 결론 및 다음 단계

### 8.1 핵심 결론

**온톨로지가 Multi-level Anchor를 해결하는가?**

→ **온톨로지 단독으로는 불충분하지만**,  
→ **온톨로지 + 데이터 구조 분석 + LLM 추론을 결합하면 자동 해결 가능**

---

### 8.2 즉시 결정 필요 사항

1. **구현 옵션 선택:**
   - [ ] 옵션 A: 간단한 버전 (1-2일)
   - [ ] 옵션 B: 완전 자동화 (1주일)
   - [ ] 단계별 접근 (Phase 1부터 시작)

2. **Primary Anchor 정책:**
   - [ ] caseid 우선 (케이스 중심 분석)
   - [ ] subjectid 우선 (환자 중심 분석)
   - [ ] Multi-level 지원 (둘 다 사용)

3. **온톨로지 저장 형식:**
   - [ ] JSON 파일
   - [ ] SQLite 테이블
   - [ ] 별도 MongoDB

---

### 8.3 Action Items

#### 즉시 (이번 주)
- [ ] 메타데이터 파일 감지 로직 구현
- [ ] 온톨로지 저장 구조 설계
- [ ] VitalDB 특화 설정 추가 (임시)

#### 단기 (다음 주)
- [ ] LLM 기반 관계 추론 구현
- [ ] Multi-level Anchor 설정 로직

#### 장기 (2주 후)
- [ ] JOIN 쿼리 자동 생성
- [ ] 다른 데이터셋으로 일반화

---

## 9. 참고 자료

### 9.1 VitalDB 공식 문서
- https://vitaldb.net/dataset/
- 데이터 구조 및 관계 설명

### 9.2 관련 논문
- "Ontology-based Data Integration in Healthcare" (2020)
- "Automated Schema Matching using LLMs" (2023)

### 9.3 유사 사례
- OMOP CDM: 의료 데이터 표준 온톨로지
- FHIR: Fast Healthcare Interoperability Resources

---

**문서 버전:** 1.0  
**작성자:** Medical AI System Development Team  
**검토 필요 사항:** Primary Anchor 정책, 구현 우선순위
