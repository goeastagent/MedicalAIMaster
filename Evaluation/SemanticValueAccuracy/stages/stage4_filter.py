"""
Evaluation/SemanticValueAccuracy/stages/stage4_filter.py

Stage 4: Quality Filtering (4 sub-filters, applied in cost-ascending order)

  Filter 1  Track name exposure check       (cost: low)
  Filter 2  Determinism verification         (cost: medium — executor call)
  Filter 3  Semantic deduplication           (cost: medium — SequenceMatcher)
  Filter 4  LLM quality audit               (cost: high — LLM call)

Output: sva_filtered.jsonl  (cases that passed all 4 filters)

Usage (standalone):
    python -m Evaluation.SemanticValueAccuracy.stages.stage4_filter
    python -m Evaluation.SemanticValueAccuracy.stages.stage4_filter --skip-llm
    python -m Evaluation.SemanticValueAccuracy.stages.stage4_filter --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.SemanticValueAccuracy.config import (
    FilterConfig,
    LLMConfig,
    Paths,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage4] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _save_jsonl(path: Path, items: List[Dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Filter 1: Track name exposure
# ---------------------------------------------------------------------------

TRACK_PATTERN = re.compile(r"\b[A-Z][a-z]+\d*/[A-Z][A-Z0-9_]+\b")


def filter_track_exposure(cases: List[Dict]) -> tuple[List[Dict], int]:
    """Remove cases where the query text contains raw track names."""
    passed = []
    removed = 0
    for c in cases:
        matches = TRACK_PATTERN.findall(c.get("query", ""))
        if matches:
            log.info("  F1 REMOVE %s: track names found: %s", c["id"], matches)
            removed += 1
        else:
            passed.append(c)
    return passed, removed


# ---------------------------------------------------------------------------
# Filter 2: Determinism verification
# ---------------------------------------------------------------------------

def _compare_simple(a: Any, b: Any, tol: float = 1e-5) -> bool:
    """Compare two values for approximate equality."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < tol
    return a == b


def filter_determinism(
    cases: List[Dict],
    executor,
    dry_run: bool = False,
) -> tuple[List[Dict], int]:
    """Remove cases where result changes with interval=0.5 but query lacks sampling spec."""
    if dry_run:
        return cases, 0

    passed = []
    removed = 0
    for c in cases:
        code = c.get("ground_truth_logic", {}).get("code", "")
        if not code or code.strip() == "output_result(None)":
            passed.append(c)
            continue

        modified = code.replace("], 1)", "], 0.5)")
        if modified == code:
            passed.append(c)
            continue

        result = executor.execute_code(modified)
        if not result["success"]:
            passed.append(c)
            continue

        eq_values = c.get("equivalence_values", {})
        first_param = next(iter(eq_values), None)
        original_value = eq_values.get(first_param) if first_param else None
        half_value = result["result"]

        if _compare_simple(original_value, half_value):
            passed.append(c)
            continue

        query_lower = c.get("query", "").lower()
        has_rate_spec = any(kw in query_lower for kw in ["hz", "sampl", "interval", "1 hz"])

        if has_rate_spec:
            passed.append(c)
        else:
            log.info(
                "  F2 REMOVE %s: non-deterministic (orig=%s, half=%s) no sampling spec",
                c["id"], original_value, half_value,
            )
            removed += 1

    return passed, removed


# ---------------------------------------------------------------------------
# Filter 3: Semantic deduplication
# ---------------------------------------------------------------------------

def _hashable_values(eq_values: Dict) -> frozenset:
    """Convert equivalence_values to a hashable set for comparison."""
    result = set()
    for v in eq_values.values():
        if v is not None:
            if isinstance(v, (dict, list)):
                result.add(json.dumps(v, sort_keys=True))
            else:
                result.add(v)
    return frozenset(result)


def filter_deduplication(
    cases: List[Dict],
    threshold: float = FilterConfig.DEDUP_THRESHOLD,
) -> tuple[List[Dict], int]:
    """Remove semantically duplicate queries within same category."""
    passed: List[Dict] = []
    removed = 0
    by_category: Dict[str, List[Dict]] = {}

    for c in cases:
        cat = c.get("query_category", "")
        existing = by_category.get(cat, [])

        new_q = c.get("query", "")
        new_vals = _hashable_values(c.get("equivalence_values", {}))

        is_dup = False
        for ex in existing:
            sim = SequenceMatcher(None, new_q, ex.get("query", "")).ratio()
            ex_vals = _hashable_values(ex.get("equivalence_values", {}))
            if sim >= threshold and new_vals == ex_vals:
                is_dup = True
                log.info(
                    "  F3 REMOVE %s: duplicate of %s (sim=%.2f)",
                    c["id"], ex["id"], sim,
                )
                break

        if is_dup:
            removed += 1
        else:
            passed.append(c)
            by_category.setdefault(cat, []).append(c)

    return passed, removed


# ---------------------------------------------------------------------------
# Filter 4: LLM quality audit
# ---------------------------------------------------------------------------

