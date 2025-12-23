# Indexing Agent 아키텍처 및 동작 원리

## 📖 개요

Indexing Agent는 의료 데이터 파일(CSV, Signal 등)을 분석하여:
1. **PostgreSQL 데이터베이스**에 정형화된 테이블로 저장
2. **Neo4j 그래프 데이터베이스**에 온톨로지(지식 그래프)를 구축

하는 자동화 에이전트입니다.

핵심 철학: **"Rule Prepares, LLM Decides"**
- 규칙 기반 로직이 데이터를 전처리하고 후보를 추출
- LLM이 최종 판단 (의미 해석, 관계 추론)
- 불확실할 때는 사람에게 질문 (Human-in-the-Loop)

---

## 🔄 전체 데이터 흐름 (Data Flow)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         입력: CSV/Signal 파일                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  1️⃣ LOADER NODE                                                      │
│  ─────────────────                                                   │
│  • 파일 형식 감지 (CSV? Signal?)                                      │
│  • Processor 선택                                                    │
│  • 기초 메타데이터 추출 (컬럼명, 샘플 데이터, Anchor 후보)              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2️⃣ ONTOLOGY BUILDER NODE                                            │
│  ─────────────────────────                                           │
│  • 파일 분류: "메타데이터" vs "일반 데이터"                            │
│  • 메타데이터면 → 용어 사전 파싱 후 온톨로지에 추가                     │
│  • 일반 데이터면 → 다음 단계로 진행                                    │
│                                                                      │
│  🤖 LLM 사용: 파일 유형 판단 (confidence 점수 반환)                    │
│  👤 Human Review: confidence < 90% 이면 사람에게 질문                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            [메타데이터 파일]                  [일반 데이터 파일]
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────────────┐
        │ 용어 파싱 후       │           │ 3️⃣ ANALYZER NODE           │
        │ Neo4j에 저장       │           │ ───────────────            │
        │ (인덱싱 스킵)      │           │ • Anchor 컬럼 확정         │
        └───────────────────┘           │ • 스키마 분석              │
                                        │ • 테이블 간 관계 추론       │
                                        │                           │
                                        │ 🤖 LLM 사용:               │
                                        │   - Anchor 매칭           │
                                        │   - 컬럼 의미 해석         │
                                        │   - FK 관계 추론           │
                                        │                           │
                                        │ 👤 Human Review:           │
                                        │   - Anchor 불일치 시       │
                                        │   - 불확실할 때            │
                                        └───────────────────────────┘
                                                    │
                                                    ▼
                                        ┌───────────────────────────┐
                                        │ 4️⃣ INDEXER NODE            │
                                        │ ─────────────              │
                                        │ • PostgreSQL 테이블 생성   │
                                        │ • 데이터 적재              │
                                        │ • FK/인덱스 생성           │
                                        │ • 온톨로지 관계 저장        │
                                        └───────────────────────────┘
                                                    │
                                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            출력                                      │
│  ────────────────────────────────────────────────────────────────   │
│  📊 PostgreSQL: 정형화된 테이블 + FK 관계 + 인덱스                    │
│  🧠 Neo4j: 온톨로지 (Concepts, Relationships, Hierarchy)             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🧩 주요 컴포넌트 설명

### 1. Processor (전처리기)
**역할**: 파일 형식별로 기초 메타데이터 추출 및 LLM에게 Anchor 판단 요청

| Processor | 대상 파일 | 추출 정보 |
|-----------|-----------|-----------|
| TabularProcessor | CSV, Excel | 컬럼명, 데이터 타입, 샘플 값, categorical/continuous 판단 |
| SignalProcessor | .vital, .edf | 채널 정보, 샘플링 레이트, 시간 범위 |

**Anchor 탐지 방식 (LLM 기반)**:
1. **전처리 (Rule-based)**: 컬럼 정보 추출 (dtype, unique values, samples)
2. **LLM 호출**: 추출된 정보를 텍스트로 요약하여 LLM에게 전달
3. **LLM 판단**: "어떤 컬럼이 Patient/Subject ID인가?" 판단
4. **confidence < 85%**: Human Review 요청

> ⚠️ 참고: `base.py`에 명시된 대로 "Rule-based 로직(정규식 등)은 제거되었습니다."
> Anchor 탐지는 순수하게 LLM이 수행합니다.

### 2. Ontology Manager (온톨로지 관리자)
**역할**: Neo4j와의 상호작용 담당

**저장하는 정보**:
- **Definitions (용어 정의)**: 컬럼명 → 설명 매핑
- **Relationships (관계)**: 테이블 간 FK 관계
- **Hierarchy (계층)**: 데이터 레벨 (환자 → 케이스 → 측정값)
- **File Tags (파일 태그)**: 파일별 메타데이터/데이터 분류

### 3. LLM Client (LLM 클라이언트)
**역할**: OpenAI/Anthropic API 호출

