# VitalAgent 평가 방법론 (Evaluation Methodology)

VitalAgent의 성능과 신뢰성을 체계적으로 검증하기 위한 평가 프레임워크입니다. 이 문서는 VitalAgent가 범용 LLM(ChatGPT, Claude)과 차별화되는 가치를 증명하고, 로컬 LLM 도입 가능성을 타진하기 위한 논리적 근거를 제공합니다.

---

## 1. 핵심 가설 (Core Hypotheses)

이 평가 방법론은 다음 3가지 가설을 검증하기 위해 설계되었습니다.

1.  **전문화 가설 (Specialization Hypothesis):**
    *   "데이터의 위치와 구조를 아는(Indexing) 특화 에이전트는, 아무리 똑똑해도 데이터에 접근할 수 없는 범용 LLM보다 실질적인 문제 해결 능력이 뛰어날 것이다."
2.  **자동화 가설 (Automation Hypothesis):**
    *   "복잡한 생체신호 분석 과정을 에이전트에게 위임함으로써, 인간 전문가가 수행하는 수동 작업(데이터 검색, 변환, 코딩) 시간을 획기적으로 단축할 수 있다."
3.  **로컬화 가설 (Localization Hypothesis):**
    *   "정교한 RAG와 Tooling이 뒷받침된다면, 병원 내부망의 소형 로컬 모델(Llama-3 등)로도 클라우드 모델(GPT-4o) 대비 80% 이상의 성능을 낼 수 있다."

---

## 2. 평가 계층 구조 (Evaluation Hierarchy)

에이전트의 파이프라인 단계별로 병목 구간을 진단합니다.

| 레벨 | 평가 대상 | 평가 항목 | 측정 지표 (Metrics) |
| :--- | :--- | :--- | :--- |
| **Level 1** | **Indexing & Retrieval** | 파라미터 검색 정확도 | **Recall@K**, **Precision** (필요한 신호 컬럼을 찾았는가?) |
| **Level 2** | **Extraction & Planning** | 의도 파악 및 계획 | **Intent Accuracy**, **Parameter Extraction** (분석 의도와 변수 추출) |
| **Level 3** | **Data-Code Integration** | 데이터-코드 정합성 및 안전성 | **Schema Compliance** (매핑 정확도), **API Correctness** (vitaldb 활용력), **Safety Check** |
| **Level 4** | **End-to-End** | 최종 결과 정확도 | **Value Accuracy** (허용 오차 내 일치), **Execution Time** |

---

## 3. 데이터셋 구조 (Dataset Schema)

단순 QA 쌍을 넘어, 중간 과정(검색, 코드, 의도)까지 검증할 수 있는 확장된 스키마를 사용합니다.

```json
[
  {
    "id": "TEST-001",
    "category": "statistical_analysis",
    "difficulty": "medium",
    "query": "수술 중 SpO2가 90% 미만으로 떨어진 구간의 평균 심박수를 구해줘",
    "context": {
      "case_ids": [1, 2, 3],
      "data_source": "vitaldb"
    },
    "ground_truth": {
      "intent": "analysis",
      "required_parameters": ["Solar8000/PLETH_SPO2", "Solar8000/HR"],
      "answer_type": "float",
      "answer_value": 85.4,
      "tolerance_pct": 5,
      "reference_code": "def solve(case_id): ..."
    },
    "constraints": {
      "timeout_sec": 30,
      "allowed_libraries": ["numpy", "pandas", "vitaldb"]
    }
  }
]
```

---

## 4. 평가 방법론 (Evaluation Methods)

### A. "Gold Standard Code" 기반 동적 평가
데이터 버전 변경에 유연하게 대응하기 위해, 정적 정답값 대신 **검증된 정답 코드**를 실행하여 비교합니다.
*   **지표:** **Execution Accuracy (EX)** (코드 형태가 달라도 결과값이 허용 오차 내 일치하면 정답)

### B. 경로 기반 평가 (Trajectory Evaluation)
결과뿐만 아니라 **올바른 절차**를 따랐는지 평가합니다.
*   **Metric:** `Process Accuracy = (수행한 필수 단계 수) / (전체 필수 단계 수)` (AST 파싱 활용)

### C. LLM 기반 정성 평가 (LLM-as-a-Judge)
정량화하기 어려운 코드 품질을 평가합니다. (GPT-4o 등 활용)
*   **평가 항목:** 효율성(Efficiency), 가독성(Readability), 임상적 안전성(Clinical Safety)

### D. 동적 상호작용 평가 (Dynamic Interaction)
*   **Metric:** **Clarification Rate** (모호한 질문에 대해 즉시 코드를 짜지 않고 되묻는 비율)

---

## 5. 비교 평가 전략 (Comparative Evaluation Strategy)

VitalAgent의 가치를 입증하기 위한 대조군 비교 실험 설계입니다.

### 전략 1. "Code Generation" 비교 (vs GPT-4o)
> **검증 가설:** Specialization Hypothesis
> **관련 레벨:** Level 3 (Code Generation)

*   **설정:** VitalAgent(자동 검색) vs GPT-4o(스키마 제공 프롬프트)
*   **평가:** "자동으로 찾은 정보로 짠 코드"가 "사람이 떠먹여준 정보로 짠 코드"만큼 정확한가?

### 전략 2. "End-to-End Accuracy" 비교 (vs Ground Truth Code)
> **검증 가설:** Reliability Hypothesis (신뢰성 검증)
> **관련 레벨:** Level 4 (End-to-End)

