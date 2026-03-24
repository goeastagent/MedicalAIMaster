# Semantic Value Accuracy (SVA) 평가 데이터셋

VitalAgent의 **시맨틱 파라미터 해석 능력**과 **구조적 파이프라인 우위**를 검증하기 위한 전용 평가 데이터셋 설계 문서입니다.

---

## 1. 개요 (Overview)

### 1-1. 평가 목적

기존 ValueAccuracy 평가는 질의에 정확한 track 이름(e.g., `` `Solar8000/HR` ``)을 백틱으로 포함하여 제공하기 때문에, VitalAgent와 Claude Code CLI 모두 단순한 코드 생성 능력만 시험받는다. 이 조건에서는 VitalAgent의 핵심 강점인 **ExtractionAgent의 시맨틱 파라미터 해석**, **코호트-시그널 크로스 조인**, **Cross-Device 우선순위 결정** 등이 전혀 활용되지 않는다.

SVA는 이 문제를 해결하기 위해, **track 이름을 포함하지 않는 시맨틱 질의**를 사용하여 다음을 측정한다:

1. **Parameter Resolution 정확도**: 자연어 임상 표현 → 올바른 `param_key` 매핑 능력
2. **Cross-Device 판별 능력**: 동일 생리학적 파라미터가 여러 장비에 존재할 때 적절한 소스 선택
3. **Cohort-Signal Join 능력**: 코호트 메타데이터(CSV)와 시그널 데이터(.vital) 연계 분석
4. **Ontology 기반 탐색 능력**: 카테고리/관계 기반의 복합 질의 처리
5. **최종 수치 정확도**: 올바른 파라미터를 사용했을 때의 값 일치 여부

### 1-2. 기존 ValueAccuracy와의 차이점

| 항목 | ValueAccuracy (기존) | SVA (신규) |
| :--- | :--- | :--- |
| **질의에 track 이름** | 포함 (`` `Solar8000/HR` ``) | **미포함** (임상적/시맨틱 표현만) |
| **파라미터 해석** | 불필요 (이미 제공됨) | **필수** (에이전트가 직접 해석) |
| **코호트 데이터 활용** | 미사용 | **사용** (CSV 필터링 → 시그널 조인) |
| **Cross-Device 판별** | 불필요 | **필수** (동일 개념, 다중 소스) |
| **채점 방식** | 단일 Layer (값 일치) | **3-Layer** (해석 + 실행 + 값) |
| **카테고리** | calculation, conditional, adversarial | semantic, cross-device, cohort-join, ontology, adversarial |
| **Claude CLI 난이도** | 낮음 (코드 생성만) | **높음** (해석 + 탐색 + 코드 생성) |

### 1-3. 왜 별도 데이터셋이 필요한가

현재 ValueAccuracy의 결과(`VitalAgent 94% vs Claude CLI 92%`)는 VitalAgent의 구조적 가치를 증명하지 못한다. 2% 차이는 통계적으로 유의하지 않으며, 이는 양쪽 모두 "주어진 track 이름으로 코드를 생성"하는 동일한 작업을 수행하기 때문이다.

VitalAgent가 투자한 **오프라인 인덱싱**(IndexingAgent), **시맨틱 해석**(ExtractionAgent), **온톨로지 구축**(Neo4j), **코호트-시그널 연계**(DataContext)의 가치를 정량적으로 증명하려면, 이 구성요소들이 **필수적으로 동작해야만** 정답을 낼 수 있는 질의가 필요하다.

---

## 2. 소스 데이터 정의 (Source Data)

### 2-1. VitalDB 원천 데이터

```
IndexingAgent/data/raw/Open_VitalDB_1.0.0/
├── vital_files/
│   ├── 0001.vital ~ 6384.vital    ← 6,384개 수술 케이스 생체신호 (케이스당 1파일)
├── clinical_data.csv               ← 케이스별 수술·마취 임상 메타데이터
└── lab_data.csv                    ← 케이스별 시계열 검사 결과
```

SVA 데이터셋은 기존 ValueAccuracy와 동일하게 3개 케이스(`0001`, `0002`, `0009`)를 대상으로 하되, 코호트-시그널 조인 카테고리에서는 `clinical_data.csv`의 해당 케이스 행도 함께 사용한다.

### 2-2. `track_names.csv` — VitalDB 공식 파라미터 레퍼런스

SVA 데이터셋 생성의 핵심 레퍼런스는 PostgreSQL `parameter` 테이블(IndexingAgent가 구축)이 아닌, VitalDB 공식 배포 파일인 `track_names.csv`를 사용한다. 이 파일은 VitalDB Open Dataset에 포함된 **모든 시그널 파라미터의 정의**를 담고 있다.

**파일 위치**: `IndexingAgent/data/raw/Open_VitalDB_1.0.0/track_names.csv`

**총 196개 파라미터** (6개 장비 + 6개 보조 장비)

| 컬럼 | 설명 | 예시 |
| :--- | :--- | :--- |
| `Parameter` | 장비/파라미터 형식의 고유 식별자 | `Solar8000/HR` |
| `Description` | VitalDB 공식 영문 설명 | `Heart rate` |
| `Type/Hz` | 데이터 유형과 샘플링 레이트 | `N` (Numeric, 1Hz), `W/500` (Waveform, 500Hz) |
| `Unit` | 측정 단위 | `/min`, `mmHg`, `%`, `mL` |

**장비별 파라미터 분포:**

| 장비 | 유형 | 파라미터 수 | 대표 파라미터 |
| :--- | :--- | :---: | :--- |
| `SNUADC` | 고해상도 파형 (500Hz) | 6 | `ART`, `ECG_II`, `ECG_V5`, `PLETH` |
| `Solar8000` | 환자 모니터 (Numeric) | 44 | `HR`, `ART_MBP`, `PLETH_SPO2`, `ETCO2`, `VENT_*` |
| `Primus` | 마취기/환기장치 | 36 | `ETCO2`, `FIO2`, `TV`, `COMPLIANCE`, `MAC` |
| `Orchestra` | 약물 주입 펌프 | 52 | `PPF20_CE`, `RFTN20_RATE`, `NEPI_RATE` |
| `BIS` | 마취 깊이 모니터 | 8 | `BIS`, `EMG`, `SQI`, `SEF`, `EEG1_WAV` |
| `Invos` | 뇌산소포화도 모니터 | 2 | `SCO2_L`, `SCO2_R` |
| `Vigileo` | 심박출량 모니터 | 5 | `CO`, `CI`, `SVV`, `SV` |
| `EV1000` | 혈역학 모니터 | 9 | `CO`, `CI`, `SVV`, `SVR` |
| `Vigilance` | Swan-Ganz 카테터 | 14 | `CO`, `SVO2`, `RVEF`, `EDV` |
| `CardioQ` | 식도 도플러 | 13 | `CO`, `HR`, `FTc`, `PV` |
| `FMS` | 수액 관리 시스템 | 7 | `FLOW_RATE`, `TOTAL_VOL`, `INPUT_TEMP` |
| **합계** | | **196** | |

**왜 `track_names.csv`를 사용하는가:**

| 기준 | `track_names.csv` | PostgreSQL `parameter` 테이블 |
| :--- | :--- | :--- |
| **권위성** | VitalDB 공식 배포 파일 | IndexingAgent가 LLM으로 자동 생성 |
| **안정성** | 정적 파일, 변경 없음 | DB 재구축 시 값 변동 가능 |
| **Description** | VitalDB 원저자가 작성한 정확한 영문 설명 | LLM이 추론한 `semantic_name` (오류 가능) |
| **의존성** | 파일만 있으면 됨 (DB 불필요) | PostgreSQL 접속 필요 |
| **범위** | 시그널 파라미터 196개 (정확) | 시그널 + 코호트 컬럼 혼합 260개 |
| **재현성** | 누구나 동일한 결과 | DB 상태에 따라 달라짐 |

> **참고**: VitalAgent 평가 시에는 VitalAgent 내부적으로 PostgreSQL `parameter` 테이블을 사용한다. `track_names.csv`는 **데이터셋 생성 단계**에서만 참조하는 ground truth 레퍼런스이다. 이렇게 분리함으로써 VitalAgent의 IndexingAgent 품질 자체도 간접적으로 검증할 수 있다.

### 2-3. 케이스별 사용 가능 Track 인벤토리

SVA Stage 1(메타데이터 수집)에서 수집할 정보이다. 3개 케이스의 track 구성:

**Case 0001:**

| 카테고리 | Track |
| :--- | :--- |
| Vital Signs | `Solar8000/HR`, `Solar8000/PLETH_HR`, `Solar8000/PLETH_SPO2`, `Solar8000/BT` |
| Hemodynamics | `Solar8000/ART_SBP`, `Solar8000/ART_DBP`, `Solar8000/ART_MBP`, `Solar8000/NIBP_SBP`, `Solar8000/NIBP_DBP`, `Solar8000/NIBP_MBP` |
| Respiratory | `Primus/ETCO2`, `Primus/FIO2`, `Primus/FEO2`, `Primus/TV`, `Primus/MV`, `Primus/RR_CO2`, `Primus/COMPLIANCE`, `Primus/PIP_MBAR`, `Primus/PEEP_MBAR`, `Primus/MAC`, `Primus/CO2` |
| Respiratory (Solar) | `Solar8000/ETCO2` |
| Anesthesia | `BIS/BIS`, `BIS/SQI`, `BIS/EMG`, `BIS/SEF`, `BIS/SR`, `BIS/TOTPOW` |
| Waveform | `SNUADC/ART`, `SNUADC/ECG_II`, `SNUADC/PLETH` |

**Case 0002:**

| 카테고리 | Track |
| :--- | :--- |
| Vital Signs | `Solar8000/HR`, `Solar8000/PLETH_HR`, `Solar8000/PLETH_SPO2` |
| Respiratory | `Primus/ETCO2`, `Primus/FIO2`, `Primus/FEO2`, `Primus/TV`, `Primus/MV`, `Primus/RR_CO2`, `Primus/COMPLIANCE`, `Primus/PIP_MBAR`, `Primus/PEEP_MBAR`, `Primus/MAC`, `Primus/CO2` |
| Respiratory (Solar) | `Solar8000/ETCO2` |
| Anesthesia | `BIS/BIS`, `BIS/SQI`, `BIS/EMG` |
| Drug Infusion | `Orchestra/RFTN20_RATE`, `Orchestra/RFTN20_CE`, `Orchestra/RFTN20_CP` |

