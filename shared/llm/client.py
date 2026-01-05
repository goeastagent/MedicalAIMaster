# shared/llm/client.py
"""
LLM Client with tenacity retry logic

Supports OpenAI and Anthropic (Claude).
"""

import json
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

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


# config 파일 임포트
from shared.config import LLMConfig

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
    def ask_text(self, prompt: str, max_tokens: int = None) -> str:
        """일반 텍스트 응답을 요청
        
        Args:
            prompt: 프롬프트 텍스트
            max_tokens: 최대 응답 토큰 수 (None이면 config 기본값 사용)
        """
        pass

    def ask_json(self, prompt: str, max_tokens: int = None) -> Dict[str, Any]:
        """
        프롬프트를 보내고 결과를 JSON 객체(Dict)로 반환.
        JSON 파싱 실패 시 재시도하거나 에러를 반환하는 로직 포함.
        
        Args:
            prompt: 프롬프트 텍스트
            max_tokens: 최대 응답 토큰 수 (None이면 config 기본값 사용)
        """
        system_instruction = (
            "\n\n[SYSTEM IMPORTANT]: You MUST respond with valid JSON only. "
            "Do not add markdown code blocks (```json). Do not add explanations."
        )
        full_prompt = prompt + system_instruction
        
        raw_response = self.ask_text(full_prompt, max_tokens=max_tokens)
        
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
    
    # Models that require max_completion_tokens instead of max_tokens
    NEW_API_MODELS = {'o1', 'o3', 'gpt-5', 'gpt-4o'}
    
    def __init__(self):
        if not OpenAI:
            raise ImportError("OpenAI library not installed. pip install openai")
        if not LLMConfig.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in config.")
            
        self.client = OpenAI(api_key=LLMConfig.OPENAI_API_KEY)
        self.model = LLMConfig.OPENAI_MODEL
        
        # Check if model uses new API (max_completion_tokens)
        self._use_new_api = any(
            self.model.lower().startswith(prefix) 
            for prefix in self.NEW_API_MODELS
        )
    
    def _get_token_param(self, max_tokens: int = None) -> Dict[str, int]:
        """Get the correct token parameter based on model type"""
        token_value = max_tokens or LLMConfig.MAX_TOKENS
        if self._use_new_api:
            return {"max_completion_tokens": token_value}
        else:
            return {"max_tokens": token_value}

    @create_retry_decorator()
    def ask_text(self, prompt: str, max_tokens: int = None) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=LLMConfig.TEMPERATURE,
            **self._get_token_param(max_tokens)
        )
        return response.choices[0].message.content

    @create_retry_decorator()
    def ask_json(self, prompt: str, max_tokens: int = None) -> Dict[str, Any]:
        """OpenAI는 JSON Mode를 지원하므로 오버라이딩해서 최적화"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=LLMConfig.TEMPERATURE,
                **self._get_token_param(max_tokens)
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
        if not LLMConfig.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in config.")

        self.client = Anthropic(api_key=LLMConfig.ANTHROPIC_API_KEY)
        self.model = LLMConfig.ANTHROPIC_MODEL

    @create_retry_decorator()
    def ask_text(self, prompt: str, max_tokens: int = None) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or LLMConfig.MAX_TOKENS,
            temperature=LLMConfig.TEMPERATURE,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text


# Singleton instance cache
_llm_client_instance = None


def get_llm_client() -> AbstractLLMClient:
    """
    config.py의 설정에 따라 적절한 클라이언트 인스턴스를 반환 (Singleton)
    """
    global _llm_client_instance
    
    if _llm_client_instance is not None:
        return _llm_client_instance
    
    provider = LLMConfig.ACTIVE_PROVIDER

    if provider == "openai":
        _llm_client_instance = OpenAIClient()
    elif provider in ("anthropic", "claude"):
        _llm_client_instance = ClaudeClient()
    else:
        raise ValueError(f"Unsupported LLM Provider: {provider}. Supported: openai, anthropic")
    
    return _llm_client_instance


def reset_llm_client():
    """Reset the singleton instance (useful for testing)"""
    global _llm_client_instance
    _llm_client_instance = None


# =============================================================================
# LLM Logging (Input/Output 저장)
# =============================================================================

class LoggingLLMClient(AbstractLLMClient):
    """
    LLM 클라이언트를 감싸서 모든 호출의 입력/출력을 파일에 저장하는 래퍼
    
    사용법:
        from src.utils.llm_client import enable_llm_logging
        enable_llm_logging("./data/llm_logs")
    """
    
    def __init__(self, client: AbstractLLMClient, log_dir: str):
        self._client = client
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._call_counter = 0
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 세션 폴더 생성
        self._session_dir = self._log_dir / f"session_{self._session_id}"
        self._session_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"LLM Logging enabled. Logs: {self._session_dir}")
    
    def _get_model_name(self) -> str:
        """래핑된 클라이언트의 모델명 반환"""
        if hasattr(self._client, 'model'):
            return self._client.model
        return "unknown"
    
    def _save_log(
        self, 
        method: str, 
        prompt: str, 
        response: Any, 
        duration: float,
        max_tokens: Optional[int] = None,
        error: Optional[str] = None
    ):
        """호출 로그를 파일에 저장"""
        self._call_counter += 1
        timestamp = datetime.now()
        
        # 파일명: 001_ask_json_20260101_123456.json
        filename = f"{self._call_counter:03d}_{method}_{timestamp.strftime('%H%M%S')}.json"
        filepath = self._session_dir / filename
        
        log_data = {
            "call_id": self._call_counter,
            "timestamp": timestamp.isoformat(),
            "method": method,
            "model": self._get_model_name(),
            "duration_seconds": round(duration, 3),
            "input": {
                "prompt": prompt,
                "max_tokens": max_tokens,
            },
            "output": {
                "response": response if isinstance(response, (dict, list)) else str(response),
            },
        }
        
        if error:
            log_data["error"] = error
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
        
        # 콘솔에도 간략히 출력
        print(f"📝 LLM Call #{self._call_counter} ({method}) - {duration:.2f}s - Saved to {filename}")
    
    def ask_text(self, prompt: str, max_tokens: int = None) -> str:
        """텍스트 응답 요청 (로깅 포함)"""
        start_time = time.time()
        error = None
        response = ""
        
        try:
            response = self._client.ask_text(prompt, max_tokens=max_tokens)
            return response
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start_time
            self._save_log("ask_text", prompt, response, duration, max_tokens, error)
    
    def ask_json(self, prompt: str, max_tokens: int = None) -> Dict[str, Any]:
        """JSON 응답 요청 (로깅 포함)"""
        start_time = time.time()
        error = None
        response = {}
        
        try:
            response = self._client.ask_json(prompt, max_tokens=max_tokens)
            return response
        except Exception as e:
            error = str(e)
            raise
        finally:
            duration = time.time() - start_time
            self._save_log("ask_json", prompt, response, duration, max_tokens, error)
    
    def get_session_dir(self) -> Path:
        """현재 세션의 로그 디렉토리 반환"""
        return self._session_dir
    
    def get_call_count(self) -> int:
        """현재까지의 호출 횟수 반환"""
        return self._call_counter


# Logging 상태
_logging_enabled = False
_logging_dir: Optional[str] = None


def enable_llm_logging(log_dir: str = "./data/llm_logs") -> Path:
    """
    LLM 로깅 활성화. 이후 모든 LLM 호출이 파일에 저장됨.
    
    Args:
        log_dir: 로그 저장 디렉토리 (기본: ./data/llm_logs)
    
    Returns:
        세션 로그 디렉토리 경로
    
    사용법:
        from src.utils.llm_client import enable_llm_logging
        session_dir = enable_llm_logging()
        # ... 파이프라인 실행 ...
        print(f"Logs saved to: {session_dir}")
    """
    global _llm_client_instance, _logging_enabled, _logging_dir
    
    _logging_enabled = True
    _logging_dir = log_dir
    
    # 기존 클라이언트가 있으면 래핑
    if _llm_client_instance is not None:
        if not isinstance(_llm_client_instance, LoggingLLMClient):
            _llm_client_instance = LoggingLLMClient(_llm_client_instance, log_dir)
            return _llm_client_instance.get_session_dir()
        else:
            return _llm_client_instance.get_session_dir()
    
    # 아직 클라이언트가 없으면 새로 생성 후 래핑
    provider = LLMConfig.ACTIVE_PROVIDER
    
    if provider == "openai":
        base_client = OpenAIClient()
    elif provider in ("anthropic", "claude"):
        base_client = ClaudeClient()
    else:
        raise ValueError(f"Unsupported LLM Provider: {provider}")
    
    _llm_client_instance = LoggingLLMClient(base_client, log_dir)
    return _llm_client_instance.get_session_dir()


def disable_llm_logging():
    """LLM 로깅 비활성화"""
    global _logging_enabled
    _logging_enabled = False
    # 기존 싱글톤 리셋 (다음 호출시 로깅 없이 생성)
    reset_llm_client()


def get_llm_log_session_dir() -> Optional[Path]:
    """현재 로깅 세션 디렉토리 반환 (로깅이 활성화된 경우)"""
    global _llm_client_instance
    if isinstance(_llm_client_instance, LoggingLLMClient):
        return _llm_client_instance.get_session_dir()
    return None
