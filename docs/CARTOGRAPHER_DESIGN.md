# Cartographer 설계: 데이터셋 → Engram 생성기 (서버리스, 이식 가능한 지식 조각)

> **Status**: 설계 문서 (구현 대기)
> **작성일**: 2026-05-31
> **전제**: 기존 IndexingAgent를 계승하되, **새 디렉토리에 처음부터** 제작하는 차세대. 기존 IndexingAgent / `shared/database` 와의 **호환성은 고려하지 않는다 (clean greenfield)**.
> **용어 규약**: **Cartographer** = 구 IndexingAgent의 차세대 에이전트(신규 코드는 모두 이 이름). "구 IndexingAgent / 구버전" = 기존 PostgreSQL+Neo4j 구현(설명용 참조).
> **선행 문서**: [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md) (왜/무엇), [`ACPO_SKILL.md`](ACPO_SKILL.md) (아티팩트 포맷 §3·§4 — 저장 방식은 본 문서로 superseded), [`INDEXING_AGENT_ROADMAP.md`](INDEXING_AGENT_ROADMAP.md) (기능 TODO), [`CARTOGRAPHER_RELATED_WORK.md`](CARTOGRAPHER_RELATED_WORK.md) (선행연구·이름충돌)

---

## 0. 이름과 한 줄 정의

| 용어 | 의미 |
|---|---|
| **Cartographer** | 미지의 데이터 디렉토리를 탐사해, 그 데이터셋의 지식을 *이식 가능한 기억 조각(Engram)* 으로 새기는 **에이전트/패키지**. = 구 IndexingAgent의 차세대. |
| **Engram** | 한 데이터셋에 대해 Cartographer가 산출하는 **재사용 가능한 지식+접근 아티팩트** (= [`ACPO_SKILL.md`](ACPO_SKILL.md)가 정의한 ACPO Skill의 구현체). 모델에 *떼었다 붙였다* 하는 지식 조각. 순수 파일 디렉토리. (어원: 신경과학에서 *뇌에 저장된 기억의 단위*.) |

> **Cartographer 는 "어떤 데이터 디렉토리든 입력받아, DB *서버* 없이 *그 데이터셋의 Engram* — 무엇이 있는지(Ontology)와 어떻게 불러오는지(Access Recipe)를 함께 담은 단일 폴더 — 를 직접 생성하는 범용 에이전트"** 이다. 즉 *스킬(Engram)을 만들어주는 에이전트*.

은유: 매트릭스의 트리니티가 헬기 조종법을 즉시 *이식*받듯, Cartographer가 미지의 데이터셋을 탐사해 만든 **Engram을 모델에 꽂으면 모델이 그 데이터셋을 *즉시 안다***. Engram은 누구에게나 빼다 꽂았다 할 수 있는 지식 조각이다.

구 IndexingAgent와의 본질적 차이:

| | 구 IndexingAgent | Cartographer (이 문서) |
|---|---|---|
| 저장소 | PostgreSQL + Neo4j **서버 2개** | **DB 서버 0개**. 작업 스토어 = 임베디드 SQLite(스크래치), 산출물 = 순수 파일 |
| 산출물 | DB 테이블 (transient) → (별도) export | **Engram 디렉토리(JSONL/YAML)** = 유일한 영속 산출물 |
| export 단계 | 필요 (DB→파일, 2개 영속 원천 drift 위험) | finalize 1회 덤프 (SQLite=스크래치라 영속 2차원천 아님 → drift 없음) |
| 담는 지식 | "무엇이 있나"(K1–K5)만 | **"무엇"(Ontology) + "어떻게"(Access Recipe)** |
| 데이터셋 결합 | VitalDB 가정이 곳곳에 | dataset-agnostic 지향 (포맷은 처음부터 범용, 프롬프트 범용화는 단계적) |
| 실행 전제 | `run_postgres_neo4j.sh` 필요 | `cartographer map <dir>` 단독 실행 (서버 설치 0) |

> **"DB 제거"의 정확한 의미**: 제거 대상은 **DB *서버*(Postgres/Neo4j 데몬)** 이다. 인덱싱 *도중*의 동적 관리(레코드 update·트랜잭션·중단복구)는 **임베디드 SQLite**(파이썬 표준, 파일 1개, 서버 0)가 담당한다. 최종 배포물은 SQLite를 포함하지 않는 순수 JSONL/YAML Engram다. (§4·§2 D1)

---

## 1. 목표 / 비목표

### 1.1 목표 (이번 작업 범위)

1. **서버리스 저장**: 인덱싱 *도중*은 임베디드 SQLite 스크래치, *결과*는 `engrams/<engram_id>/` 순수 파일. DB 서버 의존 0.
2. **Engram 포맷 확정** (artifact-first): ACPO_SKILL.md §3 포맷을 네이티브 출력으로 채택하고, **범용 Access Recipe 레이어**를 추가.
3. **단일 영속 산출물**: 영속 진실의 원천은 Engram 하나. SQLite는 빌드 스크래치(폐기 가능).
4. **저장소 추상화(`EngramStore`)**: 노드는 `EngramStore` 인터페이스에만 의존. 백엔드(SQLite)는 교체 가능.
5. **생산/소비/라이브러리 3분할 명문화**: Cartographer(생산) · ExtractionAgent(소비) · DataAccessKit(공유 코드)의 책임 경계(§5).
6. **HITL 유지**: "Rule Prepares, LLM Decides, *불확실하면 사람에게 질문*" 철학을 계승(§6.3).
7. **재개·관측성**: 노드 단위 체크포인트(중단복구) + LLM 호출 로그/결정 캐시.
8. **Manifest/provenance 자동 생성**: 재현성·privacy 검증 메타데이터.
9. **Access 자가검증 + refine 루프**: 인덱싱 부산물로 *데이터-grounded* access probe를 만들어 검증, 실패 시 바운드 재정련(§6.5). *의미 평가는 외부(D4).*

### 1.2 비목표 (이번엔 하지 않음 — 사용자 확정)

- ❌ **소비자(ExtractionAgent) 전환**: Cartographer는 *생산(Engram 파일 생성)까지만*. ExtractionAgent가 Engram을 읽도록 바꾸는 건 후속. (포맷은 소비자가 나중에 필요로 할 것을 모두 담도록 설계 — §3·§5.)
- ❌ **프롬프트 레벨 완전 범용화**: VitalDB few-shot 예시 제거는 *2단계*. **단, 포맷(§3)은 처음부터 범용**(§8 — 1-A 반영).
- ❌ **K4(embedding) / K5(PCO 구조화) 완성**: 포맷에 *자리만*.
- ❌ 멀티 active Engram / layered composition (ACPO_SKILL §10) — single Engram 출력만.

---

## 2. 핵심 설계 결정 (Decisions)

