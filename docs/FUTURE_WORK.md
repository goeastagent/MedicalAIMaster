# Future Work

---

# Part A. 평가 기반 파이프라인 품질 개선

> **기준 평가일**: 2024-03-24 (Level1 / Temporal / ValueAccuracy 최신 결과 기반)
>
> 이 섹션은 3개 평가 벤치마크의 오류를 심층 분석하여 도출한 **현재 파이프라인의 구조적 문제점**과 **4-Layer 개선 체계**를 기술합니다. 장기적인 자율형 에이전트 전환(Part B)과는 독립적으로 진행할 수 있습니다.

## A-1. 현재 성적표

| 평가 | 지표 | VitalAgent | Claude-Code-CLI | 비고 |
|---|---|---|---|---|
| **Level1** (파라미터 추출, 141건) | F1 | **0.748** | 0.580 | VitalAgent 우위 |
| | Recall | 0.770 | 0.599 | |
| | Precision | 0.753 | 0.571 | |
| | Adversarial 정확도 | 40% (8/20) | 40% (8/20) | 양쪽 모두 낮음 |
| **Temporal** (시간범위 쿼리, 20건) | Numeric Accuracy | **100%** | 100% | 동일 |
| | Ambiguity Pass Rate | **0%** (0/5) | 20% (1/5) | 치명적 약점 |
| **ValueAccuracy** (값 정확도, 50건) | Accuracy | **94%** | 92% | VitalAgent 우위 |
| | Avg Latency (ms) | 15,274 | 10,242 | VitalAgent 느림 |

## A-2. 문제 진단: 5가지 핵심 이슈

### 이슈 1. Cross-Device 파라미터 혼동

- **심각도**: HIGH
- **영향**: Level1에서 11건 완전 실패 (F1=0.0)
- **현상**: 동일한 생리학적 개념이 Solar8000(환자 모니터)과 Primus(마취기) 양쪽에 존재할 때, 시스템이 일관되지 않게 잘못된 디바이스의 파라미터를 선택한다.

| 쿼리 개념 | 기대값 | 실제 반환 | 패턴 |
|---|---|---|---|
| Ventilator FiO2 | `Solar8000/VENT_SET_FIO2` | `Primus/SET_FIO2` | Primus 과선호 |
| Mean Airway Pressure (2건) | `Solar8000/VENT_MAWP` | `Primus/MAWP_MBAR` | Primus 과선호 |
| Tidal Volume | `Solar8000/VENT_TV` | `Primus/TV` | Primus 과선호 |
| Peak Inspiratory Pressure | `Solar8000/VENT_SET_PCP` | `Primus/SET_PIP` | Primus 과선호 |
| Plateau Pressure | `Solar8000/VENT_PPLAT` | `Primus/PPLAT_MBAR` | Primus 과선호 |
| Minute Volume | `Primus/MV` | `Solar8000/VENT_MV` | 반대 방향도 발생 |

- **근본 원인**: ParameterResolver의 LLM 프롬프트에 "호흡/환기 파라미터 → Primus 선호" 규칙이 있지만, `Solar8000/VENT_*` 접두사 파라미터(환자 모니터가 보고하는 환기 데이터)와 `Primus/*`(마취기 자체 측정)를 구분하는 규칙이 없다. LLM이 이 규칙을 확률적으로 해석하므로 같은 유형의 쿼리에서도 결과가 달라진다.
- **왜 프롬프트 수정만으로 부족한가**: 프롬프트에 규칙을 추가해도 LLM은 확률적이므로, 디바이스 간 같은 개념의 파라미터가 늘어날수록 불일치율이 비례해서 증가한다. 결정적(deterministic)인 매핑 체계가 필요하다.

### 이슈 2. Adversarial 쿼리 오분류

- **심각도**: HIGH
- **영향**: 20건 중 12건 실패 (40% 정확도)
- **현상**: 두 가지 실패 패턴이 존재한다.

**패턴 A — 존재하지 않는 파라미터를 `clarify`로 오분류 (6건)**

| 쿼리 | 기대 | 감지 |
|---|---|---|
| "skin conductance levels" | `not_found` | `clarify` |
| "synovial fluid pressure" | `not_found` | `clarify` |
| "bladder pressure" | `not_found` | `clarify` |
| "cardiac output (esophageal Doppler)" | `not_found` | `clarify` |
| "electrolyte balance levels" | `not_found` | `clarify` |
| "cerebral blood flow velocity" | `not_found` | `clarify` |

