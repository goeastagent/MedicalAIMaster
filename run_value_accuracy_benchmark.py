#!/usr/bin/env python
"""
Value Accuracy Benchmark
========================

난이도별 4개 데이터셋(Low/Mid/High/Multi-Case)을 순차 실행하고,
성능 요약 테이블 3종을 자동 생성하는 벤치마크 스크립트.

사용법:
    # 전체 벤치마크 실행
    python run_value_accuracy_benchmark.py

    # 특정 데이터셋만 실행
    python run_value_accuracy_benchmark.py --datasets low mid

    # 로그 레벨 조정
    python run_value_accuracy_benchmark.py --log-level WARNING

결과물:
    Evaluation/ValueAccuracy/
    └── benchmark_YYYYMMDD_HHMMSS.xlsx
        ├── Summary          (Table 1: 난이도별 정확도)
        ├── Format_Breakdown (Table 2: 응답 형식별 분석)
        ├── Error_Analysis   (Table 3: 오류 유형 분류)
        ├── Detail_Low       (Low 상세 결과)
        ├── Detail_Mid       (Mid 상세 결과)
        ├── Detail_High      (High 상세 결과)
        └── Detail_Multi     (Multi-Case 상세 결과)
"""

import sys
import json
import logging
import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from test_qa_dataset import (
    load_qa_pairs,
    run_qa_test,
    setup_logging,
    compare_values,
)
from OrchestrationAgent.src.orchestrator import Orchestrator
from shared.llm import enable_llm_logging, get_current_model_name

logger = logging.getLogger(__name__)

# ============================================================
# Dataset Configuration
# ============================================================

BENCHMARK_DATASETS = [
    {
        "key": "low",
        "name": "Single-Case Low",
        "path": "testdata/vitaldb_low_qa_pairs_explicit.json",
        "difficulty": "Low",
        "scope": "Single",
        "description": "Basic statistics (max/min/mean/median)",
        "detail_sheet": "Detail_Low",
    },
    {
        "key": "mid",
        "name": "Single-Case Mid",
        "path": "testdata/vitaldb_mid_qa_pairs_explicit.json",
        "difficulty": "Mid",
        "scope": "Single",
        "description": "Time-range conditioned stats",
        "detail_sheet": "Detail_Mid",
    },
    {
        "key": "high",
        "name": "Single-Case High",
        "path": "testdata/vitaldb_high_qa_pairs_explicit.json",
        "difficulty": "High",
        "scope": "Single",
        "description": "Signal processing (filter/resample/window)",
        "detail_sheet": "Detail_High",
    },
    {
        "key": "multi",
        "name": "Multi-Case (3)",
        "path": "testdata/case3_low_dataset.json",
        "difficulty": "Low",
        "scope": "Multi",
        "description": "Batch stats across 3 patients",
        "detail_sheet": "Detail_Multi",
    },
]

DATASET_KEY_MAP = {ds["key"]: ds for ds in BENCHMARK_DATASETS}


# ============================================================
# Dataset Pre-processing
# ============================================================

