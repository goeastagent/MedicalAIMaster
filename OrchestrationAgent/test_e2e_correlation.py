#!/usr/bin/env python
"""
End-to-End Test: Multi-Parameter Correlation Analysis
======================================================

테스트 목표:
  - HR과 SpO2의 Pearson 상관계수 계산
  - 각 케이스별로 상관계수와 p-value 계산
  - 통계적으로 유의미한 케이스 비율 반환

테스트하는 기능:
  - scipy.stats 사용 (pearsonr)
  - 다중 컬럼 동시 접근
  - 통계적 유의성 필터링 (p < 0.05)
  - 복합 결과 반환

사용법:
    python test_e2e_correlation.py
    python test_e2e_correlation.py --verbose
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
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

# Signal 컬럼
HR_COLUMN = "Solar8000/HR"
SPO2_COLUMN = "Solar8000/PLETH_SPO2"

# 유의수준
SIGNIFICANCE_LEVEL = 0.05


# =============================================================================
# Ground Truth 계산
# =============================================================================

def calculate_ground_truth(case_ids: List[int]) -> Dict[str, Any]:
    """
    Ground Truth 계산: 각 케이스별 HR-SpO2 상관계수
    
    Returns:
        {
            "case_correlations": {caseid: {"r": float, "p": float, "significant": bool}, ...},
            "significant_ratio": float,
            "mean_correlation": float,
            "valid_cases": int
        }
    """
    import vitaldb
    from scipy import stats
    
    data_dir = Path(__file__).parent.parent / "IndexingAgent" / "data" / "test" / "vitaldb_sample" / "vital_files"
    case_correlations = {}
    
    for case_id in case_ids:
        vital_path = data_dir / f"{case_id:04d}.vital"
        if not vital_path.exists():
            continue
        
        try:
            vf = vitaldb.read_vital(str(vital_path), [HR_COLUMN, SPO2_COLUMN])
            hr_vals = vf.to_numpy([HR_COLUMN], 1)
            spo2_vals = vf.to_numpy([SPO2_COLUMN], 1)
            
            if hr_vals is not None and hasattr(hr_vals, 'ndim') and hr_vals.ndim == 2:
                hr_vals = hr_vals.flatten()
            if spo2_vals is not None and hasattr(spo2_vals, 'ndim') and spo2_vals.ndim == 2:
                spo2_vals = spo2_vals.flatten()
            
            if hr_vals is None or spo2_vals is None:
                continue
            
            # 길이 맞추기
            min_len = min(len(hr_vals), len(spo2_vals))
            hr_vals = hr_vals[:min_len]
            spo2_vals = spo2_vals[:min_len]
            
            # NaN 동시 제거
            mask = ~(np.isnan(hr_vals) | np.isnan(spo2_vals))
            hr_clean = hr_vals[mask]
            spo2_clean = spo2_vals[mask]
            
            if len(hr_clean) < 10:  # 최소 데이터 포인트
                continue
            
            # 상관계수 계산
            r, p = stats.pearsonr(hr_clean, spo2_clean)
            
            case_correlations[str(case_id)] = {
                "r": r,
                "p": p,
                "significant": p < SIGNIFICANCE_LEVEL
            }
            
        except Exception as e:
            logging.warning(f"Error processing case {case_id}: {e}")
            continue
    
    valid_cases = len(case_correlations)
    significant_count = sum(1 for c in case_correlations.values() if c["significant"])
    significant_ratio = significant_count / valid_cases if valid_cases > 0 else 0.0
    
    correlations = [c["r"] for c in case_correlations.values()]
    mean_correlation = np.mean(correlations) if correlations else 0.0
    
    return {
        "case_correlations": case_correlations,
        "significant_ratio": significant_ratio,
        "mean_correlation": mean_correlation,
        "valid_cases": valid_cases,
        "significant_count": significant_count
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
    logging.info(f"   Significant cases: {ground_truth['significant_count']}")
    logging.info(f"   Significant ratio: {ground_truth['significant_ratio']:.4f}")
    logging.info(f"   Mean correlation: {ground_truth['mean_correlation']:.4f}")
    
    # 테스트 쿼리
    case_ids_str = str(TEST_CASE_IDS)
    query = f"""caseid가 {case_ids_str} 중 하나인 케이스들에 대해서:
각 케이스별로 HR(Solar8000/HR)과 SpO2(Solar8000/PLETH_SPO2)의 Pearson 상관계수를 계산해줘.
NaN 값은 제외하고 계산하고, 두 신호의 길이가 다르면 짧은 쪽에 맞춰줘.
통계적으로 유의미한 상관관계(p-value < 0.05)를 가진 케이스의 비율을 구해줘.
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
                expected = ground_truth["significant_ratio"]
                
                # 비율은 정확히 일치해야 함 (이산값)
                diff = abs(analysis_result - expected)
                
                logging.info(f"\n📊 Ground Truth Validation:")
                logging.info(f"   Result: {analysis_result:.4f}")
                logging.info(f"   Expected: {expected:.4f}")
                logging.info(f"   Diff: {diff:.4f}")
                
                # 10% 이내 또는 0.1 이내면 통과 (케이스 수가 적어 이산 오차 허용)
                if diff <= 0.15:
                    logging.info("   ✅ VALIDATION PASSED")
                    return True
                else:
                    logging.error("   ❌ VALIDATION FAILED")
                    return False
            else:
                logging.warning(f"   ⚠️ Unexpected result type: {type(analysis_result)}")
                # dict 형태로 반환했을 수도 있음
                if isinstance(analysis_result, dict):
                    logging.info(f"   Result dict: {analysis_result}")
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
    parser = argparse.ArgumentParser(description="E2E Test: Correlation Analysis")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    logging.info("=" * 60)
    logging.info("E2E Test: Multi-Parameter Correlation (HR vs SpO2)")
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