| # | 결정 | 근거 |
|---|---|---|
| **D1** | **DB *서버*(Postgres/Neo4j) 제거.** 작업 스토어 = 임베디드 SQLite, 산출물 = 순수 파일 | "서버 없이 self-contained·이식"이 목표. 동적 update/트랜잭션/중단복구는 SQLite로 해결(서버 0 유지). |
| **D2** | 영속 진실의 원천은 **Engram 디렉토리 하나** | SQLite는 폐기되는 스크래치 → 2개 영속 원천 drift 없음. |
| **D3** | 노드는 `EngramStore` 추상화에만 의존 | 구 `DatabaseMixin`/`Neo4jMixin` 직접 의존 제거. 테스트·교체 용이. |
| **D4** | 파이프라인 중간 read/update는 **SQLite**, 종료 시 **JSONL/YAML 덤프** | 동적 관리(레코드 갱신)는 SQLite가 자연스럽게 처리. 순수 인메모리의 크래시 손실·RAM 바운드 회피. |
| **D5** | 그래프(K3)는 Neo4j 대신 **k1–k3에서 파생한 nodes/edges JSONL** (단일 원천 = k1–k3, 그래프는 *편의 직렬화 뷰*) | ACPO_SKILL §3.1 포맷. **그래프 라이브러리(networkx 등) 비사용** — 소비자는 JSONL을 평범한 dict/인접리스트로 읽음. 중복 최소화. |
| **D6** | **LangGraph 미사용** — 단순 순차 러너 + 노드 리스트 | LangGraph HITL `interrupt()`는 *별도 checkpointer를 강제*(공식 문서) → 우리 SQLite 옆 *2번째 영속 상태* = D2/D11 drift 부활. 파이프라인은 선형, HITL 분기는 *노드 국소 재실행*, durable resume은 SQLite 체크포인트가 이미 제공. ∴ LangGraph는 값을 못 하고 단일-원천 원칙과 충돌. (복잡 분기 DAG로 커지면 재검토.) |
| **D7** | Engram 포맷 = ACPO_SKILL.md §3 **네이티브 출력** | exporter가 아니라 Cartographer가 직접 그 포맷을 씀. |
| **D8** | Engram은 **Ontology(K1–K5) + Access Recipe** 를 한 폴더에 *(목표 상태)* | "how to load"는 "what"의 파생물이고 항상 같이 쓰임(§5.1). *주의: Access Recipe 합성은 보류(1-C)라 **이번 단계 Engram엔 비어 있음** — D8은 목표.* |
| **D9** | **생산/소비/라이브러리 3분할**: Cartographer · ExtractionAgent · DataAccessKit | "로딩 기계장치"는 *코드*(스킬 아님), "로딩 레시피"는 *데이터*(Engram에 동결)(§5). |
| **D10** | **Access Recipe·ConceptCategory를 처음부터 범용 스키마로** | 목표가 "어떤 데이터든". cohort/signal·임상 enum을 박으면 2단계에서 포맷을 깨야 함(§3.2·§8). |
| **D11** | **단일 진실의 원천**: 영속 *데이터*는 EngramStore(SQLite)만. 러너의 `ctx`는 *제어흐름 + HITL 신호*(현재 노드, `needs_human_review`, `human_question` 등)만 — 대량 데이터 미보유(슬림) | 중간 단계 두 원천 drift 방지. ctx는 분기·인터럽트 신호 운반용. |
| **D12** | **HITL 유지** | V1 핵심 철학. 저신뢰·모호 관계 시 일시정지(§6.3). |
| **D13** | **Access 자가검증 + 바운드 refine 루프** (의미 평가는 외부) | 인덱싱 부산물(access_recipe·HITL 플래그)로 *데이터-grounded* 실행 테스트 생성 → "내가 인덱싱한 걸 실제로 access 하나?" 검증. 오라클=데이터 자체(순환 없음). 실패 시 타깃 재실행(MAX_REFINE). **천장: access≠semantics — 의미 정확성 평가는 외부(D4 보존)**(§6.5). |
| **D14** | **재개(resume)는 *결정적 노드*만 skip한다. LLM 노드(Phase 2·3)는 재개 시 *전체 재실행* 또는 *해당 run 전체 폐기 후 재시작*** | LLM은 비결정적(temp=0이어도)이라, 완료된 LLM 노드를 그대로 두고 뒤만 재개하면 *앞=run-A 판정 + 뒤=run-B 판정*이 섞인다 → **어떤 단일 실행과도 일치하지 않는 합성 artifact** 생성(provenance가 표기 불가). ∴ 재개 단위는 "결정적 K1까지는 skip, LLM 단계는 run 경계로 묶어 일관성 보존"(§6.1·§6.6). |
| **D15** | **`access_recipe`는 내부 *recipe_v0*(SQLite의 K1/K3 파생)로 항상 빌드된다. 외부 `access_recipe.yaml` *동결*만 보류(1-C)** | Self-Validation probe는 recipe가 *반드시* 필요(§6.5). 그래서 합성 로직 자체는 P5b에 포함하되, *배포 파일로 동결*하는 단계만 소비자 전환까지 미룬다. probe는 finalize 전이므로 `reader.py`(동결물 소비자)가 아니라 **store(SQLite)에서 직접** recipe_v0/주장을 읽는다(§6.5·§6.6). |
| **D16** | **refine 재실행은 *변경 레버*를 동반해야 한다**(같은 입력 재호출 금지) | 실패 probe를 그냥 재실행하면 같은 LLM 입력 → 같은 오답 → 비용만 2배. 레버: ① probe가 노출한 *대립 증거*(예: join coverage 0.02, 후보 키 B)를 프롬프트에 주입, ② bound/threshold 조정, ③ HITL 승격. 레버 없는 재실행은 *no-op로 간주하고 skip*(§6.5). |

---

## 3. Engram 아티팩트 포맷 (산출물 — 이 작업의 중심)

### 3.1 디렉토리 구조

ACPO_SKILL.md §3.1을 네이티브 출력으로 채택하고 **범용 Access Recipe**를 더한다. (SQLite는 빌드 스크래치라 배포물에 미포함.)

```
engrams/
└── <engram_id>/                     예: vitaldb_v1, mimic_test
    ├── manifest.yaml                메타데이터 + provenance + 무결성 해시 (§7)
    ├── README.md                    사람이 읽는 요약 (자동 생성)
    │
    │   ── Ontology: "무엇이 있나" (K1–K5) ──
    ├── k1_directories.jsonl         directory_catalog (+ filename_pattern)
    ├── k1_files.jsonl               file_catalog (분류·그룹·filename_values 포함)
    ├── k1_columns.jsonl             column_metadata (역할·통계 포함)
    ├── k1_file_groups.jsonl         file_group 정의
    ├── k2_parameters.jsonl          ★핵심: parameter 사전 (semantic_name/unit/category)
    ├── k2_data_dictionary.jsonl     metadata 파일에서 추출한 key-desc-unit 사전
    ├── k3_entities.jsonl            table_entities (row_represents, identifier)
    ├── k3_relationships.jsonl       table_relationships (FK, cardinality)
    ├── k3_graph_nodes.jsonl         그래프 노드 (k1–k3 파생 직렬화 뷰; Neo4j 대체)
    ├── k3_graph_edges.jsonl         그래프 엣지 (k1–k3 파생)
    ├── k4_synonyms.json             (자리만) synonym map
    ├── k4_embeddings.npz            (자리만) parameter embedding 캐시
    ├── k5_procedural_rules.yaml     (자리만) 절차적 규칙 (PCO 호환)
    │
    │   ── Access Recipe: "어떻게 불러오나" (포맷 예약; 합성 보류 1-C → 이번 단계 미생성) ──
    ├── access_recipe.yaml           sources[]·relations[]·temporal[] (§3.2)
    │
    │   ── Self-Validation 리포트 (§6.5; 명세+집계만, raw 미포함) ──
    └── validation_report.json       access probes 결과 (pass/fail·coverage%·범위)
```

> **레이어 두 종류**: `k1–k5`=**Ontology**(무엇), `access_recipe.yaml`=**Access Recipe**(어떻게). 후자는 전자의 *파생/요약*이지만 소비자(DataAccessKit)가 곧바로 먹도록 *동결된 형태*로 별도 제공(§5.3).

### 3.2 파일별 라인 스키마 (핵심 발췌)

**`k2_parameters.jsonl`** (가장 중요)

```jsonl
{"param_id":"uuid","param_key":"Solar8000/HR","semantic_name":"Heart Rate","unit":"/min","concept_category":"Vital Signs","source_type":"group_common","is_identifier":false,"file_id":null,"group_id":"uuid","measurement_type":null,"concept_id":null}
```

> `measurement_type`, `concept_id`, `name_embedding` 등 [`INDEXING_AGENT_ROADMAP.md`](INDEXING_AGENT_ROADMAP.md) I-01~I-03 필드는 **자리만**(null 허용) 추후 채운다.
> **`concept_category` 는 open-vocabulary**: 기본 카테고리(Vital Signs 등)는 *권장 시드*일 뿐, 비임상 데이터셋에선 LLM이 새 카테고리를 부여할 수 있다(고정 enum 강제 금지 — D10).

**`k3_graph_nodes.jsonl`** / **`k3_graph_edges.jsonl`** (Neo4j 대체)

```jsonl
{"label":"Parameter","key":"Solar8000/HR","properties":{"name":"Heart Rate","unit":"/min","concept_category":"Vital Signs"}}
```
```jsonl
{"type":"HAS_COLUMN","from":{"label":"RowEntity","key":"file_uuid"},"to":{"label":"Parameter","key":"Solar8000/HR"},"properties":{}}
```

> 노드는 *match key* 로 식별(ACPO_SKILL §3.3, 휘발성 ID 비의존). 이 그래프 파일은 **k1–k3에서 파생한 편의 직렬화 뷰**(단일 원천 = k1–k3)이며, 소비자는 JSONL을 평범한 dict/인접리스트로 읽는다(**그래프 라이브러리 비사용**).

**`access_recipe.yaml`** (신설 — *범용* 스키마. VitalDB는 한 인스턴스일 뿐)

DataContext가 *런타임에 재조립*하던 로딩 파라미터를 인덱싱 시점에 동결한다. cohort/signal 이분법을 박지 않고, **source·load_strategy·relation 추상모델**로 표현한다(D10).

