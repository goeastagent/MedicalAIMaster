# Extraction Agent 아키텍처 및 동작 원리

## 📖 개요

Extraction Agent는 **IndexingAgent가 구축한 리소스**(PostgreSQL DB, Neo4j 온톨로지, VectorDB 임베딩)를 활용하여:
1. 사용자의 **자연어 질의**를 분석
2. **VectorDB 시맨틱 검색**으로 관련 컬럼/테이블 추출
3. **SQL 쿼리**로 자동 변환
4. 데이터베이스에서 **결과 추출**
5. CSV, JSON 등 **파일로 저장**

하는 Text-to-SQL 에이전트입니다.

---

## 🔄 전체 데이터 흐름 (Data Flow)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         사용자 입력                                   │
│  "지난 24시간 동안 환자별 바이탈, 랩(젖산/칼륨), 투약 데이터를         │
│   타임라인으로 보여줘"                                                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  1️⃣ INSPECTOR NODE (컨텍스트 수집)                                   │
│  ─────────────────────────────────                                   │
│  • PostgreSQL information_schema 조회 → 테이블/컬럼 정보              │
│  • Neo4j 온톨로지 조회 → 용어 정의, 테이블 관계                        │
│  • VectorDB 시맨틱 검색 → 쿼리 관련 컬럼/테이블 추출                   │
│  • Self-Correction Loop 상태 초기화 (retry_count=0, max_retries=3)   │
│  • LLM이 이해할 수 있는 형태로 포맷팅                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    🔄 SELF-CORRECTION LOOP (최대 3회)                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  2️⃣ PLANNER NODE (SQL 생성)                                  │    │
│  │  ─────────────────────────────                               │    │
│  │  • 스키마 + 온톨로지 + 사용자 질의 → 프롬프트 구성             │    │
│  │  • [재시도 시] 이전 SQL + 에러 메시지를 컨텍스트에 포함        │    │
│  │  • LLM 호출 → SQL 쿼리 생성                                   │    │
│  │                                                              │    │
│  │  🤖 LLM 사용: 자연어 → SQL 변환 (에러 학습)                   │    │
│  └──────────────────────────┬──────────────────────────────────┘    │
│                             │                                       │
│                             ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  3️⃣ EXECUTOR NODE (SQL 실행)                                 │    │
│  │  ────────────────────────────                                │    │
│  │  • PostgreSQL에서 SQL 실행                                   │    │
│  │  • 성공 → Break Loop → PACKAGER                              │    │
│  │  • 실패 → 에러를 sql_history에 기록 → retry_count++          │    │
│  └──────────────────────────┬──────────────────────────────────┘    │
│                             │                                       │
│                             ▼                                       │
│                    ┌────────────────┐                               │
│                    │   Success?     │                               │
│                    └───────┬────────┘                               │
│                            │                                        │
│              ┌─────Yes─────┴─────No─────┐                          │
│              │                          │                          │
│              ▼                          ▼                          │
│         Break Loop              ┌──────────────┐                   │
│              │                  │ retry < 3?   │                   │
│              │                  └──────┬───────┘                   │
│              │                         │                           │
│              │           ┌────Yes──────┴─────No────┐               │
│              │           │                         │               │
│              │           ▼                         ▼               │
│              │      Back to PLANNER           Return Error         │
│              │      (with error context)           │               │
└──────────────┼─────────────────────────────────────┼───────────────┘
               │                                     │
               ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4️⃣ PACKAGER NODE (결과 저장)                                        │
│  ──────────────────────────                                          │
│  • pandas DataFrame으로 변환                                         │
│  • CSV/JSON/Excel/Parquet 형식으로 저장                              │
│  • 파일 경로 반환                                                     │
│  • 시도 횟수 및 Self-Correction 히스토리 로깅                        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            출력                                      │
│  ────────────────────────────────────────────────────────────────   │
│  📄 extraction_20231223_143052.csv (또는 JSON, Excel 등)             │
│  📊 추출된 데이터 (DataFrame 형태)                                    │
│  🔄 Self-Correction 통계: "3회 시도 중 2회차에 성공"                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Self-Correction Loop 상세

### 동작 원리

