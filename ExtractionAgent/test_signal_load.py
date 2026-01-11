#!/usr/bin/env python
"""
Signal 데이터 로드 테스트 스크립트

이 스크립트는:
1. ExtractionAgent를 통해 "전체 signal 데이터를 로드해줘" 쿼리 처리
2. DataContext에 execution plan 로드
3. 실제 signal 데이터 로드
4. 로드된 데이터 검증 및 출력
"""

import sys
import os
import time
from pathlib import Path

# 프로젝트 루트를 PYTHONPATH에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def print_header(text: str, char: str = "="):
    """헤더 출력"""
    print(f"\n{char * 70}")
    print(f"  {text}")
    print(f"{char * 70}\n")


def print_subheader(text: str):
    """서브헤더 출력"""
    print(f"\n{'─' * 70}")
    print(f"  {text}")
    print(f"{'─' * 70}\n")


def main():
    print_header("Signal 데이터 로드 테스트")
    
    # =========================================================================
    # Step 1: ExtractionAgent 파이프라인 실행
    # =========================================================================
    print_subheader("Step 1: ExtractionAgent 파이프라인 실행")
    
    try:
        from src.agents.graph import build_agent
        # 노드 import로 자동 등록
        from src.agents.nodes import (
            QueryUnderstandingNode,
            ParameterResolverNode,
            PlanBuilderNode
        )
        
        # 파이프라인 빌드 (checkpointer 없이)
        workflow = build_agent()
        print("✅ 파이프라인 빌드 성공")
        
    except Exception as e:
        print(f"❌ 파이프라인 빌드 실패: {e}")
        return
    
    # 테스트 쿼리 (파라미터 명시 없이 - ConceptCategory 기반 추론 필요)
    test_query = "수술 환자의 vital signal 데이터를 전부 추출해줘"
    print(f"\n📝 테스트 쿼리: \"{test_query}\"")
    
    # 파이프라인 실행
    print("⏳ 파이프라인 실행 중...")
    start_time = time.time()
    
    try:
        initial_state = {
            "user_query": test_query,  # ExtractionState의 키 이름
            "logs": []
        }
        
        result = workflow.invoke(initial_state)
        elapsed = time.time() - start_time
        print(f"✅ 파이프라인 실행 완료 ({elapsed:.2f}s)")
        
    except Exception as e:
        print(f"❌ 파이프라인 실행 실패: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Execution Plan 확인
    execution_plan = result.get("execution_plan", {})
    if not execution_plan:
        print("❌ Execution Plan이 생성되지 않았습니다.")
        return
    
    print("\n📋 생성된 Execution Plan:")
    print(f"   - Version: {execution_plan.get('version')}")
    print(f"   - Agent: {execution_plan.get('agent')}")
    
    plan = execution_plan.get("execution_plan", {})
    cohort = plan.get("cohort_source", {})
    signal = plan.get("signal_source", {})
    
    print(f"   - Cohort: {cohort.get('file_name')}")
    print(f"   - Signal Group: {signal.get('group_name')}")
    print(f"   - Parameters: {len(signal.get('parameters', []))}개")
    
    for i, p in enumerate(signal.get("parameters", []), 1):
        print(f"      [{i}] {p.get('term')}: {p.get('param_keys')}")
    
    # =========================================================================
    # Step 2: DataContext에 Plan 로드
    # =========================================================================
    print_subheader("Step 2: DataContext에 Plan 로드")
    
    try:
        from shared.data import DataContext
        
        ctx = DataContext()
        ctx.load_from_plan(execution_plan)
        print("✅ DataContext에 Plan 로드 성공")
        
        # 상태 확인
        print("\n📊 DataContext 상태:")
        print(f"   - cohort_file_id: {ctx._cohort_file_id}")
        print(f"   - cohort_file_path: {ctx._cohort_file_path}")
        print(f"   - signal_group_id: {ctx._signal_group_id}")
        print(f"   - signal_files 수: {len(ctx._signal_files)}")
        if ctx._signal_files:
            print(f"   - signal_files 샘플: {ctx._signal_files[:3]}")
        print(f"   - param_keys: {ctx._param_keys}")
        print(f"   - temporal_type: {ctx._temporal_config.get('type')}")
        print(f"   - is_loaded: {ctx.is_loaded()}")
        
    except Exception as e:
        print(f"❌ DataContext 로드 실패: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # =========================================================================
    # Step 3: 실제 Signal 데이터 로드
    # =========================================================================
    print_subheader("Step 3: Signal 데이터 로드")
    
    # 사용 가능한 케이스 ID 확인
    print("📋 케이스 ID 조회 중...")
    try:
        cohort_case_ids = ctx.get_case_ids(signals_only=False)
        signal_case_ids = ctx.get_case_ids(signals_only=True)  # 기본값
        available_case_ids = ctx.get_available_case_ids()  # 교집합
        
        print(f"   - Cohort 전체 케이스: {len(cohort_case_ids)}개")
        print(f"   - Signal 파일 있는 케이스: {len(signal_case_ids)}개")
        print(f"   - 분석 가능 케이스 (교집합): {len(available_case_ids)}개")
        
        if signal_case_ids:
            print(f"   - Signal 케이스 ID: {signal_case_ids[:5]}{'...' if len(signal_case_ids) > 5 else ''}")
    except Exception as e:
        print(f"   ⚠️ 케이스 ID 조회 실패: {e}")
        signal_case_ids = []
    
    # Signal 파일 상세 정보
    print(f"\n📋 Signal 파일 상세:")
    print(f"   - Signal files 수: {len(ctx._signal_files)}")
    
    if ctx._signal_files:
        for i, sf in enumerate(ctx._signal_files[:3]):
            print(f"   - [{i+1}] caseid={sf.get('caseid')}, path={sf.get('file_path')}")
    
    # Signal file이 있는 케이스로 테스트
    test_case_id = None
    test_file_path = None
    if signal_case_ids:
        test_case_id = signal_case_ids[0]
        # 파일 경로 찾기
        for f in ctx._signal_files:
            if f.get("caseid") == test_case_id:
                test_file_path = f.get("file_path")
                break
        print(f"\n🔍 케이스 {test_case_id}의 Signal 데이터 로드 중...")
        print(f"   파일: {test_file_path}")
    else:
        print(f"\n⚠️ Signal 파일이 없습니다. 테스트를 스킵합니다.")
    
    if test_case_id and test_file_path:
        # .vital 파일 전체 트랙 정보 확인
        print(f"\n📂 .vital 파일 전체 트랙 정보:")
        try:
            import vitaldb
            vf = vitaldb.VitalFile(test_file_path)
            all_tracks = list(vf.trks.keys())
            print(f"   - 파일 내 전체 트랙 수: {len(all_tracks)}")
            print(f"   - 전체 트랙 목록:")
            for i, trk in enumerate(all_tracks):
                print(f"      [{i+1}] {trk}")
        except Exception as e:
            print(f"   ⚠️ 트랙 정보 조회 실패: {e}")
        
        # 요청한 param_keys vs 실제 로드
        print(f"\n📋 요청 param_keys vs 실제 로드:")
        print(f"   - 요청된 param_keys ({len(ctx._param_keys)}개): {ctx._param_keys}")
        
        start_time = time.time()
        try:
            signals = ctx.get_signals(caseid=test_case_id)
            elapsed = time.time() - start_time
            
            if signals is not None:
                print(f"✅ Signal 데이터 로드 성공 ({elapsed:.2f}s)")
                print(f"\n📊 로드된 데이터 정보:")
                print(f"   - type: {type(signals).__name__}")
                print(f"   - shape: {signals.shape if hasattr(signals, 'shape') else 'N/A'}")
                print(f"   - columns: {list(signals.columns) if hasattr(signals, 'columns') else 'N/A'}")
                
                if hasattr(signals, 'head') and len(signals) > 0:
                    # 실제 데이터가 있는 행 찾기 (nan이 아닌 값)
                    numeric_cols = [c for c in signals.columns if c != 'Time']
                    
                    print(f"\n📋 전체 데이터 개요:")
                    print(f"   - 총 행 수: {len(signals)}")
                    print(f"   - 시간 범위: {signals['Time'].min():.1f}s ~ {signals['Time'].max():.1f}s")
                    
                    # 각 컬럼별 유효 데이터 수 확인
                    print(f"\n📊 컬럼별 유효 데이터 수:")
                    for col in numeric_cols:
                        # [nan] 같은 리스트 형태의 데이터 처리
                        if signals[col].dtype == object:
                            # 리스트 형태의 데이터인 경우
                            valid_count = signals[col].apply(
                                lambda x: x is not None and (not isinstance(x, list) or (len(x) > 0 and x[0] == x[0]))
                            ).sum()
                        else:
                            valid_count = signals[col].notna().sum()
                        print(f"   - {col}: {valid_count}/{len(signals)} ({valid_count/len(signals)*100:.1f}%)")
                    
                    # nan이 아닌 데이터가 있는 행 찾기
                    print(f"\n📋 실제 데이터 샘플 (유효한 값이 있는 행):")
                    
                    # 중간 지점의 데이터 출력 (보통 수술 중 데이터)
                    mid_idx = len(signals) // 2
                    sample_range = signals.iloc[mid_idx:mid_idx+10]
                    
                    # 출력 형식 개선
                    print(f"   (시간 {sample_range['Time'].iloc[0]:.0f}s ~ {sample_range['Time'].iloc[-1]:.0f}s)")
                    print(sample_range.to_string(index=False))
                    
                    # 통계 정보 (숫자형 컬럼만)
                    if len(numeric_cols) > 0:
                        print(f"\n📊 데이터 통계:")
                        # 리스트 형태 데이터를 숫자로 변환
                        stats_df = signals.copy()
                        for col in numeric_cols:
                            if stats_df[col].dtype == object:
                                stats_df[col] = stats_df[col].apply(
                                    lambda x: x[0] if isinstance(x, list) and len(x) > 0 else None
                                )
                        
                        numeric_stats = stats_df[numeric_cols].describe()
                        print(numeric_stats.to_string())
                        
                elif len(signals) == 0:
                    print(f"\n⚠️ Signal 데이터가 비어있습니다. (param_keys가 없거나 파일을 찾을 수 없음)")
            else:
                print(f"⚠️ Signal 데이터가 None입니다.")
                
        except Exception as e:
            print(f"❌ Signal 데이터 로드 실패: {e}")
            import traceback
            traceback.print_exc()
    
    # =========================================================================
    # Step 4: Cohort 데이터 로드 확인
    # =========================================================================
    print_subheader("Step 4: Cohort 데이터 로드 확인")
    
    try:
        cohort_data = ctx.get_cohort()
        
        if cohort_data is not None:
            print(f"✅ Cohort 데이터 로드 성공")
            print(f"\n📊 Cohort 데이터 정보:")
            print(f"   - type: {type(cohort_data).__name__}")
            print(f"   - shape: {cohort_data.shape if hasattr(cohort_data, 'shape') else 'N/A'}")
            print(f"   - columns: {list(cohort_data.columns)[:10]}..." if hasattr(cohort_data, 'columns') and len(cohort_data.columns) > 10 else f"   - columns: {list(cohort_data.columns) if hasattr(cohort_data, 'columns') else 'N/A'}")
            
            if hasattr(cohort_data, 'head'):
                print(f"\n📋 샘플 데이터 (처음 3행, 주요 컬럼만):")
                display_cols = ['caseid', 'age', 'sex', 'department'] if all(c in cohort_data.columns for c in ['caseid', 'age', 'sex', 'department']) else list(cohort_data.columns)[:6]
                print(cohort_data[display_cols].head(3).to_string(index=False))
        else:
            print(f"⚠️ Cohort 데이터가 None입니다.")
            
    except Exception as e:
        print(f"❌ Cohort 데이터 로드 실패: {e}")
        import traceback
        traceback.print_exc()
    
    # =========================================================================
    # Step 5: 전체 케이스 로드 및 캐시 관리
    # =========================================================================
    print_subheader("Step 5: 전체 케이스 로드 및 캐시 관리")
    
    # 캐시 클리어 후 전체 로드
    DataContext.clear_cache("signals")
    print("🗑️ Signal 캐시 클리어")
    
    def print_cache_status():
        print(f"   - cohort_cache: {len(DataContext._cohort_cache)}개")
        print(f"   - signal_cache: {len(DataContext._signal_cache)}개")
        if DataContext._signal_cache:
            print(f"   - 캐시된 caseid: {list(DataContext._signal_cache.keys())}")
    
    print(f"\n📊 초기 캐시 상태:")
    print_cache_status()
    
    # 순차적으로 케이스 로드
    print(f"\n🔄 케이스별 순차 로드:")
    for i, cid in enumerate(signal_case_ids):
        start_time = time.time()
        df = ctx.get_signals(caseid=cid)
        elapsed = time.time() - start_time
        print(f"\n   [{i+1}] 케이스 {cid}: {df.shape}, {elapsed:.2f}s")
        print_cache_status()
    
    # 캐시 히트 테스트
    if signal_case_ids:
        print(f"\n🚀 캐시 히트 테스트 (동일 케이스 재요청):")
        start_time = time.time()
        df = ctx.get_signals(caseid=signal_case_ids[0])
        elapsed = time.time() - start_time
        print(f"   케이스 {signal_case_ids[0]} 재로드: {elapsed:.4f}s (캐시 히트)")
    
    # 메모리 사용량 확인
    print(f"\n📊 케이스별 메모리 사용량:")
    total_memory = 0
    for cid, df in DataContext._signal_cache.items():
        mem = df.memory_usage(deep=True).sum()
        total_memory += mem
        print(f"   - 케이스 {cid}: {mem/1024/1024:.2f} MB ({len(df)} rows)")
    print(f"\n   💾 총 캐시 메모리: {total_memory/1024/1024:.2f} MB")
    
    # =========================================================================
    # Step 6: 로드 상태 최종 확인
    # =========================================================================
    print_subheader("Step 6: 로드 상태 최종 확인")
    
    print("📊 DataContext 최종 상태:")
    print(f"   - is_loaded(): {ctx.is_loaded()}")
    
    # Summary 출력
    try:
        summary = ctx.summary()
        print(f"\n📋 Summary:")
        print(f"   - loaded_at: {summary.get('loaded_at')}")
        print(f"   - cohort.loaded: {summary.get('cohort', {}).get('loaded')}")
        print(f"   - signals.total_files: {summary.get('signals', {}).get('total_files')}")
        print(f"   - signals.cached_count: {summary.get('signals', {}).get('cached_count')}")
        print(f"   - cache_stats: {summary.get('cache_stats')}")
    except Exception as e:
        print(f"   ⚠️ Summary 조회 실패: {e}")
    
    # Analysis Context
    print_subheader("Step 7: Analysis Context 생성")
    
    try:
        analysis_ctx = ctx.get_analysis_context()
        print("✅ Analysis Context 생성 성공")
        print(f"\n📋 Analysis Context:")
        print(f"   - description: {analysis_ctx.get('description', '')[:100]}...")
        print(f"   - original_query: {analysis_ctx.get('original_query')}")
        print(f"   - cohort.total_cases: {analysis_ctx.get('cohort', {}).get('total_cases')}")
        print(f"   - signals.param_keys: {analysis_ctx.get('signals', {}).get('param_keys')}")
    except Exception as e:
        print(f"❌ Analysis Context 생성 실패: {e}")
    
    # =========================================================================
    # 완료
    # =========================================================================
    print_header("테스트 완료", "═")
    print("🎉 Signal 데이터 로드 테스트가 완료되었습니다!")


if __name__ == "__main__":
    main()