근본 원인: `ParameterResolverNode`의 zero-match 분기 로직이 단일 조건문에 의존한다.

```python
# node.py:89-90 — 현재 로직
is_vague = any(cat in ["Unknown", "Other"] for cat in expected_categories)
mode = "clarify" if is_vague else "not_found"
```

QueryUnderstanding LLM이 "bladder pressure"같은 구체적이지만 DB에 없는 의학 용어도 `"Unknown"` 카테고리로 태깅하기 때문에, `not_found`가 아닌 `clarify`로 분류된다. 이 단일 조건문은 **"모호한 요청"과 "구체적이지만 우리 DB에 없는 요청"을 구분하지 못한다.**

**패턴 B — 부분 정보 쿼리를 무분별하게 retrieve (6건)**

| 쿼리 | 기대 | 감지 | 반환 |
|---|---|---|---|
| "end-tidal CO2 during the last hour" | `clarify` | `retrieve` | `Primus/ETCO2` |
| "inspiratory CO2 trends for patient 12" | `clarify` | `retrieve` | `Primus/INCO2` |
| "breathing gas CO2 from the procedure" | `clarify` | `retrieve` | `Primus/ETCO2` |

근본 원인: ParameterResolver는 파라미터 매칭만 수행하고, 시간 조건("last hour")이나 환자 참조("patient 12")의 유효성을 검증하지 않는다. CO2 파라미터가 DB에 존재하므로 바로 `retrieve`를 반환한다.

### 이슈 3. Over-Extraction (과잉 파라미터 반환)

- **심각도**: MEDIUM
- **영향**: Level1에서 11건 정밀도(precision) 저하
- **현상**: 정답 파라미터를 포함하지만, 불필요한 관련 파라미터를 함께 반환한다.

| 패턴 | 예시 쿼리 | 기대 | 실제 반환 |
|---|---|---|---|
| ECG 리드 과잉 | "heart's electrical signals" | `ECG_V5` | `ECG_II, ECG_V5` |
| NIBP 과잉 | "NIBP reading" | `NIBP_MBP` | `NIBP_SBP, NIBP_DBP, NIBP_MBP` |
| 약물 관련 과잉 | "propofol pharmacokinetic parameters" (BIS < 40 조건) | `PPF20_CE` | `PPF20_CE, PPF20_CP, PPF20_CT, PPF20_RATE, PPF20_VOL` |
| BIS 서브메트릭 과잉 | "BIS signal quality" | `BIS/SQI` | `BIS/BIS, BIS/EMG, BIS/SEF, BIS/SQI, BIS/SR, BIS/TOTPOW` |

- **근본 원인**: Resolver 프롬프트의 "If multiple leads exist for the same signal type, select all" 규칙이 너무 광범위하게 적용된다. 이 규칙에 상한이 없어 관련 파라미터를 모두 끌어온다.
- **왜 문제인가**: 과잉 파라미터는 후속 AnalysisAgent의 코드 생성을 복잡하게 만들고, 불필요한 데이터 로딩으로 레이턴시가 증가한다.

### 이슈 4. Temporal Ambiguity 미처리

- **심각도**: CRITICAL
- **영향**: 5/5 모호한 시간 쿼리 전부 FAIL (Pass Rate 0%)
- **현상**: 필수 정보(caseid, 정확한 시간 범위 등)가 누락된 쿼리에 대해, 시스템이 아무런 확인 없이 임의로 가정하고 숫자 답변을 반환한다.

| 쿼리 | 누락 정보 | 시스템 응답 |
|---|---|---|
| "Average HR during the first 10 minutes?" | caseid, sampling rate, NaN handling | `83.59` (바로 반환) |
| "Max BIS/EMG near the end of recording?" | caseid, "near end" 정의 | `63.74` (바로 반환) |
| "Median FIO2 between two specific times?" | caseid, 실제 시간 범위 | `38.0` (바로 반환) |

- **근본 원인 (아키텍처 결함)**: Orchestrator에 **파이프라인 중단 메커니즘이 없다.** 코드를 추적하면:
  1. `OrchestratorConfig.auto_resolve_ambiguity = True`가 기본값이지만, 이 플래그는 **코드에서 실제로 소비되지 않는다** (dead config).
  2. `Orchestrator._run_extraction()`은 ambiguities를 추출하지만, 이를 확인하는 분기 없이 바로 Step 2(Data Load)로 진행한다.
  3. ExtractionAgent가 ambiguity를 감지해도, 파이프라인은 멈추지 않고 끝까지 실행된다.
  4. AnalysisAgent는 누락된 caseid를 첫 번째 케이스로 자동 선택하고, 모호한 시간 표현을 임의 해석하여 계산을 완료한다.
  5. 최종 결과에 어떤 가정(assumption)도 명시되지 않는다.

