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

## 🔄 전체 워크플로우 아키텍처

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                   입력: 의료 데이터 디렉토리                             ┃
┃                          (CSV, .vital, Signal Files, Metadata Files)                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                              │
                                              ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 1: 메타데이터 수집 (Rule-based)                          ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                         ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [100] directory_catalog 📏   │────▶│ PostgreSQL: directory_catalog              │  ┃
┃   │  • 디렉토리 구조 스캔         │     │  • dir_path, file_count, file_extensions   │  ┃
┃   │  • 파일 확장자별 통계         │     │  • filename_samples (LLM 분석용)           │  ┃
┃   │  • 파일명 샘플 수집           │     └────────────────────────────────────────────┘  ┃
┃   └───────────────────────────────┘                                                     ┃
┃                   │                                                                     ┃
┃                   ▼                                                                     ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [200] file_catalog 📏        │────▶│ PostgreSQL: file_catalog                   │  ┃
┃   │  • 파일별 메타데이터 추출     │     │  • file_path, file_size, processor_type    │  ┃
┃   │  • 컬럼 정보 (타입, 통계)     │     │  • raw_stats (row_count, column_count)     │  ┃
┃   │  • row count, null count     │     │                                            │  ┃
┃   └───────────────────────────────┘     │ PostgreSQL: column_metadata                │  ┃
┃                   │                     │  • original_name, column_type, data_type   │  ┃
┃                   │                     │  • value_distribution                      │  ┃
┃                   ▼                     └────────────────────────────────────────────┘  ┃
┃   ┌───────────────────────────────┐                                                     ┃
┃   │ [300] schema_aggregation 📏  │────▶ State Only (LLM 배치 준비)                      ┃
┃   │  • 유니크 컬럼명 집계         │      • unique_columns, unique_files                 ┃
┃   │  • 대표 통계 계산             │      • column_batches, file_batches                 ┃
┃   │  • LLM 배치 구성              │                                                     ┃
┃   └───────────────────────────────┘                                                     ┃
┃                                                                                         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                              │
                                              ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 2: 의미 분석 (LLM-based)                                 ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                         ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [400] file_classification 🤖 │────▶│ PostgreSQL: file_catalog UPDATE            │  ┃
┃   │  • metadata vs data 분류      │     │  • is_metadata (true/false)                │  ┃
┃   │  • 파일 목적 추론             │     │  • llm_confidence                          │  ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────────┘  ┃
┃                   │                                                                     ┃
┃                   ▼                                                                     ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [500] metadata_semantic 🤖   │────▶│ PostgreSQL: data_dictionary                │  ┃
┃   │  • metadata 파일 파싱         │     │  • parameter_key (예: "HR", "SBP")         │  ┃
┃   │  • key-desc-unit 컬럼 식별    │     │  • parameter_desc (예: "Heart Rate")       │  ┃
┃   │  • data_dictionary 추출       │     │  • parameter_unit (예: "bpm")              │  ┃
┃   └───────────────────────────────┘     │  • extra_info (추가 메타정보)              │  ┃
┃                   │                     └────────────────────────────────────────────┘  ┃
┃                   ▼                                                                     ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [600] data_semantic 🤖       │────▶│ PostgreSQL: column_metadata UPDATE         │  ┃
┃   │  • data 파일 컬럼 의미 분석   │     │  • semantic_name (표준화된 이름)           │  ┃
┃   │  • data_dictionary 매칭       │     │  • unit (측정 단위)                        │  ┃
┃   │  • concept_category 추론      │     │  • concept_category (개념 카테고리)        │  ┃
┃   └───────────────────────────────┘     │  • dict_entry_id (dictionary FK)           │  ┃
┃                   │                     │  • dict_match_status                       │  ┃
┃                   ▼                     └────────────────────────────────────────────┘  ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [700] directory_pattern 🤖   │────▶│ PostgreSQL: directory_catalog UPDATE       │  ┃
┃   │  • 파일명 패턴 분석           │     │  • filename_pattern (예: "{caseid}.vital") │  ┃
┃   │  • ID 값 추출                 │     │  • filename_columns (추출할 필드 정의)     │  ┃
┃   │  • 패턴 기반 필드 정의        │     │                                            │  ┃
┃   └───────────────────────────────┘     │ PostgreSQL: file_catalog UPDATE            │  ┃
┃                                         │  • filename_values (예: {"caseid": 123})   │  ┃
┃                                         └────────────────────────────────────────────┘  ┃
┃                                                                                         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                              │
                                              ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 3: 관계 추론 (LLM + Neo4j)                               ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                         ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [800] entity_identification 🤖│───▶│ PostgreSQL: table_entities                 │  ┃
