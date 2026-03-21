#!/usr/bin/env python
"""
Local Model Value Accuracy Benchmark
=====================================

설치된 로컬 Ollama 모델들로 Value Accuracy 벤치마크를 실행하고,
모델 간 성능을 비교하는 테이블을 자동 생성한다.

사용법:
    # 설치된 모든 모델로 Low 데이터셋 벤치마크 (기본)
    python compare_local_models_benchmark.py

    # 특정 모델만, Low + Mid
    python compare_local_models_benchmark.py --models qwen2.5:7b llama3.1:8b --datasets low mid

    # 이전 실행에서 이어받기 (완료된 모델은 스킵)
    python compare_local_models_benchmark.py --resume 20260306_150000

결과물:
    Evaluation/ValueAccuracy/local_models/
    ├── comparison_YYYYMMDD_HHMMSS.xlsx     # 모델 간 비교 테이블
    ├── checkpoints/
    │   ├── qwen2.5_7b/low_TIMESTAMP.json
    │   ├── qwen2.5_7b/mid_TIMESTAMP.json
    │   └── ...
    └── detail_qwen2.5_7b_TIMESTAMP.xlsx    # 모델별 상세 결과
"""

import os
import sys
import json
import logging
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

os.environ["LLM_PROVIDER"] = "ollama"

from shared.llm import (
    enable_llm_logging,
    switch_model,
    get_current_model_name,
    reset_llm_client,
)
from test_qa_dataset import (
    load_qa_pairs,
    run_qa_test,
    setup_logging,
)
from OrchestrationAgent.src.orchestrator import Orchestrator
from run_value_accuracy_benchmark import (
    BENCHMARK_DATASETS,
    DATASET_KEY_MAP,
    preprocess_qa_pairs,
    generate_accuracy_table,
    generate_format_breakdown_table,
    generate_error_analysis_table,
    print_accuracy_table,
    classify_error,
)

logger = logging.getLogger(__name__)

# ============================================================
# Model Configuration
# ============================================================

MODELS_TO_EXCLUDE = [
    "hf.co/mradermacher/hari-q2.5-Thinking-i1-GGUF",
]

GPT_REFERENCE = {
    "model": "gpt-5.2-2025-12-11",
    "low": {"queries": 22, "correct": 19, "accuracy": 86.36, "avg_latency_ms": 8639.4},
    "mid": {"queries": 10, "correct": 9, "accuracy": 90.0, "avg_latency_ms": 9886.1},
    "high": {"queries": 23, "correct": 5, "accuracy": 21.74, "avg_latency_ms": 18628.9},
    "multi": {"queries": 24, "correct": 23, "accuracy": 95.83, "avg_latency_ms": 11878.6},
}


# ============================================================
# Ollama Utilities
# ============================================================

