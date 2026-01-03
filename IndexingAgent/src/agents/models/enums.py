# src/agents/models/enums.py
"""
Enum 정의

데이터베이스 및 LLM 응답에서 사용되는 열거형 타입들을 정의합니다.
PostgreSQL은 VARCHAR로 저장하되, Python에서 타입 안정성을 제공합니다.
"""

from enum import Enum
from typing import List


class ColumnRole(str, Enum):
    """
    컬럼의 역할 분류
    
    [column_classification] 노드에서 LLM이 각 컬럼에 할당하는 역할입니다.
    이 값을 기반으로 parameter 테이블 생성 로직이 결정됩니다.
    """
    
    # Wide-format: 컬럼명이 파라미터 (예: HR, SpO2, Temperature 컬럼)
    PARAMETER_NAME = 'parameter_name'
    
    # Long-format: 컬럼 값들이 파라미터 (예: param 컬럼에 HR, SpO2 등이 값으로 있음)
    PARAMETER_CONTAINER = 'parameter_container'
    
    # 식별자 컬럼 (예: caseid, patient_id, subject_id)
    IDENTIFIER = 'identifier'
    
    # 측정값 컬럼 - Long-format에서 실제 값이 저장되는 컬럼 (예: value 컬럼)
    VALUE = 'value'
    
    # 단위 컬럼 - Long-format에서 단위가 저장되는 컬럼 (예: unit 컬럼)
    UNIT = 'unit'
    
    # 시간/날짜 컬럼 (예: timestamp, datetime, date)
    TIMESTAMP = 'timestamp'
    
    # 속성 컬럼 - 범주형 속성 (예: sex, department, diagnosis_code)
    ATTRIBUTE = 'attribute'
    
    # 기타 - 분류가 어려운 컬럼
    OTHER = 'other'
    
    @classmethod
    def values(cls) -> List[str]:
        """모든 역할 값 목록 반환 (LLM 프롬프트용)"""
        return [e.value for e in cls]
    
    @classmethod
    def descriptions(cls) -> dict:
        """각 역할의 설명 반환 (LLM 프롬프트용)"""
        return {
            cls.PARAMETER_NAME.value: "Column name itself is a measurement parameter (Wide-format)",
            cls.PARAMETER_CONTAINER.value: "Column values are parameter names (Long-format key column)",
            cls.IDENTIFIER.value: "Identifier column (caseid, patient_id, etc.)",
            cls.VALUE.value: "Measurement value column (Long-format)",
            cls.UNIT.value: "Unit column (Long-format)",
            cls.TIMESTAMP.value: "Time/date column",
            cls.ATTRIBUTE.value: "Categorical attribute (sex, department, etc.)",
            cls.OTHER.value: "Other/unknown",
        }
    
    @classmethod
    def for_prompt(cls) -> str:
        """LLM 프롬프트에 삽입할 수 있는 형식의 문자열 반환"""
        lines = []
        for role, desc in cls.descriptions().items():
            lines.append(f"- '{role}': {desc}")
        return "\n".join(lines)


class SourceType(str, Enum):
    """
    Parameter의 출처 타입
    
    parameter 테이블에서 해당 파라미터가 어디서 왔는지를 나타냅니다.
    """
    
    # Wide-format: 컬럼명에서 추출 (컬럼명 자체가 파라미터)
    COLUMN_NAME = 'column_name'
    
    # Long-format: 컬럼 값에서 추출 (key 컬럼의 unique values가 파라미터)
    COLUMN_VALUE = 'column_value'
    
    @classmethod
    def values(cls) -> List[str]:
        """모든 값 목록 반환"""
        return [e.value for e in cls]


class DictMatchStatus(str, Enum):
    """
    Dictionary 매칭 상태
    
    parameter와 data_dictionary 간의 매칭 결과를 나타냅니다.
    """
    
    # 매칭 성공
    MATCHED = 'matched'
    
    # dictionary에서 찾지 못함
    NOT_FOUND = 'not_found'
    
    # LLM이 null 반환 (불확실)
    NULL_FROM_LLM = 'null_from_llm'
    
    @classmethod
    def values(cls) -> List[str]:
        """모든 값 목록 반환"""
        return [e.value for e in cls]

