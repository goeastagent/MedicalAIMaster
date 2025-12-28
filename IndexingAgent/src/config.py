# config.py
import os
from dotenv import load_dotenv

# .env 파일이 있다면 로드
load_dotenv()

class Neo4jConfig:
    """Neo4j 데이터베이스 설정"""
    URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    USER = os.getenv("NEO4J_USER", "neo4j")
    PASSWORD = os.getenv("NEO4J_PASSWORD", "password") # 초기 비밀번호 확인 필요
    DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

class LLMConfig:
    # --- 1. 활성화할 Provider 선택 (openai, anthropic, google 중 택1) ---
    # 환경변수 'LLM_PROVIDER'가 설정되어 있으면 그걸 쓰고, 아니면 'openai'를 기본값으로 사용
    ACTIVE_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower() 

    # --- 2. OpenAI 설정 (ChatGPT) ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-5.2-2025-12-11"  # None = use default, or specify model name

    # --- 3. Anthropic 설정 (Claude) ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    AHTROPIC_MODEL = "claude-opus-4-5-20251101"  # None = use default, or specify model name

    # --- 4. 공통 설정 ---
    TEMPERATURE = 0.0  # 분석 작업이므로 창의성보다는 정확성을 위해 0에 가깝게 설정
    
    # --- 5. Token 제한 설정 ---
    # 응답 최대 토큰 수 (value_mappings 등 긴 응답 처리용)
    MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    
    # 컬럼 분석 시 최대 토큰 (많은 컬럼 처리 시 사용)
    MAX_TOKENS_COLUMN_ANALYSIS = int(os.getenv("LLM_MAX_TOKENS_COLUMN_ANALYSIS", "8192"))
    
    # Enrichment 시 최대 토큰 (definitions enrichment 시 사용)
    MAX_TOKENS_ENRICHMENT = int(os.getenv("LLM_MAX_TOKENS_ENRICHMENT", "4096"))


class EmbeddingConfig:
    """임베딩 모델 설정"""
    
    # --- 1. 임베딩 Provider 선택 ---
    # "openai" 또는 "local"
    PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai")
    
    # --- 2. OpenAI Embedding 설정 ---
    OPENAI_MODEL = "text-embedding-3-small"  # Good balance of performance & cost (1536 dimensions)
    OPENAI_DIMENSIONS = 1536
    # Alternative: "text-embedding-3-large" (3072 dims, highest performance)
    
    # --- 3. Local Embedding 설정 (무료) ---
    LOCAL_MODEL = "all-MiniLM-L6-v2"  # sentence-transformers 모델
    LOCAL_DIMENSIONS = 384
    
    @classmethod
    def get_dimensions(cls):
        """현재 선택된 모델의 차원 수 반환"""
        if cls.PROVIDER == "openai":
            return cls.OPENAI_DIMENSIONS
        else:
            return cls.LOCAL_DIMENSIONS


