# config.py
"""
IndexingAgent Configuration

10-Phase Sequential Pipeline 설정:
- Phase 1: Directory Catalog
- Phase 3: Schema Aggregation
- Phase 5: Metadata Semantic
- Phase 6: Data Semantic
- Phase 7: Directory Pattern
- Phase 8: Entity Identification
- Phase 9: Relationship Inference
- Phase 10: Ontology Enhancement

구조:
- Neo4jConfig: Neo4j 데이터베이스 설정
- LLMConfig: LLM Provider 설정
- BaseLLMPhaseConfig: LLM 사용 Phase의 공통 설정 (추상)
- Phase1~10Config: 각 Phase별 설정
- ProcessingConfig: 파일 처리 관련 설정
"""
import os
from dotenv import load_dotenv

# .env 파일이 있다면 로드
load_dotenv()


# =============================================================================
# Database Configuration
# =============================================================================

class Neo4jConfig:
    """Neo4j 데이터베이스 설정"""
    URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    USER = os.getenv("NEO4J_USER", "neo4j")
    PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
    DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


# =============================================================================
# LLM Configuration
# =============================================================================

class LLMConfig:
    """LLM Provider 설정"""
    
    # --- 1. 활성화할 Provider 선택 (openai, anthropic, google 중 택1) ---
    ACTIVE_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower() 

    # --- 2. OpenAI 설정 (ChatGPT) ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-5.2-2025-12-11"

    # --- 3. Anthropic 설정 (Claude) ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = "claude-opus-4-5-20251101"

    # --- 4. 공통 설정 ---
    TEMPERATURE = 0.0  # 분석 작업이므로 정확성을 위해 0
    
    # --- 5. Token 제한 설정 ---
    MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    MAX_TOKENS_COLUMN_ANALYSIS = int(os.getenv("LLM_MAX_TOKENS_COLUMN_ANALYSIS", "8192"))


# =============================================================================
# Base Configuration Classes (공통 설정)
# =============================================================================

class BaseLLMPhaseConfig:
    """
    LLM을 사용하는 Phase의 공통 설정
    
    Phase 5, 6, 8, 9, 10이 상속받아 사용합니다.
    서브클래스에서 필요시 오버라이드 가능합니다.
    """
    # LLM 재시도 설정
    MAX_RETRIES: int = 3
    RETRY_DELAY_SECONDS: int = 2
    
    # Confidence 임계값 (서브클래스에서 오버라이드)
    CONFIDENCE_THRESHOLD: float = 0.8


class BaseNeo4jPhaseConfig(BaseLLMPhaseConfig):
    """
    Neo4j를 사용하는 Phase의 공통 설정
    
    Phase 9, 10이 상속받아 사용합니다.
    """
    # Neo4j 연결 설정
    NEO4J_ENABLED: bool = os.getenv("NEO4J_ENABLED", "true").lower() == "true"


# =============================================================================
# Phase 1-3: Rule-based Phases (LLM 미사용)
# =============================================================================

class Phase1Config:
    """Phase 1: Directory Catalog 설정"""
    
    # --- 1. 파일명 샘플링 ---
    FILENAME_SAMPLE_SIZE = int(os.getenv("PHASE_NEG1_SAMPLE_SIZE", "20"))
    
    # 샘플링 전략: "first", "random", "diverse"
    SAMPLE_STRATEGY = os.getenv("PHASE_NEG1_SAMPLE_STRATEGY", "diverse")
    
    # --- 2. 디렉토리 필터링 ---
    IGNORE_DIRS = [".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"]
    IGNORE_PATTERNS = [".*", "*.pyc", "*.log", "*.tmp", "*.bak"]
    
    # --- 3. 처리 옵션 ---
    MIN_FILES_FOR_PATTERN = int(os.getenv("PHASE_NEG1_MIN_FILES", "3"))
    MAX_DEPTH = int(os.getenv("PHASE_NEG1_MAX_DEPTH", "10"))
    
    # --- 4. 확장자 그룹 ---
    SIGNAL_EXTENSIONS = {"vital", "edf", "bdf", "wav", "wfdb"}
    TABULAR_EXTENSIONS = {"csv", "tsv", "xlsx", "xls", "parquet"}
    METADATA_EXTENSIONS = {"json", "xml", "yaml", "yml", "txt", "md"}
    
    # --- 5. 디렉토리 타입 분류 기준 ---
    TYPE_CLASSIFICATION_THRESHOLD = float(os.getenv("PHASE_NEG1_TYPE_THRESHOLD", "0.8"))