┃   │  • 테이블별 Entity 식별       │     │  • row_represents (예: "surgery")          │  ┃
┃   │  • row_represents 추론        │     │  • entity_identifier (예: "caseid")        │  ┃
┃   │  • entity_identifier 컬럼     │     │  • confidence, reasoning                   │  ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────────┘  ┃
┃                   │                                                                     ┃
┃                   ▼                                                                     ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [900] relationship_inference 🤖│──▶│ PostgreSQL: table_relationships            │  ┃
┃   │  • 테이블 간 FK 관계 추론     │     │  • source_file_id, target_file_id          │  ┃
┃   │  • Cardinality 추론 (1:N)     │     │  • source_column, target_column            │  ┃
┃   │  • 3-Level Ontology 구축      │     │  • relationship_type, cardinality          │  ┃
┃   └───────────────────────────────┘     └────────────────────────────────────────────┘  ┃
┃                                         ┌────────────────────────────────────────────┐  ┃
┃                                         │ Neo4j: 3-Level Ontology                    │  ┃
┃                                         │  • (RowEntity)-[:LINKS_TO]->(RowEntity)    │  ┃
┃                                         │  • (RowEntity)-[:HAS_CONCEPT]->(Category)  │  ┃
┃                                         │  • (Category)-[:CONTAINS]->(Parameter)     │  ┃
┃                                         │  • (RowEntity)-[:HAS_COLUMN]->(Parameter)  │  ┃
┃                                         │  • (RowEntity)-[:FILENAME_VALUE]->(Param)  │  ┃
┃                                         └────────────────────────────────────────────┘  ┃
┃                                                                                         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                              │
                                              ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                          PHASE 4: 온톨로지 강화 (LLM + Neo4j)                           ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                         ┃
┃   ┌───────────────────────────────┐     ┌────────────────────────────────────────────┐  ┃
┃   │ [1000] ontology_enhancement 🤖│───▶│ PostgreSQL: ontology_subcategories         │  ┃
┃   │  • Concept Hierarchy 세분화   │     │  • parent_category, subcategory_name       │  ┃
┃   │  • Semantic Edges 추론        │     │                                            │  ┃
┃   │  • Medical Term Mapping       │     │ PostgreSQL: semantic_edges                 │  ┃
┃   │  • Cross-table Semantics      │     │  • source_parameter, target_parameter      │  ┃
┃   └───────────────────────────────┘     │  • relationship_type (DERIVED_FROM 등)     │  ┃
┃                                         │                                            │  ┃
┃                                         │ PostgreSQL: medical_term_mappings          │  ┃
┃                                         │  • parameter_key                           │  ┃
┃                                         │  • snomed_code/name, loinc_code/name       │  ┃
┃                                         │  • icd10_code/name                         │  ┃
┃                                         │                                            │  ┃
┃                                         │ PostgreSQL: cross_table_semantics          │  ┃
┃                                         │  • source/target file_id, column           │  ┃
┃                                         │  • relationship_type                       │  ┃
┃                                         └────────────────────────────────────────────┘  ┃
┃                                         ┌────────────────────────────────────────────┐  ┃
┃                                         │ Neo4j: Extended Ontology                   │  ┃
┃                                         │  • (Category)-[:HAS_SUBCATEGORY]->(SubCat) │  ┃
┃                                         │  • (Param)-[:DERIVED_FROM]->(Param)        │  ┃
┃                                         │  • (Param)-[:RELATED_TO]->(Param)          │  ┃
┃                                         │  • (Param)-[:MAPS_TO]->(MedicalTerm)       │  ┃
┃                                         └────────────────────────────────────────────┘  ┃
┃                                                                                         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                              │
                                              ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                                        최종 출력                                        ┃
