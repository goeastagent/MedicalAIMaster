#!/usr/bin/env python
"""
Level 1 Evaluation Script — Parameter Retrieval Accuracy
=========================================================

Runs level1_dataset.json through multiple scenarios and compares
parameter retrieval accuracy:

  1. VitalAgent Full Pipeline   (Orchestrator.run)
  2. VitalAgent Extraction-Only (ExtractionFacade.extract_with_state)
  3. GPT-4o  + Parameter List
  4. Claude  + Parameter List
  5. GPT-4o  + Parameter List + Synonym Map
  6. Claude  + Parameter List + Synonym Map

Metrics per case:
  - Parameter Recall     |retrieved ∩ required| / |required|
  - Parameter Precision  |retrieved ∩ accepted| / |retrieved|
  - F1                   harmonic mean of the above
  - Behavior Match       retrieve / not_found / clarify exact match

Results are saved to an xlsx workbook (summary + detail sheets).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import statistics
import sys
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


logger = logging.getLogger("Level1Eval")

# ---------------------------------------------------------------------------
# API keys & models (hardcoded as requested)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-4o"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    """Evaluation result for a single (case, scenario) pair."""
    case_id: str
    scenario: str
    query: str
    query_type: str
    query_style: str
    difficulty: str
    category: str
    num_required_params: int

    # ground truth
    expected_params: List[str]
    acceptable_alternatives: Dict[str, List[str]]
    expected_behavior: str          # retrieve | not_found | clarify

    # system output
    retrieved_params: List[str]
    detected_behavior: str          # retrieve | not_found | clarify

    # metrics
    recall: float = 0.0
    precision: float = 0.0
    f1: float = 0.0
    behavior_match: bool = False

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
    mean_recall: float = 0.0
    mean_precision: float = 0.0
    mean_f1: float = 0.0
    behavior_accuracy: float = 0.0
    perfect_recall_rate: float = 0.0   # recall == 1.0
    mean_time_ms: float = 0.0
    median_time_ms: float = 0.0
    min_time_ms: float = 0.0
    max_time_ms: float = 0.0
    p95_time_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 1. Dataset loader
# ═══════════════════════════════════════════════════════════════════════════

def load_level1_dataset(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Metric computation
# ═══════════════════════════════════════════════════════════════════════════

def _build_accepted_set(
    required: List[str],
    alternatives: Dict[str, List[str]],
) -> Dict[str, set]:
    """Return a mapping from each required param to the set of all accepted keys."""
    accepted = {}
    for rp in required:
        alts = set(alternatives.get(rp, []))
        alts.add(rp)
        accepted[rp] = alts
    return accepted


def compute_metrics(
    required: List[str],
    alternatives: Dict[str, List[str]],
    retrieved: List[str],
    expected_behavior: str,
    detected_behavior: str,
    acceptable_behaviors: Optional[List[str]] = None,
    confusing_valid_params: Optional[List[str]] = None,
) -> Tuple[float, float, float, bool]:
    """Return (recall, precision, f1, behavior_match)."""

    if acceptable_behaviors:
        behavior_match = detected_behavior in acceptable_behaviors
    else:
        behavior_match = expected_behavior == detected_behavior

    # For confusing adversarial: if system retrieved a valid param, score it
    if (expected_behavior != "retrieve"
            and detected_behavior == "retrieve"
            and confusing_valid_params
            and retrieved):
        valid_set = set(confusing_valid_params)
        retrieved_set = set(retrieved)
        hits = retrieved_set & valid_set
        if hits:
            precision = len(hits) / len(retrieved_set)
            return 1.0, precision, 2 * precision / (1 + precision), True

    if expected_behavior != "retrieve":
        recall = 1.0 if behavior_match else 0.0
        precision = 1.0 if behavior_match else 0.0
        f1 = 1.0 if behavior_match else 0.0
        return recall, precision, f1, behavior_match

    if not required:
        return (1.0, 1.0, 1.0, behavior_match) if not retrieved else (1.0, 0.0, 0.0, behavior_match)

    accepted_map = _build_accepted_set(required, alternatives)
    retrieved_set = set(retrieved)

    # Recall: for each required param, check if ANY of its accepted variants was retrieved
    hits = 0
    for rp in required:
        if retrieved_set & accepted_map[rp]:
            hits += 1
    recall = hits / len(required)

    # Precision: for each retrieved param, check if it belongs to any accepted set
    all_accepted = set()
    for s in accepted_map.values():
        all_accepted |= s
    if retrieved:
        precision_hits = sum(1 for p in retrieved if p in all_accepted)
        precision = precision_hits / len(retrieved)
    else:
        precision = 0.0

    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return recall, precision, f1, behavior_match


# ═══════════════════════════════════════════════════════════════════════════
# 3. Param extraction helpers
# ═══════════════════════════════════════════════════════════════════════════

PARAM_KEY_RE = re.compile(r"\b[A-Za-z0-9]+/[A-Za-z0-9_]+\b")


def extract_params_from_plan(plan: Optional[Dict[str, Any]]) -> List[str]:
    """Extract param_keys from an ExtractionAgent execution_plan."""
    if not plan:
        return []
    params: set = set()
    exec_plan = plan.get("execution_plan", plan)
    signal = exec_plan.get("signal_source") or {}
    for p in signal.get("parameters", []):
        for key in p.get("param_keys", []):
            params.add(key)
    return sorted(params)


def extract_params_from_data_summary(summary: Optional[Dict[str, Any]]) -> List[str]:
    if not summary:
        return []
    return sorted(summary.get("param_keys", []))


def extract_params_from_code(code: Optional[str]) -> List[str]:
    """Regex-based extraction from generated Python code."""
    if not code:
        return []
    return sorted(set(PARAM_KEY_RE.findall(code)))


def detect_behavior_from_orchestration(result) -> str:
    """Infer expected_behavior from an OrchestrationResult."""
    if result.ambiguities:
        return "clarify"
    if result.status == "error":
        if result.error_stage == "extraction":
            return "not_found"
        if result.error_message and "not found" in result.error_message.lower():
            return "not_found"
    return "retrieve"


def detect_behavior_from_extraction(result) -> str:
    """Infer behavior from ExtractionResult (facade)."""
    if result.has_ambiguity and result.ambiguities:
        return "clarify"
    if not result.success:
        return "not_found"
    plan_params = extract_params_from_plan(result.execution_plan)
    if not plan_params:
        return "not_found"
    return "retrieve"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Scenario runners
# ═══════════════════════════════════════════════════════════════════════════

# ---- 4-A  VitalAgent Full Pipeline ----------------------------------------

def run_vitalagent_full(cases: List[Dict], progress_cb=None) -> List[CaseResult]:
    from OrchestrationAgent.src.orchestrator import Orchestrator
    orch = Orchestrator()
    results: List[CaseResult] = []

    for idx, case in enumerate(cases):
        _log_progress("VitalAgent-Full", idx, len(cases), case["id"])
        t0 = time.time()
        try:
            res = orch.run(case["query"])
            elapsed = (time.time() - t0) * 1000

            plan_params = extract_params_from_plan(res.extraction_plan)
            summary_params = extract_params_from_data_summary(
                res.data_summary if isinstance(res.data_summary, dict) else None
            )
            code_params = extract_params_from_code(res.generated_code)
            retrieved = sorted(set(plan_params + summary_params + code_params))
            detected = detect_behavior_from_orchestration(res)
            error = res.error_message
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            retrieved, detected, error = [], "not_found", str(e)

        cr = _build_case_result("VitalAgent-Full", case, retrieved, detected, elapsed, error)
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))
    return results


# ---- 4-B  VitalAgent Extraction-Only -------------------------------------

def run_vitalagent_extraction(cases: List[Dict], progress_cb=None) -> List[CaseResult]:
    from ExtractionAgent.src.facade import ExtractionFacade
    facade = ExtractionFacade()
    results: List[CaseResult] = []

    for idx, case in enumerate(cases):
        _log_progress("VitalAgent-Extraction", idx, len(cases), case["id"])
        t0 = time.time()
        try:
            res = facade.extract_with_state(case["query"])
            elapsed = (time.time() - t0) * 1000
            retrieved = extract_params_from_plan(res.execution_plan)
            detected = detect_behavior_from_extraction(res)
            error = res.error_message
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            retrieved, detected, error = [], "not_found", str(e)

        cr = _build_case_result("VitalAgent-Extraction", case, retrieved, detected, elapsed, error)
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))
    return results


# ---- 4-C  Claude Code CLI ------------------------------------------------

def run_claude_code_cli(cases: List[Dict], progress_cb=None) -> List[CaseResult]:
    results: List[CaseResult] = []

    OPENVITALDB_DIR = "/Users/goeastagent/products/ClaudeCodeTest/Open_VitalDB_1.0.0"

    for idx, case in enumerate(cases):
        _log_progress("Claude-Code-CLI", idx, len(cases), case["id"])
        query = case["query"]
        prompt = (
            f"You are a medical data parameter retrieval system for VitalDB intraoperative biosignal data. "
            f"Read the file 'track_names.csv' in the current directory to look up the exact parameter keys. "
            f"Given the query, identify which parameter key(s) from track_names.csv are needed. "
            f"Return ONLY a JSON object in this format: "
            f"{{\"param_keys\": [\"Device/Param1\"], \"behavior\": \"retrieve\"}} "
            f"If the required parameter does not exist in track_names.csv, set behavior to \"not_found\" and param_keys to []. "
            f"If the query is ambiguous (multiple devices could apply), set behavior to \"clarify\" and param_keys to []. "
            f"Do not invent parameter keys — only use keys from track_names.csv.\n\n"
            f"Query: {query}"
        )

        t0 = time.time()
        raw_output = ""
        error_msg = None
        retrieved = []
        detected = "not_found"

        try:
            process = subprocess.run(
                ["claude", "-p", prompt, "--no-session-persistence"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=OPENVITALDB_DIR
            )
            elapsed = (time.time() - t0) * 1000
            raw_output = process.stdout.strip()
            if process.returncode != 0:
                error_msg = process.stderr.strip()

            json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                retrieved = parsed.get("param_keys", [])
                detected = parsed.get("behavior", "retrieve")
        except subprocess.TimeoutExpired:
            elapsed = 60000
            error_msg = "TimeoutExpired"
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            error_msg = str(e)

        cr = _build_case_result("Claude-Code-CLI", case, retrieved, detected, elapsed, error_msg, raw_output)
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))

    return results


# ---- 4-D  Baseline LLM ---------------------------------------------------

BASELINE_SYSTEM_PROMPT = """\
You are a medical data parameter retrieval system for the VitalDB intraoperative dataset.

