"""
Evaluation/Level1/run_pipeline.py

Entry point for the Level 1 evaluation dataset generation pipeline.

Stages:
  1  Parameter corpus + synonym generation   (DB + LLM)
  2  Query candidate generation              (LLM)
  3  Ground truth auto-labeling              (rule-based)
  4  Quality filtering (4 sub-filters)       (embedding + LLM)
  5  Adversarial case generation             (LLM)
  6  Final validation & dataset assembly     (rule-based)

Usage examples:
    # Full pipeline
    python -m Evaluation.Level1.run_pipeline

    # Full pipeline, dry-run (no LLM / embedding calls)
    python -m Evaluation.Level1.run_pipeline --dry-run

    # Run only stage 1
    python -m Evaluation.Level1.run_pipeline --stage 1

    # Run from stage 3 onwards (assumes stages 1-2 outputs exist)
    python -m Evaluation.Level1.run_pipeline --from-stage 3

    # Run stages 4 through 6
    python -m Evaluation.Level1.run_pipeline --from-stage 4 --to-stage 6

    # Run stage 4 but skip the LLM validity filter
    python -m Evaluation.Level1.run_pipeline --stage 4 --skip-llm
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
    format="%(asctime)s [Pipeline] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

STAGE_NAMES = {
    1: "Parameter Corpus + Synonym Generation",
    2: "Query Candidate Generation",
    3: "Ground Truth Auto-Labeling",
    4: "Quality Filtering",
    5: "Adversarial Case Generation",
    6: "Final Validation & Dataset Assembly",
}

MIN_STAGE = 1
MAX_STAGE = 6


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _run_stage1(dry_run: bool, **kwargs) -> None:
    from Evaluation.Level1.stages.stage1_corpus import run
    run(dry_run=dry_run)


def _run_stage2(dry_run: bool, **kwargs) -> None:
    from Evaluation.Level1.stages.stage2_generate import run
    run(dry_run=dry_run)


def _run_stage3(dry_run: bool, **kwargs) -> None:
    from Evaluation.Level1.stages.stage3_label import run
    run(dry_run=dry_run)


def _run_stage4(dry_run: bool, skip_llm: bool = False, **kwargs) -> None:
    from Evaluation.Level1.stages.stage4_filter import run
    run(dry_run=dry_run, skip_llm=skip_llm)


def _run_stage5(dry_run: bool, **kwargs) -> None:
    from Evaluation.Level1.stages.stage5_adversarial import run
    run(dry_run=dry_run)


def _run_stage6(dry_run: bool, **kwargs) -> None:
    from Evaluation.Level1.stages.stage6_validate import run
    run(dry_run=dry_run)


STAGE_RUNNERS = {
    1: _run_stage1,
    2: _run_stage2,
    3: _run_stage3,
    4: _run_stage4,
    5: _run_stage5,
    6: _run_stage6,
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
    stages = range(from_stage, to_stage + 1)
    total = to_stage - from_stage + 1

    log.info("=" * 60)
    log.info("Level 1 Dataset Generation Pipeline")
    log.info("  Stages     : %d → %d (%d stage%s)",
             from_stage, to_stage, total, "s" if total > 1 else "")
    log.info("  Dry-run    : %s", dry_run)
    log.info("  Skip LLM   : %s", skip_llm)
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
            log.error("Stage %d failed: %s", stage_num, e)
            log.error("Pipeline aborted. Fix the issue and re-run with --from-stage %d", stage_num)
            sys.exit(1)
        elapsed = time.time() - t0
        timings[stage_num] = elapsed
        log.info("  Stage %d finished in %.1fs", stage_num, elapsed)

    # Summary
    total_time = sum(timings.values())
    log.info("")
    log.info("=" * 60)
    log.info("  Pipeline complete!")
    log.info("=" * 60)
    for s, t in timings.items():
        log.info("  Stage %d %-35s %6.1fs", s, STAGE_NAMES[s], t)
    log.info("  %-40s %6.1fs", "TOTAL", total_time)
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Level 1 evaluation dataset generation pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m Evaluation.Level1.run_pipeline               # full pipeline\n"
            "  python -m Evaluation.Level1.run_pipeline --dry-run      # no LLM calls\n"
            "  python -m Evaluation.Level1.run_pipeline --stage 1      # single stage\n"
            "  python -m Evaluation.Level1.run_pipeline --from-stage 3 # stages 3-6\n"
            "  python -m Evaluation.Level1.run_pipeline --from-stage 4 --to-stage 5\n"
        ),
    )
    parser.add_argument(
        "--stage", type=int, default=None,
        help="Run only this single stage (1-6).",
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
        help="Skip all LLM / embedding API calls.",
    )
    parser.add_argument(
        "--skip-llm", action="store_true",
        help="Skip only LLM calls in Stage 4 (validity filter).",
    )
    args = parser.parse_args()

    # --stage N overrides --from-stage / --to-stage
    if args.stage is not None:
        from_stage = to_stage = args.stage
    else:
        from_stage = args.from_stage
        to_stage = args.to_stage

    # Validate range
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