┃━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┃
┃                                                                                         ┃
┃   📊 PostgreSQL (정형 데이터)                    🧠 Neo4j (지식 그래프)                  ┃
┃   ┌────────────────────────────┐                ┌────────────────────────────────────┐  ┃
┃   │ directory_catalog          │                │         ┌──────────────┐           │  ┃
┃   │ file_catalog               │                │         │  RowEntity   │           │  ┃
┃   │ column_metadata            │                │         │  (surgery)   │           │  ┃
┃   │ data_dictionary            │                │         └───────┬──────┘           │  ┃
┃   │ table_entities             │                │     LINKS_TO    │   HAS_CONCEPT    │  ┃
┃   │ table_relationships        │                │        ┌────────┼────────┐         │  ┃
┃   │ ontology_subcategories     │                │        ▼        ▼        ▼         │  ┃
┃   │ semantic_edges             │                │   ┌─────────┐┌───────┐┌────────┐   │  ┃
┃   │ medical_term_mappings      │                │   │RowEntity││Category ││ SubCat │   │  ┃
┃   │ cross_table_semantics      │                │   │(lab)    ││(Vitals)  ││(Cardio)│   │  ┃
┃   └────────────────────────────┘                │   └─────────┘└────┬────┘└────────┘   │  ┃
┃                                                 │                   │ CONTAINS        │  ┃
┃                                                 │                   ▼                 │  ┃
┃                                                 │             ┌───────────┐           │  ┃
┃                                                 │             │ Parameter │           │  ┃
┃                                                 │             │   (HR)    │           │  ┃
┃                                                 │             └─────┬─────┘           │  ┃
┃                                                 │                   │ MAPS_TO        │  ┃
┃                                                 │                   ▼                 │  ┃
┃                                                 │           ┌─────────────┐           │  ┃
┃                                                 │           │ MedicalTerm │           │  ┃
┃                                                 │           │(SNOMED/LOINC)│           │  ┃
┃                                                 │           └─────────────┘           │  ┃
┃                                                 └────────────────────────────────────┘  ┃
┃                                                                                         ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## 📊 Phase별 결과물 상세

### 🔷 PHASE 1: 메타데이터 수집 (Rule-based)

물리적 메타데이터를 규칙 기반으로 수집합니다. LLM을 사용하지 않아 빠르고 정확합니다.

| Node | Order | 결과물 (DB) | 주요 필드 |
|------|-------|-------------|-----------|
| directory_catalog | 100 | `directory_catalog` | dir_path, file_count, file_extensions, filename_samples |
| file_catalog | 200 | `file_catalog` | file_path, file_size, processor_type, raw_stats |
| | | `column_metadata` | original_name, column_type, data_type, value_distribution |
| schema_aggregation | 300 | (State only) | unique_columns, unique_files, column_batches, file_batches |

```sql
-- directory_catalog 예시
SELECT dir_path, file_count, file_extensions FROM directory_catalog;
-- /data/Open_VitalDB/vital_files | 6388 | {"vital": 6388}

-- file_catalog 예시  
SELECT file_name, processor_type, raw_stats->>'row_count' FROM file_catalog;
-- clinical_data.csv | tabular | 6388

-- column_metadata 예시
SELECT original_name, column_type, data_type FROM column_metadata;
-- caseid | categorical | int64
-- hr | continuous | float64
```

---

### 🔷 PHASE 2: 의미 분석 (LLM-based)

LLM을 활용하여 데이터의 의미를 분석하고 풍부한 시맨틱 정보를 추가합니다.