**Case 0009:**

| 카테고리 | Track |
| :--- | :--- |
| Vital Signs | `Solar8000/HR`, `Solar8000/PLETH_HR`, `Solar8000/PLETH_SPO2` |
| Respiratory | `Primus/ETCO2`, `Primus/FIO2`, `Primus/FEO2`, `Primus/TV`, `Primus/MV`, `Primus/RR_CO2`, `Primus/COMPLIANCE`, `Primus/PIP_MBAR`, `Primus/PEEP_MBAR`, `Primus/MAC`, `Primus/CO2` |
| Anesthesia | `BIS/BIS`, `BIS/SQI`, `BIS/EMG` |
| Drug Infusion | `Orchestra/RFTN20_RATE`, `Orchestra/RFTN20_CE`, `Orchestra/PPF20_CE`, `Orchestra/PPF20_CP`, `Orchestra/PPF20_RATE`, `Orchestra/PPF20_VOL` |

### 2-4. Cross-Device 파라미터 쌍 (동일 개념, 다중 소스)

SVA에서 핵심적으로 테스트할 파라미터 쌍이다. VitalAgent의 `ParameterResolver`가 Cross-Device Resolution Hierarchy에 따라 올바른 소스를 선택해야 한다.

| 생리학적 개념 | 소스 1 (Primary) | 소스 2 (Secondary) | 선호 규칙 |
| :--- | :--- | :--- | :--- |
| Heart Rate | `Solar8000/HR` | `Solar8000/PLETH_HR` | Patient Monitor > Pulse Ox |
| EtCO2 | `Primus/ETCO2` | `Solar8000/ETCO2` | Ventilator > Patient Monitor |
| Propofol CE vs CT | `Orchestra/PPF20_CE` | `Orchestra/PPF20_CT` | Effect-site > Target |
| Remifentanil CE vs CP | `Orchestra/RFTN20_CE` | `Orchestra/RFTN20_CP` | Effect-site > Plasma |

### 2-5. 코호트 메타데이터 (clinical_data.csv)

코호트-시그널 조인 질의에 사용할 코호트 CSV의 주요 컬럼:

| 컬럼 | 타입 | 설명 | 예시 값 |
| :--- | :--- | :--- | :--- |
| `caseid` | int | 케이스 ID (vital 파일명과 매핑) | 1, 2, 9 |
| `age` | int | 환자 나이 | 45, 68, 72 |
| `sex` | str | 성별 | `M`, `F` |
| `height` | float | 신장 (cm) | 165.0 |
| `weight` | float | 체중 (kg) | 70.5 |
| `bmi` | float | BMI | 25.9 |
| `asa` | int | ASA 분류 | 1, 2, 3 |
| `optype` | str | 수술 유형 | `General`, `Laparoscopic` |
| `ane_type` | str | 마취 유형 | `General`, `Spinal` |
| `department` | str | 진료과 | `General Surgery` |
| `opname` | str | 수술명 | `Laparoscopic cholecystectomy` |
| `approach` | str | 접근법 | `Laparoscopic` |
| `position` | str | 수술 체위 | `Supine` |
| `preop_htn` | int | 고혈압 여부 (0/1) | 0, 1 |
| `preop_dm` | int | 당뇨 여부 (0/1) | 0, 1 |
| `emop` | int | 응급수술 여부 (0/1) | 0, 1 |
| `casestart` | float | 케이스 시작 시간 (초) | 0.0 |
| `caseend` | float | 케이스 종료 시간 (초) | 7200.0 |
| `opstart` | float | 수술 시작 시간 (초) | 1200.0 |
| `opend` | float | 수술 종료 시간 (초) | 5400.0 |
| `anestart` | float | 마취 시작 시간 (초) | 600.0 |
| `aneend` | float | 마취 종료 시간 (초) | 6000.0 |

> **주의**: Stage 1에서 실제 CSV를 읽어 3개 케이스(0001, 0002, 0009)의 실제 값을 확인하고, 이를 기반으로 코호트 조건 질의를 설계해야 한다. 존재하지 않는 컬럼이나 비현실적 조건을 방지하기 위함이다.

---

## 3. 질의 카테고리 분류 체계 (Query Taxonomy)

### 3-1. 카테고리 개요

SVA 질의는 **5개 카테고리**로 분류하며, 각 카테고리는 VitalAgent의 특정 구조적 강점을 시험한다.

| 카테고리 | 약칭 | 시험 대상 | 목표 개수 | VitalAgent 구성요소 |
| :--- | :--- | :--- | :---: | :--- |
| Semantic Resolution | `sem` | 시맨틱 파라미터 해석 | 15 | ParameterResolver + track_names.csv 레퍼런스 |
| Cross-Device Disambiguation | `xdev` | 동일 개념 다중 소스 판별 | 10 | Cross-Device Resolution Hierarchy |
| Cohort-Signal Join | `cj` | 코호트 필터 → 시그널 분석 | 10 | DataContext + PlanBuilder 조인 |
| Ontology / Category-Based | `onto` | 카테고리/관계 기반 탐색 | 10 | Neo4j + concept_category |
| Adversarial-Semantic | `adv` | 시맨틱 혼동 유도 | 5 | 파라미터 존재 검증 + 모호성 판별 |
| **합계** | | | **50** | |

### 3-2. 카테고리별 상세 정의

#### A. Semantic Resolution (`sem`, 15개)

**정의**: track 이름 없이 임상적/의미적 표현만으로 파라미터를 지칭하는 질의. VitalAgent의 `ParameterResolverNode`가 시맨틱 해석을 수행해야 하며, ground truth는 `track_names.csv`의 `Description` 필드에 기반한다.

**표현 스타일 (3종):**

| 스타일 | 설명 | 예시 질의 |
| :--- | :--- | :--- |
| `clinical` | 영어 임상 표현 | "What is the mean heart rate for case 0001?" |
| `abbreviation` | 의학 약어 사용 | "What is the SD of EtCO2 for case 0002?" |
| `descriptive` | 개념 설명적 표현 | "For case 0009, what is the median value of the depth-of-anesthesia index?" |

**질의 요구사항:**
- track 이름(`Device/Signal` 형식)을 절대 포함하지 않을 것
- 시맨틱 표현이 `equivalence_group` 내의 파라미터로 해석 가능할 것
- 기존 ValueAccuracy와 동일한 명확성 지시를 포함할 것: sampling rate, NaN handling, rounding precision
- 모든 질의는 **영어**로만 작성할 것

**Ground Truth 필드:**

```json
{
    "resolution_target": {
        "equivalence_group": ["Solar8000/HR", "Solar8000/PLETH_HR"],
        "distractors": [],
        "resolution_rationale": "heart rate → Solar8000/HR (direct), Solar8000/PLETH_HR (pleth-derived) 모두 의학적으로 유효한 heart rate 측정"
    }
}
```

#### B. Cross-Device Disambiguation (`xdev`, 10개)

**정의**: 동일한 생리학적 개념이 여러 장비에서 측정될 때, 질의의 맥락이나 ParameterResolver의 Cross-Device Resolution Hierarchy에 따라 올바른 소스를 선택해야 하는 질의.

**3가지 하위 스타일:**

| 스타일 | 설명 | 예시 |
| :--- | :--- | :--- |
| `implicit_preference` | 장비를 명시하지 않아 hierarchy 규칙이 적용되어야 함 | "What is the SD of end-tidal CO2 for case 0002?" → Ventilator preferred → `Primus/ETCO2` |
| `explicit_device_hint` | 장비를 자연어로 암시 (정확한 장비명은 아님) | "heart rate from the patient monitor" → `Solar8000/HR` |
| `multi_source_compare` | 두 소스 모두 필요 (비교 질의) | "mean absolute difference of EtCO2 between the two devices" → `Primus/ETCO2` + `Solar8000/ETCO2` |

**VitalAgent Cross-Device Resolution Hierarchy** (참고용 — VitalAgent 내부 규칙):

```
1) Vital Signs (HR, BP, SpO2) → Patient Monitor (Solar8000) 우선
2) Respiratory / Anesthetic Gas (ETCO2, FIO2, TV) → Ventilator (Primus) 우선
3) Anesthesia Depth → BIS 우선
4) Drug Infusion → Orchestra 우선
5) Measured > Set value (항상, 장비 불문)
```

> **주의**: 이 hierarchy는 VitalAgent의 내부 동작 규칙이며, SVA 채점에는 사용하지 않는다. SVA는 `equivalence_group` 기반으로 채점하므로, 이 hierarchy와 다른 파라미터를 선택하더라도 동등 그룹 내라면 정답으로 인정한다.

**Ground Truth 필드:**

```json
{
    "resolution_target": {
        "equivalence_group": ["Primus/ETCO2", "Solar8000/ETCO2"],
        "distractors": [],
        "resolution_rationale": "장비 힌트 없는 경우: ETCO2는 Primus(ventilator)와 Solar8000(monitor) 모두에서 측정되며 동등하게 유효"
    }
}
```

> **장비 힌트가 있는 경우**: "ventilator의 ETCO2" → `equivalence_group: ["Primus/ETCO2"]`, `distractors: ["Solar8000/ETCO2"]`로 축소

#### C. Cohort-Signal Join (`cj`, 10개)

**정의**: 코호트 메타데이터(clinical_data.csv)의 조건으로 케이스를 필터링한 후, 해당 케이스의 시그널 데이터에서 값을 계산하는 질의. VitalAgent의 `DataContext.load_from_plan()`과 `PlanBuilder`의 `join_specification`이 동작해야 한다.

**3가지 하위 스타일:**

| 스타일 | 설명 | 예시 |
| :--- | :--- | :--- |
| `filter_then_aggregate` | 코호트 조건 → 필터 → 시그널 집계 | "What is the mean heart rate for patients with preop_htn=1?" |
| `conditional_cross_data` | 코호트 속성과 시그널 값의 교차 조건 | "Among patients with BMI > 25, which case has the lowest mean BIS? What is its median EtCO2?" |
| `ranked_selection` | 코호트 속성으로 정렬 → 상위/하위 선택 → 시그널 분석 | "What is the mean arterial pressure for the oldest patient?" |

