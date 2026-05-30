# ACPO Skill: Distributable Ontology Artifact

> **⚠️ 저장 방식 SUPERSEDED (2026-05-31)**: 본 문서의 `DB(작업) → exporter → 파일(배포본)` 구조는 [`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md)로 대체되었다. Cartographer(구 IndexingAgent 차세대)는 DB 서버 없이 인덱싱 도중엔 임베디드 SQLite, 산출물은 순수 파일 **Engram**(= 본 문서의 Skill 구현체)을 직접 생성한다(export 단계 없음). **여전히 유효한 부분**: §3 아티팩트 포맷, §4 manifest(키는 `skill:`→`engram:`으로 통일), §7 privacy 검사, §9 ablation 활용. **무효**: §5(DB export/activate 라이프사이클), §7.1 loader의 DB 복원 단계.
>
> **Status**: 설계 제안서 (저장 방식은 superseded, 포맷/manifest/ablation은 계승)
>
> 이 문서는 [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md)에서 정의한 K1–K5 ontology의 *오프라인 인덱싱 산출물*을 **재사용 가능한 단일 단위로 동결·배포·교체**할 수 있게 만드는 ACPO Skill의 설계를 기술한다. (구체 구현은 Cartographer의 Engram으로 실현 — [`CARTOGRAPHER_DESIGN.md`](CARTOGRAPHER_DESIGN.md).)
>
> 핵심 아이디어 한 줄: **"한 번 인덱싱한 결과를 빼다 꽂다 할 수 있게."**

---

## 1. 동기 (Why ACPO Skill)

### 1.1 현재 시스템의 운영적 한계

지금 IndexingAgent는 한 번 실행되면 PostgreSQL/Neo4j에 *영속적으로* K1–K3을 기록한다. 이로 인해 다음 작업이 모두 무겁다.

- **다른 데이터셋으로 전환**: VitalDB → MIMIC-IV로 바꾸려면 DB 초기화 후 IndexingAgent 재실행. 수십 분 작업.
- **버전 비교**: 같은 데이터셋이라도 "gpt-4o로 인덱싱한 K2 vs Claude Sonnet 4로 인덱싱한 K2" 비교가 사실상 불가.
- **Ablation**: ACPO ON/OFF 비교를 위해 DB 백업/복원 필요. 수동 작업.
- **공유/배포**: 다른 연구자/병원과 공유하려면 raw 데이터까지 같이 보내야 하는데, 환자 데이터라 불가.
- **재현성**: 6개월 뒤 같은 평가를 재현하려면 IndexingAgent가 그때와 같은 결과를 줄 거라는 보장이 없음(LLM 호출 결과가 약간씩 달라짐).

### 1.2 ACPO Skill이 답하는 다섯 가지 질문

| Q | 답 |
|---|---|
| Q1. 인덱싱 결과를 *한 줄로 전환* 할 수 있나? | `acpo skill activate mimic_v1` |
| Q2. 같은 데이터셋의 *다른 인덱싱 버전* 을 보존할 수 있나? | `vitaldb_v1` (gpt-4o), `vitaldb_v2` (sonnet-4) 병존 |
| Q3. 인덱싱 결과만 *환자 데이터 없이* 다른 곳에 보낼 수 있나? | JSON skill 파일 압축 → 공유 |
| Q4. ACPO를 *완전히 꺼서* 베이스라인 비교가 가능한가? | `acpo skill deactivate` (passthrough mode) |
| Q5. 1년 뒤 같은 평가를 *재현* 할 수 있나? | manifest의 provenance 메타데이터로 LLM 모델·코드 버전까지 추적 |

### 1.3 framework 차원의 가치

이 작업은 [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md)의 다음 섹션을 직접 강화한다.

- **§4.1 (Offline phase)**: "인덱싱 결과는 ACPO Skill 아티팩트로 동결된다"는 한 문장이 추가됨
- **§5 (Empirical Evaluation)**: Skill ON/OFF 비교가 *한 명령으로 자동화* 됨 → D5(동일 LLM ablation) 더 깔끔
- **§7.4 (다른 데이터셋 일반화)**: "MIMIC용 skill 빌드 → 활성화 → 동일 60%p 격차 재현" 흐름이 1일 작업으로 단축
- **§8 (Summary)**: *distributable, privacy-preserving knowledge artifact* 가 실용적 가치로 추가됨

---

## 2. 개념 정의

### 2.1 ACPO Skill이란 무엇인가

> **ACPO Skill** 은 특정 데이터셋에 대해 IndexingAgent가 산출한 K1–K5 ontology와, 그 산출 과정의 provenance 메타데이터를 묶은 **자기-기술적(self-describing) 단일 디렉토리 아티팩트**이다.

세 가지 성질을 만족한다.

| 성질 | 의미 |
|---|---|
| **Frozen** | 한 번 export되면 변하지 않음. 재현·비교의 기준점. |
| **Inspectable** | 사람이 직접 파일을 열어 K2 parameter 목록을 검토 가능. binary opaque 아님. |
| **Self-contained** | 별도 raw 데이터·외부 KB·표준 ontology 의존 없이 단독으로 로드 가능. |

### 2.2 Skill이 *아닌* 것

오해를 막기 위해 명시한다.

- ❌ Skill은 **raw 데이터를 포함하지 않는다**. `.vital` 파일, clinical_data.csv 등 환자 데이터는 일절 들어가지 않는다.
- ❌ Skill은 **LLM 가중치를 포함하지 않는다**. 인덱싱에 사용한 모델은 manifest의 식별자(`gpt-4o`, `claude-sonnet-4-20250514`)로만 기록.
- ❌ Skill은 **IndexingAgent 코드를 포함하지 않는다**. 코드는 git에 있고, manifest의 `indexing_agent_commit` 필드가 그것을 참조.
- ❌ Skill은 **DB 스키마 마이그레이션 도구가 아니다**. 우리 K1–K5 산출물 구조만 다룬다.

### 2.3 Single vs Multiple skills

본 설계는 **한 시점에 하나의 active skill** 만 허용한다.

```
   inactive/
     ├── vitaldb_v1/          ← export됨, 보관 중
     ├── vitaldb_v2/
     ├── mimic_v1/
     └── synthetic_test/

   active: vitaldb_v1         ← 현재 DB/Neo4j에 로드된 상태
```

`activate(new)` 호출 시 기존 active skill은 자동으로 deactivate된다. 멀티 active(layered/namespace)는 [§10. Future Work](#10-future-layered-composition)에서 다룬다.

---

## 3. Artifact Format (JSON-primary)

### 3.1 디렉토리 구조

```
skills/
└── vitaldb_v1/
    ├── manifest.yaml              ← 메타데이터 + provenance + 무결성 해시
    ├── README.md                  ← 사람이 읽는 요약 (자동 생성)
    │
    ├── k1_file_schema.jsonl       ← directory_catalog + file_catalog + column_metadata
    ├── k2_parameters.jsonl        ← parameter 테이블 전체 (가장 핵심)
    ├── k3_entities.jsonl          ← table_entities
    ├── k3_relationships.jsonl     ← table_relationships
    ├── k3_neo4j_nodes.jsonl       ← Neo4j 노드 export (Cypher 대신)
    ├── k3_neo4j_edges.jsonl       ← Neo4j 엣지 export
    │
    ├── k4_synonyms.json           ← (있을 때만) Level1 빌드 시 생성한 synonym map
    ├── k4_embeddings.npz          ← (있을 때만) parameter embedding 캐시
    │
    └── k5_procedural_rules.yaml   ← (장기) PCO 구조화된 룰. 초기엔 ParameterResolver 프롬프트 발췌
```

### 3.2 포맷 선택 근거 요약

[ACPO_FRAMEWORK §1.1](ACPO_FRAMEWORK.md)의 design 토론에서 확인된 4가지 시나리오 모두에서 JSON-primary가 우위였다.

- **Diff 친화적** (`git diff`로 두 skill 비교)
- **Privacy 검증 친화적** (raw 환자 데이터 미포함을 사람이 직접 확인 가능)
- **DB 버전 독립** (PostgreSQL 15 → 17 마이그레이션에서도 동작)
- **Ablation 자동화 친화적** (activate가 빠름, 스크립트화 용이)

단점은 **loader를 우리가 직접 작성** 한다는 점(~200줄 추정). ACPO 테이블이 단순하므로 비용 작음.

K4 embeddings만 `.npz` (numpy binary) — base64 JSON으로 만들면 비효율적이므로 이건 어쩔 수 없음.

### 3.3 각 파일의 라인 단위 스키마 예시

**`k2_parameters.jsonl`** (가장 핵심)

```jsonl
{"param_id": "uuid-...", "param_key": "Solar8000/HR", "semantic_name": "Heart Rate", "unit": "/min", "concept_category": "Vital Signs", "file_id": null, "group_id": "uuid-..."}
{"param_id": "uuid-...", "param_key": "Solar8000/PLETH_HR", "semantic_name": "Plethysmography Heart Rate", "unit": "/min", "concept_category": "Vital Signs", "file_id": null, "group_id": "uuid-..."}
...
```

**`k3_neo4j_nodes.jsonl`**

```jsonl
{"label": "Parameter", "properties": {"key": "Solar8000/HR", "name": "Heart Rate", "unit": "/min", "concept_category": "Vital Signs"}}
{"label": "FileGroup", "properties": {"group_id": "uuid-...", "name": "vital_case_records", "file_count": 6384}}
{"label": "ConceptCategory", "properties": {"name": "Vital Signs"}}
...
```

**`k3_neo4j_edges.jsonl`**

```jsonl
{"type": "HAS_COLUMN", "from": {"label": "RowEntity", "match_key": "file_id", "match_value": "..."}, "to": {"label": "Parameter", "match_key": "key", "match_value": "Solar8000/HR"}, "properties": {}}
...
```

> Neo4j는 ID가 휘발성이므로 노드를 *match key* 기준으로 식별한다. loader는 노드를 먼저 MERGE한 뒤 엣지를 만든다.

**`k5_procedural_rules.yaml`** (현재 단계, 향후 PCO와 호환)

```yaml
cross_device_hierarchy:
  vital_signs:
    description: "심박수·혈압·SpO2 등 일반 활력 징후"
    prefer:
      - Solar8000
    matches_pattern:
      - "Solar8000/HR"
      - "Solar8000/PLETH_*"
      - "Solar8000/NIBP_*"
  respiratory:
    description: "호흡·환기 파라미터"
    prefer:
      - Primus
  anesthesia_depth:
    prefer:
      - BIS
  drug_infusion:
    prefer:
      - Orchestra

measurement_vs_setting:
  rule: "ALWAYS prefer measured/observed over Set/target unless explicitly requested"
  examples:
    - prefer: "Solar8000/VENT_INSP_TM"
      over: "Primus/SET_INSP_TM"

effect_site_vs_target:
  rule: "Prefer CE (Effect-site Concentration) over CT (Target Concentration) when query asks about patient effect"
  examples:
    - prefer: "Orchestra/PPF20_CE"
      over: "Orchestra/PPF20_CT"
```

이 YAML이 [`FUTURE_WORK.md`](FUTURE_WORK.md) Part A Layer 1 (PCO) 구현 시 그대로 자료구조 입력으로 사용된다. K5의 *결정론화* 와 *artifact 분리* 가 동시에 달성된다.

---

## 4. Manifest Specification

`manifest.yaml`은 skill의 정체성과 출처를 기록한다. **provenance가 reproducibility의 핵심**이다.

```yaml
# manifest.yaml
schema_version: "1.0"           # ACPO Skill format 버전

skill:
  id: vitaldb_v1                # 고유 식별자 (디렉토리 이름과 동일)
  display_name: "VitalDB Open 1.0.0 — GPT-4o indexing"
  description: |
    Indexing result of VitalDB Open Dataset 1.0.0 (6,384 cases)
    using gpt-4o as the LLM for K2/K3 semantic augmentation.
  created_at: "2026-05-27T16:00:00+09:00"
  created_by: "indexing-agent"

source:
  dataset:
    name: "VitalDB Open Dataset"
    version: "1.0.0"
    citation: "Lee HC et al. Sci Data 2022"
    url: "https://vitaldb.net/"
  data_root: "/path/to/Open_VitalDB_1.0.0"   # 원본 위치 (참고용, 재배포 시 익명화 가능)
  num_cases: 6384
  num_parameters: 260

indexing:
  agent_version: "0.4.2"          # IndexingAgent 코드 버전 (semver)
  agent_commit: "abc123..."        # git commit hash
  llm:
    provider: openai
    model: gpt-4o
    temperature: 0.0
    snapshot: "gpt-4o-2024-08-06"  # 모델 스냅샷 (재현성)
  embedding:
    provider: openai
    model: text-embedding-3-small
    dim: 1536
  started_at: "2026-05-27T14:00:00+09:00"
  finished_at: "2026-05-27T15:42:00+09:00"
  duration_minutes: 102

layers:
  K1:
    included: true
    files: ["k1_file_schema.jsonl"]
    row_count: 1247
  K2:
    included: true
    files: ["k2_parameters.jsonl"]
    row_count: 260
  K3:
    included: true
    files:
      - "k3_entities.jsonl"
      - "k3_relationships.jsonl"
      - "k3_neo4j_nodes.jsonl"
      - "k3_neo4j_edges.jsonl"
  K4:
    included: false               # 아직 미구현 (EMBEDDING_PARAMETER_SEARCH.md 작업 대기)
    files: []
    note: "Embedding cache pending implementation"
  K5:
    included: true
    files: ["k5_procedural_rules.yaml"]
    note: "Extracted from ParameterResolver prompt; awaits PCO structured form"

integrity:
  hash_algo: "sha256"
  file_hashes:
    k1_file_schema.jsonl: "a1b2c3..."
    k2_parameters.jsonl: "d4e5f6..."
    k3_entities.jsonl: "..."
    # ...
  artifact_hash: "deadbeef..."     # 전체 무결성 (모든 파일 정렬 후 해시)

distribution:
  privacy_review:
    raw_data_excluded: true        # raw .vital, .csv 미포함
    phi_excluded: true             # 환자 식별 정보 미포함 (이름·MRN·DOB·날짜 등)
    semantic_only: true            # K2의 semantic_name은 데이터셋-고유 변수명일 뿐 환자 정보 아님
  license: "MIT"
  contact: "your-email@example.com"

compatibility:
  acpo_runtime_min: "0.4.0"        # 호환되는 ExtractionAgent 최소 버전
  postgresql_min: "13"
  neo4j_min: "5.0"
```

### 4.1 Provenance 필드의 중요성

논문 reviewer가 "이 결과를 어떻게 재현하나?"라고 물을 때, **manifest 하나로 답이 됩니다**.

- `llm.snapshot`: 정확한 모델 스냅샷 ID (예: `gpt-4o-2024-08-06`)로 그 시점 모델 호출 재현
- `agent_commit`: IndexingAgent 코드의 정확한 버전
- `integrity.artifact_hash`: skill이 변조되지 않았음 보장

### 4.2 `privacy_review` 섹션의 역할

`raw_data_excluded`, `phi_excluded`, `semantic_only` 세 플래그는 **선언적 약속이자 자동 검증 대상**이다.

- export 시점에 자동 검사: K2 파일을 스캔하여 환자 ID 패턴(`pid_`, `MRN_`, 숫자 ID 등) 존재 여부 검사
- 발견 시 export 실패 → 사용자에게 경고
- manifest에 검사 결과 기록 → reviewer가 안심

---

## 5. Registry & Lifecycle

### 5.1 상태 다이어그램

```
                  ┌───────────────────┐
                  │  raw 데이터 디렉토리  │
                  └─────────┬─────────┘
                            │ IndexingAgent 실행
                            ▼
                  ┌───────────────────┐
                  │ PostgreSQL+Neo4j   │
                  │ (transient state)  │
                  └─────────┬─────────┘
                            │ acpo skill export
                            ▼
                  ┌───────────────────┐
                  │  skills/foo_v1/    │  ← Frozen artifact (배포 가능)
                  └─────────┬─────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
   acpo skill activate              acpo skill deactivate
              │                           │
              ▼                           ▼
  ┌──────────────────────┐     ┌──────────────────────┐
  │ Active state          │     │ Passthrough state    │
  │ - DB/Neo4j 로드됨     │     │ - ACPO 지식 안 씀     │
  │ - ExtractionAgent     │     │ - Baseline 비교 모드  │
  │   K1–K5 사용         │     │                       │
  └──────────────────────┘     └──────────────────────┘
```

### 5.2 5가지 핵심 연산

| 연산 | 의미 | 부작용 |
|---|---|---|
| `export(skill_id)` | 현재 DB 상태를 `skills/<id>/`로 동결 | 디스크 write, DB 변경 없음 |
| `activate(skill_id)` | skill을 DB/Neo4j/캐시에 복원 | DB truncate→insert, Neo4j MERGE, 캐시 로드 |
| `deactivate()` | passthrough 모드로 전환 | 인메모리 플래그만 변경 (DB는 그대로) |
| `list()` | 등록된 skill 목록 | read-only |
| `diff(a, b)` | 두 skill의 K2/K3 차이 비교 | read-only |

### 5.3 `activate`의 trade-off 한 가지

활성화 시 **기존 PostgreSQL 데이터를 어떻게 처리할지** 두 가지 선택지가 있고, 어느 쪽이 좋을지 구현 시 결정해야 합니다.

| 옵션 | 설명 | 장점 | 단점 |
|---|---|---|---|
| **Replace** | 기존 K1–K5 테이블 truncate 후 새 skill 데이터 삽입 | 단순, 깨끗 | 기존 데이터 손실(다시 export 안 했으면) |
| **Side-by-side** | `parameter_vitaldb_v1`처럼 skill_id를 prefix로 별도 테이블 생성 | 손실 없음, 멀티 active 확장 가능 | 모든 쿼리에 active skill 참조 필요, 복잡 |

→ 단순함을 위해 **Replace**를 기본으로 권장. 사용자는 active skill을 바꾸기 전에 현재 상태가 export되어 있는지 확인하면 됨. (deactivate 자동화 시 export-then-deactivate 패턴도 가능)

### 5.4 `deactivate` (Passthrough mode) 의미

**가장 중요한 모드입니다.** ACPO 논문의 ablation을 자동화하는 핵심.

passthrough mode에서:
- `SchemaContextBuilder.build_context()` → 빈 컨텍스트 반환 (K1–K5 미주입)
- `ParameterResolver` → DB 검색 자체를 건너뜀. requested_parameters를 그대로 passthrough
- `QueryUnderstanding`의 system prompt에서 `schema_context` 부분 제거

이러면 ExtractionAgent가 사실상 "no-knowledge baseline"이 되어 [`docs/RESULT.md`](RESULT.md)의 Claude Code CLI 시나리오와 *근접한* 조건이 됩니다. (완전 동일하진 않음 — Claude CLI는 코드 생성까지 직접 함. 정확히 비교하려면 별도 baseline mode 필요.)

---

## 6. API Specifications

### 6.1 CLI

```bash
# Export — 현재 DB 상태를 skill로 동결
$ acpo skill export vitaldb_v1 \
    --display-name "VitalDB Open 1.0.0 — GPT-4o indexing" \
    --description "Initial indexing run with gpt-4o" \
    --license MIT
✓ Privacy check passed (no PHI patterns detected)
✓ Exported K1 (1247 rows), K2 (260 rows), K3 (8 entities, 12 relationships)
✓ Skipped K4 (not yet implemented)
✓ Exported K5 procedural rules
✓ Manifest written to skills/vitaldb_v1/manifest.yaml
✓ Total size: 1.3 MB

# List — 등록된 skill 목록
$ acpo skill list
  ID              CREATED       PARAMS  LLM       SIZE    ACTIVE
  vitaldb_v1      2026-05-27    260     gpt-4o    1.3 MB  ✓
  vitaldb_v2      2026-05-28    260     sonnet-4  1.3 MB
  mimic_v1        2026-06-15    412     gpt-4o    2.1 MB

# Activate — skill 로 DB 복원
$ acpo skill activate vitaldb_v2
⚠ Active skill 'vitaldb_v1' will be replaced. Continue? [y/N] y
✓ Truncated existing ACPO tables
✓ Restored 260 parameters
✓ Restored 8 entities, 12 relationships
✓ Restored Neo4j graph (134 nodes, 412 edges)
✓ Active skill: vitaldb_v2

# Status
$ acpo skill status
  Active skill: vitaldb_v2
  Loaded layers: K1 K2 K3 K5
  Pending: K4 (not in skill)
  Runtime: passthrough disabled

# Deactivate (Passthrough)
$ acpo skill deactivate
⚠ ACPO is now in PASSTHROUGH mode.
  - SchemaContextBuilder will return empty context
  - ParameterResolver will skip DB search
  - This mode is intended for ablation experiments only.

# Diff
$ acpo skill diff vitaldb_v1 vitaldb_v2 --layer K2
  Changed semantic_name (3 parameters):
    Solar8000/PLETH_HR: "Plethysmography HR" → "Plethysmography Heart Rate"
    Primus/PIP_MBAR:    "PIP"               → "Peak Inspiratory Pressure"
    BIS/SEF:            "SEF"               → "Spectral Edge Frequency"
  Identical: 257 parameters
```

### 6.2 Python API (평가 스크립트용)

```python
from shared.skill import ACPOSkillRegistry

registry = ACPOSkillRegistry()

# 시나리오 1: 멀티 데이터셋 ablation
for skill_id in ["vitaldb_v1", "mimic_v1"]:
    registry.activate(skill_id)
    results[skill_id] = run_level1_eval()

# 시나리오 2: Skill ON vs OFF ablation
with registry.context("vitaldb_v1"):
    result_on = orchestrator.run(query)

with registry.passthrough():
    result_off = orchestrator.run(query)

# 시나리오 3: 인덱싱 LLM 비교
for skill_id in ["vitaldb_v1_gpt4o", "vitaldb_v2_sonnet4"]:
    with registry.context(skill_id):
        scores[skill_id] = evaluate(orchestrator)
```

`registry.context()`는 with 블록 종료 시 이전 상태로 복원하는 **컨텍스트 매니저**. 평가 스크립트의 안전성을 위해 권장 패턴.

---

## 7. Loader Architecture

JSON → DB 복원을 담당하는 ~200줄 모듈의 골격.

```
shared/skill/
├── __init__.py
├── manifest.py          # ManifestSchema (Pydantic)
├── exporter.py          # DB → JSONL 추출
├── loader.py            # JSONL → DB 복원
├── registry.py          # 위 5가지 연산
├── passthrough.py       # 비활성화 모드 구현 (SchemaContextBuilder hook)
└── privacy.py           # PHI 패턴 검사
```

### 7.1 `loader.py` 책임 (구현 시 핵심 결정 지점)

| 단계 | 동작 | 충돌 처리 |
|---|---|---|
| 1. Manifest 검증 | schema_version, integrity hash 확인 | 불일치 시 fail-fast |
| 2. ACPO 테이블 truncate | parameter, file_catalog 등 비움 | 기존 데이터 손실 경고 |
| 3. K1 JSONL → INSERT | bulk insert | UUID 충돌 시 새 UUID 발급 (또는 fail) |
| 4. K2 JSONL → INSERT | bulk insert | param_key UNIQUE 위반 시 fail (loader 버그 가능성) |
| 5. K3 JSONL → INSERT | entities → relationships 순서 | FK 순서 중요 |
| 6. Neo4j 그래프 복원 | 노드 MERGE → 엣지 MERGE | 기존 그래프 처리 정책 결정 필요 (replace vs merge) |
| 7. K4 embeddings 로드 | npz → 인메모리 캐시 | 파일 없으면 skip |
| 8. K5 룰 로드 | YAML → ParameterResolver context | 파일 없으면 프롬프트 텍스트 그대로 사용 |
| 9. Active skill 기록 | `~/.acpo/state.json`에 active_skill_id 기록 | 동시 활성화 방지 lock |

### 7.2 PHI 검사 (`privacy.py`)

export 전에 K1–K3 JSONL을 스캔.

```python
PHI_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",        # SSN 형태
    r"\bMRN\b",                       # Medical Record Number
    r"\bDOB\b",                       # Date of Birth
    r"\bSSN\b",
    r"\bpatient_id\b",                # 식별자 컬럼명
    # ... 확장 가능
]

