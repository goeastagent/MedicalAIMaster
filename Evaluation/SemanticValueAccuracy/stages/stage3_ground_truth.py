"""
Evaluation/SemanticValueAccuracy/stages/stage3_ground_truth.py

Stage 3: Ground Truth Code Generation + VitalExecutor Verification

3-Pass structure per candidate:
  Pass 1  LLM generates Python GT code for the first param in equivalence_group
  Pass 2  VitalExecutor runs the code; on failure retry with error feedback (≤3 tries)
  Pass 3  For remaining equivalence_group params, substitute and re-execute

Output: sva_verified.jsonl  (candidates with ground_truth_logic + equivalence_values)

Usage (standalone):
    python -m Evaluation.SemanticValueAccuracy.stages.stage3_ground_truth
    python -m Evaluation.SemanticValueAccuracy.stages.stage3_ground_truth --dry-run
    python -m Evaluation.SemanticValueAccuracy.stages.stage3_ground_truth --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.SemanticValueAccuracy.config import (
    FilterConfig,
    LLMConfig,
    Paths,
    TARGET_CASE_IDS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage3] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VitalExecutor (reuse from ValueAccuracy)
# ---------------------------------------------------------------------------

def _get_executor():
    """Lazy-import VitalExecutor to avoid heavy deps at parse time."""
    from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor
    return VitalExecutor()


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

def _call_gt_llm(prompt: str) -> str:
    """Call LLM and return raw code string."""
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=LLMConfig.GT_CODE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a Python code generator for biosignal data analysis. "
                    "Output ONLY executable Python code. No markdown fences, no explanations."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=LLMConfig.GT_CODE_TEMPERATURE,
        max_tokens=LLMConfig.GT_CODE_MAX_TOKENS,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if present
    raw = re.sub(r"^```(?:python)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```\s*$", "", raw).strip()
    return raw


def _generate_gt_code(
    query: str,
    target_param: str,
    answer_type: str,
    case_ids: List[str],
) -> str:
    """Generate GT code via LLM (Pass 1)."""
    template = (Paths.PROMPTS_DIR / "gt_code_gen.txt").read_text(encoding="utf-8")
    prompt = template.format(
        query=query,
        target_param=target_param,
        case_ids=", ".join(case_ids),
        answer_type=answer_type,
    )
    return _call_gt_llm(prompt)


def _fix_gt_code(
    query: str,
    target_param: str,
    answer_type: str,
    previous_code: str,
    error_message: str,
) -> str:
    """Generate fixed GT code via LLM (retry after failure)."""
    template = (Paths.PROMPTS_DIR / "gt_code_fix.txt").read_text(encoding="utf-8")
    prompt = template.format(
        query=query,
        target_param=target_param,
        answer_type=answer_type,
        previous_code=previous_code,
        error_message=error_message,
    )
    return _call_gt_llm(prompt)


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

ANSWER_TYPE_MAP = {
    "number": (int, float),
    "dict": dict,
    "list": list,
    "null": type(None),
}


def _coerce_value(value: Any, answer_type: str) -> Any:
    """Attempt to coerce value to expected answer_type."""
    if answer_type == "number":
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    if answer_type == "dict" and isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    if answer_type == "list" and isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return value


# ---------------------------------------------------------------------------
# Case ID extraction from query
# ---------------------------------------------------------------------------

def _extract_case_ids(query: str) -> List[str]:
    """Extract case IDs referenced in the query."""
    found = []
    for cid in TARGET_CASE_IDS:
        if cid in query:
            found.append(cid)
    return found if found else TARGET_CASE_IDS


# ---------------------------------------------------------------------------
# Core 3-Pass logic
# ---------------------------------------------------------------------------

def process_candidate(
    candidate: Dict,
    executor,
    dry_run: bool = False,
) -> Optional[Dict]:
    """Process a single candidate through the 3-pass pipeline.

    Returns the enriched candidate dict on success, or None on failure.
    """
    cid = candidate["id"]
    query = candidate["query"]
    answer_type = candidate.get("answer_type", "number")
    rt = candidate.get("resolution_target", {})
    eq_group = rt.get("equivalence_group", [])
    case_ids = _extract_case_ids(query)

    # --- Pass 1 + 2: Generate and verify base GT code ---
    if not eq_group:
        # Adversarial with empty equivalence_group → expected null
        if dry_run:
            candidate["ground_truth_logic"] = {"language": "python", "code": "output_result(None)"}
            candidate["equivalence_values"] = {}
            candidate["is_verified_by_execution"] = False
            return candidate

        code = "output_result(None)"
        result = executor.execute_code(code)
        candidate["ground_truth_logic"] = {"language": "python", "code": code}
        candidate["equivalence_values"] = {}
        candidate["is_verified_by_execution"] = result.get("success", False)
        candidate["verification_timestamp"] = datetime.now(timezone.utc).isoformat()
        return candidate

    base_param = eq_group[0]

    if dry_run:
        candidate["ground_truth_logic"] = {
            "language": "python",
            "code": f"# [DRY-RUN] GT code for {base_param}",
        }
        candidate["equivalence_values"] = {p: None for p in eq_group}
        candidate["is_verified_by_execution"] = False
        return candidate

    # Pass 1: generate base code
    code = _generate_gt_code(query, base_param, answer_type, case_ids)
    base_value = None
    verified = False

    # Pass 2: execute with retries
    for attempt in range(1, LLMConfig.GT_MAX_RETRIES + 1):
        result = executor.execute_code(code)

        if result["success"]:
            base_value = result["result"]

            # Type check
            expected_types = ANSWER_TYPE_MAP.get(answer_type, object)
            if base_value is not None and not isinstance(base_value, expected_types):
                log.warning(
                    "  %s: type mismatch (expected %s, got %s), coercing",
                    cid, answer_type, type(base_value).__name__,
                )
                base_value = _coerce_value(base_value, answer_type)

            verified = True
            log.info(
                "  %s: Pass 2 OK (attempt %d) → base_value=%s",
                cid, attempt, _truncate(base_value),
            )
            break

        # Execution failed → retry with error feedback
        error = result.get("error", "unknown error")
        log.warning(
            "  %s: Pass 2 FAIL (attempt %d/%d): %s",
            cid, attempt, LLMConfig.GT_MAX_RETRIES, error[:200],
        )

        if attempt < LLMConfig.GT_MAX_RETRIES:
            code = _fix_gt_code(query, base_param, answer_type, code, error)
            time.sleep(0.5)

    if not verified:
        log.error("  %s: All %d attempts failed — dropping", cid, LLMConfig.GT_MAX_RETRIES)
        return None

    # --- Pass 3: compute equivalence_values for all params ---
    eq_values: Dict[str, Any] = {base_param: base_value}

    for param in eq_group[1:]:
        param_code = code.replace(base_param, param)
        param_result = executor.execute_code(param_code)

        if param_result["success"]:
            val = param_result["result"]
            expected_types = ANSWER_TYPE_MAP.get(answer_type, object)
            if val is not None and not isinstance(val, expected_types):
                val = _coerce_value(val, answer_type)
            eq_values[param] = val
            log.info("  %s: Pass 3 %s → %s", cid, param, _truncate(val))
        else:
            log.warning(
                "  %s: Pass 3 %s FAIL: %s",
                cid, param, param_result.get("error", "")[:150],
            )
            eq_values[param] = None

    candidate["ground_truth_logic"] = {"language": "python", "code": code}
    candidate["equivalence_values"] = eq_values
    candidate["is_verified_by_execution"] = True
    candidate["verification_timestamp"] = datetime.now(timezone.utc).isoformat()

    return candidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(val: Any, maxlen: int = 80) -> str:
    s = repr(val)
    return s[:maxlen] + "..." if len(s) > maxlen else s


def _append_jsonl(path: Path, obj: Dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

_PROGRESS_FILE = Paths.OUTPUT_DIR / "stage3_progress.json"


def _load_progress() -> Dict:
    if _PROGRESS_FILE.exists():
        return json.loads(_PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"completed_ids": [], "verified": 0, "failed": 0}


def _save_progress(progress: Dict) -> None:
    _PROGRESS_FILE.write_text(
        json.dumps(progress, indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> int:
    """Execute Stage 3."""
    Paths.ensure_output_dir()

    # Load candidates from Stage 2
    candidates = _load_jsonl(Paths.CANDIDATES)
    if not candidates:
        raise FileNotFoundError(
            f"No candidates found at {Paths.CANDIDATES}. Run Stage 2 first."
        )
    log.info("Loaded %d candidates from Stage 2", len(candidates))

    # Resume support
    progress = _load_progress()
    completed_ids = set(progress["completed_ids"])

    output_file = Paths.VERIFIED

    # Reset output if progress is empty but file has data
    if not completed_ids and output_file.exists() and output_file.stat().st_size > 0:
        backup = output_file.with_suffix(".jsonl.bak")
        log.warning("Resetting: %s → %s", output_file.name, backup.name)
        output_file.rename(backup)

    # Filter to pending
    pending = [c for c in candidates if c["id"] not in completed_ids]
    if limit:
        pending = pending[:limit]

    if not pending:
        log.info("All candidates already processed. Nothing to do.")
        return 0

    log.info(
        "Processing %d candidates (%d already done)",
        len(pending), len(completed_ids),
    )

    # Initialize executor
    executor = None if dry_run else _get_executor()

    verified_count = 0
    failed_count = 0

    for idx, candidate in enumerate(pending, start=1):
        cid = candidate["id"]
        cat = candidate.get("query_category", "?")
        log.info(
            "[%d/%d] %s (%s) ...",
            idx, len(pending), cid, cat,
        )

        result = process_candidate(candidate, executor, dry_run=dry_run)

        if result is not None:
            _append_jsonl(output_file, result)
            verified_count += 1
        else:
            failed_count += 1

        progress["completed_ids"].append(cid)
        progress["verified"] = verified_count + len(completed_ids)
        progress["failed"] = failed_count
        _save_progress(progress)

        if not dry_run:
            time.sleep(0.3)

    # Summary
    total_in_file = len(_load_jsonl(output_file))
    log.info("=" * 60)
    log.info("Stage 3 — Ground Truth Verification complete")
    log.info("  Processed this run  : %d", len(pending))
    log.info("  Verified            : %d", verified_count)
    log.info("  Failed (dropped)    : %d", failed_count)
    log.info("  Total in output     : %d", total_in_file)
    log.info("  Output file         : %s", output_file)
    log.info("=" * 60)

    return verified_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 3 — Generate and verify GT code for SVA candidates."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip LLM and executor calls.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N candidates.",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, limit=args.limit)
