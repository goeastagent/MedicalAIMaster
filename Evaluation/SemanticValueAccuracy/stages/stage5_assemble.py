"""
Evaluation/SemanticValueAccuracy/stages/stage5_assemble.py

Stage 5: Final Dataset Assembly + Validation Report

1. Load filtered candidates (Stage 4 output)
2. Select top-N per category (ranked by audit score)
3. Re-assign sequential IDs
4. Run validation checks against minimum acceptance criteria
5. Write final dataset + validation report

Output:
    sva_dataset.jsonl           — final dataset
    sva_validation_report.json  — quality summary

Usage (standalone):
    python -m Evaluation.SemanticValueAccuracy.stages.stage5_assemble
    python -m Evaluation.SemanticValueAccuracy.stages.stage5_assemble --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.SemanticValueAccuracy.config import (
    CategoryTargets,
    Paths,
    ValidationCriteria,
)
from Evaluation.SemanticValueAccuracy.models import ValidationReport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage5] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

TRACK_PATTERN = re.compile(r"\b[A-Z][a-z]+\d*/[A-Z][A-Z0-9_]+\b")


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
# Selection logic
# ---------------------------------------------------------------------------

def select_top_per_category(
    filtered: List[Dict],
) -> List[Dict]:
    """Select top-N cases per category, ranked by audit_score_avg."""
    final: List[Dict] = []

    for category, target_n in CategoryTargets.TARGETS.items():
        pool = [c for c in filtered if c.get("query_category") == category]

        pool.sort(key=lambda x: x.get("audit_score_avg", 0), reverse=True)
        selected = pool[:target_n]

        if len(selected) < target_n:
            log.warning(
                "Category %s: only %d/%d available (min=%d)",
                category, len(selected), target_n,
                CategoryTargets.MINIMUMS.get(category, 0),
            )

        prefix = CategoryTargets.ID_PREFIXES[category]
        for i, case in enumerate(selected):
            case["id"] = f"{prefix}_{i + 1:03d}"

        final.extend(selected)

    return final


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def _count_candidates(stage: str) -> int:
    """Count lines in a stage output file."""
    path_map = {
        "candidates": Paths.CANDIDATES,
        "verified": Paths.VERIFIED,
        "filtered": Paths.FILTERED,
    }
    p = path_map.get(stage)
    if p and p.exists():
        with open(p, "r") as f:
            return sum(1 for _ in f)
    return 0


def _collect_filter_stats() -> Dict[str, int]:
    """Try to read Stage 4's progress for filter_stats."""
    progress_path = Paths.OUTPUT_DIR / "stage4_progress.json"
    if progress_path.exists():
        data = json.loads(progress_path.read_text())
        return data.get("filter_stats", {})
    return {}


def validate_dataset(final: List[Dict]) -> ValidationReport:
    """Run all validation checks and build the report."""
    timestamp = datetime.now(timezone.utc).isoformat()

    total_generated = _count_candidates("candidates")
    total_filtered = _count_candidates("filtered")

    cat_dist = dict(Counter(c["query_category"] for c in final))
    style_dist = dict(Counter(c.get("query_style", "unknown") for c in final))

    # Unique equivalence params
    all_params = set()
    for c in final:
        rt = c.get("resolution_target", {})
        for p in rt.get("equivalence_group", []):
            all_params.add(p)
    unique_params = len(all_params)

    # Execution verified %
    verified_count = sum(1 for c in final if c.get("is_verified_by_execution"))
    verified_pct = (verified_count / len(final) * 100) if final else 0

    # Null value ratio (exclude adversarial — they are expected null)
    retrieve_cases = [
        c for c in final
        if c.get("resolution_target", {}).get("expected_behavior", "retrieve") == "retrieve"
    ]
    null_count = 0
    for c in retrieve_cases:
        ev = c.get("equivalence_values", {})
        if not ev or all(v is None for v in ev.values()):
            null_count += 1
    null_ratio = null_count / len(retrieve_cases) if retrieve_cases else 0

    # --- Validation checks ---
    issues: List[str] = []
    checks: Dict[str, str] = {}

    # Check 1: min per category
    min_ok = True
    for cat, minimum in CategoryTargets.MINIMUMS.items():
        actual = cat_dist.get(cat, 0)
        if actual < minimum:
            min_ok = False
            issues.append(f"Category '{cat}': {actual} < minimum {minimum}")
    checks["min_per_category"] = "PASS" if min_ok else "FAIL"

    # Check 2: all execution verified
    all_verified = verified_count == len(final)
    checks["all_execution_verified"] = "PASS" if all_verified else "FAIL"
    if not all_verified:
        issues.append(f"Not all cases verified: {verified_count}/{len(final)}")

    # Check 3: no track names in queries
    track_leaks = 0
    for c in final:
        if TRACK_PATTERN.search(c.get("query", "")):
            track_leaks += 1
    checks["no_track_in_queries"] = "PASS" if track_leaks == 0 else "FAIL"
    if track_leaks > 0:
        issues.append(f"{track_leaks} queries contain track names")

    # Check 4: null ratio
    null_ok = null_ratio <= ValidationCriteria.NULL_RATIO_MAX
    checks["null_ratio_under_20pct"] = "PASS" if null_ok else "FAIL"
    if not null_ok:
        issues.append(f"Null ratio {null_ratio:.1%} exceeds {ValidationCriteria.NULL_RATIO_MAX:.0%}")

    # Check 5: case diversity — dynamically extract case IDs from queries
    case_refs: Dict[str, int] = Counter()
    for c in final:
        q = c.get("query", "")
        for cid in re.findall(r'\b(\d{4})\b', q):
            case_refs[cid] += 1
    unique_cases = len(case_refs)
    diversity_ok = unique_cases >= 2
    if not diversity_ok:
        issues.append(f"Only {unique_cases} unique case(s) referenced across all queries")
    checks["case_diversity"] = "PASS" if diversity_ok else "FAIL"

    report = ValidationReport(
        generation_timestamp=timestamp,
        total_generated=total_generated,
        total_after_filter=total_filtered,
        total_final=len(final),
        category_distribution=cat_dist,
        style_distribution=style_dist,
        unique_equivalence_params=unique_params,
        execution_verified_pct=round(verified_pct, 1),
        null_value_ratio=round(null_ratio, 3),
        filter_stats=_collect_filter_stats(),
        validation_checks=checks,
        issues=issues,
    )
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> int:
    """Execute Stage 5."""
    Paths.ensure_output_dir()

    # Load filtered candidates
    filtered = _load_jsonl(Paths.FILTERED)
    if not filtered:
        raise FileNotFoundError(
            f"No filtered cases at {Paths.FILTERED}. Run Stage 4 first."
        )
    log.info("Loaded %d filtered cases from Stage 4", len(filtered))

    # Select top-N per category
    final = select_top_per_category(filtered)
    log.info("Selected %d cases for final dataset", len(final))

    # Validate
    report = validate_dataset(final)

    if dry_run:
        log.info("[DRY-RUN] Would write dataset and report (skipped)")
        report.print_summary()
        return len(final)

    # Save final dataset
    _save_jsonl(Paths.FINAL_DATASET, final)
    log.info("Final dataset: %s", Paths.FINAL_DATASET)

    # Save validation report
    report_path = Paths.VALIDATION_REPORT
    report_dict = report.model_dump()
    report_dict["passes_minimum_criteria"] = report.passes_minimum_criteria
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, ensure_ascii=False, indent=2)
    log.info("Validation report: %s", report_path)

    # Print summary
    report.print_summary()

    return len(final)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 5 — Assemble final SVA dataset + validation report."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip writing output files.",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run)