*   **설정:** VitalAgent(Generated Code) vs Gold Standard(Verified Code)
*   **방법:** 동일한 질의에 대해 에이전트가 생성한 결과와, 전문가가 미리 검증해 둔 정답 코드(Gold Standard)의 실행 결과를 비교합니다.
*   **평가 포인트:**
    *   **Value Accuracy:** 에이전트의 계산 결과가 정답 코드의 결과와 허용 오차(Tolerance, 예: ±1%) 내에서 일치하는가?
    *   **Dynamic Validation:** 데이터가 업데이트되어도 정답 코드를 재실행하여 현재 시점의 정답(Ground Truth)을 동적으로 생성하므로 평가의 유효성이 유지됨.
    *   **의의:** 사람의 개입 없이 시스템의 **분석 정확도**를 정량적으로 검증 가능.

### 전략 3. "Retrieval Accuracy" 비교 (vs Basic RAG)
> **검증 가설:** Specialization Hypothesis
> **관련 레벨:** Level 1 (Indexing)

*   **설정:** VitalAgent(Graph RAG) vs Basic RAG(Vector Similarity)
*   **평가:** 단순 키워드 매칭으로 찾기 힘든 파라미터(`Solar8000/HR` vs "심박수") 검색 성능 비교.

### 전략 4. "Local LLM Feasibility" 비교 (Model Independence)
> **검증 가설:** Localization Hypothesis
> **관련 레벨:** Level 1~4 (Backbone Performance)

VitalAgent의 아키텍처가 모델의 지능 부족을 얼마나 보완해 줄 수 있는지 검증합니다.

#### 4-1. Backbone Model 성능 비교 매트릭스

| 평가 레벨 | 테스트 항목 | GPT-4o / Claude 3.5 (Cloud) | Llama-3 / Qwen-2.5 (Local) | 비교 목적 |
| :--- | :--- | :--- | :--- | :--- |
| **Level 1** | **Medical Reasoning** | High (방대한 의학 지식) | Medium/Low (용어 이해 부족 가능성) | 로컬 모델의 **의학 용어 추론 능력** 검증 |
| **Level 2** | **JSON Formatting** | Perfect (복잡한 스키마 준수) | High (Fine-tuning 필요할 수 있음) | 로컬 모델의 **지시 이행(Instruction Following)** 능력 검증 |
| **Level 3** | **API Usage** | High (In-Context Learning 우수) | Medium (예제 많이 제공해야 함) | 로컬 모델의 **새로운 도구(vitaldb) 학습 능력** 검증 |
| **Level 4** | **Overall Success** | **Benchmark (100% 기준)** | **Target: >80%** | **"로컬 모델로도 충분한가?"** 최종 판단 |

#### 4-2. 실패 유형 분석 (Failure Mode Analysis)
Local LLM의 성능이 떨어질 경우, 그 원인을 분석하여 개선 방향을 도출합니다.
*   **Format Error:** JSON 구조를 못 맞춤 → *Prompt Engineering / Fine-tuning 필요*
*   **Hallucination:** 존재하지 않는 함수나 파라미터 사용 → *RAG Context Reinforcement 필요*
*   **Logic Error:** 분석 순서나 로직이 틀림 → *Chain-of-Thought Prompting 필요*

---

## 6. 평가의 전환 (Evaluation Focus Shift)

우리는 "누가 더 코딩을 잘하는가?"가 아니라, **"누가 더 우리 데이터를 잘 다루는가?"**를 평가해야 합니다.

| Feature | **General LLM (ChatGPT/Claude)** | **VitalAgent (Ours)** | **Evaluation Method** |
| :--- | :--- | :--- | :--- |
| **Data Access** | **Impossible** (Upload required) | **Direct Local Access** | **Level 1: Indexing & Retrieval Test** (자동 검색 정확도) |
| **Context** | Zero-shot (Blind) | **Schema-Aware** (Indexed) | **Level 2: Parameter Mapping Test** (스키마 인지 능력) |
| **Execution** | Cloud Sandbox (Generic) | **On-Premise Server** (Specialized) | **Level 3: Local API Integration Test** (`vitaldb` 활용성) |
| **Privacy** | **High Risk** (Data Leakage) | **Safe** (Local Only) | **Level 3: Sandbox Safety Check** (보안 준수 여부) |

---

## 7. 핵심 지표 요약 (Key Metrics Summary)

| 평가 영역 | 주요 지표 | 설명 |
| :--- | :--- | :--- |
| **정확도** | **Value Accuracy** | 최종 결과값의 정확성 (허용 오차 내) |
| **검색** | **Recall@K** | 필요한 생체신호 파라미터 검색 성공률 |
| **과정** | **Trajectory Match** | 필수 전처리/분석 단계 수행 여부 |
| **효율성** | **Execution Time** | 분석 완료까지 걸린 시간 |
| **안전성** | **Rejection Rate** | 잘못된/위험한 질의 차단 비율 |
| **로컬화** | **Performance Drop Rate** | Cloud 모델 대비 Local 모델의 성능 하락폭 |

---

## 8. 실행 계획 (Action Plan)

1.  **Level 1 데이터셋 구축:** `docs/LEVEL1_DATASET.md` 참조.
2.  **평가 스크립트 고도화:** `test_qa_dataset.py`에 Parameter Match 및 Code Safety Check 로직 추가.
3.  **비교 실험 수행:** 핵심 시나리오 10개에 대해 GPT-4o 및 Human Expert와의 비교 실험 진행.
4.  **Local LLM 벤치마킹:** Llama-3-8B 모델을 연결하여 Level 1~4 테스트 수행 후 Failure Mode 분석.
