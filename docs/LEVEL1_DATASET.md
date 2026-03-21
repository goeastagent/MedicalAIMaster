# Level 1 평가 데이터셋: Parameter Retrieval Benchmark

VitalAgent의 파라미터 검색 능력(Indexing & Retrieval)을 평가하기 위한 전용 데이터셋 설계 문서입니다.

---

## 1. 개요 (Overview)

### 1-1. 평가 목적

Level 1은 VitalAgent 평가 계층의 첫 번째 단계로, 자연어 질의가 주어졌을 때 에이전트가 해당 질의를 수행하는 데 필요한 **생체신호 파라미터를 올바르게 식별(retrieve)**하는 능력을 측정한다.

- **입력(Input):** 자연어 질의 $q$
- **출력(Expected Output):** 파라미터 집합 $P^* = \{p_1, p_2, ..., p_k\}$ (각 $p_i$는 `parameter` 테이블의 `param_key`)
- **평가 지표:** Set Recall, Precision, F1

> **지표 정의 — Set Recall vs. Recall@K:**
> 현재 ExtractionAgent의 `ParameterResolver`는 순위(ranking) 없이 매칭된 파라미터 집합을 반환한다. 순위 기반인 Recall@K는 검색 엔진처럼 순위가 있을 때 유효한 지표이므로, 여기서는 **Set Recall**을 기본 지표로 사용한다.
>
> - **Set Recall** = $|P_{retrieved} \cap P^*| / |P^*|$ (정답 파라미터 중 몇 개를 찾았는가)
> - **Precision** = $|P_{retrieved} \cap P^*| / |P_{retrieved}|$ (반환된 파라미터 중 실제 필요한 것의 비율)
> - **F1** = Set Recall과 Precision의 조화 평균
> - 단, 향후 시스템이 순위를 반환하도록 개선될 경우 Recall@K로 전환 가능

### 1-2. 왜 기존 벤치마크를 사용할 수 없는가

Text-to-SQL 및 코드 생성 분야에서는 Spider, BIRD, WikiSQL 등 다양한 공개 벤치마크가 존재한다. 그러나 이들은 다음과 같은 근본적인 이유로 생체신호 분석 도메인에 직접 적용할 수 없다.

| 기준 | 기존 벤치마크 (Spider, BIRD 등) | VitalAgent 도메인 |
| :--- | :--- | :--- |
| **데이터 형식** | 정형 테이블 (CSV, DB) | 고빈도 시계열 신호 (`.vital`, 최대 500Hz) |
| **파라미터 식별** | 컬럼명 = 파라미터명 (1:1 대응) | 장치/채널 계층 구조 (`Solar8000/HR`, `SNUADC/ECG_II`) |
| **질의 복잡도** | SELECT / JOIN / GROUP BY | 신호 전처리 → 조건 필터링 → 통계 연산 파이프라인 |
| **도메인 지식** | 범용 (영화, 스포츠, 전자상거래) | 수술실 생체신호 전문 (마취과학, 중환자의학) |
| **다중 소스** | 단일 DB 내 JOIN | vital 신호 + 임상 데이터 + 검사 결과 혼합 |
| **정답 형태** | 정적 값 (숫자, 문자열) | 동적 값 (데이터 업데이트 시 변화) |

**생체신호 도메인의 고유한 어려움 — 3가지 핵심 이유**

**① 파라미터 명칭의 비표준성 (Device Polymorphism)**

동일한 생리 지표가 제조사와 측정 방식에 따라 수십 가지 다른 이름으로 존재한다. 예를 들어 "Heart Rate"는 아래와 같이 다양하게 표현된다.

```
Solar8000/HR       — ECG-derived Heart Rate (Solar8000 monitor)
Solar8000/PLETH_HR — Plethysmography-derived Heart Rate (Solar8000 monitor)
CardioQ/HR         — Esophageal Doppler Heart Rate (CardioQ device)
Vigilance/HR_AVG   — Average Heart Rate (Edwards Vigilance)
```

이러한 장치별 다형성은 범용 NL2SQL 벤치마크에 존재하지 않는 고유한 검색 난이도를 형성한다.

