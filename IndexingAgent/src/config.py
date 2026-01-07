# config.py
"""
IndexingAgent Configuration

10-Node Sequential Pipeline 설정:
- DirectoryCatalogConfig: 디렉토리 카탈로그
- SchemaAggregationConfig: 스키마 집계
- MetadataSemanticConfig: 메타데이터 시맨틱 분석
- DataSemanticConfig: 데이터 시맨틱 분석
- DirectoryPatternConfig: 디렉토리 패턴 분석
- EntityIdentificationConfig: 엔티티 식별
- RelationshipInferenceConfig: 관계 추론
- OntologyEnhancementConfig: 온톨로지 강화

구조:
- Neo4jConfig: shared.config에서 import
- LLMConfig: shared.config에서 import
- BaseLLMNodeConfig: shared.config에서 import
- *Config: 각 Node별 설정 (IndexingAgent 전용)
- ProcessingConfig: 파일 처리 관련 설정
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# .env 파일이 있다면 로드
load_dotenv()

# shared 패키지를 찾을 수 있도록 경로 추가
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# =============================================================================
# Shared Configuration (Re-export from shared.config)
# =============================================================================
from shared.config import (
    Neo4jConfig,
    LLMConfig,
    BaseLLMNodeConfig,
    BaseLLMPhaseConfig,  # Backward compatibility
    BaseNeo4jNodeConfig,
    BaseNeo4jPhaseConfig,  # Backward compatibility
)


# =============================================================================
# Global Indexing Configuration
# =============================================================================

class IndexingConfig:
    """
    전역 인덱싱 설정
    
    FORCE_REANALYZE: True면 이미 분석된 파일도 다시 LLM 분석
                     False면 llm_analyzed_at가 있는 파일은 스킵 (기본값)
    """
    FORCE_REANALYZE = os.getenv("FORCE_REANALYZE", "false").lower() == "true"

__all__ = [
    # Re-exported from shared.config
    'Neo4jConfig',
    'LLMConfig',
    'BaseLLMNodeConfig',
    'BaseLLMPhaseConfig',
    'BaseNeo4jNodeConfig',
    'BaseNeo4jPhaseConfig',
    # Global Indexing Config
    'IndexingConfig',
    # IndexingAgent specific configs
    'DirectoryCatalogConfig',
    'Phase1Config',
    'SchemaAggregationConfig',
    'Phase3Config',
    'MetadataSemanticConfig',
    'Phase5Config',
    'ColumnClassificationConfig',
    'DataSemanticConfig',
    'Phase6Config',
    'DirectoryPatternConfig',
    'Phase7Config',
    'EntityIdentificationConfig',
    'Phase8Config',
    'RelationshipInferenceConfig',
    'Phase9Config',
    'OntologyEnhancementConfig',
    'Phase10Config',
    'ProcessingConfig',
]


# =============================================================================
# Rule-based Nodes (LLM 미사용): directory_catalog, file_catalog, schema_aggregation
# =============================================================================

class DirectoryCatalogConfig:
    """[directory_catalog] 디렉토리 카탈로그 설정"""
    
    # --- 1. 파일명 샘플링 ---
    FILENAME_SAMPLE_SIZE = int(os.getenv("DIR_CATALOG_SAMPLE_SIZE", "20"))
    
    # 샘플링 전략: "first", "random", "diverse"
    SAMPLE_STRATEGY = os.getenv("DIR_CATALOG_SAMPLE_STRATEGY", "diverse")
    
    # --- 2. 디렉토리 필터링 ---
    IGNORE_DIRS = [".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"]
    IGNORE_PATTERNS = [".*", "*.pyc", "*.log", "*.tmp", "*.bak"]
    
    # --- 3. 처리 옵션 ---
    MIN_FILES_FOR_PATTERN = int(os.getenv("DIR_CATALOG_MIN_FILES", "3"))
    MAX_DEPTH = int(os.getenv("DIR_CATALOG_MAX_DEPTH", "10"))
    
    # --- 4. 확장자 그룹 ---
    SIGNAL_EXTENSIONS = {"vital", "edf", "bdf", "wav", "wfdb"}
    TABULAR_EXTENSIONS = {"csv", "tsv", "xlsx", "xls", "parquet"}
    METADATA_EXTENSIONS = {"json", "xml", "yaml", "yml", "txt", "md"}
    
    # --- 5. 디렉토리 타입 분류 기준 ---
    TYPE_CLASSIFICATION_THRESHOLD = float(os.getenv("DIR_CATALOG_TYPE_THRESHOLD", "0.8"))


# Backward compatibility alias
Phase1Config = DirectoryCatalogConfig


class SchemaAggregationConfig:
    """[schema_aggregation] 스키마 집계 설정"""
    
    # --- 1. 배치 크기 ---
    BATCH_SIZE = int(os.getenv("SCHEMA_AGG_BATCH_SIZE", "100"))
    
    # --- 2. 집계 설정 ---
    MAX_SAMPLE_FILE_IDS = 3
    MAX_SAMPLE_VALUES = 5


# Backward compatibility alias
Phase3Config = SchemaAggregationConfig


# =============================================================================
# LLM-based Nodes: file_classification ~ ontology_enhancement
# =============================================================================

class FileClassificationConfig(BaseLLMNodeConfig):
    """[file_classification] 파일 분류(metadata/data) 설정"""
    
    # --- 1. 파일 배치 크기 ---
    # 파일 수가 많을 때 LLM 호출을 나눠서 처리
    FILE_BATCH_SIZE = int(os.getenv("FILE_CLASS_FILE_BATCH_SIZE", "25"))
    
    # --- 2. Confidence 설정 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("FILE_CLASS_CONFIDENCE_THRESHOLD", "0.7"))


class MetadataSemanticConfig(BaseLLMNodeConfig):
    """[metadata_semantic] 메타데이터 시맨틱 분석 설정"""
    
    # --- 1. 배치 크기 ---
    COLUMN_BATCH_SIZE = int(os.getenv("METADATA_SEM_COLUMN_BATCH_SIZE", "50"))
    FILE_BATCH_SIZE = int(os.getenv("METADATA_SEM_FILE_BATCH_SIZE", "20"))
    
    # --- 2. Confidence 설정 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("METADATA_SEM_CONFIDENCE_THRESHOLD", "0.8"))
    MAX_REVIEW_RETRIES = int(os.getenv("METADATA_SEM_MAX_REVIEW_RETRIES", "3"))
    MIN_LOW_CONF_RATIO = float(os.getenv("METADATA_SEM_MIN_LOW_CONF_RATIO", "0.55"))
    
    # Note: 컨셉 카테고리는 src/agents/models/enums.py의 ConceptCategory ENUM 참조


# Backward compatibility alias
Phase5Config = MetadataSemanticConfig


class ColumnClassificationConfig(BaseLLMNodeConfig):
    """[column_classification] 컬럼 역할 분류 설정"""
    
    # --- 1. 컬럼 배치 크기 ---
    COLUMN_BATCH_SIZE = int(os.getenv("COL_CLASS_COLUMN_BATCH_SIZE", "20"))
    
    # --- 2. Confidence 설정 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("COL_CLASS_CONFIDENCE_THRESHOLD", "0.7"))


class DataSemanticConfig(BaseLLMNodeConfig):
    """[data_semantic] 데이터 시맨틱 분석 설정"""
    
    # --- 1. 컬럼 배치 크기 ---
    COLUMN_BATCH_SIZE = int(os.getenv("DATA_SEM_COLUMN_BATCH_SIZE", "50"))
    
    # --- 2. Dictionary Context 설정 ---
    MAX_DICT_ENTRIES = int(os.getenv("DATA_SEM_MAX_DICT_ENTRIES", "0"))
    
    # --- 3. 통계 정보 설정 ---
    MAX_UNIQUE_VALUES_DISPLAY = int(os.getenv("DATA_SEM_MAX_UNIQUE_VALUES", "10"))
    MAX_SAMPLES_DISPLAY = int(os.getenv("DATA_SEM_MAX_SAMPLES", "3"))
    
    # --- 4. Confidence 임계값 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("DATA_SEM_MATCH_CONFIDENCE", "0.7"))


# Backward compatibility alias
Phase6Config = DataSemanticConfig


class DirectoryPatternConfig:
    """[directory_pattern] 디렉토리 패턴 분석 설정"""
    
    # --- 1. 배치 처리 ---
    MAX_DIRS_PER_BATCH = int(os.getenv("DIR_PATTERN_MAX_DIRS_BATCH", "10"))
    MAX_SAMPLES_PER_DIR = int(os.getenv("DIR_PATTERN_MAX_SAMPLES", "10"))
    
    # --- 2. 필터링 ---
    MIN_FILES_FOR_PATTERN = int(os.getenv("DIR_PATTERN_MIN_FILES", "3"))
    SKIP_EXTENSIONS = {"txt", "md", "json", "xml", "yaml", "yml"}


# Backward compatibility alias
Phase7Config = DirectoryPatternConfig


class EntityIdentificationConfig(BaseLLMNodeConfig):
    """[entity_identification] 엔티티 식별 설정"""
    
    # --- 1. 배치 크기 ---
    TABLE_BATCH_SIZE = int(os.getenv("ENTITY_ID_TABLE_BATCH_SIZE", "10"))
    
    # --- 2. Confidence 임계값 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("ENTITY_ID_CONFIDENCE", "0.8"))
    
    # --- 3. 컬럼 정보 표시 설정 ---
    MAX_COLUMNS_PER_TABLE = int(os.getenv("ENTITY_ID_MAX_COLUMNS", "30"))
    SHOW_UNIQUE_COUNTS = True


# Backward compatibility alias
Phase8Config = EntityIdentificationConfig


class RelationshipInferenceConfig(BaseNeo4jNodeConfig):
    """[relationship_inference] 관계 추론 + Neo4j 설정"""
    
    # --- 1. Confidence 임계값 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("REL_INFER_CONFIDENCE", "0.8"))
    
    # --- 2. FK 후보 탐지 설정 ---
    FK_CANDIDATE_CONCEPTS = ["Identifiers", "Demographics"]
    FK_CANDIDATE_PATTERNS = ["id", "ID", "Id", "key", "Key", "code", "Code"]
    
    # --- 3. 배치 처리 설정 (프롬프트 크기 제한) ---
    MAX_TABLES_PER_BATCH = int(os.getenv("REL_INFER_MAX_TABLES_BATCH", "20"))
    MAX_SHARED_COLS_PER_BATCH = int(os.getenv("REL_INFER_MAX_SHARED_COLS_BATCH", "30"))


# Backward compatibility alias
Phase9Config = RelationshipInferenceConfig


class OntologyEnhancementConfig(BaseNeo4jNodeConfig):
    """[ontology_enhancement] 온톨로지 강화 설정"""
    
    # --- 1. Confidence 임계값 ---
    CONFIDENCE_THRESHOLD = float(os.getenv("ONTOLOGY_ENH_CONFIDENCE", "0.7"))
    
    # --- 2. Task 활성화 설정 ---
    ENABLE_CONCEPT_HIERARCHY = os.getenv("ONTOLOGY_ENH_CONCEPT_HIERARCHY", "true").lower() == "true"
    ENABLE_SEMANTIC_EDGES = os.getenv("ONTOLOGY_ENH_SEMANTIC_EDGES", "true").lower() == "true"
    ENABLE_MEDICAL_TERMS = os.getenv("ONTOLOGY_ENH_MEDICAL_TERMS", "true").lower() == "true"
    ENABLE_CROSS_TABLE = os.getenv("ONTOLOGY_ENH_CROSS_TABLE", "true").lower() == "true"
    
    # --- 3. 배치 설정 ---
    PARAMETER_BATCH_SIZE = int(os.getenv("ONTOLOGY_ENH_PARAM_BATCH_SIZE", "30"))
    MEDICAL_TERM_BATCH_SIZE = int(os.getenv("ONTOLOGY_ENH_MED_TERM_BATCH_SIZE", "20"))


# Backward compatibility alias
Phase10Config = OntologyEnhancementConfig


# =============================================================================
# Processing Configuration
# =============================================================================

class ProcessingConfig:
    """파일 처리 관련 설정"""
    
    # --- 0. 파일 확장자 (DirectoryCatalogConfig에서 참조) ---
    SIGNAL_EXTENSIONS = DirectoryCatalogConfig.SIGNAL_EXTENSIONS
    TABULAR_EXTENSIONS = DirectoryCatalogConfig.TABULAR_EXTENSIONS
    
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
