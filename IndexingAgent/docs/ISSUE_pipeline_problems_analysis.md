# Pipeline 문제 분석 보고서

> 작성일: 2026-01-03
> 분석 대상: Full Pipeline 테스트 실행 결과

---

## 1. 개요

전체 파이프라인 테스트 실행 후 발견된 문제점들을 분석합니다.

**테스트 환경**:
- 데이터셋: Open VitalDB
- 파일 수: 8개 (metadata 3개, data 5개)
- 총 컬럼 수: 342개
- 총 파라미터 수: 307개
- 실행 시간: 17.9분

---

## 2. 발견된 문제 목록

| ID | 문제 | 심각도 | 발생 노드 | 상태 |
|----|------|--------|----------|------|
| P1 | NoneType 에러로 노드 실패 | 🔴 Critical | relationship_inference | 수정됨 |
| P2 | Parameter Semantic 절반만 업데이트 | 🔴 Critical | parameter_semantic | 수정됨 |
| P3 | Metadata 컬럼 role 미설정 | 🟡 Medium | metadata_semantic | 미해결 |
| P4 | Vital 파일 entity_identifier 미식별 | 🟡 Medium | entity_identification | 미해결 |
| P5 | filename_values 매칭 실패 | 🟡 Medium | directory_pattern | 미해결 |
| P6 | TEXT 파일 metadata 미지원 | 🟠 Design | metadata_semantic | 미구현 |

---

## 3. 문제 상세 분석

### 3.1 [P1] NoneType 에러 - relationship_inference

**증상**:
```
❌ [relationship_inference] Error: 'NoneType' object has no attribute 'lower'
File: relationship_inference/node.py, line 574
```

**발생 위치**:
```python
if 'id' in matched_column.lower() or 'case' in matched_column.lower():
```

**근본 원인**:
- `directory_pattern` 노드에서 filename 패턴 분석 시 `matched_column`이 `None`으로 설정될 수 있음
- `matched_info.get('matched_column', key)`에서 값이 명시적으로 `None`이면 기본값이 적용되지 않음
- `None.lower()` 호출 시 AttributeError 발생

**영향 범위**:
- Neo4j FILENAME_VALUE 엣지 생성 실패
- 파이프라인은 계속 진행되나 일부 관계 누락

---

### 3.2 [P2] Parameter Semantic 절반만 업데이트

**증상**:
```
Parameter 테이블 Match Status:
   matched: 154
   null: 152      ← 307개 중 절반이 미처리
   null_from_llm: 1
```

**발생 위치**:
```python
# execute() 메서드
param_key_to_id = {p['param_key']: p['param_id'] for p in parameters}
```

**근본 원인**:
- **동일한 `param_key`가 여러 파일에 존재**하는 상황을 고려하지 않음
- Dict comprehension에서 동일 키는 마지막 값만 유지됨

**예시**:
```
파일별 param_key "Solar8000/HR":
- 3249.vital → param_id = 1
- 3698.vital → param_id = 2  
- 4388.vital → param_id = 3

결과: param_key_to_id["Solar8000/HR"] = 3 (마지막 것만 남음)
```

**데이터 분석**:
- 3개 vital 파일에 공통 컬럼 약 70개 존재
- 실제 고유 param_key 수 ≈ 155개
- 307 - 155 = 152개가 업데이트 누락 (일치!)

**영향 범위**:
- `parameter` 테이블의 semantic 정보 불완전
- Neo4j ConceptCategory 노드 생성에 영향
- 하위 노드(relationship_inference, ontology_enhancement)의 데이터 품질 저하

---

### 3.3 [P3] Metadata 컬럼 role 미설정

**증상**:
```
Column Role Distribution:
   parameter_name: 286
   attribute: 26
   null: 13       ← metadata 파일 컬럼들
   ...
```

**발생 위치**:
```python
# column_classification/node.py
data_files = state.get("data_files", [])  # metadata 파일 제외
for file_path in data_files:
    # 컬럼 분류...
```

**근본 원인**:
- `column_classification` 노드는 **data 파일만** 처리하도록 설계됨
- `metadata_files`는 별도 처리 대상 (`metadata_semantic` 노드)
- 두 노드 간 `column_role` 설정에 대한 책임 분담이 명확하지 않음