**② 시계열 신호의 조건부 분석 (Cross-conditional Query)**

생체신호 분석의 핵심은 "A 신호가 특정 조건을 만족하는 구간에서 B 신호를 분석"하는 교차 조건부 질의이다. 이는 단순 SQL JOIN으로 표현할 수 없으며, 에이전트가 두 파라미터를 동시에 식별해야 한다.

```
e.g.: "Average HR during SpO2 < 90% episodes"
→ required_parameters: ["Solar8000/PLETH_SPO2", "Solar8000/HR"]
→ Classical Text-to-SQL cannot identify these parameters in the first place
```

**③ 전문 용어와 일상 표현 사이의 극단적 괴리**

의사가 사용하는 표현("hypoxemia episodes", "Hypotension episode")과 일반인 표현("when oxygen was low", "when BP dropped")이 동일한 `param_key`를 가리키지만 형태가 매우 달라, 범용 의미 검색 모델만으로는 해결이 어렵다.

### 1-3. 기존 방식의 시도 및 한계

본 연구 초기에는 VitalDB의 단일 케이스를 대상으로 단순 통계 질의에 대한 QA 쌍을 수동으로 구성하는 방식을 사용하였다.

초기 데이터셋 형태 (`vitaldb_low_qa_pairs.json`):

```json
{
  "question": "caseid가 1인 환자의 HR 최댓값을 구해주세요.",
  "answer": 139.0,
  "parameter": "Solar8000/HR"
}
```

이 방식은 다음 한계를 드러냈다.

| 한계 | 내용 |
| :--- | :--- |
| **단일 파라미터 편향** | 질의당 파라미터 1개로 고정 → 다중 파라미터 추론 능력 평가 불가 |
| **정적 정답 의존** | 데이터 업데이트 시 정답값이 변해 재검증 필요 |
| **파이프라인 평가 불가** | 최종 숫자 일치 여부만 측정 → 검색·계획·코드 생성 단계의 오류 진단 불가 |
| **도메인 다양성 부재** | 단순 통계(max/min/mean)에 국한 → 실제 임상 분석 시나리오 미반영 |

---

## 2. 소스 데이터 정의 (Source Data)

데이터셋 제작의 근거가 되는 원천 데이터는 IndexingAgent가 VitalDB를 분석하여 구축한 `parameter` 테이블과 실제 데이터 파일들이다.

### 2-1. `parameter` 테이블 구조

총 **260개의 파라미터**를 포함하며, LLM이 자동으로 부여한 semantic 정보를 함께 저장한다.

| 필드 | 설명 | 예시 |
| :--- | :--- | :--- |
| `param_key` | 시스템 내 고유 식별자 | `Solar8000/HR` |
| `semantic_name` | LLM이 부여한 의미적 이름 | `Heart Rate` |
| `unit` | 측정 단위 | `/min` |
| `concept_category` | 상위 카테고리 | `Vital Signs` |

### 2-2. 카테고리별 파라미터 분포

| 카테고리 | 파라미터 수 | 대표 파라미터 |
| :--- | :---: | :--- |
| Medication | 57 | `Orchestra/NEPI_RATE`, `Orchestra/PPF20_RATE` |
| Respiratory | 42 | `Solar8000/ETCO2`, `Primus/FIO2`, `Primus/TV` |
| Hemodynamics | 38 | `CardioQ/CO`, `EV1000/SVV`, `Solar8000/CVP` |
| Laboratory:Chemistry | 29 | `cr`, `na`, `lac`, `gluc` |
| **Vital Signs** | **22** | `Solar8000/HR`, `Solar8000/PLETH_SPO2`, `Solar8000/ART_SBP` |
| Device/Equipment | 16 | `FMS/FLOW_RATE`, `Primus/FLOW_O2` |
| Waveform/Signal | 14 | `SNUADC/ECG_II`, `SNUADC/ART`, `BIS/EEG1_WAV` |
| Anesthesia | 10 | `Orchestra/RFTN50_CE`, `BIS/BIS` |
| Neurological | 8 | `BIS/BIS`, `Invos/SCO2_L` |
| Surgical | 6 | `intraop_ebl`, `intraop_rbc` |
| 기타 | 18 | Demographics, Lab:Coagulation 등 |
| **합계** | **260** | |

