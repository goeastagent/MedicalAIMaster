# src/agents/prompts/generator.py
"""
Pydantic 모델 → JSON Output Format 자동 생성기

Pydantic 모델의 필드 정보(타입, description, example)를 활용하여
LLM에게 전달할 출력 형식을 자동으로 생성합니다.

사용 예시:
    from IndexingAgent.src.models.llm_responses import FileClassificationItem
    
    generator = OutputFormatGenerator()
    format_str = generator.generate(
        item_model=FileClassificationItem,
        wrapper_key="classifications",
        is_list=True
    )
    
    # 결과:
    # {
    #   "classifications": [
    #     {
    #       "file_name": "string - 파일명",
    #       "is_metadata": "boolean - True=메타데이터, False=데이터",
    #       "confidence": "float (0.0-1.0) - 분류 확신도",
    #       "reasoning": "string - 판단 근거"
    #     }
    #   ]
    # }
"""

import json
from typing import Any, Dict, List, Optional, Type, Union, get_args, get_origin
from pydantic import BaseModel
from pydantic.fields import FieldInfo


class OutputFormatGenerator:
    """
    Pydantic 모델에서 LLM용 JSON Output Format 생성
    
    Features:
    - Field(description=...) → 필드 설명 포함
    - Field(examples=[...]) → 예시 값 표시
    - 중첩 모델 지원
    - List, Optional 타입 자동 처리
    """
    
    def generate(
        self,
        item_model: Type[BaseModel],
        wrapper_key: Optional[str] = None,
        is_list: bool = True,
        indent: int = 2
    ) -> str:
        """
        Pydantic 모델에서 JSON Output Format 문자열 생성
        
        Args:
            item_model: Pydantic 모델 클래스
            wrapper_key: 최상위 래퍼 키 (예: "classifications")
                         None이면 래퍼 없이 직접 객체/리스트 반환
            is_list: True면 리스트 형태, False면 단일 객체
            indent: JSON 들여쓰기 수준
            
        Returns:
            LLM에게 전달할 Output Format 문자열
        """
        # 모델 스키마 생성
        item_schema = self._model_to_schema(item_model)
        
        # 래퍼 적용
        if wrapper_key:
            if is_list:
                output = {wrapper_key: [item_schema]}
            else:
                output = {wrapper_key: item_schema}
        else:
            if is_list:
                output = [item_schema]
            else:
                output = item_schema
        
        # JSON 문자열로 변환 (예쁘게)
        return json.dumps(output, indent=indent, ensure_ascii=False)
    
    def generate_with_comments(
        self,
        item_model: Type[BaseModel],
        wrapper_key: Optional[str] = None,
        is_list: bool = True
    ) -> str:
        """
        주석 스타일의 Output Format 생성 (가독성 향상)
        
        JSON이 아닌 주석 형태로 출력 (LLM이 이해하기 쉬움)
        """
        lines = []
        lines.append("{")
        
        if wrapper_key:
            if is_list:
                lines.append(f'  "{wrapper_key}": [')
                lines.append("    {")
                self._add_field_lines(item_model, lines, indent=6)
                lines.append("    }")
                lines.append("  ]")
            else:
                lines.append(f'  "{wrapper_key}": {{')
                self._add_field_lines(item_model, lines, indent=4)
                lines.append("  }")
        else:
            if is_list:
                lines.append("  [")
                lines.append("    {")
                self._add_field_lines(item_model, lines, indent=6)
                lines.append("    }")
                lines.append("  ]")
            else:
                self._add_field_lines(item_model, lines, indent=2)
        
        lines.append("}")
        return "\n".join(lines)
    
    def _model_to_schema(self, model: Type[BaseModel]) -> Dict[str, Any]:
        """
        Pydantic 모델을 설명 포함 스키마로 변환
        """
        schema = {}
        
        for field_name, field_info in model.model_fields.items():
            schema[field_name] = self._field_to_description(field_name, field_info)
        
        return schema
    
    def _field_to_description(self, field_name: str, field_info: FieldInfo) -> str:
        """
        필드 정보를 설명 문자열로 변환
        
        예: "string - 파일명" 또는 "float (0.0-1.0) - 분류 확신도"
        """
        # 타입 문자열 생성
        type_str = self._get_type_string(field_info.annotation)
        
        # description 가져오기
        description = field_info.description or ""
        
        # 예시 값이 있으면 추가
        examples = []
        if field_info.examples:
            examples = field_info.examples
        elif field_info.json_schema_extra and isinstance(field_info.json_schema_extra, dict):
            examples = field_info.json_schema_extra.get("examples", [])
        
        # 조합
        parts = [type_str]
        
        # 제약조건 추가 (ge, le 등)
        constraints = self._get_constraints(field_info)
        if constraints:
            parts[0] = f"{type_str} ({constraints})"
        
        if description:
            parts.append(description)
        
        if examples:
            examples_str = ", ".join(str(e) for e in examples[:3])
            parts.append(f"예: {examples_str}")
        
        return " - ".join(parts) if len(parts) > 1 else parts[0]
    
    def _get_type_string(self, annotation: Any) -> str:
        """
        Python 타입 어노테이션을 LLM 친화적 문자열로 변환
        """
        if annotation is None:
            return "any"
        
        origin = get_origin(annotation)
        args = get_args(annotation)
        
        # Optional[X] = Union[X, None]
        if origin is Union:
            non_none_args = [a for a in args if a is not type(None)]
            if len(non_none_args) == 1:
                inner = self._get_type_string(non_none_args[0])
                return f"{inner} or null"
            return "any"
        
        # List[X]
        if origin is list:
            if args:
                inner = self._get_type_string(args[0])
                return f"array of {inner}"
            return "array"
        
        # Dict[K, V]
        if origin is dict:
            return "object"
        
        # 기본 타입들
        type_map = {
            str: "string",
            int: "integer",
            float: "float",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        
        if annotation in type_map:
            return type_map[annotation]
        
        # Pydantic 모델인 경우
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return f"object ({annotation.__name__})"
        
        return "any"
    
    def _get_constraints(self, field_info: FieldInfo) -> str:
        """
        필드 제약조건(ge, le 등) 추출
        """
        constraints = []
        
        # Pydantic v2에서 metadata로 제약조건 접근
        for metadata in field_info.metadata:
            if hasattr(metadata, "ge"):
                constraints.append(f">={metadata.ge}")
            if hasattr(metadata, "le"):
                constraints.append(f"<={metadata.le}")
            if hasattr(metadata, "gt"):
                constraints.append(f">{metadata.gt}")
            if hasattr(metadata, "lt"):
                constraints.append(f"<{metadata.lt}")
        
        return ", ".join(constraints)
    
    def _add_field_lines(
        self,
        model: Type[BaseModel],
        lines: List[str],
        indent: int
    ):
        """
        필드별 라인 추가 (주석 스타일용)
        """
        indent_str = " " * indent
        fields = list(model.model_fields.items())
        
        for i, (field_name, field_info) in enumerate(fields):
            desc = self._field_to_description(field_name, field_info)
            comma = "," if i < len(fields) - 1 else ""
            lines.append(f'{indent_str}"{field_name}": "{desc}"{comma}')


# 싱글톤 인스턴스 (편의용)
_generator_instance: Optional[OutputFormatGenerator] = None


def get_output_format_generator() -> OutputFormatGenerator:
    """OutputFormatGenerator 싱글톤 반환"""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = OutputFormatGenerator()
    return _generator_instance


def generate_output_format(
    item_model: Type[BaseModel],
    wrapper_key: Optional[str] = None,
    is_list: bool = True
) -> str:
    """
    편의 함수: Pydantic 모델에서 Output Format 생성
    
    사용 예시:
        format_str = generate_output_format(
            FileClassificationItem,
            wrapper_key="classifications",
            is_list=True
        )
    """
    return get_output_format_generator().generate(
        item_model=item_model,
        wrapper_key=wrapper_key,
        is_list=is_list
    )