SQL 실행 실패 시 LLM이 에러 메시지를 분석하여 자동으로 SQL을 수정합니다.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Self-Correction Loop 예시                                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  User Query: "저혈압 환자의 랩 데이터"                               │
│                                                                      │
│  [Attempt 1]                                                         │
│  SQL: SELECT * FROM lab_data WHERE sbp < 90                         │
│  Error: column "sbp" does not exist                                 │
│  → sql_history에 기록, retry_count = 1                              │
│                                                                      │
│  [Attempt 2] ← 에러 컨텍스트 포함                                    │
│  SQL: SELECT l.* FROM lab_data l                                    │
│       JOIN vital_data v ON l.caseid = v.caseid                      │
│       WHERE v.sbp < 90                                              │
│  Error: relation "lab_data" does not exist                          │
│  → sql_history에 기록, retry_count = 2                              │
│                                                                      │
│  [Attempt 3] ← 모든 에러 히스토리 포함                               │
│  SQL: SELECT l.* FROM lab_data_table l                              │
│       JOIN vital_data_table v ON l.caseid = v.caseid                │
│       WHERE v.sbp < 90                                              │
│  Result: ✅ SUCCESS - 125 rows                                      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### State 필드 (Self-Correction 관련)

| 필드 | 타입 | 설명 |
|------|------|------|
| `retry_count` | int | 현재 시도 횟수 (0부터 시작) |
| `max_retries` | int | 최대 재시도 횟수 (기본값: 3) |
| `sql_history` | List[Dict] | 이전 시도 기록: `[{attempt, sql, error}, ...]` |

### 재시도 프롬프트 구성

재시도 시 LLM에게 전달되는 컨텍스트:

```
[PREVIOUS FAILED ATTEMPTS - LEARN FROM THESE ERRORS]
--- Attempt 1 ---
SQL: SELECT * FROM lab_data WHERE sbp < 90
Error: column "sbp" does not exist

--- Attempt 2 ---
SQL: SELECT l.* FROM lab_data l JOIN vital_data v ON ...
Error: relation "lab_data" does not exist

[DB Schema - VERIFY TABLE/COLUMN NAMES HERE]
Table: lab_data_table
  - caseid (bigint)
  - name (text)
  - result (double precision)
  ...

[User Query]
저혈압 환자의 랩 데이터
```

### LangGraph 조건부 라우팅

```python
workflow.add_conditional_edges(
    "executor",
    should_retry,
    {
        "success": "packager",   # 성공 → 결과 저장
        "retry": "planner",      # 실패 → SQL 재생성 (Self-Loop)
        "fail": END              # 최대 재시도 → 종료
    }
)
```

---

## 🧩 주요 컴포넌트 설명

### 1. PostgresConnector (DB 연결)
**역할**: PostgreSQL 데이터베이스 연결 및 쿼리 실행

| 메서드 | 설명 |
|--------|------|
| `get_schema_info()` | information_schema에서 테이블/컬럼 정보 조회 |
| `execute_query(sql)` | SQL 실행 및 결과 반환 |

### 2. Neo4jConnector (온톨로지 연결)
**역할**: Neo4j에서 온톨로지 정보 조회

| 메서드 | 설명 |
|--------|------|
| `get_ontology_context()` | Concept 노드, Relationship 정보 조회 |

### 3. SchemaCollector (스키마 수집기)
**역할**: DB 스키마 정보를 프롬프트에 적합한 형태로 가공

**수집 정보**:
- 테이블 목록 및 행 개수
- 컬럼명, 데이터 타입, NULL 허용 여부
- Primary Key, Foreign Key 관계
- 인덱스 정보

### 4. OntologyContextBuilder (온톨로지 컨텍스트 빌더)
**역할**: 온톨로지 정보를 LLM 프롬프트에 적합한 형태로 가공

**제공 정보**:
- **Definitions (용어 정의)**: `subjectid = "환자 고유 식별자"`
- **Relationships (관계)**: `lab_data.caseid → clinical_data.caseid`
- **Hierarchy (계층)**: `Level 1: 환자 → Level 2: 케이스 → Level 3: 측정값`
- **Column Metadata (컬럼 메타데이터)**: 약어 풀이, 단위, 정상 범위

| 메서드 | 설명 |
|--------|------|
| `get_relevant_definitions(query)` | VectorDB 시맨틱 검색으로 관련 정의 추출 (키워드 매칭 폴백) |
| `format_column_metadata_for_prompt()` | 컬럼 메타데이터 포맷팅 (단위, 범위 등) |

### 5. VectorStoreReader (VectorDB 검색)
**역할**: IndexingAgent가 구축한 pgvector 임베딩을 시맨틱 검색