```yaml
# access_recipe.yaml — 추상 스키마 (예시는 VitalDB)
sources:
  - id: clinical
    role: cohort                    # cohort | signal | auxiliary | <open>
    load_strategy: tabular_wide     # tabular_wide | long_format | per_entity_file
    file: clinical_data.csv
    entity: surgical_case
    entity_key: caseid
  - id: vitals
    role: signal
    load_strategy: per_entity_file  # 엔티티마다 파일 1개 (.vital)
    file_group: vital_case_records
    filename_pattern: "{caseid}.vital"
    entity_key_from_filename: caseid
relations:
  - from: vitals
    to: clinical
    from_key: caseid
    to_key: caseid
    cardinality: "N:1"
    id_normalize: strip_leading_zeros   # "0001" == "1"
temporal:
  - applies_to: vitals
    time_column: Time
    time_unit: seconds
    windows:
      procedure: { start: opstart, end: opend }
```

> **범용성 검증**: MIMIC-IV `chartevents` → `load_strategy: long_format`(filename_pattern 불필요); wide EMR → `tabular_wide`; VitalDB → 위처럼 `per_entity_file`. 즉 *동일 스키마가 세 데이터모델을 모두 표현*한다.
> 이 파일이 채워지면 DataContext의 `_resolve_*`/`_find_time_column`/leading-zero 하드코딩이 *Engram 한 줄 읽기*로 대체된다(소비자 전환은 다음 단계).

### 3.3 포맷 원칙

- **JSONL**: `git diff` 친화·`head -5` 검토 가능(privacy). **append-during가 아니라 finalize 시 SQLite→JSONL 1회 덤프**(중간 update는 SQLite가 처리).
- **Access Recipe만 YAML**: 사람이 검토·수정하기 좋은 단일 문서.
- **UUID는 Engram 내부에서만 의미**. self-contained.
- **임베딩만 `.npz`**.

---

## 4. 저장소 추상화: `EngramStore` (SQLite 백엔드)

### 4.1 핵심 아이디어

구버전은 노드가 `self.parameter_repo.get_...()` 로 DB 서버에 의존했다. Cartographer는 그 자리에 **`EngramStore`** 단일 추상화를 두고, 백엔드를 **임베디드 SQLite**(빌드 스크래치)로 구현한다.

- **쓰기/갱신**: 엔티티 upsert → SQLite UPSERT (레코드 update 자연 처리). 단일 트랜잭션.
- **읽기**: SQLite 쿼리(또는 핫 경로 인메모리 캐시) — 파이프라인 중간 read-back.
- **체크포인트**: 노드 완료를 SQLite에 기록 → 중단 시 재개(완료 노드 skip).
- **종료(finalize)**: SQLite → `*.jsonl` + `access_recipe.yaml` 덤프 + manifest + 무결성 해시 + README. (SQLite 스크래치는 폐기 또는 `.cache/`.)

> **단일 진실의 원천(D11)**: 영속 데이터는 **EngramStore(SQLite)만**. 러너의 `ctx`는 *제어 흐름용 경량 신호*(현재 노드·HITL 등)만 담고, 데이터 원천으로 쓰지 않는다(LangGraph 미사용 — D6).

```
Node.execute(state, store) ──► store.upsert_parameters(...)        # SQLite UPSERT
                          └──► store.get_parameters_by_concept()   # SQLite 쿼리
...
store.finalize(meta)  ──► engrams/<id>/*.jsonl + manifest.yaml (+ validation_report.json; access_recipe는 보류 1-C)
```

### 4.2 인터페이스 초안 (구 노드 read 패턴 기반)

§6.2에서 추출한 구 노드의 실제 호출을 그대로 수용(메서드명 거의 유지 → 마이그레이션 비용 최소화). 백엔드만 SQLite.

```python
class EngramStore(Protocol):
    # --- 디렉토리/파일/컬럼 (K1) ---
    def upsert_directory(self, d: DirectoryRecord) -> str: ...
    def get_directories_for_analysis(self, ...) -> list[DirectoryRecord]: ...
    def upsert_file(self, f: FileRecord) -> str: ...
    def get_file_by_id(self, file_id: str) -> FileRecord | None: ...
    def get_file_by_path(self, path: str) -> FileRecord | None: ...
    def get_files_by_paths(self, paths: list[str]) -> list[FileRecord]: ...
    def get_files_by_dir_id(self, dir_id: str) -> list[FileRecord]: ...
    def get_data_files_with_details(self) -> list[FileRecord]: ...
    def get_ungrouped_data_files(self) -> list[FileRecord]: ...
    def update_filename_values_by_pattern(self, ...) -> int: ...
    def upsert_columns(self, cols: list[ColumnRecord]) -> None: ...
    def get_columns_with_stats(self, file_id: str) -> list[ColumnRecord]: ...
    def get_columns_with_semantic(self, file_id: str) -> list[ColumnRecord]: ...
    def get_columns_for_classification(self, file_id: str) -> list[ColumnRecord]: ...

    # --- 파일 그룹 / 파라미터 / 사전 (K1·K2) ---
    def upsert_file_group(self, g: FileGroupRecord) -> str: ...
    def upsert_parameters(self, params: list[ParameterRecord]) -> None: ...   # update 포함
    def get_parameters_by_concept(self) -> dict[str, list[ParameterRecord]]: ...
    def get_all_parameters_for_ontology(self) -> list[ParameterRecord]: ...
    def upsert_data_dictionary(self, entries: list[DictEntry]) -> None: ...
    def get_data_dictionary_simple(self) -> list[DictEntry]: ...

    # --- 엔티티 / 관계 / 그래프 (K3) ---
    def save_table_entities(self, entities: list[EntityRecord]) -> None: ...
    def has_entity_for_file_path(self, path: str) -> bool: ...
    def get_tables_with_entities(self, include_semantic=True) -> list[...]: ...
    def save_relationships(self, rels: list[RelationshipRecord]) -> None: ...
    def get_relationships(self) -> list[RelationshipRecord]: ...
    def add_graph_node(self, node: GraphNode) -> None: ...
    def add_graph_edge(self, edge: GraphEdge) -> None: ...

    # --- 라이프사이클 ---
    def mark_node_done(self, node_name: str) -> None: ...      # 체크포인트(재개)
    def is_node_done(self, node_name: str) -> bool: ...
    def synthesize_access_recipe(self) -> AccessRecipe: ...    # ⏳ 포맷 슬롯만 예약 — 합성 구현은 소비자 전환 단계로 보류(1-C)
    def finalize(self, manifest_meta: ManifestMeta) -> None:  ...  # SQLite→JSONL/YAML 덤프+manifest+hash+README
```

### 4.3 레코드 모델

구버전 Pydantic 모델을 SQLite 테이블 + JSONL 라인 스키마로 재정의. enum 중 `ColumnRole`·`SourceType`는 재사용, **`ConceptCategory`는 open-vocabulary(권장 시드 + 자유값 허용 — D10)**.

### 4.4 소비 측 인터페이스: `EngramReader` + 포맷 검증 (스텁) — 2-A

Engram의 가치 절반은 *플러그인(읽기)* 이다. 쓰기(`EngramStore`)와 **대칭으로 읽기 계약을 미리 스케치**해, 포맷을 실제 소비에 비춰 검증한다. (소비자 *전체* 전환은 비목표지만, 읽기 인터페이스의 *형태*는 지금 고정해 "소비 못 하는 포맷을 동결"하는 함정을 막는다.)

```python
class EngramReader(Protocol):
    @classmethod
    def load(cls, engram_dir: str) -> "EngramReader": ...   # manifest 검증 후 로드 (실패 시 fail-fast)
    def validate(self) -> list[str]: ...                    # schema_version·무결성 해시·필수 레이어 검사 → 위반 목록
    def parameters(self) -> list[ParameterRecord]: ...      # k2_parameters
    def access_recipe(self) -> "AccessRecipe | None": ...   # 없으면 None (이번 단계엔 보통 None)
    def graph(self) -> tuple[list[GraphNode], list[GraphEdge]]: ...   # k3_graph_*
    def manifest(self) -> "Manifest": ...
```

- **format validator**: `load()`가 `schema_version` 호환성 + `integrity.file_hashes` 대조 + 필수 레이어 존재를 확인하고, 불일치 시 즉시 실패.
- 구현 위치: `engram/reader.py`(읽기) + `engram/validate.py`(검증). 이 스텁은 포맷 *검증용*이며, ExtractionAgent의 실제 소비 로직 이식은 후속.

---

## 5. 생산 / 소비 / 라이브러리 3분할 (이 설계의 핵심 통찰)

### 5.1 "어떻게 불러오는지"는 두 개로 쪼개진다

