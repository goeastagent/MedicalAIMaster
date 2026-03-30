"""
Evaluation/SemanticValueAccuracy/stages/stage2_generate.py

Stage 2: Semantic Query Generation (LLM)

Reads metadata_context.json (Stage 1 output) and generates query candidates
for 5 SVA categories using category-specific LLM prompts.

Output: sva_candidates.jsonl  (one JSON object per line)

Resumable: tracks per-category progress so partial runs can be continued.

Usage (standalone):
    python -m Evaluation.SemanticValueAccuracy.stages.stage2_generate
    python -m Evaluation.SemanticValueAccuracy.stages.stage2_generate --dry-run
    python -m Evaluation.SemanticValueAccuracy.stages.stage2_generate --category semantic_resolution
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.SemanticValueAccuracy.config import (
    CategoryTargets,
    LLMConfig,
    Paths,
)
from Evaluation.SemanticValueAccuracy.models import QueryCategory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage2] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Category → prompt file mapping
# ---------------------------------------------------------------------------

CATEGORY_PROMPT_FILES: Dict[str, str] = {
    "semantic_resolution": "semantic_query_gen.txt",
    "cross_device": "cross_device_query_gen.txt",
    "cohort_signal_join": "cohort_signal_query_gen.txt",
    "ontology_based": "ontology_query_gen.txt",
    "adversarial_semantic": "adversarial_semantic_gen.txt",
}


# ---------------------------------------------------------------------------
# Context formatters
# ---------------------------------------------------------------------------

def _format_params_context(metadata: Dict) -> str:
    """Format track_names_ref for LLM prompt (hide raw param names from query)."""
    ref = metadata.get("track_names_ref", {})
    lines = []
    for param, info in sorted(ref.items()):
        lines.append(
            f"  {param}: Description=\"{info['description']}\", "
            f"Unit=\"{info['unit']}\", Type={info['type_hz']}, "
            f"Device={info['device']}"
        )
    return "\n".join(lines)


def _format_cross_device_pairs(metadata: Dict) -> str:
    """Format cross-device pairs for prompt context."""
    pairs = metadata.get("cross_device_pairs", [])
    lines = []
    for p in pairs:
        lines.append(
            f"  Concept: {p['concept']} → Sources: {p['sources']} "
            f"(Devices: {p['devices']})"
        )
    return "\n".join(lines)


def _format_device_groups(metadata: Dict) -> str:
    """Format device groups for prompt context."""
    groups = metadata.get("device_groups", {})
    lines = []
    for dev, params in sorted(groups.items()):
        lines.append(f"  {dev}: {params}")
    return "\n".join(lines)


def _format_cohort_data(metadata: Dict) -> str:
    """Format cohort data as readable text."""
    rows = metadata.get("cohort_data", [])
    return json.dumps(rows, indent=2, ensure_ascii=False)


def _format_cohort_schema(metadata: Dict) -> str:
    """Format cohort schema."""
    schema = metadata.get("cohort_schema", {})
    return json.dumps(schema, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(
    category: str,
    metadata: Dict,
    n: int,
) -> str:
    """Load the prompt template and fill in context."""
    prompt_file = Paths.PROMPTS_DIR / CATEGORY_PROMPT_FILES[category]
    template = prompt_file.read_text(encoding="utf-8")

    params_ctx = _format_params_context(metadata)
    xdev = _format_cross_device_pairs(metadata)
    dev_groups = _format_device_groups(metadata)
    cohort = _format_cohort_data(metadata)
    cohort_schema = _format_cohort_schema(metadata)

    # Prefer case IDs stored by Stage 1 in metadata_context.json; fall back to
    # an empty string so that the prompt can still be rendered if the key is absent.
    stored_ids: List[str] = metadata.get("target_case_ids", [])
    case_ids = ", ".join(stored_ids) if stored_ids else "(unknown — re-run stage 1)"

    prompt = template.format(
        parameters_context=params_ctx,
        cross_device_pairs=xdev,
        device_groups=dev_groups,
        cohort_data=cohort,
        cohort_schema=cohort_schema,
        case_ids=case_ids,
        n=n,
    )
    return prompt


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, dry_run: bool = False) -> List[Dict]:
    """Call OpenAI and return parsed JSON array."""
    if dry_run:
        return [{
            "query": "[DRY-RUN] placeholder semantic query for case 0001",
            "query_style": "clinical",
            "answer_type": "number",
            "resolution_target": {
                "equivalence_group": ["Solar8000/HR"],
                "distractors": [],
                "resolution_rationale": "dry-run placeholder",
            },
        }]

    try:
        from openai import OpenAI

        _REASONING_PREFIXES = ("o1", "o3", "gpt-5")
        _model = LLMConfig.GENERATION_MODEL
        _is_reasoning = any(_model.lower().startswith(p) for p in _REASONING_PREFIXES)
        _token_param = (
            {"max_completion_tokens": LLMConfig.GENERATION_MAX_TOKENS}
            if _is_reasoning
            else {"max_tokens": LLMConfig.GENERATION_MAX_TOKENS}
        )

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate evaluation test data for a medical AI benchmark. "
                        "Output a JSON array only, no markdown fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=LLMConfig.GENERATION_TEMPERATURE,
            **_token_param,
        )
        raw = response.choices[0].message.content

        text = re.sub(r"```json\s*", "", raw, flags=re.IGNORECASE)
        text = re.sub(r"```", "", text).strip()

        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed

    except Exception as e:
        log.error("LLM call failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------

def _append_jsonl(path: Path, obj: Dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

_PROGRESS_FILE = Paths.OUTPUT_DIR / "stage2_progress.json"


def _load_progress() -> Dict:
    if _PROGRESS_FILE.exists():
        return json.loads(_PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"completed_categories": {}, "total_candidates": 0}


def _save_progress(progress: Dict) -> None:
    _PROGRESS_FILE.write_text(
        json.dumps(progress, indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------

def _generate_category(
    category: str,
    metadata: Dict,
    target: int,
    output_file: Path,
    id_prefix: str,
    id_offset: int,
    dry_run: bool,
) -> int:
    """Generate candidates for one category. Returns count generated."""
    batch_size = LLMConfig.BATCH_SIZE
    total_gen = target * CategoryTargets.OVERSAMPLING_MULTIPLIER
    generated = 0
    batch_idx = 0
    consecutive_failures = 0
    MAX_CONSECUTIVE_FAILURES = 5

    while generated < total_gen:
        n = min(batch_size, total_gen - generated)
        prompt = build_prompt(category, metadata, n)
        results = _call_llm(prompt, dry_run=dry_run)

        for i, item in enumerate(results):
            case_num = id_offset + generated + i + 1
            case_id = f"{id_prefix}_{case_num:03d}"

            candidate = {
                "id": case_id,
                "query_category": category,
                "query": item.get("query", ""),
                "query_style": item.get("query_style", ""),
                "answer_type": item.get("answer_type", "number"),
                "resolution_target": item.get("resolution_target", {}),
                "generation_notes": item.get("generation_notes"),
            }
            _append_jsonl(output_file, candidate)

        batch_generated = len(results)
        generated += batch_generated
        batch_idx += 1

        if batch_generated == 0:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log.error(
                    "  [%s] %d consecutive empty batches — aborting category to avoid infinite loop.",
                    category, consecutive_failures,
                )
                break
        else:
            consecutive_failures = 0

        log.info(
            "  [%s] batch %d → %d candidates (total: %d / %d)",
            category, batch_idx, batch_generated, generated, total_gen,
        )

        if not dry_run and batch_generated > 0:
            time.sleep(1.0)

    return generated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    dry_run: bool = False,
    category_filter: Optional[str] = None,
    output_file: Optional[Path] = None,
    metadata_context_path: Optional[Path] = None,
) -> int:
    """Execute Stage 2.

    Args:
        dry_run:               Skip LLM calls.
        category_filter:       Only process this category.
        output_file:           Custom path for the candidates JSONL file.
                               Defaults to Paths.CANDIDATES (sva_candidates.jsonl).
        metadata_context_path: Custom path for the Stage 1 metadata JSON.
                               Defaults to Paths.METADATA_CONTEXT.
    """
    Paths.ensure_output_dir()
    if output_file is None:
        output_file = Paths.CANDIDATES
    if metadata_context_path is None:
        metadata_context_path = Paths.METADATA_CONTEXT

    # Load metadata context from Stage 1
    if not metadata_context_path.exists():
        raise FileNotFoundError(
            f"Stage 1 output not found: {metadata_context_path}. "
            "Run Stage 1 first."
        )
    metadata = json.loads(metadata_context_path.read_text(encoding="utf-8"))
    log.info(
        "Loaded metadata: %d params, %d xdev pairs, %d cohort rows",
        len(metadata.get("track_names_ref", {})),
        len(metadata.get("cross_device_pairs", [])),
        len(metadata.get("cohort_data", [])),
    )

    # Resume support (only applies to the default output file; per-run files always start fresh)
    progress = _load_progress() if output_file == Paths.CANDIDATES else {"completed_categories": {}, "total_candidates": 0}
    completed = progress["completed_categories"]

    # Reset output if progress is empty but file exists
    if not completed and output_file.exists() and output_file.stat().st_size > 0:
        backup = output_file.with_suffix(".jsonl.bak")
        log.warning("Resetting: renaming %s → %s", output_file.name, backup.name)
        output_file.rename(backup)

    grand_total = 0
    id_offset = 0

    for category, target in CategoryTargets.TARGETS.items():
        if category_filter and category != category_filter:
            id_offset += target * CategoryTargets.OVERSAMPLING_MULTIPLIER
            continue

        if category in completed and not dry_run:
            log.info("Skipping completed category: %s (%d)", category, completed[category])
            id_offset += completed[category]
            grand_total += completed[category]
            continue

        id_prefix = CategoryTargets.ID_PREFIXES[category]
        log.info(
            "━━ %s ━━ (target=%d, oversample=%dx → generate %d)",
            category, target, CategoryTargets.OVERSAMPLING_MULTIPLIER,
            target * CategoryTargets.OVERSAMPLING_MULTIPLIER,
        )

        count = _generate_category(
            category=category,
            metadata=metadata,
            target=target,
            output_file=output_file,
            id_prefix=id_prefix,
            id_offset=id_offset,
            dry_run=dry_run,
        )

        grand_total += count
        id_offset += count

        if not dry_run:
            progress["completed_categories"][category] = count
            progress["total_candidates"] = grand_total
            _save_progress(progress)

        log.info("  → %s: %d candidates generated", category, count)

    # Summary
    total_in_file = _count_jsonl(output_file)
    log.info("=" * 60)
    log.info("Stage 2 — Semantic Query Generation complete")
    log.info("  Generated this run    : %d", grand_total)
    log.info("  Total in candidates   : %d", total_in_file)
    log.info("  Output file           : %s", output_file)
    log.info("=" * 60)

    return grand_total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 2 — Generate SVA query candidates via LLM."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip LLM calls; emit placeholder candidates.",
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Only process this category (e.g., 'semantic_resolution').",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, category_filter=args.category)