def check_ollama_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def get_installed_models() -> List[Dict[str, Any]]:
    """설치된 Ollama 모델 목록을 크기 순으로 반환한다."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            models = data.get("models", [])
            return sorted(models, key=lambda m: m.get("size", 0))
    except Exception:
        return []


def filter_models(models: List[Dict[str, Any]], include: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """제외 목록 적용 및 선택 필터링."""
    filtered = []
    for m in models:
        name = m["name"]
        if any(exc in name for exc in MODELS_TO_EXCLUDE):
            continue
        if include and not any(inc in name or name in inc for inc in include):
            continue
        filtered.append(m)
    return filtered


def safe_model_name(model: str) -> str:
    return model.replace(":", "_").replace("/", "_").replace(".", "_")


# ============================================================
# Per-Model Benchmark Runner
# ============================================================

def run_single_model_benchmark(
    model_name: str,
    datasets: List[Dict[str, Any]],
    output_dir: Path,
    timestamp: str,
    existing_checkpoints: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    단일 모델로 여러 데이터셋 벤치마크를 실행한다.

    Returns:
        {
            "model": str,
            "all_results": { "low": [...], ... },
            "summary": { "low": {"queries":..., "correct":..., "accuracy":...}, ... },
        }
    """
    model_safe = safe_model_name(model_name)
    cp_dir = output_dir / "checkpoints" / model_safe
    cp_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 100}")
    print(f"  Model: {model_name}")
    print(f"  Datasets: {', '.join(ds['key'] for ds in datasets)}")
    print(f"{'=' * 100}")

    switch_model(model_name)
    current = get_current_model_name()
    print(f"  Active model: {current}")

    orchestrator = Orchestrator()

    all_results: Dict[str, List[Dict[str, Any]]] = {}
    if existing_checkpoints:
        all_results.update(existing_checkpoints)

    for ds_idx, ds in enumerate(datasets, 1):
        if ds["key"] in all_results:
            n = len(all_results[ds["key"]])
            c = sum(1 for r in all_results[ds["key"]] if r["점수"] == 1)
            print(f"\n  [{ds_idx}/{len(datasets)}] {ds['name']} - SKIPPED (checkpoint: {c}/{n})")
            continue

        ds_path = project_root / ds["path"]
        if not ds_path.exists():
            print(f"\n  [{ds_idx}/{len(datasets)}] {ds['name']} - FILE NOT FOUND, skip")
            continue

        print(f"\n  [{ds_idx}/{len(datasets)}] {ds['name']} ({ds['path']})")

        qa_pairs = load_qa_pairs(str(ds_path))
        qa_pairs = preprocess_qa_pairs(qa_pairs)
        print(f"    Loaded {len(qa_pairs)} QA pairs")

        results = run_qa_test(qa_pairs, orchestrator, verbose=True)
        all_results[ds["key"]] = results

        cp_file = cp_dir / f"{ds['key']}_{timestamp}.json"
        with open(cp_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        correct = sum(1 for r in results if r["점수"] == 1)
        total = len(results)
        acc = (correct / total * 100) if total > 0 else 0
        print(f"\n    >>> {ds['name']}: {correct}/{total} ({acc:.1f}%)")

    summary = {}
    for ds in datasets:
        results = all_results.get(ds["key"], [])
        if not results:
            continue
        n = len(results)
        correct = sum(1 for r in results if r["점수"] == 1)
        latencies = [r["실행시간(ms)"] for r in results if r["실행시간(ms)"] is not None]
        failures = sum(1 for r in results if r["에러메시지"])
        summary[ds["key"]] = {
            "queries": n,
            "correct": correct,
            "accuracy": round(correct / n * 100, 2) if n > 0 else 0,
            "avg_latency_ms": round(np.mean(latencies), 1) if latencies else None,
            "failures": failures,
        }

    return {
        "model": model_name,
        "all_results": all_results,
        "summary": summary,
    }


# ============================================================
# Cross-Model Comparison Tables
# ============================================================

def generate_model_comparison_table(
    model_summaries: List[Dict[str, Any]],
    datasets: List[Dict[str, Any]],
    model_sizes: Dict[str, float],
) -> pd.DataFrame:
    """모델 간 성능 비교 테이블을 생성한다."""
    ds_keys = [ds["key"] for ds in datasets]
    rows = []

    for ms in model_summaries:
        model = ms["model"]
        summary = ms["summary"]
        size_gb = model_sizes.get(model)

        row: Dict[str, Any] = {
            "Model": model,
            "Size (GB)": f"{size_gb:.1f}" if size_gb else "Cloud",
        }

        total_q = 0
        total_c = 0
        all_lat = []

        for ds in datasets:
            key = ds["key"]
            s = summary.get(key)
            if s:
                row[f"{key.capitalize()} Acc (%)"] = s["accuracy"]
                row[f"{key.capitalize()} ({s['correct']}/{s['queries']})"] = f"{s['accuracy']}%"
                total_q += s["queries"]
                total_c += s["correct"]
                if s["avg_latency_ms"]:
                    all_lat.append(s["avg_latency_ms"])
            else:
                row[f"{key.capitalize()} Acc (%)"] = "-"

        row["Overall Acc (%)"] = round(total_c / total_q * 100, 2) if total_q > 0 else "-"
        row["Avg Latency (ms)"] = round(np.mean(all_lat), 1) if all_lat else "-"
        row["Total Correct"] = total_c
        row["Total Queries"] = total_q
        rows.append(row)

    df = pd.DataFrame(rows)

    def sort_key(x):
        if isinstance(x, (int, float)):
            return (0, -x)
        return (1, 0)
    df["_sort"] = df["Overall Acc (%)"].apply(sort_key)
    df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
    return df


def print_model_comparison(df: pd.DataFrame, datasets: List[Dict[str, Any]]):
    """모델 비교 결과를 콘솔에 출력한다."""
    ds_keys = [ds["key"] for ds in datasets]

    print("\n" + "=" * 120)
    print("  Model Comparison - Value Accuracy")
    print("=" * 120)

    acc_cols = [f"{k.capitalize()} Acc (%)" for k in ds_keys]
    header_parts = [f"{'Model':<32}", f"{'Size':>8}"]
    for k in ds_keys:
        header_parts.append(f"{k.capitalize():>10}")
    header_parts.extend([f"{'Overall':>10}", f"{'Latency':>12}"])
    print("  ".join(header_parts))
    print("-" * 120)

    for _, row in df.iterrows():
        parts = [f"{row['Model']:<32}", f"{row['Size (GB)']:>8}"]
        for k in ds_keys:
            col = f"{k.capitalize()} Acc (%)"
            val = row[col]
            parts.append(f"{val:>9}%" if isinstance(val, (int, float)) else f"{val:>10}")
        overall = row["Overall Acc (%)"]
        parts.append(f"{overall:>9}%" if isinstance(overall, (int, float)) else f"{overall:>10}")
        lat = row["Avg Latency (ms)"]
        parts.append(f"{lat}ms" if isinstance(lat, (int, float)) else f"{lat:>12}")
        print("  ".join(parts))

    print("=" * 120)

    valid = df[df["Overall Acc (%)"].apply(lambda x: isinstance(x, (int, float)))]
    if not valid.empty:
        best = valid.iloc[0]
        print(f"\n  Best: {best['Model']} (Overall {best['Overall Acc (%)']}%)")


def save_comparison_xlsx(
    output_path: str,
    comparison_df: pd.DataFrame,
    model_summaries: List[Dict[str, Any]],
    datasets: List[Dict[str, Any]],
    timestamp: str,
):
    """비교 결과를 xlsx로 저장한다."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        meta_df = pd.DataFrame({
            "Key": ["Timestamp", "Total Models", "Datasets"],
            "Value": [
                timestamp,
                len(model_summaries),
                ", ".join(ds["key"] for ds in datasets),
            ],
        })
        meta_df.to_excel(writer, sheet_name="Info", index=False)
        comparison_df.to_excel(writer, sheet_name="Model_Comparison", index=False)

        for ms in model_summaries:
            model_safe = safe_model_name(ms["model"])[:28]
            for ds in datasets:
                results = ms["all_results"].get(ds["key"], [])
                if results:
                    sheet = f"{model_safe}_{ds['key']}"[:31]
                    pd.DataFrame(results).to_excel(writer, sheet_name=sheet, index=False)

    print(f"\n  Results saved: {output_path}")


# ============================================================
# Checkpoint Management
# ============================================================

def load_model_checkpoints(
    output_dir: Path,
    model_name: str,
    timestamp: str,
    ds_keys: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """특정 모델의 체크포인트들을 로드한다."""
    model_safe = safe_model_name(model_name)
    cp_dir = output_dir / "checkpoints" / model_safe
    loaded = {}
    for key in ds_keys:
        cp_file = cp_dir / f"{key}_{timestamp}.json"
        if cp_file.exists():
            with open(cp_file, "r", encoding="utf-8") as f:
                loaded[key] = json.load(f)
    return loaded


def is_model_complete(
    output_dir: Path,
    model_name: str,
    timestamp: str,
    ds_keys: List[str],
) -> bool:
    """모델의 모든 데이터셋이 체크포인트 완료인지 확인한다."""
    cp = load_model_checkpoints(output_dir, model_name, timestamp, ds_keys)
    return len(cp) == len(ds_keys)


# ============================================================
# Main Runner
# ============================================================

def run_local_model_comparison(
    models: List[Dict[str, Any]],
    datasets: List[Dict[str, Any]],
    output_dir: Path,
    timestamp: str,
    log_level: str = "WARNING",
    resume: bool = False,
) -> Dict[str, Any]:
    """로컬 모델 벤치마크를 실행한다."""
    setup_logging(log_level)
    enable_llm_logging("./data/llm_logs")

    ds_keys = [ds["key"] for ds in datasets]
    model_sizes: Dict[str, float] = {}
    model_summaries: List[Dict[str, Any]] = []

    print("=" * 120)
    print("  Local Model Value Accuracy Benchmark")
    print("=" * 120)
    print(f"  Models    : {len(models)}")
    for i, m in enumerate(models, 1):
        size_gb = m["size"] / 1e9
        model_sizes[m["name"]] = size_gb
        print(f"    {i:>2}. {m['name']:<40s} ({size_gb:.1f} GB)")
    print(f"  Datasets  : {', '.join(ds['key'] for ds in datasets)}")
    print(f"  Timestamp : {timestamp}")
    print("=" * 120)

    for m_idx, m in enumerate(models, 1):
        model_name = m["name"]
        model_sizes[model_name] = m["size"] / 1e9

        if resume and is_model_complete(output_dir, model_name, timestamp, ds_keys):
            cp = load_model_checkpoints(output_dir, model_name, timestamp, ds_keys)
            summary = {}
            for ds in datasets:
                results = cp.get(ds["key"], [])
                if results:
                    n = len(results)
                    c = sum(1 for r in results if r["점수"] == 1)
                    lats = [r["실행시간(ms)"] for r in results if r["실행시간(ms)"] is not None]
                    summary[ds["key"]] = {
                        "queries": n, "correct": c,
                        "accuracy": round(c / n * 100, 2) if n > 0 else 0,
                        "avg_latency_ms": round(np.mean(lats), 1) if lats else None,
                        "failures": sum(1 for r in results if r["에러메시지"]),
                    }
            model_summaries.append({"model": model_name, "all_results": cp, "summary": summary})
            print(f"\n  [{m_idx}/{len(models)}] {model_name} - SKIPPED (all checkpoints exist)")
            continue

        print(f"\n  [{m_idx}/{len(models)}] Starting: {model_name}")

        existing_cp = {}
        if resume:
            existing_cp = load_model_checkpoints(output_dir, model_name, timestamp, ds_keys)
            if existing_cp:
                print(f"    Resuming with {len(existing_cp)} existing checkpoints")

        try:
            result = run_single_model_benchmark(
                model_name=model_name,
                datasets=datasets,
                output_dir=output_dir,
                timestamp=timestamp,
                existing_checkpoints=existing_cp,
            )
            model_summaries.append(result)
        except Exception as e:
            print(f"\n  ERROR: {model_name} failed: {e}")
            import traceback
            traceback.print_exc()
            model_summaries.append({
                "model": model_name,
                "all_results": {},
                "summary": {},
            })

        reset_llm_client()

    gpt_ref_summary = {}
    for ds in datasets:
        if ds["key"] in GPT_REFERENCE:
            gpt_ref_summary[ds["key"]] = GPT_REFERENCE[ds["key"]]
    model_summaries.append({
        "model": GPT_REFERENCE["model"],
        "all_results": {},
        "summary": gpt_ref_summary,
    })
    model_sizes[GPT_REFERENCE["model"]] = 0

    comparison_df = generate_model_comparison_table(model_summaries, datasets, model_sizes)
    print_model_comparison(comparison_df, datasets)

    return {
        "comparison_df": comparison_df,
        "model_summaries": model_summaries,
        "timestamp": timestamp,
    }


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Local Model Value Accuracy Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python compare_local_models_benchmark.py                                # all models, low only
  python compare_local_models_benchmark.py --datasets low mid             # low + mid
  python compare_local_models_benchmark.py --models qwen2.5:7b llama3.1:8b
  python compare_local_models_benchmark.py --resume 20260306_150000       # resume previous run
        """,
    )
    parser.add_argument(
        "--models", "-m", nargs="+", default=None,
        help="테스트할 모델 목록 (미지정시 설치된 모든 모델, hari 제외)",
    )
    parser.add_argument(
        "--datasets", "-d", nargs="+",
        choices=["low", "mid", "high", "multi"], default=["low"],
        help="실행할 데이터셋 (default: low)",
    )
    parser.add_argument(
        "--output-dir", "-o", default=None,
        help="결과 저장 디렉토리 (default: Evaluation/ValueAccuracy/local_models)",
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="WARNING",
        help="로그 레벨 (default: WARNING)",
    )
    parser.add_argument(
        "--resume", "-r", default=None,
        help="이전 실행의 timestamp로 이어받기 (완료된 모델은 자동 스킵)",
    )
    args = parser.parse_args()

    if not check_ollama_available():
        print("Ollama server is not running. Start it with: ollama serve")
        sys.exit(1)

    installed = get_installed_models()
    if not installed:
        print("No Ollama models installed.")
        sys.exit(1)

    models = filter_models(installed, include=args.models)
    if not models:
        print("No models available after filtering.")
        sys.exit(1)

    datasets = [DATASET_KEY_MAP[k] for k in args.datasets]

    output_dir = Path(args.output_dir) if args.output_dir else (project_root / "Evaluation" / "ValueAccuracy" / "local_models")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = args.resume or datetime.now().strftime("%Y%m%d_%H%M%S")

    result = run_local_model_comparison(
        models=models,
        datasets=datasets,
        output_dir=output_dir,
        timestamp=timestamp,
        log_level=args.log_level,
        resume=bool(args.resume),
    )

    xlsx_path = str(output_dir / f"comparison_{result['timestamp']}.xlsx")
    save_comparison_xlsx(
        output_path=xlsx_path,
        comparison_df=result["comparison_df"],
        model_summaries=result["model_summaries"],
        datasets=datasets,
        timestamp=result["timestamp"],
    )

    print("\n" + "=" * 120)
    print("  Local Model Benchmark Complete!")
    print(f"  Results: {xlsx_path}")
    print("=" * 120)


if __name__ == "__main__":
    main()
