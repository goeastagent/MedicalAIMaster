#!/usr/bin/env python
"""
End-to-End Test: Signal Segmentation Mean Analysis
===================================================

전체 파이프라인을 테스트합니다:
  ExtractionAgent → DataContext → AnalysisAgent

테스트 목표:
  - 케이스 별로 SBP(NIBP_SBP) 값을 10분 단위로 segmentation
  - 각 segment의 평균을 구하고, segment 평균들의 평균을 계산
  - 환자별 SBP 평균을 구함
  - 동일 환자가 여러 케이스를 가진 경우, 모든 segment를 합쳐서 평균

테스트 모드:
  - 기본 모드: 특정 subjectid (1, 2, 4, 5, 6, 7, 32, 150) 대상, 사전정의된 Ground Truth 사용
  - 전체 모드 (--full): 모든 환자 대상, Ground Truth 동적 계산

사용법:
    # 기본 모드 (특정 환자, 빠른 테스트)
    python test_e2e_signal_segmentation_mean.py
    
    # 전체 모드 (모든 환자, Ground Truth 동적 계산)
    python test_e2e_signal_segmentation_mean.py --full
    
    # 전체 모드 + 상세 로그
    python test_e2e_signal_segmentation_mean.py --full --verbose
"""

import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple
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


# =============================================================================
# 테스트 대상 케이스 - 기본 모드 (subjectid 기준)
# =============================================================================

# 테스트 대상 환자 (subjectid) - 기본 모드
# - 다중수술: 32 (2 surgeries), 150 (2 surgeries)
# - 단일수술: 1, 2, 4, 5, 6, 7
DEFAULT_TEST_SUBJECT_IDS = [1, 2, 4, 5, 6, 7, 32, 150]
DEFAULT_TEST_SUBJECT_IDS_STR = "1, 2, 4, 5, 6, 7, 32, 150"

# 환자별 케이스 매핑 (참고용)
SUBJECT_CASES = {
    1: [3594],
    2: [121],
    4: [3417],
    5: [734],
    6: [1580],
    7: [1579],
    32: [1598, 1845],   # 다중수술
    150: [316, 5359],   # 다중수술
}


# =============================================================================
# Ground Truth 정의 - DEPRECATED (더 이상 사용되지 않음)
# =============================================================================
# 
# 아래 상수들은 이전에 하드코딩된 값으로, 더 이상 사용되지 않습니다.
# 현재는 compute_full_ground_truth()를 통해 동적으로 계산됩니다.
# 참고용으로만 남겨둡니다.
#
# 문제점: 이전 계산 방식과 현재 알고리즘의 불일치로 인해 값이 부정확했음
# 해결: 동적 계산으로 전환하여 LLM 생성 코드와 동일한 알고리즘 사용

# [DEPRECATED] 케이스별 평균 (참고용)
_DEPRECATED_GROUND_TRUTH_CASE_MEANS = {
    '121': 116.360474,   # 실제: ~128.57
    '316': 105.333336,
    '734': 124.750000,
    '1579': 112.615158,
    '1580': 112.800003,
    '1598': 179.949997,
    '1845': 138.772766,
    '3417': 113.357964,
    '3594': 129.399994,
    '5359': 99.666664,
}

# [DEPRECATED] 환자별 최종 평균 (Ground Truth)
_DEPRECATED_GROUND_TRUTH_SUBJECT_MEANS = {
    '1': 129.399994,
    '2': 116.360474,    # 실제: ~128.57
    '4': 113.357964,
    '5': 124.750000,
    '6': 112.800003,
    '7': 112.615158,
    '32': 152.498505,
    '150': 101.555557,  # 실제: ~108.42
}

# [DEPRECATED] 전체 평균
_DEPRECATED_GROUND_TRUTH_OVERALL_MEAN = 120.417206


# =============================================================================
# 케이스 샘플링 (범용 유틸리티)
# =============================================================================