**중요 제약사항:**
- 코호트 조건은 3개 대상 케이스(0001, 0002, 0009)의 실제 데이터에 기반해야 한다
- 코호트 필터링 결과가 공집합이 되지 않아야 한다 (최소 1건 이상 매칭)
- `entity_identifier`(caseid)를 통한 조인 경로가 명확해야 한다

**Ground Truth 필드:**

```json
{
    "resolution_target": {
        "equivalence_group": ["Solar8000/HR", "Solar8000/PLETH_HR"],
        "distractors": [],
        "cohort_filter": "preop_htn == 1",
        "cohort_source": "clinical_data.csv",
        "join_key": "caseid",
        "expected_matching_cases": ["0002", "0009"],
        "resolution_rationale": "heart rate 측정의 두 파라미터는 동등. 코호트 필터 후 매칭 케이스의 HR 계산"
    }
}
```

**Ground Truth 코드 구조:**

```python
# 코호트 로딩 및 필터링
COHORT_PATH = VITAL_DIR.parent / "clinical_data.csv"
cohort = pd.read_csv(COHORT_PATH)
filtered = cohort[cohort["preop_htn"] == 1]
target_caseids = filtered["caseid"].tolist()

# 시그널 로딩 및 계산
all_vals = []
for cid in target_caseids:
    file_path = VITAL_DIR / f"{str(cid).zfill(4)}.vital"
    if not file_path.exists():
        continue
    vf = vitaldb.VitalFile(str(file_path))
    arr = vf.to_numpy(["Solar8000/HR"], 1)
    x = np.asarray(arr).reshape(-1)
    x = x[~np.isnan(x)]
    if x.size > 0:
        all_vals.append(x)

if not all_vals:
    output_result(None)
else:
    pooled = np.concatenate(all_vals)
    output_result(round(float(np.nanmean(pooled)), 2))
```

#### D. Ontology / Category-Based (`onto`, 10개)

**정의**: 장비 그룹이나 기능적 카테고리를 기반으로 한 탐색적 질의. `track_names.csv`의 장비별 그룹핑(Solar8000, Primus, Orchestra, BIS 등)과 Description의 기능적 분류를 활용한다. VitalAgent는 내부적으로 Neo4j 온톨로지 그래프와 `concept_category` 분류를 통해 이를 처리한다.

**3가지 하위 스타일:**

| 스타일 | 설명 | 예시 |
| :--- | :--- | :--- |
| `category_aggregate` | 특정 장비/카테고리의 전체 파라미터 대상 집계 | "Compute the mean of each vital sign parameter from the patient monitor for case 0001" |
| `category_discovery` | 카테고리 내 파라미터 탐색 + 조건부 선택 | "Among the respiratory parameters, which one has the highest variability (std)?" |
| `relationship_based` | 파라미터 간 관계 기반 질의 | "What is the Pearson correlation between anesthesia depth and propofol effect-site concentration?" |

**Ground Truth 필드:**

```json
{
    "resolution_target": {
        "equivalence_group": ["Solar8000/HR", "Solar8000/PLETH_SPO2", "Solar8000/ART_SBP", "Solar8000/ART_DBP", "Solar8000/ART_MBP"],
        "distractors": [],
        "device_group_filter": "Solar8000",
        "functional_filter": "vital_signs",
        "resolution_rationale": "환자 모니터(Solar8000)에서 측정되는 활력징후 파라미터를 대상으로 각각 평균 계산. track_names.csv의 Solar8000 그룹 중 vital signs 관련 Description을 가진 파라미터를 선별"
    }
}
```

**참고**: Ontology 질의는 `equivalence_group`이 탐색 후보 집합 역할을 하며 다수일 수 있다. 결과도 단일 값이 아닌 딕셔너리/리스트 형태가 될 수 있다.

#### E. Adversarial-Semantic (`adv`, 5개)

**정의**: 시맨틱 해석을 의도적으로 혼동시키는 적대적 질의. 존재하지 않는 개념, 잘못된 장비 힌트, 모호한 범위 등을 포함한다.

**3가지 하위 스타일:**

| 스타일 | 설명 | 기대 동작 | 예시 |
| :--- | :--- | :--- | :--- |
| `nonexistent_concept` | DB에 없는 의학 개념 질의 | `not_found` / `null` | "What is the mean voltage of the raw EEG waveform for case 0001?" |
| `misleading_device_hint` | 잘못된 장비 정보로 유도 | 올바른 소스 선택 | "What is the mean heart rate from the Primus ventilator?" (Primus has no HR) |
| `ambiguous_scope` | 범위/대상이 모호한 질의 | `null` 또는 올바른 해석 | "What is the average of all gas-related data?" (FIO2? ETCO2? CO2? All?) |

**Ground Truth 필드:**

```json
{
    "resolution_target": {
        "equivalence_group": [],
        "distractors": ["BIS/BIS", "BIS/SQI"],
        "expected_behavior": "not_found",
        "resolution_rationale": "EEG raw signal은 BIS 모듈에서 처리된 지표(BIS/BIS)만 존재하며, raw EEG waveform은 별도 track이 아님"
    }
}
```

### 3-3. 카테고리별 목표 분배

| 카테고리 | 최소 | 목표 | 최대 | 오버샘플링 생성 수 |
| :--- | :---: | :---: | :---: | :---: |
| `sem` | 12 | 15 | 18 | 30 |
| `xdev` | 8 | 10 | 12 | 20 |
| `cj` | 8 | 10 | 12 | 20 |
| `onto` | 8 | 10 | 12 | 20 |
| `adv` | 4 | 5 | 7 | 10 |
| **합계** | **40** | **50** | **61** | **100** |

오버샘플링 비율은 2x로 설정하여 Stage 4 품질 필터링 후에도 목표 개수를 충족시킨다.

---

## 4. 데이터셋 JSON 스키마

### 4-1. 공통 스키마

> **Equivalence Group 원칙**: 의학적으로 동등한 파라미터들은 하나의 **동등 그룹(equivalence_group)** 으로 묶는다. 에이전트가 그룹 내 어떤 파라미터를 선택하든 **동일하게 정답으로 인정**한다. 이를 통해 특정 시스템의 내부 우선순위(hierarchy)에 대한 편향 없이 공정하게 평가할 수 있다.

```json
{
    "id": "sva_sem_001",
    "query_category": "semantic_resolution",
    "query_style": "clinical",
    "query": "For case 0001, what is the mean heart rate over the entire recording, sampled at 1 Hz, ignoring NaN values? (Round to 1 decimal place)",

    "resolution_target": {
        "equivalence_group": ["Solar8000/HR", "Solar8000/PLETH_HR"],
        "distractors": [],
        "resolution_rationale": "heart rate → Solar8000/HR and Solar8000/PLETH_HR are both valid heart rate measurements from the patient monitor",
        "expected_behavior": "retrieve"
    },

    "ground_truth_logic": {
        "language": "python",
        "code": "file_path = VITAL_DIR / '0001.vital'\n..."
    },
    "equivalence_values": {
        "Solar8000/HR": 77.2,
        "Solar8000/PLETH_HR": 77.5
    },

    "is_verified_by_execution": true,
    "verification_timestamp": "2026-03-24T14:00:00"
}
```

### 4-2. 필드 정의

| 필드 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `id` | string | O | 고유 ID. 형식: `sva_{category}_{NNN}` |
| `query_category` | string | O | `semantic_resolution` \| `cross_device` \| `cohort_signal_join` \| `ontology_based` \| `adversarial_semantic` |
| `query_style` | string | O | 카테고리별 하위 스타일 (3-2절 참조) |
| `query` | string | O | 자연어 질의 (track 이름 미포함) |
| `resolution_target` | object | O | 파라미터 해석 정답 정보 (4-3절 참조) |
| `ground_truth_logic` | object | O | 실행 가능한 Python GT 코드 (equivalence_group 내 모든 파라미터에 대해 값 계산) |
| `equivalence_values` | object | O | `equivalence_group` 내 각 param_key → GT 계산 결과 매핑. 에이전트 출력이 이 중 아무 값과 일치하면 정답 |
| `is_verified_by_execution` | bool | O | VitalExecutor로 실행 검증 완료 여부 |
| `verification_timestamp` | string | O | 검증 시각 (ISO 8601) |

### 4-3. `resolution_target` 서브 스키마

| 필드 | 타입 | 필수 | 설명 |
| :--- | :--- | :---: | :--- |
| `equivalence_group` | string[] | O | **동등 그룹** — 의학적으로 동등한 param_key 집합. 이 중 어떤 것을 선택해도 동일하게 정답(1.0) 인정. Adversarial의 경우 빈 배열 `[]` |
| `distractors` | string[] | △ | 유사해 보이지만 의학적으로 동등하지 않아 선택하면 오답인 param_key |
| `resolution_rationale` | string | O | 동등 그룹 구성 근거 및 distractor 제외 사유 |
| `expected_behavior` | string | O | `retrieve` \| `not_found` \| `clarify` |
| `cohort_filter` | string | △ | (cj 전용) 코호트 필터 조건 표현식 |
| `cohort_source` | string | △ | (cj 전용) 코호트 CSV 파일명 |
| `join_key` | string | △ | (cj 전용) 조인 키 컬럼 |
| `expected_matching_cases` | string[] | △ | (cj 전용) 필터링 후 매칭되는 케이스 ID |
| `device_group_filter` | string | △ | (onto 전용) 장비 그룹 이름 (e.g., `Solar8000`, `Primus`) |
| `functional_filter` | string | △ | (onto 전용) 기능적 분류 (e.g., `vital_signs`, `respiratory`, `hemodynamics`) |

**Equivalence Group 구성 가이드라인:**

| 카테고리 | equivalence_group 의미 | 예시 |
| :--- | :--- | :--- |
| `semantic_resolution` | 동일 생리학적 개념을 측정하는 모든 파라미터 | "heart rate" → `[Solar8000/HR, Solar8000/PLETH_HR]` |
| `cross_device` | 쿼리에 장비 힌트가 없으면 모든 장비의 동일 개념 파라미터; 장비 힌트가 있으면 해당 장비의 파라미터만 | "end-tidal CO2" → `[Primus/ETCO2, Solar8000/ETCO2]`; "ventilator의 ETCO2" → `[Primus/ETCO2]` |
| `cohort_signal_join` | 코호트 필터 후 사용할 신호 파라미터의 동등 그룹 | "hypertensive patients의 HR" → `[Solar8000/HR, Solar8000/PLETH_HR]` |
| `ontology_based` | 탐색 대상이 되는 전체 후보 파라미터 집합 | "Primus의 모든 호흡 파라미터" → `[Primus/ETCO2, Primus/FIO2, ...]` |
| `adversarial_semantic` | 빈 배열 (정답 파라미터가 존재하지 않음) | `[]` |

