# src/agents/prompts/base.py
"""
PromptTemplate 베이스 클래스

모든 LLM 프롬프트의 기반 클래스입니다.
프롬프트 구성요소를 구조화하고, 출력 형식을 자동 생성합니다.

사용 예시:
    class FileClassificationPrompt(PromptTemplate):
        name = "file_classification"
        response_model = FileClassificationItem
        response_wrapper_key = "classifications"
        is_list_response = True
        
        system_role = "You are a Medical Data Expert..."
        task_description = "Classify each file as metadata or data..."
        context_template = "[Files to Classify]\\n{files_info}"
        rules = [
            "metadata: Data dictionaries, codebooks...",
            "data: Actual measurements...",
        ]
    
    # 프롬프트 빌드
    prompt_str = FileClassificationPrompt.build(files_info="...")
    
    # LLM 응답 파싱
    items = FileClassificationPrompt.parse_response(llm_response)
"""

from abc import ABC
from typing import Any, Dict, List, Optional, Type, TypeVar, Union
from pydantic import BaseModel

from .generator import OutputFormatGenerator


T = TypeVar("T", bound=BaseModel)


class PromptTemplate(ABC):
    """
    LLM 프롬프트 템플릿 베이스 클래스
    
    서브클래스에서 정의해야 할 클래스 변수:
    - name: 프롬프트 식별자
    - response_model: 응답 파싱에 사용할 Pydantic 모델
    - response_wrapper_key: LLM 응답의 래퍼 키 (예: "classifications")
    - is_list_response: 응답이 리스트인지 여부
    - system_role: LLM의 역할 설명
    - task_description: 수행할 작업 설명
    - context_template: 컨텍스트 템플릿 (format 변수 포함)
    - rules: 추가 규칙/지침 리스트 (선택)
    - examples: Few-shot 예시 (선택)
    """
    
    # === 필수 클래스 변수 ===
    name: str = ""
    response_model: Optional[Type[BaseModel]] = None
    response_wrapper_key: Optional[str] = None
    is_list_response: bool = True
    
    # === 프롬프트 구성요소 ===
    system_role: str = ""
    task_description: str = ""
    context_template: str = ""
    rules: List[str] = []
    examples: List[Dict[str, Any]] = []
    
    # === 출력 형식 관련 ===
    custom_output_format: Optional[str] = None  # 커스텀 형식 (자동 생성 대신 사용)
    
    # === 내부 ===
    _generator = OutputFormatGenerator()
    
    @classmethod
    def build(cls, **context_vars) -> str:
        """
        최종 프롬프트 문자열 생성
        
        Args:
            **context_vars: context_template에 들어갈 변수들
            
        Returns:
            완성된 프롬프트 문자열
        """
        sections = []
        
        # 1. System Role
        if cls.system_role:
            sections.append(f"[Role]\n{cls.system_role}")
        
        # 2. Task Description
        if cls.task_description:
            sections.append(f"[Task]\n{cls.task_description}")
        
        # 3. Rules (있으면)
        if cls.rules:
            rules_text = "\n".join(f"- {rule}" for rule in cls.rules)
            sections.append(f"[Rules]\n{rules_text}")
        
        # 4. Examples (있으면)
        if cls.examples:
            examples_text = cls._format_examples()
            sections.append(f"[Examples]\n{examples_text}")
        
        # 5. Context (템플릿 변수 대입)
        if cls.context_template:
            try:
                context = cls.context_template.format(**context_vars)
                sections.append(f"[Context]\n{context}")
            except KeyError as e:
                raise ValueError(f"Missing context variable: {e}")
        
        # 6. Output Format (자동 생성 또는 커스텀)
        output_format = cls._get_output_format()
        if output_format:
            sections.append(f"[Output Format]\nRespond with valid JSON:\n{output_format}")
        
        return "\n\n".join(sections)
    
    @classmethod
    def _get_output_format(cls) -> str:
        """
        출력 형식 문자열 반환
        
        custom_output_format이 있으면 사용, 없으면 Pydantic 모델에서 자동 생성
        """
        if cls.custom_output_format:
            return cls.custom_output_format
        
        if cls.response_model:
            return cls._generator.generate(
                item_model=cls.response_model,
                wrapper_key=cls.response_wrapper_key,
                is_list=cls.is_list_response
            )
        
        return ""
    
    @classmethod
    def _format_examples(cls) -> str:
        """Few-shot 예시 포맷팅"""
        formatted = []
        for i, example in enumerate(cls.examples, 1):
            example_text = f"Example {i}:\n"
            if "input" in example:
                example_text += f"Input: {example['input']}\n"
            if "output" in example:
                example_text += f"Output: {example['output']}"
            formatted.append(example_text)
        return "\n\n".join(formatted)
    
    @classmethod
    def parse_response(
        cls,
        response: Dict[str, Any]
    ) -> Union[List[T], T, None]:
        """
        LLM 응답을 Pydantic 모델로 파싱
        
        Args:
            response: LLM의 JSON 응답 (dict)
            
        Returns:
            - is_list_response=True: List[response_model]
            - is_list_response=False: response_model
            - 파싱 실패 시: None
        """
        if not cls.response_model:
            return response  # 모델 없으면 raw dict 반환
        
        try:
            # wrapper_key로 데이터 추출
            if cls.response_wrapper_key:
                data = response.get(cls.response_wrapper_key, [])
            else:
                data = response
            
            # 리스트 응답
            if cls.is_list_response:
                if not isinstance(data, list):
                    data = [data]
                return [cls.response_model.model_validate(item) for item in data]
            
            # 단일 객체 응답
            return cls.response_model.model_validate(data)
            
        except Exception as e:
            # 파싱 실패 시 None 반환 (호출자가 처리)
            return None
    
    @classmethod
    def get_info(cls) -> Dict[str, Any]:
        """프롬프트 메타 정보 반환 (디버깅/문서화용)"""
        return {
            "name": cls.name,
            "response_model": cls.response_model.__name__ if cls.response_model else None,
            "response_wrapper_key": cls.response_wrapper_key,
            "is_list_response": cls.is_list_response,
            "has_rules": len(cls.rules) > 0,
            "has_examples": len(cls.examples) > 0,
        }


