# Issue: .vital 파일의 Entity Identifier 문제

## 문제 요약

`.vital` 파일들이 개별적으로 처리되면서 `entity_identifier`가 NULL로 남아있고, `reasoning`이 파일마다 제각각임. 동일 데이터셋 내의 6,388개 파일들이 **서로 관련 없는 개별 엔티티**처럼 취급되고 있음.

---

## 현재 상태

### 데이터셋 구조 (Open_VitalDB_1.0.0)

```
Open_VitalDB_1.0.0/
├── clinical_data.csv          # 6,388개 case의 메타데이터 (caseid가 PK)
├── clinical_parameters.csv    # 임상 파라미터 정의
├── lab_data.csv               # 검사 결과 데이터
├── lab_parameters.csv         # 검사 파라미터 정의
├── track_names.csv            # vital 파일 내 트랙/채널 정보
└── vital_files/
    ├── 1.vital                # caseid=1의 생체신호 데이터
    ├── 2.vital                # caseid=2의 생체신호 데이터
    ├── 3.vital
    ├── ...
    └── 6388.vital             # 총 6,388개 파일
```

### file_catalog 테이블 현황

```
file_name     | filename_values      | entity_identifier_column | primary_entity
--------------+----------------------+--------------------------+---------------
3698.vital    | {'caseid': 3698}     | NULL                     | NULL
3249.vital    | {'caseid': 3249}     | NULL                     | NULL
4388.vital    | {'caseid': 4388}     | NULL                     | NULL
```

- `filename_values`에 caseid가 **이미 추출되어 있음**
- 그러나 `entity_identifier_column`, `primary_entity`는 NULL

### table_entities 테이블 현황

```sql
SELECT fc.file_name, te.entity_identifier, te.row_represents, te.confidence, te.reasoning
FROM table_entities te
JOIN file_catalog fc ON te.file_id = fc.file_id
WHERE fc.file_path LIKE '%.vital';
```

| file_name   | entity_identifier | row_represents     | confidence | reasoning (요약)                    |
|-------------|-------------------|--------------------|------------|-------------------------------------|
| 3249.vital  | NULL              | vital_sign_record  | 0.55       | "high-frequency physiologic monitoring data..." |
| 3698.vital  | NULL              | vital_sign_record  | 0.55       | "waveform channels, ECG, pleth..."  |
| 4388.vital  | NULL              | vital_sign_record  | 0.55       | "physiologic monitoring table..."   |

- **모든 파일의 `entity_identifier`가 NULL**
- `reasoning`이 파일마다 다름 (LLM이 각각 독립적으로 분석)
- 같은 데이터셋의 같은 형식임에도 일관성 없음

---

## 문제점 분석

### 1. 파일 단위 개별 처리의 한계

현재 파이프라인은 각 파일을 **독립적으로** 분석:

```
파일 A → LLM 분석 → entity_identifier 추론 시도 → NULL (컬럼 없음)
파일 B → LLM 분석 → entity_identifier 추론 시도 → NULL (컬럼 없음)
파일 C → LLM 분석 → entity_identifier 추론 시도 → NULL (컬럼 없음)
...
```

`.vital` 파일은 시계열 데이터라 **파일 내부**에 `caseid` 컬럼이 없음. caseid는 **파일명** 자체에 인코딩되어 있음.

### 2. 파일명 기반 Entity 인식 부재

`filename_values: {'caseid': 3249}`로 caseid를 **이미 추출**했음에도:
- 이 값이 `entity_identifier`로 연결되지 않음
- LLM이 "컬럼에서 entity identifier를 찾을 수 없다"고 판단

### 3. 메타데이터 CSV와의 관계 미인식

```
clinical_data.csv (caseid=1,2,3,...,6388)
        ↓
    연결 없음
        ↓
1.vital, 2.vital, 3.vital, ..., 6388.vital
```

`clinical_data.csv`의 `caseid` 컬럼과 `.vital` 파일명의 caseid가 **동일한 entity를 가리킴**을 인식하지 못함.

### 4. 반복적이고 비효율적인 LLM 호출

6,388개 파일 각각에 대해:
- LLM이 동일한 분석을 수행
- 동일한 결론 (`entity_identifier=NULL`) 도출
- 약간씩 다른 `reasoning` 생성

→ **불필요한 LLM 비용 및 시간 낭비**

### 5. 향후 쿼리/분석의 어려움

```sql
-- "caseid 3249의 모든 데이터를 가져와라"
-- 현재 불가능:
SELECT * FROM ... WHERE entity_identifier = 'case:3249';
-- 결과: 0건 (모두 NULL이므로)
```

entity_identifier가 NULL이면:
- case 기반 데이터 통합 불가
- clinical_data와 vital 데이터 조인 불가
- "환자 X의 모든 데이터" 쿼리 불가

---

## 영향 범위

| 항목 | 현재 상태 | 예상 문제 |
|------|----------|-----------|
| `.vital` 파일 수 | 6,388개 | 모두 entity_identifier NULL |
| LLM 호출 | 파일당 1회 | 6,388회 중복 분석 |
| 메타데이터 연결 | 없음 | clinical_data와 조인 불가 |
| 데이터 활용 | 개별 파일만 접근 가능 | case 단위 통합 분석 불가 |

---

## 관련 코드 위치

1. **파일명 값 추출**: `src/agents/nodes/directory_catalog.py`
   - `filename_values: {'caseid': 3249}` 생성하는 부분

2. **Entity 분류**: `src/agents/nodes/catalog.py` 또는 `file_classification/node.py`
   - table_entities 테이블에 entity_identifier 저장하는 부분

3. **테이블 스키마**:
   - `file_catalog`: `filename_values`
   - `table_entities`: `entity_identifier`, `row_represents`, `reasoning`

---

## 핵심 질문

1. **파일명에서 추출한 값**(`filename_values.caseid`)을 어떻게 `entity_identifier`로 연결할 것인가?

2. **동일 패턴의 대량 파일들**을 개별 처리할 것인가, 그룹으로 처리할 것인가?

3. **메타데이터 CSV**와의 관계를 어느 단계에서, 어떻게 인식할 것인가?

4. 이러한 **시그널/시계열 파일들**의 entity 관리는 테이블형 데이터와 **동일한 방식**으로 해야 하는가?

---

## 참고: 다른 데이터셋의 유사 패턴

```
physionet.org/
├── mimic-iv-waveform/
│   ├── p100/
│   │   ├── p10000032/
│   │   │   ├── 81739927.hea
│   │   │   └── 81739927.dat
│   │   └── p10000084/
│   │       ├── 83411188.hea
│   │       └── 83411188.dat
```

- 디렉토리 구조에 `subject_id` (p10000032)가 인코딩
- 파일명에 `record_id` (81739927)가 인코딩
- `.hea`와 `.dat`가 쌍으로 존재

→ VitalDB와 유사한 "파일명/경로 = entity identifier" 패턴