### 4-4. 카테고리별 스키마 예시

**Semantic Resolution:**

```json
{
    "id": "sva_sem_001",
    "query_category": "semantic_resolution",
    "query_style": "clinical",
    "query": "For case 0001, what is the mean heart rate over the entire recording, sampled at 1 Hz, ignoring NaN values? (Round to 1 decimal place)",
    "resolution_target": {
        "equivalence_group": ["Solar8000/HR", "Solar8000/PLETH_HR"],
        "distractors": [],
        "resolution_rationale": "heart rate → Solar8000/HR (direct HR) and Solar8000/PLETH_HR (plethysmograph-derived HR) are both medically valid heart rate measurements",
        "expected_behavior": "retrieve"
    },
    "ground_truth_logic": {
        "language": "python",
        "code": "... (equivalence_group 내 모든 파라미터에 대해 각각 값 계산)"
    },
    "equivalence_values": {
        "Solar8000/HR": 77.2,
        "Solar8000/PLETH_HR": 77.5
    },
    "is_verified_by_execution": true
}
```

**Cross-Device Disambiguation:**

```json
{
    "id": "sva_xdev_001",
    "query_category": "cross_device",
    "query_style": "implicit_preference",
    "query": "For case 0002, what is the standard deviation of end-tidal CO2 over the entire recording, sampled at 1 Hz, ignoring NaN values? (Round to 2 decimal places)",
    "resolution_target": {
        "equivalence_group": ["Primus/ETCO2", "Solar8000/ETCO2"],
        "distractors": [],
        "resolution_rationale": "end-tidal CO2 → Primus/ETCO2 (ventilator 직접 측정)와 Solar8000/ETCO2 (patient monitor 측정) 모두 의학적으로 유효한 ETCO2 측정값. 장비 힌트 없으므로 동등 그룹",
        "expected_behavior": "retrieve"
    },
    "ground_truth_logic": {
        "language": "python",
        "code": "..."
    },
    "equivalence_values": {
        "Primus/ETCO2": 12.45,
        "Solar8000/ETCO2": 12.38
    },
    "is_verified_by_execution": true
}
```

> **Cross-Device 힌트 축소 예시**: 질의에 "from the ventilator" 같은 장비 힌트가 포함된 경우, `equivalence_group`을 `["Primus/ETCO2"]`로 축소하고 `Solar8000/ETCO2`를 `distractors`로 이동한다.

**Cohort-Signal Join:**

```json
{
    "id": "sva_cj_001",
    "query_category": "cohort_signal_join",
    "query_style": "filter_then_aggregate",
    "query": "What is the mean heart rate for patients with a history of hypertension (preop_htn=1), sampled at 1 Hz, ignoring NaN values? (Round to 2 decimal places)",
    "resolution_target": {
        "equivalence_group": ["Solar8000/HR", "Solar8000/PLETH_HR"],
        "distractors": [],
        "cohort_filter": "preop_htn == 1",
        "cohort_source": "clinical_data.csv",
        "join_key": "caseid",
        "expected_matching_cases": ["0002"],
        "resolution_rationale": "Filter cohort for preop_htn=1 → compute mean HR for matching cases. Solar8000/HR, Solar8000/PLETH_HR 모두 heart rate의 유효한 측정이므로 동등 그룹",
        "expected_behavior": "retrieve"
    },
    "ground_truth_logic": {
        "language": "python",
        "code": "COHORT_PATH = VITAL_DIR.parent / 'clinical_data.csv'\ncohort = pd.read_csv(COHORT_PATH)\nfiltered = cohort[cohort['preop_htn'] == 1]\n..."
    },
    "equivalence_values": {
        "Solar8000/HR": 81.3,
        "Solar8000/PLETH_HR": 81.7
    },
    "is_verified_by_execution": true
}
```

**Ontology-Based:**

```json
{
    "id": "sva_onto_001",
    "query_category": "ontology_based",
    "query_style": "category_discovery",
    "query": "For case 0009, among all numeric respiratory parameters from the anesthesia machine, which one has the highest variability (standard deviation)? Return the parameter name and its SD value. Sampled at 1 Hz, ignoring NaN values. (Round to 2 decimal places)",
    "resolution_target": {
        "equivalence_group": ["Primus/ETCO2", "Primus/FIO2", "Primus/FEO2", "Primus/TV", "Primus/MV", "Primus/RR_CO2", "Primus/CO2"],
        "distractors": [],
        "device_group_filter": "Primus",
        "functional_filter": "respiratory",
        "resolution_rationale": "track_names.csv의 Primus 장비 그룹 중 Numeric(N) 타입 파라미터 전체가 탐색 대상. 에이전트는 이들 중 최대 std를 가진 파라미터를 식별해야 함",
        "expected_behavior": "retrieve"
    },
    "ground_truth_logic": {
        "language": "python",
        "code": "..."
    },
    "equivalence_values": {
        "Primus/TV": {"parameter": "Primus/TV", "std": 145.23}
    },
    "is_verified_by_execution": true
}
```

> **Ontology 카테고리 특수성**: `equivalence_group`이 "동등 대안"이 아닌 **탐색 후보 집합** 역할을 한다. 에이전트는 이 후보들을 발견하고 분석한 뒤, 질의 조건(최대 std 등)에 맞는 하나의 결과를 반환해야 한다. `equivalence_values`에는 정답 결과만 기록한다.

**Adversarial-Semantic:**

```json
{
    "id": "sva_adv_001",
    "query_category": "adversarial_semantic",
    "query_style": "nonexistent_concept",
    "query": "For case 0001, what is the mean voltage of the raw EEG waveform over the entire recording, sampled at 1 Hz, ignoring NaN values? (Round to 2 decimal places)",
    "resolution_target": {
        "equivalence_group": [],
        "distractors": ["BIS/BIS", "BIS/SQI"],
        "expected_behavior": "not_found",
        "resolution_rationale": "The BIS module provides processed EEG indices but no raw EEG waveform track exists. BIS/BIS, BIS/SQI are related but NOT equivalent to raw EEG voltage"
    },
    "equivalence_values": {},
    "is_verified_by_execution": true
}
```

---

## 5. 데이터셋 생성 파이프라인 (Construction Pipeline)

### 5-0. 전체 흐름

```
[Stage 1] 메타데이터 수집 및 정리
     ↓
[Stage 2] 시맨틱 질의 생성 (LLM × 5 카테고리)
     ↓
[Stage 3] Ground Truth 코드 생성 + VitalExecutor 실행 검증
     ↓
[Stage 4] 품질 필터링 (4개 필터)
     ↓
[Stage 5] 최종 데이터셋 조립 + 검증 리포트
     ↓
[Output] sva_dataset.jsonl (~50개)
```

### 5-1. Stage 1: 메타데이터 수집 및 정리

**파일**: `stages/stage1_metadata.py`

**목적**: `track_names.csv`(VitalDB 공식 파라미터 레퍼런스)와 코호트 CSV에서 LLM 질의 생성에 필요한 컨텍스트를 수집하여 `output/metadata_context.json`으로 저장. PostgreSQL DB 접속 불필요.

**동작:**

```python
def run_stage1():
    """
    1. track_names.csv 로딩 → 전체 196개 파라미터의 Description/Unit/Type 매핑
    2. 3개 케이스의 .vital 파일에서 실제 사용 가능 track 목록 추출
    3. 장비별 그룹핑 + Cross-Device 파라미터 쌍 자동 탐지
    4. clinical_data.csv에서 3개 케이스의 코호트 메타데이터 추출
    """

    # 1. track_names.csv 로딩 (VitalDB 공식 레퍼런스)
    TRACK_NAMES_PATH = VITAL_DIR.parent / "track_names.csv"
    track_ref = pd.read_csv(TRACK_NAMES_PATH)
    # columns: Parameter, Description, Type/Hz, Unit
    param_lookup = {
        row["Parameter"]: {
            "description": row["Description"],
            "type_hz": row["Type/Hz"],
            "unit": row["Unit"],
            "device": row["Parameter"].split("/")[0],
        }
        for _, row in track_ref.iterrows()
    }

    # 2. 케이스별 실제 사용 가능 track 목록 추출
    case_params = {}
    for caseid in TARGET_CASES:
        file_path = VITAL_DIR / f"{str(caseid).zfill(4)}.vital"
        vf = vitaldb.VitalFile(str(file_path))
        tracks = vf.get_track_names()
        case_params[caseid] = tracks

    # 3. 장비별 그룹핑
    device_groups = {}
    for param, info in param_lookup.items():
        device = info["device"]
        device_groups.setdefault(device, []).append(param)

    # 4. Cross-Device 쌍 탐지 (동일 Description, 다른 장비)
    from collections import defaultdict
    desc_to_params = defaultdict(list)
    for param, info in param_lookup.items():
        desc_normalized = info["description"].lower().strip()
        desc_to_params[desc_normalized].append(param)

    cross_device_pairs = []
    for desc, params in desc_to_params.items():
        devices = set(p.split("/")[0] for p in params)
        if len(devices) > 1:
            cross_device_pairs.append({
                "concept": desc,
                "sources": params,
                "devices": sorted(devices),
            })

    # 5. 코호트 메타데이터 추출
    COHORT_PATH = VITAL_DIR.parent / "clinical_data.csv"
    cohort_df = pd.read_csv(COHORT_PATH)
    target_cohort = cohort_df[cohort_df["caseid"].isin(TARGET_CASES)]

    # 6. 조합하여 저장
    context = {
        "track_names_ref": param_lookup,
        "device_groups": device_groups,
        "cross_device_pairs": cross_device_pairs,
        "cohort_data": target_cohort.to_dict(orient="records"),
        "cohort_schema": extract_schema(cohort_df),
        "case_track_inventory": case_params,
    }
    save_json(context, "output/metadata_context.json")
```

**출력 스키마** (`output/metadata_context.json`):

