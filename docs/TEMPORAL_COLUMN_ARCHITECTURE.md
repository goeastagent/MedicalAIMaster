# Temporal Column Architecture: 문제 분석 및 해결 방안

## 1. 문제 요약

### 핵심 문제
**Signal 데이터의 시간 컬럼("Time")이 메타데이터로 관리되지 않아, LLM 코드 생성 시 하드코딩에 의존하고 있음**

```
현재 상태:
  DataContext._apply_temporal_filter() 내부:
    if "Time" in signals_df.columns:  ← 하드코딩!
        ...
```

### 영향 범위
- VitalDB 이외의 데이터셋에서 동작 불가
- 시간 컬럼 이름이 다른 경우 (timestamp, datetime, dt 등) 실패
- 범용적인 의료 데이터 분석 플랫폼으로서의 확장성 제한

---

## 2. 배경: 두 종류의 "시간"

의료 데이터 분석에서 "시간"은 두 가지 의미를 가집니다:

### 2.1 Cohort 레벨 시간 (메타데이터)
```
clinical_data.csv:
┌─────────┬─────────┬─────────┬──────────┐
│ caseid  │ opstart │ opend   │ diagnosis│
├─────────┼─────────┼─────────┼──────────┤
│ 1       │ 100     │ 500     │ ...      │
│ 2       │ 150     │ 600     │ ...      │
└─────────┴─────────┴─────────┴──────────┘

역할: "언제" 분석할 것인가를 정의
예시: "수술 중" = opstart ~ opend 구간
```

**현재 상태**: ✅ ExtractionAgent가 `temporal_context`로 처리
```python
temporal_context: {
    "type": "procedure_window",
    "start_column": "opstart",   # ← DB에서 조회
    "end_column": "opend",       # ← DB에서 조회
}
```

### 2.2 Signal 레벨 시간 (데이터 자체)
```
0001.vital → DataFrame:
┌───────┬──────┬───────┐
│ Time  │ HR   │ SpO2  │
├───────┼──────┼───────┤
│ 0     │ 72   │ 98    │
│ 1     │ 73   │ 97    │
│ ...   │ ...  │ ...   │
│ 600   │ 75   │ 99    │
└───────┴──────┴───────┘

역할: 데이터의 시간축 (각 측정값의 타임스탬프)
```

**현재 상태**: ❌ 메타데이터로 관리되지 않음

---

## 3. 근본 원인 분석

### 3.1 VitalDB 파일 구조의 특수성

```
┌─────────────────────────────────────────────────────────────────┐
│                    VitalDB .vital 파일                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  원본 파일 구조:                                                │
│  - 트랙 데이터만 저장 (HR, SpO2, ABP 등)                        │
│  - 시간 정보는 샘플링 레이트로 암시됨                            │
│  - "Time" 컬럼 없음!                                            │
│                                                                 │
│  Signal Processor 로드 시:                                      │
│  - resample_interval 기반으로 Time 컬럼 생성                    │
│  - df["Time"] = [i * resample_interval for i in range(max_len)]│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**shared/processors/signal.py (line 413-415):**
```python
df = pd.DataFrame({
    "Time": [i * resample_interval for i in range(max_len)]  # 생성!
})
```

### 3.2 IndexingAgent의 분석 범위

```
IndexingAgent가 분석하는 것:
  ✅ 원본 파일의 컬럼 (Solar8000/HR, BIS/BIS 등)
  ✅ 컬럼 역할 (column_role: parameter_name, identifier, timestamp 등)
  ✅ 의미론적 분류 (concept_category: Vital Signs, Hemodynamics 등)

IndexingAgent가 분석하지 않는 것:
  ❌ Signal Processor가 생성하는 컬럼 ("Time")
  ❌ 로드 과정에서 추가되는 메타데이터
```

### 3.3 메타데이터 저장소 현황

| 저장소 | 시간 컬럼 정보 | 상태 |
|--------|---------------|------|
| PostgreSQL `column_metadata` | `column_role = 'timestamp'` | ✅ Cohort만 |
| PostgreSQL `parameter` | `concept_category = 'Temporal'` | ❌ 없음 |
| PostgreSQL `file_group` | - | ❌ 시간 메타데이터 없음 |
| Neo4j `ConceptCategory` | - | ❌ Temporal 카테고리 없음 |
| Neo4j `Parameter` | - | ❌ Time 노드 없음 |

---

## 4. 현재 코드의 문제점

### 4.1 하드코딩된 시간 컬럼 참조

**shared/data/context.py:**
```python
def _apply_temporal_filter(self, signals_df, cohort_row):
    ...
    # 문제: "Time" 하드코딩
    if "Time" in signals_df.columns:
        return signals_df[
            (signals_df["Time"] >= start_sec) & 
            (signals_df["Time"] <= end_sec)
        ].copy()