`shared/data/context.py`(DataContext)를 분석하면 "어떻게 불러오나"는 성격이 다른 둘이 섞여 있다.

| 구성요소 | 성격 | 데이터셋 의존? |
|---|---|---|
| **(가) 로딩 기계장치 (코드)**: `get_signals`/병렬로딩/조인/`_apply_temporal_filter`/캐싱/processors | 범용 알고리즘 | ❌ |
| **(나) 로딩 레시피 (데이터)**: entity 키·join·filename_values·temporal·time_column | 데이터셋-고유 파라미터 | ✅ |

핵심 관찰: **(나)는 이미 Cartographer 산출물의 파생/부분집합이다.** `_resolve_*`→K1, `join_config`→K3, `filename_values`→K1, `_param_info`→K2. DataContext는 *런타임에 K1–K3을 재조립*할 뿐. ([`INDEXING_AGENT_ROADMAP.md`](INDEXING_AGENT_ROADMAP.md) I-05/I-06 방향과 일치.)

### 5.2 결론: 따로 만들지 않는다. 하나의 Engram + 3분할 책임

```
        ┌──────────────────────────────────────────────┐
        │   DataAccessKit  (범용 CODE 라이브러리)        │  ← (가) 로딩 기계장치. 스킬 아님(git)
        │   processors · join · temporal · cache · peek  │
        └──────────────────────────────────────────────┘
              ▲ 인덱싱 중 파일 peek          ▲ 소비 중 실제 로드
              │                              │
   ┌──────────┴───────────┐      ┌───────────┴──────────────┐
   │ Cartographer          │      │ ExtractionAgent (얇은 소비자)│
   │  = Engram GENERATOR    │      │  query→param (Engram 읽음)   │
   └──────────┬───────────┘      └───────────▲──────────────┘
              │ produces                      │ reads
              ▼                               │
        ┌──────────────────────────────────────────────┐
        │            데이터셋 1개당 Engram 1개            │
        │  ├─ K1–K5            Ontology  (WHAT)         │
        │  └─ access_recipe.yaml  Access Recipe (HOW)   │
        └──────────────────────────────────────────────┘
```

| 구성 | 종류 | 책임 | 데이터셋마다 새로? |
|---|---|---|---|
| **Cartographer** | 에이전트 | Engram 생성 (이 문서) | — (도구) |
| **Engram** | 파일 아티팩트 | Ontology + Access Recipe 동결 | ✅ 데이터셋당 1개 |
| **DataAccessKit** | 공유 코드 라이브러리 | 실제 파일 로딩·조인·temporal·peek | ❌ 고정 코드 |
| **ExtractionAgent** | 에이전트(코드) | query 이해 → param 해석 (Engram 소비) | ❌ 고정 코드 |

핵심 명제: **"로딩 기계장치(코드)는 스킬화하지 않는다. 데이터셋-고유한 로딩 레시피(데이터)만 Engram에 동결한다."**

### 5.3 Access Recipe 합성 (`synthesize_access_recipe`) — *포맷 슬롯만, 합성은 보류(1-C)*

> **이번 단계 범위**: `access_recipe.yaml` **포맷 슬롯만 예약**한다. 아래 합성 로직 구현은 *ExtractionAgent 소비 전환 단계로 보류*. 지금은 빈/부분 recipe 또는 미생성을 허용(소비자가 없으므로). 포맷을 먼저 못박아 두는 것이 목적.

(향후) finalize 직전, EngramStore가 이미 가진 K1(file_group, directory_pattern)·K3(entities, relationships)에서 `access_recipe.yaml`을 **조립**한다. 이는 *신규 LLM 호출이 아니라*, K3 노드가 이미 LLM으로 내린 판정(cohort/signal 역할, join 키 등 동결된 결과)을 **규칙으로 매핑**하는 것이다.

| Access Recipe 필드 | 출처 (Engram 내부, 이미 결정됨) |
|---|---|
| `sources[].role`, `entity`, `entity_key` | K3 `entities` |
| `sources[].load_strategy`, `file_group`, `filename_pattern` | K1 `file_group` + `directory_pattern` (source_type로 strategy 결정) |
| `relations[]` | K3 `relationships` |
| `temporal[]` | (장기) Knowledge 노드 I-05/I-06; 초기엔 휴리스틱 + HITL 확인 |

### 5.4 Peek/Probe primitive

**가벼운 파일 검사 primitive**(`peek_file`: 스키마·dtype·샘플만)는 `primitives/`에 둔다(§5.5). file_catalog 노드가 쓰고, 장기적으로 [`INDEXING_AGENT_ROADMAP.md`](INDEXING_AGENT_ROADMAP.md) §7 자율 오케스트레이터가 `list_files`/`peek_file` 도구로 재사용.

### 5.5 구조 방침: 결정적 워크플로우 백본 + 얇은 primitives (tool/subagent 보류) — 3

ACPO의 정체성(**재현성 지향·저렴한 지식 공장**)상, Cartographer 본체는 *자율 tool-calling 루프*가 아니라 **결정적 워크플로우**다. (재현성은 LLM 단계 때문에 *완전 보장은 아니지만*, 워크플로우가 자율 루프보다 *변동을 최소화*한다 — §7 재현성 표기 참고.) LLM이 매번 어떤 도구를 부를지 자율 결정하면 변동성↑·비용↑로 ACPO가 파는 가치를 스스로 훼손한다. 트렌디하다는 이유로 전체를 subagent 루프로 바꾸는 것은 *과설계*다.

| 레이어 | 지금 도입? | 근거 / 위치 |
|---|---|---|
| **primitive** (`peek`, jsonl/yaml io, sqlite ops, column profiling) | ✅ **예** — `src/primitives/` | 비용 0·재사용↑. 이미 `peek` 존재 |
| **tool** (classify_columns 등을 LLM-호출 도구로) | ⏳ **보류**(seam만) | 자율 오케스트레이터(ROADMAP §7)·HITL 재실행이 실제 필요할 때 |
| **skill** (playbook) | ↔ Cartographer를 *상위가 부르는 skill*로 취급은 자연스러움. 내부 노드의 skill화는 범주 오류 | — |
| **subagent** (병렬 배치 워커) | ⏳ **비용 벽에서** | `column_classification`/`parameter_semantic`처럼 수백 항목 LLM 배치 노드를 *병렬 subagent*로 → throughput 최적화(§6.4). 구조 필수가 아닌 *최적화* |

→ **방침**: 결정적 워크플로우 백본 + `primitives/` 정식화. tool/subagent는 *seam만 남기고 보류*. (지금 4계층 풀스택은 선형 인덱서에 과함.)

---

## 6. 파이프라인 (구버전 흐름 계승, 저장소 교체, HITL·자가검증 추가, LangGraph 미사용)

### 6.1 3-Phase 12-Node + 단순 러너

```
입력: 데이터 디렉토리
   │
   ▼ PHASE 1 (Rule-based, K1)         [4 nodes]
   [100] directory_catalog   → store.upsert_directory
   [200] file_catalog        → store.upsert_file / upsert_columns   (primitives.peek 사용)
   [250] file_grouping_prep   (ctx only)
   [300] schema_aggregation   (ctx only)
   │
   ▼ PHASE 2 (LLM, K2)        ── 저신뢰 시 HITL(§6.3) ──   [6 nodes]
   [350] file_grouping        → store.upsert_file_group
   [400] file_classification  → store.upsert_file (is_metadata)
   [420] column_classification→ store.upsert_columns / upsert_parameters
   [500] metadata_semantic    → store.upsert_data_dictionary
   [600] parameter_semantic   → store.upsert_parameters (semantic_name 등)
   [700] directory_pattern    → store.upsert_directory (filename_pattern)
   │
   ▼ PHASE 3 (LLM, K3)        ── 모호 관계 시 HITL ──        [2 nodes]
   [800] entity_identification→ store.save_table_entities
   [900] relationship_inference→ store.save_relationships + add_graph_node/edge
   │
   ▼ store.build_recipe_v0()  → 내부 recipe_v0 (K1/K3 파생, SQLite 상주; D15) — finalize 전 probe 입력
   ▼ SELF-VALIDATION (§6.5)   access probes 실행 (store에서 직접 read) → validation_report (실패 시 ↺ refine 루프, *변경 레버 동반* 타깃 재실행 — D16)
   ▼ (보류 1-C) recipe_v0 → access_recipe.yaml *동결*만 보류 (합성 자체는 위에서 수행)
   ▼ store.finalize()         → JSONL/YAML 덤프 + manifest(completeness·issues·validation·capabilities) + 해시 + README
출력: engrams/<engram_id>/  (완성 또는 부분 Engram — manifest가 완전성 선언)
```