class HumanReviewConfig:
    """Human-in-the-Loop 설정 (유연한 Threshold 관리)"""
    
    # --- 1. Confidence Thresholds ---
    # 메타데이터 판단 시 Human Review 요청 기준 (이 값 미만이면 사람에게 물어봄)
    METADATA_CONFIDENCE_THRESHOLD = 0.90
    
    # Entity Identifier 매칭 시 Human Review 요청 기준
    ANCHOR_CONFIDENCE_THRESHOLD = 0.90  # Legacy name kept for backward compatibility
    
    # 분류 확신도 임계값 (이 값 미만이면 리뷰 필요)
    CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.75
    
    # LLM 확신도 임계값 (이 값 미만이면 파일명 분석 경고)
    FILENAME_ANALYSIS_CONFIDENCE_THRESHOLD = 0.70
    
    # LLM 확신도 임계값 (이 값 미만이면 메타데이터 감지 경고)
    METADATA_DETECTION_CONFIDENCE_THRESHOLD = 0.75
    
    # LLM 확신도 임계값 (이 값 미만이면 관계 추론 경고)
    RELATIONSHIP_CONFIDENCE_THRESHOLD = 0.80
    
    # 일반적인 기본 임계값
    DEFAULT_CONFIDENCE_THRESHOLD = 0.75
    
    # --- 2. LLM 기반 판단 활성화 ---
    # True: LLM이 직접 "Human Review가 필요한가" 판단 (더 유연하지만 비용 증가)
    # False: 기존 Rule-based 조건만 사용 (빠르고 저렴)
    USE_LLM_FOR_REVIEW_DECISION = True
    
    # --- 3. 자동 재시도 설정 ---
    MAX_RETRY_COUNT = 3
    
    # --- 4. Signal 파일 처리 ---
    SIGNAL_FILE_CONFIDENCE_THRESHOLD = 0.70  # Signal 파일 ID 확신도 임계값
    
    # --- 5. LLM Skip 임계값 ---
    # 이 값 미만이면 LLM 호출 생략 (비용 절감)
    LLM_SKIP_CONFIDENCE_THRESHOLD = 0.50


class MetadataEnrichmentConfig:
    """메타데이터 Enrichment 설정 (Hybrid Approach)"""
    
    # --- 1. 빠른 테스트 모드 ---
    # True: 첫 번째 청크만 LLM 처리 (빠른 테스트용)
    # False: 전체 청크 처리 (프로덕션용)
    FAST_TEST_MODE = True
    
    # 빠른 테스트 모드에서 처리할 최대 청크 수
    FAST_TEST_MAX_CHUNKS = 1
    
    # --- 2. 청킹 설정 ---
    # LLM에 한 번에 보낼 definition 수
    ENRICHMENT_CHUNK_SIZE = 100
    
    # --- 3. 컨텍스트 설정 ---
    # 대화 히스토리에서 포함할 최대 턴 수
    MAX_CONVERSATION_TURNS = 5


class Phase05Config:
    """Phase 0.5: Schema Aggregation 설정"""
    
    # --- 1. 배치 크기 ---
    # LLM에 한 번에 보낼 유니크 컬럼 수
    BATCH_SIZE = int(os.getenv("PHASE05_BATCH_SIZE", "100"))
    
    # --- 2. 집계 설정 ---
    # 샘플 파일 ID 최대 개수 (참고용)
    MAX_SAMPLE_FILE_IDS = 3
    
    # 범주형 컬럼의 샘플 값 최대 개수
    MAX_SAMPLE_VALUES = 5


class Phase1BConfig:
    """Phase 1B: Data Semantic Analysis 설정"""
    
    # --- 1. 컬럼 배치 크기 ---
    # 파일 내 컬럼 수가 이 값을 초과하면 배치로 나눠서 LLM 호출
    COLUMN_BATCH_SIZE = int(os.getenv("PHASE1B_COLUMN_BATCH_SIZE", "50"))
    
    # --- 2. Dictionary Context 설정 ---
    # data_dictionary에서 context에 포함할 최대 entry 수 (0 = 전체)
    MAX_DICT_ENTRIES = int(os.getenv("PHASE1B_MAX_DICT_ENTRIES", "0"))
    
    # --- 3. 통계 정보 설정 ---
    # categorical 컬럼의 unique values 최대 표시 개수
    MAX_UNIQUE_VALUES_DISPLAY = int(os.getenv("PHASE1B_MAX_UNIQUE_VALUES", "10"))
    
    # 샘플 값 최대 표시 개수
    MAX_SAMPLES_DISPLAY = int(os.getenv("PHASE1B_MAX_SAMPLES", "3"))
    
    # --- 4. LLM 설정 ---
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    # --- 5. Confidence 임계값 ---
    # 이 값 미만이면 dict_entry_key를 null로 설정하라고 LLM에게 안내
    MATCH_CONFIDENCE_THRESHOLD = float(os.getenv("PHASE1B_MATCH_CONFIDENCE", "0.7"))