| Node | Order | 결과물 (DB) | 주요 필드 |
|------|-------|-------------|-----------|
| file_classification | 400 | `file_catalog` UPDATE | is_metadata, llm_confidence |
| metadata_semantic | 500 | `data_dictionary` | parameter_key, parameter_desc, parameter_unit, extra_info |
| data_semantic | 600 | `column_metadata` UPDATE | semantic_name, unit, concept_category, dict_entry_id |
| directory_pattern | 700 | `directory_catalog` UPDATE | filename_pattern, filename_columns |
| | | `file_catalog` UPDATE | filename_values |

```sql
-- data_dictionary 예시 (metadata_semantic 결과)
SELECT parameter_key, parameter_desc, parameter_unit FROM data_dictionary;
-- hr          | Heart Rate                          | bpm
-- sbp         | Systolic Blood Pressure             | mmHg
-- spo2        | Peripheral Oxygen Saturation        | %

-- column_metadata (data_semantic 결과)
SELECT original_name, semantic_name, concept_category, unit FROM column_metadata;
-- hr          | Heart Rate           | Vitals              | bpm
-- caseid      | Case Identifier      | Identifier          | NULL

-- directory_catalog (directory_pattern 결과)
SELECT dir_path, filename_pattern, filename_columns FROM directory_catalog;
-- /data/vital_files | {caseid:integer}.vital | [{"name": "caseid", "type": "integer"}]
```

---

### 🔷 PHASE 3: 관계 추론 (LLM + Neo4j)

테이블 간 관계를 추론하고 Neo4j에 기본 온톨로지 구조를 구축합니다.

| Node | Order | PostgreSQL 결과물 | Neo4j 결과물 |
|------|-------|-------------------|--------------|
| entity_identification | 800 | `table_entities` | - |
| relationship_inference | 900 | `table_relationships` | 3-Level Ontology |

#### PostgreSQL 테이블 구조

```sql
-- table_entities (entity_identification 결과)
SELECT fc.file_name, te.row_represents, te.entity_identifier 
FROM table_entities te JOIN file_catalog fc ON te.file_id = fc.file_id;
-- clinical_data.csv | surgery     | caseid
-- lab_data.csv      | lab_result  | NULL (복합키)

-- table_relationships (relationship_inference 결과)
SELECT 
    s.file_name as source, t.file_name as target,
    tr.source_column, tr.target_column, tr.cardinality
FROM table_relationships tr
JOIN file_catalog s ON tr.source_file_id = s.file_id
JOIN file_catalog t ON tr.target_file_id = t.file_id;
-- clinical_data.csv | lab_data.csv | caseid | caseid | 1:N
```

#### Neo4j 3-Level Ontology

```cypher
-- Level 1: RowEntity (테이블이 나타내는 Entity)
(:RowEntity {name: "surgery", source_table: "clinical_data.csv"})
(:RowEntity {name: "lab_result", source_table: "lab_data.csv"})

-- Level 2: ConceptCategory (개념 그룹)
(:ConceptCategory {name: "Vitals"})
(:ConceptCategory {name: "Demographics"})
(:ConceptCategory {name: "Identifier"})

-- Level 3: Parameter (측정 파라미터)
(:Parameter {name: "hr", semantic_name: "Heart Rate", unit: "bpm"})
(:Parameter {name: "sbp", semantic_name: "Systolic Blood Pressure", unit: "mmHg"})

-- 관계 (Relationships)
(:RowEntity {name: "surgery"})-[:LINKS_TO {cardinality: "1:N"}]->(:RowEntity {name: "lab_result"})
(:RowEntity {name: "surgery"})-[:HAS_CONCEPT]->(:ConceptCategory {name: "Vitals"})
(:ConceptCategory {name: "Vitals"})-[:CONTAINS]->(:Parameter {name: "hr"})
(:RowEntity {name: "surgery"})-[:HAS_COLUMN]->(:Parameter {name: "caseid"})
(:RowEntity)-[:FILENAME_VALUE]->(:Parameter)  -- 파일명에서 추출된 값
```

**Neo4j 시각화:**

