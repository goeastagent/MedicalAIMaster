# Paper Writing Strategy for VitalAgent

> 작성일: 2026-04-10
>
> 이 문서는 VitalAgent 논문의 포지셔닝, 실험 설계, 베이스라인 구성, 그리고 향후 다중 LLM 아키텍처 확장 전략을 정리한 내부 전략 메모이다.

---

## 1. 현재 결과 해석의 핵심 전환

현재 `Level1` 결과는 VitalAgent의 강점을 잘 보여주지만, 논문 메시지를 단순히

- "VitalAgent가 Claude Code보다 우수하다"

로 가져가면 약해질 수 있다. 이유는 reviewer가 다음과 같이 반응할 수 있기 때문이다.

- 비교 baseline이 충분히 강한가?
- 이 성능 차이가 모델 자체의 한계인가, 아니면 retrieval/ontology 부재 때문인가?
- 이 벤치마크는 일반 의료 QA가 아니라 특정 데이터셋의 내부 스키마 매핑 문제 아닌가?

따라서 논문의 핵심 주장은 "agent superiority"보다 아래 방향으로 이동하는 것이 더 강하다.

- **heterogeneous physiologic data에서 자연어 질의를 내부 signal ontology로 grounding하기 위한 ontology-backed indexing and resolution framework**

즉, VitalAgent는 단순히 하나의 agent 제품이 아니라, 다음 요소를 결합한 방법론으로 제시하는 것이 유리하다.

- 오프라인 인덱싱
- 구조화된 ontology/parameter catalog
- synonym normalization
- candidate pruning
- stateful resolution
- execution-safe downstream handoff

---

## 2. `Level1`의 정확한 포지셔닝

`Level1`은 일반적인 clinical QA benchmark라기보다 아래 능력을 측정한다.

- 자연어 임상 표현을
- VitalDB의 내부 키 체계인
- 정확한 `Device/Param` 형식으로
- 안정적으로 grounding하는 능력

이 의미에서 `Level1`은 사실상 **custom ontology resolution benchmark**에 가깝다.

이 표현은 부정적인 의미가 아니라, 논문 포지셔닝을 더 정밀하게 만들기 위한 것이다.

### 2-1. 왜 이 framing이 중요한가

만약 논문이 `Level1`을 "범용 의료 QA benchmark"처럼 서술하면 다음 비판을 받을 수 있다.

- VitalDB 고유 ontology를 잘 아는 시스템이 유리한 것은 당연하다
- 실제 임상 질의응답 전체를 대표한다고 보기 어렵다
- benchmark 설계가 특정 시스템 구조와 지나치게 정렬되어 있다

반대로 아래처럼 쓰면 훨씬 자연스럽다.

- 본 연구는 일반 의료 지식 질의응답이 아니라,
- **실제 생체신호 분석 시스템에서 자연어 질의를 내부 파라미터 ontology로 grounding하는 문제**를 다룬다
- 이 문제는 범용 LLM의 세계지식만으로 해결되지 않으며,
- 구조화된 catalog, synonym mapping, device disambiguation, session state가 중요하다

---

## 3. 현재 결과에 대한 비판적 재해석

과거 해석처럼 "Claude가 parameter list를 몰라서 못 했다"는 서사는 충분히 정확하지 않을 수 있다. 특히 baseline prompt에 이미 parameter list 또는 catalog가 들어가 있다면, 성능 차이의 핵심 원인은 다른 곳에 있을 가능성이 높다.

보다 정밀한 원인 후보는 다음과 같다.

- flat textual list만으로는 synonym normalization이 불안정함
- 장비 간 유사 파라미터 disambiguation이 약함
- multi-parameter reasoning에서 candidate consistency를 유지하기 어려움
- multi-turn 또는 sequential context에서 prior resolution을 안정적으로 재사용하지 못함
- 구조화된 ontology 제약 없이 output을 생성하므로 unsafe mismatch가 생김

