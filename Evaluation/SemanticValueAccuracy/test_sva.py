#!/usr/bin/env python
"""
Semantic Value Accuracy (SVA) Evaluation Script
================================================

Runs sva_dataset.jsonl through multiple scenarios and scores using the
3-Layer scoring system (Resolution / Execution / Value).

Scenarios:
  1. VitalAgent       — Orchestrator full pipeline
  2. Claude Code CLI  — claude subprocess + VitalExecutor

Usage:
    python -m Evaluation.SemanticValueAccuracy.test_sva --scenarios vitalagent claude-code-cli
    python -m Evaluation.SemanticValueAccuracy.test_sva -s vitalagent --limit 5
    python -m Evaluation.SemanticValueAccuracy.test_sva -s claude-code-cli -n 10
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from Evaluation.SemanticValueAccuracy.config import Paths, ScoringWeights
from Evaluation.SemanticValueAccuracy.models import SVAMetrics, SVAResult
from Evaluation.SemanticValueAccuracy.utils.scoring import (
    compute_composite,
    extract_params_from_code,
    parse_agent_answer,
    score_execution,
    score_resolution,
    score_value,
)


def setup_logging(level: str = "INFO"):
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [SVA-Eval] %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    for name in ("httpx", "httpcore", "openai", "urllib3", "anthropic"):
        logging.getLogger(name).setLevel(logging.WARNING)


log = logging.getLogger(__name__)

ANSWER_FORMAT_INSTRUCTION = (
    "Respond with ONLY a JSON object in this exact format: {\"answer\": <value>}\n"
    "- If the answer is a single number: {\"answer\": 77.2}\n"
    "- If the answer is an object: {\"answer\": {\"parameter\": \"X\", \"value\": Y}}\n"
    "- If the answer is a list: {\"answer\": [1.0, 2.0, 3.0]}\n"
    "- If the data does not exist or cannot be computed: {\"answer\": null}"
)

VITAL_DIR = str(Paths.VITAL_DIR)
CLINICAL_CSV = str(Paths.CLINICAL_DATA_CSV)


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_dataset(path: Path) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _log_progress(scenario: str, idx: int, total: int, case_id: str):
    log.info("[%s] (%d/%d) %s", scenario, idx + 1, total, case_id)


def _extract_resolution_info(res: Any) -> Dict:
    """Extract resolved parameters from VitalAgent Orchestrator result."""
    info: Dict[str, Any] = {"resolved_params": [], "generated_code": None}

    try:
        raw = str(res)

        code_patterns = [
            r"```python\n(.*?)\n```",
            r"code='(.*?)'",
            r'code="(.*?)"',
        ]
        for pat in code_patterns:
            m = re.search(pat, raw, re.DOTALL)
            if m:
                info["generated_code"] = m.group(1)
                break

        if info["generated_code"]:
            info["resolved_params"] = extract_params_from_code(info["generated_code"])

        if not info["resolved_params"]:
            param_pattern = r"(?:resolved_param|param_key|track)[s]?\s*[:=]\s*\[([^\]]+)\]"
            pm = re.search(param_pattern, raw, re.IGNORECASE)
            if pm:
                params = re.findall(r"['\"]([^'\"]+)['\"]", pm.group(1))
                info["resolved_params"] = sorted(set(params))

        if not info["resolved_params"]:
            track_pattern = r"['\"]([A-Z][a-zA-Z0-9]+/[A-Z][A-Z0-9_]+)['\"]"
            tracks = re.findall(track_pattern, raw)
            if tracks:
                info["resolved_params"] = sorted(set(tracks))

    except Exception:
        pass

    return info


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 1: VitalAgent (Orchestrator full pipeline)
# ═══════════════════════════════════════════════════════════════════════════

def run_vitalagent(cases: List[Dict]) -> List[SVAResult]:
    from OrchestrationAgent.src.orchestrator import Orchestrator
    orch = Orchestrator()
    results: List[SVAResult] = []

    for idx, case in enumerate(cases):
        _log_progress("VitalAgent", idx, len(cases), case["id"])

        answer_type = case.get("answer_type", "number")
        eq_values = case.get("equivalence_values", {})

        prompt = (
            f"{case['query']}\n\n"
            f"IMPORTANT: When calling `vf.to_numpy(track_names, interval)`, "
            f"you MUST use `interval=1` unless specified otherwise.\n"
            f"{ANSWER_FORMAT_INSTRUCTION}"
        )

        t0 = time.time()
        raw_output = None
        agent_answer = None
        error = None
        code_executed = False

        try:
            res = orch.run(prompt)
            elapsed = (time.time() - t0) * 1000
            raw_output = res.final_answer if hasattr(res, "final_answer") else str(res)
            code_executed = True

            agent_answer = parse_agent_answer(raw_output)

            if hasattr(res, "result") and isinstance(res.result, dict) and "answer" in res.result:
                agent_answer = res.result["answer"]
            elif hasattr(res, "final_answer") and isinstance(res.final_answer, dict) and "answer" in res.final_answer:
                agent_answer = res.final_answer["answer"]

        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            error = str(e)

        extraction = _extract_resolution_info(res if raw_output else "")

        results.append(SVAResult(
            case_id=case["id"],
            scenario="VitalAgent",
            query=case["query"],
            equivalence_values=eq_values,
            answer_type=answer_type,
            agent_output=agent_answer,
            resolved_params=extraction.get("resolved_params", []),
            generated_code=extraction.get("generated_code"),
            execution_time_ms=round(elapsed, 1),
            error_message=error,
            code_executed=code_executed,
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Scenario 2: Claude Code CLI
# ═══════════════════════════════════════════════════════════════════════════

def run_claude_code_cli(cases: List[Dict]) -> List[SVAResult]:
    results: List[SVAResult] = []

    for idx, case in enumerate(cases):
        _log_progress("Claude-Code-CLI", idx, len(cases), case["id"])

        answer_type = case.get("answer_type", "number")
        eq_values = case.get("equivalence_values", {})

        prompt = (
            f"You are a medical data analyst.\n"
            f"Answer the following question: '{case['query']}'\n\n"
            f"Vital files location: {VITAL_DIR}/ (format: NNNN.vital, zero-padded)\n"
            f"You can discover available tracks using: vf = vitaldb.VitalFile(path); vf.get_track_names()\n"
            f"Clinical metadata: {CLINICAL_CSV}\n"
            f"IMPORTANT: You must figure out which track(s) match the clinical concept "
            f"described in the query. Use vf.get_track_names() to explore.\n"
            f"When calling vf.to_numpy(), use interval=1 unless specified otherwise.\n"
            f"{ANSWER_FORMAT_INSTRUCTION}\n"
            f"You MUST output the python code you want to run inside a ```python block. "
            f"Make sure your python code prints the final answer using "
            f"`print(json.dumps({{\"answer\": ...}}))`."
        )

        t0 = time.time()
        raw_output = ""
        error_msg = None
        agent_answer = None
        used_params: List[str] = []
        code: Optional[str] = None
        code_executed = False

        try:
            process = subprocess.run(
                ["claude", "-p", prompt, "--no-session-persistence"],
                capture_output=True,
                text=True,
                timeout=180,
            )
            elapsed = (time.time() - t0) * 1000
            raw_output = process.stdout.strip()

            if not raw_output and process.stderr:
                raw_output = process.stderr.strip()
            if process.returncode != 0:
                error_msg = process.stderr.strip()

            code_match = re.search(r"```python\n(.*?)\n```", raw_output, re.DOTALL)

            if code_match:
                code = code_match.group(1)
                used_params = extract_params_from_code(code)
                try:
                    from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor
                    executor = VitalExecutor()
                    res = executor.execute_code(code)
                    code_executed = True
                    if res["success"]:
                        agent_answer = res["result"]
                    else:
                        error_msg = res.get("error", "execution failed")
                except Exception as e:
                    error_msg = f"Executor error: {e}"
            else:
                agent_answer = parse_agent_answer(raw_output)

        except subprocess.TimeoutExpired:
            elapsed = 180_000
            error_msg = "TimeoutExpired"
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            error_msg = str(e)

        results.append(SVAResult(
            case_id=case["id"],
            scenario="Claude-Code-CLI",
            query=case["query"],
            equivalence_values=eq_values,
            answer_type=answer_type,
            agent_output=agent_answer,
            resolved_params=used_params,
            generated_code=code,
            execution_time_ms=round(elapsed, 1),
            error_message=error_msg,
            code_executed=code_executed,
        ))

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Scoring
# ═══════════════════════════════════════════════════════════════════════════

def score_results(cases: List[Dict], results: List[SVAResult]) -> List[SVAResult]:
    """Apply 3-Layer scoring to each result."""
    case_map = {c["id"]: c for c in cases}

    for r in results:
        case = case_map.get(r.case_id, {})
        answer_type = case.get("answer_type", "number")
        expected_behavior = case.get("resolution_target", {}).get("expected_behavior", "retrieve")

        r.resolution_score, r.resolution_detail = score_resolution(
            case, r.resolved_params, r.agent_output, r.error_message,
        )
        r.execution_score, r.execution_detail = score_execution(
            r.agent_output, r.error_message, expected_behavior, r.code_executed,
        )
        r.value_score, r.value_detail = score_value(
            case, r.agent_output, answer_type,
        )
        r.composite_score = round(compute_composite(
            r.resolution_score, r.execution_score, r.value_score,
        ), 4)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# Aggregation
# ═══════════════════════════════════════════════════════════════════════════

def aggregate_metrics(
    cases: List[Dict],
    results: List[SVAResult],
    scenario: str,
) -> SVAMetrics:
    case_map = {c["id"]: c for c in cases}
    n = len(results)

    if n == 0:
        return SVAMetrics(scenario=scenario, n_cases=0)

    times = [r.execution_time_ms for r in results]
    res_dist = dict(Counter(r.resolution_detail for r in results))

    cat_groups: Dict[str, List[SVAResult]] = defaultdict(list)
    for r in results:
        cat = case_map.get(r.case_id, {}).get("query_category", "unknown")
        cat_groups[cat].append(r)

    cat_breakdown = {}
    for cat, group in cat_groups.items():
        cat_breakdown[cat] = {
            "resolution": round(sum(r.resolution_score for r in group) / len(group), 4),
            "execution": round(sum(r.execution_score for r in group) / len(group), 4),
            "value": round(sum(r.value_score for r in group) / len(group), 4),
            "composite": round(sum(r.composite_score for r in group) / len(group), 4),
            "count": len(group),
        }

    style_groups: Dict[str, List[SVAResult]] = defaultdict(list)
    for r in results:
        style = case_map.get(r.case_id, {}).get("query_style", "unknown")
        style_groups[style].append(r)

    style_breakdown = {}
    for style, group in style_groups.items():
        style_breakdown[style] = {
            "resolution": round(sum(r.resolution_score for r in group) / len(group), 4),
            "execution": round(sum(r.execution_score for r in group) / len(group), 4),
            "value": round(sum(r.value_score for r in group) / len(group), 4),
            "composite": round(sum(r.composite_score for r in group) / len(group), 4),
            "count": len(group),
        }

    return SVAMetrics(
        scenario=scenario,
        n_cases=n,
        resolution_accuracy=round(sum(r.resolution_score for r in results) / n, 4),
        execution_rate=round(sum(r.execution_score for r in results) / n, 4),
        value_accuracy=round(sum(r.value_score for r in results) / n, 4),
        composite_score=round(sum(r.composite_score for r in results) / n, 4),
        avg_time_ms=round(sum(times) / n, 1),
        category_breakdown=cat_breakdown,
        style_breakdown=style_breakdown,
        resolution_distribution=res_dist,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Console output
# ═══════════════════════════════════════════════════════════════════════════

def print_scenario_results(metrics: SVAMetrics) -> None:
    print(f"\n{'═' * 70}")
    print(f"  SVA Evaluation — {metrics.scenario}")
    print(f"{'═' * 70}")
    print(f"  Cases: {metrics.n_cases}    Avg time: {metrics.avg_time_ms:.0f}ms")
    print(f"  Weights: Res={ScoringWeights.RESOLUTION}, "
          f"Exec={ScoringWeights.EXECUTION}, Val={ScoringWeights.VALUE}")
    print(f"\n  {'Metric':<25} {'Score':>8}")
    print(f"  {'-' * 25} {'-' * 8}")
    print(f"  {'Resolution Accuracy':<25} {metrics.resolution_accuracy:>8.4f}")
    print(f"  {'Execution Rate':<25} {metrics.execution_rate:>8.4f}")
    print(f"  {'Value Accuracy':<25} {metrics.value_accuracy:>8.4f}")
    print(f"  {'Composite Score':<25} {metrics.composite_score:>8.4f}")

    print(f"\n  Resolution Distribution:")
    for label, count in sorted(metrics.resolution_distribution.items()):
        print(f"    {label:<25} {count:>3}")

    print(f"\n  Category Breakdown:")
    print(f"    {'Category':<25} {'Res':>6} {'Exec':>6} {'Val':>6} {'Comp':>6} {'N':>4}")
    print(f"    {'-' * 25} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 6} {'-' * 4}")
    for cat, m in sorted(metrics.category_breakdown.items()):
        print(f"    {cat:<25} {m['resolution']:>6.2f} {m['execution']:>6.2f} "
              f"{m['value']:>6.2f} {m['composite']:>6.2f} {m['count']:>4}")

    print(f"{'═' * 70}\n")


def print_comparison_table(all_metrics: Dict[str, SVAMetrics]) -> None:
    print(f"\n{'═' * 80}")
    print("  SVA Evaluation — Scenario Comparison")
    print(f"{'═' * 80}")
    header = (f"  {'Scenario':<20} {'N':>4} {'Res':>8} {'Exec':>8} "
              f"{'Val':>8} {'Comp':>8} {'Avg(ms)':>10}")
    print(header)
    print(f"  {'-' * 72}")
    for name, m in all_metrics.items():
        print(f"  {name:<20} {m.n_cases:>4} {m.resolution_accuracy:>8.4f} "
              f"{m.execution_rate:>8.4f} {m.value_accuracy:>8.4f} "
              f"{m.composite_score:>8.4f} {m.avg_time_ms:>10.0f}")
    print(f"{'═' * 80}\n")


# ═══════════════════════════════════════════════════════════════════════════
# Excel output
# ═══════════════════════════════════════════════════════════════════════════

def save_excel(
    cases: List[Dict],
    all_results: Dict[str, List[SVAResult]],
    all_metrics: Dict[str, SVAMetrics],
    output_path: Path,
) -> None:
    case_map = {c["id"]: c for c in cases}

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Comparison
        comp_rows = []
        for scenario, m in all_metrics.items():
            comp_rows.append({
                "Scenario": scenario,
                "N": m.n_cases,
                "Resolution": m.resolution_accuracy,
                "Execution": m.execution_rate,
                "Value": m.value_accuracy,
                "Composite": m.composite_score,
                "Avg Time (ms)": m.avg_time_ms,
            })
        pd.DataFrame(comp_rows).to_excel(writer, sheet_name="Comparison", index=False)

        # Category breakdown
        cat_rows = []
        for scenario, m in all_metrics.items():
            for cat, d in m.category_breakdown.items():
                cat_rows.append({"Scenario": scenario, "Category": cat, **d})
        if cat_rows:
            pd.DataFrame(cat_rows).to_excel(writer, sheet_name="Category_Breakdown", index=False)

        # Style breakdown
        style_rows = []
        for scenario, m in all_metrics.items():
            for sty, d in m.style_breakdown.items():
                style_rows.append({"Scenario": scenario, "Style": sty, **d})
        if style_rows:
            pd.DataFrame(style_rows).to_excel(writer, sheet_name="Style_Breakdown", index=False)

        # Detail
        detail_rows = []
        for scenario, results in all_results.items():
            for r in results:
                c = case_map.get(r.case_id, {})
                detail_rows.append({
                    "Scenario": scenario,
                    "Case ID": r.case_id,
                    "Category": c.get("query_category", ""),
                    "Style": c.get("query_style", ""),
                    "Answer Type": c.get("answer_type", ""),
                    "Query": r.query[:200],
                    "Equivalence Group": str(c.get("resolution_target", {}).get("equivalence_group", [])),
                    "Resolved Params": str(r.resolved_params or []),
                    "Agent Output": str(r.agent_output)[:200] if r.agent_output is not None else "",
                    "Equivalence Values": str(r.equivalence_values)[:200],
                    "Resolution": r.resolution_score,
                    "Res Detail": r.resolution_detail,
                    "Execution": r.execution_score,
                    "Exec Detail": r.execution_detail,
                    "Value": r.value_score,
                    "Val Detail": r.value_detail,
                    "Composite": r.composite_score,
                    "Time (ms)": r.execution_time_ms,
                    "Error": r.error_message or "",
                })
        if detail_rows:
            pd.DataFrame(detail_rows).to_excel(writer, sheet_name="Detail", index=False)

    log.info("Results saved to %s", output_path)


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

SCENARIO_CHOICES = ["vitalagent", "claude-code-cli"]

SCENARIO_RUNNERS = {
    "vitalagent": ("VitalAgent", run_vitalagent),
    "claude-code-cli": ("Claude-Code-CLI", run_claude_code_cli),
}


def main():
    parser = argparse.ArgumentParser(
        description="SVA Evaluation — compare VitalAgent vs Claude Code CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dataset", "-i", type=str, default=None,
        help=f"Path to dataset (default: {Paths.FINAL_DATASET})",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output xlsx path (default: auto-timestamped)",
    )
    parser.add_argument(
        "--scenarios", "-s", nargs="+",
        choices=SCENARIO_CHOICES, default=SCENARIO_CHOICES,
        help="Which scenarios to run (default: all)",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None,
        help="Process at most N cases.",
    )
    parser.add_argument(
        "--log-level", "-l",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    dataset_path = Path(args.dataset) if args.dataset else Paths.FINAL_DATASET
    if not dataset_path.exists():
        log.error("Dataset not found: %s", dataset_path)
        sys.exit(1)

    cases = load_dataset(dataset_path)
    if args.limit:
        cases = cases[: args.limit]
    log.info("Loaded %d cases from %s", len(cases), dataset_path.name)

    if args.output:
        output_path = Path(args.output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Paths.OUTPUT_DIR / f"sva_eval_{ts}.xlsx"

    all_results: Dict[str, List[SVAResult]] = {}
    all_metrics: Dict[str, SVAMetrics] = {}

    for scenario_key in args.scenarios:
        display_name, runner = SCENARIO_RUNNERS[scenario_key]
        log.info("=" * 60)
        log.info("  Running scenario: %s", display_name)
        log.info("=" * 60)

        t0 = time.time()
        try:
            results = runner(cases)
        except Exception as e:
            log.error("Scenario %s failed: %s", scenario_key, e, exc_info=True)
            continue
        wall_time = time.time() - t0

        results = score_results(cases, results)
        metrics = aggregate_metrics(cases, results, display_name)

        all_results[display_name] = results
        all_metrics[display_name] = metrics

        print_scenario_results(metrics)
        log.info("Scenario %s completed in %.1fs (%d cases)",
                 display_name, wall_time, len(results))

    if not all_results:
        log.error("No scenarios produced results. Exiting.")
        sys.exit(1)

    # Comparison table (only when multiple scenarios)
    if len(all_metrics) > 1:
        print_comparison_table(all_metrics)

    # Save
    save_excel(cases, all_results, all_metrics, output_path)

    summary_path = output_path.with_suffix(".json")
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "scenarios": {k: m.model_dump() for k, m in all_metrics.items()},
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log.info("JSON summary saved to %s", summary_path)


if __name__ == "__main__":
    main()
