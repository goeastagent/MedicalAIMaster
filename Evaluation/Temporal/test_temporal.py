#!/usr/bin/env python
"""
Temporal Evaluation Script
==========================

Runs temporal_dataset_validated.jsonl through multiple scenarios and compares
the calculated values against the ground truth:

  1. VitalAgent (MedicalAIMaster) Full Pipeline
  2. Claude Code CLI

Two scoring modes depending on question_type:
  - temporal        → numeric value comparison (same as Value Accuracy)
  - temporal_ambiguous → LLM-as-a-Judge rubric (PASS / PARTIAL_PASS / FAIL)

Results are saved to an xlsx workbook (summary + detail sheets).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import statistics
import sys
import time
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# ---------------------------------------------------------------------------

from Evaluation.Temporal.evaluate_ambiguity import evaluate_ambiguous_response

def setup_logging(level: str = "INFO"):
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler()],
    )
    for name in ("httpx", "httpcore", "openai", "urllib3", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)

logger = logging.getLogger("TemporalEval")

# ═══════════════════════════════════════════════════════════════════════════
# Data models
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CaseResult:
    case_id: str
    scenario: str
    query: str
    question_type: str
    query_style: str

    expected_value: Any
    agent_output: Any

    value_match: bool = False             # for temporal (numeric)
    match_type: str = ""                  # "exact" | "approx" | "mismatch" | "none_match"
    ambiguity_score: str = ""             # for temporal_ambiguous (PASS/PARTIAL_PASS/FAIL)
    ambiguity_reason: str = ""

    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    raw_response: Optional[str] = None
    quality_flags: str = ""               # comma-separated flags from dataset generation

@dataclass
class AggregateMetrics:
    scenario: str
    slice_name: str = "overall"
    slice_value: str = "all"
    count: int = 0
    accuracy: float = 0.0                 # temporal numeric accuracy
    ambiguity_pass_rate: float = 0.0      # temporal_ambiguous PASS+PARTIAL rate
    ambiguity_fail_rate: float = 0.0
    mean_time_ms: float = 0.0
    median_time_ms: float = 0.0
    min_time_ms: float = 0.0
    max_time_ms: float = 0.0
    p95_time_ms: float = 0.0

# ═══════════════════════════════════════════════════════════════════════════
# 1. Dataset loader
# ═══════════════════════════════════════════════════════════════════════════

def load_dataset(path: str) -> List[Dict[str, Any]]:
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    return cases

# ═══════════════════════════════════════════════════════════════════════════
# 2. Metric computation
# ═══════════════════════════════════════════════════════════════════════════

FLOAT_TOLERANCE = 1e-2
STRICT_FLOAT_TOLERANCE = 1e-4


def compare_values(expected: Any, actual: Any) -> tuple[bool, str]:
    """
    Compare expected vs actual and return (match, match_type).
    match_type: "exact" (tight tolerance), "approx" (loose, e.g. ddof/rounding diff),
                "none_match", "mismatch", "parse_error"
    """
    if isinstance(actual, str):
        try:
            actual_parsed = json.loads(actual.replace("'", '"'))
            if isinstance(actual_parsed, dict) and "answer" in actual_parsed:
                actual = actual_parsed["answer"]
        except Exception:
            pass

    if expected is None:
        if actual is None or actual == "None" or actual == "null":
            return True, "none_match"
        if isinstance(actual, (list, dict)) and len(actual) == 0:
            return True, "none_match"
        if actual == 0 or actual == "0":
            return True, "none_match"
        return False, "mismatch"

    if isinstance(expected, (int, float)):
        try:
            actual_f = float(actual)
            expected_f = float(expected)
        except (ValueError, TypeError):
            return False, "parse_error"

        if math.isclose(expected_f, actual_f, rel_tol=STRICT_FLOAT_TOLERANCE):
            return True, "exact"
        if math.isclose(expected_f, actual_f, rel_tol=FLOAT_TOLERANCE):
            return True, "approx"
        return False, "mismatch"

    if isinstance(expected, str):
        if str(expected).strip().lower() == str(actual).strip().lower():
            return True, "exact"
        return False, "mismatch"

    if str(expected) == str(actual):
        return True, "exact"
    return False, "mismatch"

# ═══════════════════════════════════════════════════════════════════════════
# 3. Scenario runners
# ═══════════════════════════════════════════════════════════════════════════

VITAL_DIR = str(PROJECT_ROOT / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0" / "vital_files")

# ---- 3-A  VitalAgent -------------------------------------------------------

def run_vitalagent(cases: List[Dict], progress_cb=None) -> List[CaseResult]:
    from OrchestrationAgent.src.orchestrator import Orchestrator
    orch = Orchestrator()
    results: List[CaseResult] = []

    for idx, case in enumerate(cases):
        _log_progress("VitalAgent", idx, len(cases), case["id"])
        t0 = time.time()

        prompt = (
            f"{case['query']}\n\n"
            "Please output ONLY a JSON object with a single key 'answer' containing the final calculated value. "
            "Do not include any other text.\n"
            "IMPORTANT: When calling `vf.to_numpy(track_names, interval)`, you MUST use `interval=1` (1 Hz)."
        )

        raw_output = None
        agent_answer = None
        error = None

        try:
            res = orch.run(prompt)
            elapsed = (time.time() - t0) * 1000
            raw_output = res.final_answer if hasattr(res, 'final_answer') else str(res)
            agent_answer = _extract_answer(raw_output, res)
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            error = str(e)

        cr = _build_case_result(case, "VitalAgent", agent_answer, raw_output, elapsed, error)
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))

    return results

# ---- 3-B  Claude Code CLI --------------------------------------------------

def run_claude_code_cli(cases: List[Dict], progress_cb=None) -> List[CaseResult]:
    results: List[CaseResult] = []

    for idx, case in enumerate(cases):
        _log_progress("Claude-Code-CLI", idx, len(cases), case["id"])

        prompt = (
            f"You are a medical data analyst. Write a python script using `vitaldb` to answer: '{case['query']}'.\n\n"
            f"The vital files are at `{VITAL_DIR}/`.\n"
            f"Return ONLY a JSON: {{\"answer\": <value>}}. If not found, return null.\n"
            f"Output the code in a ```python block. "
            f"Make sure your code prints the answer via `print(json.dumps({{\"answer\": ...}}))`.\n"
            f"IMPORTANT: Use `vf.to_numpy([track], 1)` with interval=1 (1 Hz)."
        )

        t0 = time.time()
        raw_output = ""
        error_msg = None
        agent_answer = None

        OPENVITALDB_DIR = str(PROJECT_ROOT / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0")

        try:
            process = subprocess.run(
                ["claude", "-p", prompt, "--no-session-persistence"],
                capture_output=True, text=True, timeout=120,
                cwd=OPENVITALDB_DIR
            )
            elapsed = (time.time() - t0) * 1000
            raw_output = process.stdout.strip()
            if not raw_output and process.stderr:
                raw_output = process.stderr.strip()
            if process.returncode != 0:
                error_msg = process.stderr.strip()

            code_match = re.search(r'```python\n(.*?)\n```', raw_output, re.DOTALL)
            json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)

            if code_match:
                from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor
                executor = VitalExecutor()
                res = executor.execute_code(code_match.group(1))
                if res["success"]:
                    agent_answer = res["result"]
                else:
                    agent_answer = f"Error: {res['error']}"
            elif json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    agent_answer = parsed.get("answer")
                except json.JSONDecodeError:
                    agent_answer = raw_output
            else:
                agent_answer = raw_output

        except subprocess.TimeoutExpired:
            elapsed = 120_000
            error_msg = "TimeoutExpired"
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            error_msg = str(e)

        cr = _build_case_result(case, "Claude-Code-CLI", agent_answer, raw_output, elapsed, error_msg)
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))

    return results

# ═══════════════════════════════════════════════════════════════════════════
# 4. Post-scoring: Ambiguity LLM Judge
# ═══════════════════════════════════════════════════════════════════════════

def score_ambiguous_cases(results: List[CaseResult], dataset: List[Dict[str, Any]]):
    from shared.llm.client import get_llm_client
    llm = get_llm_client()

    case_map = {c["id"]: c for c in dataset}

    for cr in results:
        if cr.question_type != "temporal_ambiguous":
            continue

        case_data = case_map.get(cr.case_id, {})
        missing_info = case_data.get(
            "missing_info", "caseid, sampling rate, NaN handling, time range"
        )

        eval_res = evaluate_ambiguous_response(
            llm,
            query=cr.query,
            agent_response=str(cr.agent_output or cr.raw_response or ""),
            missing_info=missing_info,
        )
        cr.ambiguity_score = eval_res.get("score", "ERROR")
        cr.ambiguity_reason = eval_res.get("reason", "")
        logger.info(f"  [{cr.case_id}] ambiguity_score={cr.ambiguity_score}")

# ═══════════════════════════════════════════════════════════════════════════
# 5. Aggregation
# ═══════════════════════════════════════════════════════════════════════════

BREAKDOWN_DIMS = ["question_type", "query_style"]

def aggregate(results: List[CaseResult], scenario: str) -> List[AggregateMetrics]:
    aggs: List[AggregateMetrics] = []
    aggs.append(_agg_slice(results, scenario, "overall", "all"))
    for dim in BREAKDOWN_DIMS:
        values = sorted(set(getattr(r, dim) for r in results if getattr(r, dim)))
        for v in values:
            subset = [r for r in results if getattr(r, dim) == v]
            aggs.append(_agg_slice(subset, scenario, dim, v))
    return aggs

def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])

def _agg_slice(results: List[CaseResult], scenario: str, dim: str, val: str) -> AggregateMetrics:
    n = len(results)
    if n == 0:
        return AggregateMetrics(scenario=scenario, slice_name=dim, slice_value=val)

    numeric = [r for r in results if r.question_type == "temporal"]
    ambig = [r for r in results if r.question_type == "temporal_ambiguous"]

    acc = sum(1 for r in numeric if r.value_match) / len(numeric) if numeric else 0.0

    amb_pass = sum(1 for r in ambig if r.ambiguity_score in ("PASS", "PARTIAL_PASS"))
    amb_fail = sum(1 for r in ambig if r.ambiguity_score == "FAIL")
    amb_pass_rate = amb_pass / len(ambig) if ambig else 0.0
    amb_fail_rate = amb_fail / len(ambig) if ambig else 0.0

    times = sorted(r.execution_time_ms for r in results)

    return AggregateMetrics(
        scenario=scenario,
        slice_name=dim,
        slice_value=val,
        count=n,
        accuracy=acc,
        ambiguity_pass_rate=amb_pass_rate,
        ambiguity_fail_rate=amb_fail_rate,
        mean_time_ms=statistics.mean(times),
        median_time_ms=statistics.median(times),
        min_time_ms=times[0],
        max_time_ms=times[-1],
        p95_time_ms=_percentile(times, 95),
    )

# ═══════════════════════════════════════════════════════════════════════════
# 6. XLSX output
# ═══════════════════════════════════════════════════════════════════════════

def save_results_xlsx(
    all_results: Dict[str, List[CaseResult]],
    all_aggs: Dict[str, List[AggregateMetrics]],
    output_path: str,
):
    detail_rows = []
    for scenario, results in all_results.items():
        for r in results:
            detail_rows.append({
                "scenario": r.scenario,
                "case_id": r.case_id,
                "question_type": r.question_type,
                "query_style": r.query_style,
                "query": r.query,
                "expected_value": str(r.expected_value),
                "agent_output": str(r.agent_output),
                "value_match": r.value_match,
                "match_type": r.match_type,
                "ambiguity_score": r.ambiguity_score,
                "ambiguity_reason": r.ambiguity_reason,
                "time_ms": round(r.execution_time_ms, 1),
                "error": r.error_message or "",
                "quality_flags": r.quality_flags,
            })
    df_detail = pd.DataFrame(detail_rows)

    agg_rows = []
    for scenario, aggs in all_aggs.items():
        for a in aggs:
            agg_rows.append({
                "scenario": a.scenario,
                "dimension": a.slice_name,
                "value": a.slice_value,
                "count": a.count,
                "numeric_accuracy%": round(a.accuracy * 100, 2),
                "ambiguity_pass_rate%": round(a.ambiguity_pass_rate * 100, 2),
                "ambiguity_fail_rate%": round(a.ambiguity_fail_rate * 100, 2),
                "avg_ms": round(a.mean_time_ms, 1),
                "median_ms": round(a.median_time_ms, 1),
                "min_ms": round(a.min_time_ms, 1),
                "max_ms": round(a.max_time_ms, 1),
                "p95_ms": round(a.p95_time_ms, 1),
            })
    df_agg = pd.DataFrame(agg_rows)

    overall = df_agg[df_agg["dimension"] == "overall"].set_index("scenario")
    pivot_cols = ["count", "numeric_accuracy%", "ambiguity_pass_rate%", "ambiguity_fail_rate%",
                  "avg_ms", "median_ms", "min_ms", "max_ms", "p95_ms"]
    df_pivot = overall[pivot_cols].T if not overall.empty else pd.DataFrame()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if not df_pivot.empty:
            df_pivot.to_excel(writer, sheet_name="Comparison")
        df_agg.to_excel(writer, sheet_name="Aggregated", index=False)
        df_detail.to_excel(writer, sheet_name="Detail", index=False)

    logger.info(f"Results saved to {output_path}")

# ═══════════════════════════════════════════════════════════════════════════
# 7. Console summary
# ═══════════════════════════════════════════════════════════════════════════

def print_comparison_table(all_aggs: Dict[str, List[AggregateMetrics]]):
    header = (f"{'Scenario':<25} {'N':>4} {'NumAcc%':>8} {'AmbPass%':>9} {'AmbFail%':>9}"
              f" {'Avg(ms)':>10} {'Med(ms)':>10} {'P95(ms)':>10}")
    print(f"\n{'=' * 90}")
    print("  Temporal Evaluation — Scenario Comparison")
    print(f"{'=' * 90}")
    print(header)
    print("-" * 90)
    for scenario, aggs in all_aggs.items():
        ov = next((a for a in aggs if a.slice_name == "overall"), None)
        if not ov:
            continue
        print(
            f"{ov.scenario:<25} {ov.count:>4} "
            f"{ov.accuracy * 100:>7.2f}% "
            f"{ov.ambiguity_pass_rate * 100:>8.2f}% "
            f"{ov.ambiguity_fail_rate * 100:>8.2f}%"
            f" {ov.mean_time_ms:>10.1f} {ov.median_time_ms:>10.1f} {ov.p95_time_ms:>10.1f}"
        )
    print(f"{'=' * 90}\n")

def print_breakdown(all_aggs: Dict[str, List[AggregateMetrics]], dim: str):
    print(f"\n--- Breakdown by {dim} ---")
    header = f"{'Scenario':<25} {dim:<25} {'N':>4} {'NumAcc%':>8} {'AmbPass%':>9} {'Avg(ms)':>10}"
    print(header)
    print("-" * 85)
    for scenario, aggs in all_aggs.items():
        for a in aggs:
            if a.slice_name != dim:
                continue
            print(
                f"{a.scenario:<25} {a.slice_value:<25} {a.count:>4} "
                f"{a.accuracy * 100:>7.2f}% "
                f"{a.ambiguity_pass_rate * 100:>8.2f}%"
                f" {a.mean_time_ms:>10.1f}"
            )

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _log_progress(scenario: str, idx: int, total: int, case_id: str):
    logger.info(f"[{scenario}] ({idx + 1}/{total}) {case_id}")

def _extract_answer(raw_output, res_obj=None):
    agent_answer = raw_output
    json_match = re.search(r'\{.*\}', str(raw_output), re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            agent_answer = parsed.get("answer", raw_output)
        except json.JSONDecodeError:
            pass

    if res_obj:
        if hasattr(res_obj, 'result') and isinstance(res_obj.result, dict) and "answer" in res_obj.result:
            agent_answer = res_obj.result["answer"]
        elif hasattr(res_obj, 'final_answer') and isinstance(res_obj.final_answer, dict) and "answer" in res_obj.final_answer:
            agent_answer = res_obj.final_answer["answer"]
    return agent_answer

def _build_case_result(case, scenario, agent_answer, raw_output, elapsed, error):
    is_ambiguous = case.get("question_type") == "temporal_ambiguous"

    if is_ambiguous:
        match, match_type = False, ""
    else:
        match, match_type = compare_values(case.get("expected_value"), agent_answer)

    quality_flags = case.get("quality_flags", [])
    flags_str = ", ".join(quality_flags) if isinstance(quality_flags, list) else str(quality_flags)

    return CaseResult(
        case_id=case["id"],
        scenario=scenario,
        query=case["query"],
        question_type=case.get("question_type", ""),
        query_style=case.get("query_style", ""),
        expected_value=case.get("expected_value"),
        agent_output=agent_answer,
        value_match=match,
        match_type=match_type,
        execution_time_ms=elapsed,
        error_message=error,
        raw_response=str(raw_output) if raw_output else None,
        quality_flags=flags_str,
    )

# ═══════════════════════════════════════════════════════════════════════════
# 8. Main
# ═══════════════════════════════════════════════════════════════════════════

SCENARIO_CHOICES = ["vitalagent", "claude-code-cli"]

def main():
    parser = argparse.ArgumentParser(description="Temporal Evaluation")
    parser.add_argument(
        "--input", "-i",
        default=str(Path(__file__).parent / "output" / "temporal_dataset_validated.jsonl"),
    )
    parser.add_argument("--output", "-o", default=None)
    parser.add_argument(
        "--scenarios", "-s", nargs="+",
        choices=SCENARIO_CHOICES, default=SCENARIO_CHOICES,
    )
    parser.add_argument("--limit", "-n", type=int, default=None)
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO",
    )
    args = parser.parse_args()
    setup_logging(args.log_level)

    dataset_path = Path(args.input)
    if not dataset_path.exists():
        logger.error(f"Dataset not found: {dataset_path}")
        sys.exit(1)

    cases = load_dataset(str(dataset_path))
    if args.limit:
        cases = cases[:args.limit]
    logger.info(f"Loaded {len(cases)} cases from {dataset_path.name}")

    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(Path(__file__).parent / "output" / f"temporal_eval_{ts}.xlsx")

    scenario_runners = {
        "vitalagent": lambda: run_vitalagent(cases),
        "claude-code-cli": lambda: run_claude_code_cli(cases),
    }

    all_results: Dict[str, List[CaseResult]] = {}
    all_aggs: Dict[str, List[AggregateMetrics]] = {}

    for scenario_key in args.scenarios:
        runner = scenario_runners.get(scenario_key)
        if not runner:
            continue
        logger.info(f"\n{'='*60}\n  Running scenario: {scenario_key}\n{'='*60}")
        t0 = time.time()
        try:
            results = runner()
        except Exception as e:
            logger.error(f"Scenario {scenario_key} failed: {e}")
            continue
        elapsed = time.time() - t0

        # LLM Judge for ambiguous cases
        score_ambiguous_cases(results, cases)

        scenario_name = results[0].scenario if results else scenario_key
        all_results[scenario_name] = results
        all_aggs[scenario_name] = aggregate(results, scenario_name)
        logger.info(f"Scenario {scenario_key} completed in {elapsed:.1f}s ({len(results)} cases)")

    if not all_results:
        logger.error("No scenarios produced results. Exiting.")
        sys.exit(1)

    save_results_xlsx(all_results, all_aggs, output_path)
    print_comparison_table(all_aggs)
    for dim in BREAKDOWN_DIMS:
        print_breakdown(all_aggs, dim)


if __name__ == "__main__":
    main()