**영향받는 파일**:
| 파일 | 컬럼 수 | column_role |
|------|---------|-------------|
| clinical_parameters.csv | 4 | NULL |
| lab_parameters.csv | 5 | NULL |
| track_names.csv | 4 | NULL |

**영향 범위**:
- 데이터 일관성 저하
- 쿼리/분석 시 metadata 컬럼 구분 어려움

---

### 3.4 [P4] Vital 파일 entity_identifier 미식별

**증상**:
```
Entity Identification Results:
🟡 3249.vital
   row_represents: vital_sign_record
   entity_identifier: (none)     ← 식별자 없음
   confidence: 0.55              ← 낮은 신뢰도

🟢 clinical_data.csv
   entity_identifier: caseid     ← 정상 식별
   confidence: 0.90
```

**근본 원인**:
- Vital 파일에는 **caseid 컬럼이 존재하지 않음**
- caseid는 **파일명에서 추출** (예: `3249.vital` → caseid=3249)
- `entity_identification` 노드는 컬럼 기반으로만 identifier 탐색
- `filename_values`를 identifier 후보로 고려하지 않음

**데이터 구조 분석**:
```
clinical_data.csv:
   - 컬럼: caseid, age, sex, height, weight, ...
   - caseid가 PK 역할

vital 파일:
   - 컬럼: EVENT, Solar8000/HR, BIS/BIS, ... (caseid 없음!)
   - 파일명이 caseid: 3249.vital, 3698.vital, 4388.vital
```

**영향 범위**:
- vital 파일과 clinical_data.csv 간 관계 추론 품질 저하
- Row-level 조인이 불가능 (어떤 row가 어떤 case인지 불명확)

---

### 3.5 [P5] filename_values 매칭 실패

**증상**:
```
📋 Directories with Patterns:
   📁 vital_files
      Pattern: {caseid:integer}.vital
      matched_column: None           ← 매칭 실패
      match_confidence: 0.2          ← 매우 낮은 신뢰도
```

**발생 위치**:
- `directory_pattern` 노드의 LLM 응답

**근본 원인**:
- LLM이 패턴을 인식했으나 (`caseid:integer`)
- data_dictionary에서 매칭할 컬럼을 찾지 못함
- 실제로 `clinical_parameters.csv`에 `caseid` 정의가 존재하지만 LLM이 연결하지 못함

**프롬프트 컨텍스트 부족 추정**:
- data_dictionary 전체가 아닌 일부만 전달되었을 가능성
- 또는 `caseid`가 parameter가 아닌 identifier로 분류되어 dictionary에 없을 가능성

**영향 범위**:
- P1 에러의 원인이 됨 (matched_column = None)
- vital 파일 ↔ clinical_data.csv 관계 설정에 영향

---

## 4. Metadata 처리 방식 분석 및 논의

### 4.1 현재 Metadata 처리 아키텍처

```
[file_classification]
        ↓
    metadata 파일 식별
        ↓
[metadata_semantic]
        ↓
    CSV/TSV/XLSX 파싱
        ↓
    LLM으로 컬럼 역할 추론
    (key_column, desc_column, unit_column, extra_columns)
        ↓
    data_dictionary 테이블 저장
```

### 4.2 현재 지원 파일 형식

| 형식 | 지원 여부 | 처리 방식 |
|------|----------|----------|
| CSV | ✅ 지원 | pandas DataFrame 파싱 |
| TSV | ✅ 지원 | pandas DataFrame 파싱 |
| XLSX/XLS | ✅ 지원 | pandas DataFrame 파싱 |
| **TXT** | ❌ 미지원 | "추후 지원" TODO |
| JSON | ❌ 미지원 | - |
| PDF | ❌ 미지원 | - |

### 4.3 현재 data_dictionary 스키마

