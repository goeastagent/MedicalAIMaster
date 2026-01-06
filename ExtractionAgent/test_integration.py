#!/usr/bin/env python3
"""
ExtractionAgent + DataContext 통합 테스트
==========================================

ExtractionAgent가 생성한 execution_plan을 DataContext가
올바르게 파싱하고 처리할 수 있는지 확인합니다.

Usage:
    cd /path/to/MedicalAIMaster
    python ExtractionAgent/test_integration.py
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "ExtractionAgent"))

print("=" * 70)
print("  ExtractionAgent + DataContext 통합 테스트")
print("=" * 70)


def test_pipeline_to_datacontext():
    """ExtractionAgent 파이프라인 실행 후 DataContext로 전달 테스트"""
    print("\n[Test] ExtractionAgent → DataContext 연동")
    print("-" * 50)
    
    try:
        # 1. ExtractionAgent 파이프라인 빌드
        print("\n  📦 ExtractionAgent 파이프라인 빌드 중...")
        from src.agents.graph import build_agent
        
        agent = build_agent()
        print("  ✅ 파이프라인 빌드 성공")
        
        # 2. 테스트 쿼리 실행
        test_query = "위암 환자의 수술 중 심박수와 혈압 데이터를 추출해줘"
        print(f"\n  🔍 테스트 쿼리: \"{test_query}\"")
        
        initial_state = {
            "user_query": test_query,
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
        
        print("  🚀 파이프라인 실행 중...")
        result = agent.invoke(initial_state)
        print("  ✅ 파이프라인 실행 완료")
        
        # 3. execution_plan 확인
        execution_plan = result.get("execution_plan")
        if not execution_plan:
            print("  ❌ execution_plan이 없습니다!")
            return False
        
        print(f"\n  📋 Execution Plan 생성됨:")
        print(f"     - version: {execution_plan.get('version')}")
        print(f"     - agent: {execution_plan.get('agent')}")
        
        plan = execution_plan.get("execution_plan", {})
        cohort = plan.get("cohort_source", {})
        signals = plan.get("signal_source", {})
        
        print(f"     - cohort_source.file_id: {cohort.get('file_id')}")
        print(f"     - cohort_source.filters: {len(cohort.get('filters', []))}개")
        print(f"     - signal_source.group_id: {signals.get('group_id')}")
        print(f"     - signal_source.parameters: {len(signals.get('parameters', []))}개")
        
        # 4. DataContext에 Plan 로드
        print("\n  📦 DataContext에 Plan 로드 중...")
        from shared.data.context import DataContext
        
        ctx = DataContext()
        ctx.load_from_plan(execution_plan, preload_cohort=False)
        
        if ctx.is_loaded():
            print("  ✅ DataContext Plan 로드 성공")
        else:
            print("  ❌ DataContext Plan 로드 실패")
            return False
        
        # 5. DataContext 상태 확인
        print(f"\n  📊 DataContext 상태:")
        print(f"     - cohort_file_id: {ctx._cohort_file_id}")
        print(f"     - signal_group_id: {ctx._signal_group_id}")
        print(f"     - param_keys: {ctx._param_keys}")
        print(f"     - temporal_config: {ctx._temporal_config}")
        print(f"     - cohort_filters: {ctx._cohort_filters}")
        
        # 6. Analysis Context 생성
        print("\n  📋 Analysis Context 생성...")
        analysis_ctx = ctx.get_analysis_context()
        
        print(f"     - description: {analysis_ctx['description'][:80]}...")
        print(f"     - original_query: {analysis_ctx['original_query']}")
        print(f"     - cohort.total_cases: {analysis_ctx['cohort']['total_cases']}")
        print(f"     - cohort.entity_identifier: {analysis_ctx['cohort']['entity_identifier']}")
        print(f"     - signals.param_keys: {len(analysis_ctx['signals']['param_keys'])}개")
        print(f"     - signals.temporal_setting.type: {analysis_ctx['signals']['temporal_setting']['type']}")
        
        # 7. Parameter Info 확인
        print("\n  📋 Parameter Info 확인...")
        available_params = ctx.get_available_parameters()
        print(f"     - 사용 가능한 파라미터: {available_params}")
        
        for pk in available_params[:2]:  # 처음 2개만
            info = ctx.get_parameter_info(pk)
            if info:
                print(f"     - {pk}:")
                print(f"       term: {info.get('term')}")
                print(f"       semantic_name: {info.get('semantic_name')}")
        
        # 8. Validation 결과 확인
        validation = result.get("validation", {})
        print(f"\n  📊 Validation:")
        print(f"     - confidence: {validation.get('confidence', 0):.2f}")
        print(f"     - warnings: {validation.get('warnings', [])}")
        
        print("\n  ✅ 통합 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"\n  ❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_datacontext_summary():
    """DataContext summary 메서드 테스트 (DB 없이 파싱만)"""
    print("\n[Test] DataContext Summary (파싱 전용)")
    print("-" * 50)
    
    try:
        from shared.data.context import DataContext
        
        # 샘플 plan으로 테스트 (DB 접근 없이)
        sample_plan = {
            "version": "1.0",
            "original_query": "테스트 쿼리",
            "execution_plan": {
                "cohort_source": {
                    "file_id": "00000000-0000-0000-0000-000000000001",  # Valid UUID format
                    "filters": [{"column": "dept", "operator": "=", "value": "GS"}]
                },
                "signal_source": {
                    "group_id": "00000000-0000-0000-0000-000000000002",  # Valid UUID format
                    "parameters": [
                        {"term": "HR", "param_keys": ["Solar8000/HR"], "semantic_name": "Heart Rate", "unit": "bpm"}
                    ],
                    "temporal_alignment": {
                        "type": "surgery_window",
                        "margin_seconds": 300
                    }
                }
            }
        }
        
        ctx = DataContext()
        
        # 직접 파싱 (DB 접근 없이)
        ctx._plan = sample_plan
        plan = sample_plan.get("execution_plan", {})
        
        cohort_source = plan.get("cohort_source", {})
        ctx._cohort_file_id = cohort_source.get("file_id")
        ctx._cohort_entity_id = cohort_source.get("entity_identifier", "caseid")
        ctx._cohort_filters = cohort_source.get("filters", [])
        
        signal_source = plan.get("signal_source", {})
        ctx._signal_group_id = signal_source.get("group_id")
        ctx._temporal_config = signal_source.get("temporal_alignment", {})
        
        parameters = signal_source.get("parameters", [])
        ctx._param_info = parameters
        ctx._param_keys = []
        for p in parameters:
            ctx._param_keys.extend(p.get("param_keys", []))
        
        ctx._loaded_at = None
        
        summary = ctx.summary()
        print(f"\n  📊 Summary:")
        print(f"     - loaded_at: {summary['loaded_at']}")
        print(f"     - cohort.file_id: {summary['cohort']['file_id']}")
        print(f"     - cohort.filters_count: {summary['cohort']['filters_count']}")
        print(f"     - cohort.loaded: {summary['cohort']['loaded']}")
        print(f"     - signals.group_id: {summary['signals']['group_id']}")
        print(f"     - signals.param_keys: {summary['signals']['param_keys']}")
        print(f"     - signals.temporal_type: {summary['signals']['temporal_type']}")
        
        print("\n  ✅ Summary 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"\n  ❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    results = {}
    
    # 테스트 실행
    results["test_pipeline_to_datacontext"] = test_pipeline_to_datacontext()
    results["test_datacontext_summary"] = test_datacontext_summary()
    
    # 결과 요약
    print("\n" + "=" * 70)
    print("  테스트 결과 요약")
    print("=" * 70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {name}")
    
    print(f"\n  총 {passed}/{total} 테스트 통과")
    print("=" * 70)
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

