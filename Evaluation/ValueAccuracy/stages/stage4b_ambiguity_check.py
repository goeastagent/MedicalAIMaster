import os
import json
import re
import logging
from pathlib import Path
from collections import Counter
from difflib import SequenceMatcher
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor
from shared.llm.client import get_llm_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_NONE_RATIO = 0.30
SIMILARITY_THRESHOLD = 0.80

AMBIGUITY_AUDIT_PROMPT = """You are a benchmark quality auditor. Your job is to determine whether a natural-language query about medical vital-sign data is UNAMBIGUOUS — meaning any competent developer would produce the EXACT SAME numerical answer.

### Context:
This benchmark operates on .vital files containing full intraoperative recordings. Phrases like "over the entire recording" or "for caseid XXXX" mean the FULL recording for that case — this is UNAMBIGUOUS and should PASS the time range check.

### Query to audit:
"{query}"

### Check these ambiguity vectors:
1. **Sampling rate**: Does the query specify a sampling rate (e.g., "at 1 Hz", "sampled at 1 Hz")? If not, using a different rate would change counts and averages.
2. **NaN handling**: For mean/average/std/count queries, does it specify how to treat NaN/missing values (e.g., "ignoring NaN", "non-NaN samples")?
3. **Precision**: Does the query specify rounding or decimal places (e.g., "Round to 2 decimal places", "Return as an integer")?
4. **Aggregation scope**: For multi-case queries, does it specify "pool all samples" vs "per-case then average"?
5. **Time range**: Does it mention "entire recording", "full recording", or "over the entire recording"? If the query says "for caseid XXXX" and all data from that case is implied, this counts as specified — PASS.

### Respond with EXACTLY this JSON:
{{"verdict": "PASS" or "FAIL", "issues": ["list of ambiguity issues found, empty if PASS"]}}

Be strict on vectors 1-4. For vector 5 (time range), PASS if the query mentions "entire recording" OR if it simply specifies a caseid (which implies the full recording by default in this benchmark)."""