**캐싱 전략**:
- 동일한 질문은 캐시에서 반환 (비용 절감)
- 캐시 키: 프롬프트 해시값
- 저장 위치: `data/cache/llm/`

---

## 🤖 LLM이 사용되는 곳

### 1. 파일 유형 분류 (Ontology Builder)
```
입력: 파일명, 컬럼 목록, 샘플 데이터
질문: "이 파일이 메타데이터(코드북/사전)인가요, 실제 데이터인가요?"
출력: { is_metadata: true/false, confidence: 0.95, reasoning: "..." }
```

**판단 기준 (LLM에게 제공)**:
- 파일명에 "parameter", "code", "dictionary" 등이 있으면 메타데이터 가능성 높음
- 컬럼이 "name", "description", "unit" 등이면 메타데이터
- 값이 설명문이면 메타데이터, 숫자/측정값이면 데이터

### 2. Anchor 컬럼 매칭 (Analyzer)
```
입력: 프로젝트의 Master Anchor (예: subjectid), 현재 파일의 컬럼 목록
질문: "이 파일에서 Master Anchor와 같은 역할을 하는 컬럼이 무엇인가요?"
출력: { status: "MATCH"/"CONFLICT"/"MISSING", target_column: "...", reasoning: "..." }
```

**매칭 유형**:
- **MATCH**: 정확히 같은 컬럼 또는 동의어 (pid ≈ patient_id)
- **INDIRECT_LINK**: 다른 테이블을 경유하여 연결 가능 (caseid → clinical_data.subjectid)
- **CONFLICT**: 매칭 불가
- **MISSING**: 해당 컬럼 없음

### 3. 컬럼 의미 분석 (Analyzer)
```
입력: 컬럼명, 샘플 값, Anchor 정보
질문: "이 컬럼들의 의료적 의미와 역할을 분석해주세요"
출력: [{ column: "...", semantic_type: "...", role: "identifier/feature/timestamp" }, ...]
```

### 4. 테이블 관계 추론 (Indexer)
```
입력: 현재 테이블, 기존 테이블들, 공통 컬럼
질문: "이 테이블들 간의 FK 관계를 추론해주세요"
출력: { relationships: [...], hierarchy: [...] }
```

### 5. Human Review 질문 생성
```
입력: 이슈 상황, 컨텍스트
질문: "사용자에게 물어볼 자연스러운 질문을 한국어로 작성해주세요"
출력: 자연어 질문 문자열
```

---

## 👤 Human Review 메커니즘

### 언제 사람에게 물어보나요?

| 상황 | 조건 | 질문 예시 |
|------|------|-----------|
| 파일 분류 불확실 | confidence < 90% | "이 파일이 메타데이터인가요, 데이터인가요?" |
| Anchor 불확실 | Processor가 확신 못 함 | "어떤 컬럼이 환자 ID인가요?" |
| Anchor 충돌 | 기존 Master와 매칭 안 됨 | "subjectid와 동일한 컬럼이 무엇인가요?" |

### 판단 방식: Rule + LLM Hybrid

```
         ┌─────────────────┐
         │ Rule-based 체크  │
         │ (Threshold 비교) │
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────┐
         │ LLM 추가 판단    │ ← USE_LLM_FOR_REVIEW_DECISION=true 일 때만
         │ (상황 종합 분석) │
         └────────┬────────┘
                  │
                  ▼
    ┌─────────────┴─────────────┐
    │ 둘 중 하나라도 "필요" →    │
    │ Human Review 요청          │
    └───────────────────────────┘
```

### 설정 가능한 파라미터 (`config.py`)

| 설정 | 기본값 | 설명 |
|------|--------|------|
| METADATA_CONFIDENCE_THRESHOLD | 0.90 | 이 값 미만이면 Human Review |
| ANCHOR_CONFIDENCE_THRESHOLD | 0.90 | Anchor 판단 기준 |
| USE_LLM_FOR_REVIEW_DECISION | true | LLM 추가 판단 활성화 |
| MAX_RETRY_COUNT | 3 | 최대 재시도 횟수 |

---

## 💾 DB 구축 과정 (PostgreSQL)

### 1단계: 테이블 생성
- 파일명에서 테이블명 생성 (예: `clinical_data.csv` → `clinical_data_table`)
- pandas가 데이터 타입을 자동 추론하여 컬럼 생성

### 2단계: 데이터 적재
- 작은 파일: 한 번에 INSERT
- 대용량 파일 (>50MB): Chunk 단위로 분할 처리 (100,000행씩)

### 3단계: FK 제약조건 생성
```
온톨로지의 relationships 정보를 기반으로:

clinical_data_table.subjectid  ←──┐
                                   │ FK
lab_data_table.caseid ────────────►clinical_data_table.caseid
```

### 4단계: 인덱스 생성
- Anchor 컬럼에 인덱스 자동 생성
- 자주 조회되는 컬럼 (timestamp 등)에 인덱스 추가

---