### 2-3. Acceptable Alternatives 결정 기준

ground truth에서 `acceptable_alternatives`는 "정답 param_key 대신 이것을 반환해도 정답으로 인정"하는 집합이다. 아무 파라미터나 넣으면 평가가 무의미해지므로, 아래 세 조건을 **모두** 만족하는 경우에만 허용한다.

| 조건 | 설명 | 예시 |
| :--- | :--- | :--- |
| **① Same physiological indicator** | The measured physiological variable must be identical | HR → HR (different measurement principle is OK) |
| **② Actually exists in VitalDB** | Must be an existing param_key in the `parameter` table | Must verify `CardioQ/HR` exists |
| **③ Query context agnostic** | The query must not specify a particular device | "heart rate" is OK, "HR from the Solar8000 monitor" is not |

By condition ③, if a query specifies a device (e.g., "FIO2 from the Primus ventilator"), `acceptable_alternatives` is an empty set.

### 2-4. 데이터 소스 구조

```
vital_files/0001.vital ~ 6384.vital  — 6,384개 수술 케이스 연속 생체신호 (케이스당 1파일, 4자리 zero-padded)
clinical_data.csv                    — 케이스별 수술·마취 임상 정보 (수술 유형, 마취 방법 등)
lab_data.csv                         — 케이스별 시계열 검사 결과 (혈액 검사 등)
```

---

## 3. 질의 유형 분류 체계 (Query Taxonomy)

질의는 두 축으로 분류한다: **복잡도(Complexity)** 와 **표현 스타일(Expression Style)**.

### 3-1. 복잡도 기준

| 레벨 | 유형 | 설명 | 필요 파라미터 수 | 예시 질의 |
| :--- | :--- | :--- | :---: | :--- |
| Easy | Single-Direct | 파라미터명 직접 명시 | 1 | "What is the maximum HR value?" |
| Easy | Single-Semantic | 의미적 표현으로 지칭 | 1 | "What is the maximum heart rate?" |
| Medium | Single-Abbreviation | 의학 약어 또는 장치명 포함 | 1 | "What is the average BIS index?" |
| Medium | Multi-Independent | 두 파라미터를 독립적으로 동시 요청 | 2~3 | "Get the mean HR and SpO2 separately." |
| Hard | Multi-Conditional | A 파라미터 조건 구간에서 B 파라미터 분석 | 2~3 | "What is the mean HR when SpO2 < 90%?" |
| Hard | Cross-Source | vital 신호 + 임상/검사 데이터 결합 | 2+ | "Compare mean HR across general anesthesia cases." |

### 3-2. 표현 스타일 기준 (페르소나 기반)

| 스타일 | 특징 | 예시 |
| :--- | :--- | :--- |
| **Doctor** | 의학 전문 용어 | "Analyze the HR trend during hypotension episodes." |
| **Data Scientist** | 수식/통계 용어 | "Compute the IQR of HR where MAP < 65." |
| **Layperson** | 일상적인 풀어쓴 표현 | "How did the heart rate change when blood pressure dropped too low?" |

### 3-3. 의학적 연관 파라미터 쌍 (Multi-parameter 케이스용)

Multi-parameter 케이스 생성 시 활용할 연관 파라미터 쌍 목록이다. 의학적 연관성 유형별로 분류한다.

**Cardiopulmonary**

| Parameter A | Parameter B | Clinical Relationship |
| :--- | :--- | :--- |
| `Solar8000/PLETH_SPO2` | `Solar8000/HR` | Compensatory tachycardia during hypoxemia |
| `Solar8000/PLETH_SPO2` | `Primus/FIO2` | O2 supply-saturation response |
| `SNUADC/ECG_II` | `Solar8000/HR` | ECG waveform–heart rate validation |
| `Solar8000/ETCO2` | `Primus/TV` | EtCO2–tidal volume relationship |
| `Primus/ETCO2` | `Primus/FIO2` | Respiratory management correlation |

**Hemodynamic-Pharmacologic**