즉, 현재 관측된 성능 차이는 "list access 여부"보다 아래 차이로 설명하는 편이 좋다.

- **flat prompting vs structured ontology resolution**

---

## 4. 논문에서 더 강한 주장과 약한 주장의 구분

### 4-1. 비교적 안전한 주장

- VitalAgent는 VitalDB-like physiologic datasets에서 natural language를 internal parameter keys로 grounding하는 작업에 강하다
- 구조화된 ontology와 indexing pipeline은 semantic, abbreviation, multi-conditional query에서 큰 이점을 제공한다
- 성능 차이는 parameter disambiguation과 candidate control이 중요한 조건에서 커진다

### 4-2. 현재 상태로는 과한 주장

- VitalAgent가 최신 범용 LLM보다 실제 의료 질의응답 전반에서 우수하다
- 오프라인 구조화가 모든 의료 태스크에 항상 유리하다
- sequential dialogue에서 범용 LLM은 본질적으로 한계가 있다

이런 주장은 stronger baseline과 더 넓은 실험 범위가 확보되기 전에는 피하는 것이 좋다.

---

## 5. 추천 논문 포지셔닝

가장 설득력 있는 방향은 다음과 같다.

### 5-1. 피해야 할 중심 메시지

- "VitalAgent가 Claude Code를 이겼다"

이 문장은 결과 요약으로는 쓸 수 있지만, 논문의 주된 contribution framing으로는 약하다.

### 5-2. 추천 중심 메시지

- **범용 LLM의 성능은 model choice 자체보다 ontology 구축, indexing, candidate retrieval, stateful resolution에 더 크게 좌우된다**
- **도메인 특화 생체신호 시스템에서는 offline structured indexing이 natural-language-to-parameter grounding의 핵심이다**

### 5-3. 더 좋은 논문 제목 방향

- Ontology-Backed Grounding for Natural Language Access to Physiologic Signal Repositories
- Stateful Parameter Resolution for Natural Language Queries over Heterogeneous Vital-Sign Data
- Indexing and Ontology Design for Grounding Clinical Signal Queries to Internal Parameter Keys

---

## 6. Baseline 설계 전략

논문을 강하게 만들려면 단순 Claude Code baseline만으로는 부족하다. 아래 계층형 baseline이 필요하다.

### 6-1. 최소 baseline 계층

1. **Plain LLM baseline**
   - flat prompt
   - parameter list 제공
   - JSON output만 강제

2. **LLM + retrieval baseline**
   - ontology DB에서 top-k 후보 추출
   - 후보만 LLM에 제공

3. **LLM + retrieval + state baseline**
   - 이전 turn resolution 결과를 요약/구조화하여 전달
   - session consistency 유지

4. **VitalAgent full pipeline**
   - offline indexing
   - ontology-backed resolver
   - stateful execution plan handoff

### 6-2. 이 baseline 구조의 의미

이렇게 설계하면 reviewer가 묻는 아래 질문에 답할 수 있다.

- parameter list만 있으면 충분한가?
- retrieval만 추가하면 해결되는가?
- session state가 얼마나 중요한가?
- full pipeline의 추가 기여는 정확히 무엇인가?

---

## 7. Sequential benchmark에 대한 전략적 판단

연속 질의는 매우 유망하지만, 메인 benchmark보다는 **statefulness를 보여주는 stress test**로 쓰는 것이 더 안전하다.

### 7-1. 왜 sequential이 중요한가

sequential query는 다음 능력을 동시에 요구한다.

- co-reference resolution
- previous entity grounding 유지
- synonym rephrasing across turns
- condition update while preserving entity identity
- ambiguity resolution under evolving context

이 조건에서는 flat list 기반 LLM 방식보다 stateful ontology-backed system의 강점이 더 잘 드러날 수 있다.

### 7-2. 왜 조심해야 하는가

너무 복잡한 multi-turn benchmark는 다음 비판을 받을 수 있다.

