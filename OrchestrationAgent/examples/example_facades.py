#!/usr/bin/env python
"""
Facade 사용 예제
================

각 Agent의 Facade 인터페이스를 독립적으로 사용하는 방법을 보여줍니다.

Facades:
1. ExtractionFacade - 자연어 쿼리 → Execution Plan
2. DataContext - Execution Plan → DataFrame 로드

Note: AnalysisFacade는 AnalysisAgent로 대체되었습니다.
      → OrchestrationAgent/examples/example_end_to_end.py 참고
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


# =============================================================================
# 예제 1: ExtractionFacade
# =============================================================================

def example_extraction_facade():
    """
    ExtractionFacade 사용 예제
    
    자연어 쿼리를 Execution Plan JSON으로 변환합니다.
    """
    print("=" * 60)
    print("예제 1: ExtractionFacade")
    print("=" * 60)
    
    from ExtractionAgent.src.facade import ExtractionFacade, extract_plan
    
    # 방법 1: 클래스 인스턴스 사용
    print("\n--- 방법 1: ExtractionFacade 클래스 ---")
    
    facade = ExtractionFacade(verbose=False)
    
    # extract() - Plan만 반환
    try:
        plan = facade.extract("위암 환자의 수술 중 심박수 데이터")
        
        print(f"✅ Plan generated:")
        print(f"   Version: {plan.get('version')}")
        print(f"   Agent: {plan.get('agent')}")
        
        exec_plan = plan.get('execution_plan', {})
        if exec_plan.get('cohort_source'):
            print(f"   Cohort file: {exec_plan['cohort_source'].get('file_name')}")
        if exec_plan.get('signal_source'):
            print(f"   Signal group: {exec_plan['signal_source'].get('group_name')}")
            params = exec_plan['signal_source'].get('parameters', [])
            if params:
                print(f"   Parameters: {[p.get('term') for p in params]}")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # 방법 2: 편의 함수 사용
    print("\n--- 방법 2: extract_plan() 편의 함수 ---")
    
    try:
        plan2 = extract_plan("폐암 환자의 혈압 데이터", verbose=False)
        print(f"✅ Plan generated via convenience function")
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # 방법 3: 전체 상태 포함 (디버깅용)
    print("\n--- 방법 3: extract_with_state() ---")
    
    result = facade.extract_with_state("당뇨 환자의 산소포화도")
    
    print(f"   Success: {result.success}")
    print(f"   Execution time: {result.execution_time_seconds:.2f}s")
    print(f"   Has ambiguity: {result.has_ambiguity}")
    
    if result.resolved_parameters:
        print(f"   Resolved parameters:")
        for p in result.resolved_parameters[:3]:
            print(f"      - {p.get('term')}: {p.get('param_keys', [])[:3]}")
    
    # 방법 4: 쿼리 유효성 검사
    print("\n--- 방법 4: validate_query() ---")
    
    validation = facade.validate_query("환자의 체온 데이터")
    print(f"   Valid: {validation['valid']}")
    print(f"   Has ambiguity: {validation['has_ambiguity']}")
    print(f"   Estimated params: {validation['estimated_parameters']}")


# =============================================================================
# 예제 2: DataContext
# =============================================================================

def example_data_context():
    """
    DataContext 사용 예제
    
    Execution Plan을 기반으로 실제 데이터를 로드합니다.
    """
    print("\n" + "=" * 60)
    print("예제 2: DataContext")
    print("=" * 60)
    
    from shared.data.context import DataContext
    from ExtractionAgent.src.facade import ExtractionFacade
    
    # 먼저 Execution Plan 생성
    print("\n--- Step 1: Generate Execution Plan ---")
    
    extraction = ExtractionFacade(verbose=False)
    
    try:
        plan = extraction.extract("심부전 환자의 심박수 데이터")
        print(f"✅ Plan generated")
    except Exception as e:
        print(f"❌ Could not generate plan: {e}")
        print("   Using mock plan for demonstration...")
        plan = None
    
    if plan is None:
        print("\n⚠️  Skipping DataContext example (no plan)")
        return
    
    # DataContext로 데이터 로드
    print("\n--- Step 2: Load Data with DataContext ---")
    
    ctx = DataContext()
    ctx.load_from_plan(plan, preload_cohort=True)
    
    # 요약 정보
    summary = ctx.summary()
    print(f"\n📊 Data Summary:")
    print(f"   Cohort file: {summary['cohort']['file_path']}")
    print(f"   Cohort loaded: {summary['cohort']['loaded']}")
    print(f"   Signal files: {summary['signals']['total_files']}")
    print(f"   Parameters: {summary['signals']['param_keys'][:5]}")
    
    # Cohort 데이터
    print("\n--- Step 3: Get Cohort Data ---")
    
    cohort = ctx.get_cohort()
    if not cohort.empty:
        print(f"   Cohort shape: {cohort.shape}")
        print(f"   Columns: {list(cohort.columns)[:10]}")
        print(f"   Sample:")
        print(cohort.head(3).to_string(index=False))
    
    # Signal 데이터 (특정 케이스)
    print("\n--- Step 4: Get Signal Data ---")
    
    case_ids = ctx.get_case_ids()
    if case_ids:
        signals = ctx.get_signals(caseid=case_ids[0])
        print(f"   Case: {case_ids[0]}")
        print(f"   Signal shape: {signals.shape if not signals.empty else 'N/A'}")
        if not signals.empty:
            print(f"   Columns: {list(signals.columns)}")
    
    # AnalysisAgent용 컨텍스트
    print("\n--- Step 5: Get Execution Context (for AnalysisAgent) ---")
    
    exec_context = ctx.to_execution_context()
    print(f"   Available variables: {list(exec_context['available_variables'].keys())}")
    print(f"   Data schemas: {list(exec_context['data_schemas'].keys())}")
    
    # 통계 계산
    print("\n--- Step 6: Compute Statistics ---")
    
    stats = ctx.compute_statistics(sample_size=5)
    for param, stat in list(stats.items())[:3]:
        if 'mean' in stat:
            print(f"   {param}: mean={stat['mean']:.2f}, std={stat['std']:.2f}")


# =============================================================================
# 예제 3: AnalysisAgent (신규)
# =============================================================================
# 
# AnalysisFacade는 AnalysisAgent로 대체되었습니다.
# 분석 예제는 example_end_to_end.py를 참고하세요.
#
# from OrchestrationAgent.src.orchestrator import Orchestrator
# orchestrator = Orchestrator()
# result = orchestrator.run_analysis_only(query, runtime_data)
#


# =============================================================================
# 예제 3: 전체 통합
# =============================================================================
# 
# 전체 파이프라인 예제는 example_end_to_end.py를 참고하세요.
#


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  Facade Usage Examples")
    print("=" * 70)
    
    # DB 연결이 필요한 예제
    example_extraction_facade()
    example_data_context()
    
    # AnalysisAgent 예제는 example_end_to_end.py 참고
    
    print("\n" + "=" * 70)
    print("  All examples completed!")
    print("=" * 70)