| Parameter A | Parameter B | Clinical Relationship |
| :--- | :--- | :--- |
| `Solar8000/ART_MBP` | `Orchestra/NEPI_RATE` | Norepinephrine response during hypotension |
| `Solar8000/ART_SBP` | `Orchestra/DOPA_RATE` | SBP–dopamine dose response |
| `Solar8000/ART_MBP` | `Orchestra/PHEN_RATE` | MAP–phenylephrine response |
| `Solar8000/ART_DBP` | `Solar8000/HR` | DBP–heart rate correlation |

**Anesthesia Depth**

| Parameter A | Parameter B | Clinical Relationship |
| :--- | :--- | :--- |
| `BIS/BIS` | `Orchestra/PPF20_CE` | Anesthesia depth–propofol effect-site concentration |
| `BIS/BIS` | `Orchestra/RFTN50_CE` | Anesthesia depth–remifentanil effect-site concentration |
| `BIS/BIS` | `Solar8000/HR` | Anesthesia depth–heart rate response |

**Surgical Outcome (Cross-Source)**

| Parameter A (vital) | Parameter B (clinical/lab) | Clinical Relationship |
| :--- | :--- | :--- |
| `Solar8000/ART_MBP` | `intraop_ebl` | Hypotension–blood loss association |
| `Solar8000/HR` | `intraop_ebl` | Hemorrhage-induced tachycardia response |
| `Solar8000/PLETH_SPO2` | `hb` | SpO2–hemoglobin association |
| `Solar8000/ART_MBP` | `intraop_crystalloid` | Fluid administration–MAP response |

---

## 4. 데이터셋 JSON 스키마

### 4-1. 스키마 정의

```json
{
  "id": "L1-001",
  "category": "vital_only",
  "difficulty": "easy",
  "query_style": "doctor",
  "num_required_params": 1,
  "query": "What is the maximum HR value for case ID 1?",
  "ground_truth": {
    "required_parameters": ["Solar8000/HR"],
    "acceptable_alternatives": {
      "Solar8000/HR": ["CardioQ/HR", "Vigilance/HR_AVG", "Solar8000/PLETH_HR"]
    },
    "param_source": "signal",
    "retrieval_notes": "HR is the most direct param_key representation"
  }
}
```

### 4-2. 멀티 파라미터 스키마 예시

```json
{
  "id": "L1-087",
  "category": "vital_only",
  "difficulty": "hard",
  "query_style": "data_scientist",
  "num_required_params": 2,
  "query": "What is the mean HR during SpO2 < 90% episodes?",
  "ground_truth": {
    "required_parameters": ["Solar8000/PLETH_SPO2", "Solar8000/HR"],
    "acceptable_alternatives": {
      "Solar8000/HR": ["CardioQ/HR", "Vigilance/HR_AVG"]
    },
    "param_source": "signal",
    "retrieval_notes": "Both the condition parameter (SpO2) and the analysis parameter (HR) must be identified"
  }
}
```

### 4-3. 적대적 케이스 스키마 예시

```json
{
  "id": "L1-ADV-003",
  "category": "adversarial",
  "difficulty": "hard",
  "query_style": "layperson",
  "num_required_params": 0,
  "query": "Show me the continuous blood glucose waveform.",
  "ground_truth": {
    "required_parameters": [],
    "expected_behavior": "not_found",
    "retrieval_notes": "Continuous glucose waveform parameter does not exist in DB"
  }
}
```

### 4-4. 메타데이터 필드 정의

| 필드 | 타입 | 허용값 |
| :--- | :--- | :--- |
| `id` | string | `L1-001` ~ `L1-150`, `L1-ADV-001` ~ |
| `category` | string | `vital_only` \| `vital+clinical` \| `vital+lab` \| `adversarial` |
| `difficulty` | string | `easy` \| `medium` \| `hard` |
| `query_style` | string | `doctor` \| `layperson` \| `data_scientist` |
| `param_source` | string | `signal` \| `tabular_clinical` \| `tabular_lab` \| `mixed` |
| `num_required_params` | int | 0, 1, 2, 3 ... |
| `expected_behavior` | string | `retrieve` \| `not_found` \| `clarify` |

---

## 5. LLM 자동 생성 파이프라인 (Construction Pipeline)

