# shared/models/__init__.py
"""
Shared Models

공유 데이터 모델:
- enums.py: 열거형 타입 정의 (ColumnRole, SourceType, DictMatchStatus, ConceptCategory, TemporalType)
- plan.py: Execution Plan 관련 모델 (CohortMetadata, SignalMetadata, JoinConfig, ParsedPlan, AnalysisContext)
- parameter.py: Parameter 정보 모델 (ParameterInfo)
"""

from .enums import (
    ColumnRole,
    SourceType,
    DictMatchStatus,
    ConceptCategory,
    TemporalType,
)
from .plan import (
    CohortMetadata,
    SignalMetadata,
    JoinConfig,
    ParsedPlan,
    CohortColumnInfo,
    AnalysisContext,
)
from .parameter import ParameterInfo

__all__ = [
    # Enums
    'ColumnRole',
    'SourceType',
    'DictMatchStatus',
    'ConceptCategory',
    'TemporalType',
    
    # Plan models
    'CohortMetadata',
    'SignalMetadata',
    'JoinConfig',
    'ParsedPlan',
    'CohortColumnInfo',
    'AnalysisContext',
    
    # Parameter models
    'ParameterInfo',
]
