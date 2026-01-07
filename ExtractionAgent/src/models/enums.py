# src/models/enums.py
"""
VitalExtractionAgent Enums

파이프라인에서 사용되는 열거형 정의.
"""

from enum import Enum


class Intent(str, Enum):
    """쿼리 의도 분류 (Vital 전용이므로 항상 DATA_RETRIEVAL)"""
    DATA_RETRIEVAL = "data_retrieval"


class TemporalType(str, Enum):
    """시간 범위 타입"""
    FULL_RECORD = "full_record"          # 전체 기록
    PROCEDURE_WINDOW = "procedure_window"    # 시술/수술 시간 범위
    TREATMENT_WINDOW = "treatment_window"  # 치료 시간 범위
    CUSTOM_WINDOW = "custom_window"      # 사용자 정의 범위


class ResolutionMode(str, Enum):
    """파라미터 해석 모드"""
    ALL_SOURCES = "all_sources"    # 모든 소스에서 데이터 가져오기
    SPECIFIC = "specific"          # 특정 소스만 선택
    CLARIFY = "clarify"            # 사용자에게 확인 필요


class OperatorType(str, Enum):
    """필터 연산자"""
    EQ = "="
    NE = "!="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    LIKE = "LIKE"
    IN = "IN"
    NOT_IN = "NOT IN"
    BETWEEN = "BETWEEN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"

