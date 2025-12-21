📑 Autonomous Dynamic Indexing Agent 구현 계획표문서 버전: v4.0 (JSONB Dynamic Schema 반영)작성일: 2025-12-17작성자: Medical AI Team목표: 무작위 데이터(Random Data) 수용 및 자율적 메타데이터 스키마 설계를 통한 "지능형 데이터 레이크" 구축1. 개요 (Overview)1.1 배경 및 목적기존의 고정된 스키마(Fixed Schema) 방식은 다양한 형태의 비정형 데이터(Signal, Log, Financial 등)를 수용하는 데 한계가 있음.본 프로젝트는 LLM의 추론 능력을 활용하여 데이터의 성격을 스스로 파악하고, 최적의 메타데이터 구조를 **동적으로 설계(Dynamic Design)**하여 저장하는 자율 인덱싱 에이전트를 구축함.1.2 핵심 철학Universal Ingestion: 의료 데이터뿐만 아니라 어떤 포맷(CSV, Vital, JSON 등)이든 수용한다.Schema-on-Write by AI: 데이터를 저장하는 시점에 LLM이 스키마를 정의한다.Zero-Scan Retrieval: Analysis Agent가 분석 시 원본 파일을 열지 않고도, DB 쿼리만으로 완벽한 코호트 선별이 가능하게 한다.2. 시스템 아키텍처 (Architecture)2.1 데이터 흐름도 (Data Flow)코드 스니펫graph TD
    A[Raw Data File] --> B(Loader Node)
    B --> C{Processor Selection}
    C -- Tabular --> D[Tabular Processor]
    C -- Signal --> E[Signal Processor]
    
    D & E --> F[Dynamic Profiler Node]
    F -- LLM Reasoning --> G[Schema Design]
    G --> H[Metadata Extractor Node]
    H -- Code Execution --> I[Generated Metadata (JSON)]
    
    I --> J[Catalog Manager]
    J --> K[(PostgreSQL - JSONB)]
    J --> L[(VectorDB - Semantic)]
2.2 주요 모듈 역할Processors (Rule): 파일의 헤더, 기술적 스펙(SR, Unit), 샘플 데이터를 "있는 그대로" 추출.Dynamic Profiler (LLM): 샘플 데이터를 보고 "이 데이터는 무엇이며(Semantic Type), 검색을 위해 어떤 정보가 필요한지(Key Metadata)"를 결정.Catalog Manager (DB): 고정된 컬럼 없이 JSONB 컨테이너에 메타데이터를 유연하게 적재.3. 데이터베이스 설계 (Database Schema)전략: PostgreSQL의 JSONB를 활용한 Schema-less SQL 구조.3.1 file_catalog (Main Storage)모든 파일의 메타데이터가 저장되는 만능 테이블.컬럼명타입설명예시file_idSERIALPK101file_pathTEXT물리적 경로 (Unique)/data/raw/case01.vitalsemantic_typeVARCHAR데이터 유형 (LLM 정의)Signal:Hemodynamics, Biz:Salesfile_metadataJSONB동적 메타데이터 (핵심){ "sampling_rate": 500, "duration": 1200, "patients": ["P01"] }created_atTIMESTAMP생성일인덱싱 전략: file_metadata 컬럼에 GIN Index를 적용하여 JSON 내부 Key에 대한 고속 검색 지원.3.2 schema_registry (Metadata Map)Analysis Agent에게 "어떤 유형의 데이터에서 무엇을 검색할 수 있는지" 알려주는 지도.컬럼명타입설명semantic_typeVARCHARPK (예: Signal:Hemodynamics)searchable_keysJSONB검색 가능 키 목록 (예: ["duration", "sampling_rate", "devices"])descriptionTEXT유형 설명4. 상세 구현 계획 (Implementation Phases)✅ Phase 3.1: DB 인프라 구축 (Infrastructure)목표: 유연한 저장을 위한 DB 환경 구성[ ] DDL 작성 (src/database/ddl.sql):file_catalog 테이블 생성 (JSONB 컬럼 포함).GIN Index 생성 구문 작성.schema_registry 테이블 생성.[ ] Catalog Manager 구현 (src/database/catalog_manager.py):Python Dictionary $\rightarrow$ PostgreSQL JSONB 변환 적재 로직 (psycopg2.extras.Json 활용).Upsert(Insert or Update) 로직 구현.✅ Phase 3.2: 동적 프로파일러 구현 (Intelligence)목표: LLM이 스스로 스키마를 설계하도록 만들기[ ] Profiler Node 구현 (src/agents/nodes.py):Processor의 출력(헤더, 샘플)을 입력으로 받음.Prompt Engineering:"이 데이터의 성격을 정의해라.""분석가가 필터링에 사용할 핵심 메타데이터 Key 5개를 제안해라."[ ] Extractor Node 구현:LLM이 제안한 Key를 실제 값으로 추출하는 Python 코드 생성 및 실행기.(예: df['price'].mean() 계산)✅ Phase 3.3: 통합 및 검증 (Integration)목표: 전체 파이프라인 연결[ ] Graph 연결 (src/agents/graph.py):Loader -> Profiler -> Extractor -> Indexer 순서 연결.[ ] 테스트 시나리오 수행:Case 1 (의료): .vital 파일 입력 $\rightarrow$ sampling_rate, duration 자동 추출 확인.Case 2 (일반): 주식/매출 .csv 입력 $\rightarrow$ ticker, total_sales 자동 추출 확인.5. Analysis Agent와의 인터페이스 (Interface)Indexing Agent가 구축한 DB를 Analysis Agent가 어떻게 조회하는지 정의함.5.1 검색 쿼리 예시 (JSON Query)질문: "샘플링 레이트 500Hz 이상인 데이터 찾아줘."SQL-- Analysis Agent가 생성할 쿼리
SELECT file_path 
FROM file_catalog 
WHERE file_metadata->>'sampling_rate' IS NOT NULL 
  AND (file_metadata->>'sampling_rate')::float >= 500;
6. 일정 및 리소스단계작업 내용예상 소요 시간담당Week 1DB 스키마 변경 (JSONB), Catalog Manager 구현2일DevWeek 1Dynamic Profiler 프롬프트 개발 및 테스트3일Dev/AIWeek 2Metadata Extractor (Code Execution) 구현3일DevWeek 2통합 테스트 (Random Data Ingestion)2일QA7. 기대 효과유연성(Flexibility): 스키마 변경 없이 어떤 도메인의 데이터도 즉시 수용 가능.검색 속도(Performance): 파일을 열지 않고 인덱싱된 JSONB 쿼리로 밀리초(ms) 단위 코호트 선별.자율성(Autonomy): 개발자가 일일이 파싱 규칙을 짜지 않아도 에이전트가 알아서 중요 정보를 추출함.ㄱ