### 이슈 5. ValueAccuracy 부동소수점 정밀도

- **심각도**: LOW
- **영향**: 3건 실패 (94% → 잠재적 100%)
- **현상**: 쿼리에 "Round to 2 decimal places"라고 명시했지만, 에이전트가 raw float를 반환한다.

| 케이스 | 기대값 | 실제값 | 절대 오차 | 원인 |
|---|---|---|---|---|
| va_base_003 | 14.79 | 14.800000190734863 | 0.01 | float32 정밀도 + 반올림 미적용 |
| va_base_013 | 14.79 | 14.800000190734863 | 0.01 | 동일 (같은 쿼리 변형) |
| va_cond_009 | 5621.38 | 5621.3798828125 | 0.0001 | float32 소수점 잔여 |

- **근본 원인 (이중)**: (1) VitalDB 데이터가 float32로 저장되어 `std()` 등의 계산에서 float64 대비 미세한 차이 발생. (2) AnalysisAgent의 CodeGenerator가 쿼리의 반올림 지시를 코드에 반영하지 않아 raw float를 그대로 반환. (3) `compare_values()`가 절대 오차 `1e-5`로 비교하여 0.01 차이도 실패로 처리 (Temporal 평가의 상대 오차 `1e-2`와 불일치).

## A-3. 구조적 결함 분석: 왜 프롬프트 패치로는 해결되지 않는가

위 5가지 이슈를 관통하는 **3가지 구조적 결함**이 있다:

| 구조적 결함 | 설명 | 영향받는 이슈 |
|---|---|---|
| **지식이 LLM 프롬프트에만 인코딩됨** | Cross-device 우선순위, CE/CT 구분, 파라미터 관계 등이 자연어 프롬프트 안에만 존재. LLM은 이를 확률적으로 해석하므로 동일 쿼리에서도 결과가 달라질 수 있다. | 이슈1, 이슈3 |
| **파이프라인이 항상 끝까지 실행됨** | Ambiguity를 감지해도 멈추지 않고 임의 가정으로 결과를 반환한다. Orchestrator에 gate/halt 메커니즘이 없다. | 이슈4, 이슈2(패턴B) |
| **분류 경계가 단일 조건문** | `not_found` vs `clarify` 판단이 `expected_categories`의 `"Unknown"` 포함 여부 한 줄에 의존한다. 구체적 의학 용어와 모호한 일반 표현을 구분하지 못한다. | 이슈2(패턴A) |

## A-4. 제안: 4-Layer 개선 체계

현재 LangGraph 파이프라인의 노드 구조를 유지하면서, 4개의 구조적 레이어를 추가한다.

```
현재 파이프라인:
  [100] QueryUnderstanding → [200] ParameterResolver → [300] PlanBuilder
  → Orchestrator → AnalysisAgent

개선 파이프라인:
  [100] QueryUnderstanding
  → [150] QueryCompletenessGate          ← Layer 2 (NEW)
  → [200] ParameterResolver + PCO        ← Layer 1 (ENHANCED)
  → [300] PlanBuilder
  → Orchestrator.ConfidenceGate          ← Layer 3 (NEW)
  → AnalysisAgent
  → OutputPostProcessor                  ← Layer 4 (NEW)
```

### Layer 1. Parameter Concept Ontology (PCO)

- **해결 대상**: 이슈1(Cross-device), 이슈2 패턴A(not_found), 이슈3(Over-extraction)
- **핵심 아이디어**: LLM이 개별 `param_key`를 직접 선택하는 대신, **"개념(Concept)"만 식별**하고, 구조화된 온톨로지가 **결정적으로** `param_key`를 매핑한다.

**동작 원리:**

```
LLM: "이 쿼리는 Tidal Volume 개념을 요청합니다" (concept만 식별)
  ↓
PCO Lookup: "Tidal Volume" → {
    Solar8000/VENT_TV (measured, primary, context: ventilator/monitoring),
    Primus/TV         (measured, secondary, context: anesthesia),
    Primus/SET_TV     (setting, tertiary, context: target/setting),
}
  ↓
Context Scoring: 쿼리에 "ventilator" 키워드 없음 → primary 기본 선택 → Solar8000/VENT_TV
```