Given a natural language query about intraoperative medical data,
identify which parameter keys from the available database should be retrieved.

## Rules
1. Return ONLY param_keys that appear in the Available Parameters list.
2. If the query is too vague or ambiguous to determine specific parameters, set behavior to "clarify".
3. If the requested measurement does not exist in the parameter list, set behavior to "not_found".
4. Otherwise set behavior to "retrieve" and list the matching param_keys.

## Response Format (strict JSON, no markdown fences)
{{"param_keys": ["Device/Param1", "Device/Param2"], "behavior": "retrieve"}}
"""

PARAM_LIST_BLOCK = """\
## Available Parameters
{param_list}
"""

SYNONYM_BLOCK = """\
## Available Parameters (with descriptions and synonyms)
{param_detail}
"""


def _build_param_list_text(synonym_map: Dict[str, Any]) -> str:
    lines: List[str] = []
    for key, info in sorted(synonym_map.items()):
        name = info.get("semantic_name") or ""
        unit = info.get("unit") or ""
        cat = info.get("concept_category") or ""
        parts = [key]
        if name:
            parts.append(name)
        if unit:
            parts.append(f"({unit})")
        if cat:
            parts.append(f"[{cat}]")
        lines.append(" — ".join(parts))
    return "\n".join(lines)


def _build_synonym_text(synonym_map: Dict[str, Any]) -> str:
    lines: List[str] = []
    for key, info in sorted(synonym_map.items()):
        name = info.get("semantic_name") or ""
        unit = info.get("unit") or ""
        cat = info.get("concept_category") or ""
        synonyms: List[str] = []
        for field_name in ("direct", "semantic_en", "medical_term", "abbreviation"):
            synonyms.extend(info.get(field_name, []))
        # deduplicate while preserving order
        seen: set = set()
        unique_syn: List[str] = []
        for s in synonyms:
            if s and s not in seen and s != key:
                seen.add(s)
                unique_syn.append(s)
        header = key
        if name:
            header += f": {name}"
        if unit:
            header += f" ({unit})"
        if cat:
            header += f" [{cat}]"
        if unique_syn:
            header += f"\n  Synonyms: {', '.join(unique_syn)}"
        lines.append(header)
    return "\n".join(lines)


def _call_openai(system: str, user: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.0,
        max_tokens=512,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content.strip()


def _call_anthropic(system: str, user: str) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=512,
        temperature=0.0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text.strip()


def _parse_llm_response(raw: str) -> Tuple[List[str], str]:
    """Parse JSON from LLM response, return (param_keys, behavior)."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            obj = json.loads(match.group())
        else:
            return [], "not_found"
    keys = obj.get("param_keys", [])
    behavior = obj.get("behavior", "retrieve")
    if behavior not in ("retrieve", "not_found", "clarify"):
        behavior = "retrieve"
    return keys, behavior


