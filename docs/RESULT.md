# Evaluation Results & Analysis

> **평가일**: 2026-03-24
>
> 이 문서는 VitalAgent와 Claude Code CLI의 평가 결과를 분석하고, 두 평가 벤치마크(Value Accuracy vs Level1) 간 성능 역전 현상의 원인을 심층 진단합니다. 논문 작성을 위한 근거 자료로 활용됩니다.

---

## 1. 성적 총괄 (Performance Summary)

### 1-1. 전체 평가 결과

| 평가 | 지표 | VitalAgent | Claude Code CLI | 비고 |
|---|---|---|---|---|
| **Value Accuracy** (50건) | Accuracy | **94%** | 92% | 2%p 차이 (통계적 비유의) |
| **Level1** (141건) | F1 | **0.907** | 0.307 | **60%p 차이** |
| | Recall | 0.922 | 0.312 | |
| | Precision | 0.909 | 0.306 | |
| | Behavior Accuracy | 0.872 | 0.887 | Claude CLI가 근소 우위 |
| | Perfect Recall Rate | 90.07% | 28.37% | |
| **Temporal** (20건) | Numeric Accuracy | **100%** | 100% | 동일 |
| | Ambiguity Pass Rate | 0% | 20% | 양쪽 모두 낮음 |

### 1-2. Level1 — query_type별 세부 결과

| query_type | 설명 | VitalAgent Recall | VitalAgent F1 | Claude CLI Recall | Claude CLI F1 |
|---|---|---|---|---|---|
| **Single-Direct** | track 이름이 쿼리에 직접 포함 | 0.917 | 0.917 | **1.000** | **1.000** |
| **Single-Semantic** | 임상적/의미적 표현으로 파라미터 지칭 | 0.893 | 0.869 | 0.071 | 0.071 |
| **Single-Abbreviation** | 의학 약어로 파라미터 지칭 | 0.900 | 0.865 | 0.133 | 0.113 |
| **Multi-Independent** | 독립적 2개 이상 파라미터 동시 검색 | 0.842 | 0.849 | 0.105 | 0.105 |
| **Multi-Conditional** | 조건부 다중 파라미터 분석 | 0.969 | 0.953 | 0.188 | 0.184 |
| **Adversarial** | 모호/존재하지 않는 파라미터 요청 | 1.000 | 1.000 | 0.900 | 0.900 |

### 1-3. Level1 — query_style별 세부 결과

| query_style | VitalAgent Recall | VitalAgent F1 | Claude CLI Recall | Claude CLI F1 |
|---|---|---|---|---|
| **doctor** | 1.000 | 0.973 | 0.346 | 0.333 |
| **data_scientist** | 0.940 | 0.947 | 0.380 | 0.380 |
| **layperson** | 0.795 | 0.769 | 0.180 | 0.180 |

### 1-4. Level1 — difficulty별 세부 결과

| difficulty | VitalAgent Recall | VitalAgent F1 | Claude CLI Recall | Claude CLI F1 |
|---|---|---|---|---|
| **easy** | 0.900 | 0.883 | 0.350 | 0.350 |
| **medium** | 0.878 | 0.859 | 0.122 | 0.110 |
| **hard** | 0.981 | 0.971 | 0.462 | 0.460 |

> **주목**: hard 난이도에서 Claude CLI의 점수(0.46)가 medium(0.12)보다 높은 역전 현상은, hard에 Adversarial 케이스(20건)가 포함되어 있고 Claude CLI가 Adversarial에서 0.90의 높은 점수를 받기 때문이다.

---

## 2. 핵심 발견: Value Accuracy와 Level1 간 성능 역전 원인

### 2-1. 두 평가가 측정하는 능력의 본질적 차이

| 항목 | Value Accuracy | Level1 |
|---|---|---|
| **핵심 도전** | 올바른 코드 생성 + 수치 계산 | 올바른 파라미터 식별 (시맨틱 해석) |
| **질의에 track 이름 포함** | **포함** (백틱으로 직접 제공, e.g. `` `Solar8000/HR` ``) | **미포함** (임상적 자연어만 제공) |
| **파라미터 해석 필요성** | 불필요 (이미 제공됨) | **필수** (에이전트가 직접 해석) |
| **VitalAgent 구조적 우위** | 미미 (2%p 차이) | **압도적** (60%p 차이) |
| **Claude의 강점 발휘** | 코드 생성 능력 충분히 발휘 | 발휘 불가 (도메인 지식 부재) |

### 2-2. Value Accuracy에서 Claude CLI가 잘하는 이유 (92%)

Value Accuracy의 질의는 다음과 같은 형태이다:

> *"What is the mean of `Solar8000/HR` for case 0001, sampled at 1 Hz, ignoring NaN values? (Round to 2 decimal places)"*

이 질의에서 Claude CLI의 작업은:

1. 백틱 안의 `Solar8000/HR`을 그대로 추출 (trivial — 정규식 수준의 작업)
2. `vitaldb` 라이브러리로 데이터를 로드하는 Python 코드 생성 (LLM의 핵심 강점)
3. `np.nanmean()` 등으로 수치를 계산하여 반환 (표준 데이터 분석 패턴)

