# Hybrid Privacy Architecture Strategy

> 작성일: 2026-04-10
>
> 이 문서는 병원 데이터 반출 제한 환경에서 VitalAgent를 어떻게 설계하고 논문화할지에 대한 전략 메모이다. 핵심 주제는 **로컬 데이터 접근 + 원격 고성능 reasoning**의 안전한 결합이다.

---

## 1. 문제 배경

병원 데이터는 일반적으로 외부 반출이 불가능하거나 매우 엄격한 규제를 받는다. 특히 다음 정보는 외부 전송이 금지되거나 강한 제한을 받는다.

- 환자 식별 정보
- 원시 생체신호 데이터
- EMR 원문
- 시간축 이벤트 정보
- 내부 스키마 및 기관 특화 메타데이터

반면 실제 의료 분석 태스크에서는 여전히 높은 수준의 reasoning, 계획 수립, 질의 해석, 코드 생성 능력이 필요하다. 이 능력은 여전히 frontier remote model이 강한 경우가 많다.

따라서 핵심 연구 질문은 다음과 같다.

- **민감 데이터는 병원 내부에 남기면서도, 외부 고성능 모델의 reasoning 능력을 안전하게 활용할 수 있는가?**

---

## 2. 핵심 아이디어

가장 현실적인 방향은 다음과 같은 **hybrid privacy-preserving architecture**이다.

- **로컬**
  - 실제 병원 데이터 접근
  - ontology/parameter DB 검색
  - natural language to internal key grounding
  - candidate pruning
  - policy enforcement
  - 실행 코드 생성 및 실행

- **원격**
  - 질의 의도 해석
  - 분석 절차 설계
  - reasoning-heavy planning
  - 안전한 중간표현 기반의 DSL 또는 execution plan 생성

즉, 외부 모델은 병원 데이터를 직접 보는 것이 아니라, **로컬 시스템이 정제한 안전한 중간표현만** 처리한다.

---

## 3. 추천 구조

가장 추천하는 구조는 아래와 같다.

### 3-1. Remote Planner + Local Executor

1. 사용자가 자연어 질의를 입력한다
2. 로컬 시스템이 ontology grounding과 candidate selection을 수행한다
3. 로컬 시스템이 비식별화된 중간표현을 만든다
4. 원격 모델은 이 중간표현을 바탕으로 분석 계획을 생성한다
5. 로컬 시스템이 계획을 검증한다
6. 로컬 시스템이 안전한 코드로 변환하여 실행한다

### 3-2. 왜 이 구조가 좋은가

- PHI와 원시 데이터가 외부로 나가지 않는다
- ontology resolution의 정확성과 통제력을 로컬에서 유지할 수 있다
- 복잡한 reasoning은 강한 원격 모델의 도움을 받을 수 있다
- code execution을 로컬에서 통제할 수 있다

---

## 4. 원격 모델이 받아야 하는 것은 "데이터"가 아니라 "계획용 표현"이다

가장 중요한 설계 원칙은 이것이다.

- **원격 모델은 raw patient data를 받지 않는다**
- **원격 모델은 safe abstraction만 받는다**

예를 들어 원격 모델에 보내는 것은 다음과 같아야 한다.

- 질의 목적
- 필요한 연산 유형
- 비식별화된 파라미터 참조자
- 허용 가능한 연산 집합
- 제약 조건

보내면 안 되는 예시는 다음과 같다.

- 실제 환자 파형 일부
- 자유서술 EMR 원문
- 날짜/시간이 포함된 상세 이벤트
- 희귀 질환명과 개별 상황이 결합된 설명
- 재식별 가능성이 있는 low-count 정보

---

## 5. "원격 code generation"보다 "원격 DSL planning"이 더 안전하다

처음에는 다음과 같이 생각하기 쉽다.

- 원격 모델이 Python 코드를 생성하고
- 로컬에서 실행한다

하지만 의료 환경에서는 이 방식이 위험할 수 있다. 이유는 다음과 같다.

- 원격 모델이 unsafe code를 생성할 수 있다
- 데이터 접근 경로가 코드에 직접 녹아들 수 있다
- 로컬 정책 위반을 코드 수준에서 막기 어렵다
- reasoning error가 execution error로 바로 전이된다

그래서 더 좋은 방식은 다음과 같다.

- 원격은 **직접 실행 코드가 아니라 DSL 또는 execution plan**만 만든다
- 로컬은 그 plan을 검증하고 안전한 코드로 컴파일한다

예시:

```json
{
  "operation": "conditional_mean",
  "target_param": "PARAM_REF_1",
  "condition": {
    "lhs": "PARAM_REF_2",
    "op": ">",
    "rhs": 100
  },
  "time_scope": "CURRENT_CASE"
}
```

위 예시에서 `PARAM_REF_1`, `PARAM_REF_2`가 무엇인지와 실제 데이터 경로는 로컬만 알고 있어야 한다.

---

## 6. VitalAgent에 특히 잘 맞는 이유

VitalAgent는 이미 다음 구조를 가지고 있다.

- 오프라인 인덱싱
- parameter ontology
- internal `Device/Param` grounding
- execution plan 기반 분석 흐름

따라서 VitalAgent는 일반적인 의료 챗봇보다 hybrid privacy architecture에 더 잘 맞는다. 특히 강점은 다음과 같다.

- 자연어를 먼저 로컬 ontology에 grounding할 수 있다
- 외부 모델이 직접 병원 원시 데이터를 볼 필요가 없다
- 로컬에서 parameter-level control이 가능하다
- downstream execution을 정책 기반으로 검증할 수 있다

즉, 이 구조는 VitalAgent의 기존 철학을 크게 바꾸지 않고도 확장 가능하다.

---

## 7. 이 접근은 선행 흐름과도 잘 맞는다

완전히 동일한 문제는 아니지만, 최근 의료 LLM 연구에는 다음과 같은 흐름이 존재한다.

### 7-1. Hybrid cloud-local clinical framework

최근 연구들에서는 cloud LLM이 planning, decomposition, prompt generation 같은 상위 reasoning을 담당하고, local system 또는 local LLM이 실제 민감한 임상 데이터 처리를 담당하는 구조가 제안되었다.

대표적으로 다음과 같은 흐름이 알려져 있다.

- `MedEx`
- `MedOrchestra`

이 계열의 공통 메시지는 다음과 같다.

- cloud model은 강한 reasoning 능력을 제공한다
- local environment는 privacy-preserving execution을 보장한다
- 민감 데이터는 외부로 전송하지 않는다

### 7-2. Secure or institutional LLM

또 다른 흐름은 병원 방화벽 내부에서 secure LLM을 운영하는 방식이다.

- institution-hosted model
- EMR 연동
- 내부 워크플로우 보조
- no PHI export

이 접근은 완전 로컬 운영에 가깝지만, privacy-first clinical AI라는 점에서 같은 문제를 다룬다.

### 7-3. Local RAG / privacy-preserving retrieval

또 하나의 중요한 흐름은 retrieval 자체를 병원 내부에 두는 것이다.

- 인덱스는 내부에 유지
- 문서/신호/메타데이터도 내부 저장
- LLM은 retrieval 결과 또는 안전한 요약만 사용

VitalAgent는 이미 indexing과 ontology 기반 retrieval를 갖고 있기 때문에, 이 흐름과 자연스럽게 연결된다.

---

## 8. 논문적으로 왜 좋은가

이 구조는 단순 구현상의 절충안이 아니라, 독립적인 연구 기여로 발전시킬 수 있다.

가능한 핵심 주장은 다음과 같다.

- frontier model의 reasoning 능력은 유용하지만, healthcare deployment에서는 direct cloud inference가 불가능한 경우가 많다
- 이를 해결하기 위해 우리는 **local ontology-grounded access + remote abstraction-level planning** 구조를 제안한다
- 이 구조는 privacy를 보존하면서도 strong reasoning capability를 활용할 수 있게 한다

즉 논문 메시지를 아래와 같이 만들 수 있다.

- privacy-performance trade-off를 완화하는 architecture
- ontology-grounded local execution framework
- safe hybrid planning for clinical signal analysis

---

## 9. 반드시 경계해야 할 위험

이 구조가 안전하려면 단순히 "PHI만 빼고 보내면 된다"는 수준으로는 부족하다.

### 9-1. 재식별 위험

다음 정보는 직접 식별자가 아니어도 재식별 위험을 가질 수 있다.

- 희귀 질환 조합
- 특이한 수술 이벤트 시퀀스
- 정밀 시간 정보
- 내부 장비/병동 코드
- 소수 사례에서만 나타나는 메타데이터

### 9-2. Schema leakage

병원 내부 ontology나 schema가 외부 모델 prompt로 과도하게 전달되면, 직접 PHI는 아니더라도 보안상 민감할 수 있다.

### 9-3. Unsafe generation

