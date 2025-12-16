# src/utils/llm_client.py
import json
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

# 각 SDK 라이브러리 임포트 (설치 필요: openai, anthropic, google-generativeai)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

# config 파일 임포트
import config

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
        # 시스템 프롬프트에 JSON 강제 명령 추가
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
        except json.JSONDecodeError as e:
            print(f"[LLM Error] JSON Parsing Failed. Raw text:\n{raw_text}")
            # 실패 시 빈 딕셔너리 혹은 에러 정보를 담아 반환
            return {"error": "JSON_DECODE_ERROR", "raw_text": raw_text}


# --- 구현체 1: OpenAI (ChatGPT) ---
class OpenAIClient(AbstractLLMClient):
    def __init__(self):
        if not OpenAI:
            raise ImportError("OpenAI library not installed. pip install openai")
        if not config.LLMConfig.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in config.")
            
        self.client = OpenAI(api_key=config.LLMConfig.OPENAI_API_KEY)
        self.model = config.LLMConfig.OPENAI_MODEL

    def ask_text(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=config.LLMConfig.TEMPERATURE
        )
        return response.choices[0].message.content

    def ask_json(self, prompt: str) -> Dict[str, Any]:
        """OpenAI는 JSON Mode를 지원하므로 오버라이딩해서 최적화"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that outputs JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}, # GPT-4/3.5-turbo 최신 기능
                temperature=config.LLMConfig.TEMPERATURE
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            return {"error": str(e)}


# --- 구현체 2: Anthropic (Claude) ---
class ClaudeClient(AbstractLLMClient):
    def __init__(self):
        if not Anthropic:
            raise ImportError("Anthropic library not installed. pip install anthropic")
        if not config.LLMConfig.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in config.")

        self.client = Anthropic(api_key=config.LLMConfig.ANTHROPIC_API_KEY)
        self.model = config.LLMConfig.ANTHROPIC_MODEL

    def ask_text(self, prompt: str) -> str:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            temperature=config.LLMConfig.TEMPERATURE,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text


# --- 구현체 3: Google (Gemini) ---
class GeminiClient(AbstractLLMClient):
    def __init__(self):
        if not genai:
            raise ImportError("Google GenAI library not installed. pip install google-generativeai")
        if not config.LLMConfig.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set in config.")

        genai.configure(api_key=config.LLMConfig.GOOGLE_API_KEY)
        self.model = genai.GenerativeModel(config.LLMConfig.GEMINI_MODEL)

    def ask_text(self, prompt: str) -> str:
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=config.LLMConfig.TEMPERATURE
            )
        )
        return response.text
    
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
        except Exception as e:
            # 구버전 모델 등을 위한 fallback
            return super().ask_json(prompt)


# --- Factory Function (핵심) ---
def get_llm_client() -> AbstractLLMClient:
    """
    config.py의 설정에 따라 적절한 클라이언트 인스턴스를 반환
    """
    provider = config.LLMConfig.ACTIVE_PROVIDER

    if provider == "openai":
        return OpenAIClient()
    elif provider == "anthropic" or provider == "claude":
        return ClaudeClient()
    elif provider == "google" or provider == "gemini":
        return GeminiClient()
    else:
        raise ValueError(f"Unsupported LLM Provider: {provider}")