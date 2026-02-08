# Database Migration Scripts

IndexingAgent 실행 결과(PostgreSQL + Neo4j)를 다른 서버로 마이그레이션하기 위한 스크립트입니다.

## 개요

IndexingAgent를 다시 실행하지 않고도 분석 결과를 다른 서버에서 사용할 수 있습니다:

```
[Server A: IndexingAgent 실행됨]     [Server B: Agent만 사용]
         │                                    │
         │  export_db.sh                      │
         ├──────────────────►  .tar.gz  ──────┤
         │                                    │  import_db.sh
         │                                    ▼
    PostgreSQL ───────────────────────► PostgreSQL
       Neo4j  ───────────────────────►    Neo4j
```

## 사전 요구사항

### Export 서버 (원본)
- PostgreSQL 클라이언트 (`pg_dump`, `psql`)
- Python 3.8+ with `neo4j` package (Neo4j export용)

### Import 서버 (대상)
- PostgreSQL 서버 실행 중
- Neo4j 서버 실행 중 (optional)
- PostgreSQL 클라이언트 (`psql`)

## 사용법

### 1. Export (원본 서버에서)

```bash
# IndexingAgent가 실행된 서버에서
cd MedicalAIMaster

# PostgreSQL + Neo4j 서비스가 실행 중인지 확인
./IndexingAgent/run_postgres_neo4j.sh  # 별도 터미널에서

# Export 실행
./scripts/export_db.sh

# 또는 출력 디렉토리 지정
./scripts/export_db.sh ./my_export
```

**출력:**
```
db_export/
└── indexing_agent_export_20240101_120000/
    ├── postgres_schema.sql   # 스키마만 (테이블 구조)
    ├── postgres_dump.sql     # 스키마 + 데이터
    ├── neo4j_dump.cypher     # Neo4j 그래프 데이터
    └── metadata.json         # Export 메타정보

db_export/
└── indexing_agent_export_20240101_120000.tar.gz  # 압축 파일
```

### 2. 파일 전송

```bash
# SCP로 전송
scp db_export/indexing_agent_export_*.tar.gz user@target-server:/path/to/

# 또는 rsync
rsync -avz db_export/ user@target-server:/path/to/db_export/
```

### 3. Import (대상 서버에서)

```bash
# 대상 서버에서
cd MedicalAIMaster

# PostgreSQL + Neo4j 서비스 시작
./IndexingAgent/run_postgres_neo4j.sh  # 별도 터미널에서

# Import 실행 (압축 파일 또는 디렉토리)
./scripts/import_db.sh ./indexing_agent_export_20240101_120000.tar.gz

# 또는 압축 해제된 디렉토리
./scripts/import_db.sh ./indexing_agent_export_20240101_120000/
```

## 환경 변수

스크립트는 다음 환경변수를 사용합니다 (기본값 포함):

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `POSTGRES_HOST` | localhost | PostgreSQL 호스트 |
| `POSTGRES_PORT` | 5432 | PostgreSQL 포트 |
| `POSTGRES_USER` | postgres | PostgreSQL 사용자 |
| `POSTGRES_DB` | medical_data | 데이터베이스 이름 |
| `NEO4J_URI` | bolt://localhost:7687 | Neo4j 연결 URI |
| `NEO4J_USER` | neo4j | Neo4j 사용자 |
| `NEO4J_PASSWORD` | password | Neo4j 비밀번호 |
| `NEO4J_DATABASE` | neo4j | Neo4j 데이터베이스 |

**예시:**
```bash
POSTGRES_PORT=5433 POSTGRES_DB=my_db ./scripts/export_db.sh
```

## Docker 환경에서 사용

### Docker로 PostgreSQL + Neo4j 시작

```bash
# PostgreSQL
docker run -d \
  --name medical-postgres \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres \
  postgres:16

# Neo4j
docker run -d \
  --name medical-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5
```

### Import 실행

```bash
./scripts/import_db.sh ./indexing_agent_export_*.tar.gz
```

## Export되는 테이블 목록

### PostgreSQL (12 tables)

| 테이블 | 설명 |
|--------|------|
| `directory_catalog` | 디렉토리 메타데이터 |
| `file_group` | 파일 그룹 정의 |
| `file_catalog` | 파일 메타데이터 |
| `column_metadata` | 컬럼 메타데이터 |
| `parameter` | 파라미터 정보 |
| `data_dictionary` | 파라미터 정의 사전 |
| `table_entities` | 테이블 Entity 정의 |
| `table_relationships` | 테이블 간 관계 |
| `ontology_subcategories` | 카테고리 세분화 |
| `semantic_edges` | 파라미터 간 관계 |
| `medical_term_mappings` | 의료 용어 매핑 |
| `cross_table_semantics` | 테이블 간 시맨틱 관계 |

### Neo4j (6 node types)

| 노드 타입 | 설명 |
|----------|------|
| `FileGroup` | 파일 그룹 |
| `RowEntity` | 테이블 Entity |
| `ConceptCategory` | 개념 카테고리 |
| `Parameter` | 파라미터 |
| `SubCategory` | 하위 카테고리 |
| `MedicalTerm` | 의료 용어 |

## 문제 해결

### PostgreSQL 연결 오류

```bash
# PostgreSQL이 실행 중인지 확인
pg_isready -h localhost -p 5432

# Docker로 실행 중인 경우
docker ps | grep postgres
```

### Neo4j 연결 오류

```bash
# Neo4j 포트 확인
nc -z localhost 7687 && echo "Neo4j is running" || echo "Neo4j is not running"

# Docker로 실행 중인 경우
docker ps | grep neo4j
```

### cypher-shell 없음

Neo4j export/import는 Python `neo4j` 패키지로 대체됩니다:

```bash
pip install neo4j
```

## Import 후 Agent 사용

Import 완료 후 바로 Agent를 사용할 수 있습니다:

```bash
# AnalysisAgent
cd AnalysisAgent
python -c "from src.agent import AnalysisAgent; print('AnalysisAgent ready')"

# OrchestrationAgent
cd OrchestrationAgent
python test_e2e_hr_mean.py

# ExtractionAgent
cd ExtractionAgent
python test_integration.py
```