**구현 위치**: `shared/data/parameter_ontology.py` (새 모듈)

**PCO가 해결하는 세부 문제:**

- **Cross-device**: 각 concept에 device별 priority가 정의되어 있으므로, LLM의 확률적 판단에 의존하지 않음
- **Over-extraction**: concept 단위로 결과를 반환하므로 "Heart Rate" → `Solar8000/HR` 1개만 반환. ECG_V5 등은 별도 concept ("ECG Waveform")으로 분리됨
- **CE vs CT**: "Propofol Concentration" concept 내에서 measurement_type으로 CE(measured) vs CT(target) 구분
- **not_found 판별**: PCO가 의학 개념 사전 역할을 겸하여, "synovial fluid pressure"가 유효한 의학 용어이지만 DB에 없는 경우 → `not_found` (concept은 존재하지만 매핑된 param_key 없음)

**PCO 구축**: IndexingAgent가 이미 구축한 PostgreSQL `parameter` 테이블(param_key, semantic_name, unit, concept_category)에서 자동 생성. 같은 `semantic_name`을 공유하는 param_key들을 하나의 concept으로 그룹핑하고, device 접두사와 `SET_`/`VENT_` 패턴으로 measurement_type과 priority를 자동 추론한다. 이후 평가 결과 피드백으로 priority를 점진적 보정 가능.

### Layer 2. Query Completeness Gate (LangGraph 노드 [150])

- **해결 대상**: 이슈4(Temporal ambiguity), 이슈2 패턴B(부분 정보 쿼리)
- **핵심 아이디어**: ExtractionAgent 파이프라인에 새 노드를 추가하여, QueryUnderstanding 결과의 **필수 슬롯 충족 여부를 검증**하고, 누락 시 파이프라인을 중단한다.

**LangGraph 조건부 엣지 활용:**

```
[100] QueryUnderstanding
  → [150] CompletenessGate
      → if complete:   → [200] ParameterResolver (기존 흐름)
      → if incomplete: → END (clarification_needed 반환)
```

**검증 항목:**

| 슬롯 | 검증 내용 | 실패 시 |
|---|---|---|
| `parameter` | requested_parameters가 비어있지 않은가 | "어떤 측정값을 찾고 계신가요?" |
| `entity_id` | 시간 범위 쿼리에서 caseid가 지정되었는가 | "어떤 케이스를 분석할까요?" |
| `time_range` | 시간 키워드가 있는데 temporal_context가 해석되지 않았는가 | "정확한 시간 범위를 지정해주세요" |
| `entity_exists` | 참조된 환자/케이스가 DB에 존재하는가 | "해당 환자를 찾을 수 없습니다" |

**Temporal Ambiguity 해결 원리**: "Average HR during the first 10 minutes?" → CompletenessGate가 temporal intent를 감지하지만 caseid 없음 → `missing_slots = [entity_id]` → 파이프라인 중단, clarification 반환.

**ADV 패턴B 해결 원리**: "end-tidal CO2 during the last hour" → "last hour"가 temporal intent이지만 해석 불가 → `missing_slots = [time_range]` → 파이프라인 중단.

### Layer 3. Orchestrator Confidence Gate

- **해결 대상**: 이슈4(파이프라인이 멈추지 않는 근본 문제)
- **핵심 아이디어**: Orchestrator의 `run()` 메서드에서 ExtractionAgent 결과의 ambiguity/confidence를 확인하고, 조건 미충족 시 Analysis로 진행하지 않는다.

**변경 위치**: `OrchestrationAgent/src/orchestrator.py` 의 `run()` 메서드

**핵심 로직:**

```python
# Step 1: Extraction 실행 후
ambiguities = extraction_result.get("ambiguities", [])

if ambiguities and not self.config.auto_resolve_ambiguity:
    return OrchestrationResult(
        status="clarification_needed",     # 새 status 값
        ambiguities=ambiguities,
        result=format_clarification(ambiguities),
    )
# ambiguity가 없을 때만 Step 2, 3 진행
```

**필요한 추가 변경:**
- `OrchestrationResult.status`에 `"clarification_needed"` 값 추가
- `OrchestratorConfig.auto_resolve_ambiguity` 플래그를 실제로 소비하는 코드 구현 (현재 dead config)
- 평가 환경에서는 `auto_resolve_ambiguity=False`로 설정하여 모호한 쿼리 자동 차단

### Layer 4. Output Post-Processor

