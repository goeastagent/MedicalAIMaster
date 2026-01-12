# Temporal Column Architecture: 문제 분석

## 1. 핵심 문제

**의료 데이터 분석에서 "시간" 정보를 어떻게 자동으로 파악하고 활용할 것인가?**

현재 시스템은 시간 관련 정보를 자동으로 파악하지 못해, 하드코딩에 의존하고 있음.

```python
# 현재 상태 (shared/data/context.py)
if "Time" in signals_df.columns:  # ← 하드코딩!
    ...
```

---

## 2. 의료 데이터에서 "시간"의 두 가지 의미

### 2.1 Cohort 레벨 시간 (메타데이터)

```
clinical_data.csv:
┌─────────┬─────────┬─────────┬──────────┐
│ caseid  │ opstart │ opend   │ diagnosis│
├─────────┼─────────┼─────────┼──────────┤
│ 1       │ 100     │ 500     │ ...      │
│ 2       │ 150     │ 600     │ ...      │
└─────────┴─────────┴─────────┴──────────┘

역할: "언제" 분석할 것인가 (시간 범위 정의)
예시: "수술 중" = opstart ~ opend 구간
```

- 원본 파일에 존재 ✅
- IndexingAgent가 인덱싱 ✅
- `column_role = 'timestamp'` 할당 가능 ✅
- `ConceptCategory = 'Timestamps'` 할당 가능 ✅

### 2.2 Signal 레벨 시간 (데이터 축)

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

역할: 각 측정값의 시간축 (x축)
```

- 원본 .vital 파일에는 "Time" 컬럼 없음 ❌
- SignalProcessor가 로드 시 생성 (processor-generated)
- IndexingAgent가 볼 수 없음 ❌
- 메타데이터로 관리되지 않음 ❌

---

## 3. VitalDB 데이터셋의 특수성

### 3.1 파일 구조

```
VitalDB 데이터셋
├── clinical_data.csv          # Cohort 메타데이터
│   └── opstart, opend 컬럼    # 시간 범위 정보 (상대 초)
│
└── 0001.vital ~ 6388.vital    # Signal 파일들
    └── 트랙 데이터만 저장      # HR, SpO2, ABP 등
    └── 시간 컬럼 없음!         # 샘플링 레이트로 암시
```

### 3.2 시간 정보 획득 방법

**방법 1**: clinical_data.csv에서 확인
```
caseid=1의 수술 시간:
  opstart = 100 (초)
  opend = 500 (초)
  → 400초 동안의 데이터 분석 필요
```

**방법 2**: .vital 파일 직접 열어서 확인
```python
# vitaldb 라이브러리로 파일 열기
vital_file = vitaldb.VitalFile("0001.vital")
# 트랙별 길이, 샘플링 레이트 등 확인
```

### 3.3 SignalProcessor의 Time 컬럼 생성

```python
# shared/processors/signal.py (line 413-415)
df = pd.DataFrame({
    "Time": [i * resample_interval for i in range(max_len)]
})
# resample_interval = 1 (기본값) → 1초 간격
```

**결과**: 모든 .vital 파일은 로드 후 "Time" 컬럼을 가짐 (0, 1, 2, ... 초)

---

## 4. ConceptCategory로 해결 가능한 것 vs 불가능한 것

### 4.1 현재 ConceptCategory 정의

```python
class ConceptCategory(str, Enum):
    TIMESTAMPS = 'Timestamps'  # "Date, time, datetime, duration"
    # ... 기타 카테고리
