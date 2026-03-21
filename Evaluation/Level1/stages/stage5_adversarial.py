"""
Evaluation/Level1/stages/stage5_adversarial.py

Stage 5: Adversarial Case Generation

Generates three types of adversarial cases and merges them with the
quality-filtered normal cases from Stage 4:

  Ambiguous  — LLM strips parameter hints from source queries → "clarify"
  Impossible — LLM creates queries for signals absent from the DB → "not_found"
  Confusing  — LLM creates queries where the same indicator spans
               multiple devices, without specifying which → "clarify"

Inputs:
  - filtered.jsonl   (Stage 4 output — source queries for Ambiguous)
  - synonym_map.json (Stage 1 output — for confusing groups)

Output:
  - with_adversarial.jsonl  (filtered cases + adversarial cases)

Usage:
    python -m Evaluation.Level1.stages.stage5_adversarial
    python -m Evaluation.Level1.stages.stage5_adversarial --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.Level1.config import (
    AdversarialConfig,
    GenerationConfig,
    Paths,
)
from Evaluation.Level1.models import (
    ExpectedBehavior,
    GroundTruth,
    QueryCandidate,
    QueryStyle,
    QueryType,
    SynonymEntry,
)
from Evaluation.Level1.utils import append_jsonl, load_synonym_map

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage5] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Plausible intraoperative signals that do NOT exist in VitalDB
UNAVAILABLE_SIGNALS = [
    "continuous blood glucose waveform",
    "intracranial pressure (ICP)",
    "intra-abdominal pressure",
    "jugular venous oxygen saturation (SjvO2)",
    "transcutaneous CO2 (TcPCO2)",
    "cerebral blood flow velocity",
    "esophageal Doppler cardiac output",
    "skin conductance / galvanic skin response",
    "bladder pressure",
    "core body temperature waveform",
    "near-infrared spectroscopy (NIRS) regional saturation",
    "exhaled nitric oxide (FeNO)",
    "pulse pressure variation (PPV) waveform",
    "stroke volume variation (SVV) waveform",
]


# ---------------------------------------------------------------------------
# Load helpers
# ---------------------------------------------------------------------------

def _load_filtered(path: Path) -> List[QueryCandidate]:
    if not path.exists():
        raise FileNotFoundError(f"filtered.jsonl not found at {path}")
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(QueryCandidate(**json.loads(line)))
        except Exception as e:
            log.warning("Skipping invalid line: %s", e)
    return items


# ---------------------------------------------------------------------------
# Confusing groups builder
# ---------------------------------------------------------------------------

def build_confusing_groups(
    synonym_map: Dict[str, SynonymEntry],
) -> List[Dict]:
    """Find parameters where the same physiological indicator has multiple
    param_keys (different devices).

    Returns list of:
      {"semantic_name": str, "param_keys": [str, ...]}
    """
    by_semantic: Dict[str, Set[str]] = defaultdict(set)
    for pk, entry in synonym_map.items():
        if entry.semantic_name:
            key = entry.semantic_name.strip().lower()
            by_semantic[key].add(pk)

    # Also group by signal suffix for cases where semantic_name differs
    by_signal: Dict[str, Set[str]] = defaultdict(set)
    for pk in synonym_map:
        signal = pk.split("/", 1)[1] if "/" in pk else pk
        by_signal[signal].add(pk)

    # Merge both groupings
    merged: Dict[str, Set[str]] = {}
    for name, pks in by_semantic.items():
        if len(pks) > 1:
            merged[name] = pks
    for signal, pks in by_signal.items():
        if len(pks) > 1:
            label = f"signal:{signal}"
            if label not in merged:
                merged[label] = pks

    groups = []
    for name, pks in merged.items():
        groups.append({
            "semantic_name": name,
            "param_keys": sorted(pks),
        })

    groups.sort(key=lambda g: len(g["param_keys"]), reverse=True)
    return groups


def _format_confusing_groups(groups: List[Dict]) -> str:
    """Format confusing groups for prompt injection."""
    if not groups:
        return "  (no confusing groups available)"
    lines = []
    for g in groups[:10]:
        pks = ", ".join(g["param_keys"])
        lines.append(f"  - {g['semantic_name']}: [{pks}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_adversarial_llm(
    prompt: str,
    dry_run: bool = False,
) -> List[dict]:
    """Call LLM for adversarial generation. Returns list of raw dicts."""
    if dry_run:
        return [
            {
                "query": "[DRY-RUN] adversarial placeholder",
                "adversarial_type": "ambiguous",
                "expected_behavior": "clarify",
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
                        "You generate adversarial test data for a medical AI system. "
                        "Output a JSON array only, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=GenerationConfig.GENERATION_TEMPERATURE,
            max_tokens=GenerationConfig.GENERATION_MAX_TOKENS,
        )
        raw = response.choices[0].message.content
        text = re.sub(r"```json\s*", "", raw, flags=re.IGNORECASE)
        text = re.sub(r"```", "", text).strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = [parsed]
        return parsed
    except Exception as e:
        log.warning("Adversarial LLM call failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Per-type generators
# ---------------------------------------------------------------------------

def _generate_ambiguous(
    source_cases: List[QueryCandidate],
    prompt_template: str,
    target: int,
    dry_run: bool,
) -> List[QueryCandidate]:
    """Generate ambiguous adversarial cases by stripping hints from source queries."""
    n_generate = target * AdversarialConfig.GENERATION_MULTIPLIER
    styles = list(QueryStyle)

    # Sample source queries for context
    sampled = random.sample(source_cases, min(len(source_cases), 10))
    source_str = json.dumps(
        [c.query for c in sampled], ensure_ascii=False, indent=2
    )

    results = []
    for style in styles:
        n = n_generate // len(styles) + (1 if n_generate % len(styles) else 0)
        prompt = prompt_template.format(
            n=n,
            adversarial_type="ambiguous",
            source_queries=source_str,
            unavailable_signals="(not applicable for ambiguous type)",
            confusing_groups="(not applicable for ambiguous type)",
            query_style=style.value,
        )
        raw_items = _call_adversarial_llm(prompt, dry_run=dry_run)
        for item in raw_items:
            cand = _to_adversarial_candidate(item, "ambiguous", style=style)
            if cand:
                results.append(cand)
        if not dry_run:
            time.sleep(0.5)

    return results[:n_generate]


def _generate_impossible(
    prompt_template: str,
    target: int,
    dry_run: bool,
) -> List[QueryCandidate]:
    """Generate impossible adversarial cases for signals not in DB."""
    n_generate = target * AdversarialConfig.GENERATION_MULTIPLIER
    unavail_str = ", ".join(UNAVAILABLE_SIGNALS)
    styles = list(QueryStyle)

    results = []
    for style in styles:
        n = n_generate // len(styles) + (1 if n_generate % len(styles) else 0)
        prompt = prompt_template.format(
            n=n,
            adversarial_type="impossible",
            source_queries="(not applicable for impossible type)",
            unavailable_signals=unavail_str,
            confusing_groups="(not applicable for impossible type)",
            query_style=style.value,
        )
        raw_items = _call_adversarial_llm(prompt, dry_run=dry_run)
        for item in raw_items:
            cand = _to_adversarial_candidate(item, "impossible", style=style)
            if cand:
                results.append(cand)
        if not dry_run:
            time.sleep(0.5)

    return results[:n_generate]


def _generate_confusing(
    confusing_groups: List[Dict],
    prompt_template: str,
    target: int,
    dry_run: bool,
) -> List[QueryCandidate]:
    """Generate confusing adversarial cases using multi-device param groups."""
    n_generate = target * AdversarialConfig.GENERATION_MULTIPLIER
    groups_str = _format_confusing_groups(confusing_groups)
    styles = list(QueryStyle)

    if not confusing_groups:
        log.warning("No confusing groups found — skipping confusing generation.")
        return []

    results = []
    for style in styles:
        n = n_generate // len(styles) + (1 if n_generate % len(styles) else 0)
        prompt = prompt_template.format(
            n=n,
            adversarial_type="confusing",
            source_queries="(not applicable for confusing type)",
            unavailable_signals="(not applicable for confusing type)",
            confusing_groups=groups_str,
            query_style=style.value,
        )
        raw_items = _call_adversarial_llm(prompt, dry_run=dry_run)
        for item in raw_items:
            cand = _to_adversarial_candidate(item, "confusing", style=style)
            if cand:
                results.append(cand)
        if not dry_run:
            time.sleep(0.5)

    return results[:n_generate]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_adversarial_candidate(
    raw: dict,
    expected_type: str,
    style: QueryStyle = QueryStyle.DOCTOR,
) -> Optional[QueryCandidate]:
    """Convert raw LLM output to QueryCandidate with adversarial ground truth."""
    try:
        adv_type = raw.get("adversarial_type", expected_type)
        if adv_type in ("ambiguous", "confusing"):
            behavior = ExpectedBehavior.CLARIFY
        elif adv_type == "impossible":
            behavior = ExpectedBehavior.NOT_FOUND
        else:
            behavior = ExpectedBehavior.CLARIFY

        gt = GroundTruth(
            required_parameters=[],
            acceptable_alternatives={},
            expected_behavior=behavior,
            retrieval_notes=raw.get("generation_notes"),
        )

        return QueryCandidate(
            query=raw["query"],
            required_parameters=[],
            query_type=QueryType.ADVERSARIAL,
            query_style=style,
            generation_notes=raw.get("generation_notes"),
            ground_truth=gt,
        )
    except Exception as e:
        log.warning("Invalid adversarial candidate: %s — %s", e, raw)
        return None


def _select_best(
    candidates: List[QueryCandidate],
    target: int,
) -> List[QueryCandidate]:
    """Select up to `target` candidates, preferring diverse queries.

    Simple strategy: deduplicate exact matches, then take first N.
    """
    seen_queries: set = set()
    unique = []
    for c in candidates:
        q_norm = c.query.strip().lower()
        if q_norm not in seen_queries:
            seen_queries.add(q_norm)
            unique.append(c)
    return unique[:target]



# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> dict:
    """Run Stage 5.

    Returns:
        Stats dict with counts per adversarial type.
    """
    Paths.ensure_output_dir()
    output_file = Paths.WITH_ADVERSARIAL

    # Load inputs
    filtered_cases = _load_filtered(Paths.FILTERED)
    log.info("Loaded filtered cases: %d", len(filtered_cases))

    synonym_map = load_synonym_map(Paths.SYNONYM_MAP)
    log.info("Loaded synonym_map: %d param_keys", len(synonym_map))

    prompt_template = (Paths.PROMPTS_DIR / "adversarial_gen.txt").read_text(
        encoding="utf-8"
    )

    # Build confusing groups from synonym_map
    confusing_groups = build_confusing_groups(synonym_map)
    log.info("Confusing groups found: %d", len(confusing_groups))
    for g in confusing_groups[:5]:
        log.info("  %s → %s", g["semantic_name"], g["param_keys"])

    # ── Generate each adversarial type ──
    log.info("Generating ambiguous cases (target=%d)...",
             AdversarialConfig.TARGET_AMBIGUOUS)
    ambiguous_raw = _generate_ambiguous(
        filtered_cases, prompt_template,
        AdversarialConfig.TARGET_AMBIGUOUS, dry_run,
    )
    ambiguous = _select_best(ambiguous_raw, AdversarialConfig.TARGET_AMBIGUOUS)
    log.info("  generated %d → selected %d", len(ambiguous_raw), len(ambiguous))

    log.info("Generating impossible cases (target=%d)...",
             AdversarialConfig.TARGET_IMPOSSIBLE)
    impossible_raw = _generate_impossible(
        prompt_template, AdversarialConfig.TARGET_IMPOSSIBLE, dry_run,
    )
    impossible = _select_best(impossible_raw, AdversarialConfig.TARGET_IMPOSSIBLE)
    log.info("  generated %d → selected %d", len(impossible_raw), len(impossible))

    log.info("Generating confusing cases (target=%d)...",
             AdversarialConfig.TARGET_CONFUSING)
    confusing_raw = _generate_confusing(
        confusing_groups, prompt_template,
        AdversarialConfig.TARGET_CONFUSING, dry_run,
    )
    confusing = _select_best(confusing_raw, AdversarialConfig.TARGET_CONFUSING)
    log.info("  generated %d → selected %d", len(confusing_raw), len(confusing))

    all_adversarial = ambiguous + impossible + confusing

    # ── Merge: filtered cases + adversarial ──
    # Always create (or truncate) so downstream stages can read even if empty
    output_file.write_text("", encoding="utf-8")

    for c in filtered_cases:
        append_jsonl(output_file, c)
    for c in all_adversarial:
        append_jsonl(output_file, c)

    stats = {
        "filtered_cases": len(filtered_cases),
        "ambiguous": len(ambiguous),
        "impossible": len(impossible),
        "confusing": len(confusing),
        "total_adversarial": len(all_adversarial),
        "total_merged": len(filtered_cases) + len(all_adversarial),
    }

    log.info("=" * 60)
    log.info("Stage 5 complete.")
    log.info("  Filtered (normal)    : %d", stats["filtered_cases"])
    log.info("  Adversarial total    : %d", stats["total_adversarial"])
    log.info("    - ambiguous        : %d", stats["ambiguous"])
    log.info("    - impossible       : %d", stats["impossible"])
    log.info("    - confusing        : %d", stats["confusing"])
    log.info("  Merged total         : %d", stats["total_merged"])
    if not dry_run:
        log.info("  Output file          : %s", output_file)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 5 — Adversarial case generation."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip LLM calls; emit placeholder adversarial cases.",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run)