## 🧠 온톨로지 구축 과정 (Neo4j)

### 저장되는 노드 유형

```
(:Concept {name: "subjectid", definition: "환자 고유 식별자"})
(:Concept {name: "heart_rate", definition: "심박수 (bpm)"})
(:Concept {name: "clinical_data_table", level: 1, anchor_column: "subjectid"})
```

### 저장되는 관계 유형

```
(clinical_data)-[:HAS_MANY]->(lab_data)
(lab_data)-[:BELONGS_TO]->(clinical_data)
(subjectid)-[:IDENTIFIES]->(clinical_data)
```

### 계층 구조 (Hierarchy)

```
Level 1: 환자 (subject)
    └── Level 2: 케이스/방문 (case/visit)
            └── Level 3: 측정값 (measurement)
```

### 온톨로지 활용 사례

1. **스키마 자동 이해**: 새 파일이 들어오면 기존 온톨로지를 참조하여 컬럼 의미 파악
2. **FK 추론**: 공통 컬럼 기반으로 테이블 간 관계 자동 설정
3. **질의 최적화**: 어떤 테이블을 JOIN해야 하는지 자동 결정

---

## 🔧 실행 방법

### 1. 서비스 시작
```bash
cd IndexingAgent
./run_postgres_neo4j.sh   # PostgreSQL + Neo4j 실행
```

### 2. 인덱싱 실행
```bash
python test_agent_with_interrupt.py
```

### 3. 결과 확인
```bash
python view_database.py    # PostgreSQL 테이블 확인
python view_ontology.py    # Neo4j 온톨로지 확인
```

---

## 📊 전체 시스템 구조

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              Indexing Agent                                 │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │   Loader     │───►│  Ontology    │───►│   Analyzer   │                  │
│  │    Node      │    │   Builder    │    │     Node     │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│         │                   │                   │                          │
│         │                   │                   │                          │
│         ▼                   ▼                   ▼                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  Processors  │    │   LLM        │    │   Indexer    │                  │
│  │  (Tabular/   │    │   Client     │    │     Node     │                  │
│  │   Signal)    │    │   (Cached)   │    │              │                  │
│  └──────────────┘    └──────────────┘    └──────────────┘                  │
│                             │                   │                          │
│                             │                   │                          │
│                             ▼                   ▼                          │
│                      ┌──────────────┐    ┌──────────────┐                  │
│                      │  Human       │    │   Ontology   │                  │
│                      │  Review      │    │   Manager    │                  │
│                      │  (Optional)  │    │              │                  │
│                      └──────────────┘    └──────────────┘                  │
│                                                │                           │
└────────────────────────────────────────────────┼───────────────────────────┘
                                                 │
                         ┌───────────────────────┼───────────────────────┐
                         │                       │                       │
                         ▼                       ▼                       ▼
                  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
                  │  PostgreSQL  │       │    Neo4j     │       │  Vector DB   │
                  │  (Tables,    │       │  (Ontology,  │       │  (Semantic   │
                  │   FK, Index) │       │   Concepts)  │       │   Search)    │
                  └──────────────┘       └──────────────┘       └──────────────┘
```

---

## 🎯 설계 원칙

1. **점진적 학습**: 파일을 처리할수록 온톨로지가 풍부해져서 다음 파일 분석이 더 정확해짐
2. **Human-in-the-Loop**: 불확실할 때는 무작정 진행하지 않고 사람에게 확인
3. **캐싱 최적화**: 동일한 LLM 질문은 재사용하여 비용 절감
4. **유연한 설정**: Threshold, LLM 사용 여부 등을 설정으로 조정 가능
5. **데이터 무결성**: FK 제약조건으로 테이블 간 관계 보장

---

## 📁 파일 구조

```
IndexingAgent/
├── src/
│   ├── agents/
│   │   ├── graph.py          # LangGraph 워크플로우 정의
│   │   ├── nodes.py          # 각 노드 구현 (Loader, Analyzer, Indexer)
│   │   └── state.py          # 상태 객체 정의
│   ├── processors/
│   │   ├── tabular.py        # CSV 처리기
│   │   └── signal.py         # Signal 파일 처리기
│   ├── database/
│   │   ├── connection.py     # PostgreSQL 연결
│   │   └── neo4j_connection.py # Neo4j 연결
│   ├── utils/
│   │   ├── llm_client.py     # LLM API 클라이언트
│   │   ├── llm_cache.py      # LLM 응답 캐시
│   │   └── ontology_manager.py # 온톨로지 CRUD
│   └── config.py             # 설정 (Threshold 등)
├── data/
│   ├── raw/                  # 원본 데이터 파일
│   ├── processed/            # 처리된 데이터
│   └── cache/llm/            # LLM 응답 캐시
├── test_agent_with_interrupt.py  # 메인 실행 스크립트
├── view_database.py          # DB 확인 도구
└── view_ontology.py          # 온톨로지 확인 도구
```