수동 작성의 한계(확장성 부재, 표현 다양성 부족)를 극복하기 위해 LLM 기반 자동 생성 파이프라인을 채택한다. 전체 흐름은 아래와 같다.

```
[Stage 1] 파라미터 코퍼스 자동 구성
     ↓
[Stage 2] 생성 배치 계획 (카테고리 × 스타일 조합)
     ↓
[Stage 3] LLM 기반 질의 후보 생성
     ↓
[Stage 4] Ground Truth 자동 레이블링
     ↓
[Stage 5] 품질 필터링 (4단계)
     ↓
[Stage 6] 적대적 케이스 생성
     ↓
[Output] level1_retrieval_dataset.json (150개)
```

---

### Stage 1: 파라미터 코퍼스 자동 구성

`parameter` 테이블을 쿼리하여 코퍼스 $\mathcal{P}$를 구성하고, **LLM을 이용해 각 파라미터의 동의어·약어 표현을 자동 생성**한다. `semantic_name`을 시드(seed)로 활용한다.

```python
# 자동화 쿼리
SELECT param_key, semantic_name, unit, concept_category
FROM parameter
WHERE concept_category IS NOT NULL;

# LLM synonym generation prompt (one call per parameter)
"""
Generate diverse English expressions for the following biosignal parameter
as used by doctors, data scientists, and laypersons.

param_key: Solar8000/HR
semantic_name: Heart Rate
unit: /min
category: Vital Signs

Output format (JSON):
{
  "direct": ["Solar8000/HR", "HR"],
  "semantic_en": ["Heart Rate", "pulse rate", "cardiac rate"],
  "medical_term": ["tachycardia threshold", "heart rate"],
  "abbreviation": ["HR", "HR bpm"]
}
"""
```

생성된 동의어 맵은 `synonym_map.json`으로 저장하여 Stage 3에서 재사용한다.

---

### Stage 2: 생성 배치 계획

목표 케이스 수를 카테고리 × 스타일 조합으로 분배한다. **각 셀당 최소 2개를 생성**하여 필터링 후 목표 수를 충족시킨다 (생성 수 = 목표 × 2).

| 유형 \ 스타일 | Doctor | Data Scientist | Layperson | 소계 |
| :--- | :---: | :---: | :---: | :---: |
| Single-Direct | 7 | 7 | 6 | 20 |
| Single-Semantic | 7 | 7 | 6 | 20 |
| Single-Abbreviation | 7 | 7 | 6 | 20 |
| Multi-Independent | 7 | 7 | 6 | 20 |
| Multi-Conditional | 10 | 10 | 10 | 30 |
| Cross-Source | 7 | 7 | 6 | 20 |
| **Adversarial** | — | — | — | **20** |
| **합계** | | | | **150** |

---

### Stage 3: LLM 기반 질의 후보 생성

각 배치 셀에 대해 LLM을 호출하여 질의 후보를 생성한다.

**사용 모델:** GPT-4o (temperature=0.8, 다양성 확보)

**핵심 프롬프트 구조:**

```
[System Prompt]
You are a test data generator for a medical AI system that analyzes intraoperative biosignal data.
Generate natural language queries in English that match the given parameter and style conditions.

[Constraints]
- query_type: {type}
- query_style: {style}
- required_parameters: {list of param_keys}
- Do not expose raw param_key format (e.g., Solar8000/HR) in the query (except for Single-Direct type)
- caseid can be any integer value between 1 and 10
- Write in English only

[Parameter Information]
{synonym list for the param_key from synonym_map}

[Output Format — JSON]
{
  "query": "generated natural language query",
  "required_parameters": ["param_key_1", "param_key_2"],
  "query_style": "doctor|data_scientist|layperson",
  "generation_notes": "rationale or intent for the generated query"
}

[Include 2 few-shot examples]
```

**Few-shot 예시 (Multi-Conditional, Doctor 스타일):**