```json
{
    "track_names_ref": {
        "Solar8000/HR": {
            "description": "Heart rate",
            "type_hz": "N",
            "unit": "/min",
            "device": "Solar8000"
        },
        "Primus/ETCO2": {
            "description": "End-tidal CO2",
            "type_hz": "N",
            "unit": "mmHg",
            "device": "Primus"
        }
    },
    "device_groups": {
        "SNUADC": ["SNUADC/ART", "SNUADC/CVP", "SNUADC/ECG_II", "SNUADC/ECG_V5", "SNUADC/FEM", "SNUADC/PLETH"],
        "Solar8000": ["Solar8000/ART_DBP", "Solar8000/ART_MBP", "Solar8000/HR", ...],
        "Primus": ["Primus/COMPLIANCE", "Primus/ETCO2", "Primus/FIO2", ...],
        "Orchestra": ["Orchestra/PPF20_CE", "Orchestra/RFTN20_RATE", ...],
        "BIS": ["BIS/BIS", "BIS/EMG", "BIS/SQI", ...],
        "Vigileo": ["Vigileo/CO", "Vigileo/CI", ...],
        "EV1000": ["EV1000/CO", "EV1000/SVV", ...],
        "Vigilance": ["Vigilance/CO", "Vigilance/SVO2", ...],
        "CardioQ": ["CardioQ/CO", "CardioQ/HR", ...],
        "Invos": ["Invos/SCO2_L", "Invos/SCO2_R"],
        "FMS": ["FMS/FLOW_RATE", "FMS/TOTAL_VOL", ...]
    },
    "cross_device_pairs": [
        {
            "concept": "end-tidal co2",
            "sources": ["Primus/ETCO2", "Solar8000/ETCO2"],
            "devices": ["Primus", "Solar8000"]
        },
        {
            "concept": "heart rate",
            "sources": ["Solar8000/HR", "Solar8000/PLETH_HR", "Vigilance/HR_AVG", "CardioQ/HR"],
            "devices": ["CardioQ", "Solar8000", "Vigilance"]
        },
        {
            "concept": "cardiac output",
            "sources": ["Vigileo/CO", "EV1000/CO", "Vigilance/CO", "CardioQ/CO"],
            "devices": ["CardioQ", "EV1000", "Vigilance", "Vigileo"]
        }
    ],
    "cohort_data": [
        {"caseid": 1, "age": 75, "sex": "F", "bmi": 22.1, "asa": 2, "preop_htn": 1, ...},
        {"caseid": 2, "age": 56, "sex": "M", "bmi": 27.3, "asa": 1, "preop_htn": 0, ...},
        {"caseid": 9, "age": 63, "sex": "F", "bmi": 24.8, "asa": 2, "preop_htn": 1, ...}
    ],
    "cohort_schema": {
        "columns": ["caseid", "age", "sex", "height", "weight", "bmi", "asa", ...],
        "dtypes": {"caseid": "int64", "age": "int64", "sex": "object", ...}
    },
    "case_track_inventory": {
        "0001": ["Solar8000/HR", "Solar8000/PLETH_HR", "SNUADC/ART", ...],
        "0002": ["Solar8000/HR", "Orchestra/RFTN20_RATE", ...],
        "0009": ["Solar8000/HR", "Orchestra/PPF20_CE", ...]
    }
}
```

### 5-2. Stage 2: 시맨틱 질의 생성 (LLM)

**파일**: `stages/stage2_generate.py`

**목적**: 5개 카테고리별 LLM 프롬프트를 사용하여 질의 후보를 생성.

**공통 생성 규칙:**
1. track 이름(`Device/Signal` 형식)을 질의 텍스트에 포함하지 말 것
2. 각 질의에 `resolution_target` 포함 (LLM이 함께 생성)
3. 기존 ValueAccuracy와 동일한 unambiguity 지시 포함: sampling rate ("1 Hz"), NaN handling ("ignoring NaN"), rounding ("Round to N decimal places"), time scope ("entire recording")
4. 모든 질의는 **영어**로만 작성할 것
5. 결과는 단일 숫자, null, 또는 구조화된 JSON으로 한정

**카테고리별 프롬프트 파일:**

| 카테고리 | 프롬프트 파일 | LLM 호출 수 |
| :--- | :--- | :---: |
| `sem` | `prompts/semantic_query_gen.txt` | 6 배치 × 5개 = 30개 |
| `xdev` | `prompts/cross_device_query_gen.txt` | 4 배치 × 5개 = 20개 |
| `cj` | `prompts/cohort_signal_query_gen.txt` | 4 배치 × 5개 = 20개 |
| `onto` | `prompts/ontology_query_gen.txt` | 4 배치 × 5개 = 20개 |
| `adv` | `prompts/adversarial_semantic_gen.txt` | 2 배치 × 5개 = 10개 |

**프롬프트 구조 (Semantic Resolution 예시):**

```
[System]
You are a test data generator for the Semantic Value Accuracy benchmark of a medical AI system.
Generate natural language queries that refer to biosignal parameters using ONLY semantic/clinical
expressions — NEVER include raw track names like "Solar8000/HR" or "Primus/ETCO2" in the query.

[Context — DO NOT expose in queries]
Available parameters (for internal reference only, from track_names.csv):
{parameters_list with Description, Unit, Device — but NOT the Parameter (track name) field}

Case IDs: 0001, 0002, 0009
Cross-Device pairs (internal): {cross_device_pairs}

[Constraints]
1. Each query must include: sampling rate (1 Hz), NaN handling (ignore), rounding precision, time scope
2. The query must be resolvable to a specific set of param_key(s) via semantic interpretation
3. All queries must be in English only
4. Mix styles: clinical, abbreviation, descriptive
5. For each query, generate the resolution_target with equivalence_group (all medically equivalent params) and rationale
6. Generate {n} queries in this batch

[Output Format — JSON array]
[
  {
    "query": "...",
    "query_style": "clinical",
    "resolution_target": {
      "equivalence_group": ["Solar8000/HR", "Solar8000/PLETH_HR"],
      "distractors": [],
      "resolution_rationale": "heart rate → both Solar8000/HR and PLETH_HR are valid HR measurements"
    }
  }
]
```

**프롬프트 구조 (Cohort-Signal Join 예시):**

```
[System]
Generate queries that require joining clinical metadata with vital signal data.

[Context]
Cohort data for target cases:
{cohort_data_for_cases}

Cohort schema:
{cohort_schema}

Available signal parameters:
{parameters_with_semantic_names}

[Constraints]
1. Each query must require a cohort filter FIRST, then signal analysis
2. The cohort filter must match at least 1 case from the 3 target cases
3. Do NOT include track names in the query
4. Include the cohort_filter expression in resolution_target
5. Ensure the join path: cohort.caseid → vital file name (zero-padded)
```

**배치 처리 로직:**

```python
def run_stage2(metadata_context: dict):
    llm_client = get_llm_client()

    category_configs = {
        "semantic_resolution": {
            "prompt_file": "prompts/semantic_query_gen.txt",
            "batch_size": 5,
            "total_target": 30,
            "id_prefix": "sva_sem",
        },
        "cross_device": {
            "prompt_file": "prompts/cross_device_query_gen.txt",
            "batch_size": 5,
            "total_target": 20,
            "id_prefix": "sva_xdev",
        },
        # ... 나머지 카테고리
    }

    all_candidates = []
    for category, config in category_configs.items():
        prompt_template = load_prompt(config["prompt_file"])
        remaining = config["total_target"]
        batch_idx = 0

        while remaining > 0:
            n = min(config["batch_size"], remaining)
            prompt = prompt_template.format(
                n=n,
                parameters_list=format_params_for_category(metadata_context, category),
                cohort_data=json.dumps(metadata_context.get("cohort_data", []), ensure_ascii=False),
                cross_device_pairs=json.dumps(metadata_context.get("cross_device_pairs", [])),
                # ... 카테고리별 추가 컨텍스트
            )

            response = llm_client.ask_json(prompt)
            queries = parse_response(response)

            for i, q in enumerate(queries):
                q["id"] = f"{config['id_prefix']}_{(batch_idx * config['batch_size'] + i + 1):03d}"
                q["query_category"] = category
                all_candidates.append(q)

            remaining -= len(queries)
            batch_idx += 1

    save_jsonl(all_candidates, "output/sva_candidates.jsonl")
```

**Resume 지원**: 각 배치 완료 시 progress 파일 업데이트. 중단 후 재시작 시 완료된 배치는 건너뛴다.

### 5-3. Stage 3: Ground Truth 코드 생성 + 실행 검증

**파일**: `stages/stage3_ground_truth.py`

**목적**: 각 질의에 대해 실행 가능한 Python GT 코드를 생성하고, `VitalExecutor`로 검증하여 `equivalence_values`를 확정.

**핵심 원칙**: `equivalence_group` 내 **모든** 파라미터에 대해 GT 값을 계산한다. 이를 통해 에이전트가 그룹 내 어떤 파라미터를 선택하든 해당 파라미터의 정답값과 비교할 수 있다.

**3-Pass 구조:**

```
Pass 1: LLM에게 기준 GT 코드 생성 요청
   ↓
   equivalence_group의 첫 번째 param_key를 사용한 코드 생성
   ↓
Pass 2: VitalExecutor로 기준 코드 실행 검증
   ↓
   성공 → 기준값 확보
   실패 → 에러 피드백 → 재생성 (최대 3회)
   ↓
Pass 3: equivalence_group 내 나머지 파라미터에 대해 코드 변환 + 실행
   ↓
   모든 파라미터의 값을 equivalence_values에 기록
```

**코드 생성 프롬프트:**

```
[System]
Generate Python code that computes the ground truth answer for the following query.

[Query]
{query}

[Resolution Information — USE THIS EXACT param_key]
Target parameter: {equivalence_group[0]}
Case IDs to process: {extracted_case_ids}

[Available Infrastructure]
- VITAL_DIR: Path to vital files (e.g., VITAL_DIR / "0001.vital")
- vitaldb.VitalFile(path).to_numpy([track_names], interval)
- np, pd are pre-imported
- output_result(value) to emit the final answer
- For cohort joins: COHORT_PATH = VITAL_DIR.parent / "clinical_data.csv"

[Constraints]
1. Use EXACTLY the param_key listed in "Target parameter"
2. Follow the query's instructions for sampling rate, NaN handling, rounding
3. Handle missing files/tracks gracefully (output_result(None))
4. Call output_result() exactly once at the end
```

**Equivalence Values 생성:**