- 현실성이 부족하다
- benchmark가 특정 시스템에 유리하게 설계되었다
- 평가 기준이 모호해진다

### 7-3. 추천 framing

- `Level1`: single-turn ontology resolution
- `Level1-MT`: multi-turn contextual resolution
- `Stress-Seq`: adversarial sequential disambiguation

이렇게 나누면 sequential 실험을 강한 보조 증거로 활용할 수 있다.

### 7-4. 현실적인 sequential 예시

1. "환자의 심박수 보여줘"
2. "그거 말고 혈압도 같이"
3. "아까 그 심박수에서 100 넘는 구간만"
4. "그 구간의 EtCO2는?"
5. "모니터 말고 마취기 쪽 값으로 보면?"

이런 세션은 실제 사용 시나리오에 가깝고, stateful resolution의 장점을 보여주기 좋다.

---

## 8. Ablation Study 설계

현재 논문에서 가장 중요한 것은 "왜 성능 차이가 발생했는가"를 분해하는 것이다.
이를 위해 VitalAgent의 내부 파이프라인을 구성요소별로 분해하고,
각 요소를 독립적으로 제거하거나 대체한 조건(ablation condition)을 설계한다.

### 8-1. VitalAgent 내부 파이프라인 구조

VitalAgent의 ExtractionAgent는 3-Node LangGraph로 구성된다.

```
[100] QueryUnderstanding ──→ [200] ParameterResolver ──→ [300] PlanBuilder ──→ END
```

각 노드의 역할과 의존하는 데이터 소스는 다음과 같다.

| Node | 역할 | 데이터 소스 | LLM 호출 |
|---|---|---|---|
| **QueryUnderstanding** | NL 질의 → 구조화된 의도/파라미터 후보 추출 | PostgreSQL (schema_context: file_catalog, column_metadata, parameter, table_entities 등 6개 테이블) | 1회 |
| **ParameterResolver** | 후보 → 정확한 param_key 매핑 | PostgreSQL (parameter ILIKE 검색) + Neo4j (OntologyCache: ConceptCategory→Parameter) | 파라미터당 1회 (병렬 최대 3) |
| **PlanBuilder** | 실행 계획 조립 (cohort/signal/join/temporal) | 이전 노드 출력 (규칙 기반, LLM 없음) | 0회 |

ParameterResolver 내부는 다시 4단계로 나뉜다.

```
DB Search (ILIKE)
  → OntologyCache 카테고리 확장 (Neo4j)
    → LLM Resolution (후보 중 최적 선택)
      → measurement_type 필터 (unit 기반 후보 제거)
```

이 구조에서 핵심 ablation 대상은 아래 5개 요소이다.

1. **Ontology DB (Neo4j)** — ConceptCategory→Parameter 그래프 기반 카테고리 확장
2. **Synonym/Semantic enrichment** — parameter 테이블의 semantic_name + data_dictionary 매칭
3. **LLM-based resolution** — DB 후보를 LLM이 최종 판별 (cross-device hierarchy 포함)
4. **Measurement type filter** — unit 패턴 기반 후보 제거 (rate, concentration, waveform 등)
5. **Schema context** — QueryUnderstanding에 주입되는 DB 메타데이터 전체

### 8-2. Ablation Conditions 정의

총 **10개 조건**을 정의한다. A1–A4는 VitalAgent 변형, B1–B3은 LLM baseline 변형,
C1–C3은 component isolation 실험이다.

#### A. VitalAgent 변형 (component removal)

| ID | 조건명 | 설명 | 구현 방법 |
|---|---|---|---|
| **A1** | VitalAgent Full | 모든 구성요소 활성화 (현재 기본값) | 기본 설정 그대로 실행 |
| **A2** | w/o Ontology DB | Neo4j OntologyCache 비활성화. 카테고리 확장 없이 PostgreSQL ILIKE + LLM resolution만 사용 | `NEO4J_ENABLED=false` 환경변수 또는 `OntologyResolverConfig.enabled = False` |
| **A3** | w/o LLM Resolution | DB 검색 결과를 LLM 없이 직접 반환. 첫 번째 매칭 후보를 자동 선택 | `build_agent(exclude_nodes=["parameter_resolver"])` 후 DB 상위 결과를 rule-based로 매핑 |
| **A4** | w/o Measurement Filter | measurement_type_hint 기반 unit 필터 비활성화 | `OntologyResolverConfig.apply_measurement_type_filter = False` |

