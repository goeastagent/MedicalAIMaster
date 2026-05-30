# Cartographer 평가 설계: 생산물(Engram) 품질을 어떻게 측정할 것인가

> **Status**: 평가 설계 문서 (구현 대기)
> **작성일**: 2026-05-31
> **선행 문서**: [`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md) (에이전트/Engram 설계), [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md) (K1–K5·평가 철학 D4/D5), [`EVALUATION_METHODOLOGY.md`](EVALUATION_METHODOLOGY.md) (소비자 평가 계층), [`LEVEL1_DATASET.md`](LEVEL1_DATASET.md) (Level1 데이터셋), [`SEMANTIC_VALUE_ACCURACY.md`](SEMANTIC_VALUE_ACCURACY.md) (SVA)
> **범위**: 이 문서는 **Cartographer(생산자)** 의 성능을 측정하는 평가 파이프라인을 정의한다. 기존 `Evaluation/`(Level1·ValueAccuracy·SVA·Temporal)은 **소비자(ExtractionAgent/end-to-end)** 평가이며, 본 문서는 그 위가 아니라 *그 앞단*(Engram 자체의 품질)을 다룬다.

---

## 0. 한 줄 요지

> **기존 평가는 전부 "Engram이 주어졌을 때 다운스트림이 답을 맞히는가"(소비자)를 본다. 그러나 Cartographer는 Engram을 *만드는* 에이전트다. 본 에이전트의 성능 = *생산한 Engram 자체가 정확한가*이며, 이를 재려면 (1) 생산자 평가를 소비자 평가와 분리하고, (2) 정답지를 인덱싱 입력과 독립된 출처에서 hold-out으로 가져와 순환을 끊고, (3) 정확도뿐 아니라 calibration·stability 같은 신뢰성 축을 함께 재야 한다.**

---

## 1. 문제 정의: 지금 평가가 측정하지 못하는 것

### 1.1 생산자(producer) vs 소비자(consumer)

| | 평가 대상 | 입력 | 출력 | 현재 자산 |
|---|---|---|---|---|
| **소비자 평가** | ExtractionAgent / end-to-end | 쿼리 + (이미 만들어진) Engram/DB | param_keys / 값 | `Evaluation/Level1`, `ValueAccuracy`, `SVA`, `Temporal` |
| **생산자 평가 (본 문서)** | **Cartographer** | raw 데이터 디렉토리 | **Engram(K1–K5, access_recipe)** | **없음** |

소비자 평가가 높아도 그것은 *주어진 Engram이 좋았다*는 뜻일 수도, *나쁜 Engram을 소비자가 보정했다*는 뜻일 수도 있다. 두 원인을 분리하지 못하면 Cartographer를 개선할 신호를 얻지 못한다.

### 1.2 Self-Validation(§6.5)은 평가가 아니다

[`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md) §6.5의 access probe는 **빌드타임 게이트**(정답지 없이 "로드되나"만 확인)이며, 문서 스스로 *access ≠ semantics* 를 인정한다. 즉 "Solar8000/HR이 *심박수로* 라벨됐는가"는 검증하지 못한다. 그것은 **외부 정답지가 있는 평가(evaluation)** 의 몫이다.

> **용어 고정**: **Validation** = 빌드 게이트(내부, 정답지 없음, §6.5). **Evaluation** = 벤치마크(외부 정답지 기반, 본 문서). 둘을 섞지 않는다.

---

## 2. 가장 중요한 원칙: 순환성(circularity)을 끊어라

### 2.1 함정

현재 Level1 데이터셋은 **DB(=인덱싱 산출물)** 에서 코퍼스·synonym을 만들어 ground truth를 라벨링한다(`Evaluation/Level1/stages/stage3_label.py`의 `synonym_map`은 DB 파생). 만약 *Cartographer의 출력으로 만든* 정답지로 *그 Cartographer* 를 평가하면, Engram이 `Solar8000/HR`을 오라벨해도 **정답지가 같이 틀려 만점**이 나온다. 오류가 구조적으로 보이지 않는다.

### 2.2 규칙

