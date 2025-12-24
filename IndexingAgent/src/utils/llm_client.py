# src/utils/llm_client.py
"""
LLM Client with tenacity retry logic

Supports OpenAI, Anthropic, and Google Generative AI.
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Dict, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
import logging

# 각 SDK 라이브러리 임포트
try:
    from openai import OpenAI, RateLimitError as OpenAIRateLimitError, APIError as OpenAIAPIError
except ImportError:
    OpenAI = None
    OpenAIRateLimitError = Exception
    OpenAIAPIError = Exception

try:
    from anthropic import Anthropic, RateLimitError as AnthropicRateLimitError, APIError as AnthropicAPIError
except ImportError:
    Anthropic = None
    AnthropicRateLimitError = Exception
    AnthropicAPIError = Exception

try:
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted as GoogleRateLimitError
except ImportError:
    genai = None
    GoogleRateLimitError = Exception

# config 파일 임포트
from src import config

# Logger for retry logging
logger = logging.getLogger(__name__)


class LLMRetryConfig:
    """LLM 재시도 설정"""
    MAX_ATTEMPTS = 3
    MIN_WAIT_SECONDS = 1
    MAX_WAIT_SECONDS = 10
    EXPONENTIAL_BASE = 2


# Common retryable exceptions
RETRYABLE_EXCEPTIONS = (
    OpenAIRateLimitError,
    OpenAIAPIError,
    AnthropicRateLimitError,
    AnthropicAPIError,
    GoogleRateLimitError,
    ConnectionError,
    TimeoutError,
)


def create_retry_decorator():
    """Create a retry decorator with configured settings"""
    return retry(
        stop=stop_after_attempt(LLMRetryConfig.MAX_ATTEMPTS),
        wait=wait_exponential(
            multiplier=LLMRetryConfig.MIN_WAIT_SECONDS,
            min=LLMRetryConfig.MIN_WAIT_SECONDS,
            max=LLMRetryConfig.MAX_WAIT_SECONDS,
            exp_base=LLMRetryConfig.EXPONENTIAL_BASE
        ),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )


class AbstractLLMClient(ABC):
    """
    모든 LLM 클라이언트가 구현해야 하는 공통 인터페이스
    """
    
    @abstractmethod
    def ask_text(self, prompt: str) -> str:
        """일반 텍스트 응답을 요청"""
        pass

    def ask_json(self, prompt: str) -> Dict[str, Any]:
        """
        프롬프트를 보내고 결과를 JSON 객체(Dict)로 반환.
        JSON 파싱 실패 시 재시도하거나 에러를 반환하는 로직 포함.
        """
        system_instruction = (
            "\n\n[SYSTEM IMPORTANT]: You MUST respond with valid JSON only. "
            "Do not add markdown code blocks (```json). Do not add explanations."
        )
        full_prompt = prompt + system_instruction
        
        raw_response = self.ask_text(full_prompt)
        
        return self._clean_and_parse_json(raw_response)

    def _clean_and_parse_json(self, raw_text: str) -> Dict[str, Any]:
        """
        LLM이 흔히 저지르는 실수(Markdown backticks 등)를 제거하고 JSON 파싱
        """
        try:
            # 1. ```json ... ``` 패턴 제거
            text = re.sub(r"```json\s*", "", raw_text, flags=re.IGNORECASE)
            text = re.sub(r"```", "", text)
            
            # 2. 앞뒤 공백 제거
            text = text.strip()
            
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[LLM Error] JSON Parsing Failed. Raw text:\n{raw_text[:500]}...")
            return {"error": "JSON_DECODE_ERROR", "raw_text": raw_text}


class OpenAIClient(AbstractLLMClient):
    """OpenAI (ChatGPT) client with retry"""
    
    def __init__(self):
        if not OpenAI:
            raise ImportError("OpenAI library not installed. pip install openai")
        if not config.LLMConfig.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in config.")
            
        self.client = OpenAI(api_key=config.LLMConfig.OPENAI_API_KEY)
        self.model = config.LLMConfig.OPENAI_MODEL

    @create_retry_decorator()
    def ask_text(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=config.LLMConfig.TEMPERATURE
        )
        return response.choices[0].message.content

    @create_retry_decorator()
    def ask_json(self, prompt: str) -> Dict[str, Any]:
        """OpenAI는 JSON Mode를 지원하므로 오버라이딩해서 최적화"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=config.LLMConfig.TEMPERATURE
            )
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError:
            return {"error": "JSON_DECODE_ERROR"}
        except Exception as e:
            return {"error": str(e)}


class ClaudeClient(AbstractLLMClient):
    """Anthropic (Claude) client with retry"""
    
    def __init__(self):
        if not Anthropic:
            raise ImportError("Anthropic library not installed. pip install anthropic")
        if not config.LLMConfig.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in config.")

        self.client = Anthropic(api_key=config.LLMConfig.ANTHROPIC_API_KEY)
        self.model = config.LLMConfig.ANTHROPIC_MODEL

    @create_retry_decorator()
    def ask_text(self, prompt: str) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            temperature=config.LLMConfig.TEMPERATURE,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text


class GeminiClient(AbstractLLMClient):
    """Google (Gemini) client with retry"""
    
    def __init__(self):
        if not genai:
            raise ImportError("Google GenAI library not installed. pip install google-generativeai")
        if not config.LLMConfig.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set in config.")

        genai.configure(api_key=config.LLMConfig.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(config.LLMConfig.GEMINI_MODEL)

    @create_retry_decorator()
    def ask_text(self, prompt: str) -> str:
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=config.LLMConfig.TEMPERATURE
            )
        )
        return response.text
    
    @create_retry_decorator()
    def ask_json(self, prompt: str) -> Dict[str, Any]:
        """Gemini Pro 1.5는 response_mime_type을 지원함"""
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=config.LLMConfig.TEMPERATURE
                )
            )
            return json.loads(response.text)
        except Exception:
            # 구버전 모델 등을 위한 fallback
            return super().ask_json(prompt)


# Singleton instance cache
_llm_client_instance = None


def get_llm_client() -> AbstractLLMClient:
    """
    config.py의 설정에 따라 적절한 클라이언트 인스턴스를 반환 (Singleton)
    """
    global _llm_client_instance
    
    if _llm_client_instance is not None:
        return _llm_client_instance
    
    provider = config.LLMConfig.ACTIVE_PROVIDER

    if provider == "openai":
        _llm_client_instance = OpenAIClient()
    elif provider in ("anthropic", "claude"):
        _llm_client_instance = ClaudeClient()
    elif provider in ("google", "gemini"):
        _llm_client_instance = GeminiClient()
    else:
        raise ValueError(f"Unsupported LLM Provider: {provider}")
    
    return _llm_client_instance


def reset_llm_client():
    """Reset the singleton instance (useful for testing)"""
    global _llm_client_instance
    _llm_client_instance = None