class Phase2AConfig:
    """Phase 2A: Entity Identification 설정"""
    
    # --- 1. LLM 설정 ---
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    # --- 2. 배치 크기 ---
    # 한 번의 LLM 호출에 포함할 최대 테이블 수
    TABLE_BATCH_SIZE = int(os.getenv("PHASE2A_TABLE_BATCH_SIZE", "10"))
    
    # --- 3. Confidence 임계값 ---
    # 이 값 미만이면 낮은 확신도로 분류
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE2A_CONFIDENCE", "0.8"))
    
    # --- 4. 컬럼 정보 표시 설정 ---
    # LLM context에 포함할 테이블당 최대 컬럼 수 (0 = 전체)
    MAX_COLUMNS_PER_TABLE = int(os.getenv("PHASE2A_MAX_COLUMNS", "30"))
    
    # identifier 후보 컬럼 표시 시 unique count 포함 여부
    SHOW_UNIQUE_COUNTS = True


class Phase2BConfig:
    """Phase 2B: Relationship Inference + Neo4j 설정"""
    
    # --- 1. LLM 설정 ---
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    # --- 2. Confidence 임계값 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE2B_CONFIDENCE", "0.8"))
    
    # --- 3. Neo4j 연결 설정 ---
    NEO4J_ENABLED = os.getenv("NEO4J_ENABLED", "true").lower() == "true"
    
    # --- 4. FK 후보 탐지 설정 ---
    # FK 후보로 간주할 컬럼 concept_category 목록
    FK_CANDIDATE_CONCEPTS = ["Identifiers", "Demographics"]
    
    # FK 후보로 간주할 컬럼 이름 패턴
    FK_CANDIDATE_PATTERNS = ["id", "ID", "Id", "key", "Key", "code", "Code"]


class Phase2CConfig:
    """Phase 2C: Ontology Enhancement 설정"""
    
    # --- 1. LLM 설정 ---
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    # --- 2. Confidence 임계값 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE2C_CONFIDENCE", "0.7"))
    
    # --- 3. Neo4j 연결 설정 ---
    NEO4J_ENABLED = os.getenv("NEO4J_ENABLED", "true").lower() == "true"
    
    # --- 4. Task 활성화 설정 ---
    # 각 Enhancement Task 활성화 여부
    ENABLE_CONCEPT_HIERARCHY = os.getenv("PHASE2C_CONCEPT_HIERARCHY", "true").lower() == "true"
    ENABLE_SEMANTIC_EDGES = os.getenv("PHASE2C_SEMANTIC_EDGES", "true").lower() == "true"
    ENABLE_MEDICAL_TERMS = os.getenv("PHASE2C_MEDICAL_TERMS", "true").lower() == "true"
    ENABLE_CROSS_TABLE = os.getenv("PHASE2C_CROSS_TABLE", "true").lower() == "true"
    
    # --- 5. 배치 설정 ---
    # Semantic Edge 분석 시 한 번에 처리할 파라미터 수
    PARAMETER_BATCH_SIZE = int(os.getenv("PHASE2C_PARAM_BATCH_SIZE", "30"))
    
    # Medical Term 매핑 시 한 번에 처리할 파라미터 수
    MEDICAL_TERM_BATCH_SIZE = int(os.getenv("PHASE2C_MED_TERM_BATCH_SIZE", "20"))