#### B. LLM Baseline 변형 (external baseline)

| ID | 조건명 | 설명 | 구현 방법 |
|---|---|---|---|
| **B1** | LLM + Flat List | parameter 테이블의 `param_key — semantic_name (unit) [category]` 목록을 프롬프트에 제공 | 기존 `GPT4o-ParamList` / `Claude-ParamList` 시나리오 |
| **B2** | LLM + Synonym List | B1 + 각 파라미터의 synonym 목록(direct/semantic/medical/abbreviation)까지 함께 제공 | 기존 `GPT4o-Synonym` / `Claude-Synonym` 시나리오 |
| **B3** | LLM + Top-k Retrieval | 질의어로 embedding similarity 검색 후 상위 k개 파라미터만 LLM에 제공 (catalog 전체 노출 없음) | 새로 구현 필요: text-embedding-3-small로 parameter 테이블 임베딩 → cosine top-k → LLM |

#### C. Component Isolation 실험

| ID | 조건명 | 설명 | 격리하는 효과 |
|---|---|---|---|
| **C1** | A1 vs A2 | Full − Ontology | **Neo4j 카테고리 확장**의 독립적 기여 측정 |
| **C2** | A1 vs A3 | Full − LLM Resolution | **LLM 판별 능력** vs rule-based 매칭 차이 |
| **C3** | A1 vs A4 | Full − Measurement Filter | **unit 기반 후보 제거**의 기여 측정 |
| **C4** | A2 vs B2 | Agent w/o Ontology vs LLM+Synonym | Ontology 없이도 **파이프라인 구조** 자체의 이점이 남는가 |
| **C5** | B1 vs B2 vs B3 | Flat vs Synonym vs Retrieval | **정보 제공 방식**의 차이만 격리 |

### 8-3. 평가 벤치마크별 ablation 매핑

각 ablation 조건을 어떤 벤치마크에서 돌릴지는 아래와 같이 결정한다.

| 벤치마크 | 평가 대상 | 핵심 메트릭 | 적용할 ablation |
|---|---|---|---|
| **Level1** (210 cases) | 파라미터 이름 grounding 정확도 | Recall, Precision, F1, Behavior Accuracy | **A1–A4, B1–B3 전부** |
| **SVA** (50 cases) | 시맨틱 해석 + 값 계산 end-to-end | Composite (Resolution 40% + Execution 20% + Value 40%) | **A1, A2, B1, B2** (Resolution score로 ontology 효과 직접 분리 가능) |
| **ValueAccuracy** | track name 주어진 상태의 계산 정확도 | Value Match Accuracy | ablation 대상 아님 (supplementary evidence) |

ValueAccuracy는 이미 정확한 track name이 query에 포함되어 있어 ontology grounding이 불필요하다.
따라서 "grounding이 끝난 뒤에도 계산 능력 차이가 남는가?"를 보여주는 **보조 실험**으로만 사용한다.

### 8-4. Level1 Ablation 결과 표 형식 (예상)

아래 표 형식으로 결과를 보고한다. 행: ablation 조건, 열: query_type별 F1 + overall.

| Condition | Single-Direct | Single-Semantic | Single-Abbrev | Multi-Indep | Multi-Cond | Adversarial | **Overall F1** | **Behavior Acc** |
|---|---|---|---|---|---|---|---|---|
| A1: Full | — | — | — | — | — | — | — | — |
| A2: w/o Ontology | — | — | — | — | — | — | — | — |
| A3: w/o LLM Res | — | — | — | — | — | — | — | — |
| A4: w/o MeasFilter | — | — | — | — | — | — | — | — |
| B1: LLM+Flat | — | — | — | — | — | — | — | — |
| B2: LLM+Synonym | — | — | — | — | — | — | — | — |
| B3: LLM+Top-k | — | — | — | — | — | — | — | — |