```
                    ┌─────────────────┐
                    │   RowEntity     │
                    │   "surgery"     │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │ LINKS_TO (1:N)     │ HAS_CONCEPT        │ HAS_COLUMN
        ▼                    ▼                    ▼
┌───────────────┐   ┌────────────────┐   ┌─────────────┐
│  RowEntity    │   │ConceptCategory │   │  Parameter  │
│ "lab_result"  │   │   "Vitals"     │   │  "caseid"   │
└───────────────┘   └───────┬────────┘   └─────────────┘
                            │ CONTAINS
                            ▼
                    ┌─────────────┐
                    │  Parameter  │
                    │    "hr"     │
                    └─────────────┘
```

---

### 🔷 PHASE 4: 온톨로지 강화 (LLM + Neo4j)

3-Level 온톨로지를 확장하여 더 풍부한 지식 그래프를 구축합니다.

| Node | Order | PostgreSQL 결과물 | Neo4j 결과물 |
|------|-------|-------------------|--------------|
| ontology_enhancement | 1000 | `ontology_subcategories` | SubCategory 노드 |
| | | `semantic_edges` | DERIVED_FROM, RELATED_TO 관계 |
| | | `medical_term_mappings` | MedicalTerm 노드, MAPS_TO 관계 |
| | | `cross_table_semantics` | 테이블 간 시맨틱 관계 |

#### PostgreSQL 테이블 구조

```sql
-- ontology_subcategories
SELECT parent_category, subcategory_name FROM ontology_subcategories;
-- Vitals       | Cardiovascular
-- Vitals       | Respiratory
-- Demographics | Patient_Info

-- semantic_edges  
SELECT source_parameter, target_parameter, relationship_type FROM semantic_edges;
-- bmi      | height    | DERIVED_FROM
-- bmi      | weight    | DERIVED_FROM
-- sbp      | dbp       | RELATED_TO

-- medical_term_mappings
SELECT parameter_key, snomed_code, snomed_name, loinc_code FROM medical_term_mappings;
-- hr       | 364075005  | Heart rate              | 8867-4
-- sbp      | 271649006  | Systolic blood pressure | 8480-6

-- cross_table_semantics
SELECT source_column, target_column, relationship_type FROM cross_table_semantics;
-- caseid | patient_id | SEMANTICALLY_SIMILAR
```

#### Neo4j Extended Ontology

```cypher
-- SubCategory 추가
(:ConceptCategory {name: "Vitals"})-[:HAS_SUBCATEGORY]->(:SubCategory {name: "Cardiovascular"})
(:ConceptCategory {name: "Vitals"})-[:HAS_SUBCATEGORY]->(:SubCategory {name: "Respiratory"})

-- Semantic Edges
(:Parameter {name: "bmi"})-[:DERIVED_FROM]->(:Parameter {name: "height"})
(:Parameter {name: "bmi"})-[:DERIVED_FROM]->(:Parameter {name: "weight"})
(:Parameter {name: "sbp"})-[:RELATED_TO]->(:Parameter {name: "dbp"})

-- Medical Term Mapping
(:Parameter {name: "hr"})-[:MAPS_TO]->(:MedicalTerm {
    snomed_code: "364075005",
    snomed_name: "Heart rate",
    loinc_code: "8867-4",
    loinc_name: "Heart rate"
})
```

---

## 📊 전체 DB 스키마 요약

### PostgreSQL 테이블 (10개)

| 테이블 | 생성 노드 | 주요 용도 |
|--------|-----------|----------|
| `directory_catalog` | directory_catalog → directory_pattern | 디렉토리 메타데이터 + 파일명 패턴 |
| `file_catalog` | file_catalog → file_classification | 파일 메타데이터 + 분류 + 파일명 값 |
| `column_metadata` | file_catalog → data_semantic | 컬럼 메타데이터 + 시맨틱 정보 |
| `data_dictionary` | metadata_semantic | 파라미터 정의 사전 (key-desc-unit) |
| `table_entities` | entity_identification | 테이블 Entity 정의 |
| `table_relationships` | relationship_inference | 테이블 간 FK 관계 |
| `ontology_subcategories` | ontology_enhancement | 카테고리 세분화 |
| `semantic_edges` | ontology_enhancement | 파라미터 간 의미 관계 |
| `medical_term_mappings` | ontology_enhancement | 의료 표준 용어 매핑 |
| `cross_table_semantics` | ontology_enhancement | 테이블 간 시맨틱 관계 |

