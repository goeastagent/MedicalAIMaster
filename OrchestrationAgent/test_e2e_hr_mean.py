#!/usr/bin/env python
"""
End-to-End Test: Full Pipeline HR Analysis
===========================================

전체 파이프라인을 테스트합니다:
  ExtractionAgent → DataContext → AnalysisAgent

사용법:
    python test_e2e_hr_mean.py
    python test_e2e_hr_mean.py --verbose
    python test_e2e_hr_mean.py --query "심박수 평균을 구해줘"
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
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
    
    # 외부 라이브러리 로그 레벨 조절
    for logger_name in ["httpx", "httpcore", "openai", "urllib3"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def run_full_pipeline_test(
    queries: List[tuple], 
    verbose: bool = False,
    validate: bool = True
) -> bool:
    """
    전체 파이프라인 테스트 실행
    
    ExtractionAgent → DataContext → AnalysisAgent
    
    Args:
        queries: (쿼리 문자열, validator 함수) 튜플 목록
        verbose: 상세 로그 출력
        validate: Ground Truth와 비교 여부
    
    Returns:
        모든 테스트 성공 여부
    """
    from OrchestrationAgent.src.orchestrator import Orchestrator
    from shared.data.context import DataContext
    
    # 캐시 클리어 (재현성 보장)
    DataContext.clear_cache()
    logging.info("🗑️ Cache cleared for reproducibility")
    
    logging.info("=" * 70)
    logging.info("  Full Pipeline End-to-End Test")
    logging.info("=" * 70)
    logging.info("  Pipeline: ExtractionAgent → DataContext → AnalysisAgent")
    if validate:
        logging.info("  Mode: With Ground Truth Validation ✓")
        logging.info(f"  Test Cases: {TEST_CASE_IDS}")
    logging.info("=" * 70)
    
    orchestrator = Orchestrator()
    test_results = []
    
    for i, query_item in enumerate(queries, 1):
        # 쿼리와 validator 분리
        if isinstance(query_item, tuple):
            query, validator = query_item
        else:
            query, validator = query_item, None
        
        logging.info(f"\n{'='*60}")
        logging.info(f"[Test {i}/{len(queries)}] {query}")
        logging.info("=" * 60)
        
        start_time = time.time()
        
        # 전체 파이프라인 실행
        result = orchestrator.run(query)
        
        elapsed = time.time() - start_time
        
        if result.status == "success":
            logging.info(f"✅ Execution SUCCESS ({elapsed:.2f}s)")
            logging.info(f"   Result: {result.result}")
            
            # Ground Truth 검증
            validation_passed = True
            validation_msg = ""
            
            if validate and validator:
                logging.info("\n   📊 Ground Truth Validation:")
                validation_passed, validation_msg = validator(result.result)
                
                for line in validation_msg.split("\n"):
                    logging.info(f"   {line}")
                
                if validation_passed:
                    logging.info("   ✅ VALIDATION PASSED")
                else:
                    logging.error("   ❌ VALIDATION FAILED")
            
            if verbose and result.generated_code:
                logging.info(f"\n   Generated Code:")
                logging.info("-" * 40)
                for line in result.generated_code.split("\n"):
                    logging.info(f"   {line}")
            
            test_results.append((query, validation_passed, result, validation_msg))
        else:
            logging.error(f"❌ Execution FAILED ({elapsed:.2f}s)")
            logging.error(f"   Error Stage: {result.error_stage}")
            logging.error(f"   Error: {result.error_message}")
            test_results.append((query, False, result, "Execution failed"))
    
    # 결과 요약
    logging.info("\n" + "=" * 70)
    logging.info("테스트 결과 요약")
    logging.info("=" * 70)
    
    passed_count = sum(1 for _, passed, _, _ in test_results if passed)
    total_count = len(test_results)
    
    for query, passed, result, val_msg in test_results:
        status = "✅ PASS" if passed else "❌ FAIL"
        short_query = query[:50] + "..." if len(query) > 50 else query
        logging.info(f"  {status} | {short_query}")
    
    logging.info("-" * 70)
    logging.info(f"  Total: {passed_count}/{total_count} passed")
    
    all_passed = passed_count == total_count
    
    logging.info("\n" + "=" * 70)
    if all_passed:
        logging.info("  ✅ ALL TESTS PASSED (with Ground Truth validation)!")
    else:
        logging.info("  ❌ SOME TESTS FAILED")
    logging.info("=" * 70)
    
    return all_passed


# =============================================================================
# 테스트 대상 케이스 ID (재현성을 위해 고정)
# =============================================================================

TEST_CASE_IDS = ['1', '11', '32', '197', '198', '199', '200', '574', '575', '576']
TEST_CASE_IDS_STR = ", ".join(TEST_CASE_IDS)  # "1, 11, 32, 197, 198, 199, 200, 574, 575, 576"


# =============================================================================
# Ground Truth 정의 (10개 케이스 기준: 1, 11, 32, 197, 198, 199, 200, 574, 575, 576)
# =============================================================================

# 케이스별 HR 평균 (Ground Truth)
GROUND_TRUTH_CASE_MEANS = {
    '1': 77.192667,
    '11': 69.065425,
    '32': 65.264281,
    '197': 64.691626,
    '198': 66.415616,
    '199': 61.723522,
    '200': 77.371204,
    '574': 72.946735,
    '575': 73.755811,
    '576': 93.802846,
}

# 케이스별 통계 (Ground Truth)
GROUND_TRUTH_CASE_STATS = {
    '1':   {'mean': 77.192667, 'std': 14.608640, 'min': 57.0, 'max': 139.0},
    '11':  {'mean': 69.065425, 'std': 8.158767,  'min': 46.0, 'max': 96.0},
    '32':  {'mean': 65.264281, 'std': 14.055257, 'min': 49.0, 'max': 153.0},
    '197': {'mean': 64.691626, 'std': 7.509587,  'min': 45.0, 'max': 175.0},
    '198': {'mean': 66.415616, 'std': 9.338637,  'min': 52.0, 'max': 123.0},
    '199': {'mean': 61.723522, 'std': 8.620957,  'min': 36.0, 'max': 133.0},
    '200': {'mean': 77.371204, 'std': 9.977991,  'min': 50.0, 'max': 112.0},
    '574': {'mean': 72.946735, 'std': 6.293863,  'min': 62.0, 'max': 105.0},
    '575': {'mean': 73.755811, 'std': 6.728994,  'min': 60.0, 'max': 106.0},
    '576': {'mean': 93.802846, 'std': 9.963528,  'min': 79.0, 'max': 131.0},
}

# 전체 통계 (Ground Truth)
GROUND_TRUTH_OVERALL = {
    'mean': 72.222973,  # 케이스 평균의 평균
    'std': 9.525622,    # 케이스 std의 평균
    'min': 36.0,
    'max': 175.0,
}


# =============================================================================
# Ground Truth 비교 함수
# =============================================================================

def compare_numeric(result: Any, expected: float, tolerance: float = 0.01) -> tuple:
    """
    숫자 결과 비교 (다양한 형태 지원)
    
    Returns:
        (is_match, message)
    """
    # DataFrame/Series에서 값 추출 시도
    if isinstance(result, pd.DataFrame):
        if 'mean' in result.columns:
            result = result['mean'].mean()
        elif len(result.columns) == 1:
            result = result.iloc[:, 0].mean()
        else:
            return False, f"Cannot extract numeric from DataFrame: {result.columns.tolist()}"
    elif isinstance(result, pd.Series):
        result = result.mean()
    elif isinstance(result, dict):
        # dict인 경우 - 단일 숫자 값이면 그 값 사용, 아니면 'mean' 키 찾기
        if len(result) == 1:
            result = list(result.values())[0]
        elif 'mean' in result:
            result = result['mean']
    
    if result is None or (isinstance(result, float) and np.isnan(result)):
        return False, f"Result is None/NaN, expected {expected:.4f}"
    
    try:
        result_val = float(result)
    except (TypeError, ValueError):
        return False, f"Cannot convert result to float: {result}"
    
    diff = abs(result_val - expected)
    rel_diff = diff / abs(expected) if expected != 0 else diff
    
    if rel_diff <= tolerance:
        return True, f"✅ {result_val:.4f} ≈ {expected:.4f} (diff: {rel_diff*100:.2f}%)"
    else:
        return False, f"❌ {result_val:.4f} ≠ {expected:.4f} (diff: {rel_diff*100:.2f}%)"


def compare_dict_means(result: Any, expected: Dict[str, float], tolerance: float = 0.01) -> tuple:
    """
    케이스별 평균 딕셔너리 비교 (DataFrame도 지원)
    
    Returns:
        (is_match, message)
    """
    # DataFrame을 dict로 변환
    if isinstance(result, pd.DataFrame):
        # caseid 컬럼과 mean 컬럼이 있는 경우
        if 'caseid' in result.columns and 'mean' in result.columns:
            result = dict(zip(result['caseid'].astype(str), result['mean']))
        # index가 caseid인 경우
        elif 'mean' in result.columns:
            result = result['mean'].to_dict()
            result = {str(k): v for k, v in result.items()}
        else:
            return False, f"Cannot extract case means from DataFrame: {result.columns.tolist()}"
    
    if not isinstance(result, dict):
        return False, f"Result is not a dict: {type(result)}"
    
    messages = []
    all_match = True
    matched = 0
    total = len(expected)
    
    for case_id, exp_val in expected.items():
        if case_id not in result:
            messages.append(f"  ❌ Case {case_id}: MISSING")
            all_match = False
            continue
        
        res_val = result[case_id]
        if isinstance(res_val, float) and np.isnan(res_val):
            messages.append(f"  ❌ Case {case_id}: NaN (expected {exp_val:.4f})")
            all_match = False
            continue
        
        try:
            res_val = float(res_val)
        except (TypeError, ValueError):
            messages.append(f"  ❌ Case {case_id}: Cannot convert {res_val}")
            all_match = False
            continue
        
        diff = abs(res_val - exp_val)
        rel_diff = diff / abs(exp_val) if exp_val != 0 else diff
        
        if rel_diff <= tolerance:
            messages.append(f"  ✅ Case {case_id}: {res_val:.4f} ≈ {exp_val:.4f}")
            matched += 1
        else:
            messages.append(f"  ❌ Case {case_id}: {res_val:.4f} ≠ {exp_val:.4f} (diff: {rel_diff*100:.2f}%)")
            all_match = False
    
    summary = f"Matched: {matched}/{total}"
    return all_match, summary + "\n" + "\n".join(messages)


def compare_stats(result: Any, expected_case_stats: Dict, expected_overall: Dict, tolerance: float = 0.01) -> tuple:
    """
    통계 결과 비교 (케이스별 + 전체)
    DataFrame, dict 모두 지원
    
    Returns:
        (is_match, message)
    """
    messages = []
    all_match = True
    
    # DataFrame을 dict로 변환 (caseid가 컬럼인 경우)
    if isinstance(result, pd.DataFrame):
        if 'caseid' in result.columns:
            # caseid 컬럼이 있는 DataFrame -> per_case dict 형태로 변환
            result = {'per_case': result}
        else:
            # index 기반 DataFrame
            result = {'per_case': result}
    
    # 결과 형태 확인
    if not isinstance(result, dict):
        return False, f"Result is not a dict: {type(result)}"
    
    # 1. 케이스별 통계 비교 (per_case가 있는 경우)
    per_case = result.get('per_case')
    if per_case is not None:
        messages.append("=== Per-Case Statistics ===")
        
        # DataFrame인 경우
        if isinstance(per_case, pd.DataFrame):
            # caseid 컬럼이 있는 경우 해당 컬럼 기준으로 검색
            has_caseid_col = 'caseid' in per_case.columns
            
            for case_id, exp_stats in expected_case_stats.items():
                # 해당 케이스 row 찾기
                if has_caseid_col:
                    # caseid 컬럼 기준
                    mask = per_case['caseid'].astype(str) == str(case_id)
                    if not mask.any():
                        mask = per_case['caseid'] == int(case_id)
                    if not mask.any():
                        messages.append(f"  ❌ Case {case_id}: MISSING")
                        all_match = False
                        continue
                    row = per_case[mask].iloc[0]
                else:
                    # index 기준
                    if case_id not in per_case.index and int(case_id) not in per_case.index:
                        messages.append(f"  ❌ Case {case_id}: MISSING")
                        all_match = False
                        continue
                    idx = case_id if case_id in per_case.index else int(case_id)
                    row = per_case.loc[idx]
                
                for stat_name in ['mean', 'std', 'min', 'max']:
                    exp_val = exp_stats[stat_name]
                    res_val = row.get(stat_name, np.nan) if isinstance(row, dict) else row[stat_name] if stat_name in row.index else np.nan
                    
                    if pd.isna(res_val):
                        messages.append(f"  ❌ Case {case_id} {stat_name}: NaN")
                        all_match = False
                    else:
                        rel_diff = abs(res_val - exp_val) / abs(exp_val) if exp_val != 0 else abs(res_val - exp_val)
                        if rel_diff > tolerance:
                            messages.append(f"  ❌ Case {case_id} {stat_name}: {res_val:.2f} ≠ {exp_val:.2f}")
                            all_match = False
        
        # Dict인 경우
        elif isinstance(per_case, dict):
            for case_id, exp_stats in expected_case_stats.items():
                if case_id not in per_case:
                    messages.append(f"  ❌ Case {case_id}: MISSING")
                    all_match = False
                    continue
                
                case_result = per_case[case_id]
                for stat_name in ['mean', 'std', 'min', 'max']:
                    exp_val = exp_stats[stat_name]
                    res_val = case_result.get(stat_name, np.nan)
                    
                    if pd.isna(res_val):
                        messages.append(f"  ❌ Case {case_id} {stat_name}: NaN")
                        all_match = False
                    else:
                        rel_diff = abs(res_val - exp_val) / abs(exp_val) if exp_val != 0 else abs(res_val - exp_val)
                        if rel_diff > tolerance:
                            messages.append(f"  ❌ Case {case_id} {stat_name}: {res_val:.2f} ≠ {exp_val:.2f}")
                            all_match = False
        
        if all_match:
            messages.append("  ✅ All per-case statistics match!")
    
    # 2. 전체 통계 비교
    messages.append("=== Overall Statistics ===")
    overall_keys = ['overall', 'overall_across_cases', 'overall_stats']
    overall_result = None
    for key in overall_keys:
        if key in result:
            overall_result = result[key]
            break
    
    if overall_result is None:
        # 단일 값 결과인 경우 (mean만)
        if 'mean' in result:
            overall_result = result
    
    if overall_result:
        for stat_name, exp_val in expected_overall.items():
            res_val = overall_result.get(stat_name, np.nan) if isinstance(overall_result, dict) else np.nan
            
            if pd.isna(res_val):
                messages.append(f"  ⚠️ Overall {stat_name}: Not found in result")
            else:
                rel_diff = abs(res_val - exp_val) / abs(exp_val) if exp_val != 0 else abs(res_val - exp_val)
                if rel_diff <= tolerance:
                    messages.append(f"  ✅ Overall {stat_name}: {res_val:.4f} ≈ {exp_val:.4f}")
                else:
                    messages.append(f"  ❌ Overall {stat_name}: {res_val:.4f} ≠ {exp_val:.4f}")
                    all_match = False
    else:
        messages.append("  ⚠️ No overall statistics found in result")
    
    return all_match, "\n".join(messages)


# =============================================================================
# 테스트 케이스 정의
# =============================================================================

def validate_query1_result(result: Any) -> tuple:
    """쿼리 1: 모든 수술 환자의 심박수(HR) 평균"""
    expected = GROUND_TRUTH_OVERALL['mean']
    return compare_numeric(result, expected)


def validate_query2_result(result: Any) -> tuple:
    """쿼리 2: 각 환자별 HR 평균을 dictionary로"""
    return compare_dict_means(result, GROUND_TRUTH_CASE_MEANS)


def validate_query3_result(result: Any) -> tuple:
    """쿼리 3: HR의 기본 통계"""
    return compare_stats(result, GROUND_TRUTH_CASE_STATS, GROUND_TRUTH_OVERALL)


# =============================================================================
# 기본 테스트 쿼리 (케이스 ID 명시로 재현성 보장)
# =============================================================================

DEFAULT_QUERIES = [
    # Query 1: 전체 평균 - 단일 float 반환 명시
    (f"caseid가 {TEST_CASE_IDS_STR}인 환자들의 심박수(HR) 전체 평균을 구해서 단일 float 값으로 반환해줘", validate_query1_result),
    # Query 2: 케이스별 평균 - dict 형태 명시 (기존과 동일)
    (f"caseid가 {TEST_CASE_IDS_STR}인 각 환자별 HR 평균을 {{caseid: mean}} 형태의 dictionary로 반환해줘", validate_query2_result),
    # Query 3: 기본 통계 - DataFrame 형태 명시
    (f"caseid가 {TEST_CASE_IDS_STR}인 환자들의 HR 기본 통계(평균, 표준편차, 최소, 최대)를 caseid별로 DataFrame으로 반환해줘", validate_query3_result),
]


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Full Pipeline End-to-End Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 기본 테스트 (3개 쿼리 + Ground Truth 검증)
    python test_e2e_hr_mean.py
    
    # 커스텀 쿼리 테스트 (검증 없이)
    python test_e2e_hr_mean.py --query "위암 환자의 심박수 평균"
    
    # 상세 로그 출력
    python test_e2e_hr_mean.py --verbose
    
    # Ground Truth 검증 비활성화
    python test_e2e_hr_mean.py --no-validate
        """
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        nargs="+",
        help="테스트할 자연어 쿼리 (복수 가능, 검증 없이 실행)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 로그 및 생성된 코드 출력"
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Ground Truth 검증 비활성화"
    )
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    # 쿼리 결정
    if args.query:
        # 커스텀 쿼리는 validator 없이 실행
        queries = [(q, None) for q in args.query]
        validate = False
    else:
        queries = DEFAULT_QUERIES
        validate = not args.no_validate
    
    try:
        success = run_full_pipeline_test(
            queries=queries, 
            verbose=args.verbose,
            validate=validate
        )
        sys.exit(0 if success else 1)
    
    except Exception as e:
        logging.exception(f"Test failed with exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
