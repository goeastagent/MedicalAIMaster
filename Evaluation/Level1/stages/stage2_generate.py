"""
Evaluation/Level1/stages/stage2_generate.py

Stage 2: LLM-Based Query Candidate Generation

Reads synonym_map.json (Stage 1 output) and generates query candidates
according to the batch plan in config.py.

Two generation strategies:
  A) Single-* types  — parameters are batched (PARAMS_PER_BATCH at a time);
                        1 query generated per parameter in each batch.
  B) Multi-* types   — MULTI_PAIRS supply predefined parameter pairs;
                        QUERIES_PER_PAIR variants generated per pair.

Oversampling: GENERATION_MULTIPLIER × target count is generated so that
Stage 4 filtering can discard low-quality candidates and still meet the
target.

Output: candidates.jsonl  (one QueryCandidate JSON object per line)

Resumable: keeps a progress file (candidates_progress.json) so that a
partially completed run can be continued.

Usage (standalone):
    python -m Evaluation.Level1.stages.stage2_generate
    python -m Evaluation.Level1.stages.stage2_generate --dry-run
    python -m Evaluation.Level1.stages.stage2_generate --cell Single-Direct:doctor
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.Level1.config import (
    GenerationConfig,
    MULTI_PAIRS,
    Paths,
)
from Evaluation.Level1.models import (
    QueryCandidate,
    QueryStyle,
    QueryType,
    SynonymEntry,
)
from Evaluation.Level1.utils import append_jsonl, load_synonym_map

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage2] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Types that process params in flat batches (1 query per param)
SINGLE_TYPES = {
    QueryType.SINGLE_DIRECT,
    QueryType.SINGLE_SEMANTIC,
    QueryType.SINGLE_ABBREVIATION,
}
# Types that process pre-defined pairs
MULTI_TYPES = {
    QueryType.MULTI_INDEPENDENT,
    QueryType.MULTI_CONDITIONAL,
}


# ---------------------------------------------------------------------------
# Param-info formatters
# ---------------------------------------------------------------------------

def _format_single_param_info(
    entries: List[SynonymEntry],
) -> str:
    """Build the param_info block for Single-* types.

    Format:
      [1] Solar8000/HR | Heart Rate | /min | expressions: heart rate, pulse, HR
    """
    lines = []
    for i, e in enumerate(entries, start=1):
        exprs = ", ".join(e.all_expressions()[:8])
        lines.append(
            f"  [{i}] {e.param_key:<30} | "
            f"{e.semantic_name or e.param_key:<30} | "
            f"{e.unit or '—':<10} | "
            f"expressions: {exprs}"
        )
    return "\n".join(lines)


def _format_multi_param_info(
    pair: dict,
    synonym_map: Dict[str, SynonymEntry],
) -> str:
    """Build the param_info block for Multi-* types.

    For condition/analysis pairs:
      [CONDITION] Solar8000/ART_MBP | MAP | mmHg | expressions: ...
      [ANALYSIS]  Orchestra/NEPI_RATE | ... | expressions: ...

    For independent pairs:
      [1] ... | ...
      [2] ... | ...
    """
    key_a, key_b = pair["param_a"], pair["param_b"]
    ea = synonym_map.get(key_a)
    eb = synonym_map.get(key_b)

    if ea is None or eb is None:
        missing = [k for k in (key_a, key_b) if k not in synonym_map]
        raise KeyError(f"Synonym map missing param_keys: {missing}")

    exprs_a = ", ".join(ea.all_expressions()[:8])
    exprs_b = ", ".join(eb.all_expressions()[:8])

    if pair["role_a"] in ("condition",):
        label_a, label_b = "[CONDITION]", "[ANALYSIS] "
    else:
        label_a, label_b = "[1]", "[2]"

    lines = [
        f"  {label_a} {ea.param_key:<30} | "
        f"{ea.semantic_name or ea.param_key:<30} | "
        f"{ea.unit or '—':<10} | "
        f"expressions: {exprs_a}",
        f"  {label_b} {eb.param_key:<30} | "
        f"{eb.semantic_name or eb.param_key:<30} | "
        f"{eb.unit or '—':<10} | "
        f"expressions: {exprs_b}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_generation_llm(prompt: str, dry_run: bool = False) -> List[dict]:
    """Call the generation LLM and return parsed JSON array.

    Returns an empty list on any error.
    """
    if dry_run:
        return [
            {
                "query": "[DRY-RUN] placeholder query",
                "required_parameters": [],
                "query_style": "doctor",
                "generation_notes": "dry-run",
            }
        ]

    try:
        import os
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=GenerationConfig.GENERATION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate evaluation test data. "
                        "Output a JSON array only, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=GenerationConfig.GENERATION_TEMPERATURE,
            max_tokens=GenerationConfig.GENERATION_MAX_TOKENS,
        )
        raw = response.choices[0].message.content

        # Strip markdown fences if present
        text = re.sub(r"```json\s*", "", raw, flags=re.IGNORECASE)
        text = re.sub(r"```", "", text).strip()

        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed

    except Exception as e:
        log.warning("LLM call failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Batch builders
# ---------------------------------------------------------------------------

def _build_single_batches(
    query_type: QueryType,
    query_style: QueryStyle,
    synonym_map: Dict[str, SynonymEntry],
    target: int,
) -> List[dict]:
    """Build LLM call batches for Single-* types.

    Returns a list of batch dicts, each containing:
      {"params": List[SynonymEntry], "query_type": ..., "query_style": ...}
    """
    all_entries = list(synonym_map.values())
    random.seed(42)
    random.shuffle(all_entries)

    multiplied_target = target * GenerationConfig.GENERATION_MULTIPLIER
    entries_to_use = all_entries[:multiplied_target]

    batch_size = GenerationConfig.PARAMS_PER_BATCH
    batches = []
    for i in range(0, len(entries_to_use), batch_size):
        chunk = entries_to_use[i : i + batch_size]
        batches.append({
            "params": chunk,
            "query_type": query_type,
            "query_style": query_style,
        })
    return batches


def _build_multi_batches(
    query_type: QueryType,
    query_style: QueryStyle,
    target: int,
) -> List[dict]:
    """Build LLM call batches for Multi-* types.

    Each batch corresponds to one parameter pair.
    """
    multiplied_target = target * GenerationConfig.GENERATION_MULTIPLIER
    n_per_pair = GenerationConfig.QUERIES_PER_PAIR

    # Determine which pairs to use for this type
    if query_type == QueryType.MULTI_CONDITIONAL:
        pairs = [p for p in MULTI_PAIRS if p["role_a"] == "condition"]
    elif query_type == QueryType.MULTI_INDEPENDENT:
        pairs = [p for p in MULTI_PAIRS if p["role_a"] == "independent"]
    else:
        pairs = list(MULTI_PAIRS)

    if not pairs:
        log.warning("No pairs available for %s", query_type.value)
        return []

    batches = []
    generated_count = 0
    pair_idx = 0
    while generated_count < multiplied_target:
        pair = pairs[pair_idx % len(pairs)]
        batches.append({
            "pair": pair,
            "n": n_per_pair,
            "query_type": query_type,
            "query_style": query_style,
        })
        generated_count += n_per_pair
        pair_idx += 1

    return batches


# ---------------------------------------------------------------------------
# Progress tracking (resume support)
# ---------------------------------------------------------------------------

_PROGRESS_FILE = Paths.OUTPUT_DIR / "candidates_progress.json"


def _load_progress() -> dict:
    if _PROGRESS_FILE.exists():
        return json.loads(_PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"completed_cells": [], "total_candidates": 0}


def _save_progress(progress: dict) -> None:
    _PROGRESS_FILE.write_text(
        json.dumps(progress, indent=2), encoding="utf-8"
    )


def _cell_key(qt: QueryType, qs: QueryStyle) -> str:
    return f"{qt.value}:{qs.value}"


# ---------------------------------------------------------------------------
# Core generation loop
# ---------------------------------------------------------------------------

def _process_single_cell(
    query_type: QueryType,
    query_style: QueryStyle,
    target: int,
    synonym_map: Dict[str, SynonymEntry],
    prompt_template: str,
    output_file: Path,
    dry_run: bool,
) -> int:
    """Generate candidates for a Single-* cell. Returns count of candidates."""
    batches = _build_single_batches(query_type, query_style, synonym_map, target)
    total_generated = 0

    for batch_idx, batch in enumerate(batches, start=1):
        param_info = _format_single_param_info(batch["params"])
        n = len(batch["params"])

        prompt = prompt_template.format(
            query_type=query_type.value,
            query_style=query_style.value,
            param_info=param_info,
            n=n,
        )

        results = _call_generation_llm(prompt, dry_run=dry_run)

        for item in results:
            candidate = _to_candidate(item, query_type, query_style)
            if candidate:
                append_jsonl(output_file, candidate)
                total_generated += 1

        log.info(
            "  batch %d/%d → %d candidates",
            batch_idx, len(batches), len(results),
        )
        if not dry_run:
            time.sleep(0.5)

    return total_generated


def _process_multi_cell(
    query_type: QueryType,
    query_style: QueryStyle,
    target: int,
    synonym_map: Dict[str, SynonymEntry],
    prompt_template: str,
    output_file: Path,
    dry_run: bool,
) -> int:
    """Generate candidates for a Multi-* cell. Returns count of candidates."""
    batches = _build_multi_batches(query_type, query_style, target)
    total_generated = 0

    for batch_idx, batch in enumerate(batches, start=1):
        try:
            param_info = _format_multi_param_info(batch["pair"], synonym_map)
        except KeyError as e:
            log.warning("Skipping pair — %s", e)
            continue

        prompt = prompt_template.format(
            query_type=query_type.value,
            query_style=query_style.value,
            param_info=param_info,
            n=batch["n"],
        )

        results = _call_generation_llm(prompt, dry_run=dry_run)

        for item in results:
            candidate = _to_candidate(item, query_type, query_style)
            if candidate:
                append_jsonl(output_file, candidate)
                total_generated += 1

        log.info(
            "  batch %d/%d (pair %s × %s) → %d candidates",
            batch_idx, len(batches),
            batch["pair"]["param_a"], batch["pair"]["param_b"],
            len(results),
        )
        if not dry_run:
            time.sleep(0.5)

    return total_generated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_candidate(
    raw: dict,
    query_type: QueryType,
    query_style: QueryStyle,
) -> Optional[QueryCandidate]:
    """Convert raw LLM output dict → QueryCandidate. Returns None on failure."""
    try:
        return QueryCandidate(
            query=raw["query"],
            required_parameters=raw.get("required_parameters", []),
            query_type=query_type,
            query_style=query_style,
            generation_notes=raw.get("generation_notes"),
        )
    except Exception as e:
        log.warning("Invalid candidate: %s — %s", e, raw)
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    dry_run: bool = False,
    cell_filter: Optional[str] = None,
) -> int:
    """Run Stage 2.

    Args:
        dry_run:     Skip LLM calls; emit placeholder candidates.
        cell_filter: Only process this cell, e.g. "Single-Direct:doctor".
                     None = process all cells in the batch plan.

    Returns:
        Total number of candidates written.
    """
    Paths.ensure_output_dir()
    output_file = Paths.CANDIDATES
    prompt_template = (Paths.PROMPTS_DIR / "query_gen.txt").read_text(
        encoding="utf-8"
    )

    # Load synonym map from Stage 1
    synonym_map = load_synonym_map(Paths.SYNONYM_MAP)
    log.info("Loaded synonym_map: %d param_keys", len(synonym_map))

    # Resume support
    progress = _load_progress()
    completed = set(progress["completed_cells"])

    # Consistency check: if no cells completed but candidates file has data,
    # the progress was likely reset/deleted — rename old file to avoid dupes.
    if not completed and output_file.exists() and output_file.stat().st_size > 0:
        backup = output_file.with_suffix(".jsonl.bak")
        log.warning(
            "Progress shows 0 completed cells but %s has data. "
            "Renaming to %s to avoid duplicates.",
            output_file.name, backup.name,
        )
        output_file.rename(backup)

    # Build cell list
    plan = GenerationConfig.BATCH_PLAN
    cells: List[Tuple[QueryType, QueryStyle, int]] = []
    for (qt, qs), target in plan.items():
        key = _cell_key(qt, qs)
        if cell_filter and key != cell_filter:
            continue
        if key in completed and not dry_run:
            log.info("Skipping completed cell: %s", key)
            continue
        cells.append((qt, qs, target))

    if not cells:
        log.info("No cells to process. Stage 2 complete (or all already done).")
        return 0

    log.info("Cells to process: %d", len(cells))

    grand_total = 0
    for qt, qs, target in cells:
        key = _cell_key(qt, qs)
        log.info("── %s ── (target=%d, ×%d oversample)", key, target,
                 GenerationConfig.GENERATION_MULTIPLIER)

        if qt in SINGLE_TYPES:
            count = _process_single_cell(
                qt, qs, target, synonym_map, prompt_template, output_file, dry_run,
            )
        elif qt in MULTI_TYPES:
            count = _process_multi_cell(
                qt, qs, target, synonym_map, prompt_template, output_file, dry_run,
            )
        else:
            log.warning("Unknown query_type %s — skipping", qt)
            continue

        grand_total += count
        log.info("  → %d candidates for %s", count, key)

        if not dry_run:
            progress["completed_cells"].append(key)
            progress["total_candidates"] += count
            _save_progress(progress)

    # Summary
    log.info("=" * 60)
    log.info("Stage 2 complete.")
    log.info("  Candidates this run  : %d", grand_total)
    log.info("  Total in progress    : %d", progress["total_candidates"])
    log.info("  Output file          : %s", output_file)

    return grand_total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 2 — Generate query candidates via LLM."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip LLM calls; emit placeholder candidates.",
    )
    parser.add_argument(
        "--cell", type=str, default=None,
        dest="cell_filter",
        help=(
            "Only process this cell, e.g. 'Single-Direct:doctor'. "
            "Default: all cells."
        ),
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, cell_filter=args.cell_filter)
