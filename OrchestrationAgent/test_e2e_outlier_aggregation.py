#!/usr/bin/env python
"""
End-to-End Test: Outlier Removal + Time-based Aggregation
==========================================================

테스트 목표:
  - HR에서 IQR 방식으로 outlier 제거
  - 5분(300초) 단위로 시간 기반 평균 계산
  - 전체 케이스의 평균 반환

테스트하는 기능:
  - IQR 기반 이상치 제거 (Q1 - 1.5*IQR, Q3 + 1.5*IQR)
  - 시간 기반 리샘플링/집계
  - 통계적 데이터 전처리

사용법:
    python test_e2e_outlier_aggregation.py
    python test_e2e_outlier_aggregation.py --verbose
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

# Signal 컬럼
HR_COLUMN = "Solar8000/HR"

# 집계 단위 (초)
AGGREGATION_WINDOW = 300  # 5분


# =============================================================================
# Ground Truth 계산
# =============================================================================

def remove_outliers_iqr(values: np.ndarray) -> np.ndarray:
    """IQR 방식으로 outlier 제거"""
    if len(values) == 0:
        return values
    
    q1 = np.percentile(values, 25)
    q3 = np.percentile(values, 75)
    iqr = q3 - q1
    
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    
    mask = (values >= lower_bound) & (values <= upper_bound)
    return values[mask]


def calculate_ground_truth(case_ids: List[int]) -> Dict[str, Any]:
    """
    Ground Truth 계산: IQR outlier 제거 후 5분 단위 평균
    
    Returns:
        {
            "case_means": {caseid: mean_value, ...},
            "overall_mean": float,
            "valid_cases": int,
            "total_outliers_removed": int
        }
    """
    import vitaldb
    
    data_dir = Path(__file__).parent.parent / "IndexingAgent" / "data" / "test" / "vitaldb_sample" / "vital_files"
    case_means = {}
    total_outliers_removed = 0
    
    for case_id in case_ids:
        vital_path = data_dir / f"{case_id:04d}.vital"
        if not vital_path.exists():
            continue
        
        try:
            vf = vitaldb.read_vital(str(vital_path), [HR_COLUMN])
            vals = vf.to_numpy([HR_COLUMN], 1)  # 1초 간격
            
            if vals is not None and hasattr(vals, 'ndim') and vals.ndim == 2:
                vals = vals.flatten()
            
            if vals is None or len(vals) == 0:
                continue
            
            # Time 인덱스 생성 (0, 1, 2, ... 초)
            time_idx = np.arange(len(vals))
            
            # NaN 제거
            mask = ~np.isnan(vals)
            vals = vals[mask]
            time_idx = time_idx[mask]
            
            if len(vals) == 0:
                continue
            
            original_count = len(vals)
            
            # IQR outlier 제거
            q1 = np.percentile(vals, 25)
            q3 = np.percentile(vals, 75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            
            outlier_mask = (vals >= lower_bound) & (vals <= upper_bound)
            vals_clean = vals[outlier_mask]
            time_clean = time_idx[outlier_mask]
            
            outliers_removed = original_count - len(vals_clean)
            total_outliers_removed += outliers_removed
            
            if len(vals_clean) == 0:
                continue
            
            # 5분 단위 집계 (Time 값 기준)
            segment_means = []
            segment_indices = time_clean // AGGREGATION_WINDOW
            
            for seg_idx in np.unique(segment_indices):
                seg_mask = segment_indices == seg_idx
                seg_vals = vals_clean[seg_mask]
                if len(seg_vals) > 0:
                    segment_means.append(np.mean(seg_vals))
            
            if segment_means:
                case_mean = np.mean(segment_means)
                case_means[str(case_id)] = case_mean
                
        except Exception as e:
            logging.warning(f"Error processing case {case_id}: {e}")
            continue
    
    valid_cases = len(case_means)
    overall_mean = np.mean(list(case_means.values())) if case_means else 0.0
    
    return {
        "case_means": case_means,
        "overall_mean": overall_mean,
        "valid_cases": valid_cases,
        "total_outliers_removed": total_outliers_removed
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
    logging.info(f"   Total outliers removed: {ground_truth['total_outliers_removed']}")
    logging.info(f"   Overall mean HR: {ground_truth['overall_mean']:.4f}")
    
    # 테스트 쿼리
    case_ids_str = str(TEST_CASE_IDS)
    query = f"""caseid가 {case_ids_str} 중 하나인 케이스들에 대해서:
각 케이스의 HR(Solar8000/HR) 값에서 IQR 방식으로 outlier를 제거해줘.
(Q1 - 1.5*IQR 미만, Q3 + 1.5*IQR 초과인 값 제거)
그 다음 Time 값을 기준으로 5분(300초) 단위로 평균을 구하고,
모든 segment 평균들의 평균을 케이스별로 구한 후,
전체 케이스의 평균을 구해줘.
결과는 단일 float 값으로 반환해줘."""

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
                
                # 10% 이내면 통과 (outlier 제거 방식에 따른 차이 허용)
                if diff_pct <= 10.0:
                    logging.info("   ✅ VALIDATION PASSED")
                    return True
                else:
                    logging.error("   ❌ VALIDATION FAILED (diff > 10%)")
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
    parser = argparse.ArgumentParser(description="E2E Test: Outlier Removal + Aggregation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    logging.info("=" * 60)
    logging.info("E2E Test: IQR Outlier Removal + 5min Aggregation")
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
