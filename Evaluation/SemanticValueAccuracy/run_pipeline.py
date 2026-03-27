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
import logging
import sys
import time
from pathlib import Path

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

def _run_stage1(dry_run: bool, **kwargs) -> None:
    from Evaluation.SemanticValueAccuracy.stages.stage1_metadata import run
    run(dry_run=dry_run)


def _run_stage2(dry_run: bool, **kwargs) -> None:
    from Evaluation.SemanticValueAccuracy.stages.stage2_generate import run
    run(dry_run=dry_run)


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
) -> None:
    """Execute pipeline stages sequentially."""
    from Evaluation.SemanticValueAccuracy.config import Paths
    Paths.ensure_output_dir()

    stages = range(from_stage, to_stage + 1)
    total = to_stage - from_stage + 1

    log.info("=" * 60)
    log.info("Semantic Value Accuracy — Dataset Generation Pipeline")
    log.info("  Stages     : %d → %d (%d stage%s)",
             from_stage, to_stage, total, "s" if total > 1 else "")
    log.info("  Dry-run    : %s", dry_run)
    log.info("  Skip LLM  : %s", skip_llm)
    log.info("=" * 60)

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
            runner(dry_run=dry_run, skip_llm=skip_llm)
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
    )


if __name__ == "__main__":
    main()