### Neo4j 노드 & 관계

| 노드 타입 | 생성 노드 | 설명 |
|----------|-----------|------|
| `RowEntity` | relationship_inference | 테이블이 나타내는 Entity (surgery, patient 등) |
| `ConceptCategory` | relationship_inference | 개념 카테고리 (Vitals, Demographics 등) |
| `Parameter` | relationship_inference | 측정 파라미터 (hr, sbp 등) |
| `SubCategory` | ontology_enhancement | 세분화된 카테고리 (Cardiovascular 등) |
| `MedicalTerm` | ontology_enhancement | 표준 의료 용어 (SNOMED/LOINC) |

| 관계 타입 | 생성 노드 | 설명 |
|----------|-----------|------|
| `LINKS_TO` | relationship_inference | 테이블 간 FK 관계 |
| `HAS_CONCEPT` | relationship_inference | Entity → Category |
| `CONTAINS` | relationship_inference | Category → Parameter |
| `HAS_COLUMN` | relationship_inference | Entity → Parameter |
| `FILENAME_VALUE` | relationship_inference | Entity → Parameter (파일명 추출) |
| `HAS_SUBCATEGORY` | ontology_enhancement | Category → SubCategory |
| `DERIVED_FROM` | ontology_enhancement | 파라미터 파생 관계 |
| `RELATED_TO` | ontology_enhancement | 파라미터 상관 관계 |
| `MAPS_TO` | ontology_enhancement | 표준 용어 매핑 |

---

## 🤖 LLM 사용 노드 상세

### 📏 = Rule-based (LLM 미사용)
### 🤖 = LLM 사용

| Node | Type | LLM 질문 예시 | 출력 |
|------|------|--------------|------|
| directory_catalog | 📏 | - | 디렉토리 구조 |
| file_catalog | 📏 | - | 파일/컬럼 메타데이터 |
| schema_aggregation | 📏 | - | 집계 데이터 |
| file_classification | 🤖 | "이 파일이 metadata인가 data인가?" | is_metadata, confidence |
| metadata_semantic | 🤖 | "어떤 컬럼이 key/desc/unit인가?" | data_dictionary 엔트리 |
| data_semantic | 🤖 | "이 컬럼의 의미와 카테고리는?" | semantic_name, concept_category |
| directory_pattern | 🤖 | "파일명에서 어떤 필드를 추출?" | filename_pattern |
| entity_identification | 🤖 | "테이블의 각 행은 무엇을 나타내나?" | row_represents |
| relationship_inference | 🤖 | "테이블 간 FK 관계는?" | relationships |
| ontology_enhancement | 🤖 | "카테고리 세분화, 의료 용어 매핑" | subcategories, mappings |

---

## 🔧 실행 방법

### 1. 서비스 시작
```bash
cd IndexingAgent
./run_postgres_neo4j.sh   # PostgreSQL + Neo4j 실행
```

### 2. 인덱싱 실행
```bash
python test_full_pipeline_results.py
```

### 3. 결과 확인
```bash
python view_database.py    # PostgreSQL 테이블 확인
python view_llm_logs.py    # LLM 호출 로그 확인
```

---

## 📁 파일 구조