> **단순 러너(LangGraph 미사용 — D6)**: 노드는 고정 *리스트*(동적 NodeRegistry 불필요)이며, 러너가 순차 실행 + HITL 루프 + refine 루프를 담당한다.
>
> ```python
> for node in NODES:
>     # 재개: 결정적 노드만 skip. LLM 노드는 run 일관성을 위해 재개 정책에 따름(D14·§6.6)
>     if store.is_node_done(node.name) and resume_ok(node): continue
>     result = node.run(store, ctx)
>     while result.needs_review:                            # HITL 국소 분기(§6.3)
>         ans = hitl.ask(result.question)                   # 대화형 block / --auto: 플래그 후 break
>         if ans is DEFER: store.save_pending_review(...); return   # 비동기 중단(나중 재개)
>         result = node.apply_review(store, ans)
>     store.mark_node_done(node.name, run_id=ctx.run_id)    # 어느 run의 판정인지 기록(D14)
> # 내부 recipe_v0 빌드(D15) — probe 입력. 외부 yaml 동결만 보류(1-C)
> store.build_recipe_v0()
> # 바운드 refine 루프(§6.5) — 변경 레버 동반(D16)
> for _ in range(MAX_REFINE):
>     report = self_validate(store)                         # access probes (store에서 직접 read; reader 아님 — D15)
>     if report.ok: break
>     levers = derive_refine_levers(report)                 # 대립 증거/bound/HITL 승격 (없으면 중단)
>     if not levers: break                                  # 레버 없는 재실행은 no-op → skip(D16)
>     rerun(store, invalidated_nodes(report), levers)       # 레버 주입 타깃 재실행
> store.finalize(meta)
> ```
> durable resume·HITL·refine 모두 **SQLite 단일 원천**으로 처리(별도 checkpointer 없음).
> **재개 일관성(D14)**: `mark_node_done`은 *run_id* 를 함께 기록한다. 재개 시 (a) 결정적 K1 노드는 skip 허용, (b) **LLM 노드(Phase 2·3)는 같은 `run_id` 묶음이 아니면 skip하지 않고 해당 Phase를 재실행**해 *판정 출처가 섞인 artifact* 를 방지. 완성 Engram의 manifest엔 `run_mode: clean|resumed` 와 참여 run_id를 기록(§7).
> Phase 4 `ontology_enhancement`는 구버전에서도 테스트 제외 — **선택적 노드**(기본 비활성).

### 6.2 노드별 EngramStore 호출 매핑 (구 코드 근거)

구 노드들이 저장소에서 호출하는 read/write — 전부 단순 lookup/filter/upsert 라 SQLite 백엔드로 1:1 대체.

| 노드 | 구버전 호출 (DB 서버) | Cartographer 대체 (EngramStore/SQLite) |
|---|---|---|
| entity_identification | `file_repo.get_file_by_id`, `get_files_by_paths`, `get_ungrouped_data_files`; `column_repo.get_columns_with_stats/semantic`; `entity_repo.save_table_entities/bulk_save_group_entities/has_entity_for_file_path` | 동일 시그니처 |
| metadata_semantic | `file_repo.get_file_by_path`; `column_repo.get_columns_for_classification` | 동일 |
| file_grouping(_prep) | `file_repo.get_files_by_dir_id` | 동일 |
| relationship_inference | `entity_repo.get_tables_with_entities/save_relationships/get_relationships/get_relationship_count`; `directory_repo.get_filename_column_mappings` | 동일 + `add_graph_node/edge` |
| ontology_enhancement | `parameter_repo.get_parameters_by_concept/get_all_parameters_for_ontology`; `file_repo.get_data_files_with_details`; `column_repo.get_columns_with_semantic` | 동일 |
| directory_pattern | `directory_repo.get_directories_for_analysis/get_data_dictionary_*/save_pattern_results`; `file_repo.update_filename_values_by_*` | 동일 |

> 결론: **노드의 LLM 로직·프롬프트는 거의 그대로, `self.xxx_repo.` → `store.` 로 바꾸는 수준**.

### 6.3 Human-in-the-Loop (유지, LangGraph 없이)

V1 철학 "Rule Prepares, LLM Decides, *불확실하면 사람에게 질문*"을 계승한다. 러너 `ctx`에 `needs_human_review`/`human_question`/`review_type`을 둔다.

- **발동 조건**: LLM confidence < 임계값(분류·관계), 또는 상호배타적 후보가 비등할 때.
- **동작(§6.1 러너 루프)**: 노드가 `needs_review` 반환 → 질문 제시 → 사람 응답을 `store`에 반영 → 같은 노드 재결정(*국소 분기*). 복잡한 그래프 재라우팅이 아니라 **노드 내/주변 재실행**이므로 LangGraph 불필요.
- **durable**: 도메인 데이터·`pending_review`·`node_done`이 전부 SQLite(단일 원천)에 있어, 대화형 중단/크래시 후에도 재개됨. (LangGraph의 별도 checkpointer가 없으므로 drift 없음 — D6/D11.)
- **무인 모드**: `--auto` 플래그 시 저신뢰도 항목을 *플래그만 남기고* 자동 진행(배치 인덱싱용). 이 플래그된 지점은 §6.5 자가검증의 *우선 타깃*이 된다.

### 6.4 실패·Fallback 정책 — 2-B

"어떤 데이터든"을 받으므로 *깨진 입력·LLM 실패*는 일상이다. 원칙: **한 항목의 실패가 전체 인덱싱을 죽이지 않는다(fail-soft). 단 실패는 반드시 기록한다.**

| 실패 지점 | Fallback |
|---|---|
| **파일 파싱**(인코딩/손상/미지원 포맷) | skip + `manifest.issues[]`에 격리 기록, 계속. 해당 파일은 K1에 `status: unreadable`로 남김 |
| **거대 파일/컬럼** | 전량 로드 대신 `peek` 샘플링(상한 N행/컬럼). 통계는 *표본 기반*으로 표시 |
| **LLM 무응답/형식오류** | LLMMixin 재시도(N회) → 실패 시 (a) 규칙 기반 기본값 적용 가능하면 적용, (b) 불가하면 `low_confidence` 플래그 + (대화형) HITL / (`--auto`) 플래그만 남기고 진행 |
| **LLM 판정 저신뢰** | confidence < 임계 → HITL(§6.3), 또는 `--auto` 시 보류 표기 |
| **노드 부분 실패** | 처리된 항목은 store 커밋(SQLite 트랜잭션 경계), 미처리 항목 목록 기록 → 재개 시 그것만 재시도 |
| **레이어 미완성** | 해당 K 레이어를 `completeness: partial`로 manifest 표기. **부분 Engram도 유효 산출물**(완전성은 manifest가 선언) |

→ 산출물에 **completeness 메타데이터**(레이어별 `ok`/`partial`/`failed` + `issues[]`)를 manifest(§7)에 기록해, 소비자가 신뢰 수준을 판단할 수 있게 한다. **fail-fast 하는 곳은 단 하나** — 입력 디렉토리가 아예 없거나 읽을 파일이 0개일 때.

### 6.5 Self-Validation: Access probes + refine 루프 — D13

**핵심 통찰**: 인덱싱은 *좋은 테스트 재료를 공짜로 생산*한다. 데이터를 한 번 본 결과(access_recipe)와 LLM이 *헷갈린 지점*(HITL/저신뢰 플래그)은, 곧 *"내가 인덱싱한 걸 실제로 access 할 수 있는가"* 를 묻는 probe가 된다. 질문을 *"의미가 맞나"* 가 아니라 *"access 되나"* 로 한정하면 **오라클 = 데이터 자체**가 되어 순환이 없다(text-to-SQL의 execution-guided validation과 동형).

**probe 생성(결정적, LLM 불필요)** — `primitives/probe.py`가 인덱싱 부산물에서 명세를 생성:

| probe 종류 | 무엇을 검사 | 통과 조건 (health check) |
|---|---|---|
| **source smoke** | 각 source를 load_strategy대로 1 표본 로드 | 비어있지 않음 + 선언 컬럼 존재 + dtype 일치 |
| **relation join** | 각 relation 표본 조인 | **coverage**(매칭률 ≥ 임계 — *틀린 키 탐지*) + **cardinality** 성립 |
| **parameter access** | 각(또는 표본) param_key가 선언 source에서 로드 | **non-degeneracy**(전부 null/상수 아님) + (약신호) unit 범위 plausibility |
| **temporal window** | procedure window 적용 | 비어있지 않고 *그럴듯한 크기*의 슬라이스 |
| **HITL 우선 타깃** | LLM이 헷갈린/`--auto`로 자동선택한 지점 | 위 검사를 *우선* 적용(uncertainty-targeted) |