**특징**:
- **PostgreSQL pgvector 기반**: 별도 VectorDB 없이 PostgreSQL에서 시맨틱 검색
- **Dynamic Schema**: 임베딩 모델(OpenAI/Local)에 따라 자동으로 해당 테이블 참조
- **검색 타입**: column, table, relationship 필터링 지원
- **유사도 필터**: `min_similarity` 파라미터로 노이즈 제거

| 메서드 | 설명 |
|--------|------|
| `initialize(embedding_model)` | pgvector 및 임베딩 클라이언트 초기화 |
| `semantic_search(query)` | 쿼리와 유사한 컬럼/테이블/관계 검색 |
| `search_columns(query)` | 컬럼만 검색 |
| `search_tables(query)` | 테이블만 검색 |
| `format_search_results_for_prompt()` | 검색 결과를 프롬프트용으로 포맷팅 |

```
┌─────────────────────────────────────────────────────────────────────┐
│  VectorStoreReader 동작 방식                                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  사용자 쿼리: "환자의 수축기 혈압"                                    │
│       │                                                              │
│       ▼                                                              │
│  ┌────────────────────┐                                              │
│  │  OpenAI/Local      │                                              │
│  │  Embedding Model   │                                              │
│  └─────────┬──────────┘                                              │
│            │ 쿼리 벡터화                                              │
│            ▼                                                          │
│  ┌────────────────────────────────────────────────────┐              │
│  │  PostgreSQL pgvector                                │              │
│  │  ───────────────────                                │              │
│  │  column_embeddings_openai_1536 테이블에서           │              │
│  │  코사인 유사도 검색                                  │              │
│  └─────────┬──────────────────────────────────────────┘              │
│            │                                                          │
│            ▼                                                          │
│  검색 결과: [                                                         │
│    { column: "sbp", full_name: "Systolic Blood Pressure",            │
│      unit: "mmHg", similarity: 0.92 },                               │
│    { column: "dbp", full_name: "Diastolic Blood Pressure",           │
│      unit: "mmHg", similarity: 0.85 }                                │
│  ]                                                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 6. NLToSQLConverter (자연어→SQL 변환기)
**역할**: LLM을 사용하여 자연어 질의를 SQL로 변환

**프로세스**:
1. 스키마 정보 포맷팅
2. 관련 온톨로지 정의 추출 (키워드 매칭)
3. 테이블 관계 정보 포맷팅
4. 프롬프트 구성 → LLM 호출
5. SQL 검증 (안전성 체크)

---

## 🤖 LLM이 사용되는 곳

### SQL 생성 (Planner Node)

```
┌─────────────────────────────────────────────────────────────────────┐
│  LLM 프롬프트 구성                                                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [DATABASE SCHEMA]                                                   │
│  ──────────────────                                                  │
│  Table: clinical_data_table                                          │
│    Rows: 6,388                                                       │
│    Columns:                                                          │
│      - caseid: bigint NOT NULL                                       │
│      - subjectid: bigint NOT NULL                                    │
│      - age: double precision                                         │
│      ...                                                             │
│                                                                      │
│  [ONTOLOGY DEFINITIONS] ← VectorDB 시맨틱 검색으로 관련 정의만 추출   │
│  ──────────────────────                                              │
│    - subjectid: 환자 고유 식별자 (Deidentified hospital ID)           │
│    - caseid: 케이스 번호 (수술/처치 단위)                             │
│    - chart_time: 기록 시간                                            │
│    ...                                                               │
│                                                                      │
│  [TABLE RELATIONSHIPS]                                               │
│  ─────────────────────                                               │
│    - lab_data_table.caseid → clinical_data_table.caseid              │
│    - diagnosis_table.subject_id → clinical_data_table.subjectid      │
│    ...                                                               │
│                                                                      │
│  [COLUMN METADATA] ← 약어 풀이, 단위, 정상 범위 제공                  │
│  ─────────────────                                                   │
│    📊 Table: vital_data_table                                        │
│       • sbp → Systolic Blood Pressure [mmHg] (normal: 90-140)       │
│       • dbp → Diastolic Blood Pressure [mmHg] (normal: 60-90)       │
│       • hr → Heart Rate [bpm] (normal: 60-100)                      │
│    ...                                                               │
│                                                                      │
│  [USER QUERY]                                                        │
│  ────────────                                                        │
│  "지난 24시간 동안 환자별 바이탈, 랩 데이터를 타임라인으로 보여줘"     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LLM 응답 (JSON)                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  {                                                                   │
│    "reasoning": "환자별로 clinical_data와 lab_data를 caseid로 JOIN   │
│                  하여 24시간 이내 데이터를 추출합니다.",              │
│    "sql": "SELECT c.subjectid, c.caseid, l.name, l.result, l.dt     │
│            FROM clinical_data_table c                                │
│            JOIN lab_data_table l ON c.caseid = l.caseid             │
│            WHERE l.dt > NOW() - INTERVAL '24 hours'                 │
│            ORDER BY c.subjectid, l.dt",                              │
│    "confidence": 0.85,                                               │
│    "tables_used": ["clinical_data_table", "lab_data_table"]         │
│  }                                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔒 안전성 검증

