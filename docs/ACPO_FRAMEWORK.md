# ACPO Framework: Auto-Constructed Parameter Ontology for Domain-Blind LLMs

> **Status**: 연구 wrap-up 문서 (논문 작성 이전 단계)
>
> 이 문서는 MedicalAIMaster(VitalAgent) 프로젝트가 보여준 핵심 발견 — *"같은 LLM(Claude Sonnet 4)이 시맨틱 의존도에 따라 F1=1.00에서 F1=0.07까지 12배 차이를 보인다"* — 을 하나의 일관된 framework로 정리하고, 현재 코드/평가/향후 개선이 이 framework 위에서 어떻게 맞물려 돌아가는지를 정의한다.
>
> 단일 method 이름은 **ACPO (Auto-Constructed Parameter Ontology)**, 상위 framework category는 **Dynamic Knowledge Injection**의 새 sub-paradigm이다.

---

## 1. The Domain-Blindness Problem

### 1.1 An LLM that knows medicine still cannot read your data

Claude Sonnet 4는 "심박수가 무엇인지", "마취 깊이는 BIS index로 측정한다"는 의학적 사실을 안다. 그러나 VitalDB에서 심박수가 `Solar8000/HR` 인지 `CardioQ/HR` 인지, "Solar8000"이라는 문자열이 GE Healthcare의 환자 모니터 모델명이라는 것은 **알 방법이 없다**. 이는 일반 의학 지식이 아니라 *데이터셋 고유 명명 규약* 이기 때문이다.

같은 문제가 거의 모든 임상 데이터셋에 존재한다.

| 데이터셋 | 데이터셋-고유 명명의 예 | LLM이 모를 수밖에 없는 이유 |
|---|---|---|
| **VitalDB** | `Solar8000/HR`, `Primus/ETCO2`, `Orchestra/PPF20_CE` | 제조사 모델명 + 내부 채널 코드 |
| **MIMIC-IV** | `220045` (Heart Rate item_id), `chartevents` 테이블 | 병원 내부 LOINC/itemid 매핑 |
| **eICU** | `vitalperiodic.heartrate`, `physicalexam.physicalexamvalue` | 스키마 설계자의 명명 선택 |
| **자체 EMR** | 각 병원이 자유롭게 정한 변수명, 약자, 단위 표기 | 사실상 모든 병원이 다름 |

즉 **"의학을 안다" ≠ "이 데이터셋을 안다"**. 우리는 이 간극을 **Domain-Blindness Gap** 이라 부른다.

### 1.2 Empirical evidence: same model, 60-percentage-point F1 gap

[`docs/RESULT.md`](RESULT.md) §2-4에서 보고된 핵심 결과를 재정리하면:

```
                                        Claude Sonnet 4의 Level1 F1
                                        (모든 케이스 동일 모델)

  Single-Direct      F1=1.00  ████████████████████  쿼리에 track 이름 직접 포함
                                                     ↑ "Solar8000/HR을 알려줘"
  Adversarial        F1=0.90  ██████████████████    존재 여부 판별 (일반 지식)
  Multi-Conditional  F1=0.18  ███
  Single-Abbreviation F1=0.11 ██
  Multi-Independent  F1=0.11  ██
  Single-Semantic    F1=0.07  █                     순수 임상 표현
                                                     ↑ "환자의 심박수 알려줘"
```

같은 모델, 같은 추론 능력. 변수는 **쿼리에 데이터셋-고유 식별자가 들어 있느냐 단 하나**다. 이로부터 다음 명제가 정량적으로 입증된다.

> **Proposition 1**: LLM이 임상 데이터 분석에서 실패하는 주된 원인은 *추론 능력*이 아니라 *데이터셋-고유 지식의 부재*이다.

### 1.3 Diagnosis: it's a knowledge gap, not an intelligence gap

이 명제가 중요한 이유는, 일반적인 LLM 향상 방법(모델 크기 키우기, RLHF, CoT, self-reflection)이 **이 문제를 직접 풀지 못한다**는 점이다. 96 → 128B 파라미터로 키워도 "Solar8000"이 무엇인지 모르는 것은 동일하다.

해결책은 **모델 외부에서 지식을 제공**하는 데 있다. 즉 inference time에 LLM이 데이터셋을 "읽을 수 있도록" 만들어줘야 한다.

이 framework가 답하려는 질문은 다음 셋이다.

1. **무엇을** 외부에서 제공해야 하는가? (지식 분류)
2. **어떻게** 그 지식을 자동으로 만드는가? (offline indexing)
3. **언제/어디서** LLM에게 주입하는가? (online injection points)

ACPO는 이 셋을 하나의 시스템으로 묶은 답이다.

---

## 2. Framework: Auto-Constructed Parameter Ontology (ACPO)

### 2.1 Definition

**Auto-Constructed Parameter Ontology (ACPO)** 는 다음 두 단계로 동작하는 LLM 에이전트 framework이다.