```

**shared/data/analysis_context.py:**
```python
# 문제: 하드코딩된 패턴 리스트
DATETIME_COLUMN_PATTERNS = {
    'time', 'timestamp', 'datetime', ...
}
```

### 4.2 정보 흐름의 단절

```
IndexingAgent                ExtractionAgent              AnalysisContextBuilder
     │                            │                              │
     │  column_role=timestamp     │                              │
     │  (Cohort만)                │                              │
     ▼                            ▼                              ▼
  DB 저장 ──────────────────▶ temporal_context ──────────────▶ ???
                              (start/end만)                      │
                                                                 │
  Signal time column ────────────────────────────────────────────┘
  정보 없음!                                                (하드코딩 폴백)
```

---

## 5. 해결해야 하는 과제

### 5.1 [필수] Signal 시간 컬럼 메타데이터 관리

**과제**: Signal Processor가 생성하는 시간 컬럼 정보를 메타데이터로 관리

**요구사항**:
- Signal Group별 시간 컬럼 이름 저장
- 시간 단위 (seconds, milliseconds, datetime) 저장
- 생성 방식 (processor_generated, original) 저장

**저장 위치 후보**:
1. PostgreSQL `file_group.signal_time_config` (JSONB)
2. Neo4j `FileGroup` 노드 속성
3. PostgreSQL 새 테이블 `signal_time_metadata`

### 5.2 [필수] 정보 흐름 구축

**과제**: 시간 컬럼 정보가 IndexingAgent → ExtractionAgent → DataContext → AnalysisAgent로 흐르도록

```
목표 흐름:
  IndexingAgent
       │
       ▼
  file_group.signal_time_config = {
      "column_name": "Time",
      "unit": "seconds",
      "type": "processor_generated"
  }
       │
       ▼
  ExtractionAgent (SchemaContextBuilder)
       │
       ▼
  execution_plan.signal_source.temporal_alignment = {
      "cohort_start_column": "opstart",
      "cohort_end_column": "opend",
      "signal_time_column": "Time",  ← 추가
      "time_unit": "seconds"
  }
       │
       ▼
  DataContext._temporal_config.signal_time_column
       │
       ▼
  AnalysisContextBuilder (하드코딩 제거)
```

### 5.3 [필수] 하드코딩 제거

**제거 대상**:
1. `shared/data/context.py`: `if "Time" in signals_df.columns`
2. `shared/data/analysis_context.py`: `DATETIME_COLUMN_PATTERNS`
3. `shared/data/analysis_context.py`: `_detect_datetime_columns()` (패턴 매칭 방식)
4. `shared/data/context.py`: `_find_time_column()` (패턴 매칭 방식)

**대체 방식**:
```python
# Before (하드코딩)
if "Time" in signals_df.columns:
    ...

# After (메타데이터 활용)
signal_time_col = self._temporal_config.get("signal_time_column")
if signal_time_col and signal_time_col in signals_df.columns:
    ...
```

### 5.4 [선택] 범용 시간 관계 모델링

**과제**: Cohort 시간과 Signal 시간의 관계 정의

```python
temporal_relationship = {
    "type": "same_relative_axis",  # 또는 "absolute_datetime", "offset_based"
    "description": "Both use relative seconds from recording start",
    "conversion_required": False,
    "conversion_function": None  # 필요시 변환 함수 지정
}
```

**사용 사례**:
- VitalDB: Cohort(opstart/opend)와 Signal(Time) 모두 상대 초 단위 → 직접 비교 가능
- MIMIC: Cohort(admit_time)는 datetime, Signal(timestamp)도 datetime → 직접 비교 가능
- 혼합: Cohort는 datetime, Signal은 상대 초 → 변환 필요

---

## 6. 구현 계획

### Phase 1: 메타데이터 저장 구조 추가

**변경 파일**:
- `shared/database/schemas/file_group.py`: `signal_time_config` 컬럼 추가
- `shared/database/repositories/file_group_repository.py`: 조회/저장 메서드 추가

**스키마 변경**:
```sql
ALTER TABLE file_group ADD COLUMN signal_time_config JSONB DEFAULT '{}'::jsonb;

