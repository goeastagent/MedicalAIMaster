#!/usr/bin/env python
"""
OrchestrationAgent End-to-End 예제
===================================

이 예제는 자연어 쿼리로부터 데이터 분석까지의 전체 파이프라인을 보여줍니다.

파이프라인:
1. 자연어 쿼리 → ExtractionAgent → Execution Plan
2. Execution Plan → DataContext → DataFrame 로드
3. DataFrame + 분석 요청 → AnalysisAgent → 코드 생성 + 실행 → 결과

사전 조건:
- PostgreSQL에 IndexingAgent로 인덱싱된 데이터가 있어야 합니다
- .env 파일에 DB 연결 정보와 LLM API 키가 설정되어 있어야 합니다
"""

import sys
import logging
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def setup_logging(level: str = "INFO"):
    """
    로깅 설정 - 모든 Agent의 로그를 출력
    
    Args:
        level: 로그 레벨 ("DEBUG", "INFO", "WARNING", "ERROR")
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # 로그 포맷 설정
    log_format = "%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s"
    date_format = "%H:%M:%S"
    
    # 기본 설정
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler()]
    )
    
    # 각 모듈별 로거 설정 (원하는 레벨로 조정 가능)
    loggers_config = {
        # OrchestrationAgent
        "OrchestrationAgent": log_level,
        "OrchestrationAgent.orchestrator": log_level,
        
        # ExtractionAgent (LangGraph nodes)
        "ExtractionAgent": log_level,
        "ExtractionAgent.agents": log_level,
        "LangGraph": log_level,  # BaseNode 로거
        "LangGraph.query_understanding": log_level,
        "LangGraph.parameter_resolver": log_level,
        "LangGraph.plan_builder": log_level,
        
        # AnalysisAgent
        "AnalysisAgent": log_level,
        "AnalysisAgent.code_gen": log_level,
        
        # Shared 모듈
        "shared.llm": log_level,
        "shared.llm.client": log_level,
        "shared.data.context": log_level,
        "shared.database": log_level,
        
        # 외부 라이브러리 (너무 verbose하면 WARNING으로)
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
        "openai": logging.WARNING,
        "urllib3": logging.WARNING,
    }
    
    for logger_name, logger_level in loggers_config.items():
        logging.getLogger(logger_name).setLevel(logger_level)


def example_full_pipeline():
    """
    전체 파이프라인 예제 - Orchestrator.run() 사용
    
    가장 간단한 사용법: 쿼리 하나로 모든 것을 처리
    """
    print("=" * 60)
    print("예제 1: 전체 파이프라인 (Orchestrator.run)")
    print("=" * 60)
    
    from OrchestrationAgent.src.orchestrator import Orchestrator
    
    # Orchestrator 생성
    orchestrator = Orchestrator()
    
    # 자연어 쿼리로 전체 파이프라인 실행
    query = "위암 환자의 수술 중 심박수 평균과 표준편차를 구해줘"
    
    print(f"\n📝 Query: {query}\n")
    print("🚀 Running full pipeline...")
    
    result = orchestrator.run(query)
    
    # 결과 출력
    print(f"\n✅ Status: {result.status}")
    print(f"⏱️  Execution time: {result.execution_time_ms:.2f}ms")
    
    if result.status == "success":
        print(f"\n📊 Result:")
        print(f"   {result.result}")
        
        print(f"\n💻 Generated Code:")
        print("-" * 40)
        print(result.generated_code)
        print("-" * 40)
        
        if result.data_summary:
            print(f"\n📈 Data Summary:")
            print(f"   Cases: {result.data_summary.get('cohort', {}).get('total_cases', 'N/A')}")
            print(f"   Parameters: {result.data_summary.get('signals', {}).get('param_keys', [])[:5]}")
    else:
        print(f"\n❌ Error: {result.error_message}")
        print(f"   Stage: {result.error_stage}")
    
    return result


def example_with_existing_plan():
    """
    이미 있는 Execution Plan으로 분석 (ExtractionAgent 스킵)
    
    Plan을 캐싱하거나 수동으로 만든 경우에 유용
    """
    print("\n" + "=" * 60)
    print("예제 2: 기존 Plan으로 분석 (Orchestrator.run_with_plan)")
    print("=" * 60)
    
    from OrchestrationAgent.src.orchestrator import Orchestrator
    from ExtractionAgent.src.facade import ExtractionFacade
    
    # 먼저 ExtractionFacade로 Plan 생성
    extraction = ExtractionFacade()
    plan = extraction.extract("폐암 환자의 혈압 데이터")
    
    print(f"\n📋 Pre-generated Plan:")
    print(f"   Cohort: {plan.get('execution_plan', {}).get('cohort_source', {}).get('file_name', 'N/A')}")
    print(f"   Signal Group: {plan.get('execution_plan', {}).get('signal_source', {}).get('group_name', 'N/A')}")
    
    # Orchestrator로 분석만 실행
    orchestrator = Orchestrator()
    
    result = orchestrator.run_with_plan(
        query="혈압(ABP)의 평균과 최대값을 구해줘",
        execution_plan=plan
    )
    
    print(f"\n✅ Status: {result.status}")
    
    if result.status == "success":
        print(f"📊 Result: {result.result}")
    else:
        print(f"❌ Error: {result.error_message}")
    
    return result


def example_analysis_only():
    """
    데이터가 이미 있을 때 분석만 실행 (Extraction + DataLoad 스킵)
    
    데이터를 직접 준비한 경우에 유용
    """
    print("\n" + "=" * 60)
    print("예제 3: 분석만 실행 (Orchestrator.run_analysis_only)")
    print("=" * 60)
    
    import pandas as pd
    import numpy as np
    
    from OrchestrationAgent.src.orchestrator import Orchestrator
    
    # 테스트용 데이터 생성
    np.random.seed(42)
    
    df = pd.DataFrame({
        'Time': np.arange(0, 100, 0.1),
        'HR': np.random.normal(72, 8, 1000),      # 심박수
        'SpO2': np.random.normal(98, 1, 1000),    # 산소포화도
        'ABP': np.random.normal(90, 15, 1000),    # 혈압
        'caseid': np.repeat(['case1', 'case2', 'case3', 'case4', 'case5'], 200)
    })
    
    cohort = pd.DataFrame({
        'caseid': ['case1', 'case2', 'case3', 'case4', 'case5'],
        'age': [65, 58, 72, 45, 68],
        'sex': ['M', 'F', 'M', 'F', 'M'],
        'diagnosis': ['gastric_cancer', 'lung_cancer', 'gastric_cancer', 'lung_cancer', 'gastric_cancer']
    })
    
    print(f"\n📊 Test Data:")
    print(f"   Signal DataFrame: {df.shape}")
    print(f"   Cohort DataFrame: {cohort.shape}")
    
    # Runtime data 구성
    runtime_data = {
        'df': df,
        'cohort': cohort,
        'case_ids': ['case1', 'case2', 'case3', 'case4', 'case5'],
        'param_keys': ['HR', 'SpO2', 'ABP']
    }
    
    # Orchestrator로 분석 실행
    orchestrator = Orchestrator()
    
    result = orchestrator.run_analysis_only(
        query="성별(sex)에 따른 심박수(HR) 평균을 비교해줘",
        runtime_data=runtime_data
    )
    
    print(f"\n✅ Status: {result.status}")
    print(f"⏱️  Execution time: {result.execution_time_ms:.2f}ms")
    
    if result.status == "success":
        print(f"\n📊 Result:")
        print(f"   {result.result}")
        
        print(f"\n💻 Generated Code:")
        print("-" * 40)
        print(result.generated_code)
        print("-" * 40)
    else:
        print(f"\n❌ Error: {result.error_message}")
    
    return result


def example_multiple_queries():
    """
    여러 쿼리를 순차 실행
    
    동일한 데이터에 대해 여러 분석을 수행할 때 유용
    """
    print("\n" + "=" * 60)
    print("예제 4: 여러 쿼리 순차 실행")
    print("=" * 60)
    
    import pandas as pd
    import numpy as np
    
    from OrchestrationAgent.src.orchestrator import Orchestrator
    
    # 테스트 데이터
    np.random.seed(42)
    runtime_data = {
        'df': pd.DataFrame({
            'Time': np.arange(0, 50, 0.1),
            'HR': np.random.normal(72, 8, 500),
            'SpO2': np.random.normal(98, 1, 500),
        }),
        'case_ids': ['test_case'],
        'param_keys': ['HR', 'SpO2']
    }
    
    orchestrator = Orchestrator()
    
    queries = [
        "HR의 평균값을 구해줘",
        "HR이 80 이상인 구간의 비율을 구해줘",
        "HR과 SpO2의 상관계수를 구해줘",
    ]
    
    results = []
    
    for i, query in enumerate(queries, 1):
        print(f"\n--- Query {i}: {query} ---")
        
        result = orchestrator.run_analysis_only(query, runtime_data)
        results.append(result)
        
        if result.status == "success":
            print(f"✅ Result: {result.result}")
        else:
            print(f"❌ Error: {result.error_message}")
    
    print(f"\n📊 Summary: {sum(1 for r in results if r.status == 'success')}/{len(results)} succeeded")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="OrchestrationAgent End-to-End Examples")
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="로그 레벨 설정 (default: INFO)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="DEBUG 레벨로 상세 로그 출력"
    )
    args = parser.parse_args()
    
    # 로깅 설정
    log_level = "DEBUG" if args.verbose else args.log_level
    setup_logging(log_level)
    
    print("\n" + "=" * 70)
    print("  OrchestrationAgent End-to-End Examples")
    print("=" * 70)
    print(f"  Log Level: {log_level}")
    print("=" * 70)
    
    # 예제 3부터 실행 (DB 연결 없이 테스트 가능)
    example_analysis_only()
    example_multiple_queries()
    
    # DB 연결이 필요한 예제 (주석 해제하여 실행)
    # example_full_pipeline()
    # example_with_existing_plan()
    
    print("\n" + "=" * 70)
    print("  All examples completed!")
    print("=" * 70)