> **"뭔가 로드됨" ≠ 통과**: 반드시 coverage·cardinality·non-degeneracy 같은 *health check*를 동반해야 *조용한 오류*(틀린 join 키가 빈/단건 매칭으로 위장)를 잡는다.

**probe 입력 = 내부 recipe_v0 (D15)**: probe는 `access_recipe`가 필요하다. 그런데 외부 `access_recipe.yaml` *동결*은 보류(1-C)다. ∴ **합성 로직(`build_recipe_v0`)은 P5b에 포함**하여 SQLite의 K1(file_group·directory_pattern)·K3(entities·relationships)에서 recipe_v0를 *내부 객체*로 만들고, *배포 파일로 동결하는 것만* 소비자 전환까지 미룬다. "recipe가 없어서 검증을 못 한다"는 순환을 이렇게 끊는다.

**실행·연결 (reader 아님 — 시점 주의, D15)**: Self-Validation은 **finalize 전 빌드타임**이라 동결물이 아직 없다. 따라서 probe는 `engram/reader.py`(동결 Engram 소비자)가 아니라 **`store`(SQLite)에서 직접** recipe_v0·주장을 읽고, `access_kit`(실제 1표본 로드)로 실행 → `validation_report`. (`reader.py`의 첫 실사용처는 finalize *후* 포맷 검증이다.) 실패 시 §6.1 러너의 **바운드 refine 루프**(`MAX_REFINE`)가 *타깃 노드만* 재실행.

**refine 재실행은 변경 레버를 동반한다 (D16)**: 같은 LLM 입력으로 단순 재호출하면 같은 오답이 재생산되어 비용만 2배가 된다. `derive_refine_levers(report)`가 다음 중 하나 이상을 만들 때만 재실행한다 — ① probe가 노출한 *대립 증거*(예: `relation_join` coverage 0.02 + 더 높은 매칭률을 보인 후보 키 B)를 해당 노드 프롬프트에 주입, ② coverage/cardinality *bound·threshold* 조정, ③ HITL 승격(대화형) / `--auto` 플래그 격상. **레버가 없으면 재실행은 no-op로 간주하고 skip**(무한·무익 반복 방지).

**천장·범위 (정직한 한계)**:
- **access ≠ semantics**: "로드되고 70 근처 200개"는 *access 성공*을 증명하지 *"이게 심박수다"* 를 증명하지 않는다. unit plausibility는 *gross mislabel*만 약하게 잡는 보너스. **의미 정확성 평가는 외부(독립 Level1)** — D4 보존.
- **HITL-seed는 우선순위지 완전 커버리지 아님**: *자신 있게 틀린* 경우(HITL 미발동)는 안 잡히므로, 모든 source·relation에 대한 *체계적* probe로 보완.
- **빌드타임 전용 + privacy**: 자가검증은 raw 데이터가 있는 *빌드 시점*에만 가능. **Engram에는 *명세 + 집계 결과*(pass/fail·coverage%·범위)만 동결하고, *원시 표본 값·구체 caseid는 절대 동결 금지*** (PHI 유출 방지 — §7 `validation`). 소비자는 raw가 없어 재실행 불가(정상).
- **의미 probe(NL→param_key 자동생성)는 이번 프로젝트 제외**(self-grading 순환 위험 + 범위 밖).

### 6.6 재개(resume)와 비결정성 — artifact 일관성 규칙 (D14)

문제: `is_node_done` skip은 *결정적* 노드엔 안전하지만, **LLM 노드는 temp=0이어도 비결정적**이다. 완료된 LLM 노드를 그대로 두고 뒤만 재개하면, 최종 Engram이 *앞부분=run-A 판정 + 뒷부분=run-B 판정* 으로 섞인다. 이 artifact는 **어떤 단일 실행과도 일치하지 않고**, provenance(`llm.snapshot`·`agent_commit`)로도 설명되지 않는다(재현 기준점이 무의미해짐).

규칙:

| 단계 | 재개 정책 |
|---|---|
| **Phase 1 (결정적, K1)** | 완료 노드 skip 허용(결과 동일 보장). |
| **Phase 2·3 (LLM, K2/K3)** | 같은 `run_id` 묶음으로 완료된 경우에만 skip. *다른 run에서 중단된 경우* 해당 Phase를 **재실행**(부분 LLM 판정 폐기). |
| **HITL DEFER 중단** | 사람 응답·`pending_review`는 데이터지 LLM 비결정이 아니므로, 응답 반영 후 **해당 노드만** 재개(섞임 없음). |

구현: `mark_node_done(node, run_id)`로 판정 출처를 기록하고, 러너 `resume_ok(node)`가 위 표를 적용한다. 완성 manifest에 `reproducibility.run_mode: clean|resumed` 와 참여 `run_ids`를 남겨 *섞인 산출물 여부를 소비자가 식별* 할 수 있게 한다(§7). (평가 측 **resume-consistency 지표** — [`CARTOGRAPHER_EVALUATION.md`](CARTOGRAPHER_EVALUATION.md) §5 — 가 이 규칙의 준수를 실측한다.)

---

## 7. Manifest & Provenance

`store.finalize()` 가 ACPO_SKILL.md §4 스펙대로 `manifest.yaml` 생성. **키는 `engram:`로 통일**(ACPO_SKILL의 `skill:`은 별칭으로 허용 — §11 표기).

```yaml
schema_version: "1.0"
engram:                          # (ACPO_SKILL의 skill: 와 동일 의미; engram으로 통일)
  id: <engram_id>
  created_at: <ISO8601>
  created_by: "cartographer"
source:
  data_root: <입력 디렉토리>
  num_files: <int>
  num_parameters: <int>
indexing:
  agent_version: <cartographer semver>
  agent_commit: <git hash>
  llm: {provider, model, temperature, snapshot}
layers:
  K1: {...}
  K2: {...}
  K3: {...}
  K4: {included: false}
  K5: {included: false}
  access_recipe: {included: false, note: "recipe_v0는 내부 빌드(D15)되어 probe에 사용됨; 외부 yaml 동결만 보류(1-C)"}
completeness:                   # 2-B: 부분 산출물도 유효 — 소비자가 신뢰 수준 판단
  K1: ok                        # ok | partial | failed
  K2: ok
  K3: ok
capabilities:                   # ★ partial Engram의 *사용 가능 범위*를 선언 (소비자 fail-fast 기준)
  parameter_resolution: true    # K1+K2 있으면 가능 (Level1 retrieval 등)
  graph_query: true             # k3_graph_* 있으면 가능
  access_load: false            # access_recipe.yaml 동결 전이면 false (로딩 불가)
  temporal_filter: false        # temporal[] 동결 전이면 false
issues:                         # 2-B: fail-soft로 건너뛴 항목
  - { file: "broken.csv", stage: file_catalog, error: "encoding", action: skipped }
validation:                     # §6.5 access 자가검증 — ★명세+집계만(원시값·caseid 금지=PHI)
  refine_iterations: 1
  passed: true
  probes: { source_smoke: "5/5", relation_join: "3/3", parameter_access: "258/260", temporal_window: "1/1" }
  failures: []                  # 예: [{ probe: relation_join, source: vitals→clinical, reason: "coverage 0.02 (틀린 키 의심)" }]
reproducibility:                # 아티팩트 재현성 ≠ 파이프라인 재현성
  artifact_frozen: true         # 동결된 이 Engram만이 재현의 기준점
  rule_stages_deterministic: true    # Rule-Prepares(규칙 전처리)는 결정적
  llm_stages_deterministic: false    # LLM-Decides(의미 판정)는 확률적 (temp=0이어도 모델 스냅샷·비결정성 존재)
  pipeline_reproducible: false       # ∴ 재실행이 동일 Engram을 보장하지 않음
  run_mode: clean               # clean | resumed (D14·§6.6 — resumed면 판정 출처가 섞였을 수 있음)
  run_ids: [<run_uuid>]         # 이 Engram에 기여한 run 식별자(들). 2개 이상이면 LLM 판정 혼합 가능
integrity:
  hash_algo: sha256
  file_hashes: {...}
  artifact_hash: <전체 해시>
distribution:
  privacy_review:
    raw_data_excluded: true
    quasi_identifier_scan: <결과>   # caseid·파일 절대경로 등 준식별자 스캔 포함
    phi_excluded: <검사결과>
```