1. **정답지는 인덱싱 입력과 독립된 출처**여야 한다 → 데이터셋의 **공식 data dictionary**(아래 §6).
2. 그 공식 사전은 **인덱싱 때 LLM에 주지 않고 hold-out** 한다. 그래야 "데이터만 보고 복원했는가"를 정직하게 잴 수 있다.
3. LLM-as-judge를 쓸 경우 **인덱싱에 쓴 모델과 다른 계열**을 judge로 써서 공유 맹점을 피한다.

### 2.3 이것이 ACPO 논제와 일치하는 이유

ACPO의 명제는 "LLM은 데이터를 보기 전엔 `Solar8000/HR`이 심박수인지 모른다"([`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md) Proposition 1)이다. 따라서 Cartographer 평가의 본질은 정확히:

> **"공식 사전을 *주지 않고* 데이터만 보여줬을 때, 에이전트가 `Solar8000/HR = Heart Rate`를 스스로 복원했는가?"**

정답지(VitalDB `track_names.csv`, MIMIC `d_items`/`d_labitems`, eICU 스키마 문서)는 이미 존재한다. **인덱싱에서 빼고 채점에서만 쓰면** 순환 없는 측정이 된다. 이것이 본 평가의 정중앙이다.

---

## 3. 평가 아키텍처: 2-트랙 + Bridge

```
                    raw 데이터 (+ 공식 사전은 hold-out)
                              │
                              ▼  Cartographer
                          Engram (K1–K5)
              ┌───────────────┴────────────────┐
              ▼                                 ▼
   ┌──────────────────────┐         ┌──────────────────────────┐
   │ Track A: INTRINSIC    │         │ Track B: EXTRINSIC        │
   │ Engram을 공식사전과 직접 채점 │   │ Engram을 소비자에 꽂아 task 수행 │
   │ 빠름·결정적·회귀용      │         │ 느림·end-to-end·마일스톤용   │
   │ → K-레이어별 점수       │         │ → Level1 F1, ValueAccuracy  │
   └──────────┬───────────┘         └───────────┬──────────────┘
              │                                 │
              └──────────► BRIDGE ◄─────────────┘
            intrinsic K2 점수 ↔ extrinsic Level1 F1 상관
       (상관이 높으면 싼 A로 반복개발, 비싼 B는 마일스톤만)
```

- **Track A (Intrinsic)**: 매 코드 변경마다 돌리는 싸고 빠른 회귀 가드. ACPO 핵심(K2)을 직접 찌른다.
- **Track B (Extrinsic)**: 기존 `Evaluation/` 자산을 **입력 Engram만 교체하는 ablation 하니스**로 재정의. ACPO_SKILL의 "떼었다 붙였다"를 실증.
- **Bridge**: A가 B를 예측하면, 비싼 B 없이 A만으로 반복 개발 가능. *이 상관 확보가 "좋은 평가 파이프라인"의 실질적 가치다.*

---

## 4. Track A — Intrinsic(생산물 직접 채점)

### 4.1 K-레이어별 지표

| 레이어 | 정답 출처(hold-out) | 지표 | 채점 난이도 |
|---|---|---|---|
| **K1** 파일/컬럼 | 파일시스템 + pandas dtype | 파일 discovery recall, dtype/role precision | 낮음(거의 결정적) — 회귀 가드 최적 |
| **K2 semantic_name** ★ | 공식 사전 description | **physiological-equivalence accuracy** | 중(자유텍스트 → 동등성 클래스 매칭) |
| **K2 unit** ★ | 공식 사전 unit | 정규화 후 exact/호환 match | 낮음 — 싸고 강함, gross mislabel 즉시 검출 |
| **K2 concept_category** | 사전→카테고리 매핑 | macro-F1 (open-vocab은 클러스터 정합도) | 중 |
| **K2 is_identifier** | 키 컬럼 정의 | precision/recall | 낮음 |
| **K3 relationships** | 문서화된 FK(MIMIC/eICU), caseid join(VitalDB) | FK precision/recall, **join-key 정확도**, cardinality 정확도 | 중 — "조용한 오류" 핵심 |
| **K3 entity row_represents** | 소량 수작업 골드(§6 T1) | LLM-judge / 수동 | 높음(주관적) |

★ = ACPO 가치를 직접 측정하는 1급 지표.

### 4.2 K2 semantic_name 채점법 (자유텍스트 문제)

`semantic_name`은 자유텍스트라 정확매칭이 부당하다("HR" vs "Heart Rate"). 두 가지를 결합한다.

1. **Physiological-equivalence 클래스 매칭**: 기존 `Evaluation/Level1/stages/stage3_label.py`의 `build_alternatives_map`이 *정규화 description으로 param_key를 그룹핑*한다. 이 그룹을 재사용해, 에이전트가 붙인 이름이 정답 param_key와 *같은 동등성 클래스*에 떨어지는지로 채점 → 표현 차이에 강건.
2. **3-Layer 채점 구조 차용**: `Evaluation/SemanticValueAccuracy/utils/scoring.py`의 `correct / partial / wrong` 라벨링을 그대로 K2에 적용(`used <= eq_group` → correct 등).

### 4.3 산출물

- `intrinsic_report.json`: 레이어별 점수 + **오류 분류(error taxonomy)**: `missing_param`, `wrong_unit`, `wrong_category`, `wrong_fk`, `wrong_join_key`, `wrong_identifier` …
- 오류 분류는 단순 점수보다 *개선 방향*을 직접 준다(어느 노드를 고칠지).

---

## 5. Track A(계속) — 생산 "과정"의 신뢰성 지표

본 에이전트의 성능은 정확도만이 아니다. [`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md)가 인정한 비결정성·재개 문제는 여기서 측정 대상이 된다.

| 지표 | 정의 | 왜 중요한가 |
|---|---|---|
| **Calibration / selective risk** | `llm_confidence`·HITL 플래그가 실제 오류와 상관되는가 (coverage-risk curve, AURC) | §6.5의 "uncertainty-targeted probe", `--auto`+HITL의 신뢰 근거. *에이전트가 자기가 틀린 걸 아는가* |
| **Stability** | 같은 입력 2회 실행 → semantic_name 일치율, K3 edge Jaccard | 문서가 인정한 비결정성의 **정량화**. 높은 불안정성 = 신뢰 불가 |
| **Resume-consistency** | clean run vs 중간재개 run의 Engram diff | "앞부분 run-A 판정 + 뒷부분 run-B 판정"이 섞인 artifact 버그를 실측 |
| **HITL burden** | 100 param당 질문 수 (정확도 고정 시) | 낮을수록 좋은 에이전트(비용 축) |
| **Cost/latency** | dataset당 LLM 호출·토큰·$·시간 | "저렴한 지식 공장" 주장 검증 |

> **Calibration이 1급 시민인 이유**: confidence가 엉터리면 HITL 타깃팅도 refine 타깃팅(§6.5)도 모두 헛돈다. 정확도 측정보다 우선순위가 낮지 않다.

---

## 6. 골드 표준 확보 전략 (3-Tier)

| Tier | 출처 | 비용 | 커버 | 비고 |
|---|---|---|---|---|
| **T0 (자동)** | 데이터셋 공식 사전 hold-out: VitalDB `track_names.csv`, MIMIC `d_items`/`d_labitems`, eICU 스키마 문서 | 0 | K2 semantic/unit, K3 FK 대부분 | 인덱싱에 **미투입** |
| **T1 (1회 수작업)** | 층화 샘플 ~100 param 수동 골드 | 소 | T0 oracle 자체 품질 검증 + calibration 라벨 | *oracle도 틀린다* → 메타검증 |
| **T2 (재사용)** | 기존 `Evaluation/` Level1·SVA·ValueAccuracy | 0 | extrinsic(Track B) | 단, 평가셋은 reference-built로 **동결** |

> **T1이 필수인 이유**: 공식 사전이 모호하거나 우리 매칭 규칙이 과/소관대일 수 있다. 100개 수동 골드로 "oracle을 평가하는" 단계가 있어야 자동 채점의 신뢰가 선다.

---

## 7. 표준 의료 온톨로지(SNOMED/UMLS/LOINC)를 에이전트에 넣을까?

> **결론**: **입력(인덱싱 crutch)으로 넣는 것은 over-engineering이고 ACPO의 핵심 주장을 약화시킨다. 그러나 *출력 정렬(normalization) 레이어* 와 *평가 oracle / ablation 베이스라인* 으로는 가치가 크다. 즉 "에이전트 안"이 아니라 "에이전트 출력 위"와 "평가 옆"에 둔다.**

### 7.1 먼저, 표준 온톨로지가 *어느 간극*을 메우는지 본다

Domain-Blindness Gap은 두 부분이다.

| 간극 | 예 | LLM 단독 | SNOMED/LOINC가 메우나? |
|---|---|---|---|
| **(A) 일반 의학 의미** | "심박수란 무엇인가" | **이미 강함**(Single-Direct F1=1.00) | 메움 (그러나 *이미 풀린 곳*) |
| **(B) 데이터셋-고유 명명** | `Solar8000/HR`=심박수, `Solar8000`=GE 환자모니터 채널 | **약함**(Single-Semantic F1=0.07) | **못 메움** — `Solar8000/HR`은 SNOMED/LOINC에 없음 |

핵심: **SNOMED은 (A)를 강화하는데 (A)는 LLM이 이미 잘한다. 정작 ACPO가 노리는 (B)는 표준 온톨로지에 항목 자체가 없다.** 제조사 모델명·내부 채널코드는 어떤 표준 사전에도 등재되지 않는다. 즉 *비용은 LLM이 강한 곳에 들고, 약한 곳엔 도움이 안 된다.*

### 7.2 연구 관점: D2와의 충돌

[`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md) §2.2–2.3의 차별점 **D2 = "표준 ontology(UMLS/SNOMED/MeSH) 없이 raw 데이터에서 자동 구축"** 이다. BMQExpander(UMLS 의존)와의 구분이 바로 이것이다. SNOMED을 *인덱싱 입력*으로 넣으면 이 차별점을 스스로 허문다("표준 사전이 없는/부족한 데이터셋엔 적용 불가"라는 우리가 비판한 약점을 도입하는 셈).

### 7.3 운영 관점: 비용 대비 효용

- **라이선스/규모**: UMLS는 라이선스, SNOMED CT는 대형·국가별 에디션. 매핑 모호성(다대다)·버전 드리프트 관리 부담.
- **매핑 난점**: `Solar8000/HR` → SNOMED `364075005 (Heart rate)`로 잇는 작업 자체가 *또 하나의 LLM 판정* 이라, 오류원이 줄지 않고 늘 수 있다.
- 결론: **인덱싱 파이프라인 내부에 SNOMED 룩업을 박는 것은 over-engineering**. 들이는 복잡도에 비해 (B)를 못 풀어 ROI가 낮다.

### 7.4 그럼에도 표준 코드가 *가치 있는* 자리 — 출력 정렬 레이어

설계는 이미 이를 예견했다: `k2_parameters.jsonl`에 **`concept_id` 필드가 자리만(null)** 예약되어 있다([`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md) §3.2). 표준 코드는 *입력 crutch*가 아니라 **사후(post-hoc) 정렬 타깃**으로 둘 때 가치가 생긴다.

