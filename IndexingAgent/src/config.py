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
    
    # Anchor 매칭 시 Human Review 요청 기준
    ANCHOR_CONFIDENCE_THRESHOLD = 0.90
    
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


class ProcessingConfig:
    """파일 처리 관련 설정"""
    
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