원격 모델이 생성한 code나 plan이 로컬 정책을 위반할 수 있다.

### 9-4. Error propagation

상위 reasoning이 잘못되면 로컬 executor가 잘못된 작업을 정교하게 수행할 위험이 있다.

---

## 10. 그래서 필요한 보호 장치

이 아키텍처는 다음 구성요소가 함께 있어야 안전하다.

### 10-1. Sanitizer

원격 전송 전 데이터를 최소화하고 비식별화하는 모듈

### 10-2. Policy engine

허용 가능한 요청, 연산, 데이터 범위를 규정하는 모듈

### 10-3. Validator

원격 모델이 생성한 plan이 schema, security policy, execution rule을 만족하는지 확인하는 모듈

### 10-4. Local compiler/executor

검증된 plan만 실제 실행 코드로 전환하는 모듈

### 10-5. Audit log

어떤 정보가 외부로 나갔고 어떤 plan이 실행되었는지 추적하는 모듈

---

## 11. 추천 시스템 분해

VitalAgent를 hybrid privacy architecture로 확장한다면 다음 분해가 적절하다.

### Local zone

- Query preprocessor
- Ontology linker
- Parameter resolver
- Candidate retriever
- Session state store
- Policy engine
- Secure executor

### Remote zone

- Task planner
- Reasoning engine
- DSL planner
- Optional explanation generator

### Boundary

- Sanitizer
- Allowed schema adapter
- Validator

---

## 12. 여러 local LLM과의 결합 가능성

이 구조는 여러 개의 local model을 붙이기에도 적합하다.

예를 들어:

- local small model: query routing
- local retriever/reranker: ontology candidate selection
- remote frontier model: complex reasoning plan
- local model or rule engine: ambiguity detection and refusal
- local executor: final execution

즉, "local vs remote"의 이분법보다 **기능별 배치**가 더 중요하다.

---

## 13. 추천 연구 질문

이 문서의 아키텍처를 바탕으로 다음과 같은 연구 질문을 만들 수 있다.

1. raw clinical data를 외부로 보내지 않고도 remote frontier model의 reasoning 이점을 활용할 수 있는가?
2. local ontology grounding이 privacy-preserving clinical analysis의 핵심 bottleneck을 해결하는가?
3. direct cloud inference 대비 hybrid planning-execution 구조는 어떤 정확도-privacy trade-off를 보이는가?
4. full local pipeline 대비 hybrid pipeline은 어떤 latency-cost-accuracy 특성을 보이는가?
5. code generation을 remote에 맡기는 것보다 DSL planning만 맡기는 것이 더 안전하고 견고한가?

---

## 14. 추천 실험군

논문 실험은 아래처럼 설계할 수 있다.

### Baseline A: Full remote

- 모든 reasoning과 execution planning을 remote model에 의존
- 현실적으로는 제한적 또는 synthetic setting만 가능

### Baseline B: Full local

- local LLM 또는 local rules만으로 처리

### Baseline C: Hybrid naive

- remote model이 직접 code generation
- local에서 실행

### Proposed: Hybrid safe planner-executor

- local grounding
- sanitized abstraction
- remote DSL planning
- local validation
- local execution

이 비교를 통해 아래를 보여줄 수 있다.

- privacy 보존
- 실행 안전성
- reasoning 성능 유지
- ontology grounding의 필요성

---

## 15. 논문 작성 포인트

논문에서는 이 구조를 다음처럼 서술하는 것이 좋다.

- 단순 "remote model을 썼다"가 아니라
- **privacy-constrained clinical AI deployment problem**을 해결하는 시스템 설계로 위치시킨다

특히 아래 표현이 유용하다.

- local ontology-grounded executor
- remote abstraction-level planner
- privacy-preserving hybrid clinical reasoning
- safe plan-to-execution compilation

---

## 16. 결론

병원 데이터 반출이 불가능한 환경에서, **데이터 접근은 로컬에 두고 고성능 reasoning만 원격에 맡기는 구조는 매우 현실적이고 유망하다.**

다만 가장 좋은 형태는 아래와 같다.

- 원격이 raw data를 보지 않는다
- 원격이 직접 code를 생성하지 않는다
- 원격은 DSL 또는 execution plan만 생성한다
- 로컬이 검증 후 안전하게 실행한다

이 구조는 기존 hybrid clinical LLM 흐름과 연결되면서도, VitalAgent의 강점인 ontology grounding과 indexing을 중심에 놓을 수 있다는 점에서 매우 좋은 논문 방향이 될 수 있다.