기준 코드가 검증되면, `equivalence_group` 내 모든 파라미터에 대해 동일 계산을 수행하여 `equivalence_values`를 완성한다:

```python
def compute_equivalence_values(case: dict, executor: VitalExecutor) -> dict:
    eq_group = case["resolution_target"].get("equivalence_group", [])
    base_code = case["ground_truth_logic"]["code"]
    base_param = eq_group[0] if eq_group else None
    eq_values = {}

    for param in eq_group:
        if param == base_param:
            eq_values[param] = case.get("_base_value")
        else:
            param_code = base_code.replace(base_param, param)
            result = executor.execute_code(param_code)
            if result["success"]:
                eq_values[param] = result["result"]
            else:
                logger.warning(f"Failed to compute value for {param}: {result['error']}")
                eq_values[param] = None

    return eq_values
```

> **Ontology 카테고리 예외**: ontology_based의 경우 `equivalence_group`은 탐색 후보 집합이므로, GT 코드가 전체 후보를 순회하여 조건에 맞는 결과를 반환한다. `equivalence_values`에는 최종 정답(e.g., 최대 std를 가진 파라미터)만 기록한다.

**실행 검증 결과 처리:**

| 실행 결과 | 처리 |
| :--- | :--- |
| 성공, 값 반환 | 해당 param의 `equivalence_values[param]` 기록, 전체 완료 시 `is_verified_by_execution = True` |
| 성공, None 반환 | `equivalence_values[param] = None` 기록 (adversarial의 경우 `equivalence_values = {}`) |
| 실패, 에러 | LLM 재생성 요청 (최대 3회). 3회 모두 실패 시 제거 |
| 타임아웃 | 제거 (60초 초과) |

### 5-4. Stage 4: 품질 필터링 (4개 필터)

**파일**: `stages/stage4_filter.py`

**목적**: 생성된 후보 중 품질 기준을 충족하지 않는 질의를 제거.

**필터 적용 순서** (비용 오름차순):

#### Filter 1: Track 이름 노출 검사 (비용: 낮음)

질의 텍스트에 `Device/Signal` 형식의 track 이름이 포함되어 있으면 제거한다. SVA의 핵심 전제는 "track 이름 없는 시맨틱 질의"이므로 이를 위반하면 테스트의 의미가 없다.

```python
TRACK_PATTERN = re.compile(r'\b[A-Z][a-z]+\d*/[A-Z][A-Z0-9_]+\b')

def check_track_exposure(query: str) -> bool:
    """Returns True if the query does NOT contain any track names."""
    matches = TRACK_PATTERN.findall(query)
    return len(matches) == 0
```

**예외**: adversarial 카테고리의 `misleading_device_hint` 스타일은 장비명(Primus, Solar8000 등)을 포함할 수 있으나, 완전한 track 이름(`Primus/ETCO2`)은 여전히 불가.

#### Filter 2: 결정론 검증 (비용: 중간)

GT 코드를 `interval=0.5`로 재실행하여 결과가 달라지는지 확인. 달라지면서 질의에 샘플링 레이트 명시가 없으면 제거.

```python
def check_determinism(case: dict, executor: VitalExecutor) -> bool:
    original_code = case["ground_truth_logic"]["code"]
    modified_code = original_code.replace(
        "to_numpy([", "to_numpy(["
    ).replace("], 1)", "], 0.5)")

    result_half = executor.execute_code(modified_code)
    if not result_half["success"]:
        return True  # 에러 시 pass (interval 변경이 지원 안 될 수 있음)

    eq_values = case.get("equivalence_values", {})
    first_param = list(eq_values.keys())[0] if eq_values else None
    original_value = eq_values.get(first_param) if first_param else None
    half_value = result_half["result"]

    if original_value is None and half_value is None:
        return True

    # 값이 다른데 query에 Hz/sampling 언급 없으면 fail
    if not compare_values(original_value, half_value):
        has_rate_spec = any(kw in case["query"].lower()
                          for kw in ["hz", "샘플", "sampl", "interval"])
        return has_rate_spec

    return True
```

#### Filter 3: 시맨틱 중복 제거 (비용: 중간)

동일 카테고리 내에서 SequenceMatcher 유사도 ≥ 0.80이고 `equivalence_values`의 값 집합이 동일하면 중복으로 판단.

```python
from difflib import SequenceMatcher

DEDUP_THRESHOLD = 0.80

def is_duplicate(new_query: str, new_eq_values: dict, existing: list) -> bool:
    new_vals = set(v for v in new_eq_values.values() if v is not None)
    for ex in existing:
        sim = SequenceMatcher(None, new_query, ex["query"]).ratio()
        ex_vals = set(v for v in ex.get("equivalence_values", {}).values() if v is not None)
        if sim >= DEDUP_THRESHOLD and new_vals == ex_vals:
            return True
    return False
```

#### Filter 4: LLM 품질 감사 (비용: 높음)

5개 벡터를 검사하는 LLM-as-a-Judge:

```
[Audit Prompt]
Evaluate the following SVA benchmark query on 5 criteria.

Query: "{query}"
Category: {query_category}
Resolution Target: {resolution_target}
Equivalence Values: {equivalence_values}

Criteria (score 1-5 each):
1. SEMANTIC CLARITY: Is the query clearly interpretable to a specific set of parameters
   WITHOUT knowing the track names? (1=ambiguous, 5=unambiguous)
2. CLINICAL VALIDITY: Is the query medically meaningful? (1=nonsensical, 5=realistic)
3. EQUIVALENCE GROUP CORRECTNESS: Are the parameters in equivalence_group truly medically
   equivalent for this query? Are distractors correctly excluded? (1=wrong grouping, 5=perfect)
4. GROUND TRUTH ALIGNMENT: Do the equivalence_values logically follow from the query?
   (1=clearly wrong, 5=correct)
5. CATEGORY FIT: Does the query genuinely test the claimed category's capability?
   (1=wrong category, 5=perfect fit)

Output JSON:
{
    "scores": {"clarity": N, "validity": N, "resolution": N, "truth": N, "fit": N},
    "overall_pass": true/false,
    "reason": "..."
}

Pass threshold: all scores >= 3, average >= 3.5
```

**필터 적용 요약:**

| 필터 | 통과 조건 | 예상 탈락률 |
| :--- | :--- | :---: |
| Track 노출 | query에 `Device/Signal` 패턴 없음 | ~10% |
| 결정론 | interval 변경에도 결과 동일 또는 Hz 명시 | ~5% |
| 중복 제거 | 유사도 < 0.80 또는 값 다름 | ~15% |
| LLM 감사 | 모든 점수 ≥ 3, 평균 ≥ 3.5 | ~20% |

### 5-5. Stage 5: 최종 데이터셋 조립 + 검증 리포트

**파일**: `stages/stage5_assemble.py`

**목적**: 필터링 통과한 질의를 카테고리별 목표 개수에 맞춰 선별하고, 최종 데이터셋과 검증 리포트를 생성.

**선별 로직:**

```python
def assemble_final_dataset(filtered_candidates: list) -> list:
    TARGET = {
        "semantic_resolution": 15,
        "cross_device": 10,
        "cohort_signal_join": 10,
        "ontology_based": 10,
        "adversarial_semantic": 5,
    }

    final = []
    for category, target_n in TARGET.items():
        pool = [c for c in filtered_candidates if c["query_category"] == category]

        if len(pool) < target_n:
            logger.warning(f"Category {category}: only {len(pool)}/{target_n} available")

        # LLM 감사 점수 기준 내림차순 정렬 후 상위 N개 선택
        pool.sort(key=lambda x: x.get("audit_score_avg", 0), reverse=True)
        selected = pool[:target_n]

        # ID 재부여
        for i, case in enumerate(selected):
            prefix = {"semantic_resolution": "sva_sem", "cross_device": "sva_xdev",
                      "cohort_signal_join": "sva_cj", "ontology_based": "sva_onto",
                      "adversarial_semantic": "sva_adv"}[category]
            case["id"] = f"{prefix}_{i+1:03d}"

        final.extend(selected)

    return final
```

**검증 리포트** (`output/sva_validation_report.json`):

```json
{
    "generation_timestamp": "2026-03-24T15:00:00",
    "total_generated": 100,
    "total_after_filter": 62,
    "total_final": 50,
    "category_distribution": {
        "semantic_resolution": 15,
        "cross_device": 10,
        "cohort_signal_join": 10,
        "ontology_based": 10,
        "adversarial_semantic": 5
    },
    "style_distribution": {
        "clinical": 8,
        "abbreviation": 4,
        "descriptive": 3,
        "implicit_preference": 5,
        "explicit_device_hint": 3,
        "multi_source_compare": 2,
        "filter_then_aggregate": 4,
        "conditional_cross_data": 3,
        "ranked_selection": 3,
        "category_aggregate": 4,
        "category_discovery": 4,
        "relationship_based": 2,
        "nonexistent_concept": 2,
        "misleading_device_hint": 2,
        "ambiguous_scope": 1
    },
    "unique_equivalence_params": 28,
    "execution_verified_pct": 100.0,
    "null_value_ratio": 0.10,
    "filter_stats": {
        "track_exposure_removed": 8,
        "determinism_removed": 4,
        "duplicate_removed": 12,
        "llm_audit_removed": 14
    },
    "validation_checks": {
        "min_per_category": "PASS",
        "all_execution_verified": "PASS",
        "no_track_in_queries": "PASS",
        "null_ratio_under_20pct": "PASS",
        "case_diversity": "PASS"
    }
}
```

**최소 통과 기준:**
- 각 카테고리에서 최소 개수(3-3절의 "최소" 컬럼) 충족
- 모든 케이스 `is_verified_by_execution = True`
- track 이름 미포함 100% (adversarial 예외 포함)
- null 기대값 비율 ≤ 20%
- 3개 케이스(0001, 0002, 0009) 각각 최소 20% 이상 등장

---

## 6. 평가 파이프라인 (Evaluation Pipeline)

### 6-1. 시나리오 정의

| 시나리오 | 설명 | 파라미터 해석 주체 |
| :--- | :--- | :--- |
| **VitalAgent** | 시맨틱 질의 → Orchestrator.run() 전체 파이프라인 | ExtractionAgent (ParameterResolver) |
| **Claude Code CLI** | 시맨틱 질의 → Claude가 코드 생성 → VitalExecutor 실행 | Claude LLM (track 탐색 필요) |