def check_skill_artifact(skill_dir: Path) -> PrivacyReport:
    """K1–K5 파일을 스캔하여 PHI 패턴 검출. 발견 시 export 차단."""
    ...
```

발견 시 export 실패하고 manifest 작성 안 함. 사용자에게 충돌 위치 보고.

---

## 8. Privacy & Distribution

### 8.1 무엇이 들어가고 무엇이 안 들어가는가

| 종류 | 들어가는가? | 이유 |
|---|---|---|
| `.vital` raw 파일 | ❌ | 환자 생체신호. PHI 포함 가능 |
| `clinical_data.csv` raw 행 | ❌ | 환자별 임상 기록. PHI 포함 |
| 컬럼명, 변수명 | ✅ | 데이터셋 스키마. 익명 |
| `Solar8000/HR` 같은 param_key | ✅ | 장비/채널 식별자. 환자 무관 |
| semantic_name ("Heart Rate") | ✅ | LLM이 부여한 의미 라벨 |
| concept_category ("Vital Signs") | ✅ | 카테고리 라벨 |
| 파일 *개수*, 행 *개수* | ✅ | 통계량. 식별 불가 |
| 파일명 (e.g. `clinical_data.csv`) | ✅ | 파일 이름. 환자 식별 아님 |
| 파일 절대 경로 | ⚠ 옵션 | 시스템 정보 노출. manifest의 `data_root`에만 기록, 익명화 가능 |
| 인덱싱 *과정* 의 LLM 응답 로그 | ❌ (기본) | manifest의 모델 식별자로 대체 |

### 8.2 IRB/Privacy 검토 친화적 설계

```yaml
# manifest.yaml 발췌
distribution:
  privacy_review:
    raw_data_excluded: true
    phi_excluded: true
    semantic_only: true
    phi_check_method: "regex + manual review of k2_parameters.jsonl"
    reviewer: "your-irb@institution.edu"
    review_date: "2026-05-27"
