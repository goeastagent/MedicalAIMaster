# config.py
import os
from dotenv import load_dotenv

# .env 파일이 있다면 로드
load_dotenv()

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

    # --- 5. 공통 설정 ---
    TEMPERATURE = 0.0  # 분석 작업이므로 창의성보다는 정확성을 위해 0에 가깝게 설정