| 용도 | 설명 | 가치 |
|---|---|---|
| **(1) 평가 oracle / 정규화 키** | 에이전트의 자유텍스트 `semantic_name`을 LOINC/SNOMED 코드로 정규화해 채점 | 언어·표현 무관 **안정적 동등성 키** → §4.2 채점이 견고해짐 |
| **(2) Cross-dataset 상호운용** | VitalDB HR ≡ MIMIC HR ≡ eICU HR 를 *공유 코드*로 연결 | dataset-agnostic 주장(§8.1)을 코드 레벨로 실증 |
| **(3) Ablation 베이스라인** | "ACPO(data-only)" vs "ACPO+SNOMED-injection" 비교 | **injection이 거의 안 도우면 그것이 D2의 증거** — SNOMED을 *반증 도구* 로 활용 |

특히 **(3)이 영리하다**: SNOMED을 핵심 에이전트가 아니라 *대조군*으로 쓰면, "표준 온톨로지를 넣어도 (B)는 안 풀린다 → 데이터-grounded 인덱싱이 필요하다"는 ACPO 논제를 *정량적으로 입증* 하는 실험이 된다.

### 7.5 권고 (요약)

1. **인덱싱 입력에 SNOMED/UMLS 주입 = 하지 않는다**(over-engineering + D2 훼손 + (B) 미해결).
2. **출력 `concept_id` 정렬은 *선택적 사후 레이어*** 로 분리 구현(인덱싱 "데이터로부터 자동 구축" 주장 비오염). 우선순위는 K2/K3 채점기보다 **뒤**.
3. **평가에서는 적극 활용**: (a) LOINC/SNOMED를 *정규화 키*로, (b) SNOMED-injection을 *ablation 베이스라인*으로. 단, 데이터셋 공식 사전(d_items의 LOINC 매핑 등)을 **인덱싱에 주지 않는다는 hold-out 원칙(§2.2)은 유지**.