class MultiPromptTemplate(PromptTemplate):
    """
    여러 프롬프트를 포함하는 노드용 베이스 클래스
    
    ontology_enhancement처럼 여러 Task가 있는 노드에서 사용
    
    사용 예시:
        class OntologyEnhancementPrompts(MultiPromptTemplate):
            prompts = {
                "concept_hierarchy": ConceptHierarchyPrompt,
                "semantic_edges": SemanticEdgesPrompt,
                "medical_terms": MedicalTermPrompt,
                "cross_table": CrossTablePrompt,
            }
    """
    
    prompts: Dict[str, Type[PromptTemplate]] = {}
    
    @classmethod
    def get_prompt(cls, task_name: str) -> Optional[Type[PromptTemplate]]:
        """특정 Task의 프롬프트 클래스 반환"""
        return cls.prompts.get(task_name)
    
    @classmethod
    def build_for_task(cls, task_name: str, **context_vars) -> str:
        """특정 Task의 프롬프트 빌드"""
        prompt_cls = cls.get_prompt(task_name)
        if prompt_cls:
            return prompt_cls.build(**context_vars)
        raise ValueError(f"Unknown task: {task_name}")
    
    @classmethod
    def parse_response_for_task(
        cls,
        task_name: str,
        response: Dict[str, Any]
    ):
        """특정 Task의 응답 파싱"""
        prompt_cls = cls.get_prompt(task_name)
        if prompt_cls:
            return prompt_cls.parse_response(response)
        return None
    
    @classmethod
    def list_tasks(cls) -> List[str]:
        """사용 가능한 Task 목록"""
        return list(cls.prompts.keys())

