# ExtractionAgent 설계 문서

## 개요

ExtractionAgent는 IndexingAgent를 통해 구축된 리소스(PostgreSQL DB, 온톨로지)를 기반으로 사용자의 자연어 질의를 SQL로 변환하고 데이터를 추출하는 에이전트입니다.

## 핵심 설계 원칙

### 1. 동적 스키마 정보 활용
- **문제**: IndexingAgent에서 DB가 동적으로 생성되므로 테이블 구조가 사전에 알려지지 않음
- **해결**: PostgreSQL의 `information_schema`를 실시간으로 조회하여 현재 DB의 모든 테이블과 컬럼 정보를 수집
- **구현**: `SchemaCollector` 클래스가 `information_schema.tables`, `information_schema.columns` 등을 조회

### 2. 온톨로지 정보 통합
- **문제**: 자연어 질의의 의료 용어를 DB 컬럼명으로 매핑해야 함
- **해결**: IndexingAgent가 구축한 온톨로지(`ontology_db.json`)를 로드하여 의미론적 매핑 제공
- **구현**: `OntologyContextBuilder` 클래스가 온톨로지 정보를 프롬프트에 포함할 수 있는 형태로 포맷팅

### 3. 프롬프트 최적화
- **문제**: 전체 스키마와 온톨로지를 모두 포함하면 토큰이 너무 많아짐
- **해결**: 
  - 스키마: 행 개수가 많은 테이블 우선 선택 (최대 N개)
  - 온톨로지: 쿼리와 관련된 정의만 추출 (키워드 매칭)
  - 관계: FK 정보만 간단히 포함
- **구현**: `format_schema_for_prompt()`, `get_relevant_definitions()` 등

## 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    ExtractionAgent                          │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Schema       │    │ Ontology     │    │ NL → SQL     │  │
│  │ Collector    │───▶│ Context      │───▶│ Converter    │  │
│  │              │    │ Builder      │    │              │  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘  │
│                                                   │          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────▼───────┐  │
│  │ Query        │◀───│ SQL          │    │ Query        │  │
│  │ Executor     │    │ Validator    │    │ Executor     │  │
│  └──────┬───────┘    └──────────────┘    └──────┬───────┘  │
│         │                                        │          │
│         └──────────────┬─────────────────────────┘          │
│                        ▼                                      │
│              ┌──────────────┐                                │
│              │ Result       │                                │
│              │ Exporter     │                                │
│              └──────────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

## 컴포넌트 상세

### 1. SchemaCollector
**역할**: PostgreSQL의 `information_schema`를 조회하여 동적 스키마 정보 수집

**주요 메서드**:
- `get_all_tables()`: 모든 테이블 목록 조회
- `get_table_columns(table_name)`: 특정 테이블의 컬럼 정보
- `get_foreign_keys(table_name)`: FK 관계 정보
- `get_primary_keys(table_name)`: PK 정보
- `format_schema_for_prompt(max_tables)`: 프롬프트용 포맷팅

**캐싱**: `_schema_cache`로 스키마 정보 캐싱 (성능 최적화)

### 2. OntologyContextBuilder
**역할**: 온톨로지 정보를 로드하고 프롬프트에 포함할 수 있는 형태로 포맷팅

**주요 메서드**:
- `load_ontology()`: 온톨로지 로드
- `format_definitions_for_prompt(max_definitions)`: 용어 정의 포맷팅
- `format_relationships_for_prompt()`: 테이블 관계 포맷팅
- `format_hierarchy_for_prompt()`: 계층 구조 포맷팅
- `get_relevant_definitions(query, top_k)`: 쿼리와 관련된 정의만 추출

**최적화**: 
- 전체 정의를 모두 포함하지 않고 관련 정의만 추출
- 키워드 매칭으로 관련성 판단 (향후 벡터 검색으로 개선 가능)

### 3. NLToSQLConverter
**역할**: 자연어 질의를 SQL로 변환

**주요 메서드**:
- `convert(natural_language_query, max_tables)`: 자연어 → SQL 변환
- `validate_sql(sql)`: SQL 문법 검증

**프롬프트 구성**:
1. 데이터베이스 스키마 정보
2. 관련 온톨로지 정의
3. 테이블 관계 정보
4. 사용자 질의
5. 지시사항 (JOIN 방법, 시간 기반 쿼리 등)

**안전성**: 
- SELECT 쿼리만 허용 (DROP, DELETE, UPDATE 등 차단)
- SQL 문법 검증

### 4. QueryExecutor
**역할**: 생성된 SQL을 실행하고 결과 반환