---

## 8. 최소 구현 순서 (가치/비용 순)

| 단계 | 작업 | 산출 | 비고 |
|---|---|---|---|
| **E0** | `Evaluation/Cartographer/` 골격 + Engram 로더(reader 재사용) | 하니스 뼈대 | |
| **E1** | **K2 unit + concept_category intrinsic 채점기** (track_names.csv hold-out 대비) | `intrinsic_report.json` | 하루치, ACPO 핵심 직격 |
| **E2** | **Stability 측정** (Cartographer 2회 실행 diff) | 안정성 리포트 | 인덱싱 코드 성숙 전에도 가능 |
| **E3** | **K3 join-key/FK 채점** | "조용한 오류" 가드 | |
| **E4** | K2 semantic_name physiological-equivalence 채점 (stage3 `build_alternatives_map` 재사용) | K2 핵심 점수 | |
| **E5** | Calibration(coverage-risk) + Resume-consistency | 신뢰성 축 | confidence/HITL 로그 필요 |
| **E6** | **Track B ablation 하니스**: Engram 교체 → Level1/SVA → F1 비교 | 소비자 영향 | reference-built eval셋 동결 |
| **E7** | **Bridge 상관**(intrinsic K2 ↔ Level1 F1) 측정 | 싼-비싼 평가 연결 | |
| **E8** | (선택) `concept_id` LOINC 정렬 + SNOMED-injection ablation 베이스라인 | D2 실증 | §7.4 (3) |