def _load_dataset(dataset_path: Path) -> list:
    """Load the validated JSONL dataset."""
    if not dataset_path.exists():
        logger.error(f"Dataset not found: {dataset_path}")
        return []
    queries = []
    with open(dataset_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    queries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return queries


def _check_determinism(queries: list, executor: VitalExecutor) -> list:
    """
    Re-run each query's code with interval=0.5 instead of 1.
    If the result differs, the query is sensitive to sampling rate
    and the natural-language query MUST specify it.
    """
    logger.info("--- Determinism Check (interval=1 vs interval=0.5) ---")
    flagged = []
    for q in queries:
        code = q.get("ground_truth_logic", {}).get("code", "")
        if not code or "to_numpy" not in code:
            continue

        code_alt = re.sub(
            r'\.to_numpy\((\[[^\]]+\]),\s*1\)',
            r'.to_numpy(\1, 0.5)',
            code
        )
        if code_alt == code:
            continue

        result_alt = executor.execute_code(code_alt)
        if not result_alt["success"]:
            continue

        original_val = q.get("expected_value")
        alt_val = result_alt["result"]

        if original_val is None and alt_val is None:
            continue

        vals_match = False
        if original_val is not None and alt_val is not None:
            try:
                vals_match = abs(float(original_val) - float(alt_val)) < 1e-6
            except (TypeError, ValueError):
                vals_match = str(original_val) == str(alt_val)
        elif original_val is None and alt_val is None:
            vals_match = True

        if not vals_match:
            hz_mentioned = any(kw in q["query"].lower() for kw in ["hz", "hertz", "1 hz", "sampled at"])
            if not hz_mentioned:
                flagged.append(q["id"])
                logger.warning(
                    f"  DETERMINISM FAIL: {q['id']} — "
                    f"interval=1 → {original_val}, interval=0.5 → {alt_val}, "
                    f"but query does NOT mention sampling rate"
                )
    logger.info(f"  Determinism failures: {len(flagged)}")
    return flagged


def _check_ambiguity_llm(queries: list, llm_client) -> list:
    """Ask LLM to audit each query for ambiguity."""
    logger.info("--- LLM Ambiguity Audit ---")
    flagged = []
    for q in queries:
        prompt = AMBIGUITY_AUDIT_PROMPT.format(query=q["query"])
        try:
            response = llm_client.ask_json(prompt, max_tokens=512)
        except Exception as e:
            logger.error(f"  LLM audit error for {q['id']}: {e}")
            continue

        if isinstance(response, dict) and "error" not in response:
            verdict = response.get("verdict", "FAIL")
            issues = response.get("issues", [])
            if verdict == "FAIL":
                flagged.append(q["id"])
                logger.warning(f"  AMBIGUITY FAIL: {q['id']} — {issues}")
            else:
                logger.debug(f"  AMBIGUITY PASS: {q['id']}")
        else:
            logger.warning(f"  Could not parse LLM audit for {q['id']}")
    logger.info(f"  LLM ambiguity failures: {len(flagged)}")
    return flagged


def _triage_none_values(queries: list) -> list:
    """Flag queries where expected_value is None — too many Nones reduce benchmark utility."""
    logger.info("--- None-Value Triage ---")
    none_ids = [q["id"] for q in queries if q.get("expected_value") is None]
    none_ratio = len(none_ids) / len(queries) if queries else 0
    logger.info(f"  None expected_value: {len(none_ids)}/{len(queries)} ({none_ratio:.0%})")

    if none_ratio <= MAX_NONE_RATIO:
        logger.info(f"  None ratio {none_ratio:.0%} <= {MAX_NONE_RATIO:.0%} threshold — OK")
        return []

    excess = len(none_ids) - int(len(queries) * MAX_NONE_RATIO)
    logger.warning(
        f"  None ratio {none_ratio:.0%} exceeds {MAX_NONE_RATIO:.0%} — "
        f"marking {excess} excess None queries for removal"
    )
    return none_ids[-excess:]


def _extract_caseids_from_query(query_text: str) -> frozenset:
    """Return the set of caseids mentioned in a query string."""
    return frozenset(re.findall(r'caseid\s+(\d+)', query_text, re.IGNORECASE))


def _deduplicate(queries: list) -> list:
    """
    Remove near-duplicate queries based on text similarity + same expected_value.

    Multi-run awareness: two queries that reference *different* caseids are never
    considered duplicates, even if their text is otherwise very similar and both
    have the same expected_value (e.g. adversarial-fake queries with None).
    """
    logger.info("--- Deduplication ---")
    flagged = []
    seen = []
    for q in queries:
        q_caseids = _extract_caseids_from_query(q.get("query", ""))
        is_dup = False
        for s in seen:
            # If both queries reference explicit caseids and they differ → never a dup
            s_caseids = _extract_caseids_from_query(s.get("query", ""))
            if q_caseids and s_caseids and q_caseids != s_caseids:
                continue
            if str(q.get("expected_value")) == str(s.get("expected_value")):
                sim = SequenceMatcher(None, q["query"], s["query"]).ratio()
                if sim >= SIMILARITY_THRESHOLD:
                    flagged.append(q["id"])
                    logger.warning(
                        f"  DUPLICATE: {q['id']} ~= {s['id']} "
                        f"(similarity={sim:.2f}, same value={q.get('expected_value')})"
                    )
                    is_dup = True
                    break
        if not is_dup:
            seen.append(q)
    logger.info(f"  Duplicates found: {len(flagged)}")
    return flagged


def run_ambiguity_check(
    dataset_path: Path = None,
    output_path: Path = None,
    skip_llm: bool = False,
    skip_determinism: bool = False,
) -> dict:
    """
    Run all ambiguity checks on the validated dataset.

    Returns a summary dict with counts and the cleaned dataset path.
    """
    base_dir = Path(__file__).parent.parent / "output"
    if dataset_path is None:
        dataset_path = base_dir / "value_accuracy_dataset.jsonl"
    if output_path is None:
        output_path = base_dir / "value_accuracy_dataset_clean.jsonl"

    queries = _load_dataset(dataset_path)
    if not queries:
        return {"error": "No queries to check", "kept": 0, "removed": 0}

    logger.info(f"=== Ambiguity Check: {len(queries)} queries loaded ===")

    all_flagged = set()

    # 1. Determinism check
    if not skip_determinism:
        executor = VitalExecutor()
        det_flagged = _check_determinism(queries, executor)
        all_flagged.update(det_flagged)
    else:
        logger.info("--- Determinism Check: SKIPPED ---")

    # 2. LLM ambiguity audit
    if not skip_llm:
        llm_client = get_llm_client()
        llm_flagged = _check_ambiguity_llm(queries, llm_client)
        all_flagged.update(llm_flagged)
    else:
        logger.info("--- LLM Ambiguity Audit: SKIPPED ---")

    # 3. None-value triage
    none_flagged = _triage_none_values(queries)
    all_flagged.update(none_flagged)

    # 4. Deduplication
    dup_flagged = _deduplicate(queries)
    all_flagged.update(dup_flagged)

    # Build clean dataset
    clean = [q for q in queries if q["id"] not in all_flagged]

    # Mark removed queries with reason
    for q in queries:
        if q["id"] in all_flagged:
            q["_ambiguity_removed"] = True

    with open(output_path, "w", encoding="utf-8") as f:
        for q in clean:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    summary = {
        "total_input": len(queries),
        "removed": len(all_flagged),
        "kept": len(clean),
        "removed_ids": sorted(all_flagged),
        "output_path": str(output_path),
    }

    none_in_clean = sum(1 for q in clean if q.get("expected_value") is None)
    none_ratio_clean = none_in_clean / len(clean) if clean else 0

    logger.info(f"\n=== Ambiguity Check Summary ===")
    logger.info(f"  Input:   {summary['total_input']}")
    logger.info(f"  Removed: {summary['removed']} ({', '.join(summary['removed_ids']) if summary['removed_ids'] else 'none'})")
    logger.info(f"  Kept:    {summary['kept']}")
    logger.info(f"  None values in clean set: {none_in_clean}/{len(clean)} ({none_ratio_clean:.0%})")
    logger.info(f"  Saved to: {output_path}")

    return summary


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    run_ambiguity_check()
