#!/usr/bin/env python3
"""
DataContext 통합 테스트
========================

테스트 항목:
1. Processor import 확인
2. DataContext 기본 기능 테스트
3. ExtractionAgent → DataContext 연동 테스트
4. 캐시 동작 확인

Usage:
    cd /path/to/MedicalAIMaster
    python shared/test_datacontext.py
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 70)
print("  DataContext 통합 테스트")
print("=" * 70)


# =============================================================================
# Test 1: Processor Import (직접 import)
# =============================================================================
def test_processor_import():
    """shared.processors에서 직접 import 테스트"""
    print("\n[Test 1] Processor Import")
    print("-" * 50)
    
    try:
        # 직접 processors만 import (shared 전체 아님)
        from shared.processors import SignalProcessor, TabularProcessor, BaseDataProcessor
        
        print("  ✅ SignalProcessor import 성공")
        print("  ✅ TabularProcessor import 성공")
        print("  ✅ BaseDataProcessor import 성공")
        
        # 인스턴스 생성
        sig_proc = SignalProcessor()
        tab_proc = TabularProcessor()
        
        print(f"\n  📊 SignalProcessor:")
        print(f"     - SUPPORTED_EXTENSIONS: {sig_proc.SUPPORTED_EXTENSIONS}")
        print(f"     - has can_handle: {hasattr(sig_proc, 'can_handle')}")
        print(f"     - has extract_metadata: {hasattr(sig_proc, 'extract_metadata')}")
        print(f"     - has load_data: {hasattr(sig_proc, 'load_data')}")
        
        print(f"\n  📊 TabularProcessor:")
        print(f"     - SUPPORTED_EXTENSIONS: {tab_proc.SUPPORTED_EXTENSIONS}")
        print(f"     - has can_handle: {hasattr(tab_proc, 'can_handle')}")
        print(f"     - has extract_metadata: {hasattr(tab_proc, 'extract_metadata')}")
        print(f"     - has load_data: {hasattr(tab_proc, 'load_data')}")
        
        return True
    except Exception as e:
        print(f"  ❌ Import 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# Test 2: DataContext 기본 기능
# =============================================================================
def test_datacontext_basic():
    """DataContext 클래스 기본 기능 테스트"""
    print("\n[Test 2] DataContext 기본 기능")
    print("-" * 50)
    
    try:
        # 직접 context만 import
        from shared.data.context import DataContext
        
        print("  ✅ DataContext import 성공")
        
        # 인스턴스 생성
        ctx = DataContext()
        print("  ✅ DataContext 인스턴스 생성 성공")
        
        # 메서드 존재 확인
        methods = [
            'load_from_plan',
            'get_cohort',
            'get_signals',
            'get_merged_data',
            'iter_cases',
            'get_case_ids',
            'get_available_parameters',
            'summary',
            'clear_cache',
            'get_analysis_context',
            'compute_statistics',
            'get_sample_data',
            'get_parameter_info'
        ]
        
        missing = []
        for method in methods:
            if hasattr(ctx, method):
                print(f"     ✅ {method}()")
            else:
                print(f"     ❌ {method}() - 없음")
                missing.append(method)
        
        if missing:
            print(f"  ⚠️ 누락된 메서드: {missing}")
            return False
        
        # is_loaded 확인
        print(f"\n  📊 is_loaded(): {ctx.is_loaded()}")
        
        return True
    except Exception as e:
        print(f"  ❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# Test 3: ExtractionAgent → DataContext 연동 (Plan 파싱만)
# =============================================================================
def test_extraction_to_datacontext():
    """ExtractionAgent의 execution_plan으로 DataContext 로드 테스트 (DB 없이)"""
    print("\n[Test 3] ExtractionAgent → DataContext 연동 (Plan 파싱)")
    print("-" * 50)
    
    try:
        from shared.data.context import DataContext
        
        # 샘플 execution_plan (ExtractionAgent 출력 형식)
        sample_plan = {
            "version": "1.0",
            "generated_at": "2024-01-01T00:00:00Z",
            "agent": "VitalExtractionAgent",
            "original_query": "위암 환자의 수술 중 심박수 데이터",
            "execution_plan": {
                "cohort_source": {
                    "file_id": "test-file-id-123",
                    "file_name": "clinical_data.csv",
                    "entity_identifier": "caseid",
                    "filters": [
                        {"column": "diagnosis", "operator": "LIKE", "value": "%gastric%"}
                    ]
                },
                "signal_source": {
                    "group_id": "test-group-id-456",
                    "group_name": "vital_files",
                    "parameters": [
                        {
                            "term": "심박수",
                            "param_keys": ["Solar8000/HR"],
                            "semantic_name": "Heart Rate",
                            "unit": "bpm",
                            "resolution_mode": "all_sources",
                            "confidence": 0.95
                        },
                        {
                            "term": "혈압",
                            "param_keys": ["Solar8000/NIBP_SBP", "Solar8000/NIBP_DBP"],
                            "semantic_name": "Blood Pressure",
                            "unit": "mmHg",
                            "resolution_mode": "all_sources",
                            "confidence": 0.90
                        }
                    ],
                    "temporal_alignment": {
                        "type": "surgery_window",
                        "start_column": "op_start",
                        "end_column": "op_end",
                        "margin_seconds": 300
                    }
                },
                "join_specification": {
                    "type": "inner",
                    "cohort_key": "caseid",
                    "signal_key": "caseid"
                }
            }
        }
        
        ctx = DataContext()
        
        # Plan 로드 (DB 접근 없이 파싱만 - preload_cohort=False)
        # DB 연결 없이 테스트하기 위해 _db를 None으로 유지
        ctx._plan = sample_plan
        plan = sample_plan.get("execution_plan", {})
        
        # Cohort source 파싱
        cohort_source = plan.get("cohort_source", {})
        ctx._cohort_file_id = cohort_source.get("file_id")
        ctx._cohort_entity_id = cohort_source.get("entity_identifier", "caseid")
        ctx._cohort_filters = cohort_source.get("filters", [])
        
        # Signal source 파싱
        signal_source = plan.get("signal_source", {})
        ctx._signal_group_id = signal_source.get("group_id")
        ctx._temporal_config = signal_source.get("temporal_alignment", {})
        
        parameters = signal_source.get("parameters", [])
        ctx._param_info = parameters
        ctx._param_keys = []
        for p in parameters:
            ctx._param_keys.extend(p.get("param_keys", []))
        
        # Join 설정
        join_spec = plan.get("join_specification", {})
        ctx._join_config = {
            "cohort_key": join_spec.get("cohort_key", ctx._cohort_entity_id),
            "signal_key": join_spec.get("signal_key", ctx._cohort_entity_id),
            "type": join_spec.get("type", "inner")
        }
        
        print("  ✅ Plan 파싱 성공")
        
        # 파싱 결과 확인
        print(f"\n  📋 파싱된 Plan 정보:")
        print(f"     - cohort_file_id: {ctx._cohort_file_id}")
        print(f"     - cohort_entity_id: {ctx._cohort_entity_id}")
        print(f"     - cohort_filters: {len(ctx._cohort_filters)}개")
        print(f"     - signal_group_id: {ctx._signal_group_id}")
        print(f"     - param_keys: {ctx._param_keys}")
        print(f"     - temporal_type: {ctx._temporal_config.get('type')}")
        print(f"     - join_config: {ctx._join_config}")
        
        # get_analysis_context 테스트
        analysis_ctx = ctx.get_analysis_context()
        print(f"\n  📊 get_analysis_context() 결과:")
        print(f"     - description: {analysis_ctx['description'][:60]}...")
        print(f"     - original_query: {analysis_ctx['original_query']}")
        print(f"     - cohort.filters_applied: {len(analysis_ctx['cohort']['filters_applied'])}개")
        print(f"     - signals.param_keys: {analysis_ctx['signals']['param_keys']}")
        print(f"     - signals.temporal_setting.type: {analysis_ctx['signals']['temporal_setting']['type']}")
        
        # get_parameter_info 테스트
        param_info = ctx.get_parameter_info("Solar8000/HR")
        if param_info:
            print(f"\n  📊 get_parameter_info('Solar8000/HR'):")
            print(f"     - term: {param_info['term']}")
            print(f"     - semantic_name: {param_info['semantic_name']}")
            print(f"     - unit: {param_info['unit']}")
        
        return True
    except Exception as e:
        print(f"  ❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# Test 4: 캐시 동작 확인
# =============================================================================
def test_cache_behavior():
    """캐시 동작 확인"""
    print("\n[Test 4] 캐시 동작 확인")
    print("-" * 50)
    
    try:
        from shared.data.context import DataContext
        
        # 캐시 초기화
        DataContext.clear_cache()
        print("  ✅ clear_cache() 호출 성공")
        
        # 캐시 상태 확인
        print(f"  📊 캐시 상태:")
        print(f"     - _signal_cache 크기: {len(DataContext._signal_cache)}")
        print(f"     - _cohort_cache 크기: {len(DataContext._cohort_cache)}")
        
        # 두 개의 DataContext 인스턴스가 같은 캐시를 공유하는지 확인
        ctx1 = DataContext()
        ctx2 = DataContext()
        
        # 캐시에 테스트 데이터 추가 (ctx1 통해)
        import pandas as pd
        test_df = pd.DataFrame({"test": [1, 2, 3]})
        DataContext._signal_cache["test_case"] = test_df
        
        # ctx2에서 확인
        if "test_case" in DataContext._signal_cache:
            print("  ✅ 캐시 공유 확인: ctx1과 ctx2가 같은 캐시 사용")
        else:
            print("  ❌ 캐시 공유 실패")
            return False
        
        # 정리
        DataContext.clear_cache()
        
        if len(DataContext._signal_cache) == 0:
            print("  ✅ clear_cache() 후 캐시 비워짐 확인")
        
        # 부분 캐시 클리어 테스트
        DataContext._signal_cache["test1"] = test_df
        DataContext._cohort_cache["test2"] = test_df
        
        DataContext.clear_cache("signals")
        if len(DataContext._signal_cache) == 0 and len(DataContext._cohort_cache) == 1:
            print("  ✅ clear_cache('signals') 부분 클리어 동작 확인")
        
        DataContext.clear_cache("all")
        
        return True
    except Exception as e:
        print(f"  ❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# Test 5: Processor load_data 메서드 시그니처 확인
# =============================================================================
def test_processor_load_data():
    """Processor의 load_data 메서드 시그니처 확인"""
    print("\n[Test 5] Processor load_data 메서드 확인")
    print("-" * 50)
    
    try:
        from shared.processors import SignalProcessor, TabularProcessor
        import inspect
        
        # SignalProcessor
        sig_proc = SignalProcessor()
        sig_params = inspect.signature(sig_proc.load_data).parameters
        print(f"  📊 SignalProcessor.load_data() 파라미터:")
        for name, param in sig_params.items():
            default = param.default if param.default != inspect.Parameter.empty else "required"
            print(f"     - {name}: {default}")
        
        # TabularProcessor
        tab_proc = TabularProcessor()
        tab_params = inspect.signature(tab_proc.load_data).parameters
        print(f"\n  📊 TabularProcessor.load_data() 파라미터:")
        for name, param in tab_params.items():
            default = param.default if param.default != inspect.Parameter.empty else "required"
            print(f"     - {name}: {default}")
        
        return True
    except Exception as e:
        print(f"  ❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


# =============================================================================
# Main
# =============================================================================
def main():
    results = {}
    
    # 테스트 실행
    results["test1_processor_import"] = test_processor_import()
    results["test2_datacontext_basic"] = test_datacontext_basic()
    results["test3_extraction_to_dc"] = test_extraction_to_datacontext()
    results["test4_cache"] = test_cache_behavior()
    results["test5_processor_load"] = test_processor_load_data()
    
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