> E1–E3가 1차 마일스톤(생산자 회귀 가드). E6–E7로 소비자 영향과 연결. E8은 연구 강화용 선택지.

---

## 9. 기존 문서/자산과의 관계

| 자산 | 관계 |
|---|---|
| `Evaluation/Level1` | **Track B** 소비자 평가로 재사용. `stage3_label.build_alternatives_map`은 **Track A의 K2 동등성 채점 로직으로도 재사용**. 단 평가셋은 reference-built로 동결(§2). |
| `Evaluation/SemanticValueAccuracy` | 3-Layer 채점 구조를 **Track A K2 채점에 차용**. |
| `Evaluation/ValueAccuracy`·`Temporal` | Track B end-to-end·temporal 회귀. |
| [`EVALUATION_METHODOLOGY.md`](EVALUATION_METHODOLOGY.md) | Level1–4 계층은 *소비자* 축. 본 문서는 그 **앞단(생산자)** 을 추가. |
| [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md) | D4(병목 분해)·D5(모델 통제 ablation) 철학 계승. §7은 D2(표준 ontology 불필요)를 평가로 *실증*. |
| [`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md) | §6.5 Self-Validation(게이트)과 본 문서(벤치마크)의 역할을 분리. `concept_id` 슬롯(§3.2)은 §7.4의 정렬 타깃. |

---

*문서 작성일: 2026-05-31*
*상태: 평가 설계 초안 — E1(K2 intrinsic 채점기)부터 착수 권장.*