```
IndexingAgent/
├── src/
│   ├── agents/
│   │   ├── graph.py                     # LangGraph 워크플로우 정의
│   │   ├── state.py                     # AgentState (TypedDict)
│   │   ├── registry.py                  # NodeRegistry (동적 노드 관리)
│   │   ├── base/                        # BaseNode, Mixin 클래스
│   │   │   ├── __init__.py
│   │   │   ├── node.py                  # BaseNode 추상 클래스
│   │   │   └── mixins.py                # LLMMixin, DatabaseMixin
│   │   ├── models/                      # Pydantic 모델 (LLM 응답 스키마)
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # 공통 베이스 모델
│   │   │   ├── llm_responses.py         # LLM 응답 모델들
│   │   │   └── state_schemas.py         # State 스키마
│   │   ├── prompts/                     # 프롬프트 관리
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # PromptTemplate, MultiPromptTemplate
│   │   │   └── generator.py             # OutputFormatGenerator
│   │   └── nodes/
│   │       │
│   │       │   # 📏 Rule-based 노드 (단일 파일)
│   │       ├── directory_catalog.py     # [100] 디렉토리 스캔
│   │       ├── catalog.py               # [200] 파일/컬럼 메타데이터
│   │       ├── aggregator.py            # [300] 스키마 집계
│   │       ├── common.py                # 공통 유틸리티
│   │       │
│   │       │   # 🤖 LLM 노드 (폴더 구조: node.py + prompts.py)
│   │       ├── file_classification/     # [400] 파일 분류
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── metadata_semantic/       # [500] 메타데이터 의미 분석
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── data_semantic/           # [600] 데이터 의미 분석
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── directory_pattern/       # [700] 파일명 패턴 분석
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── entity_identification/   # [800] Entity 식별
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       ├── relationship_inference/  # [900] 관계 추론 + Neo4j
│   │       │   ├── __init__.py
│   │       │   ├── node.py
│   │       │   └── prompts.py
│   │       └── ontology_enhancement/    # [1000] 온톨로지 강화 (Multi-prompt)
│   │           ├── __init__.py
│   │           ├── node.py
│   │           └── prompts.py           # 4가지 Task 프롬프트
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py                # PostgreSQL 연결
│   │   ├── neo4j_connection.py          # Neo4j 연결
│   │   ├── schemas/                     # DDL 정의
│   │   │   ├── catalog.py               # file_catalog, column_metadata
│   │   │   ├── directory.py             # directory_catalog
│   │   │   ├── dictionary.py            # data_dictionary
│   │   │   ├── ontology_core.py         # table_entities, table_relationships
│   │   │   └── ontology_enhancement.py  # subcategories, edges, mappings
│   │   ├── repositories/                # CRUD 로직
│   │   │   ├── base.py
│   │   │   ├── column_repository.py
│   │   │   ├── dictionary_repository.py
│   │   │   ├── entity_repository.py
│   │   │   ├── file_repository.py
│   │   │   └── ontology_repository.py
│   │   └── managers/                    # 스키마 매니저
│   │       ├── base.py
│   │       ├── catalog.py
│   │       ├── dictionary.py
│   │       ├── directory.py
│   │       └── ontology.py
│   │
│   ├── processors/                      # 파일 처리기
│   │   ├── base.py                      # BaseDataProcessor
│   │   ├── tabular.py                   # CSV, Excel, Parquet
│   │   └── signal.py                    # .vital, .edf 등
│   │
│   ├── utils/
│   │   └── llm_client.py                # LLM 클라이언트 (OpenAI/Anthropic)
│   │
│   └── config.py                        # 설정 (Node별 Config)
│
├── data/
│   ├── raw/                             # 원본 데이터 파일 (gitignore)
│   ├── postgres_data/                   # PostgreSQL 데이터 (gitignore)
│   ├── postgres.log                     # PostgreSQL 로그 (gitignore)
│   └── neo4j.log                        # Neo4j 로그 (gitignore)
│
├── test_debug_pipeline.py               # 디버깅/테스트 스크립트
├── test_full_pipeline_results.py        # 전체 파이프라인 실행
├── view_database.py                     # DB 조회 도구
├── view_llm_logs.py                     # LLM 로그 조회 도구
├── reset_all.py                         # DB 초기화
├── run_postgres_neo4j.sh                # 서비스 시작 스크립트
└── requirements.txt                     # Python 의존성
```

### 노드 구조 규칙