- **재현성(정직한 표기)**: Cartographer는 **Rule-Prepares / LLM-Decides** 하이브리드다. 규칙 전처리(Phase 1, 패턴 추출 등)는 결정적이지만, **LLM 의미 판정(K2/K3)은 확률적**이라 *동일 입력 재실행이 동일 Engram을 보장하지 않는다*(temp=0이어도). 따라서 재현의 기준점은 *파이프라인이 아니라 동결된 Engram 아티팩트*다. (provenance의 `llm.snapshot`·`agent_commit`은 *근사 재현*을 돕는 메타데이터.)
- **privacy 검사 (계층적 정책 — Q5 확정)**: finalize 전에 K1–K3 + validation을 스캔하여 —
  1. **진짜 PHI**(`MRN`/`SSN`/`DOB`/이름 패턴, 환자-레벨 *값*) → **하드 차단**(export 실패).
  2. **구조적 식별자**(`caseid` 같은 *키·컬럼 이름*, 개수) → **허용** (access_recipe의 join 키라 구조적으로 필요; 환자별 *값*·*행*은 애초에 Engram 미포함).
  3. **파일 절대경로** → **기본 익명화**(`data_root` 상대화/해시).
  > 원칙: **"환자-레벨 *값*"은 항상 배제, "스키마-레벨 *이름*"은 허용.** validation_report도 집계만(§6.5).

- **필드-레벨 화이트리스트 (값 누출 차단 — Q5 보강)**: "이름은 허용·값은 배제" 원칙은 *컬럼 통계·파생값* 에서 새기 쉽다. 다음을 명시적으로 통제한다.

  | Engram 필드 | 위험 | 정책 |
  |---|---|---|
  | `k1_columns.jsonl`의 `sample_values`/unique values | 환자값(이름·MRN·날짜)이 표본에 섞일 수 있음 | **drop** (스키마 추론에 쓴 뒤 동결물엔 미포함). 필요 시 *dtype·n_unique·null률* 같은 **비식별 통계만** |
  | `raw_stats`의 min/max/quantile | 날짜·나이·희귀값의 극단치가 준식별자 | 수치 측정값만 허용. **날짜·나이·자유텍스트 컬럼의 min/max는 redact** |
  | `filename_values`(예: caseid) | 키 *이름*은 허용(D-Q5), 그러나 *추출된 값 집합*은 환자 매핑 | **키 이름·개수만 동결, 값 리스트는 미포함** |
  | validation `probes`/`failures` | 표본 caseid·구체 값이 reason에 섞일 수 있음 | 집계·비율·범위만(§6.5). **구체 식별자 문자열 금지** |

  > 기본은 **deny-by-default**: 위 화이트리스트에 없는 *값성(value-bearing)* 필드는 동결 전 `privacy.py`가 차단/redact하고 `manifest.distribution.privacy_review`에 처리 내역을 남긴다.

---

## 8. 범용화(dataset-agnostic) 설계

**포맷(§3)은 처음부터 범용**(D10). 남은 *프롬프트 레벨* 범용화만 2단계.

1. **포맷 범용 (이번)**: Access Recipe는 `sources/load_strategy/relations` 추상모델(§3.2), `ConceptCategory`는 open-vocabulary. → 세 데이터모델이 모두 *같은 그릇*에 담김.
2. **프롬프트 범용 (2단계)**: VitalDB few-shot 예시(`Solar8000/HR`, `caseid`, `.vital` — `column_classification`/`entity_identification`/`directory_pattern`/`file_grouping`)를 코드 상수가 아닌 *설정/예시 모듈*로 분리. 이번엔 자리만.
3. **manifest의 `source`** 가 데이터셋 정체성을 담아, 같은 코드가 다른 engram_id를 만든다 (ACPO_FRAMEWORK §7.4 출력 측 기반).

### 8.1 검증 데이터셋 (확정): VitalDB · MIMIC-IV · eICU

dataset-agnostic 주장을 검증하는 **공식 테스트 데이터셋은 세 개**다. 마침 세 가지 `load_strategy`를 모두 커버해, 포맷·자가검증의 일반성을 실증한다.

| 데이터셋 | 데이터 모델 | 주 `load_strategy` | 검증 포인트 |
|---|---|---|---|
| **VitalDB** | 코호트 CSV + 케이스별 `.vital` 신호파일 | `per_entity_file` | filename_pattern·signal 그룹·temporal window |
| **MIMIC-IV** | 관계형 테이블(`chartevents` 등 long-format) | `long_format` | long-format 파라미터(name/value)·다중 테이블 FK |
| **eICU** | 관계형 테이블(`vitalperiodic` wide + lab long 혼재) | `tabular_wide` + `long_format` | wide/long 혼합·다른 식별자(`patientunitstayid`) |

→ **검증 기준 (2단계)**: 세 데이터셋 각각에 Cartographer를 돌려 Engram을 생성하고 — **(a) §6.5 access 자가검증 통과**(구조·로딩) + **(b) 외부 hold-out 사전 대비 intrinsic K2/K3 평가 통과**([`CARTOGRAPHER_EVALUATION.md`](CARTOGRAPHER_EVALUATION.md) Track A) — 둘 다 만족하면 "어떤 데이터든" 주장이 *구조와 의미* 양면에서 실증된다(ACPO_FRAMEWORK §7.4 일반화).
*주의*: access 통과(a)는 *필요조건이지 충분조건이 아니다* — "로드된다 ≠ 의미가 맞다". 그래서 (b)를 분리해 함께 본다. MIMIC/eICU의 *의미 품질*은 프롬프트 범용화(위 2단계)에 의존할 수 있어, (b)의 절대 점수는 그에 따라 달라질 수 있다(회귀·상대비교로 추적).

---

## 9. 디렉토리 구조 제안 (greenfield)

```
Cartographer/                       (패키지 루트)
├── src/
│   ├── pipeline/
│   │   ├── runner.py               단순 순차 러너 (HITL 루프 + refine 루프; LangGraph 미사용 — D6)
│   │   ├── nodes_list.py           NODES = [...] 고정 리스트 (동적 NodeRegistry 불필요)
│   │   └── ctx.py                  RunContext (제어흐름 + HITL 신호만 — 슬림, D11)
│   ├── nodes/                       노드 로직 (저장소 호출만 교체)
│   │   ├── directory_catalog.py
│   │   ├── file_catalog.py
│   │   ├── file_grouping/ ...
│   │   ├── parameter_semantic/ ...
│   │   └── relationship_inference/ ...
│   ├── primitives/                  ★ 얇은 재사용 primitive 레이어 (§5.5)
│   │   ├── peek.py                 peek_file (스키마·dtype·샘플)
│   │   ├── jsonl_io.py             JSONL/YAML 읽기·쓰기
│   │   ├── sqlite_ops.py           SQLite upsert/쿼리 헬퍼
│   │   ├── profiling.py            컬럼 통계 프로파일링
│   │   └── probe.py                access probe 명세 생성 (인덱싱 부산물 → §6.5)
│   ├── validation/                  ★ Self-Validation (access probes — §6.5)
│   │   ├── run.py                  probe 실행 (access_kit + reader)
│   │   ├── health.py               coverage·cardinality·non-degeneracy·plausibility
│   │   └── report.py               validation_report (명세+집계만, PHI-safe)
│   ├── engram/                       ★ Engram 저장소 (SQLite 백엔드)
│   │   ├── base.py                 EngramStore Protocol
│   │   ├── sqlite_store.py         SQLiteEngramStore (작업 스토어 + 체크포인트)
│   │   ├── records.py              레코드(테이블/라인 스키마) Pydantic 모델
│   │   ├── recipe.py               synthesize_access_recipe (⏳ 슬롯만; 합성 보류 — 1-C)
│   │   ├── dump.py                 SQLite → JSONL/YAML 덤프 (finalize)
│   │   ├── reader.py               EngramReader (소비 측 읽기 — 2-A)
│   │   ├── validate.py             format validator (schema_version·해시·필수레이어 — 2-A)
│   │   ├── manifest.py             Manifest 생성/검증 (completeness·issues 포함)
│   │   ├── privacy.py              PHI·준식별자 스캔
│   │   └── graph.py                그래프(nodes/edges) k1–k3 파생 직렬화 (그래프 lib 비사용)
│   ├── access_kit/                  ★ 공유 라이브러리 (DataAccessKit)
│   │   ├── processors/             tabular · signal
│   │   ├── loader.py               source 로드 (소비 시; primitives.peek 사용)
│   │   ├── join.py                 relation 기반 조인
│   │   └── temporal.py             temporal window 필터
│   ├── hitl/                        HITL 질문/응답 핸들러
│   ├── llm/                         LLM 클라이언트 + 호출 로그/결정 캐시
│   └── config.py
├── engrams/                         ★ 최종 산출물 (순수 파일)
│   └── <engram_id>/ ...
├── .cache/                          빌드 스크래치(build.sqlite, LLM 캐시) — gitignore
├── tests/                           golden-Engram 픽스처 테스트
└── README.md
```

