#!/usr/bin/env python
"""
End-to-End Test: Dynamic Column Name Processing
================================================

테스트 목표:
  - "SBP로 끝나는 모든 혈압 파라미터"의 평균을 각각 계산
  - 동적으로 컬럼을 검색하여 처리

테스트하는 기능:
  - 동적 컬럼 검색 (패턴 매칭: endswith, contains 등)
  - 여러 컬럼 동시 처리
  - dict 형태 결과 반환
  - 컬럼 존재 여부 처리

사용법:
    python test_e2e_dynamic_columns.py
    python test_e2e_dynamic_columns.py --verbose
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import time
import numpy as np
import pandas as pd

# 프로젝트 루트 추가
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def setup_logging(verbose: bool = False):
    """로깅 설정"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S"
    )
    for logger_name in ["httpx", "httpcore", "openai", "urllib3"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


# =============================================================================
# 테스트 설정
# =============================================================================

# 테스트 케이스 (샘플 파일 기준: 0001~0020.vital)
TEST_CASE_IDS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

# SBP 관련 컬럼 패턴 (예상)
SBP_COLUMNS = ["Solar8000/NIBP_SBP", "Solar8000/ART_SBP", "Solar8000/FEM_SBP"]


# =============================================================================
# Ground Truth 계산
# =============================================================================

def calculate_ground_truth(case_ids: List[int]) -> Dict[str, Any]:
    """
    Ground Truth 계산: SBP 컬럼별 전체 평균
    
    Returns:
        {
            "column_means": {column_name: mean_value, ...},
            "columns_found": [list of columns found],
            "valid_cases": int
        }
    """
    import vitaldb
    
    data_dir = Path(__file__).parent.parent / "IndexingAgent" / "data" / "test" / "vitaldb_sample" / "vital_files"
    
    # 각 컬럼별 모든 값 수집
    column_values = {col: [] for col in SBP_COLUMNS}
    valid_cases = 0
    columns_found = set()
    
    for case_id in case_ids:
        vital_path = data_dir / f"{case_id:04d}.vital"
        if not vital_path.exists():
            continue
        
        try:
            # 모든 SBP 컬럼 로드 시도
            vf = vitaldb.read_vital(str(vital_path), SBP_COLUMNS)
            
            case_has_data = False
            for col in SBP_COLUMNS:
                try:
                    vals = vf.to_numpy([col], 1)
                    if vals is not None:
                        if hasattr(vals, 'ndim') and vals.ndim == 2:
                            vals = vals.flatten()
                        # NaN 제거
                        valid_vals = vals[~np.isnan(vals)]
                        if len(valid_vals) > 0:
                            column_values[col].extend(valid_vals.tolist())
                            columns_found.add(col)
                            case_has_data = True
                except:
                    pass
            
            if case_has_data:
                valid_cases += 1
                
        except Exception as e:
            logging.warning(f"Error processing case {case_id}: {e}")
            continue
    
    # 컬럼별 평균 계산
    column_means = {}
    for col, values in column_values.items():
        if values:
            column_means[col] = np.mean(values)
    
    return {
        "column_means": column_means,
        "columns_found": sorted(list(columns_found)),
        "valid_cases": valid_cases
    }


# =============================================================================
# 테스트 실행
# =============================================================================

def run_test(verbose: bool = False) -> bool:
    """테스트 실행"""
    from OrchestrationAgent.src.orchestrator import Orchestrator
    from shared.llm import enable_llm_logging
    
    # LLM 로깅 활성화
    log_session_dir = enable_llm_logging("./data/llm_logs")
    logging.info(f"📝 LLM Logs: {log_session_dir}")
    
    # Ground Truth 계산
    logging.info("📊 Calculating Ground Truth...")
    ground_truth = calculate_ground_truth(TEST_CASE_IDS)
    logging.info(f"   Valid cases: {ground_truth['valid_cases']}")
    logging.info(f"   Columns found: {ground_truth['columns_found']}")
    logging.info(f"   Column means:")
    for col, mean_val in ground_truth['column_means'].items():
        logging.info(f"      {col}: {mean_val:.4f}")
    
    # 테스트 쿼리
    case_ids_str = str(TEST_CASE_IDS)
    query = f"""caseid가 {case_ids_str} 중 하나인 케이스들에 대해서:
컬럼명이 'SBP'로 끝나는 모든 혈압 파라미터를 찾아서,
각 파라미터별로 전체 케이스의 평균값을 계산해줘.
NaN 값은 제외하고 계산해줘.
결과는 {{column_name: mean_value}} 형태의 dictionary로 반환해줘."""

    logging.info(f"🔍 Query: {query[:100]}...")
    
    # Orchestrator 실행
    orchestrator = Orchestrator()
    start_time = time.time()
    
    try:
        result = orchestrator.run(query)
        elapsed = time.time() - start_time
        
        if result.status == "success":
            analysis_result = result.result
            logging.info(f"✅ Execution SUCCESS ({elapsed:.2f}s)")
            logging.info(f"   Result: {analysis_result}")
            
            # 검증
            if isinstance(analysis_result, dict):
                expected = ground_truth["column_means"]
                
                logging.info(f"\n📊 Ground Truth Validation:")
                
                # 찾은 컬럼 수 비교
                expected_cols = set(expected.keys())
                result_cols = set(analysis_result.keys())
                
                logging.info(f"   Expected columns: {expected_cols}")
                logging.info(f"   Result columns: {result_cols}")
                
                # 값 비교 (존재하는 컬럼에 대해)
                all_valid = True
                for col in expected_cols:
                    # 결과에서 매칭되는 컬럼 찾기 (정확히 일치 또는 끝부분 일치)
                    matched_col = None
                    for r_col in result_cols:
                        if col == r_col or col.endswith(r_col) or r_col.endswith(col.split('/')[-1]):
                            matched_col = r_col
                            break
                    
                    if matched_col:
                        exp_val = expected[col]
                        res_val = analysis_result[matched_col]
                        diff_pct = abs(res_val - exp_val) / exp_val * 100 if exp_val > 0 else 0
                        
                        # 10% 허용 (NIBP 등 간헐적 측정의 경우 데이터 로딩 방식 차이 허용)
                        status = "✅" if diff_pct <= 10.0 else "❌"
                        logging.info(f"   {col}: {res_val:.2f} vs {exp_val:.2f} (diff: {diff_pct:.2f}%) {status}")
                        
                        if diff_pct > 10.0:
                            all_valid = False
                    else:
                        logging.warning(f"   {col}: Not found in result")
                
                if all_valid and len(result_cols) > 0:
                    logging.info("   ✅ VALIDATION PASSED")
                    return True
                else:
                    logging.error("   ❌ VALIDATION FAILED")
                    return False
            else:
                logging.warning(f"   ⚠️ Unexpected result type: {type(analysis_result)}")
                logging.info(f"   Expected dict, got: {analysis_result}")
                return False
        else:
            logging.error(f"❌ Execution FAILED: {result.error_message}")
            return False
            
    except Exception as e:
        logging.error(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="E2E Test: Dynamic Column Processing")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    logging.info("=" * 60)
    logging.info("E2E Test: Dynamic Column Name Processing (*SBP)")
    logging.info("=" * 60)
    
    success = run_test(args.verbose)
    
    logging.info("=" * 60)
    if success:
        logging.info("✅ TEST PASSED")
    else:
        logging.info("❌ TEST FAILED")
    logging.info("=" * 60)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