| 노드 타입 | 구조 | 설명 |
|----------|------|------|
| 📏 Rule-based | 단일 파일 (`node.py`) | LLM 미사용, 규칙 기반 로직 |
| 🤖 LLM-based | 폴더 (`node.py` + `prompts.py`) | LLM 프롬프트 분리 관리 |

**LLM 노드 폴더 구조:**
- `__init__.py`: 노드와 프롬프트 클래스 export
- `node.py`: 노드 로직 (BaseNode 상속, execute 구현)
- `prompts.py`: PromptTemplate 상속, 프롬프트 정의

---

## ⚙️ 설정 (config.py)

### Node별 설정 클래스

| Config Class | Node | 주요 설정 |
|-------------|------|----------|
| `DirectoryCatalogConfig` | directory_catalog | FILENAME_SAMPLE_SIZE, SAMPLE_STRATEGY |
| `SchemaAggregationConfig` | schema_aggregation | BATCH_SIZE |
| `MetadataSemanticConfig` | metadata_semantic | COLUMN_BATCH_SIZE, CONCEPT_CATEGORIES |
| `DataSemanticConfig` | data_semantic | COLUMN_BATCH_SIZE, CONFIDENCE_THRESHOLD |
| `DirectoryPatternConfig` | directory_pattern | MAX_DIRS_PER_BATCH, MIN_FILES_FOR_PATTERN |
| `EntityIdentificationConfig` | entity_identification | TABLE_BATCH_SIZE, MAX_COLUMNS_PER_TABLE |
| `RelationshipInferenceConfig` | relationship_inference | FK_CANDIDATE_CONCEPTS, NEO4J_ENABLED |
| `OntologyEnhancementConfig` | ontology_enhancement | ENABLE_* 플래그, PARAMETER_BATCH_SIZE |

### LLM 설정

```python
class LLMConfig:
    ACTIVE_PROVIDER = "openai"  # or "anthropic"
    OPENAI_MODEL = "gpt-4o-2024-08-06"
    ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
    TEMPERATURE = 0.0  # 분석 정확도 위해 0
    MAX_TOKENS = 4096
```

### 환경 변수

```bash
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=openai
NEO4J_ENABLED=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

---

## 🎯 설계 원칙

1. **4-Phase Architecture**: Phase별로 명확히 분리된 처리 흐름
2. **Rule Prepares, LLM Decides**: 규칙 기반 전처리 + LLM 최종 판단
3. **Human-in-the-Loop**: 불확실할 때는 사람에게 확인
4. **Dual Storage**: PostgreSQL (정형) + Neo4j (그래프) 병렬 저장
5. **Progressive Enhancement**: 단계별로 온톨로지가 점진적으로 풍부해짐
6. **NodeRegistry 패턴**: 동적으로 노드 추가/제거 가능

---

## ⚠️ 알려진 제한사항

### Long-format 데이터 처리

현재 시스템은 **Long-format CSV**의 파라미터를 완전히 추출하지 못합니다:

```
Wide-format (지원됨):
┌─────────┬─────┬──────┬─────┐
│ caseid  │ HR  │ SpO2 │ BP  │  → 컬럼명이 파라미터
└─────────┴─────┴──────┴─────┘

Long-format (부분 지원):
┌─────────┬──────┬───────┐
│ caseid  │ name │ value │  → name 컬럼의 값들이 파라미터
├─────────┼──────┼───────┤
│ 1       │ HR   │ 72    │
│ 1       │ SpO2 │ 98    │
└─────────┴──────┴───────┘
```

`name` 컬럼의 unique values는 `value_distribution`에 저장되지만, 이를 온톨로지 파라미터로 자동 변환하는 기능은 아직 구현되지 않았습니다.

---

## 🔗 관련 문서

- [docs/ontology_builder_implementation_plan.md](docs/ontology_builder_implementation_plan.md) - 구현 계획
- [docs/ontology_and_multilevel_anchor_analysis.md](docs/ontology_and_multilevel_anchor_analysis.md) - 온톨로지 분석
- [docs/ontology_builder_datacatalog.md](docs/ontology_builder_datacatalog.md) - 데이터 카탈로그 설계