### 6-2. VitalAgent 시나리오 실행

```python
def run_vitalagent_sva(cases: list) -> list:
    from OrchestrationAgent.src.orchestrator import Orchestrator
    orch = Orchestrator()
    results = []

    for case in cases:
        prompt = (
            f"{case['query']}\n\n"
            f"JSON 형식으로만 답변해줘: {{\"answer\": <계산된 값>}}"
        )

        t0 = time.time()
        try:
            res = orch.run(prompt)
            elapsed = (time.time() - t0) * 1000

            # ExtractionAgent의 resolved_parameters 추출 (Layer 1 채점용)
            extraction_info = extract_resolution_info(res)

            agent_answer = parse_answer(res)
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            extraction_info = None
            agent_answer = None

        results.append(SVAResult(
            case_id=case["id"],
            scenario="VitalAgent",
            query=case["query"],
            equivalence_values=case["equivalence_values"],
            agent_output=agent_answer,
            resolved_params=extraction_info.get("resolved_params") if extraction_info else None,
            generated_code=extraction_info.get("generated_code") if extraction_info else None,
            execution_time_ms=elapsed,
        ))

    return results
```

### 6-3. Claude Code CLI 시나리오 실행

**핵심 차이**: Claude CLI에게 track 이름 목록을 직접 알려주지 않고, `vf.get_track_names()`로 스스로 탐색하도록 한다.

```python
def run_claude_code_cli_sva(cases: list) -> list:
    results = []

    for case in cases:
        prompt = (
            f"You are a medical data analyst.\n"
            f"Answer the following question: '{case['query']}'\n\n"
            f"Vital files location: {VITAL_DIR}/ (format: NNNN.vital, zero-padded)\n"
            f"You can discover available tracks using: vf = vitaldb.VitalFile(path); vf.get_track_names()\n"
            f"Clinical metadata: {VITAL_DIR.parent}/clinical_data.csv\n"
            f"IMPORTANT: You must figure out which track(s) match the clinical concept "
            f"described in the query. Use vf.get_track_names() to explore.\n"
            f"When calling vf.to_numpy(), use interval=1 unless specified otherwise.\n"
            f"Output ONLY: {{\"answer\": <value>}}\n"
            f"Write your Python code in a ```python block."
        )

        t0 = time.time()
        process = subprocess.run(
            ["claude", "-p", prompt, "--no-session-persistence"],
            capture_output=True, text=True, timeout=180
        )
        elapsed = (time.time() - t0) * 1000

        raw_output = process.stdout.strip()
        code_match = re.search(r'```python\n(.*?)\n```', raw_output, re.DOTALL)

        if code_match:
            code = code_match.group(1)
            used_params = extract_params_from_code(code)
            executor = VitalExecutor()
            res = executor.execute_code(code)
            agent_answer = res["result"] if res["success"] else None
        else:
            used_params = []
            agent_answer = parse_json_answer(raw_output)

        results.append(SVAResult(
            case_id=case["id"],
            scenario="Claude-Code-CLI",
            query=case["query"],
            equivalence_values=case["equivalence_values"],
            agent_output=agent_answer,
            resolved_params=used_params,
            generated_code=code if code_match else None,
            execution_time_ms=elapsed,
        ))

    return results
```

### 6-4. 코드에서 사용된 param_key 추출

Layer 1(Parameter Resolution) 채점을 위해, 생성된 코드에서 실제로 사용된 track 이름을 추출하는 유틸리티:

```python
def extract_params_from_code(code: str) -> list:
    """
    Python 코드에서 vf.to_numpy() 호출의 track_names 인자를 추출.

    패턴:
    - vf.to_numpy(['Solar8000/HR'], 1)
    - vf.to_numpy(["Solar8000/HR", "BIS/BIS"], 1)
    - to_numpy(['track'], interval)
    """
    pattern = r"to_numpy\(\s*\[([^\]]+)\]"
    matches = re.findall(pattern, code)

    params = set()
    for match in matches:
        # 따옴표 안의 문자열 추출
        strings = re.findall(r"['\"]([^'\"]+)['\"]", match)
        params.update(strings)

    return sorted(params)
```

---

## 7. 3-Layer 채점 체계 (Scoring System)

### 7-1. 개요

기존 ValueAccuracy의 단일 value_match 채점 대신, SVA는 에이전트의 처리 과정을 3개 계층으로 분리하여 평가한다. 이를 통해 "어디에서 실패했는가"를 진단할 수 있다.

```
Layer 1: Parameter Resolution Score   → 시맨틱 해석을 올바르게 했는가?
Layer 2: Execution Score               → 코드가 에러 없이 실행되었는가?
Layer 3: Value Accuracy Score           → 최종 값이 정답과 일치하는가?

Composite Score = weighted sum of 3 layers
```

### 7-2. Layer 1: Parameter Resolution Score

에이전트가 `equivalence_group` 내의 올바른 `param_key`를 선택했는지 평가한다. **Equivalence Group 원칙**에 따라, 그룹 내 어떤 파라미터를 선택해도 동일하게 정답(1.0)으로 인정한다.

**점수 기준:**

| 상황 | 점수 | 라벨 |
| :--- | :---: | :--- |
| `used_params ⊆ equivalence_group` (전부 그룹 내) | **1.0** | `correct` |
| `used_params ∩ equivalence_group ≠ ∅` AND `used_params ⊄ equivalence_group` (일부만 그룹 내) | **0.5** | `partial_match` |
| `used_params ∩ equivalence_group = ∅` (전부 그룹 밖) | **0.0** | `wrong_param` |
| 코드 없음 / 파라미터 추출 불가 | **0.0** | `not_attempted` |
| Adversarial: `equivalence_group = []`이고 에이전트가 null/에러 반환 | **1.0** | `correct_rejection` |
| Adversarial: `equivalence_group = []`인데 에이전트가 값 반환 | **0.0** | `hallucination` |

> **기존 방식과의 차이**: 기존에는 `intended_params`(1.0) vs `acceptable_alternatives`(0.8)로 차등 점수를 부여했으나, 이는 특정 시스템의 내부 hierarchy에 편향될 수 있었다. 새 방식에서는 의학적 동등성만을 기준으로 하므로 더 공정하다.

**구현:**

```python
def score_resolution(case: dict, result: SVAResult) -> tuple:
    target = case["resolution_target"]
    eq_group = set(target.get("equivalence_group", []))
    expected_behavior = target.get("expected_behavior", "retrieve")

    # Adversarial 처리 (equivalence_group이 빈 경우)
    if expected_behavior == "not_found" or len(eq_group) == 0:
        if result.agent_output is None or result.error_message:
            return 1.0, "correct_rejection"
        else:
            return 0.0, "hallucination"

    used = set(result.resolved_params or [])

    if not used:
        return 0.0, "not_attempted"
    if used <= eq_group:
        return 1.0, "correct"
    if used & eq_group:
        return 0.5, "partial_match"
    return 0.0, "wrong_param"
```

### 7-3. Layer 2: Execution Score

에이전트의 코드가 에러 없이 실행되어 결과를 반환했는지 평가한다.

| 상황 | 점수 | 라벨 |
| :--- | :---: | :--- |
| 정상 실행, 값 반환 | **1.0** | `success` |
| 정상 실행, None 반환 (adversarial 정답인 경우) | **1.0** | `correct_null` |
| 런타임 에러 | **0.0** | `runtime_error` |
| 타임아웃 | **0.0** | `timeout` |
| 출력 없음 / 파싱 실패 | **0.0** | `no_output` |

### 7-4. Layer 3: Value Accuracy Score

최종 반환값이 `equivalence_values`의 **어느 값과든** 일치하는지 평가한다. Equivalence Group 내 어떤 파라미터를 선택했든, 해당 파라미터의 정답값과 일치하면 **동일하게 1.0**을 부여한다.

| 상황 | 점수 | 라벨 |
| :--- | :---: | :--- |
| `equivalence_values`의 어떤 값과든 정확 일치 (tolerance 1e-5) | **1.0** | `match` |
| 불일치 | **0.0** | `mismatch` |
| Adversarial: `equivalence_values = {}` 이고 에이전트가 null 반환 | **1.0** | `null_match` |
| Adversarial: `equivalence_values = {}` 인데 에이전트가 값 반환 | **0.0** | `mismatch` |

> **기존 방식과의 차이**: 기존에는 `expected_value` 일치 → 1.0, `alternative_values` 일치 → 0.5로 차등을 두었다. 새 방식에서는 `equivalence_values`의 모든 값이 동등하므로, 어느 값과 일치하든 1.0이다.

**구현:**

```python
def score_value(case: dict, result: SVAResult) -> tuple:
    eq_values = case.get("equivalence_values", {})
    actual = result.agent_output

    # Adversarial / null 매칭 (equivalence_values가 비어있는 경우)
    if not eq_values:
        if actual is None or actual == "None" or actual == "null":
            return 1.0, "null_match"
        if isinstance(actual, (list, dict)) and len(actual) == 0:
            return 1.0, "null_match"
        return 0.0, "mismatch"

    # equivalence_values 내 어떤 값과든 일치하면 정답
    for param_key, expected_val in eq_values.items():
        if expected_val is not None and compare_values(expected_val, actual):
            return 1.0, f"match ({param_key})"

    return 0.0, "mismatch"
```

### 7-5. Composite Score 계산

```python
WEIGHTS = {
    "resolution": 0.4,   # 시맨틱 해석이 SVA의 핵심 차별점
    "execution": 0.2,    # 실행 성공 여부
    "value": 0.4,        # 최종 수치 정확도
}

def compute_composite(resolution_score, execution_score, value_score):
    return (
        WEIGHTS["resolution"] * resolution_score +
        WEIGHTS["execution"] * execution_score +
        WEIGHTS["value"] * value_score
    )