```
[OFFLINE]   raw 데이터 파일 (.vital, .csv 등)
                │
                ▼ IndexingAgent (LLM-augmented)
                │
            Parameter Ontology
            ├─ K1 File/Schema metadata
            ├─ K2 Parameter Dictionary (param_key, semantic_name, unit, category)
            ├─ K3 Entity & Relationship (FK, JOIN path)
            ├─ K4 Synonym / expression diversity
            └─ K5 Procedural domain rules
                │
                ▼
[ONLINE]    user query
                │
                ▼ SchemaContextBuilder + ParameterResolver
                │
            relevant subset of K1–K5
                │
                ▼ inject into LLM context
                │
            Knowledge-Augmented LLM
                │
                ▼
            answer / code / parameter set
```

**핵심은 세 가지 단어**:
- **Auto-Constructed**: 표준 의학 ontology(UMLS, SNOMED, MeSH 등)에 의존하지 않고 *raw 데이터로부터 LLM이 직접* 구축한다.
- **Parameter**: 우리 도메인의 일차 원자는 measurement parameter(파라미터)다. 텍스트 문서가 아니다.
- **Ontology**: 단순 schema가 아니라 *의미적 동등성, 카테고리, 관계, 절차적 우선순위*를 포함한다.

### 2.2 Position within Dynamic Knowledge Injection paradigm

