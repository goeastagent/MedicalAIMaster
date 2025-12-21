import os
import json
import re
from typing import Dict, Any, Optional
from ExtractionAgent.config import Config

class LLMClient:
    """ExtractionAgent 전용 LLM 클라이언트"""
    
    def __init__(self):
        self.provider = Config.LLM_PROVIDER
        if self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
            self.model = Config.OPENAI_MODEL
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def ask_text(self, prompt: str) -> str:
        if self.provider == "openai":
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=Config.TEMPERATURE
            )
            return response.choices[0].message.content
        return ""

    def ask_json(self, prompt: str) -> Dict[str, Any]:
        system_instruction = "\n\n[IMPORTANT]: Respond ONLY with valid JSON."
        raw_response = self.ask_text(prompt + system_instruction)
        return self._clean_and_parse_json(raw_response)

    def _clean_and_parse_json(self, raw_text: str) -> Dict[str, Any]:
        try:
            text = re.sub(r"```json\s*", "", raw_text, flags=re.IGNORECASE)
            text = re.sub(r"```", "", text)
            text = text.strip()
            return json.loads(text)
        except Exception as e:
            print(f"JSON Parsing Error: {e}\nRaw: {raw_text}")
            return {"error": "parsing_failed", "raw": raw_text}