```

reviewer는:
1. `manifest.yaml`의 `privacy_review` 섹션 읽음
2. `k2_parameters.jsonl` 직접 열어 첫 몇 줄 확인 (`head -5`)
3. `head -5 k1_file_schema.jsonl`로 컬럼명만 들어있음 확인

→ 10분 안에 검토 완료. binary dump였다면 dump 풀어서 SQL 쿼리 돌리는 30분짜리 작업.

### 8.3 배포 채널 옵션

| 채널 | 적합 시나리오 |
|---|---|
| git repo 내 `skills/` | 작은 reference skill (vitaldb_test 등) |
| Github release / Release artifact | 안정된 버전 (vitaldb_v1, mimic_v1) |
| HuggingFace Datasets / Models hub | 큰 규모 배포 |
| S3 / 자체 mirror | 기관 내부 사용 |

작은 사이즈(MB대) 덕에 어느 채널이든 무리 없음.

---

## 9. Ablation Use Cases

ACPO Skill의 가장 큰 학술적 가치는 ablation 자동화에 있다. 세 가지 실험을 *한 스크립트로* 돌릴 수 있다.

### 9.1 Skill ON vs OFF (핵심 실험)

```python
def run_acpo_ablation():
    queries = load_level1_dataset()

    # ON
    registry.activate("vitaldb_v1")
    on_results = [orchestrator.run(q) for q in queries]

    # OFF (passthrough)
    registry.deactivate()
    off_results = [orchestrator.run(q) for q in queries]

    return {
        "on": compute_f1(on_results, queries),
        "off": compute_f1(off_results, queries),
        "gap": ...,
    }