### SQL 검증 규칙

```
1. SELECT 쿼리만 허용
   ✅ SELECT * FROM ...
   ❌ DROP TABLE ...
   ❌ DELETE FROM ...
   ❌ UPDATE ... SET ...
   ❌ INSERT INTO ...

2. 위험 키워드 차단
   ❌ DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE

3. 실행 전 EXPLAIN으로 문법 검증 (선택적)
```

---

## 📊 IndexingAgent와의 관계

```
┌─────────────────────────────────────────────────────────────────────┐
│                         IndexingAgent                                │
│                         (데이터 구축)                                 │
│  ┌──────────────────┐    ┌──────────────────┐                       │
│  │   CSV 파일들      │───▶│   PostgreSQL     │                       │
│  │   (원본 데이터)   │    │   (테이블)       │                       │
│  └──────────────────┘    └────────┬─────────┘                       │
│                                   │                                  │
│  ┌──────────────────┐    ┌───────▼──────────┐    ┌──────────────┐   │
│  │   메타데이터 파일  │───▶│     Neo4j        │───▶│  VectorDB     │   │
│  │   (파라미터 설명)  │    │   (온톨로지)     │    │  (pgvector)  │   │
│  └──────────────────┘    └────────┬─────────┘    └──────┬───────┘   │
└───────────────────────────────────┼─────────────────────┼───────────┘
                                    │                     │
                                    │ 참조                │ 시맨틱 검색
                                    ▼                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        ExtractionAgent                               │
│                        (데이터 추출)                                  │
│                                                                      │
│  ┌──────────────────┐                                               │
│  │   자연어 질의     │                                               │
│  │   (사용자 입력)   │                                               │
│  └────────┬─────────┘                                               │
│           │                                                          │
│           ▼                                                          │
│  ┌────────────────────────────────────────────────────────┐         │
│  │  VectorStoreReader                                      │         │
│  │  ─────────────────                                      │         │
│  │  쿼리 → 임베딩 → pgvector 검색 → 관련 컬럼/테이블 추출   │         │
│  └────────────────────────────────────────────────────────┘         │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────┐    ┌──────────────────┐                       │
│  │   컨텍스트 구성   │───▶│   SQL 생성       │                       │
│  │   (스키마+온톨로지)│    │   (LLM 활용)     │                       │
│  └──────────────────┘    └────────┬─────────┘                       │
│                                   │                                  │
│                          ┌───────▼──────────┐                       │
│                          │   결과 추출       │                       │
│                          │   (CSV 저장)     │                       │
│                          └──────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 의존 관계

| 리소스 | 제공자 | 사용 목적 |
|--------|--------|-----------|
| PostgreSQL 테이블 | IndexingAgent | SQL 실행 대상 |
| 테이블 스키마 | information_schema | 프롬프트 컨텍스트 |
| 용어 정의 | Neo4j (온톨로지) | 의료 용어 → 컬럼 매핑 |
| 테이블 관계 | Neo4j (온톨로지) | JOIN 힌트 제공 |
| 컬럼/테이블 임베딩 | VectorDB (pgvector) | 시맨틱 검색으로 관련 정보 추출 |

---

## ⚙️ 설정 및 실행

### 환경 설정

```bash
# .env 파일

# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=medical_data
POSTGRES_USER=postgres

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password

# LLM
OPENAI_API_KEY=sk-...

