#!/usr/bin/env python3
"""
OrchestrationAgent 전체 파이프라인 테스트
==========================================

ExtractionAgent → DataContext → CodeGen 전체 흐름 테스트

Usage:
    cd /path/to/MedicalAIMaster
    python OrchestrationAgent/test_full_pipeline.py

필요 조건:
    - LLM API 키 설정 (OPENAI_API_KEY 또는 ANTHROPIC_API_KEY)
    - PostgreSQL DB 연결
    - Neo4j DB 연결 (시그널 매핑용)
    - Indexing 완료된 상태
"""

import sys
import time
from pathlib import Path
from typing import Dict, Any, List

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def print_header(title: str):
    """섹션 헤더 출력"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_subheader(title: str):
    """서브 헤더 출력"""
    print(f"\n  📌 {title}")
    print("  " + "-" * 50)


def check_prerequisites() -> bool:
    """필수 조건 확인"""
    print_header("필수 조건 확인")
    
    all_ok = True
    
    # 1. LLM API 키 확인
    print_subheader("LLM API 키")
    try:
        from shared.config import LLMConfig
        has_openai = bool(LLMConfig.OPENAI_API_KEY)
        has_anthropic = bool(LLMConfig.ANTHROPIC_API_KEY)
        
        if has_openai or has_anthropic:
            print(f"     ✅ OpenAI: {'설정됨' if has_openai else '미설정'}")
            print(f"     ✅ Anthropic: {'설정됨' if has_anthropic else '미설정'}")
        else:
            print("     ❌ LLM API 키가 설정되지 않았습니다")
            all_ok = False
    except Exception as e:
        print(f"     ❌ LLM 설정 확인 실패: {e}")
        all_ok = False
    
    # 2. DB 연결 확인
    print_subheader("Database 연결")
    try:
        from shared.database.connection import get_db_manager
        db = get_db_manager()
        
        # PostgreSQL 연결 테스트
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        print("     ✅ PostgreSQL 연결 성공")
        
    except Exception as e:
        print(f"     ❌ PostgreSQL 연결 실패: {e}")
        all_ok = False
    
    try:
        # Neo4j 연결 테스트 (선택사항)
        from shared.database.neo4j_connection import get_neo4j_manager
        neo4j = get_neo4j_manager()
        
        with neo4j.driver.session() as session:
            session.run("RETURN 1")
        print("     ✅ Neo4j 연결 성공")
        
    except Exception as e:
        print(f"     ⚠️ Neo4j 연결 실패 (선택사항): {type(e).__name__}")
    
    # 3. Indexing 상태 확인
    print_subheader("Indexing 상태")
    try:
        conn = db.get_connection()
        conn.rollback()  # 이전 트랜잭션 정리
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM file_catalog")
        file_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM parameter")
        param_count = cursor.fetchone()[0]
        
        cursor.close()
        
        print(f"     - file_catalog: {file_count} files")
        print(f"     - parameter: {param_count} parameters")
        
        if file_count == 0:
            print("     ⚠️ 파일이 인덱싱되지 않았습니다")
        if param_count == 0:
            print("     ⚠️ 파라미터가 인덱싱되지 않았습니다")
            print("     → 전체 파이프라인 테스트가 불완전할 수 있습니다")
        
    except Exception as e:
        print(f"     ⚠️ Indexing 상태 확인 실패: {e}")
    
    # 3. 모듈 임포트 확인
    print_subheader("모듈 임포트")
    try:
        from OrchestrationAgent.src import Orchestrator
        print("     ✅ Orchestrator 임포트 성공")
    except Exception as e:
        print(f"     ❌ Orchestrator 임포트 실패: {e}")
        all_ok = False
    
    try:
        from ExtractionAgent.src.agents.graph import build_agent
        print("     ✅ ExtractionAgent 임포트 성공")
    except Exception as e:
        print(f"     ❌ ExtractionAgent 임포트 실패: {e}")
        all_ok = False
    
    try:
        from shared.data.context import DataContext
        print("     ✅ DataContext 임포트 성공")
    except Exception as e:
        print(f"     ❌ DataContext 임포트 실패: {e}")
        all_ok = False
    
    return all_ok


def test_extraction_only(query: str) -> Dict[str, Any]:
    """ExtractionAgent만 테스트"""
    print_subheader(f"ExtractionAgent 테스트")
    print(f"     Query: \"{query}\"")
    
    try:
        # ExtractionAgent를 sys.path 앞에 추가 (src.agents import 위해)
        extraction_path = str(project_root / "ExtractionAgent")
        if extraction_path not in sys.path:
            sys.path.insert(0, extraction_path)
        
        # src.agents로 import (ExtractionAgent 내부 import 경로와 일치)
        from src.agents.graph import build_agent
        
        agent = build_agent()
        
        initial_state = {
            "user_query": query,
            "schema_context": None,
            "intent": None,
            "requested_parameters": None,
            "cohort_filters": None,
            "temporal_context": None,
            "resolved_parameters": None,
            "ambiguities": None,
            "has_ambiguity": None,
            "execution_plan": None,
            "validation": None,
            "logs": [],
            "error_message": None
        }
        
        start_time = time.time()
        result = agent.invoke(initial_state)
        elapsed = (time.time() - start_time) * 1000
        
        execution_plan = result.get("execution_plan")
        
        if execution_plan:
            print(f"     ✅ Execution Plan 생성 완료 ({elapsed:.0f}ms)")
            
            plan = execution_plan.get("execution_plan", {})
            cohort = plan.get("cohort_source") or {}
            signals = plan.get("signal_source") or {}
            
            cohort_id = cohort.get('file_id', 'N/A')
            signal_id = signals.get('group_id', 'N/A')
            
            print(f"        - cohort_file_id: {cohort_id[:8] if cohort_id and cohort_id != 'N/A' else 'N/A'}...")
            print(f"        - filters: {len(cohort.get('filters', []))}개")
            print(f"        - signal_group_id: {signal_id[:8] if signal_id and signal_id != 'N/A' else 'N/A'}...")
            print(f"        - parameters: {len(signals.get('parameters', []))}개")
            
            # Validation 체크
            validation = result.get("validation", {})
            confidence = validation.get("confidence", 0)
            warnings = validation.get("warnings", [])
            
            if confidence < 0.5 or not cohort or not signals:
                print(f"\n     ⚠️ Plan이 불완전합니다 (confidence: {confidence:.2f})")
                if warnings:
                    for w in warnings[:3]:
                        print(f"        - {w}")
                
                # 불완전한 plan이지만 구조는 생성됨
                return {"success": False, "plan": execution_plan, "result": result, "error": "Incomplete plan"}
            
            return {"success": True, "plan": execution_plan, "result": result}
        else:
            error = result.get("error_message", "Unknown error")
            print(f"     ❌ Extraction 실패: {error}")
            return {"success": False, "error": error}
            
    except Exception as e:
        print(f"     ❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def test_data_load(execution_plan: Dict[str, Any]) -> Dict[str, Any]:
    """DataContext 로드 테스트"""
    print_subheader("DataContext 로드 테스트")
    
    try:
        from shared.data.context import DataContext
        
        ctx = DataContext()
        
        start_time = time.time()
        ctx.load_from_plan(execution_plan, preload_cohort=True)
        elapsed = (time.time() - start_time) * 1000
        
        if ctx.is_loaded():
            print(f"     ✅ DataContext 로드 완료 ({elapsed:.0f}ms)")
            
            # Cohort 데이터
            cohort = ctx.get_cohort()
            if cohort is not None:
                print(f"        - Cohort: {len(cohort)} rows")
            
            # Signal 파일 정보
            case_ids = ctx.get_case_ids()
            print(f"        - Case IDs: {len(case_ids)}개")
            
            # 사용 가능한 파라미터
            params = ctx.get_available_parameters()
            print(f"        - Parameters: {params}")
            
            return {
                "success": True,
                "context": ctx,
                "case_count": len(case_ids),
                "param_keys": params
            }
        else:
            print("     ❌ DataContext 로드 실패")
            return {"success": False, "error": "Load failed"}
            
    except Exception as e:
        print(f"     ❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def test_full_orchestration(query: str) -> Dict[str, Any]:
    """전체 Orchestration 테스트"""
    print_subheader(f"전체 파이프라인 테스트")
    print(f"     Query: \"{query}\"")
    
    try:
        from OrchestrationAgent.src import Orchestrator
        from OrchestrationAgent.src.config import OrchestratorConfig
        
        config = OrchestratorConfig(
            max_retries=2,
            timeout_seconds=60
        )
        
        orch = Orchestrator(config=config)
        
        start_time = time.time()
        result = orch.run(query)
        elapsed = (time.time() - start_time) * 1000
        
        print(f"\n     📊 결과:")
        print(f"        - Status: {result.status}")
        print(f"        - Time: {elapsed:.0f}ms")
        
        if result.status == "success":
            print(f"        - Result: {result.result}")
            print(f"\n     📝 Generated Code:")
            if result.generated_code:
                for line in result.generated_code.split('\n')[:10]:
                    print(f"        {line}")
                if len(result.generated_code.split('\n')) > 10:
                    print("        ...")
            
            return {"success": True, "result": result}
        else:
            print(f"        - Error Stage: {result.error_stage}")
            print(f"        - Error: {result.error_message}")
            return {"success": False, "result": result}
            
    except Exception as e:
        print(f"     ❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def test_analysis_with_loaded_data(
    query: str, 
    ctx, 
    analysis_query: str
) -> Dict[str, Any]:
    """로드된 데이터로 분석 테스트"""
    print_subheader(f"분석 테스트 (CodeGen)")
    print(f"     Query: \"{analysis_query}\"")
    
    try:
        from OrchestrationAgent.src import Orchestrator
        
        # DataContext에서 runtime_data 준비
        case_ids = ctx.get_case_ids()
        
        if not case_ids:
            print("     ❌ 케이스가 없습니다")
            return {"success": False, "error": "No cases"}
        
        # 첫 번째 케이스의 시그널 로드
        first_case = case_ids[0]
        signals = ctx.get_signals(first_case)
        cohort = ctx.get_cohort()
        
        if signals is None or signals.empty:
            print(f"     ⚠️ Case {first_case}의 시그널이 없습니다")
            return {"success": False, "error": "No signals"}
        
        print(f"        - 사용 케이스: {first_case}")
        print(f"        - 시그널 shape: {signals.shape}")
        
        runtime_data = {
            'df': signals,
            'cohort': cohort,
            'case_ids': case_ids,
            'param_keys': ctx.get_available_parameters()
        }
        
        orch = Orchestrator()
        
        start_time = time.time()
        result = orch.run_analysis_only(
            query=analysis_query,
            runtime_data=runtime_data,
            max_retries=2
        )
        elapsed = (time.time() - start_time) * 1000
        
        print(f"\n     📊 분석 결과:")
        print(f"        - Status: {result.status}")
        print(f"        - Time: {elapsed:.0f}ms")
        
        if result.status == "success":
            print(f"        - Result: {result.result}")
            return {"success": True, "result": result}
        else:
            print(f"        - Error: {result.error_message}")
            return {"success": False, "result": result}
            
    except Exception as e:
        print(f"     ❌ 에러: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def run_interactive_test():
    """인터랙티브 테스트 모드"""
    print_header("인터랙티브 테스트 모드")
    
    from OrchestrationAgent.src import Orchestrator
    
    orch = Orchestrator()
    
    print("\n  명령어:")
    print("    - 자연어 질의 입력 → 전체 파이프라인 실행")
    print("    - 'q' 또는 'quit' → 종료")
    print("    - 'help' → 도움말")
    
    while True:
        print("\n" + "-" * 50)
        query = input("  Query> ").strip()
        
        if not query:
            continue
        
        if query.lower() in ['q', 'quit', 'exit']:
            print("  👋 종료합니다.")
            break
        
        if query.lower() == 'help':
            print("\n  예시 질의:")
            print("    - 위암 환자의 심박수 평균을 구해줘")
            print("    - 수술 중 혈압이 90 이하인 구간의 비율")
            print("    - HR과 SpO2의 상관관계를 분석해줘")
            continue
        
        result = orch.run(query)
        
        print(f"\n  📊 결과:")
        print(f"     Status: {result.status}")
        
        if result.status == "success":
            print(f"     Result: {result.result}")
            if result.generated_code:
                print(f"\n  📝 코드:")
                for line in result.generated_code.split('\n'):
                    print(f"     {line}")
        else:
            print(f"     Error: {result.error_message}")


def main():
    """메인 테스트 실행"""
    print_header("OrchestrationAgent 전체 파이프라인 테스트")
    
    # 1. 필수 조건 확인
    if not check_prerequisites():
        print("\n  ❌ 필수 조건이 충족되지 않았습니다. 테스트를 중단합니다.")
        return False
    
    results = {}
    
    # 2. 테스트 쿼리 정의
    test_queries = [
        # (extraction_query, analysis_query)
        ("위암 환자의 수술 중 심박수 데이터를 추출해줘", "심박수의 평균을 구해줘"),
        ("전체 환자의 혈압 데이터", "혈압이 90 이하인 비율"),
    ]
    
    # 3. 단계별 테스트
    for i, (extract_query, analyze_query) in enumerate(test_queries, 1):
        print_header(f"테스트 케이스 #{i}")
        print(f"  Extraction: \"{extract_query}\"")
        print(f"  Analysis: \"{analyze_query}\"")
        
        # Step 1: Extraction
        extract_result = test_extraction_only(extract_query)
        results[f"case{i}_extraction"] = extract_result["success"]
        
        if not extract_result["success"]:
            print(f"\n  ⚠️ Extraction 실패, 다음 케이스로...")
            continue
        
        # Step 2: Data Load
        load_result = test_data_load(extract_result["plan"])
        results[f"case{i}_data_load"] = load_result["success"]
        
        if not load_result["success"]:
            print(f"\n  ⚠️ Data Load 실패, 다음 케이스로...")
            continue
        
        # Step 3: Analysis
        analysis_result = test_analysis_with_loaded_data(
            extract_query,
            load_result["context"],
            analyze_query
        )
        results[f"case{i}_analysis"] = analysis_result["success"]
    
    # 4. 전체 파이프라인 테스트 (한 번에)
    print_header("전체 파이프라인 통합 테스트")
    full_result = test_full_orchestration(
        "위암 환자의 수술 중 심박수 평균을 계산해줘"
    )
    results["full_pipeline"] = full_result["success"]
    
    # 5. 결과 요약
    print_header("테스트 결과 요약")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {status} - {name}")
    
    print(f"\n  총 {passed}/{total} 테스트 통과")
    
    # 6. 인터랙티브 모드 제안
    print("\n" + "-" * 70)
    try:
        response = input("  인터랙티브 테스트 모드를 실행하시겠습니까? (y/n): ").strip().lower()
        
        if response == 'y':
            run_interactive_test()
    except EOFError:
        # 비대화형 모드에서는 스킵
        print("  (비대화형 모드 - 인터랙티브 테스트 스킵)")
        pass
    
    print_header("테스트 완료")
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

