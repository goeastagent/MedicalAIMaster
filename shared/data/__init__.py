# shared/data/__init__.py
"""
Data Management Module

execution_plan 기반 데이터 로드 및 관리:
- DataContext: 데이터 로드, 캐싱, 접근 인터페이스
- PlanParser: Execution Plan JSON 파싱

사용 예시:
    from shared.data import DataContext
    
    ctx = DataContext()
    ctx.load_from_plan(execution_plan)
    
    # 데이터 접근
    cohort_df = ctx.get_cohort()
    signals_df = ctx.get_signals(caseid="1234")
    merged_df = ctx.get_merged_data()
    
    # AnalysisAgent용 컨텍스트
    analysis_ctx = ctx.get_analysis_context()
    stats = ctx.compute_statistics()
    
    # Plan만 파싱 (데이터 로드 없이)
    from shared.data import PlanParser
    parser = PlanParser()
    parsed = parser.parse(execution_plan)
"""

from .context import DataContext
from .plan_parser import PlanParser
from .analysis_context import AnalysisContextBuilder

# Re-export models from shared.models for convenience
from shared.models.plan import (
    ParsedPlan,
    CohortMetadata,
    SignalMetadata,
    JoinConfig,
    AnalysisContext,
)

__all__ = [
    # Main context
    "DataContext",
    
    # Parsers/Builders
    "PlanParser",
    "AnalysisContextBuilder",
    
    # Models (re-exported from shared.models)
    "ParsedPlan",
    "CohortMetadata",
    "SignalMetadata",
    "JoinConfig",
    "AnalysisContext",
]