추가로 query_style(doctor/data_scientist/layperson)별 breakdown과
adversarial_subtype(ambiguous/impossible/confusing)별 breakdown을 보조 표로 제시한다.

### 8-5. SVA Ablation 결과 표 형식 (예상)

SVA는 3-Layer scoring이므로 각 layer별 성능을 분리 보고한다.

| Condition | semantic_resolution | cross_device | cohort_signal_join | ontology_based | adversarial | **Composite** |
|---|---|---|---|---|---|---|
| A1: Full | — | — | — | — | — | — |
| A2: w/o Ontology | — | — | — | — | — | — |
| B1: LLM+Flat | — | — | — | — | — | — |
| B2: LLM+Synonym | — | — | — | — | — | — |

여기서 `ontology_based` 카테고리의 A1 vs A2 차이가 특히 중요하다.
Neo4j ConceptCategory→Parameter 확장이 없으면 이 카테고리의 Resolution score가
급격히 하락할 것으로 예상되며, 이것이 ontology의 직접적 기여를 보여주는 핵심 증거가 된다.

### 8-6. 각 ablation이 분해하는 질문

| 질문 | 답을 주는 비교 |
|---|---|
| Ontology DB가 성능에 얼마나 기여하는가? | A1 vs A2 (Level1 전체 + SVA ontology_based 카테고리) |
| LLM resolution이 rule-based 대비 얼마나 중요한가? | A1 vs A3 (Level1 Single-Semantic, Multi-Conditional에서 차이 클 것으로 예상) |
| Unit 기반 후보 제거가 실질적 효과가 있는가? | A1 vs A4 (Level1 cross-device 관련 케이스에서 차이 예상) |
| 파이프라인 구조 자체가 flat prompting보다 우수한가? | A2 vs B2 (ontology 없이도 agent 구조가 이점 제공하는지) |
| 정보 제공 방식(flat vs synonym vs retrieval)의 차이는? | B1 vs B2 vs B3 (같은 LLM, 같은 질의, 컨텍스트만 다름) |
| Semantic query에서 성능 차이가 가장 큰 요인은? | A1 vs A3 vs B1 (Level1 Single-Semantic 행 비교) |
| Adversarial 질의에서 가장 중요한 방어선은? | A1 vs A2 vs B2 (Adversarial 열 비교: confusing subtype 특히 주목) |

### 8-7. 구현 우선순위

ablation은 구현 난이도에 따라 3단계로 나눈다.

**Phase 1 — 즉시 가능 (config flag 변경만으로 실행)**

- A1: 기본 설정
- A2: `NEO4J_ENABLED=false`
- A4: `OntologyResolverConfig.apply_measurement_type_filter = False`
- B1, B2: 기존 `test_level1_dataset.py`의 GPT4o-ParamList, Claude-Synonym 시나리오

**Phase 2 — 소규모 코드 변경 필요**

- A3: `build_agent(exclude_nodes=["parameter_resolver"])` + rule-based fallback 로직 구현
  - 구현량: ParameterResolver 대체 노드 1개 (DB top-1 결과 자동 선택, ~50줄)

**Phase 3 — 새 baseline 구현 필요**

- B3: embedding retrieval baseline
  - parameter 테이블 전체를 text-embedding-3-small로 임베딩 (1회 오프라인)
  - 질의 embedding → cosine similarity → top-k 후보 → LLM에 제공
  - 구현량: 임베딩 생성 스크립트 + retrieval wrapper (~150줄)

### 8-8. 논문 서술 전략

ablation 결과를 논문에 서술할 때 핵심은 아래 세 가지 메시지를 지원하는 것이다.

