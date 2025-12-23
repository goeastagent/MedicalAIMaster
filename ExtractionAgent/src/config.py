import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LLM Settings
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo")
    TEMPERATURE = 0.0
    
    # DB Settings
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "medical_data")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
    
    # Neo4j Settings
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
    
    # Output Settings
    OUTPUT_DIR = "ExtractionAgent/outputs"


class EmbeddingConfig:
    """임베딩 모델 설정 (IndexingAgent와 동일하게 유지)"""
    
    # --- 1. 임베딩 Provider 선택 ---
    # "openai" 또는 "local"
    PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai")
    
    # --- 2. OpenAI Embedding 설정 ---
    OPENAI_MODEL = "text-embedding-3-small"  # 1536 dimensions (good balance)
    OPENAI_DIMENSIONS = 1536
    # Alternative: "text-embedding-3-large" (3072 dims, highest performance)
    
    # --- 3. Local Embedding 설정 (무료) ---
    LOCAL_MODEL = "all-MiniLM-L6-v2"  # sentence-transformers 모델
    LOCAL_DIMENSIONS = 384