class Phase1Config:
    """Phase 1: Semantic Analysis (LLM 배치 처리) 설정"""
    
    # --- 1. 컬럼 분석 배치 크기 ---
    # 한 번의 LLM 호출에 포함할 컬럼 수
    COLUMN_BATCH_SIZE = int(os.getenv("PHASE1_COLUMN_BATCH_SIZE", "50"))
    
    # --- 2. 파일 분석 배치 크기 ---
    # 한 번의 LLM 호출에 포함할 파일 수
    FILE_BATCH_SIZE = int(os.getenv("PHASE1_FILE_BATCH_SIZE", "20"))
    
    # --- 3. LLM 재시도 설정 (API 오류) ---
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    # --- 4. Human Review 설정 ---
    # Confidence 임계값 (이 값 미만이면 Human Review 필요)
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE1_CONFIDENCE_THRESHOLD", "0.8"))
    
    # Human Review 최대 재시도 횟수 (피드백 반영 후 재분석)
    MAX_REVIEW_RETRIES = int(os.getenv("PHASE1_MAX_REVIEW_RETRIES", "3"))
    
    # 리뷰 트리거 조건: 배치의 N% 이상이 low confidence면 리뷰
    MIN_LOW_CONF_RATIO = float(os.getenv("PHASE1_MIN_LOW_CONF_RATIO", "0.55"))
    
    # --- 5. 컨셉 카테고리 (LLM에게 안내용) ---
    CONCEPT_CATEGORIES = [
        "Vital Signs",
        "Hemodynamics", 
        "Respiratory",
        "Neurological",
        "Demographics",
        "Identifiers",
        "Timestamps",
        "Laboratory:Chemistry",
        "Laboratory:Hematology",
        "Laboratory:Coagulation",
        "Medication",
        "Anesthesia",
        "Surgical",
        "Device/Equipment",
        "Waveform/Signal",
        "Other"
    ]
    
    # --- 5. 도메인 카테고리 ---
    DOMAIN_CATEGORIES = [
        "Anesthesia",
        "Surgery",
        "ICU/Critical Care",
        "Laboratory",
        "Cardiology",
        "Neurology",
        "Respiratory",
        "General Clinical",
        "Administrative",
        "Reference/Lookup",
        "Other"
    ]
    
    # --- 6. Semantic Type 형식 ---
    # Format: "{Domain}:{SubType}"
    SEMANTIC_TYPE_DOMAINS = [
        "Signal",      # Signal:Physiological, Signal:Neurological
        "Clinical",    # Clinical:Demographics, Clinical:Encounters
        "Lab",         # Lab:Chemistry, Lab:Hematology
        "Medication",  # Medication:Administration
        "Reference",   # Reference:Parameters, Reference:Codes
        "Surgical",    # Surgical:Procedures
        "Other"
    ]


class ProcessingConfig:
    """파일 처리 관련 설정"""
    
    # --- 0. 파일 확장자 ---
    # Signal 파일 확장자 (항상 데이터로 분류)
    SIGNAL_EXTENSIONS = {'vital', 'edf', 'bdf', 'wfdb'}
    
        # Tabular 파일 확장자
    TABULAR_EXTENSIONS = {'csv', 'xlsx', 'xls', 'parquet'}
    
    # --- 1. 파일 크기 임계값 ---
    # 이 크기(MB) 이상이면 청크 처리
    LARGE_FILE_THRESHOLD_MB = 50
    
    # 청크 처리 시 청크 크기 (행 수)
    CHUNK_SIZE_ROWS = 100000
    
    # --- 2. 샘플링 ---
    # 메타데이터 추출 시 샘플 행 수
    METADATA_SAMPLE_ROWS = 20
    
    # LLM 컨텍스트에 포함할 최대 컬럼 상세 수
    MAX_COLUMN_DETAILS_FOR_LLM = 5
    
    # LLM 컨텍스트에 포함할 최대 트랙 수 (Signal 파일)
    MAX_TRACKS_FOR_LLM = 20
    
    # --- 3. 컨텍스트 제한 ---
    # LLM 컨텍스트 최대 크기 (bytes)
    MAX_LLM_CONTEXT_SIZE_BYTES = 3000
    
    # 텍스트 요약 시 최대 길이
    MAX_TEXT_SUMMARY_LENGTH = 50
    
    # Unique values 최대 수
    MAX_UNIQUE_VALUES_DISPLAY = 20