```

→ [`ACPO_FRAMEWORK §5`](ACPO_FRAMEWORK.md)의 60%p 격차를 **단일 실행에서 동일 모델·동일 코드** 로 재현. D5(동일 LLM ablation)가 더 강해짐.

### 9.2 인덱싱 LLM 비교

```python
for skill_id in ["vitaldb_gpt4o", "vitaldb_sonnet4", "vitaldb_llama3"]:
    registry.activate(skill_id)
    scores[skill_id] = run_level1_eval()
```

→ **"인덱싱 LLM의 능력에 ACPO가 얼마나 의존하는가?"** 라는 질문에 답할 수 있음. 로컬 LLM 가능성 검증([`EVALUATION_METHODOLOGY.md`](EVALUATION_METHODOLOGY.md) 가설 3).

### 9.3 데이터셋 일반화 검증

```python
for skill_id in ["vitaldb_v1", "mimic_v1", "eicu_v1"]:
    registry.activate(skill_id)
    scores[skill_id] = run_corresponding_level1_eval(skill_id)
```

→ [`ACPO_FRAMEWORK §7.4`](ACPO_FRAMEWORK.md)의 일반화 검증이 *데이터셋별 skill 빌드 후 한 스크립트로* 끝남.

---

## 10. Future: Layered Composition

본 설계는 single active skill만 지원한다. 향후 다음 두 확장이 가능하다.

### 10.1 Base + Augmentation Layering

```
Active stack:
  ├── vitaldb_v1                   (Base: K1, K2, K3 from raw data)
  ├── synonym_expansion_v3         (Augmentation: K4 only — embedding cache)
  └── pco_anesthesia_v1            (Augmentation: K5 only — refined procedural rules)
