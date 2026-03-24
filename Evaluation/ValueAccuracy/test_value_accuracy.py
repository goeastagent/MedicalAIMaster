#!/usr/bin/env python
"""
Value Accuracy Evaluation Script
================================

Runs value_accuracy_dataset.jsonl through multiple scenarios and compares
the calculated values against the ground truth:

  1. VitalAgent (MedicalAIMaster) Full Pipeline
  2. Claude Code CLI

Metrics per case:
  - Value Match: True if the agent's output matches the expected_value exactly (or within a tolerance for floats).
  - Execution Time

Results are saved to an xlsx workbook (summary + detail sheets).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import sys
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

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

logger = logging.getLogger("ValueAccuracyEval")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    """Evaluation result for a single (case, scenario) pair."""
    case_id: str
    scenario: str
    query: str
    question_type: str
    query_style: str
    
    # ground truth
    expected_value: Any
    
    # system output
    agent_output: Any
    
    # metrics
    value_match: bool = False
    
    # debug
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    raw_response: Optional[str] = None

@dataclass
class AggregateMetrics:
    """Aggregated metrics for a scenario, optionally sliced by a dimension."""
    scenario: str
    slice_name: str = "overall"
    slice_value: str = "all"
    count: int = 0
    accuracy: float = 0.0
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

def compare_values(expected: Any, actual: Any) -> bool:
    """
    Compares the expected value with the actual value returned by the agent.
    Handles None, scalars (int, float, str), and lists of dicts.
    """
    # If actual is a string that looks like a dict, try to parse it
    if isinstance(actual, str):
        try:
            # Sometimes it's wrapped in quotes or has single quotes
            actual_parsed = json.loads(actual.replace("'", '"'))
            if isinstance(actual_parsed, dict) and "answer" in actual_parsed:
                actual = actual_parsed["answer"]
        except Exception:
            pass

    if expected is None:
        # For adversarial queries, the agent might return None, "None", "0", 0, or an empty list/dict
        if actual is None or actual == "None" or actual == "null":
            return True
        if isinstance(actual, (list, dict)) and len(actual) == 0:
            return True
        # Sometimes agents return 0 when nothing is found
        if actual == 0 or actual == "0":
             return True
        return False
        
    if isinstance(expected, (int, float)):
        try:
            actual_float = float(actual)
            # Use a small tolerance for floating point comparisons
            return abs(float(expected) - actual_float) < 1e-5
        except (ValueError, TypeError):
            return False
            
    if isinstance(expected, str):
        return str(expected).strip().lower() == str(actual).strip().lower()
        
    if isinstance(expected, list):
        # Complex objects (like group by results)
        # For simplicity in this benchmark, we convert both to sorted string representations
        # A more robust approach would be deep dictionary comparison
        try:
            # Try to parse actual if it's a string representation of JSON
            if isinstance(actual, str):
                actual_parsed = json.loads(actual.replace("'", '"'))
            else:
                actual_parsed = actual
                
            if isinstance(actual_parsed, list) and len(expected) == len(actual_parsed):
                # Sort both lists of dicts by their string representation to compare
                exp_sorted = sorted([json.dumps(d, sort_keys=True) for d in expected])
                act_sorted = sorted([json.dumps(d, sort_keys=True) for d in actual_parsed])
                return exp_sorted == act_sorted
        except Exception:
            pass
            
        # Fallback to string inclusion check
        str_expected = str(expected)
        str_actual = str(actual)
        return str_expected == str_actual

    return str(expected) == str(actual)

# ═══════════════════════════════════════════════════════════════════════════
# 3. Scenario runners
# ═══════════════════════════════════════════════════════════════════════════

# ---- 3-A  VitalAgent (MedicalAIMaster) Full Pipeline ----------------------

def run_vitalagent(cases: List[Dict], progress_cb=None) -> List[CaseResult]:
    from OrchestrationAgent.src.orchestrator import Orchestrator
    orch = Orchestrator()
    results: List[CaseResult] = []

    for idx, case in enumerate(cases):
        _log_progress("VitalAgent", idx, len(cases), case["id"])
        t0 = time.time()
        
        # Modify query to ask for JSON output
        prompt = f"{case['query']}\n\nPlease output ONLY a JSON object with a single key 'answer' containing the final calculated value. Do not include any other text.\nIMPORTANT: When calling `vf.to_numpy(track_names, interval)`, you MUST use `interval=1` to match the expected ground truth calculation. If the query specifies a different interval or sampling rate (like 100 Hz, which means interval=1/100), use that instead. However, note that if the query says 'sampled at 100 Hz', it means you should pass `100` as the interval argument to `to_numpy` (e.g. `vf.to_numpy(['track'], 100)`), NOT `1/100`."
        
        raw_output = None
        agent_answer = None
        error = None
        
        try:
            res = orch.run(prompt)
            elapsed = (time.time() - t0) * 1000
            raw_output = res.final_answer if hasattr(res, 'final_answer') else str(res)
            
            # Try to extract JSON from the final answer
            json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    agent_answer = parsed.get("answer", raw_output)
                except json.JSONDecodeError:
                    agent_answer = raw_output
            else:
                agent_answer = raw_output
                
            # If the agent answer is a dict, it might be the raw result object, let's try to extract answer
            if hasattr(res, 'result') and isinstance(res.result, dict) and "answer" in res.result:
                agent_answer = res.result["answer"]
            elif isinstance(agent_answer, dict) and "answer" in agent_answer:
                agent_answer = agent_answer["answer"]
            elif hasattr(res, 'final_answer') and isinstance(res.final_answer, dict) and "answer" in res.final_answer:
                agent_answer = res.final_answer["answer"]
            elif isinstance(raw_output, str) and "answer" in raw_output:
                # Sometimes the raw_output is a string representation of the result object
                try:
                    # Look for result={'answer': 365.44}
                    match = re.search(r"result=\{'answer':\s*([^}]+)\}", raw_output)
                    if match:
                        agent_answer = float(match.group(1))
                except Exception:
                    pass
                
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            error = str(e)

        match = compare_values(case["expected_value"], agent_answer)
        
        cr = CaseResult(
            case_id=case["id"],
            scenario="VitalAgent",
            query=case["query"],
            question_type=case.get("question_type", ""),
            query_style=case.get("query_style", ""),
            expected_value=case["expected_value"],
            agent_output=agent_answer,
            value_match=match,
            execution_time_ms=elapsed,
            error_message=error,
            raw_response=raw_output
        )
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))
            
    return results


# ---- 3-B  Claude Code CLI ------------------------------------------------

def run_claude_code_cli(cases: List[Dict], progress_cb=None) -> List[CaseResult]:
    results: List[CaseResult] = []

    for idx, case in enumerate(cases):
        _log_progress("Claude-Code-CLI", idx, len(cases), case["id"])
        
        prompt = (
            f"You are a medical data analyst. You need to write a python script that uses `vitaldb` to answer the following question: '{case['query']}'.\n\n"
            f"The vital files are located at `/Users/goeastagent/products/MedicalAIMaster/IndexingAgent/data/raw/Open_VitalDB_1.0.0/vital_files/`.\n"
            f"IMPORTANT: Vital file names use 4-digit zero-padded caseids (e.g., `0001.vital`, `0002.vital`, `0009.vital`). Use `str(caseid).zfill(4) + '.vital'` to construct the filename.\n"
            f"Return ONLY a JSON object in this format: "
            f"{{\"answer\": <your_calculated_value>}} "
            f"If the answer is empty or not found, return null for the answer.\n"
            f"You MUST output the python code you want to run. Do NOT try to run it yourself, just output the code inside a ```python block. I will run it for you.\n"
            f"IMPORTANT: When calling `vf.to_numpy(track_names, interval)`, you MUST use `interval=1` to match the expected ground truth calculation. If the query specifies a different interval or sampling rate (like 100 Hz, which means interval=1/100), use that instead. However, note that if the query says 'sampled at 100 Hz', it means you should pass `100` as the interval argument to `to_numpy` (e.g. `vf.to_numpy(['track'], 100)`), NOT `1/100`.\n"
            f"IMPORTANT: Make sure your python code prints the final answer using `print(json.dumps({{\"answer\": ...}}))`."
        )

        t0 = time.time()
        raw_output = ""
        error_msg = None
        agent_answer = None

        try:
            # Using the same command structure as Level1
            process = subprocess.run(
                ["claude", "-p", prompt, "--no-session-persistence"],
                capture_output=True,
                text=True,
                timeout=120 # Give it more time since it might need to run SQL
            )
            elapsed = (time.time() - t0) * 1000
            raw_output = process.stdout.strip()
            
            # If stdout is empty, check stderr
            if not raw_output and process.stderr:
                raw_output = process.stderr.strip()
                
            if process.returncode != 0:
                error_msg = process.stderr.strip()

            json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
            code_match = re.search(r'```python\n(.*?)\n```', raw_output, re.DOTALL)
            
            if code_match:
                code = code_match.group(1)
                try:
                    from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor
                    executor = VitalExecutor()
                    res = executor.execute_code(code)
                    if res["success"]:
                        agent_answer = res["result"]
                    else:
                        agent_answer = f"Error: {res['error']}"
                except Exception as e:
                    agent_answer = f"Error executing code: {e}"
            elif json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    agent_answer = parsed.get("answer")
                except json.JSONDecodeError:
                    agent_answer = raw_output
            else:
                agent_answer = raw_output
                
        except subprocess.TimeoutExpired:
            elapsed = 120000
            error_msg = "TimeoutExpired"
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            error_msg = str(e)

        match = compare_values(case["expected_value"], agent_answer)

        cr = CaseResult(
            case_id=case["id"],
            scenario="Claude-Code-CLI",
            query=case["query"],
            question_type=case.get("question_type", ""),
            query_style=case.get("query_style", ""),
            expected_value=case["expected_value"],
            agent_output=agent_answer,
            value_match=match,
            execution_time_ms=elapsed,
            error_message=error_msg,
            raw_response=raw_output
        )
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))

    return results

# ═══════════════════════════════════════════════════════════════════════════
# 4. Aggregation
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

def _agg_slice(
    results: List[CaseResult], scenario: str, dim: str, val: str
) -> AggregateMetrics:
    n = len(results)
    if n == 0:
        return AggregateMetrics(scenario=scenario, slice_name=dim, slice_value=val)
    times = sorted(r.execution_time_ms for r in results)
    return AggregateMetrics(
        scenario=scenario,
        slice_name=dim,
        slice_value=val,
        count=n,
        accuracy=sum(1 for r in results if r.value_match) / n,
        mean_time_ms=statistics.mean(times),
        median_time_ms=statistics.median(times),
        min_time_ms=times[0],
        max_time_ms=times[-1],
        p95_time_ms=_percentile(times, 95),
    )

# ═══════════════════════════════════════════════════════════════════════════
# 5. XLSX output
# ═══════════════════════════════════════════════════════════════════════════

def save_results_xlsx(
    all_results: Dict[str, List[CaseResult]],
    all_aggs: Dict[str, List[AggregateMetrics]],
    output_path: str,
):
    detail_rows: List[Dict] = []
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
                "time_ms": round(r.execution_time_ms, 1),
                "error": r.error_message or "",
                "raw_response": r.raw_response or ""
            })
    df_detail = pd.DataFrame(detail_rows)

    agg_rows: List[Dict] = []
    for scenario, aggs in all_aggs.items():
        for a in aggs:
            agg_rows.append({
                "scenario": a.scenario,
                "dimension": a.slice_name,
                "value": a.slice_value,
                "count": a.count,
                "accuracy%": round(a.accuracy * 100, 2),
                "avg_ms": round(a.mean_time_ms, 1),
                "median_ms": round(a.median_time_ms, 1),
                "min_ms": round(a.min_time_ms, 1),
                "max_ms": round(a.max_time_ms, 1),
                "p95_ms": round(a.p95_time_ms, 1),
            })
    df_agg = pd.DataFrame(agg_rows)

    # Pivot: scenarios as columns, overall metrics
    overall = df_agg[df_agg["dimension"] == "overall"].set_index("scenario")
    pivot_cols = ["count", "accuracy%", "avg_ms", "median_ms", "min_ms", "max_ms", "p95_ms"]
    df_pivot = overall[pivot_cols].T if not overall.empty else pd.DataFrame()

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        if not df_pivot.empty:
            df_pivot.to_excel(writer, sheet_name="Comparison")
        df_agg.to_excel(writer, sheet_name="Aggregated", index=False)
        df_detail.to_excel(writer, sheet_name="Detail", index=False)

    logger.info(f"Results saved to {output_path}")

# ═══════════════════════════════════════════════════════════════════════════
# 6. Console summary
# ═══════════════════════════════════════════════════════════════════════════

def print_comparison_table(all_aggs: Dict[str, List[AggregateMetrics]]):
    header = f"{'Scenario':<30} {'N':>4} {'Accuracy%':>10} {'Avg(ms)':>10} {'Med(ms)':>10} {'P95(ms)':>10}"
    print(f"\n{'=' * 80}")
    print("  Value Accuracy Evaluation — Scenario Comparison")
    print(f"{'=' * 80}")
    print(header)
    print("-" * 80)
    for scenario, aggs in all_aggs.items():
        ov = next((a for a in aggs if a.slice_name == "overall"), None)
        if not ov:
            continue
        print(
            f"{ov.scenario:<30} {ov.count:>4} {ov.accuracy * 100:>9.2f}%"
            f" {ov.mean_time_ms:>10.1f} {ov.median_time_ms:>10.1f} {ov.p95_time_ms:>10.1f}"
        )
    print(f"{'=' * 80}\n")

def print_breakdown(all_aggs: Dict[str, List[AggregateMetrics]], dim: str):
    print(f"\n--- Breakdown by {dim} ---")
    header = f"{'Scenario':<30} {dim:<25} {'N':>4} {'Accuracy%':>10} {'Avg(ms)':>10}"
    print(header)
    print("-" * 85)
    for scenario, aggs in all_aggs.items():
        for a in aggs:
            if a.slice_name != dim:
                continue
            print(
                f"{a.scenario:<30} {a.slice_value:<25} {a.count:>4} {a.accuracy * 100:>9.2f}%"
                f" {a.mean_time_ms:>10.1f}"
            )

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _log_progress(scenario: str, idx: int, total: int, case_id: str):
    logger.info(f"[{scenario}] ({idx + 1}/{total}) {case_id}")

# ═══════════════════════════════════════════════════════════════════════════
# 7. Main
# ═══════════════════════════════════════════════════════════════════════════

SCENARIO_CHOICES = [
    "vitalagent",
    "claude-code-cli",
]

def main():
    parser = argparse.ArgumentParser(
        description="Value Accuracy Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        default=str(Path(__file__).parent / "output" / "value_accuracy_dataset.jsonl"),
        help="Path to value_accuracy_dataset.jsonl",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output xlsx path (default: auto-timestamped)",
    )
    parser.add_argument(
        "--scenarios", "-s",
        nargs="+",
        choices=SCENARIO_CHOICES,
        default=SCENARIO_CHOICES,
        help="Which scenarios to run (default: all)",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        help="Limit number of cases (for quick testing)",
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    # ---- Load dataset ----
    dataset_path = Path(args.input)
    if not dataset_path.exists():
        logger.error(f"Dataset not found: {dataset_path}")
        sys.exit(1)

    cases = load_dataset(str(dataset_path))
    if args.limit:
        cases = cases[: args.limit]
    logger.info(f"Loaded {len(cases)} cases from {dataset_path.name}")

    # ---- Output path ----
    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(Path(__file__).parent / "output" / f"value_accuracy_eval_{ts}.xlsx")

    # ---- Run scenarios ----
    all_results: Dict[str, List[CaseResult]] = {}
    all_aggs: Dict[str, List[AggregateMetrics]] = {}

    scenario_runners = {
        "vitalagent": lambda: run_vitalagent(cases),
        "claude-code-cli": lambda: run_claude_code_cli(cases),
    }

    for scenario_key in args.scenarios:
        runner = scenario_runners.get(scenario_key)
        if not runner:
            continue
        logger.info(f"\n{'='*60}")
        logger.info(f"  Running scenario: {scenario_key}")
        logger.info(f"{'='*60}")
        t0 = time.time()
        try:
            results = runner()
        except Exception as e:
            logger.error(f"Scenario {scenario_key} failed: {e}")
            continue
        elapsed = time.time() - t0
        scenario_name = results[0].scenario if results else scenario_key
        all_results[scenario_name] = results
        all_aggs[scenario_name] = aggregate(results, scenario_name)
        logger.info(f"Scenario {scenario_key} completed in {elapsed:.1f}s ({len(results)} cases)")

    if not all_results:
        logger.error("No scenarios produced results. Exiting.")
        sys.exit(1)

    # ---- Save & print ----
    save_results_xlsx(all_results, all_aggs, output_path)
    print_comparison_table(all_aggs)
    for dim in BREAKDOWN_DIMS:
        print_breakdown(all_aggs, dim)

if __name__ == "__main__":
    main()