이 과정은 본질적으로 **코드 생성 능력 테스트**이며, VitalAgent의 구조적 구성요소(IndexingAgent, ExtractionAgent, Parameter DB)가 전혀 관여할 필요가 없는 영역이다. 따라서 양쪽 시스템 모두 90%+ 성능을 달성하고, 차이는 통계적으로 유의하지 않은 2%p에 그친다.

### 2-3. Level1에서 Claude CLI가 저조한 이유 (F1=0.31)

Level1의 질의는 다음과 같은 형태이다:

> *"What is the patient's heart rate during the surgery?"* (Single-Semantic)
>
> *"Show me the EtCO2 readings"* (Single-Abbreviation)
>
> *"When BIS drops below 40, what is the propofol effect-site concentration?"* (Multi-Conditional)

Claude CLI에게 전달되는 프롬프트는 다음과 같다:

```
"You are a medical data parameter retrieval system.
Given the query, extract the exact parameter names.
Return ONLY a JSON object: {"param_keys": ["Device/Param1"], "behavior": "retrieve"}
Query: {query}"
```

이 프롬프트에서 **제공되지 않는 정보**:
- VitalDB의 196개 파라미터 목록
- `Device/Signal` 네이밍 컨벤션 (`Solar8000/HR`, `Primus/ETCO2` 등)
- 장비명과 기능 매핑 (Solar8000 = 환자 모니터, Primus = 마취기)
- 동의어/약어/임상 표현 매핑

Claude는 "heart rate"가 `Solar8000/HR`이라는 VitalDB-specific 이름에 매핑된다는 것을 **추론할 방법이 없다**. "Solar8000"이라는 장비명은 일반 의학 지식에 존재하지 않는 제조사 고유 모델명이기 때문이다.

### 2-4. query_type별 분석이 입증하는 근거

Level1의 query_type별 결과는 이 가설을 정확히 뒷받침한다:

```
Claude CLI 성능 분포:

  Single-Direct      ████████████████████████████████████████  F1=1.00  (track 이름 제공됨)
  Adversarial        ████████████████████████████████████       F1=0.90  (존재 여부 판별)
  Multi-Conditional  ███                                        F1=0.18  (시맨틱 해석 필요)
  Single-Abbreviation██                                         F1=0.11  (약어→track 매핑 필요)
  Multi-Independent  █                                          F1=0.11  (시맨틱 해석 필요)
  Single-Semantic    █                                          F1=0.07  (임상 표현→track 매핑 필요)
```

- **Single-Direct (F1=1.00)**: track 이름이 쿼리에 직접 포함되므로 추출만 하면 됨 → **Value Accuracy와 동일한 조건** → 완벽한 성능
- **Adversarial (F1=0.90)**: 존재하지 않는 개념을 판별하는 능력은 일반 의학 지식으로 충분 → 높은 성능
- **Semantic/Abbreviation/Multi (F1=0.07~0.18)**: VitalDB-specific 파라미터 매핑이 필수 → Claude의 일반 지식으로 불가능 → 극도로 낮은 성능

**이 결과는 Value Accuracy = "모든 질의가 Single-Direct인 평가"와 본질적으로 동치임을 시사한다.**

---

## 3. 아키텍처 비교: 왜 VitalAgent는 Level1에서 압도적인가

### 3-1. 파라미터 해석 경로 비교

```
VitalAgent (Level1 F1=0.91):
  사용자 질의 "heart rate"
    → [100] QueryUnderstanding (의도·카테고리 파악)
    → [200] ParameterResolver (PostgreSQL 260개 파라미터 DB + 시맨틱 매핑)
    →  "heart rate" ∈ concept_category "Vital Signs"
    →  매칭: Solar8000/HR (semantic_name: "Heart rate", 동의어 목록 참조)
    → ✅ Solar8000/HR 반환

Claude Code CLI (Level1 F1=0.31):
  사용자 질의 "heart rate"
    → LLM 추론 (사전 지식에만 의존)
    → "heart rate" → "HR" (약어는 알지만)
    → "Solar8000/HR"? "Primus/HR"? "BIS/HR"? (장비명 추론 불가)
    → ❌ 정확한 track 이름 생성 실패
```

### 3-2. VitalAgent의 구조적 투자와 Level1 성능의 관계

VitalAgent가 Level1에서 압도적 성능(F1=0.91)을 달성할 수 있는 이유는 다음 구성요소들의 시너지 때문이다:

| 구성요소 | 역할 | Level1 기여 | Value Accuracy 기여 |
|---|---|---|---|
| **IndexingAgent** | 오프라인 파라미터 인덱싱 (260개) | **필수** — 파라미터 DB 제공 | 불필요 |
| **ExtractionAgent** (ParameterResolver) | 시맨틱 해석 + param_key 매핑 | **핵심** — 임상 표현 → track 변환 | 불필요 |
| **PostgreSQL parameter 테이블** | semantic_name, unit, concept_category, 동의어 | **필수** — 해석 근거 | 불필요 |
| **AnalysisAgent** (CodeGenerator) | Python 코드 생성 + 실행 | 미사용 | 핵심 |

