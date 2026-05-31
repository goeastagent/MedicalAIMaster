"""
Evaluation/Level1/stages/stage6_validate.py

Stage 6: Final Validation & Dataset Assembly

Reads with_adversarial.jsonl (Stage 5), promotes each QueryCandidate
to a Level1Case (assigns id, category, num_required_params), runs
validation checks, and writes the final outputs:

  - level1_dataset.json     (JSON array of Level1Case.to_dict())
  - validation_report.json  (ValidationReport)

Validation checks (from ValidationCriteria in config.py):
  1. Param coverage  — unique param_keys ≥ MIN_UNIQUE_PARAM_KEYS
  2. Category dist.  — each category ≥ MIN_CASES_PER_CATEGORY
  3. Style dist.     — each style within [MIN_STYLE_PCT, MAX_STYLE_PCT]
  4. DB existence    — all required_parameters present in synonym_map
  5. Dedup           — no exact-duplicate queries

Usage:
    python -m Evaluation.Level1.stages.stage6_validate
    python -m Evaluation.Level1.stages.stage6_validate --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.Level1.config import Paths, ValidationCriteria
from Evaluation.Level1.models import (
    Category,
    ExpectedBehavior,
    GroundTruth,
    Level1Case,
    QueryCandidate,
    QueryType,
    SynonymEntry,
    ValidationReport,
)
from Evaluation.Level1.utils import infer_category, load_synonym_map
from Evaluation.Level1.stages.stage5_adversarial import (
    _verify_truly_impossible,
    _find_confusing_pks_for_query,
    build_confusing_groups,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage6] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load helper
# ---------------------------------------------------------------------------

def _load_merged(path: Path) -> List[QueryCandidate]:
    if not path.exists():
        raise FileNotFoundError(f"with_adversarial.jsonl not found at {path}")
    items = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(QueryCandidate(**json.loads(line)))
        except Exception as e:
            log.warning("Skipping invalid line %d: %s", line_no, e)
    return items


# ---------------------------------------------------------------------------
# Promote QueryCandidate → Level1Case
# ---------------------------------------------------------------------------

def promote_to_level1(
    candidates: List[QueryCandidate],
) -> List[Level1Case]:
    """Convert QueryCandidates to Level1Cases with sequential IDs."""
    cases: List[Level1Case] = []
    normal_idx = 1
    adv_idx = 1

    for cand in candidates:
        is_adversarial = cand.query_type == QueryType.ADVERSARIAL

        # Assign ID
        if is_adversarial:
            case_id = f"L1-ADV-{adv_idx:03d}"
            adv_idx += 1
        else:
            case_id = f"L1-{normal_idx:03d}"
            normal_idx += 1

        # Assign category
        if is_adversarial:
            category = Category.ADVERSARIAL
        else:
            try:
                category = infer_category(
                    cand.ground_truth.required_parameters
                    if cand.ground_truth else []
                )
            except ValueError as e:
                log.warning("Skipping non-vital candidate during promotion: %s", e)
                continue

        # Ensure ground_truth exists
        gt = cand.ground_truth or GroundTruth()

        try:
            case = Level1Case(
                id=case_id,
                category=category,
                query_type=cand.query_type,
                query_style=cand.query_style,
                num_required_params=len(gt.required_parameters),
                query=cand.query,
                ground_truth=gt,
                adversarial_subtype=getattr(cand, "adversarial_subtype", None),
            )
            cases.append(case)
        except Exception as e:
            log.warning("Failed to promote candidate → Level1Case: %s", e)

    return cases


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def _check_param_coverage(cases: List[Level1Case]) -> tuple[int, Optional[str]]:
    """Return (unique_count, issue_or_None)."""
    all_params = set()
    for c in cases:
        all_params.update(c.ground_truth.required_parameters)
    count = len(all_params)
    if count < ValidationCriteria.MIN_UNIQUE_PARAM_KEYS:
        return count, (
            f"Param coverage too low: {count} < "
            f"{ValidationCriteria.MIN_UNIQUE_PARAM_KEYS} required"
        )
    return count, None


def _check_category_distribution(
    cases: List[Level1Case],
) -> tuple[Dict[str, int], List[str]]:
    dist = Counter(c.category.value for c in cases)
    for cat in Category:
        if cat.value not in dist:
            dist[cat.value] = 0
    cat_issues: List[str] = []
    allowed = set(ValidationCriteria.ALLOWED_CATEGORIES)
    for cat_val, cnt in dist.items():
        if cat_val not in allowed:
            if cnt > 0:
                cat_issues.append(
                    f"Category '{cat_val}' is not allowed in the vital-only dataset"
                )
            continue
        if cnt < ValidationCriteria.MIN_CASES_PER_CATEGORY:
            cat_issues.append(
                f"Category '{cat_val}' has {cnt} cases, "
                f"minimum is {ValidationCriteria.MIN_CASES_PER_CATEGORY}"
            )
    return dict(dist), cat_issues


def _check_style_distribution(
    cases: List[Level1Case],
) -> tuple[Dict[str, int], Optional[str]]:
    dist = Counter(c.query_style.value for c in cases)
    total = len(cases) or 1
    issues = []
    for style_val, cnt in dist.items():
        pct = cnt / total
        if pct < ValidationCriteria.MIN_STYLE_PCT:
            issues.append(
                f"Style '{style_val}' is {pct:.1%}, "
                f"below minimum {ValidationCriteria.MIN_STYLE_PCT:.0%}"
            )
        elif pct > ValidationCriteria.MAX_STYLE_PCT:
            issues.append(
                f"Style '{style_val}' is {pct:.1%}, "
                f"above maximum {ValidationCriteria.MAX_STYLE_PCT:.0%}"
            )
    issue = "; ".join(issues) if issues else None
    return dict(dist), issue


def _check_db_existence(
    cases: List[Level1Case],
    known_params: set,
) -> tuple[bool, Optional[str]]:
    """Verify all required_parameters exist in the synonym_map."""
    if not ValidationCriteria.REQUIRE_DB_EXISTENCE:
        return True, None
    missing = set()
    for c in cases:
        for pk in c.ground_truth.required_parameters:
            if pk not in known_params:
                missing.add(pk)
    if missing:
        return False, f"DB existence failed for {len(missing)} params: {sorted(missing)[:5]}..."
    return True, None


def _check_adversarial_quality(
    cases: List[Level1Case],
    synonym_map: Dict[str, SynonymEntry],
) -> List[str]:
    """Validate adversarial-specific correctness.

    Checks:
    1. impossible  — query must not word-boundary match any DB synonym
    2. confusing   — acceptable_behaviors and confusing_valid_params must be populated
    3. ambiguous   — no param_key hint should appear in the query
    """
    issues: List[str] = []
    confusing_groups = build_confusing_groups(synonym_map)

    for c in cases:
        if c.query_type != QueryType.ADVERSARIAL:
            continue

        gt = c.ground_truth
        subtype = getattr(c, "adversarial_subtype", None)

        # 1. impossible: must be absent from DB
        if (
            subtype == "impossible"
            or gt.expected_behavior == ExpectedBehavior.NOT_FOUND
        ):
            if not _verify_truly_impossible(c.query, synonym_map):
                issues.append(
                    f"{c.id} [impossible]: query overlaps with existing DB param "
                    f"— '{c.query[:70]}'"
                )

        # 2. confusing: metadata completeness
        if subtype == "confusing" or (
            gt.expected_behavior == ExpectedBehavior.CLARIFY
            and _find_confusing_pks_for_query(c.query, confusing_groups)
        ):
            if ExpectedBehavior.RETRIEVE not in gt.acceptable_behaviors:
                issues.append(
                    f"{c.id} [confusing]: missing 'retrieve' in acceptable_behaviors "
                    f"— '{c.query[:70]}'"
                )
            if not gt.confusing_valid_params:
                issues.append(
                    f"{c.id} [confusing]: confusing_valid_params is empty "
                    f"— '{c.query[:70]}'"
                )

        # 3. ambiguous: must not contain an exact param_key
        if subtype == "ambiguous" or (
            gt.expected_behavior == ExpectedBehavior.CLARIFY
            and not _find_confusing_pks_for_query(c.query, confusing_groups)
        ):
            for pk in synonym_map:
                if pk.lower() in c.query.lower():
                    issues.append(
                        f"{c.id} [ambiguous]: contains param_key hint '{pk}' "
                        f"— '{c.query[:70]}'"
                    )
                    break

    return issues


def _check_dedup(
    cases: List[Level1Case],
) -> tuple[bool, Optional[str]]:
    """Check for exact-text duplicate queries."""
    if not ValidationCriteria.REQUIRE_NO_DUPLICATES:
        return True, None
    seen: Dict[str, str] = {}
    duplicates = []
    for c in cases:
        norm = c.query.strip().lower()
        if norm in seen:
            duplicates.append((c.id, seen[norm]))
        else:
            seen[norm] = c.id
    if duplicates:
        return False, f"Found {len(duplicates)} duplicate query pairs: {duplicates[:3]}..."
    return True, None


def _check_query_type_distribution(
    cases: List[Level1Case],
) -> Dict[str, int]:
    return dict(Counter(c.query_type.value for c in cases))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> ValidationReport:
    """Run Stage 6.

    Returns:
        ValidationReport with all checks applied.
    """
    Paths.ensure_output_dir()

    # Load merged candidates
    candidates = _load_merged(Paths.WITH_ADVERSARIAL)
    log.info("Loaded merged candidates: %d", len(candidates))

    # Load synonym_map for DB existence check
    synonym_map = load_synonym_map(Paths.SYNONYM_MAP)
    known_params = set(synonym_map.keys())
    log.info("Known param_keys (synonym_map): %d", len(known_params))

    # Promote to Level1Case
    cases = promote_to_level1(candidates)
    log.info("Promoted to Level1Case: %d", len(cases))

    # ── Run validation checks ──
    issues: List[str] = []

    param_coverage, issue = _check_param_coverage(cases)
    if issue:
        issues.append(issue)

    category_dist, cat_issues = _check_category_distribution(cases)
    issues.extend(cat_issues)

    query_type_dist = _check_query_type_distribution(cases)

    style_dist, issue = _check_style_distribution(cases)
    if issue:
        issues.append(issue)

    db_ok, issue = _check_db_existence(cases, known_params)
    if issue:
        issues.append(issue)

    adv_issues = _check_adversarial_quality(cases, synonym_map)
    if adv_issues:
        log.warning("Adversarial quality issues found: %d", len(adv_issues))
        for ai in adv_issues:
            log.warning("  ✗ %s", ai)
        issues.extend(adv_issues)

    dedup_ok, issue = _check_dedup(cases)
    if issue:
        issues.append(issue)

    # ── Build report ──
    report = ValidationReport(
        total=len(cases),
        param_coverage=param_coverage,
        category_distribution=category_dist,
        query_type_distribution=query_type_dist,
        style_distribution=style_dist,
        db_existence_check=db_ok,
        dedup_check=dedup_ok,
        adversarial_quality_check=len(adv_issues) == 0,
        issues=issues,
    )

    report.print_summary()

    # ── Write outputs ──
    if not dry_run:
        # Final dataset
        dataset = [c.to_dict() for c in cases]
        Paths.FINAL_DATASET.write_text(
            json.dumps(dataset, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Final dataset: %s (%d cases)", Paths.FINAL_DATASET, len(dataset))

        # Validation report
        Paths.VALIDATION_REPORT.write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        log.info("Validation report: %s", Paths.VALIDATION_REPORT)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 6 — Final validation and dataset assembly."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run validation checks but don't write output files.",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run)