```

### 4.2 해결 가능한 영역 ✅

| 대상 | 예시 | 이유 |
|------|------|------|
| Cohort 시간 컬럼 | `opstart`, `opend`, `admit_time` | 원본 파일에 존재, 인덱싱됨 |
| CSV의 datetime 컬럼 | `timestamp`, `datetime`, `date` | 원본 파일에 존재, 인덱싱됨 |
| Long-format의 시간 컬럼 | `measurement_time` | 원본 파일에 존재, 인덱싱됨 |

**동작 방식**:
1. IndexingAgent가 컬럼 분석
2. `column_role = 'timestamp'` 또는 `ConceptCategory = 'Timestamps'` 할당
3. ExtractionAgent가 이 정보 조회하여 `temporal_context` 구성
4. DataContext가 시간 필터링에 활용

### 4.3 해결 불가능한 영역 ❌

| 대상 | 예시 | 이유 |
|------|------|------|
| Processor 생성 컬럼 | .vital의 "Time" | 원본에 없음, 로드 시 생성 |
| 암시적 시간 정보 | 샘플링 레이트 | 파일 메타데이터, DB 미저장 |
| Cohort-Signal 시간 관계 | opstart vs Time | 두 시간의 연결 관계 미정의 |

---

## 5. 현재 정보 흐름의 단절

```
┌─────────────────────────────────────────────────────────────────────┐
│                        IndexingAgent                                 │
├─────────────────────────────────────────────────────────────────────┤
│  clinical_data.csv 분석:                                            │
│    ✅ opstart → column_role: timestamp, ConceptCategory: Timestamps │
│    ✅ opend   → column_role: timestamp, ConceptCategory: Timestamps │
│                                                                      │
│  .vital 파일 분석:                                                   │
│    ✅ Solar8000/HR → ConceptCategory: Vital Signs                   │
│    ❌ "Time" 컬럼 → 인덱싱 불가 (원본에 없음)                        │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       ExtractionAgent                                │
├─────────────────────────────────────────────────────────────────────┤
│  temporal_context 구성:                                              │
│    ✅ start_column: "opstart"  (DB에서 조회)                        │
│    ✅ end_column: "opend"      (DB에서 조회)                        │
│    ❌ signal_time_column: ???  (정보 없음)                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    SignalProcessor (런타임)                          │
├─────────────────────────────────────────────────────────────────────┤
│  .vital 파일 로드:                                                   │
│    → "Time" 컬럼 생성 (0, 1, 2, ... 초)                             │
│    → 이 정보는 어디에도 기록되지 않음                                │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         DataContext                                  │
├─────────────────────────────────────────────────────────────────────┤
│  시간 필터링 시도:                                                   │
│    opstart=100, opend=500 으로 필터링하려면                          │
│    Signal DataFrame의 어떤 컬럼을 사용해야 하는가?                   │
│                                                                      │
│    ❌ 현재: if "Time" in df.columns  ← 하드코딩                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. 문제의 본질

### 6.1 두 시간 체계의 연결

```
Cohort 시간 체계          Signal 시간 체계
─────────────────        ─────────────────
opstart = 100 (초)       Time = 0, 1, 2, ... (초)
opend = 500 (초)         
                    
        │                        │
        └────────────────────────┘
                  연결?
```

**질문**: `opstart=100`일 때, Signal의 `Time=100`인 행을 찾아야 하는가?

**VitalDB의 경우**: 예, 둘 다 "기록 시작으로부터의 상대 초"로 동일한 기준

**다른 데이터셋**: 다를 수 있음
- MIMIC: Cohort는 datetime, Signal도 datetime → 직접 비교 가능
- 혼합: Cohort는 datetime, Signal은 상대 초 → 변환 필요

### 6.2 자동 분석을 위해 필요한 정보

LLM이나 시스템이 자동으로 시간 기반 분석을 하려면:

1. **Signal 데이터의 시간 컬럼 이름**
   - VitalDB: "Time" (processor 생성)
   - 다른 데이터셋: "timestamp", "datetime", etc.

2. **시간 단위**
   - 초(seconds), 밀리초(milliseconds), datetime

3. **Cohort-Signal 시간 관계**
   - 동일 기준 (직접 비교 가능)
   - 변환 필요 (오프셋, 단위 변환 등)