- **해결 대상**: 이슈5(부동소수점 정밀도, 반올림 미적용)
- **핵심 아이디어**: AnalysisAgent 실행 후 결과를 검증하고 정리하는 후처리 단계 추가. 쿼리에 명시된 반올림 지시를 결정적으로 적용한다.

**구현 위치**: `AnalysisAgent/src/postprocessor.py` (새 모듈)

**처리 항목:**

| 단계 | 내용 | 예시 |
|---|---|---|
| 반올림 감지 | 쿼리에서 "Round to N decimal places" 패턴 추출 | "Round to 2 decimal places" → `round(result, 2)` |
| float32 정리 | numpy float32 → Python float64 변환 | `14.800000190734863` → `14.8` |
| 정수 변환 | "Return as an integer" 감지 시 int 캐스팅 | `178.0` → `178` |

**Orchestrator 통합**: `_run_analysis()` 반환값에 post-processor 적용 (5줄 추가).

## A-5. 구현 우선순위

| 순위 | Layer | 구현 난이도 | 예상 효과 | 코드 변경 범위 |
|---|---|---|---|---|
| 1 | **Layer 3** (Orchestrator Gate) | 낮음 (1일) | Temporal 0%→80%+, ADV 패턴B 6건 수정 | `orchestrator.py` ~20줄, `models.py` status 추가 |
| 2 | **Layer 4** (PostProcessor) | 낮음 (1일) | VA 94%→100% | 새 파일 1개 + `orchestrator.py` ~5줄 |
| 3 | **Layer 2** (Completeness Gate) | 중간 (2일) | Temporal 완전 해결, ADV 패턴B 추가 수정 | 새 LangGraph 노드 + `graph.py` conditional edge |
| 4 | **Layer 1** (PCO) | 높음 (3-5일) | L1 F1 0.75→0.90+, 장기 안정성 확보 | 새 모듈 + ParameterResolver 리팩토링 |

**전체 개선 시 예상 성적:**

| 평가 | 현재 | 목표 |
|---|---|---|
| Level1 F1 | 0.748 | 0.90+ |
| Level1 Adversarial | 40% | 85%+ |
| Temporal Ambiguity Pass | 0% | 80%+ |
| ValueAccuracy | 94% | 100% |

---
---

# Part B. 자율형 데이터 에이전트 아키텍처 (장기 방향)

## B-1. 개요 및 핵심 목표
현재 MedicalAIMaster(VitalAgent)는 대용량 의료 데이터를 안정적으로 처리하기 위한 **"사전 구축(Pre-built) 중심의 파이프라인"**으로 훌륭하게 설계되어 있습니다. 
하지만 궁극적인 지향점인 **"폴더만 지정하면 알아서 파일에 접근하고 파악하여 분석을 진행하는 자율형 데이터 분석가(Autonomous Data Analyst)"**로 진화하기 위해서는 아키텍처의 패러다임 전환이 필요합니다.

이 문서는 현재의 폭포수(Waterfall) 파이프라인 구조를 **"도구 기반의 순환(Loop) 구조"**로 개편하기 위한 심층적인 업그레이드 방향과 로드맵을 정의합니다.

---

## B-2. 현재 아키텍처의 한계점 진단

1. **동적 대응 부족**: 파일이 폴더에 새로 추가되었을 때, `IndexingAgent`의 사전 DB 인덱싱이 완료되지 않으면 에이전트가 해당 파일을 인지하거나 분석할 수 없습니다.
2. **시야의 단절 (Blind Coding)**: `ExtractionAgent`와 `AnalysisAgent`가 실제 파일의 원본 데이터를 열어보지 못하고, DB에 요약된 메타데이터에만 의존하여 코드를 생성합니다. 이로 인해 실제 데이터의 결측치(NaN)나 예상치 못한 스키마 변형에 유연하게 대처하지 못하고 런타임 에러가 발생할 확률이 높습니다.
3. **단방향 실행 (One-shot Generation)**: 코드를 한 번에 생성하고 끝내는 방식이므로, 실제 데이터 분석가처럼 데이터를 "탐색(EDA)"하며 점진적으로 인사이트를 도출해 나가는 과정이 불가능합니다.

---

## B-3. 추천 아키텍처: 자율 탐색형 데이터 에이전트 (Autonomous Data Agent)

새로운 아키텍처는 다음 3가지 핵심 계층(Layer)으로 구성됩니다.

