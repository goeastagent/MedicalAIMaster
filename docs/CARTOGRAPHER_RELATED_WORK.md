# Cartographer / ACPO — Related Work & 이름 충돌

> **Status**: 선행연구 정리 (2026-05 검색 기준)
> **목적**: Cartographer/ACPO를 선행연구 지형 위에 못박고, 네이밍 충돌을 기록하며, 논문화 시 방어 가능한 novelty와 reviewer 반박 대비를 모아둔다.
> **관계**: [`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md)에서 분리된 논문/포지셔닝 참고 문서. ACPO_FRAMEWORK §6의 확장.

---

## 1. ⚠️ 이름 충돌 (네이밍 결정에 직접 영향)

| 충돌 | 무엇 | 대응 |
|---|---|---|
| **VitalAgent** | [arXiv 2605.29483](https://arxiv.org/html/2605.29483) "VitalAgent: A Tool-Augmented Agent for Reactive and Proactive Physiological Monitoring over Wearable Health Data" (2026-05, ECG/PPG 에이전트) — 프로젝트 내부명과 **동일** + 인접 도메인 | 시스템명 **"VitalAgent" 폐기**, Cartographer 사용 |
| **Atlas** (회피됨) | [AutoSchemaKG (arXiv 2505.23628)](https://arxiv.org/html/2505.23628)가 산출 KG 패밀리를 **"ATLAS"**(Automated Triple Linking And Schema induction)로 명명. LLM 스키마 자동귀납 동일 분야 | 이 충돌 때문에 산출물명을 **Engram**으로 확정. 단 'Engram'도 AI-memory 분야 사용례가 있어 최종 상표/논문 확인 권장 |

---

## 2. 관련연구 6군집과 차별점

| 군집 | 대표 연구 | 입력 | Cartographer가 다른 점 |
|---|---|---|---|
| **1. raw→스키마/온톨로지 자동구축** | AutoSchemaKG ([2505.23628](https://arxiv.org/html/2505.23628)), ScheMatiQ, RIGOR ([2506.01232](https://arxiv.org/html/2506.01232)), dbxmetagen(Databricks), LLMDap(VLDB'25 WS) | 텍스트 코퍼스 / **기존 RDB·카탈로그 스키마** | 입력이 **스키마 없는 생체신호 시계열**, 출력에 **access recipe(how)** 포함 |
| **2. Knowledge-Augmented Text-to-SQL / schema linking** | KB-Construction for T2SQL ([ACL'25 findings 1363](https://aclanthology.org/2025.findings-acl.1363.pdf)), LitE-SQL ([2510.09014](https://arxiv.org/html/2510.09014v1)), RASL(Amazon) | NL + **기존 DB 스키마** | 스키마가 *입력*. 우리는 raw에서 *구축* |
| **3. 임상 NL→데이터 에이전트** | M3 ([2507.01053](https://arxiv.org/html/2507.01053v1), MCP/MIMIC), ICU-GPT ([PMC11922493](https://pmc.ncbi.nlm.nih.gov/articles/PMC11922493/)) | 기존 MIMIC DB 스키마 | 영속 ontology 아티팩트 없음, human-in-loop만 |
| **4. Knowledge vs Reasoning 분리** | Decoupling K&R ([AAAI/2507.18178](https://arxiv.org/html/2507.18178)), Disentangling Memory&Reasoning ([ACL'25 long 84](https://aclanthology.org/2025.acl-long.84/)) | — | 이들은 *모델 내부 메커니즘*(fast/slow, 특수토큰). 우리는 **외부 아티팩트 ON/OFF ablation**으로 실데이터에서 분리 |
| **5. 생리신호 LLM 에이전트** | VitalAgent ([2605.29483](https://arxiv.org/html/2605.29483)), OpenCHA PPG-HR ([2502.12836](https://arxiv.org/html/2502.12836v1)) | raw ECG/PPG | 분석 파이프라인(우리 AnalysisAgent 층). **인덱싱/온톨로지 구축 아님** |
| **6. Privacy-preserving 공유 health 메타데이터** | UHDS(W3C), HealthDCAT-AP(EHDS), DPV(W3C) | 수작업 표준 스키마 | 우리는 **LLM 자동생성 데이터셋-고유 ontology**를 raw 없이 공유 |

---

## 3. 방어 가능한 Novelty (이 조합을 동시에 하는 선행연구 없음)

> **"스키마가 없는 raw 생체신호 시계열 파일에서, LLM이 (a) 데이터셋-고유 ontology(무엇)와 (b) 데이터 접근 레시피(어떻게)를 함께 담은, (c) 파일 기반·privacy-preserving·재현 가능한 portable 아티팩트(Engram)를 자동 생성하고, (d) 그 아티팩트의 inference-time 주입 ON/OFF로 동일 모델에서 knowledge bottleneck을 분리 측정한다."**

각 군집은 일부만 충족:
- 군집 1 — (a)O 지만 입력이 텍스트/기존스키마, (b)(d)X
- 군집 2 — 재사용 KB는 있으나 스키마가 입력, (b)X
- 군집 4 — 분리는 하나 *모델 내부*, 데이터 접근X
- 군집 6 — 공유 아티팩트지만 *수작업 표준*

**특히 (b)+(d)의 결합은 어떤 군집에도 없음 = 최강 셀링 포인트.** (ACPO_FRAMEWORK §2.3 D1–D5에 더해지는 gap.)

---

## 4. 가장 위협적인 reviewer 반박 & 대비

| 반박 | 대비 |
|---|---|
| "dbxmetagen이 이미 metadata+FK+ontology+PHI를 한다" | **이미 정형화된 Unity Catalog 테이블** 대상, **raw 파일→스키마 생성 없음**, **access recipe 없음**, **injection ablation 평가 없음**. (상용 엔지니어링 툴 vs framework+벤치마크+ablation.) |
| "AutoSchemaKG가 스키마 없이 KG를 만든다" | **텍스트 입력**, 출력이 QA용 KG, **데이터 접근/주입 ablation 없음**. |
| "K&R 분리는 이미 있다" | 그들은 *모델 내부 토큰/프롬프트* 개입. 우리는 *외부 지식 아티팩트 ablation* — 직교적·더 실증적. |

---

## 5. 포지셔닝 문장 초안

> "Unlike prior schema/KG auto-construction that assumes text corpora or an existing relational schema, and unlike knowledge/reasoning decoupling that intervenes on model internals, we construct — from raw, schema-less biosignal time-series — a portable, privacy-preserving artifact carrying both the dataset's ontology and its data-access recipe, and use its inference-time injection as a controlled ablation to isolate the knowledge bottleneck on a fixed model."

---

## 6. 인용 권고 (핵심)

AutoSchemaKG(2505.23628), KB-for-Text-to-SQL(ACL'25 findings 1363), RIGOR(2506.01232), Decoupling K&R(2507.18178), Disentangling Memory&Reasoning(ACL'25 long 84), M3(2507.01053). + 기존 ACPO 문서가 인용한 BMQExpander·SchemaRAG·ExSL·VITAL.

---

*문서 작성일: 2026-05-31*
*상태: 선행연구 1차 정리 — 논문 작성 시 보강*