class Phase3Config:
    """Phase 3: Schema Aggregation 설정"""
    
    # --- 1. 배치 크기 ---
    BATCH_SIZE = int(os.getenv("PHASE05_BATCH_SIZE", "100"))
    
    # --- 2. 집계 설정 ---
    MAX_SAMPLE_FILE_IDS = 3
    MAX_SAMPLE_VALUES = 5


# =============================================================================
# Phase 5-10: LLM-based Phases
# =============================================================================

class Phase5Config(BaseLLMPhaseConfig):
    """Phase 5: Metadata Semantic Analysis 설정"""
    
    # --- 1. 배치 크기 ---
    COLUMN_BATCH_SIZE = int(os.getenv("PHASE1_COLUMN_BATCH_SIZE", "50"))
    FILE_BATCH_SIZE = int(os.getenv("PHASE1_FILE_BATCH_SIZE", "20"))
    
    # --- 2. Confidence 설정 (BaseLLMPhaseConfig.CONFIDENCE_THRESHOLD 오버라이드) ---
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE1_CONFIDENCE_THRESHOLD", "0.8"))
    MAX_REVIEW_RETRIES = int(os.getenv("PHASE1_MAX_REVIEW_RETRIES", "3"))
    MIN_LOW_CONF_RATIO = float(os.getenv("PHASE1_MIN_LOW_CONF_RATIO", "0.55"))
    
    # --- 3. 컨셉 카테고리 ---
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
    
    # --- 4. 도메인 카테고리 ---
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
    
    # --- 5. Semantic Type 형식 ---
    SEMANTIC_TYPE_DOMAINS = [
        "Signal",      # Signal:Physiological, Signal:Neurological
        "Clinical",    # Clinical:Demographics, Clinical:Encounters
        "Lab",         # Lab:Chemistry, Lab:Hematology
        "Medication",  # Medication:Administration
        "Reference",   # Reference:Parameters, Reference:Codes
        "Surgical",    # Surgical:Procedures
        "Other"
    ]


class Phase6Config(BaseLLMPhaseConfig):
    """Phase 6: Data Semantic Analysis 설정"""
    
    # --- 1. 컬럼 배치 크기 ---
    COLUMN_BATCH_SIZE = int(os.getenv("PHASE1B_COLUMN_BATCH_SIZE", "50"))
    
    # --- 2. Dictionary Context 설정 ---
    MAX_DICT_ENTRIES = int(os.getenv("PHASE1B_MAX_DICT_ENTRIES", "0"))
    
    # --- 3. 통계 정보 설정 ---
    MAX_UNIQUE_VALUES_DISPLAY = int(os.getenv("PHASE1B_MAX_UNIQUE_VALUES", "10"))
    MAX_SAMPLES_DISPLAY = int(os.getenv("PHASE1B_MAX_SAMPLES", "3"))
    
    # --- 4. Confidence 임계값 (오버라이드) ---
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE1B_MATCH_CONFIDENCE", "0.7"))