def _run_baseline_llm(
    scenario_name: str,
    cases: List[Dict],
    synonym_map: Dict[str, Any],
    llm_caller,
    use_synonyms: bool,
    progress_cb=None,
) -> List[CaseResult]:
    if use_synonyms:
        context_block = SYNONYM_BLOCK.format(param_detail=_build_synonym_text(synonym_map))
    else:
        context_block = PARAM_LIST_BLOCK.format(param_list=_build_param_list_text(synonym_map))

    system_prompt = BASELINE_SYSTEM_PROMPT + "\n" + context_block
    results: List[CaseResult] = []

    for idx, case in enumerate(cases):
        _log_progress(scenario_name, idx, len(cases), case["id"])
        t0 = time.time()
        raw_response = None
        try:
            raw_response = llm_caller(system_prompt, case["query"])
            elapsed = (time.time() - t0) * 1000
            retrieved, detected = _parse_llm_response(raw_response)
            error = None
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            retrieved, detected, error = [], "not_found", str(e)

        cr = _build_case_result(scenario_name, case, retrieved, detected, elapsed, error, raw_response)
        results.append(cr)
        if progress_cb:
            progress_cb(idx + 1, len(cases))
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 5. Aggregation
# ═══════════════════════════════════════════════════════════════════════════

QUERY_TYPE_DESC = {
    "Single-Direct":       "param_key가 쿼리에 직접 노출된 단일 파라미터 검색",
    "Single-Semantic":     "param_key 없이 의미/임상 표현으로 단일 파라미터 검색",
    "Single-Abbreviation": "약어나 축약형으로 단일 파라미터 검색",
    "Multi-Independent":   "서로 독립적인 2개 이상 파라미터 동시 검색",
    "Multi-Conditional":   "한 파라미터의 조건에 따라 다른 파라미터를 분석",
    "Adversarial":         "모호하거나 존재하지 않는 파라미터 요청 (clarify/not_found 기대)",
}

