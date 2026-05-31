"""Round-robin LLM routing helpers for Level 1 dataset generation."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Sequence

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMBackend:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


class RoundRobinJSONRouter:
    """Rotate across multiple LLM backends and parse JSON replies."""

    def __init__(self, backends: Sequence[LLMBackend], stage_name: str):
        if not backends:
            raise ValueError(f"{stage_name}: at least one backend is required")
        self.backends = list(backends)
        self.stage_name = stage_name
        self._cursor = 0

    def call_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        expect_array: bool,
    ) -> tuple[Any, str]:
        ordered_backends = self._next_backend_order()
        last_error: Exception | None = None

        for backend in ordered_backends:
            try:
                raw = self._call_backend(
                    backend=backend,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                parsed = self._parse_json(raw, expect_array=expect_array)
                return parsed, backend.label
            except Exception as e:
                last_error = e
                log.warning(
                    "%s backend failed [%s]: %s",
                    self.stage_name,
                    backend.label,
                    e,
                )

        raise RuntimeError(
            f"{self.stage_name}: all configured backends failed"
            + (f" (last error: {last_error})" if last_error else "")
        )

    def _next_backend_order(self) -> list[LLMBackend]:
        start = self._cursor % len(self.backends)
        self._cursor += 1
        return self.backends[start:] + self.backends[:start]

    def _call_backend(
        self,
        *,
        backend: LLMBackend,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if backend.provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model=backend.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (response.choices[0].message.content or "").strip()

        if backend.provider == "claude":
            from anthropic import Anthropic

            client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model=backend.model,
                temperature=temperature,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            parts = []
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()

        raise ValueError(f"Unsupported provider: {backend.provider}")

    @staticmethod
    def _parse_json(raw: str, *, expect_array: bool) -> Any:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned).strip()

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            pattern = r"\[.*\]" if expect_array else r"\{.*\}"
            match = re.search(pattern, cleaned, re.DOTALL)
            if not match:
                raise
            parsed = json.loads(match.group())

        if expect_array:
            if isinstance(parsed, dict):
                return [parsed]
            if not isinstance(parsed, list):
                raise ValueError("Expected JSON array response")
            return parsed

        if isinstance(parsed, list):
            if len(parsed) == 1 and isinstance(parsed[0], dict):
                return parsed[0]
            raise ValueError("Expected JSON object response")
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object response")
        return parsed


def build_router(
    *,
    providers: Sequence[str],
    openai_model: str,
    claude_model: str,
    stage_name: str,
) -> RoundRobinJSONRouter:
    """Build a router from provider order, skipping unavailable credentials."""
    backends: list[LLMBackend] = []

    for provider in providers:
        normalized = provider.lower()
        if normalized == "anthropic":
            normalized = "claude"

        if normalized == "openai":
            if not os.getenv("OPENAI_API_KEY"):
                log.warning("%s: OPENAI_API_KEY missing, skipping OpenAI backend", stage_name)
                continue
            backends.append(LLMBackend(provider="openai", model=openai_model))
            continue

        if normalized == "claude":
            if not os.getenv("ANTHROPIC_API_KEY"):
                log.warning("%s: ANTHROPIC_API_KEY missing, skipping Claude backend", stage_name)
                continue
            backends.append(LLMBackend(provider="claude", model=claude_model))
            continue

        raise ValueError(f"{stage_name}: unsupported provider '{provider}'")

    if not backends:
        raise ValueError(f"{stage_name}: no usable backends configured")

    log.info(
        "%s backends: %s",
        stage_name,
        ", ".join(backend.label for backend in backends),
    )
    return RoundRobinJSONRouter(backends=backends, stage_name=stage_name)
