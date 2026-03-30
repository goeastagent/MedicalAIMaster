"""
Evaluation/SemanticValueAccuracy/run_pipeline.py

Entry point for the SVA (Semantic Value Accuracy) dataset generation pipeline.

Stages:
  1  Metadata collection (track_names.csv + vital files + clinical data)
  2  Semantic query generation (LLM × 5 categories)
  3  Ground truth code generation + VitalExecutor verification
  4  Quality filtering (4 sub-filters)
  5  Final dataset assembly + validation report

Usage examples:
    # Full pipeline
    python -m Evaluation.SemanticValueAccuracy.run_pipeline

    # Run only stage 1
    python -m Evaluation.SemanticValueAccuracy.run_pipeline --stage 1

    # Run from stage 3 onwards (assumes stages 1-2 outputs exist)
    python -m Evaluation.SemanticValueAccuracy.run_pipeline --from-stage 3

    # Run stages 2 through 4
    python -m Evaluation.SemanticValueAccuracy.run_pipeline --from-stage 2 --to-stage 4

    # Dry-run (no LLM / executor calls)
    python -m Evaluation.SemanticValueAccuracy.run_pipeline --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SVA] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

STAGE_NAMES = {
    1: "Metadata Collection",
    2: "Semantic Query Generation",
    3: "Ground Truth Code Generation + Verification",
    4: "Quality Filtering",
    5: "Final Dataset Assembly + Validation Report",
}

MIN_STAGE = 1
MAX_STAGE = 5


# ---------------------------------------------------------------------------
# Stage runners (lazy imports to avoid heavy deps at CLI parse time)
# ---------------------------------------------------------------------------

def _run_stage1(dry_run: bool, n_cases: int = 3, seed: int | None = None, **kwargs) -> None:
    from Evaluation.SemanticValueAccuracy.stages.stage1_metadata import run
    run(dry_run=dry_run, n_cases=n_cases, seed=seed)


def _run_stage2(dry_run: bool, **kwargs) -> None:
    from Evaluation.SemanticValueAccuracy.stages.stage2_generate import run
    run(dry_run=dry_run)


def _run_multirun(
    n_cases: int,
    num_runs: int,
    seed: Optional[int],
    dry_run: bool,
    skip_llm: bool,
) -> None:
    """
    Multi-run orchestrator for SVA.

    Runs Stage 1 + Stage 2 independently for each set of sampled cases, then
    merges all per-run candidate files into a single sva_candidates.jsonl before
    executing Stages 3-5 once on the combined set.
    """
    from Evaluation.SemanticValueAccuracy.config import Paths
    from Evaluation.SemanticValueAccuracy.stages.stage1_metadata import run as run_s1
    from Evaluation.SemanticValueAccuracy.stages.stage2_generate import run as run_s2
    from Evaluation.utils.case_sampler import sample_cases_excluding, get_vital_dir

    Paths.ensure_output_dir()
    vital_dir = get_vital_dir()
    used_cases: set[str] = set()
    per_run_candidates: list[Path] = []

    for run_idx in range(num_runs):
        run_seed = (seed + run_idx) if seed is not None else None
        log.info("")
        log.info("━" * 60)
        log.info("  Multi-run %d / %d  (seed=%s)", run_idx + 1, num_runs, run_seed)
        log.info("━" * 60)

        cases = sample_cases_excluding(
            exclude=used_cases, vital_dir=vital_dir, n=n_cases, seed=run_seed
        )
        if not cases:
            log.warning("  Run %d: no fresh cases available — stopping early", run_idx)
            break
        used_cases.update(cases.keys())
        log.info("  Sampled: %s  (total used: %d)", sorted(cases.keys()), len(used_cases))

        tag = f"run_{run_idx:03d}"
        meta_path = Paths.OUTPUT_DIR / f"{tag}_metadata_context.json"
        cand_path = Paths.OUTPUT_DIR / f"{tag}_candidates.jsonl"

        # Stage 1
        t0 = time.time()
        run_s1(
            dry_run=dry_run,
            target_case_ids=sorted(cases.keys()),
            output_path=meta_path,
        )
        log.info("  Stage 1 done in %.1fs → %s", time.time() - t0, meta_path.name)

        # Stage 2
        t0 = time.time()
        run_s2(
            dry_run=dry_run,
            output_file=cand_path,
            metadata_context_path=meta_path,
        )
        log.info("  Stage 2 done in %.1fs → %s", time.time() - t0, cand_path.name)
        per_run_candidates.append(cand_path)

    if not per_run_candidates:
        log.error("No candidate files generated. Aborting.")
        return

    # Merge all per-run candidates → master sva_candidates.jsonl
    log.info("")
    log.info("━" * 60)
    log.info("  Merging %d candidate file(s)", len(per_run_candidates))
    log.info("━" * 60)
    master_candidates = Paths.CANDIDATES
    all_records = []
    for p in per_run_candidates:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            all_records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
    with open(master_candidates, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log.info("  Merged %d candidates → %s", len(all_records), master_candidates)
    log.info("  Cases covered: %d", len(used_cases))

    # Stages 3-5
    for stage_num in range(3, MAX_STAGE + 1):
        name = STAGE_NAMES[stage_num]
        runner = STAGE_RUNNERS[stage_num]
        log.info("")
        log.info("━" * 60)
        log.info("  Stage %d / %d : %s", stage_num, MAX_STAGE, name)
        log.info("━" * 60)
        t0 = time.time()
        try:
            runner(dry_run=dry_run, skip_llm=skip_llm)
        except Exception as e:
            log.error("Stage %d failed: %s", stage_num, e, exc_info=True)
            log.error("Fix the issue and re-run with --from-stage %d", stage_num)
            sys.exit(1)
        log.info("  Stage %d finished in %.1fs", stage_num, time.time() - t0)


def _run_stage3(dry_run: bool, **kwargs) -> None:
    from Evaluation.SemanticValueAccuracy.stages.stage3_ground_truth import run
    run(dry_run=dry_run)


def _run_stage4(dry_run: bool, skip_llm: bool = False, **kwargs) -> None:
    from Evaluation.SemanticValueAccuracy.stages.stage4_filter import run
    run(dry_run=dry_run, skip_llm=skip_llm)


def _run_stage5(dry_run: bool, **kwargs) -> None:
    from Evaluation.SemanticValueAccuracy.stages.stage5_assemble import run
    run(dry_run=dry_run)


STAGE_RUNNERS = {
    1: _run_stage1,
    2: _run_stage2,
    3: _run_stage3,
    4: _run_stage4,
    5: _run_stage5,
}


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(
    from_stage: int = MIN_STAGE,
    to_stage: int = MAX_STAGE,
    dry_run: bool = False,
    skip_llm: bool = False,
    n_cases: int = 10,
    num_runs: int = 10,
    seed: int | None = None,
) -> None:
    """Execute pipeline stages sequentially.

    When num_runs > 1 and the run starts from Stage 1, this uses the multi-run
    orchestrator: Stages 1-2 are repeated num_runs times with non-overlapping
    case sets, then Stages 3-5 are executed once on the merged candidates.

    Args:
        from_stage: First stage to run.
        to_stage:   Last stage to run.
        dry_run:    Skip all LLM / executor API calls.
        skip_llm:   Skip LLM calls in Stage 4.
        n_cases:    Number of .vital files to randomly sample per run.
        num_runs:   Independent sampling+generation runs (default: 1).
        seed:       Base random seed for case sampling.
    """
    from Evaluation.SemanticValueAccuracy.config import Paths
    Paths.ensure_output_dir()

    log.info("=" * 60)
    log.info("Semantic Value Accuracy — Dataset Generation Pipeline")
    log.info("  Stages     : %d → %d", from_stage, to_stage)
    log.info("  Dry-run    : %s", dry_run)
    log.info("  Skip LLM   : %s", skip_llm)
    log.info("  n_cases    : %d", n_cases)
    log.info("  num_runs   : %d", num_runs)
    log.info("  seed       : %s", seed)
    log.info("=" * 60)

    # Multi-run path: only when starting from the beginning and num_runs > 1
    if num_runs > 1 and from_stage == MIN_STAGE:
        _run_multirun(
            n_cases=n_cases,
            num_runs=num_runs,
            seed=seed,
            dry_run=dry_run,
            skip_llm=skip_llm,
        )
        return

    # Single-run (original) path
    stages = range(from_stage, to_stage + 1)
    timings = {}

    for stage_num in stages:
        name = STAGE_NAMES[stage_num]
        runner = STAGE_RUNNERS[stage_num]

        log.info("")
        log.info("━" * 60)
        log.info("  Stage %d / %d : %s", stage_num, MAX_STAGE, name)
        log.info("━" * 60)

        t0 = time.time()
        try:
            runner(dry_run=dry_run, skip_llm=skip_llm, n_cases=n_cases, seed=seed)
        except Exception as e:
            log.error("Stage %d failed: %s", stage_num, e, exc_info=True)
            log.error(
                "Pipeline aborted. Fix the issue and re-run with --from-stage %d",
                stage_num,
            )
            sys.exit(1)
        elapsed = time.time() - t0
        timings[stage_num] = elapsed
        log.info("  Stage %d finished in %.1fs", stage_num, elapsed)

    total_time = sum(timings.values())
    log.info("")
    log.info("=" * 60)
    log.info("  Pipeline complete!")
    log.info("=" * 60)
    for s, t in timings.items():
        log.info("  Stage %d %-40s %6.1fs", s, STAGE_NAMES[s], t)
    log.info("  %-45s %6.1fs", "TOTAL", total_time)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SVA (Semantic Value Accuracy) dataset generation pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m Evaluation.SemanticValueAccuracy.run_pipeline\n"
            "  python -m Evaluation.SemanticValueAccuracy.run_pipeline --dry-run\n"
            "  python -m Evaluation.SemanticValueAccuracy.run_pipeline --stage 1\n"
            "  python -m Evaluation.SemanticValueAccuracy.run_pipeline --from-stage 3\n"
            "  python -m Evaluation.SemanticValueAccuracy.run_pipeline --from-stage 2 --to-stage 4\n"
        ),
    )
    parser.add_argument(
        "--stage", type=int, default=None,
        help="Run only this single stage (1-5).",
    )
    parser.add_argument(
        "--from-stage", type=int, default=MIN_STAGE,
        help=f"Start from this stage (default: {MIN_STAGE}).",
    )
    parser.add_argument(
        "--to-stage", type=int, default=MAX_STAGE,
        help=f"End at this stage (default: {MAX_STAGE}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip all LLM / executor API calls.",
    )
    parser.add_argument(
        "--skip-llm", action="store_true",
        help="Skip LLM calls in Stage 4 (quality audit filter).",
    )
    parser.add_argument(
        "--n-cases", type=int, default=10,
        help="Number of .vital files to randomly sample per run (default: 10).",
    )
    parser.add_argument(
        "--num-runs", type=int, default=10,
        help=(
            "Number of independent sampling+generation runs (default: 10). "
            "When >1 and --from-stage=1, Stages 1-2 are repeated with fresh "
            "non-overlapping cases; Stages 3-5 run once on the merged candidates."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Base random seed for case sampling (default: non-deterministic).",
    )
    args = parser.parse_args()

    if args.stage is not None:
        from_stage = to_stage = args.stage
    else:
        from_stage = args.from_stage
        to_stage = args.to_stage

    if not (MIN_STAGE <= from_stage <= MAX_STAGE):
        parser.error(f"--from-stage must be between {MIN_STAGE} and {MAX_STAGE}")
    if not (MIN_STAGE <= to_stage <= MAX_STAGE):
        parser.error(f"--to-stage must be between {MIN_STAGE} and {MAX_STAGE}")
    if from_stage > to_stage:
        parser.error("--from-stage cannot be greater than --to-stage")

    run_pipeline(
        from_stage=from_stage,
        to_stage=to_stage,
        dry_run=args.dry_run,
        skip_llm=args.skip_llm,
        n_cases=args.n_cases,
        num_runs=args.num_runs,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
