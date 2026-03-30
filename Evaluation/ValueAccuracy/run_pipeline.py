import argparse
import json
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import sys
from typing import Optional

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from Evaluation.ValueAccuracy.stages.stage1_base import generate_base_queries
from Evaluation.ValueAccuracy.stages.stage2_conditional import generate_conditional_queries
from Evaluation.ValueAccuracy.stages.stage3_adversarial import generate_adversarial_queries
from Evaluation.ValueAccuracy.stages.stage4_validate import validate_and_merge_datasets
from Evaluation.ValueAccuracy.stages.stage4b_ambiguity_check import run_ambiguity_check
from Evaluation.utils.case_sampler import sample_cases_excluding, get_vital_dir

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent / "output"


def _run_single(cases: dict, run_idx: int) -> list[str]:
    """
    Generate + validate queries for one set of cases.
    Returns a list of per-run validated JSONL filenames (relative to output/).
    """
    tag = f"run_{run_idx:03d}"

    base_file = f"{tag}_base_queries.jsonl"
    cond_file = f"{tag}_conditional_queries.jsonl"
    adv_file  = f"{tag}_adversarial_queries.jsonl"
    val_file  = f"{tag}_validated.jsonl"

    logger.info(f"\n  [Run {run_idx}] Generating base queries ...")
    base_q = generate_base_queries(num_queries=20, cases=cases, output_file=base_file)
    if not base_q:
        logger.warning(f"  [Run {run_idx}] Base queries empty — retrying once")
        base_q = generate_base_queries(num_queries=20, cases=cases, output_file=base_file)

    logger.info(f"  [Run {run_idx}] Generating conditional queries ...")
    cond_q = generate_conditional_queries(num_queries=20, cases=cases, output_file=cond_file)
    if not cond_q:
        logger.warning(f"  [Run {run_idx}] Conditional queries empty — retrying once")
        cond_q = generate_conditional_queries(num_queries=20, cases=cases, output_file=cond_file)

    logger.info(f"  [Run {run_idx}] Generating adversarial queries ...")
    generate_adversarial_queries(num_queries=10, cases=cases, output_file=adv_file)

    if len(base_q) + len(cond_q) == 0:
        logger.error(f"  [Run {run_idx}] No queries generated — skipping validation")
        return []

    logger.info(f"  [Run {run_idx}] Validating ...")
    validate_and_merge_datasets(
        output_filename=val_file,
        input_filenames=[base_file, cond_file, adv_file],
    )
    return [val_file]


def _merge_validated_files(validated_files: list[str], merged_filename: str) -> Path:
    """Concatenate all per-run validated JSONL files, reassign IDs."""
    merged_path = OUTPUT_DIR / merged_filename
    all_records = []
    for fname in validated_files:
        fpath = OUTPUT_DIR / fname
        if not fpath.exists():
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        all_records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    # Reassign sequential IDs so no two records share an id
    for i, rec in enumerate(all_records):
        rec["id"] = f"va_{i+1:04d}"

    with open(merged_path, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(f"Merged {len(all_records)} records → {merged_path}")
    return merged_path


def run_pipeline(
    n_cases: int = 10,
    num_runs: int = 10,
    seed: Optional[int] = None,
):
    """
    Run the full Value Accuracy benchmark dataset generation pipeline.

    When num_runs > 1, each run samples a fresh non-overlapping set of cases
    from vital_files and the per-run validated outputs are accumulated into a
    single master dataset before the final ambiguity / dedup check.

    Args:
        n_cases:  Number of .vital files to randomly sample per run.
        num_runs: How many independent runs to execute.
        seed:     Base random seed.  Run i uses seed+i so runs are reproducible
                  yet produce different case selections.
    """
    logger.info("=== Starting Value Accuracy Dataset Pipeline ===")
    logger.info(f"    n_cases={n_cases}, num_runs={num_runs}, seed={seed}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    vital_dir = get_vital_dir()

    used_cases: set[str] = set()
    all_validated_files: list[str] = []

    for run_idx in range(num_runs):
        run_seed = (seed + run_idx) if seed is not None else None
        logger.info(f"\n{'='*60}")
        logger.info(f"  Run {run_idx + 1}/{num_runs}  (seed={run_seed})")
        logger.info(f"{'='*60}")

        cases = sample_cases_excluding(
            exclude=used_cases,
            vital_dir=vital_dir,
            n=n_cases,
            seed=run_seed,
        )
        if not cases:
            logger.warning(f"  Run {run_idx}: no fresh cases available — stopping early")
            break

        logger.info(f"  Sampled caseids: {sorted(cases.keys())}  "
                    f"(total used so far: {len(used_cases) + len(cases)})")
        used_cases.update(cases.keys())

        val_files = _run_single(cases, run_idx)
        all_validated_files.extend(val_files)

    if not all_validated_files:
        logger.error("All runs produced no validated queries. Pipeline FAILED.")
        return

    # Merge all runs
    logger.info(f"\n--- Merging {len(all_validated_files)} run file(s) ---")
    merged_path = _merge_validated_files(all_validated_files, "value_accuracy_dataset.jsonl")

    # Final ambiguity + dedup check (caseid-aware) on the merged master
    logger.info("\n--- Ambiguity Check (cross-run) ---")
    clean_path = OUTPUT_DIR / "value_accuracy_dataset_clean.jsonl"
    amb_summary = run_ambiguity_check(
        dataset_path=merged_path,
        output_path=clean_path,
    )
    if "error" in amb_summary:
        logger.error(f"Ambiguity check failed: {amb_summary['error']}")
    else:
        logger.info(
            f"Ambiguity check: {amb_summary['kept']}/{amb_summary['total_input']} queries survived "
            f"({amb_summary['removed']} removed)"
        )

    logger.info("\n=== Pipeline Completed Successfully ===")
    logger.info(f"  Runs completed  : {num_runs}")
    logger.info(f"  Cases covered   : {len(used_cases)}")
    logger.info(f"  Raw merged      : {merged_path}")
    logger.info(f"  Clean dataset   : {clean_path}")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the Value Accuracy dataset generation pipeline.")
    parser.add_argument(
        "--n-cases", type=int, default=10,
        help="Number of .vital files to randomly sample per run (default: 10)",
    )
    parser.add_argument(
        "--num-runs", type=int, default=10,
        help="Number of independent runs with fresh case sets (default: 10)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Base random seed for case sampling (default: non-deterministic)",
    )
    args = parser.parse_args()
    run_pipeline(n_cases=args.n_cases, num_runs=args.num_runs, seed=args.seed)
