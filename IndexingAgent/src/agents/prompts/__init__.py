# src/agents/prompts/__init__.py
"""
LLM 프롬프트 관리 패키지

이 패키지는 모든 LLM 프롬프트를 체계적으로 관리합니다.

구조:
- base.py: PromptTemplate 베이스 클래스
- generator.py: Pydantic 모델 → JSON Output Format 자동 생성

노드별 프롬프트는 각 노드 폴더 내의 prompts.py에 정의됩니다:
- nodes/classification/prompts.py
- nodes/metadata_semantic/prompts.py
- nodes/data_semantic/prompts.py
- nodes/directory_pattern/prompts.py
- nodes/entity_identification/prompts.py
- nodes/relationship_inference/prompts.py
- nodes/ontology_enhancement/prompts.py

사용 예시:
    from src.agents.prompts import PromptTemplate, OutputFormatGenerator
    
    class MyPrompt(PromptTemplate):
        response_model = MyPydanticModel
        ...
"""

# Phase 1.2 완료
from .generator import OutputFormatGenerator, generate_output_format

# Phase 1.3 완료
from .base import PromptTemplate, MultiPromptTemplate

__all__ = [
    # Generator
    "OutputFormatGenerator",
    "generate_output_format",
    # Base Classes
    "PromptTemplate",
    "MultiPromptTemplate",
]