def preprocess_qa_pairs(qa_pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """누락된 필드(format, parameter)에 기본값을 부여한다."""
    for qa in qa_pairs:
        if "format" not in qa:
            answer = qa.get("corrected_answer", qa.get("answer"))
            if isinstance(answer, list):
                qa["format"] = "list"
            elif isinstance(answer, dict):
                qa["format"] = "dict"
            elif isinstance(answer, str):
                try:
                    parsed = json.loads(answer)
                    qa["format"] = "list" if isinstance(parsed, list) else "dict" if isinstance(parsed, dict) else "float"
                except (json.JSONDecodeError, ValueError):
                    qa["format"] = "float"
            else:
                qa["format"] = "float"
        if "parameter" not in qa:
            qa["parameter"] = "N/A"
    return qa_pairs


# ============================================================
# Error Classification
# ============================================================

def classify_error(result: Dict[str, Any]) -> str:
    """
    테스트 결과의 reason/에러메시지를 분석하여 에러 카테고리를 반환한다.

    Categories:
        - Correct              : 정답
        - Wrong Value (<=5%)   : 값 불일치 (상대오차 5% 이내)
        - Wrong Value (>5%)    : 값 불일치 (상대오차 5% 초과)
        - Type Mismatch        : 타입/구조 불일치 (dict vs float 등)
        - Wrong Parameter      : 올바른 파라미터를 사용하지 않음
        - Execution Failure    : Orchestrator가 실행 실패 반환
        - Exception            : 예외 발생
    """
    if result["점수"] == 1:
        return "Correct"

    reason = result.get("사유", "")
    error_msg = result.get("에러메시지", "")
    param_match = result.get("컬럼일치", "N/A")

    if "예외 발생" in reason:
        return "Exception"

    if "실행 실패" in reason:
        return "Execution Failure"

    if "타입 불일치" in reason or "필수 키 누락" in reason:
        return "Type Mismatch"

    if param_match == "X":
        return "Wrong Parameter"

    rel_error = _extract_relative_error(result)
    if rel_error is not None:
        return "Wrong Value (<=5%)" if rel_error <= 0.05 else "Wrong Value (>5%)"

    return "Wrong Value (>5%)"


def _extract_relative_error(result: Dict[str, Any]) -> Optional[float]:
    """reason 문자열에서 expected != actual 패턴을 찾아 상대오차를 계산한다."""
    reason = result.get("사유", "")
    match = re.search(r"([\-\d.e+]+)\s*!=\s*([\-\d.e+]+)", reason)
    if not match:
        return None
    try:
        expected = float(match.group(1))
        actual = float(match.group(2))
        if expected == 0:
            return abs(actual)
        return abs(expected - actual) / abs(expected)
    except (ValueError, ZeroDivisionError):
        return None


# ============================================================
# Table Generators
# ============================================================

def generate_accuracy_table(
    all_results: Dict[str, List[Dict[str, Any]]],
    datasets: List[Dict[str, Any]],
    model_name: str,
) -> pd.DataFrame:
    """Table 1: 난이도별 핵심 성능 테이블"""
    rows = []
    total_queries = 0
    total_correct = 0
    total_param_match = 0
    total_param_applicable = 0
    all_latencies = []
    total_failures = 0

    for ds in datasets:
        results = all_results.get(ds["key"], [])
        if not results:
            continue

        n = len(results)
        correct = sum(1 for r in results if r["점수"] == 1)
        accuracy = (correct / n * 100) if n > 0 else 0.0

        param_applicable = [r for r in results if r["컬럼일치"] in ("O", "X")]
        param_ok = sum(1 for r in param_applicable if r["컬럼일치"] == "O")
        param_pct = (param_ok / len(param_applicable) * 100) if param_applicable else None

        latencies = [r["실행시간(ms)"] for r in results if r["실행시간(ms)"] is not None]
        avg_lat = np.mean(latencies) if latencies else None

        failures = sum(1 for r in results if r["에러메시지"])

        rows.append({
            "Dataset": ds["name"],
            "Difficulty": ds["difficulty"],
            "Scope": ds["scope"],
            "Queries": n,
            "Correct": correct,
            "Value Accuracy (%)": round(accuracy, 2),
            "Param Match (%)": round(param_pct, 2) if param_pct is not None else "N/A",
            "Avg Latency (ms)": round(avg_lat, 1) if avg_lat is not None else "N/A",
            "Exec Failures": failures,
        })

        total_queries += n
        total_correct += correct
        total_param_match += param_ok
        total_param_applicable += len(param_applicable)
        all_latencies.extend(latencies)
        total_failures += failures

    overall_acc = (total_correct / total_queries * 100) if total_queries > 0 else 0
    overall_param = (total_param_match / total_param_applicable * 100) if total_param_applicable > 0 else None
    overall_lat = np.mean(all_latencies) if all_latencies else None

    rows.append({
        "Dataset": "Overall",
        "Difficulty": "-",
        "Scope": "-",
        "Queries": total_queries,
        "Correct": total_correct,
        "Value Accuracy (%)": round(overall_acc, 2),
        "Param Match (%)": round(overall_param, 2) if overall_param is not None else "N/A",
        "Avg Latency (ms)": round(overall_lat, 1) if overall_lat is not None else "N/A",
        "Exec Failures": total_failures,
    })

    df = pd.DataFrame(rows)
    df.attrs["model"] = model_name
    return df


def generate_format_breakdown_table(
    all_results: Dict[str, List[Dict[str, Any]]],
    datasets: List[Dict[str, Any]],
) -> pd.DataFrame:
    """Table 2: 응답 형식(float/dict/list)별 정확도 분석"""
    format_types = ["float", "dict", "list"]
    ds_keys = [ds["key"] for ds in datasets]

    rows = []
    for fmt in format_types:
        row: Dict[str, Any] = {"Format": fmt}
        total = 0
        correct = 0

        for ds in datasets:
            results = all_results.get(ds["key"], [])
            fmt_results = [r for r in results if r["형식"] == fmt]
            fmt_correct = sum(1 for r in fmt_results if r["점수"] == 1)
            n = len(fmt_results)

            total += n
            correct += fmt_correct

            if n > 0:
                row[ds["name"]] = f"{fmt_correct}/{n} ({fmt_correct/n*100:.1f}%)"
            else:
                row[ds["name"]] = "-"

        row["Total"] = total
        row["Total Correct"] = correct
        row["Accuracy (%)"] = round(correct / total * 100, 2) if total > 0 else "N/A"
        rows.append(row)

    total_row: Dict[str, Any] = {"Format": "All"}
    grand_total = 0
    grand_correct = 0
    for ds in datasets:
        results = all_results.get(ds["key"], [])
        n = len(results)
        c = sum(1 for r in results if r["점수"] == 1)
        grand_total += n
        grand_correct += c
        if n > 0:
            total_row[ds["name"]] = f"{c}/{n} ({c/n*100:.1f}%)"
        else:
            total_row[ds["name"]] = "-"
    total_row["Total"] = grand_total
    total_row["Total Correct"] = grand_correct
    total_row["Accuracy (%)"] = round(grand_correct / grand_total * 100, 2) if grand_total > 0 else "N/A"
    rows.append(total_row)

    return pd.DataFrame(rows)


def generate_error_analysis_table(
    all_results: Dict[str, List[Dict[str, Any]]],
    datasets: List[Dict[str, Any]],
) -> pd.DataFrame:
    """Table 3: 오류 유형 분류 테이블"""
    categories = [
        "Correct",
        "Wrong Value (<=5%)",
        "Wrong Value (>5%)",
        "Type Mismatch",
        "Wrong Parameter",
        "Execution Failure",
        "Exception",
    ]

    rows = []
    for cat in categories:
        row: Dict[str, Any] = {"Error Category": cat}
        total = 0
        for ds in datasets:
            results = all_results.get(ds["key"], [])
            count = sum(1 for r in results if classify_error(r) == cat)
            row[ds["name"]] = count
            total += count
        row["Total"] = total
        rows.append(row)

    return pd.DataFrame(rows)


# ============================================================
# Console Output
# ============================================================

def print_accuracy_table(df: pd.DataFrame, model_name: str):
    """Table 1을 콘솔에 보기 좋게 출력한다."""
    print("\n" + "=" * 100)
    print(f"  Table 1. Value Accuracy by Difficulty Level  (Model: {model_name})")
    print("=" * 100)
    header = f"{'Dataset':<22} {'Diff':>5} {'Scope':>6} {'Queries':>7} {'Correct':>7} {'Accuracy':>10} {'Param%':>9} {'Latency':>10} {'Fail':>5}"
    print(header)
    print("-" * 100)
    for _, row in df.iterrows():
        lat = f"{row['Avg Latency (ms)']}ms" if row['Avg Latency (ms)'] != 'N/A' else 'N/A'
        param = f"{row['Param Match (%)']}" if row['Param Match (%)'] != 'N/A' else 'N/A'
        style = "  " if row["Dataset"] != "Overall" else "> "
        print(f"{style}{row['Dataset']:<20} {row['Difficulty']:>5} {row['Scope']:>6} {row['Queries']:>7} {row['Correct']:>7} {row['Value Accuracy (%)']:>9}% {param:>9} {lat:>10} {row['Exec Failures']:>5}")
    print("=" * 100)


def print_format_breakdown(df: pd.DataFrame):
    """Table 2를 콘솔에 출력한다."""
    print("\n" + "=" * 100)
    print("  Table 2. Accuracy Breakdown by Answer Format")
    print("=" * 100)
    print(df.to_string(index=False))
    print("=" * 100)


def print_error_analysis(df: pd.DataFrame):
    """Table 3을 콘솔에 출력한다."""
    print("\n" + "=" * 100)
    print("  Table 3. Error Analysis")
    print("=" * 100)
    print(df.to_string(index=False))
    print("=" * 100)


# ============================================================
# XLSX Output
# ============================================================

def save_benchmark_xlsx(
    output_path: str,
    accuracy_df: pd.DataFrame,
    format_df: pd.DataFrame,
    error_df: pd.DataFrame,
    all_results: Dict[str, List[Dict[str, Any]]],
    datasets: List[Dict[str, Any]],
    model_name: str,
    timestamp: str,
):
    """벤치마크 결과를 멀티시트 xlsx로 저장한다."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        meta_df = pd.DataFrame({
            "Key": ["Model", "Timestamp", "Total Datasets", "Total Queries"],
            "Value": [
                model_name,
                timestamp,
                len(datasets),
                sum(len(all_results.get(ds["key"], [])) for ds in datasets),
            ],
        })
        meta_df.to_excel(writer, sheet_name="Info", index=False)

        accuracy_df.to_excel(writer, sheet_name="Summary", index=False)
        format_df.to_excel(writer, sheet_name="Format_Breakdown", index=False)
        error_df.to_excel(writer, sheet_name="Error_Analysis", index=False)

        for ds in datasets:
            results = all_results.get(ds["key"], [])
            if results:
                detail_df = pd.DataFrame(results)
                sheet_name = ds["detail_sheet"]
                detail_df.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"\n📁 벤치마크 결과 저장: {output_path}")


# ============================================================
# Benchmark Runner
# ============================================================

def load_checkpoints(checkpoint_dir: Path, timestamp: str, keys: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """이전 체크포인트 파일들을 로드한다."""
    loaded = {}
    for key in keys:
        cp_file = checkpoint_dir / f"{key}_{timestamp}.json"
        if cp_file.exists():
            with open(cp_file, "r", encoding="utf-8") as f:
                loaded[key] = json.load(f)
            print(f"  Resumed checkpoint: {key} ({len(loaded[key])} results)")
    return loaded


def run_benchmark(
    datasets: List[Dict[str, Any]],
    log_level: str = "INFO",
    resume_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """
    전체 벤치마크를 실행한다.

    Args:
        datasets: 실행할 데이터셋 목록
        log_level: 로그 레벨
        resume_timestamp: 이전 실행의 timestamp (체크포인트에서 이어받기)

    Returns:
        {
            "all_results": { "low": [...], "mid": [...], ... },
            "accuracy_df": DataFrame,
            "format_df": DataFrame,
            "error_df": DataFrame,
            "model_name": str,
            "timestamp": str,
        }
    """
    setup_logging(log_level)

    log_session_dir = enable_llm_logging("./data/llm_logs")
    logger.info(f"LLM Logs: {log_session_dir}")

    model_name = get_current_model_name()

    print("=" * 100)
    print("  Value Accuracy Benchmark")
    print("=" * 100)
    print(f"  Model       : {model_name}")
    print(f"  Datasets    : {len(datasets)}")
    for i, ds in enumerate(datasets, 1):
        print(f"    {i}. {ds['name']} ({ds['path']})")
    print("=" * 100)

    orchestrator = Orchestrator()

    timestamp = resume_timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")

    checkpoint_dir = project_root / "Evaluation" / "ValueAccuracy" / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    all_results: Dict[str, List[Dict[str, Any]]] = {}
    if resume_timestamp:
        all_results = load_checkpoints(
            checkpoint_dir, resume_timestamp, [ds["key"] for ds in datasets]
        )

    for ds_idx, ds in enumerate(datasets, 1):
        if ds["key"] in all_results:
            n = len(all_results[ds["key"]])
            c = sum(1 for r in all_results[ds["key"]] if r["점수"] == 1)
            print(f"\n  [{ds_idx}/{len(datasets)}] {ds['name']} - SKIPPED (resumed {c}/{n})")
            continue

        ds_path = project_root / ds["path"]
        if not ds_path.exists():
            print(f"\n⚠️  [{ds_idx}/{len(datasets)}] 파일 없음, 스킵: {ds_path}")
            continue

        checkpoint_file = checkpoint_dir / f"{ds['key']}_{timestamp}.json"

        print(f"\n{'#' * 100}")
        print(f"  [{ds_idx}/{len(datasets)}] {ds['name']}")
        print(f"  Path: {ds['path']}")
        print(f"  Difficulty: {ds['difficulty']} | Scope: {ds['scope']}")
        print(f"  Description: {ds['description']}")
        print(f"{'#' * 100}")

        qa_pairs = load_qa_pairs(str(ds_path))
        qa_pairs = preprocess_qa_pairs(qa_pairs)
        print(f"\n  Loaded {len(qa_pairs)} QA pairs")

        results = run_qa_test(qa_pairs, orchestrator, verbose=True)
        all_results[ds["key"]] = results

        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"  Checkpoint saved: {checkpoint_file}")

        correct = sum(1 for r in results if r["점수"] == 1)
        total = len(results)
        acc = (correct / total * 100) if total > 0 else 0
        print(f"\n  >>> {ds['name']} 결과: {correct}/{total} ({acc:.1f}%)")

    model_name = get_current_model_name()

    accuracy_df = generate_accuracy_table(all_results, datasets, model_name)
    format_df = generate_format_breakdown_table(all_results, datasets)
    error_df = generate_error_analysis_table(all_results, datasets)

    print_accuracy_table(accuracy_df, model_name)
    print_format_breakdown(format_df)
    print_error_analysis(error_df)

    return {
        "all_results": all_results,
        "accuracy_df": accuracy_df,
        "format_df": format_df,
        "error_df": error_df,
        "model_name": model_name,
        "timestamp": timestamp,
    }


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Value Accuracy Benchmark - 난이도별 QA 데이터셋 벤치마크",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_value_accuracy_benchmark.py                      # 전체 실행
  python run_value_accuracy_benchmark.py --datasets low mid   # Low, Mid만
  python run_value_accuracy_benchmark.py --datasets high      # High만
  python run_value_accuracy_benchmark.py --log-level WARNING  # 로그 최소화
        """,
    )
    parser.add_argument(
        "--datasets", "-d",
        nargs="+",
        choices=["low", "mid", "high", "multi"],
        default=None,
        help="실행할 데이터셋 (미지정 시 전체 실행). Choices: low, mid, high, multi",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="출력 xlsx 파일 경로 (default: Evaluation/ValueAccuracy/benchmark_TIMESTAMP.xlsx)",
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="로그 레벨 (default: INFO)",
    )
    parser.add_argument(
        "--resume", "-r",
        default=None,
        help="이전 실행의 timestamp로 체크포인트에서 이어받기 (예: 20260306_112700)",
    )
    args = parser.parse_args()

    if args.datasets:
        datasets = [DATASET_KEY_MAP[k] for k in args.datasets]
    else:
        datasets = BENCHMARK_DATASETS

    result = run_benchmark(
        datasets=datasets,
        log_level=args.log_level,
        resume_timestamp=args.resume,
    )

    output_dir = project_root / "Evaluation" / "ValueAccuracy"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = args.output
    else:
        output_path = str(output_dir / f"benchmark_{result['timestamp']}.xlsx")

    save_benchmark_xlsx(
        output_path=output_path,
        accuracy_df=result["accuracy_df"],
        format_df=result["format_df"],
        error_df=result["error_df"],
        all_results=result["all_results"],
        datasets=datasets,
        model_name=result["model_name"],
        timestamp=result["timestamp"],
    )

    print("\n" + "=" * 100)
    print("  Benchmark Complete!")
    print(f"  Results: {output_path}")
    print("=" * 100)


if __name__ == "__main__":
    main()