4. **시간 범위 컬럼의 의미**
   - opstart/opend: 수술 시작/종료
   - admit_time/discharge_time: 입원/퇴원
   - 사용자 정의 구간

---

## 7. 하드코딩 현황

| 파일 | 라인 | 하드코딩 내용 |
|------|------|--------------|
| `shared/data/context.py` | 1360-1364 | `if "Time" in signals_df.columns` |
| `shared/data/context.py` | 1370-1408 | `_find_time_column()` 패턴 매칭 |
| `shared/data/analysis_context.py` | 47-53 | `DATETIME_COLUMN_PATTERNS` |
| `shared/data/analysis_context.py` | 62-97 | `_detect_datetime_columns()` |

---

## 8. 정리: 해결해야 할 과제

### 8.1 필수 과제

1. **Signal 시간 컬럼 정보 전달**
   - Processor가 생성하는 시간 컬럼 이름/단위를 어떻게 전달할 것인가?

2. **Cohort-Signal 시간 연결**
   - 두 시간 체계가 어떤 관계인지 어떻게 정의할 것인가?

3. **하드코딩 제거**
   - 메타데이터 기반으로 동적 처리

### 8.2 고려 사항

- ConceptCategory "Timestamps"는 Cohort 레벨에서만 유효
- Signal 시간은 Processor 설정에 의존 (결정론적)
- 파일 타입별로 시간 처리 방식이 다름

---

## 9. 현재 코드 참조

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| SignalProcessor | `shared/processors/signal.py` | Time 컬럼 생성 |
| DataContext | `shared/data/context.py` | 시간 필터링 (하드코딩) |
| AnalysisContextBuilder | `shared/data/analysis_context.py` | 시간 컬럼 탐지 (패턴 매칭) |
| SchemaContextBuilder | `ExtractionAgent/src/agents/context/` | temporal_context 구성 |
| ConceptCategory | `shared/models/enums.py` | Timestamps 카테고리 정의 |

---

## 10. 해결 방향: Knowledge Layer

### 10.1 접근 방식

**점진적 학습(Progressive Learning)** 기반으로 해결:
- 한번에 모든 메타데이터를 구축하지 않음
- 분석 과정에서 지식을 축적
- 사용자 피드백으로 지식 확장

### 10.2 핵심 아이디어

```
첫 번째 분석:
  System: Signal 시간 컬럼이 뭐지? → 모름
  User: "Time 컬럼이야"
  System: ✅ 분석 완료 + 지식 저장

두 번째 분석:
  System: 이전에 배운 지식 활용 → "Time" 자동 적용
```

### 10.3 구현: Neo4j Knowledge 노드

Neo4j 온톨로지에 `Knowledge` 노드를 추가하여 학습된 지식을 저장:

```cypher
(:Knowledge {
    type: "time_column",
    value: {column_name: "Time", unit: "seconds"},
    source: "user_feedback"
})-[:APPLIES_TO]->(FileGroup)
```

**범위별 우선순위**: RowEntity > FileGroup > Dataset

### 10.4 상세 설계

👉 **[ONTOLOGY_KNOWLEDGE_EXTENSION.md](./ONTOLOGY_KNOWLEDGE_EXTENSION.md)** 참조

---

## 11. 관련 문서

- [ONTOLOGY_KNOWLEDGE_EXTENSION.md](./ONTOLOGY_KNOWLEDGE_EXTENSION.md) - Knowledge Layer 상세 설계
- [IndexingAgent_ARCHITECTURE.md](./IndexingAgent_ARCHITECTURE.md) - IndexingAgent 전체 구조
- [ExtractionAgent_ARCHITECTURE.md](./ExtractionAgent_ARCHITECTURE.md) - ExtractionAgent 구조

---

*문서 작성일: 2026-01-12*
*상태: 문제 정의 완료, 해결책 설계 완료 ([ONTOLOGY_KNOWLEDGE_EXTENSION.md](./ONTOLOGY_KNOWLEDGE_EXTENSION.md))*