1. **Ontology 구축의 필요성**: A1 vs A2 차이가 크다면 → "offline ontology construction이 runtime resolution 정확도에 직접적으로 기여한다"
2. **파이프라인 구조의 우수성**: A2 vs B2 차이가 남는다면 → "ontology 없이도 structured pipeline(DB search → LLM resolution → plan assembly)이 flat prompting보다 우수하다"
3. **정보 제공만으로는 부족함**: B1 vs B2 vs B3 차이가 작다면 → "parameter catalog을 단순히 프롬프트에 더 많이 넣는 것만으로는 한계가 있다. 구조화된 검색-판별-조립 과정이 필요하다"

만약 A1 vs A2 차이가 작고, A2 vs B2 차이가 크다면, 논문 메시지는 "ontology 자체보다
**pipeline architecture**가 핵심 기여"로 이동한다. 이 경우에도 ablation이 있어야
이러한 nuanced interpretation이 가능해진다.

---

## 9. Error analysis 방향

단순 exact match만으로는 논문의 임상적 의미가 약하다. 오답을 아래처럼 분류하는 것이 좋다.

- exact track mismatch but correct concept family
- correct concept but wrong device
- correct device family but wrong channel
- unsafe semantic mismatch
- safe refusal / ambiguity handling

이 분류를 사용하면 논문 메시지를 아래처럼 강화할 수 있다.

- VitalAgent는 단순 정답률뿐 아니라 **위험한 종류의 오답**을 줄인다
- 구조화된 ontology와 stateful resolution은 **임상적으로 더 안전한 매핑**을 유도한다

---

## 10. 논문 작성 방향에 대한 결론

현재 상황에서 가장 유리한 논문 전략은 다음과 같다.

1. VitalAgent를 단순 제품 비교가 아니라 **ontology-backed indexing and grounding methodology**로 포지셔닝한다
2. `Level1`을 일반 의료 QA가 아니라 **custom ontology resolution benchmark**로 명확히 설명한다
3. stronger LLM baselines를 추가해 공정성을 확보한다
4. sequential benchmark는 메인 claim이 아니라 **statefulness의 필요성을 보여주는 stress test**로 사용한다
5. contribution을 model superiority가 아니라 **structured grounding pipeline의 필요성**으로 정리한다

---

## 11. Local LLM 다중 구성 전략

현재 VitalAgent는 내부적으로 ChatGPT 계열 LLM을 사용하고 있다. 이를 여러 개의 local LLM으로 분리해 사용하는 방향은 충분히 연구 가치가 있다. 다만 "무조건 여러 개가 더 좋다"기보다는, **역할별 역량 분리**가 분명할 때 가장 효과적이다.

### 11-1. 왜 여러 개의 LLM이 필요할 수 있는가

VitalAgent 내부 단계는 요구 역량이 서로 다르다.

- 질의 의도 파악: 빠르고 안정적인 instruction following
- synonym/ontology 매핑: lexical normalization + retrieval-aware reranking
- ambiguity 해소: 보수적 판단과 refusal calibration
- 코드 생성/분석: 강한 reasoning과 tool-aware generation
- 멀티턴 요약: compact memory synthesis

이 모든 능력을 단일 모델 하나로 해결하려고 하면 아래 문제가 생긴다.

- 비용이 과다해짐
- latency가 증가함
- 어떤 단계에서는 과한 모델이 불필요함
- 특정 단계에서 hallucination 성향이 전체 파이프라인에 전파됨

따라서 역할별로 모델을 분리하는 것은 기술적으로 매우 자연스럽다.

### 11-2. 추천 역할 분리 예시

1. **Router / Intent model**
   - 작은 local instruct model
   - query type, ambiguity, downstream branch 결정

2. **Ontology linker / Reranker**
   - local embedding model + cross-encoder 또는 작은 reranker model
   - top-k 후보 정렬

3. **Safety / Refusal model**
   - ambiguity가 큰 경우 "추가 정보 필요"를 더 잘 결정하는 보수적 모델

