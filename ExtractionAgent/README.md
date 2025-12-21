# ExtractionAgent

IndexingAgent를 통해 구축된 리소스(PostgreSQL DB, 온톨로지)를 기반으로 사용자의 자연어 질의를 SQL로 변환하고 데이터를 추출하는 에이전트입니다.

## 주요 기능

1. **동적 스키마 정보 수집**: PostgreSQL의 `information_schema`를 통해 현재 DB의 모든 테이블과 컬럼 정보를 실시간으로 조회
2. **온톨로지 기반 컨텍스트 제공**: IndexingAgent가 구축한 온톨로지 정보를 활용하여 의미론적 매핑 지원
3. **자연어 → SQL 변환**: LLM을 사용하여 사용자 질의를 정확한 SQL 쿼리로 변환
4. **결과 추출**: 생성된 SQL을 실행하고 결과를 CSV, JSON, Excel 등 다양한 형식으로 저장

## 아키텍처

```
┌─────────────────┐
│  User Query     │ (자연어)
│  "지난 24시간   │
│   환자 바이탈"   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   Schema Collector                  │
│   - information_schema 조회          │
│   - 테이블/컬럼 정보 수집            │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   Ontology Loader                    │
│   - ontology_db.json 로드            │
│   - definitions, relationships       │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   Context Builder                    │
│   - 스키마 정보 포맷팅               │
│   - 온톨로지 정보 통합               │
│   - 프롬프트 구성                    │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   NL → SQL Converter (LLM)           │
│   - 자연어 질의 분석                 │
│   - SQL 생성                         │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   Query Executor                    │
│   - SQL 실행                         │
│   - 결과 검증                        │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│   Result Exporter                   │
│   - CSV/JSON/Excel 저장              │
└─────────────────────────────────────┘
```

## 핵심 컴포넌트

### 1. SchemaCollector
- PostgreSQL의 `information_schema`를 조회하여 동적 스키마 정보 수집
- 테이블 목록, 컬럼 정보, 데이터 타입, FK 관계 등 추출
- 프롬프트에 포함할 수 있는 형태로 포맷팅

### 2. OntologyContextBuilder
- `OntologyManager`를 통해 온톨로지 로드
- `definitions`: 용어 정의 (예: "subjectid" = "환자 ID")
- `relationships`: 테이블 간 관계 (FK 정보)
- `hierarchy`: 계층 구조 (Level 1-2 Anchor 정보)
- 프롬프트에 포함할 수 있는 형태로 요약/포맷팅

### 3. NLToSQLConverter
- LLM을 사용하여 자연어를 SQL로 변환
- 스키마 정보와 온톨로지 정보를 컨텍스트로 제공
- 생성된 SQL의 유효성 검증

### 4. QueryExecutor
- 생성된 SQL 실행
- 결과 검증 및 에러 처리
- 대용량 결과 처리 (Chunking)

### 5. ResultExporter
- 쿼리 결과를 파일로 저장
- 지원 형식: CSV, JSON, Excel, Parquet 등

## 사용 예시

```python
from src.extraction_agent import ExtractionAgent

agent = ExtractionAgent()

# 자연어 질의
query = "지난 24시간 동안 동일 환자(subject_id)에 대해 병동 바이탈, 일반 바이탈, 최근 랩(젖산/칼륨), 투약(바소프레서), 진단 코드까지 한 번에 묶어서 타임라인으로 보여줘."

# SQL 생성 및 실행
result = agent.extract(query)

# 결과 저장
result.save_csv("output/timeline_24h.csv")
```

## 디렉토리 구조

```
ExtractionAgent/
├── README.md
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── extraction_agent.py      # 메인 에이전트 클래스
│   ├── schema_collector.py      # 스키마 정보 수집
│   ├── ontology_context.py       # 온톨로지 컨텍스트 빌더
│   ├── nl_to_sql.py             # 자연어 → SQL 변환
│   ├── query_executor.py        # SQL 실행
│   └── result_exporter.py       # 결과 추출
└── tests/
    └── test_extraction_agent.py
```

## 의존성

- IndexingAgent의 리소스:
  - PostgreSQL DB (동적 테이블)
  - `data/processed/ontology_db.json` (온톨로지)
- 공통 유틸리티:
  - `src/utils/llm_client.py` (LLM 클라이언트)
  - `src/database/connection.py` (DB 연결)
  - `src/utils/ontology_manager.py` (온톨로지 로더)

