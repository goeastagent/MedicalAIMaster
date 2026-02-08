# shared/config/llm.py
"""
LLM Configuration

OpenAI, Anthropic 등 LLM Provider 설정
"""
import os
from dotenv import load_dotenv

# .env 파일이 있다면 로드
load_dotenv()


class LLMConfig:
    """LLM Provider 설정"""
    
    # --- 1. 활성화할 Provider 선택 (openai, anthropic, google 중 택1) ---
    ACTIVE_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower() 

    # --- 2. OpenAI 설정 (ChatGPT) ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2-2025-12-11")

    # --- 3. Anthropic 설정 (Claude) ---
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5-20251101")

    # --- 4. Ollama 설정 (로컬 LLM) ---
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")  # Ollama는 API 키 불필요 (더미값)
    OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))  # 로컬 모델은 느릴 수 있음

    # --- 5. 공통 설정 ---
    TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))  # 분석 작업이므로 정확성을 위해 0
    
    # --- 5. Token 제한 설정 ---
    MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    MAX_TOKENS_COLUMN_ANALYSIS = int(os.getenv("LLM_MAX_TOKENS_COLUMN_ANALYSIS", "8192"))


class BaseLLMNodeConfig:
    """
    LLM을 사용하는 Node의 공통 설정
    
    metadata_semantic, data_semantic, entity_identification 등이 상속받아 사용합니다.
    서브클래스에서 필요시 오버라이드 가능합니다.
    """
    # LLM 재시도 설정
    MAX_RETRIES: int = 3
    RETRY_DELAY_SECONDS: int = 2
    
    # Confidence 임계값 (서브클래스에서 오버라이드)
    CONFIDENCE_THRESHOLD: float = 0.8


# Backward compatibility alias
BaseLLMPhaseConfig = BaseLLMNodeConfig


class BaseNeo4jNodeConfig(BaseLLMNodeConfig):
    """
    Neo4j를 사용하는 Node의 공통 설정
    
    relationship_inference, ontology_enhancement이 상속받아 사용합니다.
    """
    from .database import Neo4jConfig
    
    # Neo4j 연결 설정
    NEO4J_ENABLED: bool = Neo4jConfig.ENABLED


# Backward compatibility alias
BaseNeo4jPhaseConfig = BaseNeo4jNodeConfig