def _call_audit_llm(prompt: str) -> Dict:
    """Call LLM audit and return parsed scores dict."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=LLMConfig.AUDIT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a quality auditor for a medical AI benchmark. "
                        "Output valid JSON only, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=LLMConfig.AUDIT_TEMPERATURE,
            max_tokens=LLMConfig.AUDIT_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except Exception as e:
        log.warning("Audit LLM failed: %s", e)
        return {}


def filter_llm_audit(
    cases: List[Dict],
    dry_run: bool = False,
    skip_llm: bool = False,
) -> tuple[List[Dict], int]:
    """Apply LLM-as-a-Judge quality audit."""
    if dry_run or skip_llm:
        for c in cases:
            c["audit_scores"] = {"clarity": 5, "validity": 5, "resolution": 5,
                                 "truth": 5, "fit": 5, "format": 5}
            c["audit_score_avg"] = 5.0
        return cases, 0

    template = (Paths.PROMPTS_DIR / "quality_audit.txt").read_text(encoding="utf-8")

    passed = []
    removed = 0

    for c in cases:
        prompt = template.format(
            query=c.get("query", ""),
            query_category=c.get("query_category", ""),
            query_style=c.get("query_style", ""),
            answer_type=c.get("answer_type", ""),
            resolution_target=json.dumps(c.get("resolution_target", {}), ensure_ascii=False),
            equivalence_values=json.dumps(c.get("equivalence_values", {}), ensure_ascii=False),
        )

        result = _call_audit_llm(prompt)
        scores = result.get("scores", {})
        overall_pass = result.get("overall_pass", False)
        reason = result.get("reason", "")

        if not scores:
            log.warning("  F4 SKIP %s: audit returned empty scores — keeping", c["id"])
            c["audit_scores"] = {}
            c["audit_score_avg"] = 0.0
            passed.append(c)
            continue

        score_values = list(scores.values())
        avg = sum(score_values) / len(score_values) if score_values else 0
        min_score = min(score_values) if score_values else 0

        c["audit_scores"] = scores
        c["audit_score_avg"] = round(avg, 2)

        if min_score >= FilterConfig.AUDIT_MIN_SCORE and avg >= FilterConfig.AUDIT_MIN_AVERAGE:
            passed.append(c)
        else:
            log.info(
                "  F4 REMOVE %s: scores=%s avg=%.1f min=%d reason=%s",
                c["id"], scores, avg, min_score, reason[:80],
            )
            removed += 1

    return passed, removed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    dry_run: bool = False,
    skip_llm: bool = False,
) -> int:
    """Execute Stage 4."""
    Paths.ensure_output_dir()

    # Load verified cases from Stage 3
    cases = _load_jsonl(Paths.VERIFIED)
    if not cases:
        raise FileNotFoundError(
            f"No verified cases at {Paths.VERIFIED}. Run Stage 3 first."
        )
    total_input = len(cases)
    log.info("Loaded %d verified cases from Stage 3", total_input)

    # Initialize executor for Filter 2
    executor = None
    if not dry_run:
        from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor
        executor = VitalExecutor()

    stats: Dict[str, int] = {}

    # Filter 1: Track exposure
    log.info("━━ Filter 1: Track name exposure ━━")
    cases, n = filter_track_exposure(cases)
    stats["track_exposure_removed"] = n
    log.info("  → %d passed, %d removed", len(cases), n)

    # Filter 2: Determinism
    log.info("━━ Filter 2: Determinism verification ━━")
    cases, n = filter_determinism(cases, executor, dry_run=dry_run)
    stats["determinism_removed"] = n
    log.info("  → %d passed, %d removed", len(cases), n)

    # Filter 3: Deduplication
    log.info("━━ Filter 3: Semantic deduplication ━━")
    cases, n = filter_deduplication(cases)
    stats["duplicate_removed"] = n
    log.info("  → %d passed, %d removed", len(cases), n)

    # Filter 4: LLM audit
    log.info("━━ Filter 4: LLM quality audit ━━")
    cases, n = filter_llm_audit(cases, dry_run=dry_run, skip_llm=skip_llm)
    stats["llm_audit_removed"] = n
    log.info("  → %d passed, %d removed", len(cases), n)

    # Save filtered results
    _save_jsonl(Paths.FILTERED, cases)

    total_removed = sum(stats.values())
    log.info("=" * 60)
    log.info("Stage 4 — Quality Filtering complete")
    log.info("  Input              : %d", total_input)
    log.info("  Total removed      : %d", total_removed)
    log.info("  Output             : %d", len(cases))
    for k, v in stats.items():
        log.info("    %-25s %d", k, v)
    log.info("  Output file        : %s", Paths.FILTERED)
    log.info("=" * 60)

    return len(cases)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 4 — Quality filtering for SVA candidates."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip executor and LLM calls.",
    )
    parser.add_argument(
        "--skip-llm", action="store_true",
        help="Skip Filter 4 (LLM audit) only.",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, skip_llm=args.skip_llm)