```sql
CREATE TABLE data_dictionary (
    dict_id UUID PRIMARY KEY,
    
    -- 출처 정보
    source_file_id UUID REFERENCES file_catalog(file_id),
    source_file_name VARCHAR(255),
    
    -- 핵심 정보 (key-desc-unit)
    parameter_key VARCHAR(255) NOT NULL,  -- 파라미터 이름
    parameter_desc TEXT,                   -- 설명
    parameter_unit VARCHAR(100),           -- 단위
    
    -- 추가 메타정보 (JSONB)
    extra_info JSONB DEFAULT '{}',
    
    -- LLM 분석 정보
    llm_confidence FLOAT,
    
    UNIQUE(source_file_id, parameter_key)
);
```

### 4.4 [P6] TEXT 파일 Metadata 미지원 문제

**현재 상태**:
```python
# metadata_semantic/node.py
if ext == 'csv':
    df = pd.read_csv(file_path)
elif ext == 'tsv':
    df = pd.read_csv(file_path, sep='\t')
elif ext in ['xlsx', 'xls']:
    df = pd.read_excel(file_path)
else:
    self.log(f"⚠️ Unsupported file type: {ext}", indent=1)
    return []  # ← TXT는 여기서 무시됨
```

**문제점**:

1. **구조화되지 않은 TXT 파일 처리 불가**
   - 의료 데이터셋은 종종 README.txt, DESCRIPTION.txt 형태의 문서 포함
   - 이 문서들에 중요한 파라미터 설명이 있을 수 있음

2. **다양한 TXT 포맷 존재**
   ```
   # 형식 1: 테이블 형태
   HR    Heart Rate    bpm
   BP    Blood Pressure    mmHg
   
   # 형식 2: Key-Value 형태
   HR: Heart Rate (bpm) - 심박수를 나타냄
   BP: Blood Pressure (mmHg) - 혈압을 나타냄
   
   # 형식 3: 자유 형식 문서
   ## Parameters
   - HR stands for Heart Rate, measured in beats per minute (bpm)
   - BP represents Blood Pressure...
   ```

3. **LLM 의존도 증가**
   - TXT 파싱은 정형화가 어려워 LLM에 크게 의존해야 함
   - 토큰 비용 증가
   - 일관성 보장 어려움

### 4.5 Parameter 설명서 제공 필요성

**현재**: data_dictionary → parameter_semantic에서 매칭

```
data_dictionary                    parameter
┌─────────────────────┐            ┌─────────────────────┐
│ parameter_key: HR   │ ──매칭──→ │ param_key: Solar8000/HR │
│ parameter_desc: ... │            │ semantic_name: ...      │
│ parameter_unit: bpm │            │ concept_category: ...   │
└─────────────────────┘            └─────────────────────┘
```

**문제점**:

1. **1:1 매칭 한계**
   - dictionary의 `HR`이 data의 `Solar8000/HR`과 매칭되는지 LLM이 추론해야 함
   - 다양한 naming convention 존재 (HR, HeartRate, heart_rate, Solar8000/HR)

2. **컬럼별 설명 조회 API 부재**
   - "Solar8000/HR 컬럼이 뭔가요?" 질문에 답하려면?
   - 현재: parameter 테이블 조회 → dict_entry_id로 dictionary 조회
   - 누락된 매칭이 있으면 설명 불가

3. **계층적 설명 미지원**
   - `Solar8000/HR`은 `Solar8000` 장비의 `HR` 측정값
   - 장비 레벨 설명 + 파라미터 레벨 설명이 모두 필요할 수 있음

### 4.6 논의 포인트

#### Q1. TXT 파일 처리 방안

| 옵션 | 설명 | 장단점 |
|------|------|--------|
| A | LLM으로 전체 TXT 파싱 | ✅ 유연함, ❌ 비용/일관성 |
| B | 정규표현식 + Rule-based | ✅ 빠름, ❌ 포맷별 규칙 필요 |
| C | 하이브리드 (규칙 → LLM fallback) | ✅ 균형, ❌ 복잡도 증가 |
| D | TXT는 미지원 (CSV 변환 권장) | ✅ 단순, ❌ 사용자 부담 |

#### Q2. parameter 설명 조회 구조

| 옵션 | 설명 |
|------|------|
| A | 현재 유지 (parameter ↔ dictionary 매칭) |
| B | parameter 테이블에 description 필드 직접 복사 |
| C | 별도 API 레이어에서 JOIN 처리 |

#### Q3. Metadata 컬럼 역할 책임