def sample_valid_case_ids(
    cohort_path: str = None,
    signal_base_path: str = None,
    sample_size: int = 100,
    seed: int = 42,
) -> List[int]:
    """
    유효한 케이스 ID 중에서 랜덤 샘플링
    
    범용적 설계:
    - 시그널 파일이 존재하고 유효한 시간 윈도우가 있는 케이스만 선택
    - 재현성을 위해 seed 고정
    
    Args:
        cohort_path: 코호트 메타데이터 CSV 경로
        signal_base_path: 시그널 파일들이 있는 디렉토리 경로
        sample_size: 샘플링할 케이스 수
        seed: 랜덤 시드 (재현성)
        
    Returns:
        선택된 케이스 ID 리스트
    """
    import random
    
    # 기본 경로 설정
    if signal_base_path is None:
        signal_base_path = PROJECT_ROOT / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0" / "vital_files"
    if cohort_path is None:
        cohort_path = PROJECT_ROOT / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0" / "clinical_data.csv"
    
    signal_base_path = Path(signal_base_path)
    cohort_path = Path(cohort_path)
    
    logging.info(f"📋 Sampling {sample_size} valid cases (seed={seed})...")
    
    # 1. 사용 가능한 시그널 파일 ID 수집
    vital_files = list(signal_base_path.glob("*.vital"))
    available_case_ids = set()
    for vf in vital_files:
        try:
            stem = vf.stem.lstrip('0') or '0'
            caseid = int(stem)
            available_case_ids.add(caseid)
        except ValueError:
            continue
    
    logging.info(f"   Available signal files: {len(available_case_ids)}")
    
    # 2. 시그널 파일이 존재하는 케이스만 필터링 (시간 윈도우 검증 없음)
    cohort = pd.read_csv(cohort_path)
    valid_case_ids = []
    
    for _, row in cohort.iterrows():
        case_id = int(row['caseid'])
        
        # 조건: 시그널 파일 존재
        if case_id not in available_case_ids:
            continue
        
        valid_case_ids.append(case_id)
    
    logging.info(f"   Valid cases (with signal file): {len(valid_case_ids)}")
    
    # 3. 랜덤 샘플링
    random.seed(seed)
    if sample_size >= len(valid_case_ids):
        selected = valid_case_ids
        logging.info(f"   ⚠️ Requested {sample_size} but only {len(valid_case_ids)} available, using all")
    else:
        selected = random.sample(valid_case_ids, sample_size)
        logging.info(f"   ✅ Sampled {len(selected)} cases")
    
    # 정렬 (재현성)
    selected = sorted(selected)
    logging.info(f"   Sample range: {min(selected)} ~ {max(selected)}")
    
    return selected


# =============================================================================
# 전체 모드 Ground Truth 계산 (동적)
# =============================================================================

