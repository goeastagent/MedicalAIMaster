import os
import re
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from difflib import SequenceMatcher
from dotenv import load_dotenv
from typing import Optional

import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from shared.llm.client import get_llm_client
from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor
from Evaluation.Temporal.extract_metadata import CLINICAL_RANGES

_DEFAULT_METADATA_PATH = Path(__file__).parent / "vital_metadata.json"
_OUTPUT_DIR = Path(__file__).parent / "output"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BATCH_SIZE = 20
MAX_TOKENS_PER_BATCH = 65536
SIMILARITY_THRESHOLD = 0.80
MAX_NONE_RATIO = 0.15
MAX_NAN_RATIO_PER_WINDOW = 0.50
MIN_UNIQUE_VALUES = 3
MIN_VALID_SAMPLES = 30
MAX_WARNINGS_IN_PROMPT = 40


# ═══════════════════════════════════════════════════════════════════════════
# Quality warnings loader
# ═══════════════════════════════════════════════════════════════════════════

def _load_vital_metadata(metadata_path: Optional[Path] = None) -> dict:
    """Load vital_metadata.json, returning an empty dict if not found."""
    if metadata_path is None:
        metadata_path = _DEFAULT_METADATA_PATH
    if not metadata_path.exists():
        logger.warning(f"vital_metadata.json not found at {metadata_path} — run extract_metadata.py first")
        return {}
    with open(metadata_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_sampled_case_ids(metadata: dict) -> list[str]:
    """Return the case IDs recorded in vital_metadata.json by extract_metadata.py."""
    stored = metadata.get("_sampled_case_ids")
    if stored:
        return stored
    # Fallback: infer from top-level keys (excluding the meta key itself)
    return sorted(k for k in metadata if not k.startswith("_"))


def _load_quality_warnings(metadata_path: Optional[Path] = None) -> str:
    """Load condensed warnings from vital_metadata.json for prompt injection."""
    metadata = _load_vital_metadata(metadata_path)
    if not metadata:
        return "(No quality warnings available — metadata not yet extracted.)"

    warnings = []
    for caseid, case_data in sorted(
        (k, v) for k, v in metadata.items() if not k.startswith("_")
    ):
        for track, profile in case_data.get("track_profiles", {}).items():
            if "error" in profile:
                continue
            for aw in profile.get("artifact_windows", []):
                if aw["out_of_range_ratio"] >= 0.5:
                    warnings.append(
                        f"- caseid {caseid} / `{track}`: [{aw['start']}s–{aw['end']}s] "
                        f"contains {int(aw['out_of_range_ratio']*100)}% clinically out-of-range "
                        f"values (calibration artifact). DO NOT query."
                    )
            for sw in profile.get("sparse_windows", []):
                if sw["nan_ratio"] >= 1.0:
                    warnings.append(
                        f"- caseid {caseid} / `{track}`: [{sw['start']}s–{sw['end']}s] "
                        f"is 100% NaN. DO NOT query."
                    )
            if profile.get("nan_ratio", 0) > 0.90:
                vr = profile.get("valid_data_range_sec")
                vr_str = f"[{vr[0]}s–{vr[1]}s]" if vr else "none"
                warnings.append(
                    f"- caseid {caseid} / `{track}`: Overall {profile['nan_ratio']:.0%} NaN. "
                    f"Valid data only in {vr_str}. Very sparse — avoid if possible."
                )

    if len(warnings) > MAX_WARNINGS_IN_PROMPT:
        warnings = warnings[:MAX_WARNINGS_IN_PROMPT]
        warnings.append(f"- ... and more. Always verify your chosen window has sufficient data.")

    return "\n".join(warnings) if warnings else "(All tracks have acceptable data quality.)"


# ═══════════════════════════════════════════════════════════════════════════
# Deduplication
# ═══════════════════════════════════════════════════════════════════════════

def _extract_signature(q: dict) -> str:
    query_text = q.get("query", "")
    tracks = tuple(sorted(q.get("track_names", [])))
    caseids = tuple(sorted(set(re.findall(r'caseid\s*(\d+)', query_text))))
    numbers = re.findall(r'(\d+)\s*(?:seconds|minutes|hrs|hours)', query_text.lower())
    time_window = tuple(sorted(numbers))
    agg_keywords = []
    for kw in ["maximum", "minimum", "average", "mean", "median",
                "standard deviation", "std", "count", "percentile"]:
        if kw in query_text.lower():
            agg_keywords.append(kw)
    agg = tuple(sorted(agg_keywords))
    return f"{tracks}|{caseids}|{time_window}|{agg}"


def _dedup_queries(queries: list) -> list:
    logger.info("--- Deduplication Check ---")
    kept = []
    seen_sigs = {}
    removed_count = 0

    for q in queries:
        if q.get("question_type") == "temporal_ambiguous":
            is_dup = False
            for existing in kept:
                if existing.get("question_type") != "temporal_ambiguous":
                    continue
                sim = SequenceMatcher(None, q["query"], existing["query"]).ratio()
                if sim >= SIMILARITY_THRESHOLD:
                    removed_count += 1
                    logger.warning(f"  DUPLICATE removed: {q['id']} ~= {existing['id']} (sim={sim:.2f})")
                    is_dup = True
                    break
            if not is_dup:
                kept.append(q)
            continue

        sig = _extract_signature(q)
        if sig in seen_sigs:
            removed_count += 1
            logger.warning(f"  DUPLICATE removed: {q['id']} same signature as {seen_sigs[sig]}")
        else:
            seen_sigs[sig] = q["id"]
            kept.append(q)

    logger.info(f"  Kept {len(kept)}, removed {removed_count} duplicates")
    return kept


def _extract_queries(response) -> list:
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for val in response.values():
            if isinstance(val, list):
                return val
        if "queries" in response:
            return response["queries"]
    return []


# ═══════════════════════════════════════════════════════════════════════════
# Quality gate for individual queries
# ═══════════════════════════════════════════════════════════════════════════

def _parse_window_from_code(code: str) -> tuple:
    """Extract (caseid, track, slice_type, start, end) from GT code."""
    caseid_match = re.search(r"'(\d{4})\.vital'", code)
    track_match = re.search(r"to_numpy\(\['([^']+)'\]", code)
    caseid = caseid_match.group(1) if caseid_match else None
    track = track_match.group(1) if track_match else None

    slice_match = re.search(r'vals\[(-?\d*):(\d*)\]', code)
    if not slice_match:
        slice_match = re.search(r'window_vals\s*=\s*vals\[(-?\d*):(\d*)\]', code)

    start_str = slice_match.group(1) if slice_match else ""
    end_str = slice_match.group(2) if slice_match else ""

    return caseid, track, start_str, end_str


def _assess_query_quality(query: dict, result, metadata: dict) -> dict:
    """
    Post-execution quality gate.
    Returns {"pass": bool, "flags": [...], "reason": str}
    """
    flags = []

    if query.get("question_type") == "temporal_ambiguous":
        return {"pass": True, "flags": [], "reason": "OK (ambiguous)"}

    code = query.get("ground_truth_logic", {}).get("code", "")
    caseid, track, start_str, end_str = _parse_window_from_code(code)
    if not caseid or not track:
        flags.append("PARSE_FAIL")
        return {"pass": True, "flags": flags, "reason": "Could not parse window, allowing"}

    case_meta = metadata.get(caseid, {})
    duration = case_meta.get("duration_sec", 0)
    profile = case_meta.get("track_profiles", {}).get(track, {})

    if "error" in profile or not profile:
        flags.append("NO_PROFILE")
        return {"pass": True, "flags": flags, "reason": "No profile available"}

    # Resolve slice indices
    try:
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else duration
        if start < 0:
            start = max(0, duration + start)
    except ValueError:
        return {"pass": True, "flags": ["SLICE_PARSE_FAIL"], "reason": "OK"}

    # Gate 1: Artifact check
    if track in CLINICAL_RANGES and result is not None and isinstance(result, (int, float)):
        lo, hi = CLINICAL_RANGES[track]
        if result < lo or result > hi:
            agg_lower = query.get("query", "").lower()
            is_count = "count" in agg_lower or "how many" in agg_lower
            if not is_count:
                flags.append(f"ARTIFACT_SUSPECT:result={result},range=[{lo},{hi}]")

    # Gate 2: NaN density
    for aw in profile.get("artifact_windows", []):
        if aw["start"] < end and aw["end"] > start and aw["out_of_range_ratio"] > 0.5:
            flags.append(f"ARTIFACT_WINDOW:[{aw['start']}-{aw['end']}]")

    for sw in profile.get("sparse_windows", []):
        if sw["start"] < end and sw["end"] > start and sw["nan_ratio"] >= 1.0:
            window_overlap = min(end, sw["end"]) - max(start, sw["start"])
            total_window = end - start
            if total_window > 0 and window_overlap / total_window > 0.5:
                flags.append(f"MOSTLY_NAN_OVERLAP:[{sw['start']}-{sw['end']}]")

    # Gate 3: Trivial result (constant value window)
    for cw in profile.get("constant_windows", []):
        if cw["start"] <= start and cw["end"] >= end and len(cw.get("unique_values", [])) <= 1:
            flags.append(f"CONSTANT_WINDOW:{cw['unique_values']}")

    # Gate 4: Result is None — check if expected
    if result is None:
        agg_lower = query.get("query", "").lower()
        is_count = "count" in agg_lower or "how many" in agg_lower
        if is_count:
            flags.append("COUNT_RETURNED_NONE")

    # Determine blocking
    blocking = [f for f in flags if f.startswith(("ARTIFACT_SUSPECT", "ARTIFACT_WINDOW", "CONSTANT_WINDOW", "COUNT_RETURNED_NONE"))]
    return {
        "pass": len(blocking) == 0,
        "flags": flags,
        "reason": "; ".join(blocking) if blocking else "OK"
    }


# ═══════════════════════════════════════════════════════════════════════════
# Dataset balance check
# ═══════════════════════════════════════════════════════════════════════════

def _check_dataset_balance(validated: list) -> list:
    warnings = []
    temporal = [q for q in validated if q.get("question_type") == "temporal"]
    ambiguous = [q for q in validated if q.get("question_type") == "temporal_ambiguous"]

    if not temporal:
        warnings.append("No temporal queries in dataset")
        return warnings

    # Determine which case IDs were sampled for this run (from vital_metadata.json)
    metadata = _load_vital_metadata()
    sampled_case_ids = _get_sampled_case_ids(metadata)
    n_sampled = len(sampled_case_ids) if sampled_case_ids else 1

    # caseid balance
    caseid_counts = Counter()
    for q in temporal:
        ids = re.findall(r'caseid\s*(\d+)', q.get("query", ""))
        for cid in ids:
            caseid_counts[cid] += 1

    expected_per_case = len(temporal) / n_sampled
    for cid in sampled_case_ids:
        count = caseid_counts.get(cid, 0)
        if count < expected_per_case * 0.6:
            warnings.append(f"caseid {cid} underrepresented: {count}/{len(temporal)} queries")

    # None ratio
    none_count = sum(1 for q in temporal if q.get("expected_value") is None)
    none_ratio = none_count / len(temporal) if temporal else 0
    if none_ratio > MAX_NONE_RATIO:
        warnings.append(f"None result ratio too high: {none_count}/{len(temporal)} ({none_ratio:.0%})")

    # Style balance
    style_counts = Counter(q.get("query_style") for q in validated)
    for style in ["Start-relative", "End-relative", "Interval-absolute", "Ambiguous"]:
        if style_counts.get(style, 0) == 0:
            warnings.append(f"Missing query_style: {style}")

    # Track diversity
    track_counts = Counter()
    for q in temporal:
        for t in q.get("track_names", []):
            track_counts[t] += 1
    max_track_usage = max(track_counts.values()) if track_counts else 0
    if max_track_usage > 2:
        top_track = track_counts.most_common(1)[0]
        warnings.append(f"Track overuse: {top_track[0]} used {top_track[1]} times")

    return warnings


# ═══════════════════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════════════════

def generate_temporal_queries(
    num_queries: int = 20,
    output_file: str = "temporal_queries.jsonl",
    metadata_path: Optional[Path] = None,
):
    """
    Args:
        num_queries:   Total queries to generate.
        output_file:   Output filename (relative to output/).
        metadata_path: Path to vital_metadata.json used for quality warnings.
                       Defaults to the standard location.
    """
    prompt_path = Path(__file__).parent / "prompts" / "temporal_query_gen.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    quality_warnings_text = _load_quality_warnings(metadata_path)
    prompt_template = prompt_template.replace("{quality_warnings}", quality_warnings_text)

    llm_client = get_llm_client()
    logger.info(f"Generating {num_queries} temporal queries using LLM...")

    all_queries = []
    remaining = num_queries
    batch_num = 0

    while remaining > 0:
        batch_size = min(BATCH_SIZE, remaining)
        batch_num += 1
        prompt = prompt_template.replace("{num_queries}", str(batch_size))

        logger.info(f"  Batch {batch_num}: requesting {batch_size} queries...")
        response = llm_client.ask_json(prompt, max_tokens=MAX_TOKENS_PER_BATCH)

        if isinstance(response, dict) and "error" in response:
            logger.error(f"  Batch {batch_num} failed: {response['error']}")
            continue

        queries = _extract_queries(response)
        if not queries:
            logger.error(f"  Batch {batch_num}: could not parse queries from response.")
            continue

        all_queries.extend(queries)
        remaining -= batch_size
        logger.info(f"  Batch {batch_num}: got {len(queries)} queries (total so far: {len(all_queries)})")

    if not all_queries:
        logger.error("All batches failed. No queries generated.")
        return []

    for i, q in enumerate(all_queries):
        q["id"] = f"temp_{i+1:03d}"
        q["expected_value"] = None
        q["is_verified_by_execution"] = False

    all_queries = _dedup_queries(all_queries)

    for i, q in enumerate(all_queries):
        q["id"] = f"temp_{i+1:03d}"

    output_dir = _OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_file

    with open(output_path, "w", encoding="utf-8") as f:
        for q in all_queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    logger.info(f"Generated {len(all_queries)} temporal queries → {output_path}")
    return all_queries


def validate_temporal_queries(
    input_file: str = "temporal_queries.jsonl",
    output_file: str = "temporal_dataset_validated.jsonl",
    metadata_path: Optional[Path] = None,
):
    """
    Args:
        input_file:    Input filename (relative to output/).
        output_file:   Output filename (relative to output/).
        metadata_path: Path to vital_metadata.json for quality gates.
    """
    input_path = _OUTPUT_DIR / input_file
    output_path = _OUTPUT_DIR / output_file

    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    # Load metadata for quality gates
    if metadata_path is None:
        metadata_path = _DEFAULT_METADATA_PATH
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    else:
        logger.warning(f"vital_metadata.json not found at {metadata_path} — quality gates will be limited")

    queries = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                queries.append(json.loads(line))

    executor = VitalExecutor()
    logger.info(f"Validating {len(queries)} queries...")

    validated = []
    rejected = []
    fail_count = 0

    for q in queries:
        if q.get("question_type") == "temporal_ambiguous":
            q["expected_value"] = "AMBIGUOUS"
            q["is_verified_by_execution"] = True
            q["quality_flags"] = []
            validated.append(q)
            continue

        code = q.get("ground_truth_logic", {}).get("code", "")
        if not code:
            logger.warning(f"  {q['id']}: no code, skipping.")
            fail_count += 1
            continue

        res = executor.execute_code(code)
        if not res["success"]:
            logger.warning(f"  {q['id']} EXEC FAILED: {res['error']}")
            fail_count += 1
            continue

        # Quality gate
        quality = _assess_query_quality(q, res["result"], metadata)
        q["quality_flags"] = quality["flags"]

        if quality["pass"]:
            q["expected_value"] = res["result"]
            q["is_verified_by_execution"] = True
            validated.append(q)
            logger.info(f"  {q['id']} OK → {res['result']}"
                        + (f"  flags={quality['flags']}" if quality["flags"] else ""))
        else:
            rejected.append(q)
            logger.warning(f"  {q['id']} REJECTED by quality gate: {quality['reason']}")

    # Dataset-level balance check
    balance_warnings = _check_dataset_balance(validated)

    # Summary
    numeric = [q for q in validated if q.get("question_type") == "temporal"]
    none_count = sum(1 for q in numeric if q["expected_value"] is None)
    none_ratio = none_count / len(numeric) if numeric else 0

    logger.info(f"\n{'='*60}")
    logger.info(f"  Validation Summary")
    logger.info(f"{'='*60}")
    logger.info(f"  Total validated: {len(validated)}")
    logger.info(f"  Execution failures (dropped): {fail_count}")
    logger.info(f"  Quality gate rejections: {len(rejected)}")
    logger.info(f"  Numeric with None result: {none_count}/{len(numeric)} ({none_ratio:.0%})")

    if balance_warnings:
        logger.warning(f"\n  --- Balance Warnings ---")
        for w in balance_warnings:
            logger.warning(f"    {w}")

    if rejected:
        logger.info(f"\n  --- Rejected Queries ---")
        for q in rejected:
            logger.info(f"    {q['id']}: {q.get('quality_flags', [])}")

    with open(output_path, "w", encoding="utf-8") as f:
        for q in validated:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    logger.info(f"\n  Saved {len(validated)} validated queries → {output_path}")


def run_temporal_pipeline(
    n_cases: int = 10,
    num_runs: int = 10,
    seed: Optional[int] = None,
    num_queries_per_run: int = 20,
):
    """
    Multi-run Temporal dataset generation orchestrator.

    Each run samples a fresh set of cases, extracts their metadata, generates
    temporal queries, validates them, then accumulates into a master dataset.

    Args:
        n_cases:           Cases per run.
        num_runs:          Number of independent runs.
        seed:              Base random seed (run i uses seed+i).
        num_queries_per_run: Temporal queries to generate per run.
    """
    from Evaluation.Temporal.extract_metadata import extract_metadata
    from Evaluation.utils.case_sampler import sample_cases_excluding, get_vital_dir

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    vital_dir = get_vital_dir()
    used_cases: set[str] = set()
    all_validated_files: list[str] = []

    for run_idx in range(num_runs):
        run_seed = (seed + run_idx) if seed is not None else None
        logger.info(f"\n{'='*60}")
        logger.info(f"  Temporal Run {run_idx + 1}/{num_runs}  (seed={run_seed})")
        logger.info(f"{'='*60}")

        cases = sample_cases_excluding(
            exclude=used_cases, vital_dir=vital_dir, n=n_cases, seed=run_seed
        )
        if not cases:
            logger.warning(f"  Run {run_idx}: no fresh cases available — stopping early")
            break
        used_cases.update(cases.keys())
        logger.info(f"  Sampled: {sorted(cases.keys())}")

        tag = f"run_{run_idx:03d}"
        meta_path = _OUTPUT_DIR / f"{tag}_vital_metadata.json"
        queries_file = f"{tag}_temporal_queries.jsonl"
        validated_file = f"{tag}_temporal_validated.jsonl"

        # 1. Extract metadata for this run's cases
        extract_metadata(
            target_cases=sorted(cases.keys()),
            output_path=meta_path,
        )

        # 2. Generate temporal queries using this run's metadata
        generate_temporal_queries(
            num_queries=num_queries_per_run,
            output_file=queries_file,
            metadata_path=meta_path,
        )

        # 3. Validate
        validate_temporal_queries(
            input_file=queries_file,
            output_file=validated_file,
            metadata_path=meta_path,
        )
        all_validated_files.append(validated_file)

    # Merge all runs into a single master dataset
    logger.info(f"\n--- Merging {len(all_validated_files)} Temporal run file(s) ---")
    master_path = _OUTPUT_DIR / "temporal_dataset_validated.jsonl"
    all_records = []
    for fname in all_validated_files:
        fpath = _OUTPUT_DIR / fname
        if fpath.exists():
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            all_records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

    # Reassign IDs
    for i, rec in enumerate(all_records):
        rec["id"] = f"temp_{i+1:04d}"

    with open(master_path, "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(f"Merged {len(all_records)} temporal records → {master_path}")
    logger.info(f"Cases covered: {len(used_cases)}")
    return master_path


if __name__ == "__main__":
    import argparse
    load_dotenv()
    parser = argparse.ArgumentParser(description="Generate Temporal benchmark dataset.")
    parser.add_argument("--num-queries", type=int, default=20)
    parser.add_argument("--n-cases", type=int, default=10,
                        help="Number of .vital files to randomly sample per run (default: 10)")
    parser.add_argument("--num-runs", type=int, default=10,
                        help="Number of independent runs with fresh case sets (default: 10)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    if args.num_runs > 1:
        run_temporal_pipeline(
            n_cases=args.n_cases,
            num_runs=args.num_runs,
            seed=args.seed,
            num_queries_per_run=args.num_queries,
        )
    else:
        generate_temporal_queries(num_queries=args.num_queries)
        validate_temporal_queries()