class Phase7Config:
    """Phase 7: Directory Pattern Analysis 설정"""
    
    # --- 1. 배치 처리 ---
    MAX_DIRS_PER_BATCH = int(os.getenv("PHASE1C_MAX_DIRS_BATCH", "10"))
    MAX_SAMPLES_PER_DIR = int(os.getenv("PHASE1C_MAX_SAMPLES", "10"))
    
    # --- 2. 필터링 ---
    MIN_FILES_FOR_PATTERN = int(os.getenv("PHASE1C_MIN_FILES", "3"))
    SKIP_EXTENSIONS = {"txt", "md", "json", "xml", "yaml", "yml"}


class Phase8Config(BaseLLMPhaseConfig):
    """Phase 8: Entity Identification 설정"""
    
    # --- 1. 배치 크기 ---
    TABLE_BATCH_SIZE = int(os.getenv("PHASE2A_TABLE_BATCH_SIZE", "10"))
    
    # --- 2. Confidence 임계값 (오버라이드) ---
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE2A_CONFIDENCE", "0.8"))
    
    # --- 3. 컬럼 정보 표시 설정 ---
    MAX_COLUMNS_PER_TABLE = int(os.getenv("PHASE2A_MAX_COLUMNS", "30"))
    SHOW_UNIQUE_COUNTS = True


class Phase9Config(BaseNeo4jPhaseConfig):
    """Phase 9: Relationship Inference + Neo4j 설정"""
    
    # --- 1. Confidence 임계값 (오버라이드) ---
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE2B_CONFIDENCE", "0.8"))
    
    # --- 2. FK 후보 탐지 설정 ---
    FK_CANDIDATE_CONCEPTS = ["Identifiers", "Demographics"]
    FK_CANDIDATE_PATTERNS = ["id", "ID", "Id", "key", "Key", "code", "Code"]


class Phase10Config(BaseNeo4jPhaseConfig):
    """Phase 10: Ontology Enhancement 설정"""
    
    # --- 1. Confidence 임계값 (오버라이드) ---
    CONFIDENCE_THRESHOLD = float(os.getenv("PHASE2C_CONFIDENCE", "0.7"))
    
    # --- 2. Task 활성화 설정 ---
    ENABLE_CONCEPT_HIERARCHY = os.getenv("PHASE2C_CONCEPT_HIERARCHY", "true").lower() == "true"
    ENABLE_SEMANTIC_EDGES = os.getenv("PHASE2C_SEMANTIC_EDGES", "true").lower() == "true"
    ENABLE_MEDICAL_TERMS = os.getenv("PHASE2C_MEDICAL_TERMS", "true").lower() == "true"
    ENABLE_CROSS_TABLE = os.getenv("PHASE2C_CROSS_TABLE", "true").lower() == "true"
    
    # --- 3. 배치 설정 ---
    PARAMETER_BATCH_SIZE = int(os.getenv("PHASE2C_PARAM_BATCH_SIZE", "30"))
    MEDICAL_TERM_BATCH_SIZE = int(os.getenv("PHASE2C_MED_TERM_BATCH_SIZE", "20"))


# =============================================================================
# Processing Configuration
# =============================================================================

class ProcessingConfig:
    """파일 처리 관련 설정"""
    
    # --- 0. 파일 확장자 (Phase1Config에서 참조) ---
    SIGNAL_EXTENSIONS = Phase1Config.SIGNAL_EXTENSIONS
    TABULAR_EXTENSIONS = Phase1Config.TABULAR_EXTENSIONS
    
    # --- 1. 파일 크기 임계값 ---
    LARGE_FILE_THRESHOLD_MB = 50
    CHUNK_SIZE_ROWS = 100000
    
    # --- 2. 샘플링 ---
    METADATA_SAMPLE_ROWS = 20
    MAX_COLUMN_DETAILS_FOR_LLM = 5
    MAX_TRACKS_FOR_LLM = 20
    
    # --- 3. 컨텍스트 제한 ---
    MAX_LLM_CONTEXT_SIZE_BYTES = 3000
    MAX_TEXT_SUMMARY_LENGTH = 50
    MAX_UNIQUE_VALUES_DISPLAY = 20