BREAKDOWN_DIMS = ["query_type", "query_style", "difficulty", "category"]


def aggregate(results: List[CaseResult], scenario: str) -> List[AggregateMetrics]:
    aggs: List[AggregateMetrics] = []
    aggs.append(_agg_slice(results, scenario, "overall", "all"))

    for dim in BREAKDOWN_DIMS:
        values = sorted(set(getattr(r, dim) for r in results))
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
        mean_recall=sum(r.recall for r in results) / n,
        mean_precision=sum(r.precision for r in results) / n,
        mean_f1=sum(r.f1 for r in results) / n,
        behavior_accuracy=sum(1 for r in results if r.behavior_match) / n,
        perfect_recall_rate=sum(1 for r in results if r.recall == 1.0) / n,
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
    detail_rows: List[Dict] = []
    for scenario, results in all_results.items():
        for r in results:
            detail_rows.append({
                "scenario": r.scenario,
                "case_id": r.case_id,
                "query_type": r.query_type,
                "query_type_desc": QUERY_TYPE_DESC.get(r.query_type, ""),
                "query_style": r.query_style,
                "difficulty": r.difficulty,
                "category": r.category,
                "query": r.query,
                "expected_params": ", ".join(r.expected_params),
                "retrieved_params": ", ".join(r.retrieved_params),
                "expected_behavior": r.expected_behavior,
                "detected_behavior": r.detected_behavior,
                "recall": round(r.recall, 4),
                "precision": round(r.precision, 4),
                "f1": round(r.f1, 4),
                "behavior_match": r.behavior_match,
                "time_ms": round(r.execution_time_ms, 1),
                "error": r.error_message or "",
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
                "recall": round(a.mean_recall, 4),
                "precision": round(a.mean_precision, 4),
                "f1": round(a.mean_f1, 4),
                "behavior_acc": round(a.behavior_accuracy, 4),
                "perfect_recall%": round(a.perfect_recall_rate * 100, 2),
                "avg_ms": round(a.mean_time_ms, 1),
                "median_ms": round(a.median_time_ms, 1),
                "min_ms": round(a.min_time_ms, 1),
                "max_ms": round(a.max_time_ms, 1),
                "p95_ms": round(a.p95_time_ms, 1),
            })
    df_agg = pd.DataFrame(agg_rows)

    # Pivot: scenarios as columns, overall metrics
    overall = df_agg[df_agg["dimension"] == "overall"].set_index("scenario")
    pivot_cols = ["count", "recall", "precision", "f1", "behavior_acc", "perfect_recall%",
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
    header = (f"{'Scenario':<30} {'N':>4} {'Recall':>8} {'Prec':>8} {'F1':>8} "
              f"{'BehAcc':>8} {'PerfR%':>8} {'Avg(ms)':>10} {'Med(ms)':>10} {'P95(ms)':>10}")
    print(f"\n{'=' * 112}")
    print("  Level 1 Evaluation — Scenario Comparison")
    print(f"{'=' * 112}")
    print(header)
    print("-" * 112)
    for scenario, aggs in all_aggs.items():
        ov = next((a for a in aggs if a.slice_name == "overall"), None)
        if not ov:
            continue
        print(
            f"{ov.scenario:<30} {ov.count:>4} "
            f"{ov.mean_recall:>8.4f} {ov.mean_precision:>8.4f} {ov.mean_f1:>8.4f} "
            f"{ov.behavior_accuracy:>8.4f} {ov.perfect_recall_rate * 100:>7.2f}%"
            f" {ov.mean_time_ms:>10.1f} {ov.median_time_ms:>10.1f} {ov.p95_time_ms:>10.1f}"
        )
    print(f"{'=' * 112}\n")


def print_breakdown(all_aggs: Dict[str, List[AggregateMetrics]], dim: str):
    print(f"\n--- Breakdown by {dim} ---")
    header = f"{'Scenario':<30} {dim:<25} {'N':>4} {'Recall':>8} {'F1':>8} {'Avg(ms)':>10}"
    print(header)
    print("-" * 90)
    for scenario, aggs in all_aggs.items():
        for a in aggs:
            if a.slice_name != dim:
                continue
            print(
                f"{a.scenario:<30} {a.slice_value:<25} {a.count:>4} "
                f"{a.mean_recall:>8.4f} {a.mean_f1:>8.4f} {a.mean_time_ms:>10.1f}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _build_case_result(
    scenario: str,
    case: Dict,
    retrieved: List[str],
    detected: str,
    elapsed_ms: float,
    error: Optional[str],
    raw_response: Optional[str] = None,
) -> CaseResult:
    gt = case["ground_truth"]
    required = gt["required_parameters"]
    alts = gt.get("acceptable_alternatives", {})
    expected_beh = gt["expected_behavior"]
    acc_behaviors = gt.get("acceptable_behaviors", [])
    confusing_params = gt.get("confusing_valid_params", [])

    recall, precision, f1, beh_match = compute_metrics(
        required, alts, retrieved, expected_beh, detected,
        acceptable_behaviors=acc_behaviors or None,
        confusing_valid_params=confusing_params or None,
    )
    return CaseResult(
        case_id=case["id"],
        scenario=scenario,
        query=case["query"],
        query_type=case.get("query_type", ""),
        query_style=case.get("query_style", ""),
        difficulty=case.get("difficulty", ""),
        category=case.get("category", ""),
        num_required_params=case.get("num_required_params", 0),
        expected_params=required,
        acceptable_alternatives=alts,
        expected_behavior=expected_beh,
        retrieved_params=retrieved,
        detected_behavior=detected,
        recall=recall,
        precision=precision,
        f1=f1,
        behavior_match=beh_match,
        execution_time_ms=elapsed_ms,
        error_message=error,
        raw_response=raw_response,
    )


def _log_progress(scenario: str, idx: int, total: int, case_id: str):
    logger.info(f"[{scenario}] ({idx + 1}/{total}) {case_id}")


# ═══════════════════════════════════════════════════════════════════════════
# 8. Main
# ═══════════════════════════════════════════════════════════════════════════

SCENARIO_CHOICES = [
    "gpt4o-paramlist",
    "claude-paramlist",
    "gpt4o-synonym",
    "claude-synonym",
    "vitalagent-extraction",
    "claude-code-cli",
    # "vitalagent-full",
]


def main():
    parser = argparse.ArgumentParser(
        description="Level 1 Parameter Retrieval Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        default=str(Path(__file__).parent / "output" / "level1_dataset.json"),
        help="Path to level1_dataset.json",
    )
    parser.add_argument(
        "--synonym-map",
        default=str(Path(__file__).parent / "output" / "synonym_map.json"),
        help="Path to synonym_map.json",
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

    cases = load_level1_dataset(str(dataset_path))
    if args.limit:
        cases = cases[: args.limit]
    logger.info(f"Loaded {len(cases)} cases from {dataset_path.name}")

    # ---- Load synonym map (for baseline scenarios) ----
    synonym_map: Dict[str, Any] = {}
    synonym_path = Path(args.synonym_map)
    if synonym_path.exists():
        with open(synonym_path, "r", encoding="utf-8") as f:
            synonym_map = json.load(f)
        logger.info(f"Loaded synonym map: {len(synonym_map)} parameters")
    else:
        logger.warning(f"Synonym map not found: {synonym_path} — baseline scenarios will have no context")

    # ---- Output path ----
    if args.output:
        output_path = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(Path(__file__).parent / "output" / f"level1_eval_{ts}.xlsx")

    # ---- Run scenarios ----
    all_results: Dict[str, List[CaseResult]] = {}
    all_aggs: Dict[str, List[AggregateMetrics]] = {}

    scenario_runners = {
        # "vitalagent-full": lambda: run_vitalagent_full(cases),
        "vitalagent-extraction": lambda: run_vitalagent_extraction(cases),
        "claude-code-cli": lambda: run_claude_code_cli(cases),
        "gpt4o-paramlist": lambda: _run_baseline_llm(
            "GPT4o-ParamList", cases, synonym_map, _call_openai, use_synonyms=False
        ),
        "claude-paramlist": lambda: _run_baseline_llm(
            "Claude-ParamList", cases, synonym_map, _call_anthropic, use_synonyms=False
        ),
        "gpt4o-synonym": lambda: _run_baseline_llm(
            "GPT4o-Synonym", cases, synonym_map, _call_openai, use_synonyms=True
        ),
        "claude-synonym": lambda: _run_baseline_llm(
            "Claude-Synonym", cases, synonym_map, _call_anthropic, use_synonyms=True
        ),
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