```json
[
  {
    "query": "What is the mean norepinephrine infusion rate during intraoperative hypotension (MAP < 65 mmHg)?",
    "required_parameters": ["Solar8000/ART_MBP", "Orchestra/NEPI_RATE"],
    "query_style": "doctor"
  },
  {
    "query": "Analyze the heart rate trend during SpO2 desaturation episodes (< 90%).",
    "required_parameters": ["Solar8000/PLETH_SPO2", "Solar8000/HR"],
    "query_style": "doctor"
  }
]
```

---

### Stage 4: Ground Truth 자동 레이블링

생성된 질의 후보에 대해 ground truth를 자동으로 구성한다.

```python
def build_ground_truth(query_candidate: dict) -> dict:
    required_params = query_candidate["required_parameters"]

    # Determine acceptable_alternatives (implements the 3 conditions from Section 2-3)
    alternatives = {}
    for param in required_params:
        category = get_category(param)           # query parameter table
        same_category_params = get_params_by_category(category)  # same category
        same_physio = filter_same_physiology(param, same_category_params)  # same physiological indicator
        existing = filter_existing_in_db(same_physio)            # verify existence in DB
        if not is_device_specific(query_candidate["query"], param):  # device not specified in query
            alternatives[param] = existing - {param}

    return {
        "required_parameters": required_params,
        "acceptable_alternatives": alternatives,
        "param_source": infer_param_source(required_params),
        "expected_behavior": "retrieve"
    }
```

---

### Stage 5: 품질 필터링 (4단계)

생성된 후보에 대해 4개의 필터를 순차 적용한다. **통과 기준을 모두 충족한 케이스만 최종 데이터셋에 포함**한다.

**Filter 1: param_key 노출 검사**

Single-Semantic / Single-Abbreviation / Layperson 스타일 케이스에서 param_key 형식이 질의 텍스트에 그대로 포함되면 제거한다.

```python
import re
def check_param_exposure(query: str, required_params: list, query_type: str) -> bool:
    if query_type == "Single-Direct":
        return True  # Single-Direct allows raw param_key exposure
    pattern = r'\b[A-Za-z0-9]+/[A-Za-z0-9_]+\b'
    exposed = re.findall(pattern, query)
    return len(exposed) == 0  # pass if no raw param_key exposed
```

**Filter 2: 의미적 중복 제거**

기존 수집된 케이스와의 코사인 유사도를 계산하여 임계값 이상이면 제거한다. 임베딩 모델은 `text-embedding-3-small`을 사용한다.

```python
DEDUP_THRESHOLD = 0.85

def is_duplicate(new_query: str, existing_queries: list) -> bool:
    new_emb = embed(new_query)
    for existing in existing_queries:
        if cosine_similarity(new_emb, embed(existing)) > DEDUP_THRESHOLD:
            return True
    return False
```

**Filter 3: 파라미터 커버리지 균형 검사**

특정 파라미터에 질의가 과도하게 몰리는 것을 방지한다. 각 `param_key`당 최대 출현 허용 횟수를 설정한다.

```python
MAX_PER_PARAM = 8   # each param_key may appear in at most 8 cases

def check_coverage_balance(param: str, coverage_counter: dict) -> bool:
    return coverage_counter.get(param, 0) < MAX_PER_PARAM
```

**Filter 4: LLM 의학적 타당성 검사**

최종 후보에 대해 LLM judge로 의학적 타당성을 확인한다. (temperature=0, 재현성 확보)

```
[Validation Prompt]
Determine whether the following query and parameter mapping are medically valid.

Query: "{query}"
Required parameters: {required_parameters}

Criteria:
1. Is the combination of parameters clinically meaningful?
2. Is there a logical connection between the query and the parameters?
3. Is the query likely to occur in a real clinical setting?

Output: {"valid": true/false, "reason": "justification"}
```

---

### Stage 6: 적대적 케이스 생성

적대적 케이스는 정상 케이스를 변형하는 방식으로 자동 생성한다.

| 유형 | 생성 방법 | 기대 동작 |
| :--- | :--- | :--- |
| **Ambiguous** | LLM removes parameter hints from a normal query ("HR when MAP < 65" → "How was the status at that point?") | `clarify` |
| **Impossible** | LLM generates queries for physiological signals not present in the `parameter` table (e.g., continuous glucose waveform, temperature waveform) | `not_found` |
| **Confusing** | Uses param_keys where the same physiological indicator exists across multiple devices; generates queries without specifying a device | `clarify` |

