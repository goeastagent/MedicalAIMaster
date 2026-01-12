#!/usr/bin/env python
"""
End-to-End Test: Conditional Filtering Analysis
================================================

테스트 목표:
  - NIBP_SBP가 특정 임계값(140 mmHg) 이상인 구간의 비율 계산
  - 환자별 고혈압 비율 계산 후 전체 평균
  
테스트하는 기능:
  - 조건부 필터링 (df['col'] >= threshold)
  - NaN 처리 (NIBP는 간헐적 측정)
  - Map-Reduce 집계
  - 비율 계산 (0~1 범위)

사용법:
    python test_e2e_conditional_filter.py
    python test_e2e_conditional_filter.py --verbose
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

# 고혈압 임계값
HYPERTENSION_THRESHOLD = 140  # mmHg

# Signal 컬럼
SIGNAL_COLUMN = "Solar8000/NIBP_SBP"


# =============================================================================
# Ground Truth 계산
# =============================================================================

def calculate_ground_truth(case_ids: List[int], threshold: float = HYPERTENSION_THRESHOLD) -> Dict[str, Any]:
    """
    Ground Truth 계산: 각 케이스별 고혈압 비율
    
    Args:
        case_ids: 테스트 케이스 ID 목록
        threshold: 고혈압 임계값 (기본 140 mmHg)
    
    Returns:
        {
            "case_ratios": {caseid: ratio, ...},
            "overall_mean": float,
            "valid_cases": int
        }
    """
    import vitaldb
    
    data_dir = Path(__file__).parent.parent / "IndexingAgent" / "data" / "test" / "vitaldb_sample" / "vital_files"
    case_ratios = {}
    
    for case_id in case_ids:
        vital_path = data_dir / f"{case_id:04d}.vital"
        if not vital_path.exists():
            continue
        
        try:
            vf = vitaldb.read_vital(str(vital_path), [SIGNAL_COLUMN])
            vals = vf.to_numpy([SIGNAL_COLUMN], 1)
            
            if vals is not None and hasattr(vals, 'ndim') and vals.ndim == 2:
                vals = vals.flatten()
            
            if vals is None or len(vals) == 0:
                continue
            
            # NaN 제거
            valid_vals = vals[~np.isnan(vals)]
            
            if len(valid_vals) == 0:
                continue
            
            # 고혈압 비율 계산
            hypertension_count = np.sum(valid_vals >= threshold)
            ratio = hypertension_count / len(valid_vals)
            
            case_ratios[str(case_id)] = ratio
            
        except Exception as e:
            logging.warning(f"Error processing case {case_id}: {e}")
            continue
    
    valid_cases = len(case_ratios)
    overall_mean = np.mean(list(case_ratios.values())) if case_ratios else 0.0
    
    return {
        "case_ratios": case_ratios,
        "overall_mean": overall_mean,
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
    logging.info(f"   Overall mean ratio: {ground_truth['overall_mean']:.4f}")
    
    # 테스트 쿼리
    case_ids_str = str(TEST_CASE_IDS)
    query = f"""caseid가 {case_ids_str} 중 하나인 케이스들에 대해서:
NIBP_SBP(Solar8000/NIBP_SBP) 값이 {HYPERTENSION_THRESHOLD} mmHg 이상인 비율을 각 케이스별로 계산하고,
모든 케이스의 평균 비율을 구해줘.
NaN 값은 제외하고 계산해줘.
결과는 단일 float 값(0~1 사이의 비율)으로 반환해줘."""

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
            if isinstance(analysis_result, (int, float)):
                expected = ground_truth["overall_mean"]
                diff_pct = abs(analysis_result - expected) / expected * 100 if expected > 0 else 0
                
                logging.info(f"\n📊 Ground Truth Validation:")
                logging.info(f"   Result: {analysis_result:.4f}")
                logging.info(f"   Expected: {expected:.4f}")
                logging.info(f"   Diff: {diff_pct:.2f}%")
                
                # 5% 이내면 통과
                if diff_pct <= 5.0:
                    logging.info("   ✅ VALIDATION PASSED")
                    return True
                else:
                    logging.error("   ❌ VALIDATION FAILED (diff > 5%)")
                    return False
            else:
                logging.warning(f"   ⚠️ Unexpected result type: {type(analysis_result)}")
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
    parser = argparse.ArgumentParser(description="E2E Test: Conditional Filtering")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    logging.info("=" * 60)
    logging.info("E2E Test: Conditional Filtering (Hypertension Ratio)")
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