```

**가중치 근거:**
- Resolution(0.4): SVA의 존재 이유는 시맨틱 해석 능력 평가. 가장 높은 가중치. Equivalence Group 방식으로 공정성 확보.
- Value(0.4): 최종 정확도가 없으면 실용적 가치가 없으므로 동일 가중치. `equivalence_values` 내 어떤 값이든 일치하면 1.0.
- Execution(0.2): 코드 실행은 Resolution과 Value의 중간 과정이므로 낮은 가중치.

### 7-6. 집계 지표

**Overall:**

| 지표 | 공식 |
| :--- | :--- |
| Resolution Accuracy | mean(resolution_scores) |
| Execution Rate | mean(execution_scores) |
| Value Accuracy | mean(value_scores) |
| Composite Score | mean(composite_scores) |

**Breakdown by category:**

각 `query_category`별로 위 4개 지표를 산출.

**Breakdown by style:**

각 `query_style`별로 위 4개 지표를 산출.

---

## 8. 결과 출력 형식

### 8-1. XLSX 워크북 구조

| 시트명 | 내용 |
| :--- | :--- |
| `Comparison` | 시나리오별 overall 지표 피벗 테이블 |
| `Category_Breakdown` | 카테고리별 4개 지표 비교 |
| `Style_Breakdown` | 스타일별 4개 지표 비교 |
| `Detail` | 케이스별 상세 결과 (모든 필드) |
| `Resolution_Analysis` | Parameter Resolution 성공/실패 패턴 분석 |

### 8-2. 콘솔 출력 형식

```
═══════════════════════════════════════════════════════════════════════════
  Semantic Value Accuracy — Scenario Comparison
═══════════════════════════════════════════════════════════════════════════
Scenario                 N  Resolution%  Execution%  Value%  Composite%  Avg(ms)
───────────────────────────────────────────────────────────────────────────
VitalAgent              50      92.00%     88.00%   86.00%     88.80%   15274
Claude-Code-CLI         50      48.00%     72.00%   40.00%     49.60%   10242
═══════════════════════════════════════════════════════════════════════════

--- Breakdown by query_category ---
Scenario             Category              N  Res%    Exec%   Val%    Comp%
───────────────────────────────────────────────────────────────────────────
VitalAgent           semantic_resolution   15  93.3%   93.3%  86.7%   90.7%
Claude-Code-CLI      semantic_resolution   15  40.0%   73.3%  33.3%   44.7%
VitalAgent           cross_device          10  90.0%   90.0%  85.0%   88.0%
Claude-Code-CLI      cross_device          10  50.0%   70.0%  40.0%   50.0%
VitalAgent           cohort_signal_join    10  95.0%   85.0%  90.0%   90.0%
Claude-Code-CLI      cohort_signal_join    10  20.0%   60.0%  15.0%   27.0%
VitalAgent           ontology_based        10  85.0%   80.0%  80.0%   82.0%
Claude-Code-CLI      ontology_based        10  30.0%   65.0%  20.0%   33.0%
VitalAgent           adversarial_semantic   5 100.0%  100.0% 100.0%  100.0%
Claude-Code-CLI      adversarial_semantic   5  60.0%   80.0%  60.0%   64.0%

--- Resolution Detail ---
Scenario             correct  partial  wrong  not_attempted  correct_rejection  hallucination
───────────────────────────────────────────────────────────────────────────────────────────────
VitalAgent              42        2      1           0              5                0
Claude-Code-CLI         16        8     18           3              3                2
```

### 8-3. Detail 시트 컬럼

| 컬럼 | 설명 |
| :--- | :--- |
| `scenario` | VitalAgent / Claude-Code-CLI |
| `case_id` | sva_sem_001, sva_xdev_003, ... |
| `query_category` | semantic_resolution, cross_device, ... |
| `query_style` | clinical, abbreviation, descriptive, implicit_preference, ... |
| `query` | 전체 질의 텍스트 |
| `equivalence_group` | 동등 그룹 param_key 목록 |
| `resolved_params` | 에이전트가 실제 사용한 param_key |
| `resolution_score` | 0.0 / 0.5 / 1.0 |
| `resolution_detail` | correct, partial_match, wrong_param, correct_rejection, hallucination, not_attempted |
| `equivalence_values` | 동등 그룹 내 각 파라미터의 GT 값 |
| `agent_output` | 에이전트 반환값 |
| `value_score` | 0.0 / 1.0 |
| `value_detail` | match (param_key), mismatch, null_match |
| `execution_score` | 0.0 / 1.0 |
| `execution_detail` | success, runtime_error, timeout |
| `composite_score` | 가중 합산 점수 |
| `time_ms` | 실행 시간 (ms) |
| `error` | 에러 메시지 (있을 경우) |

---

## 9. 파일 구조

```
Evaluation/SemanticValueAccuracy/
├── run_pipeline.py                  # 파이프라인 오케스트레이터 (--stage, --from-stage 지원)
├── config.py                        # 카테고리 목표 수, LLM 설정, 필터 임계값
├── stages/
│   ├── stage1_metadata.py           # DB 메타데이터 수집
│   ├── stage2_generate.py           # LLM 시맨틱 질의 생성 (5 카테고리)
│   ├── stage3_ground_truth.py       # GT 코드 생성 + VitalExecutor 실행 검증
│   ├── stage4_filter.py             # 4개 품질 필터
│   └── stage5_assemble.py           # 최종 데이터셋 조립 + 검증 리포트
├── prompts/
│   ├── semantic_query_gen.txt       # sem 카테고리 프롬프트
│   ├── cross_device_query_gen.txt   # xdev 카테고리 프롬프트
│   ├── cohort_signal_query_gen.txt  # cj 카테고리 프롬프트
│   ├── ontology_query_gen.txt       # onto 카테고리 프롬프트
│   ├── adversarial_semantic_gen.txt # adv 카테고리 프롬프트
│   ├── ground_truth_code_gen.txt    # GT 코드 생성 프롬프트
│   └── quality_audit.txt            # LLM 품질 감사 프롬프트
├── utils/
│   ├── vital_executor.py            # VitalExecutor (기존 재사용 또는 import)
│   ├── param_extractor.py           # 코드에서 사용 param_key 추출
│   └── scoring.py                   # 3-Layer 채점 로직
├── test_sva.py                      # 평가 실행 스크립트
└── output/
    ├── metadata_context.json        # Stage 1 출력
    ├── sva_candidates.jsonl         # Stage 2 출력 (전체 후보)
    ├── sva_verified.jsonl           # Stage 3 출력 (GT 검증 완료)
    ├── sva_filtered.jsonl           # Stage 4 출력 (필터 통과)
    ├── sva_dataset.jsonl            # Stage 5 최종 데이터셋
    ├── sva_validation_report.json   # Stage 5 검증 리포트
    └── sva_eval_YYYYMMDD_HHMMSS.xlsx  # 평가 결과 워크북
```

---

## 10. 기존 인프라 재사용

| 기존 모듈 | 위치 | SVA에서의 역할 |
| :--- | :--- | :--- |
| `VitalExecutor` | `Evaluation/ValueAccuracy/utils/vital_executor.py` | GT 코드 실행 검증, Claude CLI 코드 실행 |
| `compare_values()` | `Evaluation/ValueAccuracy/test_value_accuracy.py` | Layer 3 값 비교 |
| `get_llm_client()` | `shared/llm/client.py` | 질의 생성, GT 코드 생성, 품질 감사 |
| `Orchestrator.run()` | `OrchestrationAgent/src/orchestrator.py` | VitalAgent 시나리오 실행 |
| `track_names.csv` | `IndexingAgent/data/raw/Open_VitalDB_1.0.0/track_names.csv` | Stage 1 파라미터 레퍼런스 (196개 공식 정의) |
| `append_jsonl()` | Level1 유틸리티 | JSONL 저장 |
| Level1 resume 패턴 | `Evaluation/Level1/stages/` | Stage 2~3 checkpoint/resume |

---

## 11. 구현 로드맵

| 단계 | 작업 | 예상 소요 | 의존성 | 비고 |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1** | Stage 1 (메타데이터 수집) | 0.5일 | track_names.csv + .vital 파일 | CSV 파싱 + vitaldb로 track 목록 추출 |
| **Phase 2** | 프롬프트 설계 (5개 카테고리) | 1일 | Phase 1 출력 | 프롬프트가 데이터셋 품질의 핵심 |
| **Phase 3** | Stage 2 (질의 생성) | 0.5일 | Phase 2 | LLM 비용 ~$5-10 예상 |
| **Phase 4** | Stage 3 (GT 검증) | 0.5일 | Phase 3 | VitalExecutor 재사용 |
| **Phase 5** | Stage 4 (품질 필터링) | 0.5일 | Phase 4 | LLM 감사 비용 ~$2-3 |
| **Phase 6** | Stage 5 (조립) + test_sva.py (평가) | 1일 | Phase 5 | 3-Layer 채점 구현 |
| **Phase 7** | 첫 번째 평가 실행 + 결과 분석 | 0.5일 | Phase 6 | VitalAgent + Claude CLI 양쪽 실행 |
| | **합계** | **~4.5일** | | |

---

## 12. 기대 효과

### 12-1. VitalAgent 가치 정량화

현재 ValueAccuracy에서는 `VitalAgent 94% vs Claude CLI 92%`로 차이가 미미하다. SVA에서는 다음과 같은 격차를 기대한다:

| 카테고리 | VitalAgent 예상 | Claude CLI 예상 | 근거 |
| :--- | :---: | :---: | :--- |
| Semantic Resolution | 90%+ | 30-50% | Claude는 track 탐색 + 시맨틱 매핑을 한 번에 해야 함 |
| Cross-Device | 85%+ | 40-60% | Claude는 Cross-Device hierarchy 미보유 |
| Cohort-Signal Join | 90%+ | 10-30% | Claude는 코호트 CSV 존재/스키마를 사전에 모름 |
| Ontology | 80%+ | 20-40% | Claude는 concept_category 분류 정보 미보유 |
| Adversarial | 90%+ | 50-70% | VitalAgent는 parameter DB로 존재 여부 검증 가능 |

### 12-2. 파이프라인 병목 진단

3-Layer 채점을 통해 VitalAgent 내부의 병목을 정확히 진단할 수 있다:

- **Resolution은 높지만 Value가 낮다** → AnalysisAgent(코드 생성)에 문제
- **Resolution이 낮다** → ParameterResolver 또는 QueryUnderstanding에 문제
- **Execution이 낮다** → SandboxExecutor 또는 코드 안전성에 문제

### 12-3. FUTURE_WORK 연계

이 평가 결과는 `docs/FUTURE_WORK.md`의 Layer 1(PCO) 개선 효과를 직접 측정하는 벤치마크가 된다. PCO 도입 전후의 SVA 점수 비교를 통해 개선 효과를 정량화할 수 있다.