> `access_kit/` 는 Cartographer(인덱싱 중 peek)와 향후 ExtractionAgent(소비 중 로드)가 *함께 쓰는* 코드. 구 `shared/processors`·`shared/data/context.py`의 (가) 로딩 기계장치를 정제 이식. `shared/database/*` 는 가져오지 않는다.

---

## 10. 구축 순서 (로드맵 제안)

| 단계 | 작업 | 산출 |
|---|---|---|
| **P0** | `primitives/` + `engram/` 골격: `EngramStore` Protocol + `SQLiteEngramStore`(upsert·체크포인트) + 레코드 모델 | 서버 없이 동적 read/update |
| **P1** | `access_kit/` 골격: `primitives.peek` + tabular/signal processor 이식 + LLM 호출 로그/캐시 + fail-soft 정책(§6.4) | 파일 스키마/샘플 읽기 |
| **P2** | Phase 1 노드 이식 → K1 | (SQLite 내부) K1 |
| **P3** | Phase 2 노드 이식 + HITL 훅 → K2. ★ **여기까지 = minimal Engram(K1+K2)** — 부분 `dump`로 출시 가능(2-C) | K2 parameter (minimal Engram) |
| **P4** | Phase 3 노드 + 그래프(k1–k3 파생) → K3 | K3 |
| **P5** | `dump`/`finalize`(manifest·completeness·해시·README·privacy) + `EngramReader`/`validate`(2-A). *recipe 합성은 보류(1-C)* | 완성 Engram + 읽기·검증 |
| **P5b** | `engram/recipe.py` **`build_recipe_v0`(내부 합성 — D15)** + `primitives/probe.py` + `validation/`(run·health·report, **store 기반 read**) + 러너 **바운드 refine 루프**(MAX_REFINE, *변경 레버 동반* — D16) → manifest `validation` (§6.5) | recipe_v0 + access 자가검증 + 자동 정련 |
| **P6** | 소규모 합성 데이터 end-to-end 검증(golden-Engram) + 중단/재개(**재개 일관성 D14 검증**) + fail-soft + **probe/refine** 테스트 | 첫 (검증된) Engram 산출물 |
| **P7** | **3개 실데이터셋 검증(§8.1): VitalDB·MIMIC-IV·eICU** 각각 인덱싱 → **(a) access 자가검증 통과 + (b) intrinsic K2/K3 평가 통과**([`CARTOGRAPHER_EVALUATION.md`](CARTOGRAPHER_EVALUATION.md) Track A) | dataset-agnostic 실증 (구조 + *의미 품질*) |

> 의미 probe(NL→param_key) 자동생성, access_recipe 합성, K4/K5 채움, 프롬프트 범용화, ExtractionAgent 소비 전환은 **이 로드맵 이후**(또는 범위 밖). P7의 MIMIC/eICU *의미 품질*은 프롬프트 범용화와 함께 강화.

---

## 11. ACPO 문서와의 관계

| 문서 | Cartographer와의 관계 |
|---|---|
| [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md) | 프레임워크(K1–K5, I1–I3)는 저장소-무관이라 유효. 단 §3·§4.1의 *저장 구현* 서술("PostgreSQL 12개 테이블 + Neo4j")은 Cartographer(파일/Engram)로 대체됨 — 해당 문서에 포워드 노트 권장. |
| [`ACPO_SKILL.md`](ACPO_SKILL.md) | Engram = ACPO Skill 구현체. **포맷 §3·manifest §4는 계승**, **저장 방식(DB→export)은 본 문서가 superseded**(파일 only + Access Recipe 추가). manifest 키는 `engram:`로 통일(`skill:` 별칭 허용). |
| [`INDEXING_AGENT_ROADMAP.md`](INDEXING_AGENT_ROADMAP.md) | I-01~I-09의 *필드*는 계승하되, **저장 메커니즘은 재매핑**: pgvector `vector(1536)`/`ivfflat` → `.npz` numpy(brute-force) 또는 sqlite-vss; Neo4j Cypher(I-04 Dataset·I-05 Knowledge) → JSONL/SQLite. `k2_parameters.jsonl`엔 *자리만*. |
| [`CARTOGRAPHER_RELATED_WORK.md`](CARTOGRAPHER_RELATED_WORK.md) | 선행연구 지형·이름 충돌·novelty (논문화 참고). |

> **핵심**: Cartographer는 `파일 only`(영속 원천 1개) + **"무엇+어떻게"를 한 Engram에** 담고, 동적 인덱싱은 임베디드 SQLite로 처리한다.

---

## 12. 결정이 필요한 Open Questions

| Q | 선택지 | 메모 |
|---|---|---|
| ~~Q1 이름~~ | **Cartographer(에이전트) / Engram(산출물)** | ✅ 확정 |
| ~~작업 스토어~~ | **임베디드 SQLite + finalize 시 JSONL/YAML 덤프** | ✅ 확정 (서버 0) |
| ~~HITL~~ | **유지** (`--auto`로 무인 가능) | ✅ 확정 |
| ~~LangGraph~~ | **미사용 — 단순 러너** | ✅ 확정 (HITL이어도 불필요; checkpointer drift 회피 — D6) |
| ~~Q3~~ engram_id 명명 | **하이브리드**: 자동 `<dirname>_<llm>_<date>` 기본 + `--id` override | ✅ 확정 |
| ~~Q5~~ Privacy 발견 시 | **계층적**: 진짜 PHI(MRN/SSN/DOB/이름) = 하드 차단 / 구조적 식별자(키·컬럼 *이름*) = 허용 / 절대경로 = 기본 익명화 (§7) | ✅ 확정 |
| ~~Q6~~ 재인덱싱 | **거부/새버전**: 존재 시 실패 (`--force` 덮어쓰기, `--new-version`=`_v2`). 증분(I-08)은 나중 | ✅ 확정 |
| ~~Q7~~ access_kit 이식 | **복사 후 정제** (구 `shared`에서 복사 → DB 의존 제거·단순화) | ✅ 확정 |
| ~~Q9~~ refine 루프 | **MAX_REFINE=2 + "노드 N부터 거친 재실행"** + **변경 레버 필수(D16)** | ✅ 확정 (레버 없는 재실행은 skip) |
| ~~Q8 산출물명~~ | **Engram 확정** (후보였던 'Atlas'는 AutoSchemaKG의 "ATLAS"와 충돌해 회피) | ✅ — 단 'Engram'도 AI-memory 분야 사용례가 있어 최종 상표/논문 확인 권장 |
| **Q10** 재개 일관성 | **결정적만 skip, LLM 단계는 run 경계 보존(D14·§6.6)** | ✅ 확정 (정책). manifest `run_mode` 표기 |
| **Q11** recipe_v0 시점 | **내부 합성은 P5b, 외부 yaml 동결만 보류(D15)** | ✅ 확정 (probe 순환 해소) |

### 12.1 착수 전 *닫아야 할* 구현 스펙 (설계 결정 ≠ 구현 스펙)

설계 결정(D1–D16)은 확정이나, 아래 *구현 스펙*은 P0~P5b 진입 전 확정 필요(코드 작성의 선행조건):

- **SQLite DDL + JSONL export mapping**: 테이블 스키마, JSON 필드 저장방식(JSONB 부재), UUID·타입 매핑, 대량 insert 경로(§4 보강).
- **`build_recipe_v0` 매핑 규칙**: K1/K3 → sources/relations/temporal 결정 규칙(§5.3 표를 코드 수준으로).
- **노드 이식 경계**: "프롬프트·LLM 로직 복사" vs "재작성"의 선. 특히 K3의 Neo4j Cypher → JSONL 파생(§6.2)은 *재작성*에 가까움.
- **refine 레버 카탈로그**: probe별 `derive_refine_levers` 구체 규칙(D16).
- **privacy 화이트리스트 구현**: §7 deny-by-default 필드 목록 → `privacy.py`.

---

*문서 작성일: 2026-05-31*
*상태: **설계 결정(D1–D16) 확정.** 단 §12.1의 구현 스펙(SQLite DDL·recipe_v0 매핑·이식 경계·refine 레버·privacy 화이트리스트)은 착수 전 확정 필요 — "설계 완료, 구현 스펙 마감 진행 중".*