**주요 메서드**:
- `execute(sql, limit)`: SQL 실행 (pandas로 결과 반환)
- `execute_with_chunking(sql, chunk_size)`: 대용량 결과 청크 처리
- `test_query(sql)`: SQL 문법 검증 (EXPLAIN 사용)

**대용량 처리**: 
- 기본적으로 `limit` 파라미터로 결과 제한
- `execute_with_chunking()`으로 청크 단위 처리 지원

### 5. ResultExporter
**역할**: 쿼리 결과를 다양한 형식으로 저장

**지원 형식**:
- CSV: `save_csv()`
- JSON: `save_json()`
- Excel: `save_excel()`
- Parquet: `save_parquet()` (대용량 데이터에 적합)

## 데이터 흐름

```
1. 사용자 질의 입력
   ↓
2. SchemaCollector: information_schema 조회
   ↓
3. OntologyContextBuilder: 온톨로지 로드 및 관련 정의 추출
   ↓
4. NLToSQLConverter: 프롬프트 구성 및 LLM 호출
   ↓
5. SQL 검증 (문법, 안전성)
   ↓
6. QueryExecutor: SQL 실행
   ↓
7. ResultExporter: 결과 저장
   ↓
8. 사용자에게 결과 반환
```

## 프롬프트 구성 예시

```
[DATABASE SCHEMA]
================================================================================
DATABASE SCHEMA
================================================================================

Total Tables: 8

Table: vitals_table
  Rows: 125,000
  Primary Keys: subject_id, chart_time
  Foreign Keys:
    - subject_id → patients_table.subject_id
  Columns:
    - subject_id: integer NOT NULL [PK]
    - chart_time: timestamp NOT NULL [PK]
    - item_name: varchar NULL
    - value: double precision NULL
    ...

[ONTOLOGY DEFINITIONS]
================================================================================
RELEVANT ONTOLOGY DEFINITIONS
================================================================================

  - subjectid: EMR | Description=Subject ID; Deidentified hospital ID of patient
  - chart_time: Case file | Description=Recording Start Time
  - lactate: Lab | Description=Lactate level | Unit=mmol/L
  ...

[TABLE RELATIONSHIPS]
================================================================================
TABLE RELATIONSHIPS (Foreign Keys)
================================================================================

  - vitals_table.subject_id → patients_table.subject_id (N:1, confidence: 95%)
  - labs_table.subject_id → patients_table.subject_id (N:1, confidence: 95%)
  ...

[USER QUERY]
지난 24시간 동안 동일 환자(subject_id)에 대해 병동 바이탈, 일반 바이탈, 최근 랩(젖산/칼륨), 투약(바소프레서), 진단 코드까지 한 번에 묶어서 타임라인으로 보여줘.

[INSTRUCTIONS]
1. Analyze the user's natural language query carefully.
2. Use the database schema to identify relevant tables and columns.
3. Use ontology definitions to map medical terms to column names.
4. Use table relationships to create proper JOINs.
5. Generate a valid PostgreSQL SQL query.
...
```

## 주요 고려사항

### 1. 토큰 최적화
- **문제**: 전체 스키마와 온톨로지를 포함하면 토큰이 너무 많음
- **해결**:
  - 스키마: 행 개수가 많은 테이블 우선 선택
  - 온톨로지: 쿼리와 관련된 정의만 추출
  - 관계: FK 정보만 간단히 포함

### 2. 동적 스키마 대응
- **문제**: IndexingAgent에서 테이블이 동적으로 생성됨
- **해결**: `information_schema`를 실시간으로 조회하여 현재 상태 반영

### 3. SQL 안전성
- **문제**: 악의적인 쿼리 실행 방지
- **해결**: SELECT 쿼리만 허용, 위험한 키워드 차단

### 4. 대용량 결과 처리
- **문제**: 수만~수십만 행 결과 처리
- **해결**: `limit` 파라미터, 청크 처리 지원

## 향후 개선 사항

1. **벡터 검색 기반 정의 추출**: 현재는 키워드 매칭으로 관련 정의를 찾지만, 벡터 검색으로 개선 가능
2. **SQL 최적화**: 생성된 SQL의 성능 최적화 (인덱스 활용 등)
3. **대화형 쿼리**: 사용자 피드백을 받아 SQL을 수정하는 기능
4. **쿼리 캐싱**: 동일한 질의에 대한 결과 캐싱
5. **에러 복구**: SQL 실행 실패 시 자동으로 수정 시도

## 의존성

- **IndexingAgent 리소스**:
  - PostgreSQL DB (동적 테이블)
  - `data/processed/ontology_db.json` (온톨로지)
- **공통 유틸리티**:
  - `src/utils/llm_client.py` (LLM 클라이언트)
  - `src/database/connection.py` (DB 연결)
  - `src/utils/ontology_manager.py` (온톨로지 로더)