| 옵션 | 담당 노드 |
|------|----------|
| A | metadata_semantic에서 column_role 설정 |
| B | column_classification 확장 (metadata 포함) |
| C | 별도 post-processing 노드 추가 |

---

## 5. 문제 간 연관 관계

```
[P5] filename_values 매칭 실패
        │
        ▼ matched_column = None
[P1] NoneType 에러 ───────────────┐
                                  │
[P4] Vital entity_identifier 미식별 │
        │                         │
        ▼                         ▼
    관계 추론 품질 저하 ◄──────────┘
        │
        ▼
[P2] Parameter Semantic 절반 누락 (별개 원인)
        │
        ▼
    Neo4j Ontology 불완전

[P3] Metadata column_role null (별개 원인)
        │
        ▼
    데이터 일관성 저하

[P6] TEXT metadata 미지원 (설계 이슈)
        │
        ▼
    일부 데이터셋 metadata 누락 가능성
```

---

## 6. 데이터 정합성 분석

### 6.1 Parameter 테이블 현황

| 지표 | 값 | 비고 |
|------|-----|------|
| 총 파라미터 | 307 | |
| semantic 설정됨 | 154 | 50% |
| semantic NULL | 152 | P2로 인해 |
| dict_match_status = matched | 154 | |
| dict_match_status = null | 152 | |

### 6.2 Column 테이블 현황

| 지표 | 값 | 비고 |
|------|-----|------|
| 총 컬럼 | 342 | |
| column_role 설정됨 | 329 | 96% |
| column_role NULL | 13 | P3으로 인해 |

### 6.3 Entity 테이블 현황

| 파일 | entity_identifier | confidence |
|------|-------------------|------------|
| clinical_data.csv | caseid | 0.90 ✓ |
| lab_data.csv | (none) | 0.90 |
| 3249.vital | (none) | 0.55 ⚠️ |
| 3698.vital | (none) | 0.55 ⚠️ |
| 4388.vital | (none) | 0.55 ⚠️ |

---

## 7. 아키텍처적 관찰

### 7.1 노드 간 데이터 흐름 문제

현재 파이프라인에서 발견된 설계상 이슈:

1. **책임 분담 불명확**: `column_role` 설정을 누가 담당하는지 (column_classification vs metadata_semantic)

2. **파일명 기반 identifier 미지원**: entity_identification이 컬럼 기반만 지원

3. **중복 param_key 처리 미고려**: 동일 param_key가 여러 파일에 존재하는 시나리오

4. **filename_values ↔ data_dictionary 연결 약함**: 패턴 추출과 dictionary 매칭이 분리되어 있음

5. **비정형 metadata 미지원**: TXT, PDF 등 문서 형태 metadata 처리 불가

### 7.2 데이터 모델 관찰

- `parameter` 테이블의 `(file_id, param_key)` 조합이 unique
- 하지만 semantic 분석 시 `param_key`만으로 매핑하여 중복 발생
- vital 파일의 caseid는 컬럼이 아닌 파일명에 존재하나, 이를 표현할 모델 부재
- data_dictionary는 정형 metadata만 지원 (key-desc-unit 구조)

---

## 8. 요약

| 카테고리 | 문제 수 | Critical | Medium | Design |
|----------|---------|----------|--------|--------|
| 런타임 에러 | 1 | 1 | 0 | 0 |
| 데이터 정합성 | 3 | 1 | 2 | 0 |
| 설계 이슈 | 2 | 0 | 1 | 1 |
| **합계** | **6** | **2** | **3** | **1** |

**핵심 문제**:
1. 동일 param_key의 다중 파일 존재 시 업데이트 누락 (P2)
2. 파일명 기반 identifier가 entity로 인식되지 않음 (P4)
3. 노드 간 column_role 책임 분담 불명확 (P3)
4. 비정형 metadata(TXT 등) 처리 미지원 (P6)

---

## 9. 추가 논의 필요 사항

1. **TXT metadata 파일 처리 전략 결정**
2. **parameter 설명 조회 API 설계**
3. **metadata 컬럼 역할 설정 책임 노드 결정**
4. **filename_values와 entity_identifier 연결 방안**