```python
# Confusing 케이스 자동 탐지 (DB에서 자동 추출)
"""
SELECT semantic_name, COUNT(DISTINCT param_key) as cnt, 
       array_agg(param_key) as param_keys
FROM parameter
GROUP BY semantic_name
HAVING COUNT(DISTINCT param_key) > 1
ORDER BY cnt DESC;
-- Example results: Heart Rate → [Solar8000/HR, CardioQ/HR, Vigilance/HR_AVG, Solar8000/PLETH_HR]
--                  End-tidal CO2 → [Solar8000/ETCO2, Primus/ETCO2]
"""
```

---

### Stage 7: 최종 검수

자동 생성 완료 후 아래 항목을 일괄 검증한다.

```python
def final_validation(dataset: list) -> dict:
    results = {
        "total": len(dataset),
        "param_coverage": count_unique_params(dataset),      # number of unique param_keys used
        "category_distribution": count_by_category(dataset), # distribution by category
        "style_distribution": count_by_style(dataset),       # distribution by style
        "db_existence_check": verify_all_params_in_db(dataset), # verify all params exist in DB
        "dedup_check": check_no_duplicates(dataset),         # verify no duplicates
    }
    return results
```

**최소 통과 기준:**
- 사용된 고유 `param_key` 수 ≥ 40개 (260개 중 15% 이상 커버)
- 각 카테고리에서 최소 1개 이상의 케이스 포함
- 3가지 스타일이 각각 전체의 25~40% 범위 내
- DB 존재 확인 100% 통과

---

## 6. 최종 데이터셋 구성 목표

| 카테고리 | 유형 | 목표 케이스 수 |
| :--- | :--- | :---: |
| vital_only | Single-Direct / Single-Semantic | 40 |
| vital_only | Single-Abbreviation / Medical-term | 20 |
| vital_only | Multi-Independent | 20 |
| vital_only | Multi-Conditional | 30 |
| vital+clinical / vital+lab | Cross-Source | 20 |
| adversarial | Ambiguous / Impossible / Confusing | 20 |
| | **합계** | **150** |

---

## 7. 성능 평가 테이블

> **주의: 아래는 실험 실행 후 채워야 할 양식입니다.** 현재 수치는 모두 미측정(`—`) 상태입니다.

### 비교 기준선 (Baselines)

| Baseline | 설명 |
| :--- | :--- |
| **Baseline A (키워드 매칭)** | LLM 없이 ILIKE 키워드 검색만 사용 |
| **Baseline B (현재 시스템)** | LLM + ILIKE 조합 (ExtractionAgent 전체 파이프라인) |

### 7-1. 메인 테이블 — 질의 유형별 Retrieval 성능

| Query Category | # Cases | Set Recall | Precision | F1 |
| :--- | :---: | :---: | :---: | :---: |
| Single-Direct | 20 | — | — | — |
| Single-Semantic | 20 | — | — | — |
| Single-Abbreviation | 20 | — | — | — |
| Multi-Independent | 20 | — | — | — |
| Multi-Conditional | 30 | — | — | — |
| Cross-Source | 20 | — | — | — |
| Adversarial | 20 | — | — | — *(rejection rate)* |
| **Overall** | **150** | — | — | — |

### 7-2. 서브 테이블 — 표현 스타일별 성능 격차

| Query Style | Set Recall | Δ vs. Baseline B |
| :--- | :---: | :---: |
| Doctor (medical terminology) | — | — |
| Data Scientist (formulas/conditions) | — | — |
| Layperson (plain language) | — | — |

### 7-3. 테이블 해석 지침

- **Set Recall degradation slope** → retrieval failure rate as query complexity increases
- **Baseline A vs. B gap** → practical contribution of the LLM semantic understanding component
- **Layperson style performance drop** → evidence for the need to strengthen semantic matching
- **Adversarial rejection rate** → system safety indicator; measures how often the system avoids proceeding with incorrect parameters

---

## 8. 데이터셋 저장 경로

```
testdata/
└── level1_retrieval_dataset.json   ← 최종 150개 케이스
```