-- 예시 값:
-- {
--   "column_name": "Time",
--   "unit": "seconds",
--   "type": "processor_generated",
--   "description": "Generated by SignalProcessor using resample_interval"
-- }
```

### Phase 2: IndexingAgent 수정

**변경 파일**:
- `IndexingAgent/src/agents/nodes/file_grouping/node.py`: Signal Group 생성 시 시간 메타데이터 저장

**로직**:
```python
# Signal Group 생성 시
signal_time_config = {
    "column_name": "Time",  # Signal Processor 규칙
    "unit": "seconds",
    "type": "processor_generated"
}
file_group_repo.update_signal_time_config(group_id, signal_time_config)
```

### Phase 3: ExtractionAgent 수정

**변경 파일**:
- `ExtractionAgent/src/agents/context/schema_context_builder.py`: `get_signal_groups()`에 시간 컬럼 정보 포함
- `ExtractionAgent/src/agents/nodes/plan_builder/node.py`: `execution_plan`에 포함

### Phase 4: DataContext/AnalysisContextBuilder 수정

**변경 파일**:
- `shared/data/plan_parser.py`: `signal_time_column` 파싱
- `shared/data/context.py`: 하드코딩 제거, `_temporal_config` 활용
- `shared/data/analysis_context.py`: 패턴 매칭 제거, 메타데이터 활용

---

## 7. 검증 방법

### 7.1 단위 테스트
```python
def test_signal_time_column_from_metadata():
    """시간 컬럼이 메타데이터에서 올바르게 로드되는지 검증"""
    ctx = DataContext()
    ctx.load_from_plan(execution_plan_with_signal_time)
    
    assert ctx._temporal_config.get("signal_time_column") == "Time"
```

### 7.2 통합 테스트
```python
def test_temporal_filtering_with_metadata():
    """시간 필터링이 메타데이터 기반으로 동작하는지 검증"""
    # VitalDB 데이터셋
    result = run_pipeline("수술 중 심박수 평균")
    assert result.success
    
    # 다른 데이터셋 (시간 컬럼명이 다른 경우)
    result = run_pipeline_other_dataset("치료 중 혈압 평균")
    assert result.success
```

### 7.3 회귀 테스트
- 기존 VitalDB 분석 쿼리가 동일하게 동작하는지 확인
- `test_e2e_signal_segmentation_mean.py` 통과 여부

---

## 8. 향후 확장성

### 8.1 다양한 시간 표현 지원
```python
SUPPORTED_TIME_TYPES = {
    "processor_generated": "로드 시 생성 (VitalDB)",
    "original_column": "원본 파일에 존재",
    "index_based": "DataFrame 인덱스가 시간",
    "calculated": "다른 컬럼에서 계산"
}
```

### 8.2 시간 단위 변환
```python
TIME_UNIT_CONVERSIONS = {
    ("seconds", "milliseconds"): lambda x: x * 1000,
    ("milliseconds", "seconds"): lambda x: x / 1000,
    ("datetime", "seconds"): lambda x: x.timestamp(),
}
```

### 8.3 멀티 데이터셋 지원
- EDF 파일: `timestamp` 컬럼 (datetime)
- CSV 시계열: `dt` 컬럼 (datetime)
- 사용자 정의: 메타데이터로 지정

---

## 9. 의존성

### 영향받는 컴포넌트
1. **IndexingAgent**: 시간 메타데이터 저장 로직 추가
2. **ExtractionAgent**: 시간 컬럼 정보 조회 및 전달
3. **OrchestrationAgent**: 변경 없음 (DataContext가 처리)
4. **AnalysisAgent**: 코드 생성 프롬프트에 시간 컬럼 정보 포함
5. **DataContext**: 하드코딩 제거, 메타데이터 활용
6. **AnalysisContextBuilder**: 패턴 매칭 제거, 메타데이터 활용

### 데이터베이스 변경
- PostgreSQL: `file_group.signal_time_config` 컬럼 추가
- Neo4j: (선택) `FileGroup.signal_time_column` 속성 추가

---

## 10. 참고: 현재 코드 위치

| 파일 | 라인 | 내용 |
|------|------|------|
| `shared/processors/signal.py` | 413-415 | Time 컬럼 생성 |
| `shared/data/context.py` | 1360-1364 | 하드코딩된 Time 참조 |
| `shared/data/context.py` | 1370-1408 | `_find_time_column()` 패턴 매칭 |
| `shared/data/analysis_context.py` | 47-53 | `DATETIME_COLUMN_PATTERNS` |
| `shared/data/analysis_context.py` | 62-97 | `_detect_datetime_columns()` |
| `ExtractionAgent/src/agents/context/schema_context_builder.py` | 220-225 | Cohort temporal_columns 조회 |

---

*문서 작성일: 2026-01-11*
*작성자: AI Assistant*
*버전: 1.0*