[Survey 2502.10708](https://arxiv.org/html/2502.10708v2)은 LLM 도메인 지식 주입을 4가지로 분류한다. ACPO의 위치를 확실히 못박아 둔다.

```
[Knowledge Injection Survey 2502.10708의 분류]

  Static Knowledge Injection     ─ pretrain/fine-tune. 파라미터 업데이트.       ✗ 우리 아님
  Modular Knowledge Adapters     ─ LoRA, K-Adapter. 파라미터 부분 업데이트.    ✗ 우리 아님
  Dynamic Knowledge Injection    ─ inference time 외부 KB 검색 후 컨텍스트 주입. ✓ 우리 자리
  Prompt Optimization            ─ 모델 내부 지식을 잘 끌어내는 프롬프트.       부분 (X5)
```

Dynamic Knowledge Injection 안에서, ACPO가 기존 인스턴스들과 다른 점은 다음과 같다.

| 비교 대상 | 무엇을 주입하나 | 지식 구축 방식 | 차이 |
|---|---|---|---|
| **MedRAG 등 medical text RAG** | 의학 문서 passage | 기존 의학 문헌 DB | passage retrieval, 우리는 schema retrieval |
| **BMQExpander (UMLS QE)** | UMLS 정의/관계 | **기존 표준 ontology(UMLS/SNOMED/MeSH) 활용** | 표준 ontology가 없는/부족한 데이터셋엔 적용 불가 |
| **Text-to-SQL schema linking (ExSL, AutoLink, DB-Explore)** | RDB 테이블/컬럼 | **기존 RDB schema가 입력으로 주어짐** | raw 파일에서 schema를 직접 만들 수 없음 |
| **SchemaRAG (openreview VjtMhU3zWn)** | query-specific 동적 schema | **쿼리마다 매번 재구성** | online overhead 큼, 동일 쿼리 재현성 낮음 |
| **VITAL framework (LLM-EHR rep. learning)** | irregular time-series 임베딩 | end-to-end 학습 | 자연어 QA 시스템 아님, 표현 학습 task |
| **ACPO (ours)** | **자동 구축된 parameter ontology** | **raw 데이터 → LLM-augmented offline indexing → persistent ontology** | 표준 ontology 불필요, 임의 데이터셋에 적용 가능, 재현 가능 |

### 2.3 Differentiators (D1–D5)

ACPO를 다른 모든 Dynamic Knowledge Injection 인스턴스와 구분하는 다섯 가지 특성.

| # | 차별점 | 의미 | 기존 연구는? |
|---|---|---|---|
| **D1** | **입력이 text가 아닌 structured time-series** (`.vital` 등) | 거의 모든 KI 논문이 text corpus를 가정 | RAG/QE 계열 모두 text 기반 |
| **D2** | **Schema 자체를 raw data에서 LLM-augmented로 자동 구축** | UMLS, MIMIC schema, Spider schema처럼 사전 정의된 것 필요 없음 | Text-to-SQL은 schema가 입력. BMQExpander는 UMLS 필요 |
| **D3** | **Device-specific procedural knowledge** 포함 (Cross-Device 위계, measured-vs-set, CE-vs-CT) | 단순 schema가 아니라 임상적 *우선순위* 인코딩 | Text-to-SQL/RAG 문헌은 procedural rule을 다루지 않음 |
| **D4** | **Knowledge bottleneck과 reasoning bottleneck을 분리한 평가 설계** | Level1 (parameter retrieval) vs Value Accuracy (값 일치) | 보통 end-to-end만 측정, 병목 분해 불가 |
| **D5** | **모델 능력을 통제하고 지식만 변수화한 ablation** | 동일 Claude Sonnet 4로 60%p F1 격차 → 지식이 병목임을 정량 증명 | 보통 "GPT-4 vs Llama-3" 식 모델 비교로 모델 크기 효과와 혼재 |

이 다섯 가지가 **동시에** 성립하는 기존 연구는 본 문서 작성 시점(2026-05) 기준으로 확인되지 않는다.

---

## 3. Knowledge Layers (K1–K5)

ACPO가 인덱싱·주입하는 지식을 다섯 개의 레이어로 분류한다. 각 레이어는 **얼마나 데이터셋-고유한가** 와 **얼마나 절차적인가** 두 축으로 정렬된다.

| 레이어 | 이름 | 내용 | 데이터셋-고유성 | 우리 코드 위치 |
|---|---|---|---|---|
| **K1** | File/Schema metadata | 디렉토리 구조, 파일 목록, 컬럼 이름·타입 | 매우 높음 | `directory_catalog`, `file_catalog`, `column_metadata` (PostgreSQL) |
| **K2** | Parameter Dictionary | param_key, **LLM이 부여한** semantic_name, unit, concept_category | 매우 높음 | `parameter` 테이블 (260개) |
| **K3** | Entity & Relationship | row의 의미, identifier 컬럼, FK, JOIN path | 높음 | `table_entities`, `table_relationships` + Neo4j 온톨로지 |
| **K4** | Synonym / Expression diversity | doctor/data scientist/layperson 페르소나별 표현, 약어 매핑 | 중간 (도메인 공통 + 데이터셋 가산) | (계획) `synonym_map.json`, Level1 dataset의 표현 변형 |
| **K5** | Procedural domain rules | Cross-Device 위계, measured > set, CE > CT 등 임상적 우선순위 | 낮음 (의학적 합의) | 현재 → ParameterResolver 프롬프트 텍스트에 인코딩. 향후 → PCO 구조화 ([FUTURE_WORK.md](FUTURE_WORK.md) Layer 1) |

### K1–K3는 IndexingAgent가 자동 구축

[`docs/IndexingAgent_ARCHITECTURE.md`](IndexingAgent_ARCHITECTURE.md)의 3-Phase 워크플로우가 K1→K2→K3 순서로 작동한다.

- **Phase 1 (메타데이터 수집)** → K1
- **Phase 2 (의미 분석, LLM-augmented)** → K2
- **Phase 3 (관계 추론, LLM-augmented + Neo4j)** → K3

"Rule Prepares, LLM Decides" 원칙 하에, 규칙 기반 전처리가 후보를 추출하고 LLM이 의미 해석을 수행한다. 즉 ACPO의 자동 구축은 단순 LLM 호출이 아니라 **하이브리드 파이프라인**이다.

### K4 (현재 부분적)

Level1 데이터셋 구축 시 LLM으로 synonym map을 생성([`docs/LEVEL1_DATASET.md`](LEVEL1_DATASET.md) Stage 1)했지만, ParameterResolver는 아직 이를 ILIKE 키워드 검색으로만 활용한다. [`docs/EMBEDDING_PARAMETER_SEARCH.md`](EMBEDDING_PARAMETER_SEARCH.md)가 이 한계를 embedding 기반 의미 검색으로 보완하는 설계이며, 이것이 ACPO의 K4를 완전한 형태로 끌어올린다.

### K5 (현재 프롬프트 텍스트 → 향후 구조화)

`ExtractionAgent/src/agents/nodes/parameter_resolver/prompts.py`의 `RESOLUTION_SYSTEM_PROMPT`에 다음과 같은 규칙이 자연어로 인코딩되어 있다.

- Vital Signs → Patient Monitor (Solar8000) 우선
- Respiratory → Anesthesia Machine (Primus) 우선
- Anesthesia depth → BIS
- Drug infusion → Orchestra
- "ALWAYS prefer measured/observed values over Set/target values"
- "Pay strict attention to CE (Effect-site) vs CT (Target)"

LLM은 이를 확률적으로 해석하므로, **같은 쿼리에서도 결과가 달라질 수 있다**. 이는 ACPO의 현재 약점이며, [`docs/FUTURE_WORK.md`](FUTURE_WORK.md) Part A의 Layer 1 (PCO, Parameter Concept Ontology)이 K5를 결정적(deterministic) 자료구조로 옮기는 작업이다.

---

## 4. Pipeline: Offline Indexing → Online Injection

ACPO는 **두 시간축**을 분리한다. 이 분리가 SchemaRAG(query-time 동적)와의 핵심 차이다.

### 4.1 Offline phase — IndexingAgent

```
raw 데이터 디렉토리 (.vital 6,384개 + clinical_data.csv + lab_data.csv + track_names.csv)
         │
         ▼
[Phase 1] directory_catalog → file_catalog → file_grouping_prep → schema_aggregation
         │  (규칙 기반 메타데이터 추출)                                  → K1 구축
         ▼
[Phase 2] file_grouping → file_classification → column_classification
         │  → metadata_semantic → parameter_semantic → directory_pattern
         │  (LLM이 각 컬럼/파라미터의 semantic_name, unit, concept_category 부여)
         │                                                              → K2 구축
         ▼
[Phase 3] entity_identification → relationship_inference
         │  (LLM이 row의 의미, identifier, FK 관계 추론)
         │                                                              → K3 구축
         ▼
저장: PostgreSQL 12개 테이블 + Neo4j 온톨로지 그래프
```

> **저장 구현 업데이트 (2026-05)**: 위 "PostgreSQL + Neo4j" 저장은 *차세대 [`IndexingAgent → Cartographer`](CARTOGRAPHER_DESIGN.md)* 에서 **DB 서버 없이 파일 아티팩트(Engram)** 로 대체되었다(인덱싱 중엔 임베디드 SQLite 스크래치, 산출물은 JSONL/YAML). 프레임워크(K1–K5, I1–I3)의 *개념*은 그대로 유효하며, 바뀐 것은 *저장 매체*뿐이다. 또한 아래 "재현 가능"은 *동결된 산출물* 기준이며, *파이프라인 재실행*은 LLM 단계 때문에 동일 결과를 보장하지 않는다(Rule-Prepares는 결정적, LLM-Decides는 확률적).

**핵심 성질**:
- **재현 가능**: 동일 데이터에 대해 동일 indexing 결과
- **persistent**: 한 번 구축되면 모든 쿼리에서 재사용
- **incremental**: 새 파일 추가 시 IndexingAgent 부분 재실행으로 갱신 가능 (현재는 풀 재구축, [FUTURE_WORK.md](FUTURE_WORK.md) Part B의 동적 작업 공간 방향)

VitalDB 기준 산출물: **260개 parameter**, 12개 PostgreSQL 테이블, Neo4j 온톨로지.

### 4.2 Online injection points (I1–I3)

```
user query: "case 0009의 마취 깊이 평균을 구해줘"
         │
         ▼
┌────────────────────────────────────────────────────────────────┐
│  [I1] SchemaContextBuilder.build_context()                     │
│       → QueryUnderstanding 시스템 프롬프트에 K1+K2+K3+K5(category_guide) 주입 │
└────────────────────────────────────────────────────────────────┘
         │  · cohort_sources (K1+K3)
         │  · signal_groups (K1)
         │  · parameters by category (K2)
         │  · category_guide (K5의 일부, dynamic)
         ▼
QueryUnderstanding LLM 호출
         │  → requested_parameters: [{term: "마취 깊이", candidates: [...], expected_categories: ["Anesthesia"]}]
         ▼
┌────────────────────────────────────────────────────────────────┐
│  [I2] ParameterResolverNode._search_parameters() →             │
│       build_resolution_prompt(db_matches, signal_groups, ...)  │
│       → Resolver LLM에게 K2 후보 + K1 signal_groups + K5 위계 주입│
└────────────────────────────────────────────────────────────────┘
         │
         ▼
Resolver LLM 호출 (Pass 1)
         │  → selected_param_keys: ["BIS/BIS"]
         ▼
┌────────────────────────────────────────────────────────────────┐
│  [I3] build_validator_prompt(selected_matches)                 │
│       → Validator LLM에게 선택된 K2 항목 주입 (Pass 2)            │
└────────────────────────────────────────────────────────────────┘
         │
         ▼
resolved_parameters → PlanBuilder → DataContext → AnalysisAgent
```

코드 매핑:

| 주입 지점 | 코드 위치 | 주입되는 K 레이어 |
|---|---|---|
| **I1** | `ExtractionAgent/src/agents/context/schema_context_builder.py` `build_context_text()` → `ExtractionAgent/src/agents/nodes/query_understanding/prompts.py` `build_system_prompt(schema_context_text, available_categories)` | K1, K2, K3, K5(부분) |
| **I2** | `ExtractionAgent/src/agents/nodes/parameter_resolver/node.py` `_search_parameters()` + `_resolve_with_llm()` → `build_resolution_prompt(db_matches, signal_groups, parameter_examples)` | K2 (후보), K1 (signal_groups), K5 (프롬프트의 위계 규칙) |
| **I3** | 같은 파일 `_validate_mapping_with_llm()` → `build_validator_prompt(selected_matches)` | K2 (선택 결과 검증) |

### 4.3 Reasoning은 의도적으로 knowledge-free

ACPO의 비대칭적 설계 결정: **AnalysisAgent는 K1–K5에 의존하지 않는다.**

`AnalysisAgent/src/code_gen/generator.py` (`CodeGenerator`)는 ExtractionAgent가 만든 resolved parameter list와 DataFrame schema만 입력으로 받아 Python 코드를 생성한다. 이미 ACPO가 "어떤 파라미터를 써야 하는지" 결정해줬으므로, AnalysisAgent는 "그 파라미터로 어떤 계산을 할지"만 추론하면 된다.

이 분리는 의도된 것이다:

- **계산/추론**은 LLM의 사전 학습 능력으로 충분 → AnalysisAgent에 ACPO 지식 불필요
- **데이터셋 식별/선택**은 LLM의 사전 학습으로 불가능 → ExtractionAgent가 ACPO 지식 필수

이로 인해 평가가 깔끔하게 분리된다 ([5장]).

---

## 5. Empirical Evaluation

ACPO의 가치를 두 평가가 상호 보완적으로 입증한다.

### 5.1 Level 1 — parameter retrieval (knowledge bottleneck 격리)

[`docs/LEVEL1_DATASET.md`](LEVEL1_DATASET.md): 141 케이스, 자연어 임상 표현으로만 구성된 쿼리. 정답은 `param_key` 집합.

평가 지표: **Set Recall, Precision, F1** (parameter 식별 정확도)

이 평가는 의도적으로 **코드 생성 능력을 평가에서 제거**한다. 오직 "해당 임상 표현이 어떤 param_key를 가리키는가"만 본다. 즉 *knowledge bottleneck을 격리한* 벤치마크다.

결과 ([`docs/RESULT.md`](RESULT.md) §1):

| 지표 | VitalAgent (ACPO) | Claude Code CLI (no ACPO) | 격차 |
|---|---|---|---|
| F1 | **0.907** | 0.307 | **+60%p** |
| Recall | 0.922 | 0.312 | +61%p |
| Precision | 0.909 | 0.306 | +60%p |
| Perfect Recall Rate | 90.07% | 28.37% | +62%p |

### 5.2 Value Accuracy — code generation (knowledge 비의존)

[`Evaluation/ValueAccuracy/`](../Evaluation/ValueAccuracy/): 50 케이스, 쿼리에 track 이름이 백틱으로 직접 제공됨 (e.g., `` `Solar8000/HR` ``).

이 조건에서는 ACPO가 사실상 우회된다. 양쪽 시스템 모두 **코드 생성 능력 테스트**만 받는다.

| 지표 | VitalAgent | Claude Code CLI | 격차 |
|---|---|---|---|
| Accuracy | 94% (47/50) | 92% (46/50) | +2%p (통계적 비유의) |

### 5.3 두 평가의 분리가 framework 검증에 중요한 이유

D4 차별점이 여기서 빛난다.

- Value Accuracy에서 양쪽이 비슷한 점수 → "코드 생성 능력에서 양쪽이 비등"
- Level 1에서 60%p 격차 → "그 60%p는 코드 생성이 아닌 *다른 능력*에서 왔다"
- 그 "다른 능력"이 무엇인가? → ACPO가 제공하는 K1–K5 지식

만약 둘 중 하나만 측정했다면 (보통의 end-to-end 평가) 이 결론이 나오지 않는다. **knowledge bottleneck과 reasoning bottleneck을 분리한 평가 설계** 그 자체가 ACPO framework의 contribution이다.

### 5.4 핵심 발견 4가지 (paper claims로 재정렬)

| Claim | 내용 | 근거 |
|---|---|---|
| **C1** | track 이름이 쿼리에 제공되는 조건에서는 일반 LLM과 ACPO 사이에 유의한 성능 차이가 없다. | Value Accuracy 94% vs 92% (p > 0.05, n=50) |
| **C2** | 시맨틱 표현만 제공되는 조건에서는 ACPO가 일반 LLM 대비 60%p의 압도적 F1 격차를 보인다. | Level 1 F1 0.907 vs 0.307 (p < 0.001, n=141) |
| **C3** | 격차는 **시맨틱 의존도와 강한 양의 상관관계**를 보인다 (Single-Direct에서는 Claude 우위, Single-Semantic에서는 ACPO가 12배 우위). | Level 1 query_type별 분석 |
| **C4** | 따라서 임상 LLM 시스템의 주된 병목은 추론 능력이 아니라 **데이터셋-고유 지식의 자동 인덱싱과 주입**이다. | C1, C2, C3의 종합 |

---

## 6. Related Work Positioning

ACPO가 어디에 속하고 어디서 갈라지는지를 명시한다.

### 6.1 Dynamic Knowledge Injection 안에서의 위치

- **소속**: [Song et al. 2025 (arXiv 2502.10708)](https://arxiv.org/html/2502.10708v2) 분류의 Dynamic Knowledge Injection
- **새 sub-paradigm**: *"Pre-Indexed Schema Knowledge Injection from Raw Data"*
  - SchemaRAG가 query-time 동적 schema 구축인 반면, ACPO는 offline-built persistent ontology
  - text-RAG가 passage retrieval인 반면, ACPO는 structured parameter retrieval

### 6.2 Text-to-SQL schema linking과의 차이

| Text-to-SQL schema linking | ACPO |
|---|---|
| 입력: 자연어 + **사전 정의된 RDB schema** | 입력: 자연어 + **raw 파일** (schema 입력 없음) |
| schema linking은 *부분집합 선택* 문제 | ACPO는 *schema 구축 + 부분집합 선택* 문제 |
| 대표 작업: [ExSL (arXiv 2501.17174)](https://arxiv.org/html/2501.17174v1), [AutoLink (arXiv 2511.17190)](https://arxiv.org/html/2511.17190), [DB-Explore (EMNLP findings 2025)](https://aclanthology.org/2025.findings-emnlp.1032.pdf) | — |
| 평가: Spider, BIRD | 평가: Level 1 (parameter retrieval) |
| 결과 → SQL | 결과 → resolved param_keys → Python code |

ACPO의 ParameterResolver는 schema linking과 *기능적으로 유사* 하지만, "schema가 어디에서 오는가" 라는 가장 근본적인 가정이 다르다.

### 6.3 Medical RAG / Ontology-aware QE와의 차이

| Medical RAG / Ontology QE | ACPO |
|---|---|
| [BMQExpander (arXiv 2508.11784)](https://arxiv.org/pdf/2508.11784): UMLS/MeSH/SNOMED 의존 | 표준 ontology 불필요 (자동 구축) |
| MedRAG: 의학 텍스트 passage | structured parameter ontology |
| [JMIR 2025 medical RAG scoping review](https://www.jmir.org/2025/1/e80557): 80%+가 dense retrieval (vector search) | sparse + dense + structured (3-way) |
| [RiTeK (arXiv 2410.13987)](https://arxiv.org/html/2410.13987v2): medical TKG 벤치마크 | 시스템 + 벤치마크 + framework |

ACPO의 자동 구축 특성은 **표준 ontology가 없거나 부족한 임의의 임상 데이터셋에 즉시 적용 가능** 하다는 실용적 차별점을 만든다.

### 6.4 Biosignal LLM 연구와의 차이

| Biosignal LLM 기존 연구 | ACPO |
|---|---|
| [VITAL framework (Jeong-Eul/VITAL)](https://github.com/Jeong-Eul/VITAL): irregular time-series 표현 학습 | 자연어 QA 시스템 |
| anesthesia depth prediction (CNN/LSTM on EEG) | parameter retrieval + 코드 생성 + 임상 분석 |
| 출력: classification/forecasting | 출력: 분석 결과 (수치/dict/list) + 생성된 Python 코드 |

본 문서 작성 시점 기준, VitalDB 기반 **자연어 질의 → 자동 분석** 시스템에 대한 동등한 선행 연구는 확인되지 않는다.

---

## 7. Limitations and Future Work

ACPO의 현재 형태에서 명확히 부족한 부분을 다섯 가지로 정리한다.

### 7.1 K5 procedural knowledge가 아직 프롬프트 텍스트

**문제**: Cross-Device 위계, measured-vs-set, CE-vs-CT 같은 임상적 우선순위가 ParameterResolver의 system prompt 자연어로 인코딩되어 있다. LLM은 이를 확률적으로 해석하므로 동일 쿼리에서도 결과가 달라질 수 있다 ([`docs/RESULT.md`](RESULT.md) 분석에서도 11건의 cross-device 실패가 보고됨).

**해결 방향**: [`docs/FUTURE_WORK.md`](FUTURE_WORK.md) Part A의 **Layer 1 (PCO, Parameter Concept Ontology)**.
- LLM이 *concept만 식별* (e.g., "Tidal Volume")
- 구조화된 ontology가 *결정적으로* param_key 매핑 (Solar8000/VENT_TV primary, Primus/TV secondary 등)
- K5를 자료구조로 옮김 → ACPO의 *결정성* 확보

### 7.2 K4 synonym map이 ILIKE 키워드 검색 한계

**문제**: `effect site concentration` (하이픈 없음) → DB의 `Effect-site Concentration`을 못 찾음. `amount of propofol` → `Propofol Infused Volume`을 못 찾음 ([`docs/EMBEDDING_PARAMETER_SEARCH.md`](EMBEDDING_PARAMETER_SEARCH.md) §1).

**해결 방향**: [`docs/EMBEDDING_PARAMETER_SEARCH.md`](EMBEDDING_PARAMETER_SEARCH.md)의 hybrid (ILIKE + embedding) 검색. K4를 완전한 의미 매칭 레이어로 끌어올림.

### 7.3 Pipeline halt 메커니즘 부재

**문제**: ambiguity가 감지되어도 Orchestrator가 멈추지 않고 임의 가정으로 분석을 완료함. Temporal Ambiguity 평가에서 5/5 실패 ([`docs/FUTURE_WORK.md`](FUTURE_WORK.md) 이슈 4).

**해결 방향**: FUTURE_WORK Layer 2 (QueryCompletenessGate) + Layer 3 (Orchestrator ConfidenceGate). 이건 ACPO 본체보다는 *주변 안전성* 작업이지만, ACPO가 "지식을 안다"고 했을 때 실제로는 *얼마나 자신 있는지*를 신뢰성 있게 표현하는 데 필수적이다.

### 7.4 다른 데이터셋으로의 일반화 검증 부재

**문제**: 현재 ACPO는 VitalDB에 대해서만 평가됨. MIMIC-IV, eICU, 임의 EMR에 대해 동일한 IndexingAgent 파이프라인이 K1–K3를 잘 구축하는지 미검증.

**해결 방향**: 
1. MIMIC-IV의 일부 테이블(`chartevents`, `d_items`)에 IndexingAgent 적용 → K2 자동 구축
2. Level 1과 동일 스키마로 MIMIC-IV용 평가 데이터셋 구축
3. 같은 ACPO 파이프라인으로 60%p 격차 재현 여부 검증

이 작업이 완료되면 **"ACPO는 VitalDB 특화 시스템이 아닌 일반 framework"** 라는 주장이 정량적으로 뒷받침된다. 의료 AI venue에서 가장 강한 셀링 포인트가 될 것이다.

### 7.5 Incremental indexing 부재

현재 IndexingAgent는 전체 재실행만 지원한다. 새 파일이 추가되면 전체 K1–K3를 다시 빌드해야 한다. [`docs/FUTURE_WORK.md`](FUTURE_WORK.md) Part B의 *Dynamic Workspace* 방향이 이 문제를 해결하지만, ACPO 본체와는 분리된 작업 라인이다.

---

## 8. Summary: What This Framework Buys You

### 8.1 한 페이지 요약 (논문 abstract 초안)

> 대규모 언어 모델(LLM)은 임상 데이터 분석에서 강력한 코드 생성과 추론 능력을 보이지만, **데이터셋-고유의 명명 규약과 구조**를 학습할 방법이 없다. 우리는 동일한 Claude Sonnet 4가 같은 임상 질의에 대해 track 이름이 쿼리에 직접 제공될 때 F1=1.00, 시맨틱 표현만 제공될 때 F1=0.07을 보이는 **60-percentage-point의 domain-blindness gap**을 정량적으로 입증한다.
>
> 이 gap을 해소하기 위해 **Auto-Constructed Parameter Ontology (ACPO)** framework을 제안한다. ACPO는 (1) raw 임상 데이터 파일에서 LLM-augmented 파이프라인으로 5계층(K1–K5)의 parameter ontology를 **자동 구축**하고, (2) 사용자 쿼리 시점에 3개의 주입 지점(I1–I3)을 통해 관련 ontology subset을 LLM 컨텍스트로 주입한다.
>
> ACPO는 UMLS/SNOMED/MeSH 등 사전 정의 표준 ontology에 의존하지 않으므로, 표준이 부족한 임의의 임상 데이터셋에 직접 적용 가능하다. VitalDB(6,384 surgical cases, 196 parameters) 기반 141-case Level 1 benchmark에서 ACPO는 F1=0.907을 달성하여, 동일 LLM의 ontology-free baseline(F1=0.307) 대비 60%p의 격차를 보였다. 동시에 별도의 Value Accuracy benchmark에서는 양쪽이 통계적으로 비등(94% vs 92%, p>0.05)하여, 격차의 원인이 코드 생성 능력이 아닌 ontology 지식임을 보였다.
>
> ACPO는 Dynamic Knowledge Injection 패러다임 안의 새로운 sub-paradigm — *Pre-Indexed Schema Knowledge Injection from Raw Data* — 을 정의하며, 임상 LLM 에이전트의 주된 병목이 **추론 능력이 아니라 데이터셋-고유 지식의 자동 인덱싱과 주입**임을 시사한다.

### 8.2 한 줄로

> *Domain-Blind LLMs cannot read your data. ACPO teaches them — automatically, offline, from raw files.*

### 8.3 framework가 제공하는 것

| 항목 | 내용 |
|---|---|
| **이론적** | "knowledge gap"을 reasoning gap과 분리하는 framework, 그리고 그것을 측정하는 평가 설계 |
| **방법론적** | 5계층 지식 분류 (K1–K5), 3개 주입 지점 (I1–I3), offline–online 분리 파이프라인 |
| **실용적** | 표준 의학 ontology 없는 임의의 임상 데이터셋에 적용 가능한 deployable 시스템 |
| **실증적** | 동일 LLM 60%p 격차로 *"지식이 병목"* 명제를 정량 증명 |

---

## 부록 A. 기존 문서들과의 관계

| 기존 문서 | 본 framework 안의 역할 |
|---|---|
| [`docs/README.md`](README.md) | 프로젝트 개요 — ACPO의 시스템적 구현체(VitalAgent)를 소개 |
| [`docs/RESULT.md`](RESULT.md) | §1 (problem statement), §5 (empirical evaluation)의 1차 출처 |
| [`docs/EVALUATION_METHODOLOGY.md`](EVALUATION_METHODOLOGY.md) | §5의 4-level 평가 계층 정의. ACPO의 D4(평가 분리 설계)의 근간 |
| [`docs/LEVEL1_DATASET.md`](LEVEL1_DATASET.md) | §5.1 평가 데이터셋 설계. K4 표현 다양성(페르소나 기반)의 출처 |
| [`docs/SEMANTIC_VALUE_ACCURACY.md`](SEMANTIC_VALUE_ACCURACY.md) | §5의 차세대 보강 평가 (Level 1 + Value Accuracy의 융합) |
| [`docs/IndexingAgent_ARCHITECTURE.md`](IndexingAgent_ARCHITECTURE.md) | §4.1 offline indexing의 상세 워크플로우 |
| [`docs/ExtractionAgent_ARCHITECTURE.md`](ExtractionAgent_ARCHITECTURE.md) | §4.2 online injection points의 상세 6-Phase |
| [`docs/AnalysisAgent_ARCHITECTURE.md`](AnalysisAgent_ARCHITECTURE.md) | §4.3 knowledge-free reasoning의 코드 생성 |
| [`docs/OrchestrationAgent_ARCHITECTURE.md`](OrchestrationAgent_ARCHITECTURE.md) | 전체 파이프라인을 묶는 경량 레이어 |
| [`docs/ONTOLOGY_KNOWLEDGE_EXTENSION.md`](ONTOLOGY_KNOWLEDGE_EXTENSION.md) | K1–K3를 보강하는 Neo4j Knowledge 노드 확장안 (Dataset 노드, scope 기반 학습) |
| [`docs/EMBEDDING_PARAMETER_SEARCH.md`](EMBEDDING_PARAMETER_SEARCH.md) | §7.2 K4의 한계와 embedding 기반 해결책 |
| [`docs/TEMPORAL_COLUMN_ARCHITECTURE.md`](TEMPORAL_COLUMN_ARCHITECTURE.md) | K1의 시간 컬럼 처리 세부 |
| [`docs/FUTURE_WORK.md`](FUTURE_WORK.md) | §7의 5가지 개선 방향(특히 Part A Layer 1=PCO=K5 결정론화)의 출처 |
| [`docs/ACPO_SKILL.md`](ACPO_SKILL.md) | §4.1의 offline 산출물을 *재사용 가능한 단일 단위(Skill)* 로 동결·배포·교체. §5의 ON/OFF ablation 자동화의 출처 |

본 문서는 위 모든 문서의 **상위 framework 허브**이다. 향후 문서가 추가될 때마다 어느 K 레이어 또는 어느 I 지점을 보강하는지 명시하면 framework의 일관성이 유지된다.

---

## 부록 B. 용어 사전 (Glossary)

| 용어 | 약자 | 정의 |
|---|---|---|
| Auto-Constructed Parameter Ontology | ACPO | raw 데이터에서 LLM-augmented 파이프라인으로 자동 구축되는 parameter 중심 ontology와 그것을 활용하는 LLM 주입 framework |
| Domain-Blindness Gap | — | 일반 의학 지식을 가진 LLM이 데이터셋-고유 명명 규약을 모름으로써 발생하는 성능 손실 |
| Dynamic Knowledge Injection | DKI | inference time에 외부 KB에서 검색한 지식을 LLM 컨텍스트로 주입하는 paradigm (Song et al. 2025) |
| Knowledge Layer | K1–K5 | ACPO가 인덱싱·주입하는 5개의 지식 종류 (File/Schema, Parameter Dictionary, Entity & Relationship, Synonym, Procedural) |
| Injection Point | I1–I3 | online 단계에서 ACPO 지식이 LLM 컨텍스트로 주입되는 3개의 코드 지점 |
| Knowledge bottleneck | — | LLM 성능 저하의 원인 중 *데이터셋-고유 지식 부재*에 기인하는 부분 |
| Reasoning bottleneck | — | LLM 성능 저하의 원인 중 *추론·계산 능력*에 기인하는 부분 |
| Parameter Concept Ontology | PCO | K5(절차적 지식)를 자연어 프롬프트에서 결정적 자료구조로 옮기는 향후 작업 ([FUTURE_WORK.md](FUTURE_WORK.md) Part A Layer 1) |

---

*문서 작성일: 2026-05-27*  
*상태: wrap-up framework 정의 완료, 평가/논문 작성 단계로 이행 대기*
