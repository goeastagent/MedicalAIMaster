# shared/data/__init__.py
"""
Data Management Module

execution_plan 기반 데이터 로드 및 관리:
- DataContext: 데이터 로드, 캐싱, 접근 인터페이스

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
"""

from .context import DataContext

__all__ = [
    "DataContext",
]

