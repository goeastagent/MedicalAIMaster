"""
Evaluation/Level1/stages/stage4_filter.py

Stage 4: Quality Filtering (4 sequential filters)

Reads labeled.jsonl (Stage 3) and applies four filters in order from
cheapest to most expensive, so fewer candidates reach the costly steps:

  Filter 1 — param_key exposure check    (regex, free)
  Filter 2 — per-parameter coverage cap  (counter, free)
  Filter 3 — semantic deduplication      (embedding API)
  Filter 4 — LLM medical validity check  (LLM API)

Only candidates that pass ALL four filters are written to filtered.jsonl.

Usage:
    python -m Evaluation.Level1.stages.stage4_filter
    python -m Evaluation.Level1.stages.stage4_filter --dry-run
    python -m Evaluation.Level1.stages.stage4_filter --skip-llm
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.Level1.config import FilterConfig, Paths
from Evaluation.Level1.models import QueryCandidate, QueryType
from Evaluation.Level1.utils import append_jsonl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage4] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load helpers
# ---------------------------------------------------------------------------

def _load_labeled(path: Path) -> List[QueryCandidate]:
    if not path.exists():
        raise FileNotFoundError(f"labeled.jsonl not found at {path}")
    items = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            items.append(QueryCandidate(**json.loads(line)))
        except Exception as e:
            log.warning("Skipping invalid line %d: %s", line_no, e)
    return items


# ═══════════════════════════════════════════════════════════════════════════
# Filter 1: param_key exposure check
# ═══════════════════════════════════════════════════════════════════════════

_PARAM_KEY_RE = re.compile(FilterConfig.PARAM_KEY_PATTERN)


def filter_param_exposure(candidate: QueryCandidate) -> bool:
    """Return True if the candidate passes (no unwanted param_key leak).

    Single-Direct queries are allowed to contain raw param_keys.
    All other types must NOT expose the Device/Signal format.
    """
    if candidate.query_type == QueryType.SINGLE_DIRECT:
        return True
    return not _PARAM_KEY_RE.search(candidate.query)


# ═══════════════════════════════════════════════════════════════════════════
# Filter 2: per-parameter coverage cap
# ═══════════════════════════════════════════════════════════════════════════

def filter_coverage(
    candidate: QueryCandidate,
    counter: Counter,
) -> bool:
    """Return True if accepting this candidate won't exceed the per-param cap.

    Checks each required_parameter; if ANY would exceed the cap, reject.
    Does NOT update the counter — caller updates after acceptance.
    """
    if candidate.ground_truth is None:
        return False
    for pk in candidate.ground_truth.required_parameters:
        if counter[pk] >= FilterConfig.MAX_CASES_PER_PARAM:
            return False
    return True


def _update_coverage(candidate: QueryCandidate, counter: Counter) -> None:
    """Increment counters for all required_parameters."""
    if candidate.ground_truth:
        for pk in candidate.ground_truth.required_parameters:
            counter[pk] += 1


# ═══════════════════════════════════════════════════════════════════════════
# Filter 3: semantic deduplication (embedding-based)
# ═══════════════════════════════════════════════════════════════════════════

class EmbeddingDeduplicator:
    """Tracks accepted query embeddings and rejects near-duplicates."""

    def __init__(self, threshold: float = FilterConfig.DEDUP_THRESHOLD):
        self.threshold = threshold
        self._embeddings: List[np.ndarray] = []
        self._client = None

    def _get_client(self):
        if self._client is None:
            import os
            from openai import OpenAI
            self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._client

    def _embed(self, text: str) -> np.ndarray:
        resp = self._get_client().embeddings.create(
            model=FilterConfig.EMBEDDING_MODEL,
            input=text,
        )
        vec = np.array(resp.data[0].embedding, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def check_and_accept(self, query: str) -> bool:
        """Return True (pass) if not duplicate, and auto-register if passed."""
        if not self._embeddings:
            emb = self._embed(query)
            self._embeddings.append(emb)
            return True
        emb = self._embed(query)
        for existing in self._embeddings:
            if float(np.dot(emb, existing)) > self.threshold:
                return False
        self._embeddings.append(emb)
        return True


class NoOpDeduplicator:
    """Stub that always passes — used in dry-run or --skip-embeddings mode."""

    def check_and_accept(self, query: str) -> bool:
        return True


# ═══════════════════════════════════════════════════════════════════════════
# Filter 4: LLM medical validity check
# ═══════════════════════════════════════════════════════════════════════════

def _call_validity_llm(
    prompt: str,
) -> dict:
    """Call the validity-check LLM and return parsed JSON.

    Returns {"valid": False, "reason": "..."} on any error.
    """
    try:
        import os
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=FilterConfig.VALIDITY_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a clinical informatics expert. "
                        "Output valid JSON only, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=FilterConfig.VALIDITY_TEMPERATURE,
            max_tokens=FilterConfig.VALIDITY_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except Exception as e:
        log.warning("Validity LLM call failed: %s", e)
        return {"valid": False, "reason": f"LLM error: {e}"}


def filter_validity(
    candidate: QueryCandidate,
    prompt_template: str,
) -> bool:
    """Return True if the LLM judge deems the candidate valid."""
    params_str = json.dumps(
        candidate.ground_truth.required_parameters
        if candidate.ground_truth else [],
        ensure_ascii=False,
    )
    prompt = prompt_template.format(
        query=candidate.query,
        required_parameters=params_str,
        query_type=candidate.query_type.value,
        query_style=candidate.query_style.value,
    )

    result = _call_validity_llm(prompt)
    is_valid = result.get("valid", False)
    if not is_valid:
        log.debug(
            "Validity rejected: %s — %s",
            candidate.query[:60], result.get("reason", "?"),
        )
    return bool(is_valid)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    dry_run: bool = False,
    skip_llm: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """Run Stage 4.

    Args:
        dry_run:  Skip embedding + LLM filters (apply only free filters).
        skip_llm: Skip only the LLM validity filter (Filter 4).
        limit:    Process only first N candidates.

    Returns:
        Stats dict with per-filter rejection counts.
    """
    Paths.ensure_output_dir()
    output_file = Paths.FILTERED

    # Load labeled candidates from Stage 3
    candidates = _load_labeled(Paths.LABELED)
    log.info("Loaded labeled candidates: %d", len(candidates))

    if limit is not None:
        candidates = candidates[:limit]
        log.info("Limiting to first %d candidates", limit)

    # Load validity prompt for Filter 4
    validity_prompt = (Paths.PROMPTS_DIR / "validity_check.txt").read_text(
        encoding="utf-8"
    )

    # Deduplicator
    if dry_run:
        dedup = NoOpDeduplicator()
    else:
        dedup = EmbeddingDeduplicator()

    # Coverage counter
    coverage_counter: Counter = Counter()

    # Always create (or truncate) so downstream stages can read even if empty
    output_file.write_text("", encoding="utf-8")

    stats = {
        "total": len(candidates),
        "rejected_exposure": 0,
        "rejected_coverage": 0,
        "rejected_duplicate": 0,
        "rejected_validity": 0,
        "passed": 0,
    }

    for idx, cand in enumerate(candidates, start=1):
        # ── Filter 1: param_key exposure ──
        if not filter_param_exposure(cand):
            stats["rejected_exposure"] += 1
            continue

        # ── Filter 2: coverage cap ──
        if not filter_coverage(cand, coverage_counter):
            stats["rejected_coverage"] += 1
            continue

        # ── Filter 3: semantic dedup ──
        if not dedup.check_and_accept(cand.query):
            stats["rejected_duplicate"] += 1
            continue

        # ── Filter 4: LLM validity ──
        if not dry_run and not skip_llm:
            if not filter_validity(cand, validity_prompt):
                stats["rejected_validity"] += 1
                continue
            time.sleep(0.3)

        # ── Passed all filters ──
        stats["passed"] += 1
        _update_coverage(cand, coverage_counter)
        if not dry_run:
            append_jsonl(output_file, cand)

        if idx % 50 == 0:
            log.info("  processed %d / %d ...", idx, len(candidates))

    # Summary
    log.info("=" * 60)
    log.info("Stage 4 complete.")
    log.info("  Total candidates      : %d", stats["total"])
    log.info("  Rejected (exposure)   : %d", stats["rejected_exposure"])
    log.info("  Rejected (coverage)   : %d", stats["rejected_coverage"])
    log.info("  Rejected (duplicate)  : %d", stats["rejected_duplicate"])
    log.info("  Rejected (validity)   : %d", stats["rejected_validity"])
    log.info("  Passed                : %d", stats["passed"])
    if not dry_run:
        log.info("  Output file           : %s", output_file)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 4 — Quality filtering (4 sequential filters)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Apply only free filters (skip embeddings + LLM).",
    )
    parser.add_argument(
        "--skip-llm", action="store_true",
        help="Skip only the LLM validity filter (Filter 4).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process only first N candidates.",
    )
    args = parser.parse_args()

    run(dry_run=args.dry_run, skip_llm=args.skip_llm, limit=args.limit)