# Embedding (VectorDB 시맨틱 검색용)
# "openai" 또는 "local" 중 선택
EMBEDDING_PROVIDER=openai
```

### 임베딩 설정 (`config.py`)

| 설정 | OpenAI | Local |
|------|--------|-------|
| Provider | `openai` | `local` |
| Model | `text-embedding-3-small` | `all-MiniLM-L6-v2` |
| Dimensions | 1536 | 384 |
| 비용 | 유료 (저렴) | 무료 |
| 성능 | 높음 | 중간 |

> ⚠️ **주의**: ExtractionAgent의 임베딩 설정은 IndexingAgent와 **동일해야** 합니다.
> IndexingAgent가 OpenAI로 임베딩을 생성했다면, ExtractionAgent도 OpenAI로 검색해야 합니다.

### 사용 예시

```python
from src.extraction_agent import ExtractionAgent

# 에이전트 초기화
agent = ExtractionAgent()

# 자연어 질의
query = "지난 24시간 동안 환자별 랩 데이터를 보여줘"

# 추출 실행
result = agent.extract(query)

# 결과 확인
print(result["sql"])           # 생성된 SQL
print(result["data"])          # 추출된 데이터 (DataFrame)
print(result["output_path"])   # 저장된 파일 경로
```

### LangGraph 워크플로우 직접 실행

```python
from src.agents.graph import build_extraction_graph

# 그래프 빌드
graph = build_extraction_graph()

# 초기 상태
initial_state = {
    "user_query": "환자 ID 12345의 최근 바이탈 기록",
    "semantic_context": {},
    "sql_plan": {},
    "generated_sql": None,
    "execution_result": None,
    "output_file_path": None,
    "error": None,
    "logs": []
}

# 실행
final_state = graph.invoke(initial_state)
```

---

## 📁 파일 구조

```
ExtractionAgent/
├── ARCHITECTURE.md          # 이 문서
├── README.md                # 간략한 소개
├── DESIGN.md                # 상세 설계 문서
├── requirements.txt         # 의존성
├── src/
│   ├── agents/
│   │   ├── graph.py         # LangGraph 워크플로우 정의
│   │   ├── nodes.py         # 각 노드 구현
│   │   └── state.py         # 상태 객체 정의
│   ├── processors/
│   │   ├── nl_to_sql.py     # 자연어 → SQL 변환기
│   │   ├── query_executor.py # SQL 실행기
│   │   └── schema_collector.py # 스키마 수집기
│   ├── knowledge/
│   │   ├── ontology_context.py # 온톨로지 컨텍스트 빌더
│   │   └── vector_store.py     # VectorDB 시맨틱 검색 (pgvector)
│   ├── database/
│   │   ├── postgres.py      # PostgreSQL 연결
│   │   └── neo4j.py         # Neo4j 연결
│   ├── utils/
│   │   ├── llm_client.py    # LLM API 클라이언트
│   │   └── result_exporter.py # 결과 저장
│   ├── config.py            # 설정 (EmbeddingConfig 포함)
│   ├── extraction_agent.py  # 메인 에이전트 클래스
│   └── main.py              # CLI 진입점
├── test_simple.py           # 간단한 테스트
└── test_intermediate.py     # 중급 테스트
```

---

## 🎯 설계 원칙

1. **동적 스키마 대응**: 테이블이 언제든 추가/변경될 수 있으므로 information_schema를 실시간 조회
2. **온톨로지 활용**: 의료 용어와 DB 컬럼 간 매핑을 온톨로지에서 제공
3. **토큰 최적화**: 전체 스키마 대신 관련 정보만 프롬프트에 포함 (VectorDB 시맨틱 검색 활용)
4. **안전성**: SELECT 쿼리만 허용, 위험 키워드 차단
5. **확장성**: 새로운 출력 형식(Parquet 등) 쉽게 추가 가능
6. **임베딩 일관성**: IndexingAgent와 동일한 임베딩 모델 사용 (Dynamic Schema)

---

## 🔮 향후 개선 사항

1. ~~**벡터 검색 기반 정의 추출**: 키워드 매칭 → 의미 유사도 검색~~ ✅ **구현 완료** (VectorStoreReader)
2. **대화형 쿼리**: 사용자 피드백으로 SQL 수정 (Human-in-the-Loop)
3. **쿼리 캐싱**: 동일 질의 재사용
4. ~~**에러 자동 복구**: SQL 실행 실패 시 LLM이 자동 수정~~ ✅ **구현 완료** (Self-Correction Loop)
5. **성능 최적화**: EXPLAIN ANALYZE로 쿼리 성능 힌트 제공
6. **하이브리드 검색**: 키워드 검색 + 벡터 검색 결합으로 정확도 향상
7. **SQL 예제 기반 Few-Shot**: 유사 질의-SQL 예제를 VectorDB에서 검색하여 프롬프트에 포함