**결론**: Value Accuracy는 VitalAgent의 핵심 구조적 투자(IndexingAgent, ExtractionAgent, Parameter DB)의 가치를 전혀 반영하지 못하는 평가이다. Level1이야말로 이 투자가 빛나는 영역이다.

---

## 4. 통계적 의의

### 4-1. Value Accuracy의 한계

| 항목 | 값 |
|---|---|
| VitalAgent 정확도 | 94% (47/50) |
| Claude CLI 정확도 | 92% (46/50) |
| 차이 | 2%p (1건 차이) |
| 샘플 수 | 50건 |
| 통계적 유의성 | **비유의** (p > 0.05, McNemar's test) |

50건 중 1건의 차이로는 VitalAgent의 구조적 우위를 주장할 수 없다.

### 4-2. Level1의 차별력

| 항목 | 값 |
|---|---|
| VitalAgent F1 | 0.907 |
| Claude CLI F1 | 0.307 |
| 차이 | **0.600** (60%p) |
| 샘플 수 | 141건 |
| 통계적 유의성 | **고도 유의** (p < 0.001) |

Level1은 양 시스템 간 60%p의 압도적 차이를 보이며, 이는 VitalAgent의 구조적 파이프라인(IndexingAgent + ExtractionAgent + Parameter DB)이 시맨틱 파라미터 해석에서 결정적 우위를 제공함을 입증한다.

### 4-3. 시맨틱 의존도와 성능 격차의 상관관계

query_type을 "시맨틱 해석 의존도" 순으로 정렬하면, 의존도가 높을수록 VitalAgent와 Claude CLI 간 성능 격차가 커진다:

| query_type | 시맨틱 의존도 | VitalAgent F1 | Claude CLI F1 | 격차 (Δ) |
|---|---|---|---|---|
| Single-Direct | 없음 (track 이름 직접 제공) | 0.917 | 1.000 | -0.083 (Claude 우위) |
| Adversarial | 낮음 (존재 여부 판별) | 1.000 | 0.900 | +0.100 |
| Single-Abbreviation | 중간 (약어 → track) | 0.865 | 0.113 | **+0.752** |
| Multi-Conditional | 중간~높음 (시맨틱 + 다중) | 0.953 | 0.184 | **+0.769** |
| Multi-Independent | 높음 (시맨틱 + 다중) | 0.849 | 0.105 | **+0.744** |
| Single-Semantic | 최고 (순수 임상 표현) | 0.869 | 0.071 | **+0.798** |

시맨틱 의존도가 "없음"인 Single-Direct에서만 Claude CLI가 VitalAgent를 앞서며, 시맨틱 의존도가 높아질수록 격차는 최대 **0.80**까지 벌어진다. 이는 VitalAgent의 구조적 파이프라인이 **시맨틱 파라미터 해석**이라는 특정 능력에서 결정적 우위를 가짐을 정량적으로 증명한다.

---

## 5. 논문 활용을 위한 핵심 주장 (Key Claims)

1. **Claim 1**: track 이름이 질의에 직접 제공되는 조건(Value Accuracy)에서는 범용 LLM(Claude)과 도메인-특화 파이프라인(VitalAgent) 간 성능 차이가 통계적으로 유의하지 않다 (94% vs 92%, p > 0.05).

2. **Claim 2**: track 이름 없이 시맨틱 질의만 제공되는 조건(Level1)에서는 도메인-특화 파이프라인이 범용 LLM 대비 **60%p의 압도적 F1 격차**를 보인다 (0.907 vs 0.307, p < 0.001).

3. **Claim 3**: 성능 격차는 시맨틱 해석 의존도와 강한 양의 상관관계를 보인다. 시맨틱 의존도가 없는 Single-Direct에서는 Claude가 오히려 우위(F1=1.00 vs 0.92)이나, 최고 의존도인 Single-Semantic에서는 VitalAgent가 12배 이상 높은 F1을 기록한다 (0.87 vs 0.07).

4. **Claim 4**: 이 결과는 오프라인 파라미터 인덱싱(IndexingAgent), 시맨틱 해석 파이프라인(ExtractionAgent), 구조화된 파라미터 데이터베이스(PostgreSQL)에 대한 투자가 **시맨틱 파라미터 해석이 필요한 실제 임상 시나리오에서** 결정적 가치를 제공함을 입증한다.

---

## 6. Appendix: 실험 환경

| 항목 | 설정 |
|---|---|
| VitalAgent 시나리오 | ExtractionAgent (ExtractionFacade.extract_with_state) |
| Claude Code CLI 모델 | claude-sonnet-4-20250514 (via `claude` CLI) |
| 베이스라인 LLM 모델 | GPT-4o, Claude Sonnet 4 |
| Level1 데이터셋 | 141건 (121 normal + 20 adversarial) |
| Value Accuracy 데이터셋 | 50건 |
| Temporal 데이터셋 | 20건 (15 numeric + 5 ambiguity) |
| VitalDB 대상 케이스 | 0001, 0002, 0009 |
| 평가 실행 시간 | VitalAgent ~23분, Claude CLI ~24분 (Level1 기준) |