```

K 레이어별 *부분 skill* 을 만들어 base 위에 stack. K4와 K5를 base와 *독립적으로 반복 개선* 할 수 있게 됨.

### 10.2 Layered Ablation (L4)

ACPO 본 framework의 D5를 한 단계 더 강화하는 실험.

```python
for layers_off in ["K5", "K4", "K3", "K2", "K1", []]:
    registry.activate("vitaldb_v1", disable_layers=layers_off)
    scores[str(layers_off)] = run_level1_eval()
```

→ 각 K 레이어의 *순수 기여도* 를 정량 측정. 논문 표 한 개가 완성됨.

### 10.3 왜 지금은 안 하는가

- 구현 복잡도가 single에 비해 2배 이상
- 현재 평가 결과만으로도 60%p 격차가 충분히 강함 — layered는 *enhancement* 일 뿐
- single이 안정적으로 동작한 다음 추가하는 게 합리적

→ 본 설계 v1.0은 single-only. v2.0에서 layering을 다룰 수 있음.

---

## 11. Open Questions (구현 시 결정 필요)

설계가 명확하지만, 구현 시점에 자세히 결정해야 할 사항을 모아둔다.

| Q | 옵션 |
|---|---|
| **Q1** `activate` 시 기존 데이터 처리 | Replace (기본) vs Side-by-side |
| **Q2** Neo4j 그래프 복원 정책 | 전체 replace vs MERGE |
| **Q3** `~/.acpo/state.json` 위치 | 사용자 홈 vs 프로젝트 루트 vs DB 테이블 |
| **Q4** Skill ID 명명 규약 | `<dataset>_<llm>_<date>` vs 자유 |
| **Q5** 동시 활성화 lock 방법 | 파일 lock vs DB advisory lock |
| **Q6** PHI 검사 strict 모드 | 자동 차단 vs 경고만 후 진행 가능 |
| **Q7** Provenance 모델 식별자 | `gpt-4o-2024-08-06` 스냅샷 강제 vs `gpt-4o` 같은 alias 허용 |
| **Q8** Manifest schema 진화 | semantic versioning + 자동 마이그레이션 |

이들은 *문서 차원에서는 결정 보류*, 첫 구현 PR에서 결정한다.

---

## 12. 구현 로드맵 (참고)

본 문서는 *설계 단계* 이므로 실제 구현은 별도 결정한다. 참고를 위한 단계 분해:

| Phase | 작업 | 예상 소요 |
|---|---|---|
| **P1** | `manifest.py`, `exporter.py`, `loader.py` 기본 골격 (K1–K3만) | 1일 |
| **P2** | CLI 5가지 명령 + `~/.acpo/state.json` 추적 | 0.5일 |
| **P3** | PHI 검사 + privacy review section 생성 | 0.5일 |
| **P4** | Passthrough mode (`SchemaContextBuilder` hook) | 0.5일 |
| **P5** | Python API + context manager + 첫 ablation 스크립트 | 0.5일 |
| **P6** | Skill ON vs OFF ablation 실행 → ACPO_FRAMEWORK §5에 결과 추가 | 0.5일 |
| **합계** | | **3.5일** |

K4(embedding) 추가는 [`EMBEDDING_PARAMETER_SEARCH.md`](EMBEDDING_PARAMETER_SEARCH.md) 구현 후. K5 PCO 통합은 [`FUTURE_WORK.md`](FUTURE_WORK.md) Layer 1 구현 후.

---

## 13. 요약: ACPO Skill이 풀어주는 다섯 가지

1. **운영**: 다른 데이터셋으로 *한 줄 전환* (`acpo skill activate mimic_v1`)
2. **재현성**: 1년 뒤에도 manifest 하나로 그 시점 재현 가능
3. **공유**: raw 데이터 없이 *지식만* 다른 곳에 전달 가능 — 의료 AI에 결정적
4. **Ablation**: ACPO ON/OFF, 인덱싱 LLM 비교, 데이터셋 일반화 모두 *한 스크립트* 로
5. **Framework 확장**: [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md)의 §4.1, §5, §7.4, §8 강화

---

## 부록 A. 관련 문서

| 문서 | 관계 |
|---|---|
| [`ACPO_FRAMEWORK.md`](ACPO_FRAMEWORK.md) | 본 skill이 다루는 K1–K5의 정의 |
| [`IndexingAgent_ARCHITECTURE.md`](IndexingAgent_ARCHITECTURE.md) | skill의 *생산자*. exporter는 IndexingAgent 직후 동작 |
| [`ExtractionAgent_ARCHITECTURE.md`](ExtractionAgent_ARCHITECTURE.md) | skill의 *소비자*. activate된 skill의 K1–K5를 주입 |
| [`EMBEDDING_PARAMETER_SEARCH.md`](EMBEDDING_PARAMETER_SEARCH.md) | K4(embeddings)의 구체 형태 |
| [`ONTOLOGY_KNOWLEDGE_EXTENSION.md`](ONTOLOGY_KNOWLEDGE_EXTENSION.md) | K3(Neo4j) 확장안. 본 skill 포맷에 자연스럽게 통합 |
| [`FUTURE_WORK.md`](FUTURE_WORK.md) | K5의 PCO 결정론화 작업. 본 skill의 `k5_procedural_rules.yaml`에 통합 예정 |

---

*문서 작성일: 2026-05-27*  
*상태: 설계 완료, 구현 대기 (Q1–Q8 결정 후)*