### 계층 1: 동적 작업 공간 (Dynamic Workspace & File System Tools)
DB에 전적으로 의존하는 대신, 에이전트가 폴더(File System) 자체를 자신의 작업 공간으로 인식하고 직접 탐색할 수 있는 도구를 제공합니다.
* **제공 도구(Tools)**:
  * `list_files(directory_path)`: 폴더 내 파일 목록, 용량, 확장자 확인
  * `peek_file(file_path, n_rows=5)`: 파일의 처음 몇 줄을 읽어 실제 데이터 구조 파악
  * `search_files(keyword)`: 특정 키워드가 포함된 파일명이나 헤더 검색
* **역할 변화**: 기존 `IndexingAgent`는 파이프라인의 필수 선행 단계가 아닌, 대용량 폴더 분석 시 에이전트가 스스로 호출하는 **백그라운드 요약 도구**로 역할이 변경됩니다.

### 계층 2: 상태 유지형 코드 실행기 (Stateful Code Interpreter / REPL)
코드를 한 번에 생성하고 끝내는 것이 아니라, Jupyter Notebook처럼 **상태(메모리, 변수)가 유지되는 환경**에서 에이전트가 코드를 반복 실행하며 데이터를 만져볼 수 있게 합니다.
* **작동 방식**:
  1. 데이터를 로드하는 코드 실행 (`df = pd.read_csv(...)`)
  2. 실행 결과(스키마, 샘플 데이터)를 관찰
  3. 관찰 결과를 바탕으로 전처리 및 분석 코드 작성 및 실행
  4. 에러 발생 시 스스로 원인을 파악하고 코드를 수정하여 재실행 (Self-Correction)

### 계층 3: 오케스트레이터의 ReAct (Reasoning + Acting) 루프 전환
현재의 단방향 `OrchestrationAgent`를 LangGraph의 `AgentExecutor` 패턴 등을 활용하여 **ReAct 프레임워크 기반의 메인 브레인**으로 격상시킵니다.
* 에이전트가 사용자 질의를 받으면 스스로 **[생각 -> 도구 선택 -> 실행 -> 결과 관찰 -> 다시 생각]**의 과정을 정답이 도출될 때까지 무한히 반복합니다.

---

## B-4. 실제 작동 시나리오 예시

**사용자 질의:** *"data 폴더에 있는 파일들을 보고, 수술 중 심박수가 가장 불안정했던 환자를 찾아서 이유를 분석해줘."*

1. **탐색 (Discovery)**: `list_files("data/")` 도구를 호출하여 `.vital` 파일들과 `clinical_info.csv`를 발견.
2. **스키마 파악 (Peeking)**: `execute_python_code` 도구를 통해 첫 번째 `.vital` 파일의 트랙 목록을 출력하여 데이터 구조 확인.
3. **반복 분석 (Iterative Analysis)**: 
   * 모든 환자의 심박수 분산을 계산하는 코드를 작성 및 실행.
   * 특정 파일에서 데이터 누락으로 에러 발생 시, 스스로 예외 처리 코드를 추가하여 재실행.
4. **교차 분석 (Cross-referencing)**: 도출된 환자 ID를 바탕으로 `clinical_info.csv`를 조회하여 임상적 원인(예: 과다 출혈) 파악.
5. **최종 답변 생성**: 분석 결과, 근거 데이터, 사용된 코드를 종합하여 사용자에게 최종 리포트 제공.

---

## B-5. 단계별 업그레이드 로드맵

### Phase 1 (단기): AnalysisAgent에 REPL 도입
* `AnalysisAgent`가 코드를 한 번만 생성하는 대신, 파이썬 REPL(예: `jupyter_client` 또는 내장 `exec` 환경)을 통해 코드를 실행하고, 그 결과를 다시 LLM이 읽어들여 코드를 수정할 수 있는 **반복 루프(Loop)** 구현.

### Phase 2 (중기): ExtractionAgent의 Tool 변환 및 파일 시스템 도구 추가
* `ExtractionAgent`를 필수 파이프라인 단계에서 메인 에이전트가 필요할 때 호출하는 `search_database_tool`로 변경.
* 메인 에이전트에게 `list_directory_tool`, `read_file_header_tool` 등 파일 시스템 직접 접근 도구 제공.

### Phase 3 (장기): LangGraph 기반의 완전 자율 에이전트 구축
* 메인 `OrchestrationAgent`를 LangGraph의 순환 그래프(Cyclic Graph)로 재설계.
* 에이전트가 스스로 목표를 설정하고, 도구를 선택하며, 에러를 수정해 나가는 완전한 자율형(Autonomous) 에이전트 완성.