"""
Evaluation/Level1/stages/stage3_label.py

Stage 3: Ground Truth Auto-Labeling

Reads candidates.jsonl (Stage 2) and synonym_map.json (Stage 1), then
attaches a GroundTruth object to each candidate:

  1. **Validate** — confirm every required_parameter exists in the DB
     (synonym_map is the proxy — it was built from DB).
  2. **Build acceptable_alternatives** — find interchangeable param_keys
     under three conditions (LEVEL1_DATASET.md Section 2-3):
       ① Same physiological indicator
       ② Actually exists in VitalDB (verified via synonym_map)
       ③ Query does not specify the device
  3. **Assign category** — derived from param_source.
  4. **Set expected_behavior** — always 'retrieve' for Stage 2 candidates
     (adversarial/clarify/not_found are generated in Stage 5).

Output: labeled.jsonl  (one QueryCandidate JSON object per line, with
                        ground_truth populated)

No LLM calls — purely rule-based labeling.

Usage:
    python -m Evaluation.Level1.stages.stage3_label
    python -m Evaluation.Level1.stages.stage3_label --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.Level1.config import MANUAL_EQUIVALENCES, Paths
from Evaluation.Level1.models import (
    ExpectedBehavior,
    GroundTruth,
    QueryCandidate,
    QueryType,
    SynonymEntry,
)
from Evaluation.Level1.utils import append_jsonl, load_synonym_map

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage3] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load helpers
# ---------------------------------------------------------------------------

def load_candidates(path: Path) -> List[QueryCandidate]:
    if not path.exists():
        raise FileNotFoundError(f"candidates.jsonl not found at {path}")
    candidates = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            candidates.append(QueryCandidate(**json.loads(line)))
        except Exception as e:
            log.warning("Skipping invalid line %d: %s", line_no, e)
    return candidates


# ---------------------------------------------------------------------------
# Physiology grouping — find interchangeable param_keys
# ---------------------------------------------------------------------------

def _normalize_track_description(desc: str) -> str:
    """Remove device qualifiers to get the core physiological description."""
    desc = re.sub(r"\s*\(from ventilator\)", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s*\(PEEP\)", "", desc, flags=re.IGNORECASE)
    return desc.strip().lower()


def _load_track_descriptions(csv_path: Path) -> Dict[str, str]:
    """Load track_names.csv and return {param_key: normalized_description}.

    Falls back to an empty dict if the file is missing so the pipeline
    still works (just without description-based matching).
    """
    if not csv_path.exists():
        log.warning("track_names.csv not found at %s — skipping description-based matching", csv_path)
        return {}
    import csv
    desc_map: Dict[str, str] = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pk = row.get("Parameter", "").strip()
            desc = row.get("Description", "").strip()
            if pk and desc:
                desc_map[pk] = _normalize_track_description(desc)
    return desc_map


def build_alternatives_map(
    synonym_map: Dict[str, SynonymEntry],
    track_names_csv: Optional[Path] = None,
    manual_equivalences: Optional[List[tuple]] = None,
) -> Dict[str, Set[str]]:
    """For each param_key, find all interchangeable param_keys.

    Three sources combined (priority order):
      A) track_names.csv normalized description match — authoritative
      B) Exact signal-suffix match  (e.g., Solar8000/HR ↔ CardioQ/HR)
      C) MANUAL_EQUIVALENCES for pairs that differ in wording

    Only param_keys present in synonym_map (i.e., verified in DB) are
    included, satisfying condition ② (exists in VitalDB).
    """
    valid_keys = set(synonym_map.keys())

    # ── Source A: track_names.csv description grouping ──
    desc_groups: Dict[str, Set[str]] = defaultdict(set)
    desc_map: Dict[str, str] = {}
    if track_names_csv:
        desc_map = _load_track_descriptions(track_names_csv)
        for pk, norm_desc in desc_map.items():
            if pk in valid_keys:
                desc_groups[norm_desc].add(pk)

    # ── Source B: exact signal-suffix match ──
    signal_groups: Dict[str, Set[str]] = defaultdict(set)
    for pk in valid_keys:
        signal = pk.split("/", 1)[1] if "/" in pk else pk
        signal_groups[signal].add(pk)

    # ── Source C: manual equivalences ──
    manual_map: Dict[str, Set[str]] = defaultdict(set)
    for a, b in (manual_equivalences or []):
        if a in valid_keys and b in valid_keys:
            manual_map[a].add(b)
            manual_map[b].add(a)

    # ── Merge all sources ──
    alt_map: Dict[str, Set[str]] = {}
    for pk in valid_keys:
        alts: Set[str] = set()

        norm_desc = desc_map.get(pk)
        if norm_desc:
            alts.update(desc_groups.get(norm_desc, set()))

        signal = pk.split("/", 1)[1] if "/" in pk else pk
        alts.update(signal_groups.get(signal, set()))

        alts.update(manual_map.get(pk, set()))

        alts.discard(pk)
        alt_map[pk] = alts

    return alt_map


# ---------------------------------------------------------------------------
# Device-specificity check  (condition ③)
# ---------------------------------------------------------------------------

def is_device_specified(query: str, param_key: str) -> bool:
    """Return True if the query mentions the device for this param_key.

    Uses word-boundary matching to avoid false positives on short device
    names like 'BIS' (e.g. won't match inside 'analysis').
    """
    device = param_key.split("/")[0] if "/" in param_key else ""
    if not device:
        return False
    if re.search(r"\b" + re.escape(device) + r"\b", query, re.IGNORECASE):
        return True
    if re.search(r"\b" + re.escape(param_key) + r"\b", query, re.IGNORECASE):
        return True
    return False


# ---------------------------------------------------------------------------
# Core labeling logic
# ---------------------------------------------------------------------------

def label_candidate(
    candidate: QueryCandidate,
    synonym_map: Dict[str, SynonymEntry],
    alt_map: Dict[str, Set[str]],
) -> Optional[QueryCandidate]:
    """Attach GroundTruth to a candidate.

    Returns None if the candidate is invalid (e.g., hallucinated params).
    """
    # ── Step 1: validate required_parameters exist ──
    valid_params: List[str] = []
    invalid_params: List[str] = []
    for pk in candidate.required_parameters:
        if pk in synonym_map:
            valid_params.append(pk)
        else:
            invalid_params.append(pk)

    if invalid_params:
        log.debug(
            "Dropping candidate — hallucinated params %s: %s",
            invalid_params, candidate.query[:80],
        )
        return None

    if not valid_params:
        log.debug("Dropping candidate — empty required_parameters: %s",
                  candidate.query[:80])
        return None

    # ── Step 2: build acceptable_alternatives ──
    alternatives: Dict[str, List[str]] = {}
    for pk in valid_params:
        # Condition ③: skip if device is specified in query
        if candidate.query_type == QueryType.SINGLE_DIRECT:
            # Single-Direct always includes raw param_key → device is specified
            continue
        if is_device_specified(candidate.query, pk):
            continue

        # Conditions ① + ②: same physiology + exists in DB
        alts = alt_map.get(pk, set())
        if alts:
            alternatives[pk] = sorted(alts)

    # ── Step 3: build retrieval_notes ──
    notes_parts: List[str] = []
    if alternatives:
        n_alts = sum(len(v) for v in alternatives.values())
        notes_parts.append(f"{n_alts} acceptable alternative(s) found")
    if candidate.generation_notes:
        notes_parts.append(candidate.generation_notes)
    retrieval_notes = "; ".join(notes_parts) if notes_parts else None

    # ── Step 4: assemble GroundTruth ──
    gt = GroundTruth(
        required_parameters=valid_params,
        acceptable_alternatives=alternatives,
        expected_behavior=ExpectedBehavior.RETRIEVE,
        retrieval_notes=retrieval_notes,
    )

    candidate.ground_truth = gt
    return candidate



# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, limit: Optional[int] = None) -> dict:
    """Run Stage 3.

    Returns:
        Summary dict with counts.
    """
    Paths.ensure_output_dir()
    output_file = Paths.LABELED

    # Load inputs
    synonym_map = load_synonym_map(Paths.SYNONYM_MAP)
    log.info("Loaded synonym_map: %d param_keys", len(synonym_map))

    candidates = load_candidates(Paths.CANDIDATES)
    log.info("Loaded candidates: %d", len(candidates))

    if limit is not None:
        candidates = candidates[:limit]
        log.info("Limiting to first %d candidates", limit)

    # Build physiology-based alternatives map using track_names.csv
    alt_map = build_alternatives_map(
        synonym_map,
        track_names_csv=Paths.TRACK_NAMES_CSV,
        manual_equivalences=MANUAL_EQUIVALENCES,
    )
    n_with_alts = sum(1 for v in alt_map.values() if v)
    log.info(
        "Alternatives map: %d params, %d have alternatives (track_names.csv + manual)",
        len(alt_map), n_with_alts,
    )

    # Process candidates
    # Always create (or truncate) so downstream stages can read even if empty
    output_file.write_text("", encoding="utf-8")

    stats = {
        "total": len(candidates),
        "labeled": 0,
        "dropped_hallucinated": 0,
        "dropped_empty": 0,
        "with_alternatives": 0,
    }

    for idx, cand in enumerate(candidates, start=1):
        result = label_candidate(cand, synonym_map, alt_map)
        if result is None:
            if not cand.required_parameters:
                stats["dropped_empty"] += 1
            else:
                stats["dropped_hallucinated"] += 1
            continue

        stats["labeled"] += 1
        if result.ground_truth and result.ground_truth.acceptable_alternatives:
            stats["with_alternatives"] += 1

        if not dry_run:
            append_jsonl(output_file, result)

        if idx % 100 == 0:
            log.info("  processed %d / %d ...", idx, len(candidates))

    # Summary
    log.info("=" * 60)
    log.info("Stage 3 complete.")
    log.info("  Total candidates     : %d", stats["total"])
    log.info("  Labeled (kept)       : %d", stats["labeled"])
    log.info("  Dropped (hallucinated): %d", stats["dropped_hallucinated"])
    log.info("  Dropped (empty)      : %d", stats["dropped_empty"])
    log.info("  With alternatives    : %d", stats["with_alternatives"])
    if not dry_run:
        log.info("  Output file          : %s", output_file)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 3 — Ground truth auto-labeling (no LLM)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and compute stats without writing output.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process only first N candidates.",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, limit=args.limit)