4. **Analysis / Code generation model**
   - 상대적으로 강한 reasoning model
   - 실제 코드 생성과 계산 담당

### 11-3. 기대 가능한 장점

- 비용 절감
- local deployment 가능성
- 개인정보/병원 내부망 환경 적합성
- 각 단계에 더 잘 맞는 모델 선택 가능
- error localization이 쉬워짐

### 11-4. 예상되는 한계

- orchestration 복잡도 증가
- 모델 간 interface 설계 필요
- calibration mismatch 문제
- 앞 단계 오답이 뒤 단계로 전파될 위험
- local 모델이 medical/domain terminology에서 충분히 강하지 않을 수 있음

즉, 다중 local LLM은 유망하지만, 단순히 모델 수를 늘리는 것만으로는 성능이 오르지 않는다. 핵심은 아래다.

- **어떤 단계에 어떤 역량이 필요한지 명확히 분해하고**
- **그 단계에 가장 적절한 모델 또는 비모델 도구를 배치하는 것**

### 11-5. 중요한 관점: "여러 개의 LLM"보다 "LLM + 비LLM"

특히 ontology resolution 단계는 반드시 LLM일 필요가 없을 수 있다.

예를 들어:

- synonym expansion: rule-based / dictionary-based
- candidate generation: BM25 / embedding retrieval
- candidate reranking: small local reranker
- final arbitration: LLM

이 구조는 pure multi-LLM보다 더 강하고, 논문적으로도 더 설득력이 있다. 이유는 ontology grounding 문제에서 생성형 모델보다 **retrieval + ranking + constrained decision**이 더 직접적이기 때문이다.

### 11-6. 추천 연구 질문

- 단일 frontier model vs 다중 local model 파이프라인 중 어느 쪽이 더 안정적인가?
- ontology grounding에서는 generation model보다 reranker 중심 설계가 더 중요한가?
- stateful resolution 단계에서 compact local model도 충분한가?
- local-only 구성으로도 clinically acceptable performance가 가능한가?

### 11-7. 추천 실험 축

1. **Single remote LLM**
   - 현재 VitalAgent 기준선

2. **Single local LLM**
   - end-to-end local baseline

3. **Multi-local pipeline**
   - router + linker + analysis model

4. **Hybrid pipeline**
   - local retrieval/reranking + remote reasoning model

5. **LLM-minimized pipeline**
   - ontology linking은 retrieval/reranking으로 수행
   - LLM은 최종 reasoning과 code generation만 담당

### 11-8. 현실적인 전망

단기적으로는, 여러 개의 local LLM을 넣는다고 곧바로 현재 ChatGPT 기반 VitalAgent보다 더 좋은 성능이 나온다고 보기는 어렵다. 특히 code generation과 difficult reasoning은 아직 강한 remote model이 우세할 가능성이 높다.

하지만 아래 영역에서는 충분히 좋은 결과가 나올 수 있다.

- ontology candidate retrieval
- synonym normalization
- reranking
- ambiguity detection
- session memory compression

따라서 가장 현실적인 방향은 다음과 같다.

- **완전한 local-only 대체**를 바로 목표로 하기보다
- **ontology/indexing/resolution 단계부터 local 또는 non-LLM 구성으로 치환**하고
- 가장 어려운 reasoning/code generation만 강한 모델에 남기는 hybrid architecture를 먼저 검증한다

---

## 12. 향후 권장 액션

### 논문 전략

- `RESULT.md`의 원인 해석 문구를 재작성한다
- 논문 contribution을 ontology/indexing methodology 중심으로 재정의한다
- stronger baseline 표를 설계한다

### 시스템 연구

- `Level1-MT` 또는 `Stress-Seq` 초안을 만든다
- ontology retrieval baseline을 구현한다
- local reranker 또는 embedding 기반 linker를 붙여 본다
- hybrid local/remote pipeline의 latency-accuracy tradeoff를 측정한다