def _process_single_case_ground_truth(args: Tuple) -> Dict[str, Any]:
    """
    단일 케이스 처리 (병렬 실행용 워커 함수)
    
    범용적 설계:
    - 파일 로드 함수를 외부에서 주입받을 수 있도록 구조화
    - 결과는 표준화된 딕셔너리로 반환
    - 전체 신호 데이터 사용 (시간 필터링 없음)
    
    Args:
        args: (case_info, caseid_to_file, signal_column, segment_duration)
        
    Returns:
        {
            'subj_id': str,
            'case_id': int,
            'segment_means': List[float],
            'status': 'success' | 'no_file' | 'no_signal' | 'error',
            'error': Optional[str]
        }
    """
    import vitaldb
    
    case_info, caseid_to_file, signal_column, segment_duration = args
    
    subj_id = case_info['subjectid']
    case_id = case_info['caseid']
    
    result = {
        'subj_id': subj_id,
        'case_id': case_id,
        'segment_means': [],
        'status': 'unknown',
        'error': None
    }
    
    # 파일 존재 확인
    if case_id not in caseid_to_file:
        result['status'] = 'no_file'
        return result
    
    vital_path = caseid_to_file[case_id]
    
    try:
        # VitalDB 파일 로드 (데이터소스 특화 부분 - 다른 데이터셋에서는 이 부분만 교체)
        vf = vitaldb.read_vital(str(vital_path), [signal_column])
        vals = vf.to_numpy([signal_column], 1)  # 1초 간격 샘플링
        
        # 2D -> 1D 변환
        if vals is not None and hasattr(vals, 'ndim') and vals.ndim == 2:
            vals = vals.flatten() if vals.shape[1] == 1 else vals[:, 0]
        
        if vals is None or len(vals) == 0:
            result['status'] = 'no_signal'
            return result
        
        # ================================================================
        # Time 값 기반 Segmentation (LLM 생성 코드와 동일한 방식)
        # ================================================================
        # Time 배열 생성 (1초 간격 리샘플링이므로 인덱스 = 시간(초))
        time_vals = np.arange(len(vals))
        
        # 각 데이터 포인트의 segment 할당 (Time // segment_duration)
        segment_indices = (time_vals // segment_duration).astype(int)
        unique_segments = np.unique(segment_indices)
        
        segment_means = []
        for seg in unique_segments:
            # 해당 segment의 값들 추출
            segment_vals = vals[segment_indices == seg]
            # NaN 제외하고 평균 계산
            valid_vals = segment_vals[~np.isnan(segment_vals)]
            if len(valid_vals) > 0:
                segment_means.append(float(np.mean(valid_vals)))
        
        result['segment_means'] = segment_means
        result['status'] = 'success' if segment_means else 'no_segments'
        return result
        
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        return result


def compute_full_ground_truth(
    signal_base_path: str = None,
    cohort_path: str = None,
    segment_duration_seconds: float = 600,
    signal_column: str = "Solar8000/NIBP_SBP",
    max_workers: int = 8,
    case_ids: List[int] = None,
) -> Tuple[Dict[str, float], float, Dict[str, Any]]:
    """
    전체 시그널에서 Ground Truth 동적 계산 (병렬 처리 버전)
    
    범용적 설계:
    - 케이스 단위 병렬 처리로 I/O 병목 최소화
    - 결과 집계는 entity_id(subject) 기준으로 유연하게 처리
    - 다른 데이터셋 적용 시 _process_single_case_ground_truth의 파일 로드 부분만 수정
    
    Args:
        signal_base_path: 시그널 파일들이 있는 디렉토리 경로
        cohort_path: 코호트 메타데이터 CSV 경로
        segment_duration_seconds: segmentation 단위 (초)
        signal_column: 분석할 시그널 컬럼명
        max_workers: 병렬 처리 워커 수 (기본: 8)
        case_ids: 처리할 케이스 ID 리스트 (None이면 전체)
        
    Returns:
        (subject_means, overall_mean, stats)
        - subject_means: {subjectid: mean} 딕셔너리
        - overall_mean: 전체 환자 평균의 평균
        - stats: 통계 정보 (selected_case_ids 포함)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from collections import defaultdict
    import vitaldb
    
    # 기본 경로 설정 (VitalDB 특화 - 다른 데이터셋에서는 변경)
    if signal_base_path is None:
        signal_base_path = PROJECT_ROOT / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0" / "vital_files"
    if cohort_path is None:
        cohort_path = PROJECT_ROOT / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0" / "clinical_data.csv"
    
    signal_base_path = Path(signal_base_path)
    cohort_path = Path(cohort_path)
    
    # case_ids를 set으로 변환 (빠른 lookup)
    case_ids_filter = set(case_ids) if case_ids else None
    
    logging.info("=" * 60)
    logging.info("🔬 Computing Full Ground Truth (Parallel Processing)")
    logging.info("=" * 60)
    logging.info(f"   Signal Path: {signal_base_path}")
    logging.info(f"   Cohort Path: {cohort_path}")
    logging.info(f"   Segment Duration: {segment_duration_seconds} seconds")
    logging.info(f"   Signal Column: {signal_column}")
    logging.info(f"   Workers: {max_workers}")
    if case_ids_filter:
        logging.info(f"   🎯 FILTERED: {len(case_ids_filter)} cases selected")
    logging.info("=" * 60)
    
    # 1. Cohort 로드
    logging.info("📂 Loading cohort data...")
    cohort = pd.read_csv(cohort_path)
    logging.info(f"   Total cases in cohort: {len(cohort)}")
    
    # 2. 시그널 파일 매핑 (VitalDB 특화 - 다른 데이터셋에서는 변경)
    vital_files = list(signal_base_path.glob("*.vital"))
    logging.info(f"   Total signal files: {len(vital_files)}")
    
    caseid_to_file = {}
    for vf in vital_files:
        try:
            stem = vf.stem.lstrip('0') or '0'
            caseid = int(stem)
            caseid_to_file[caseid] = vf
        except ValueError:
            continue
    
    logging.info(f"   Mapped case IDs: {len(caseid_to_file)}")
    
    # 3. 모든 케이스를 플랫 리스트로 준비 (병렬 처리용) - 전체 신호 사용 (시간 필터링 없음)
    all_cases = []
    for _, row in cohort.iterrows():
        subj_id = str(row['subjectid'])
        case_id = int(row['caseid'])
        
        # case_ids 필터 적용 (지정된 경우)
        if case_ids_filter and case_id not in case_ids_filter:
            continue
        
        all_cases.append({
            'subjectid': subj_id,
            'caseid': case_id,
        })
    
    logging.info(f"   Valid cases to process: {len(all_cases)}")
    if case_ids_filter:
        logging.info(f"   (filtered from {len(case_ids_filter)} requested)")
    
    # 4. 병렬 처리 실행
    logging.info(f"\n🚀 Starting parallel processing ({max_workers} workers)...")
    
    start_time = time.time()
    results = []
    
    # 진행 상황 추적
    total_cases = len(all_cases)
    completed = 0
    log_interval = max(1, total_cases // 20)  # 5% 단위
    
    # 첫 케이스 디버그 플래그
    first_success_logged = False
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 모든 케이스에 대해 Future 생성
        futures = {
            executor.submit(
                _process_single_case_ground_truth,
                (case, caseid_to_file, signal_column, segment_duration_seconds)
            ): case
            for case in all_cases
        }
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1
            
            # 첫 번째 성공 케이스 디버그 출력
            if not first_success_logged and result['status'] == 'success' and result['segment_means']:
                logging.info(f"   🔍 First successful case: {result['case_id']}")
                logging.info(f"      Subject: {result['subj_id']}")
                logging.info(f"      Segments: {len(result['segment_means'])}")
                logging.info(f"      Mean: {np.mean(result['segment_means']):.2f}")
                first_success_logged = True
            
            # 진행 상황 로그
            if completed % log_interval == 0 or completed == total_cases:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total_cases - completed) / rate if rate > 0 else 0
                logging.info(
                    f"   Progress: {completed}/{total_cases} cases "
                    f"({completed/total_cases*100:.1f}%, {elapsed:.1f}s, ETA: {eta:.0f}s)"
                )
    
    # 5. 결과 집계 (Subject별)
    logging.info("\n📊 Aggregating results by subject...")
    
    subject_segment_means = defaultdict(list)
    status_counts = defaultdict(int)
    
    for r in results:
        status_counts[r['status']] += 1
        if r['status'] == 'success' and r['segment_means']:
            subject_segment_means[r['subj_id']].extend(r['segment_means'])
    
    # Subject별 평균 계산
    subject_means = {}
    for subj_id, means in subject_segment_means.items():
        if means:
            subject_means[subj_id] = float(np.mean(means))
    
    elapsed = time.time() - start_time
    
    # 6. 전체 평균 계산
    overall_mean = float(np.mean(list(subject_means.values()))) if subject_means else float('nan')
    
    # 처리된 케이스 ID와 Subject ID 수집
    processed_case_ids = [r['case_id'] for r in results if r['status'] == 'success']
    processed_subject_ids = list(subject_means.keys())
    
    # 7. 통계 정보
    stats = {
        'total_cases_in_cohort': len(all_cases),
        'processed_subjects': len(subject_means),
        'status_counts': dict(status_counts),
        'computation_time_seconds': elapsed,
        'cases_per_second': len(all_cases) / elapsed if elapsed > 0 else 0,
        # 파이프라인에서 동일한 케이스를 사용하기 위한 정보
        'processed_case_ids': processed_case_ids,
        'processed_subject_ids': processed_subject_ids,
    }
    
    logging.info("\n" + "=" * 60)
    logging.info("✅ Ground Truth Computation Complete")
    logging.info("=" * 60)
    logging.info(f"   Processed subjects: {len(subject_means)}")
    logging.info(f"   Total cases processed: {status_counts.get('success', 0)}")
    logging.info(f"   Status breakdown:")
    for status, count in sorted(status_counts.items()):
        logging.info(f"      - {status}: {count}")
    logging.info(f"   Overall mean: {overall_mean:.4f}" if not np.isnan(overall_mean) else "   Overall mean: NaN")
    logging.info(f"   Computation time: {elapsed:.2f}s ({stats['cases_per_second']:.1f} cases/s)")
    logging.info("=" * 60)
    
    return subject_means, overall_mean, stats


# =============================================================================
# Ground Truth 비교 함수
# =============================================================================

def compare_numeric(result: Any, expected: float, tolerance: float = 0.05) -> tuple:
    """
    숫자 결과 비교 (다양한 형태 지원)
    
    Args:
        result: 비교할 결과 값
        expected: 기대값
        tolerance: 허용 오차 (상대 오차, 기본 5%)
    
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
        if len(result) == 1:
            result = list(result.values())[0]
        elif 'mean' in result:
            result = result['mean']
        elif 'overall_mean' in result:
            result = result['overall_mean']
    
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


def compare_dict_means(result: Any, expected: Dict[str, float], tolerance: float = 0.05) -> tuple:
    """
    환자별 평균 딕셔너리 비교
    
    Returns:
        (is_match, message)
    """
    # DataFrame을 dict로 변환
    if isinstance(result, pd.DataFrame):
        if 'subjectid' in result.columns and 'mean' in result.columns:
            result = dict(zip(result['subjectid'].astype(str), result['mean']))
        elif 'subject_id' in result.columns and 'mean' in result.columns:
            result = dict(zip(result['subject_id'].astype(str), result['mean']))
        elif 'mean' in result.columns:
            result = result['mean'].to_dict()
            result = {str(k): v for k, v in result.items()}
        else:
            return False, f"Cannot extract subject means from DataFrame: {result.columns.tolist()}"
    
    if not isinstance(result, dict):
        return False, f"Result is not a dict: {type(result)}"
    
    messages = []
    all_match = True
    matched = 0
    total = len(expected)
    mismatched = 0
    missing = 0
    
    for subj_id, exp_val in expected.items():
        # subjectid 타입 맞추기
        subj_key = None
        for key in [subj_id, str(subj_id), int(subj_id) if subj_id.isdigit() else subj_id]:
            if key in result:
                subj_key = key
                break
        
        if subj_key is None:
            missing += 1
            if missing <= 5:  # 처음 5개만 로그
                messages.append(f"  ❌ Subject {subj_id}: MISSING")
            all_match = False
            continue
        
        res_val = result[subj_key]
        if isinstance(res_val, float) and np.isnan(res_val):
            messages.append(f"  ❌ Subject {subj_id}: NaN (expected {exp_val:.4f})")
            all_match = False
            continue
        
        try:
            res_val = float(res_val)
        except (TypeError, ValueError):
            messages.append(f"  ❌ Subject {subj_id}: Cannot convert {res_val}")
            all_match = False
            continue
        
        diff = abs(res_val - exp_val)
        rel_diff = diff / abs(exp_val) if exp_val != 0 else diff
        
        if rel_diff <= tolerance:
            matched += 1
            # 전체 모드에서는 상세 로그 생략
            if total <= 20:
                messages.append(f"  ✅ Subject {subj_id}: {res_val:.4f} ≈ {exp_val:.4f}")
        else:
            mismatched += 1
            if mismatched <= 10:  # 처음 10개만 로그
                messages.append(f"  ❌ Subject {subj_id}: {res_val:.4f} ≠ {exp_val:.4f} (diff: {rel_diff*100:.2f}%)")
            all_match = False
    
    # 요약
    summary_parts = [f"Matched: {matched}/{total}"]
    if missing > 0:
        summary_parts.append(f"Missing: {missing}")
    if mismatched > 0:
        summary_parts.append(f"Mismatched: {mismatched}")
    
    summary = ", ".join(summary_parts)
    
    if total > 20:
        messages.insert(0, f"  (Showing first few mismatches, {matched} subjects matched)")
    
    return all_match, summary + "\n" + "\n".join(messages)


# =============================================================================
# 테스트 실행
# =============================================================================

def run_full_pipeline_test(
    full_mode: bool = False,
    verbose: bool = False,
    validate: bool = True,
    max_signal_cases: int = None,  # None이면 기본값 사용
    force_mapreduce: bool = False,  # Map-Reduce 강제 사용
    batch_size: int = 100,
    sample_size: int = 0,  # 샘플 케이스 수 (0이면 전체)
) -> bool:
    """
    전체 파이프라인 테스트 실행
    
    ExtractionAgent → DataContext → AnalysisAgent
    
    Args:
        full_mode: True면 전체/샘플 시그널 대상, False면 특정 subjectid 대상
        verbose: 상세 로그 출력
        validate: Ground Truth와 비교 여부
        max_signal_cases: Signal 로드 시 최대 케이스 수 (0: 무제한)
        sample_size: 샘플링할 케이스 수 (0이면 전체, >0이면 랜덤 샘플)
    
    Returns:
        모든 테스트 성공 여부
    """
    from OrchestrationAgent.src.orchestrator import Orchestrator
    from OrchestrationAgent.src.config import OrchestratorConfig
    from shared.data.context import DataContext
    
    # 캐시 클리어 (재현성 보장)
    DataContext.clear_cache()
    logging.info("🗑️ Cache cleared for reproducibility")
    
    # ==================================================
    # Ground Truth 및 쿼리 설정
    # ==================================================
    if full_mode:
        # 샘플 모드 vs 전체 모드
        if sample_size > 0:
            # 샘플 모드: 지정된 수의 케이스만 선택
            logging.info(f"\n🎯 SAMPLE MODE: Selecting {sample_size} cases...")
            selected_case_ids = sample_valid_case_ids(sample_size=sample_size)
            
            logging.info(f"\n🔬 Computing Ground Truth for {len(selected_case_ids)} sampled cases...")
            subject_means, overall_mean, gt_stats = compute_full_ground_truth(
                case_ids=selected_case_ids
            )
            
            # 쿼리 생성 (선택된 케이스만 대상)
            # 케이스 ID 리스트를 쿼리에 포함
            case_ids_str = ", ".join(str(c) for c in selected_case_ids)
            
            queries = [
                # Query 1: 환자별 SBP 평균 (선택된 케이스)
                (
                    f"caseid가 [{case_ids_str}] 중 하나인 케이스들에 대해서만: "
                    "NIBP_SBP(Solar8000/NIBP_SBP) 값을 10분(600초) 단위로 segmentation 해서 "
                    "각 segment의 평균을 구하고, 환자별로 모든 segment 평균들을 다시 평균내서 "
                    "환자당 SBP 평균을 구해줘. "
                    "한 환자가 여러 번 수술한 경우(같은 subjectid의 여러 caseid)는 "
                    "모든 수술의 segment를 합쳐서 하나의 평균을 구해줘. "
                    "결과는 {subjectid: mean} 형태의 dictionary로 반환해줘.",
                    lambda result, sm=subject_means: compare_dict_means(result, sm)
                ),
                # Query 2: 전체 평균 (선택된 케이스의 환자 평균의 평균)
                (
                    f"caseid가 [{case_ids_str}] 중 하나인 케이스들에 대해서만: "
                    "NIBP_SBP(Solar8000/NIBP_SBP) 값을 10분(600초) 단위로 segmentation 해서 "
                    "각 segment의 평균을 구하고, 환자별로 모든 segment 평균들을 다시 평균내서 "
                    "환자당 SBP 평균을 구한 후, "
                    "모든 환자의 평균을 다시 평균내서 전체 평균을 구해줘. "
                    "한 환자가 여러 번 수술한 경우(같은 subjectid의 여러 caseid)는 "
                    "모든 수술의 segment를 합쳐서 하나의 평균을 구해줘. "
                    "결과는 단일 float 값으로 반환해줘.",
                    lambda result, om=overall_mean: compare_numeric(result, om)
                ),
            ]
            
            test_info = {
                'mode': f'SAMPLE ({sample_size})',
                'description': f'Sampled {len(selected_case_ids)} cases',
                'subjects_count': gt_stats['processed_subjects'],
                'cases_count': len(selected_case_ids),
                'selected_case_ids': selected_case_ids,
            }
        else:
            # 전체 모드: Ground Truth 동적 계산 (모든 케이스)
            logging.info("\n🔬 FULL MODE: Computing Ground Truth from all signals...")
            subject_means, overall_mean, gt_stats = compute_full_ground_truth()
            
            # 쿼리 생성 (전체 환자 대상)
            queries = [
                # Query 1: 환자별 SBP 평균 (전체 환자)
                (
                    "모든 환자들의 "
                    "NIBP_SBP(Solar8000/NIBP_SBP) 값을 10분(600초) 단위로 segmentation 해서 "
                    "각 segment의 평균을 구하고, 환자별로 모든 segment 평균들을 다시 평균내서 "
                    "환자당 SBP 평균을 구해줘. "
                    "한 환자가 여러 번 수술한 경우(같은 subjectid의 여러 caseid)는 "
                    "모든 수술의 segment를 합쳐서 하나의 평균을 구해줘. "
                    "결과는 {subjectid: mean} 형태의 dictionary로 반환해줘.",
                    lambda result: compare_dict_means(result, subject_means)
                ),
                # Query 2: 전체 평균 (환자 평균의 평균)
                (
                    "모든 환자들의 "
                    "NIBP_SBP(Solar8000/NIBP_SBP) 값을 10분(600초) 단위로 segmentation 해서 "
                    "각 segment의 평균을 구하고, 환자별로 모든 segment 평균들을 다시 평균내서 "
                    "환자당 SBP 평균을 구한 후, "
                    "모든 환자의 평균을 다시 평균내서 전체 평균을 구해줘. "
                    "한 환자가 여러 번 수술한 경우(같은 subjectid의 여러 caseid)는 "
                    "모든 수술의 segment를 합쳐서 하나의 평균을 구해줘. "
                    "결과는 단일 float 값으로 반환해줘.",
                    lambda result: compare_numeric(result, overall_mean)
                ),
            ]
            
            test_info = {
                'mode': 'FULL',
                'description': 'All patients (no filter)',
                'subjects_count': gt_stats['processed_subjects'],
                'cases_count': gt_stats.get('status_counts', {}).get('success', 0),
            }
        
        # Config 설정: 전체/샘플 케이스 로드 (max_signal_cases=0)
        if max_signal_cases is None:
            max_signal_cases = 0  # 무제한
        
        # sample_size > 0이면 해당 케이스 수만큼만 로드하도록 설정
        if sample_size > 0 and max_signal_cases == 0:
            max_signal_cases = sample_size
    else:
        # 기본 모드: 특정 케이스만 대상으로 동적 Ground Truth 계산
        # SUBJECT_CASES에서 케이스 ID 추출
        default_case_ids = []
        for case_list in SUBJECT_CASES.values():
            default_case_ids.extend(case_list)
        
        logging.info(f"\n🔬 Computing Ground Truth for default test cases ({len(default_case_ids)} cases)...")
        subject_means, overall_mean, gt_stats = compute_full_ground_truth(
            case_ids=default_case_ids
        )
        
        # 쿼리 생성 (특정 subjectid 대상)
        queries = [
            # Query 1: 환자별 SBP 평균 (특정 환자)
            (
                f"subjectid가 {DEFAULT_TEST_SUBJECT_IDS_STR}인 환자들의 "
                f"NIBP_SBP(Solar8000/NIBP_SBP) 값을 10분(600초) 단위로 segmentation 해서 "
                f"각 segment의 평균을 구하고, 환자별로 모든 segment 평균들을 다시 평균내서 "
                f"환자당 SBP 평균을 구해줘. "
                f"한 환자가 여러 번 수술한 경우(같은 subjectid의 여러 caseid)는 "
                f"모든 수술의 segment를 합쳐서 하나의 평균을 구해줘. "
                f"결과는 {{subjectid: mean}} 형태의 dictionary로 반환해줘.",
                lambda result, sm=subject_means: compare_dict_means(result, sm)
            ),
            # Query 2: 전체 평균 (환자 평균의 평균)
            (
                f"subjectid가 {DEFAULT_TEST_SUBJECT_IDS_STR}인 환자들의 "
                f"NIBP_SBP(Solar8000/NIBP_SBP) 값을 10분(600초) 단위로 segmentation 해서 "
                f"각 segment의 평균을 구하고, 환자별로 모든 segment 평균들을 다시 평균내서 "
                f"환자당 SBP 평균을 구한 후, "
                f"모든 환자의 평균을 다시 평균내서 전체 평균을 구해줘. "
                f"한 환자가 여러 번 수술한 경우(같은 subjectid의 여러 caseid)는 "
                f"모든 수술의 segment를 합쳐서 하나의 평균을 구해줘. "
                f"결과는 단일 float 값으로 반환해줘.",
                lambda result, om=overall_mean: compare_numeric(result, om)
            ),
        ]
        
        # Config 설정: 기본값 유지 (max_signal_cases=10)
        if max_signal_cases is None:
            max_signal_cases = 10
        
        test_info = {
            'mode': 'DEFAULT',
            'description': f'Selected subjects: {DEFAULT_TEST_SUBJECT_IDS}',
            'subjects_count': gt_stats['processed_subjects'],
            'cases_count': len(default_case_ids),
        }
    
    # ==================================================
    # 테스트 시작
    # ==================================================
    logging.info("\n" + "=" * 70)
    logging.info("  Signal Segmentation Mean - End-to-End Test")
    logging.info("=" * 70)
    logging.info("  Pipeline: ExtractionAgent → DataContext → AnalysisAgent")
    logging.info("  Feature: 10-minute segmentation, multi-surgery patient aggregation")
    logging.info(f"  Mode: {test_info['mode']} ({test_info['description']})")
    logging.info(f"  Max Signal Cases: {max_signal_cases if max_signal_cases > 0 else 'UNLIMITED'}")
    if validate:
        logging.info("  Validation: Ground Truth ✓")
        logging.info(f"  Test Subjects: {test_info['subjects_count']}")
        logging.info(f"  Test Cases: {test_info['cases_count']}")
    logging.info("=" * 70)
    
    # Orchestrator 설정
    if force_mapreduce:
        # Map-Reduce 강제 모드
        execution_mode = "mapreduce"
        logging.info(f"   🗺️ Execution Mode: MAPREDUCE (forced)")
    elif full_mode:
        # 전체 모드: Auto 모드 (케이스 수에 따라 자동 선택)
        execution_mode = "auto"
        logging.info(f"   🔄 Execution Mode: AUTO (threshold: 100 cases)")
    else:
        # 기본 모드: 표준 실행
        execution_mode = "standard"
        logging.info(f"   ⚡ Execution Mode: STANDARD")
    
    if full_mode or force_mapreduce:
        config = OrchestratorConfig(
            max_signal_cases=max_signal_cases,
            max_retries=2,
            execution_mode=execution_mode,
            mapreduce_threshold=100,  # 100개 이상이면 Map-Reduce
            batch_size=batch_size,
            mapreduce_max_workers=4,
        )
    else:
        # 기본 모드: 표준 실행
        config = OrchestratorConfig(
            max_signal_cases=max_signal_cases,
            max_retries=2,
        )
    orchestrator = Orchestrator(config=config)
    
    test_results = []
    
    for i, query_item in enumerate(queries, 1):
        # 쿼리와 validator 분리
        if isinstance(query_item, tuple):
            query, validator = query_item
        else:
            query, validator = query_item, None
        
        logging.info(f"\n{'='*60}")
        logging.info(f"[Test {i}/{len(queries)}]")
        logging.info(f"Query: {query[:100]}..." if len(query) > 100 else f"Query: {query}")
        logging.info("=" * 60)
        
        start_time = time.time()
        
        # 전체 파이프라인 실행 (모드에 따라 선택)
        if force_mapreduce:
            # Map-Reduce 강제 실행
            def progress_callback(batch_idx, total_batches, processed):
                logging.info(f"   📦 Batch {batch_idx+1}/{total_batches}: {processed} cases processed")
            
            result = orchestrator.run_mapreduce(
                query,
                batch_size=batch_size,
                progress_callback=progress_callback,
            )
        elif full_mode:
            # Auto 모드 실행 (케이스 수에 따라 standard/mapreduce 자동 선택)
            def progress_callback(batch_idx, total_batches, processed):
                logging.info(f"   📦 Batch {batch_idx+1}/{total_batches}: {processed} cases processed")
            
            result = orchestrator.run_auto(
                query,
                progress_callback=progress_callback,
            )
        else:
            # 표준 모드
            result = orchestrator.run(query)
        
        elapsed = time.time() - start_time
        
        if result.status == "success":
            logging.info(f"✅ Execution SUCCESS ({elapsed:.2f}s)")
            logging.info(f"   Result Type: {type(result.result).__name__}")
            
            # 결과 미리보기
            if isinstance(result.result, dict):
                logging.info(f"   Result (dict): {len(result.result)} items")
                for k, v in list(result.result.items())[:3]:
                    logging.info(f"      {k}: {v}")
                if len(result.result) > 3:
                    logging.info(f"      ... ({len(result.result) - 3} more)")
            else:
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


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Signal Segmentation Mean - End-to-End Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 기본 모드 (특정 환자, 빠른 테스트)
    python test_e2e_signal_segmentation_mean.py
    
    # 전체 모드 (모든 환자, Auto 모드로 실행)
    python test_e2e_signal_segmentation_mean.py --full
    
    # 전체 모드 + Map-Reduce 강제 사용
    python test_e2e_signal_segmentation_mean.py --full --mapreduce
    
    # Map-Reduce 배치 크기 설정
    python test_e2e_signal_segmentation_mean.py --full --mapreduce --batch-size 50
    
    # 전체 모드 + 상세 로그
    python test_e2e_signal_segmentation_mean.py --full --verbose
    
    # 케이스 수 제한 설정
    python test_e2e_signal_segmentation_mean.py --full --max-cases 100
    
    # Ground Truth 검증 비활성화
    python test_e2e_signal_segmentation_mean.py --no-validate

Execution Modes:
    STANDARD (기본):
        - 모든 데이터를 메모리에 로드 후 단일 코드 실행
        - 소량 데이터에 적합 (< 100 케이스)
    
    AUTO (--full):
        - 케이스 수에 따라 STANDARD/MAPREDUCE 자동 선택
        - 100개 이상이면 자동으로 Map-Reduce 전환
    
    MAPREDUCE (--mapreduce):
        - 배치 단위 처리로 메모리 효율적
        - 대용량 데이터에 적합 (1000+ 케이스)
        - map_func: 케이스별 처리, reduce_func: 최종 집계

Test Modes:
    DEFAULT (기본):
        - 특정 환자 대상: subjectid 1, 2, 4, 5, 6, 7, 32, 150
        - 사전 계산된 Ground Truth 사용
        - 빠른 실행 (약 30초)
    
    SAMPLE (--full --sample-size N):
        - 랜덤하게 N개의 케이스를 선택
        - Ground Truth와 파이프라인 모두 동일한 케이스 사용
        - 빠른 검증에 적합 (기본: 100개)
    
    FULL (--full --sample-size 0):
        - 모든 환자 대상 (필터 없음)
        - Ground Truth 동적 계산 (전체 .vital 파일 스캔)
        - Auto 모드 사용 (케이스 수에 따라 자동 선택)

Test Details:
    - Signal: NIBP_SBP (Solar8000/NIBP_SBP)
    - Segmentation: 10 minutes (600 seconds)
    - Time Window: Full signal data (no temporal filtering)
    - Multi-Case: Aggregate all segments across cases per patient
        """
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="전체 모드: 모든 환자 대상으로 테스트 (Ground Truth 동적 계산)"
    )
    parser.add_argument(
        "--sample-size", "-s",
        type=int,
        default=100,
        help="샘플링할 케이스 수 (기본: 100, 0이면 전체 케이스)"
    )
    parser.add_argument(
        "--mapreduce", "-m",
        action="store_true",
        help="Map-Reduce 모드 강제 사용 (대용량 데이터 배치 처리)"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=100,
        help="Map-Reduce 배치 크기 (기본: 100)"
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
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Signal 로드 시 최대 케이스 수 (0: 무제한, 기본: --full이면 0, 아니면 10)"
    )
    parser.add_argument(
        "--query", "-q",
        type=int,
        choices=[1, 2],
        help="특정 쿼리만 테스트 (1: 환자별 평균, 2: 전체 평균) - 기본 모드에서만 지원"
    )
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    
    # LLM 로깅 활성화 (생성된 코드, 프롬프트, 응답 저장)
    from shared.llm import enable_llm_logging
    log_session_dir = enable_llm_logging("./data/llm_logs")
    logging.info(f"📝 LLM Logs: {log_session_dir}")
    
    validate = not args.no_validate
    
    try:
        success = run_full_pipeline_test(
            full_mode=args.full,
            verbose=args.verbose,
            validate=validate,
            max_signal_cases=args.max_cases,
            force_mapreduce=args.mapreduce,
            batch_size=args.batch_size,
            sample_size=args.sample_size if args.full else 0,  # full 모드에서만 샘플링
        )
        sys.exit(0 if success else 1)
    
    except Exception as e:
        logging.exception(f"Test failed with exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
