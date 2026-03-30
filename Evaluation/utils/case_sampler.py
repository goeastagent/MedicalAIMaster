"""
Evaluation/utils/case_sampler.py

Shared utility for dynamically sampling .vital files and building LLM prompt
inventory blocks. Used by ValueAccuracy, Temporal, and SemanticValueAccuracy
pipelines so that caseid selection is never hardcoded.

Main API:
    sample_cases(vital_dir, n, seed) -> dict[caseid, list[track_name]]
    build_inventory_text(cases)       -> str  (injected into prompt templates)
    get_vital_dir()                   -> Path (project-relative default)
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default vital directory (relative to project root)
# ---------------------------------------------------------------------------

def get_vital_dir() -> Path:
    """Return the default vital_files directory based on project structure."""
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "IndexingAgent" / "data" / "raw" / "Open_VitalDB_1.0.0" / "vital_files"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(vital_dir: Path) -> Path:
    """JSON cache file stored alongside this utility."""
    return Path(__file__).parent / "case_sample_cache.json"


def _load_cache(vital_dir: Path, n: int, seed: Optional[int]) -> Optional[dict[str, list[str]]]:
    cache_file = _cache_path(vital_dir)
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
        key = f"{vital_dir}|n={n}|seed={seed}"
        return cache.get(key)
    except Exception:
        return None


def _save_cache(vital_dir: Path, n: int, seed: Optional[int], cases: dict[str, list[str]]) -> None:
    cache_file = _cache_path(vital_dir)
    try:
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                cache = json.load(f)
        else:
            cache = {}
        key = f"{vital_dir}|n={n}|seed={seed}"
        cache[key] = cases
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save case sample cache: {e}")


# ---------------------------------------------------------------------------
# Core sampling function
# ---------------------------------------------------------------------------

def sample_cases(
    vital_dir: Optional[Path] = None,
    n: int = 3,
    seed: Optional[int] = None,
    use_cache: bool = True,
) -> dict[str, list[str]]:
    """
    Randomly sample n .vital files and return their track lists.

    Args:
        vital_dir: Directory containing *.vital files. Defaults to the
                   project's Open_VitalDB_1.0.0/vital_files directory.
        n:         Number of cases to sample. Defaults to 3.
        seed:      Random seed for reproducibility. None means non-deterministic.
        use_cache: If True, read/write a JSON cache to avoid re-scanning files.

    Returns:
        dict mapping caseid (zero-padded string, e.g. "0042") to a sorted list
        of track name strings available in that file.
    """
    import vitaldb  # imported here to avoid hard dependency at module import time

    if vital_dir is None:
        vital_dir = get_vital_dir()

    if not vital_dir.exists():
        raise FileNotFoundError(f"vital_files directory not found: {vital_dir}")

    if use_cache and seed is not None:
        cached = _load_cache(vital_dir, n, seed)
        if cached is not None:
            logger.info(f"case_sampler: loaded {len(cached)} cases from cache (seed={seed})")
            return cached

    all_files = sorted(vital_dir.glob("*.vital"))
    if not all_files:
        raise RuntimeError(f"No .vital files found in {vital_dir}")

    rng = random.Random(seed)
    n_actual = min(n, len(all_files))
    chosen = sorted(rng.sample(all_files, n_actual))

    logger.info(f"case_sampler: sampling {n_actual} cases from {len(all_files)} available (seed={seed})")

    result: dict[str, list[str]] = {}
    for f in chosen:
        caseid = f.stem  # e.g. "0001"
        try:
            vf = vitaldb.VitalFile(str(f))
            tracks = sorted(vf.get_track_names())
            result[caseid] = tracks
            logger.info(f"  caseid {caseid}: {len(tracks)} tracks")
        except Exception as e:
            logger.warning(f"  caseid {caseid}: failed to read ({e}) — skipping")

    if not result:
        raise RuntimeError("case_sampler: no valid cases could be read")

    if use_cache and seed is not None:
        _save_cache(vital_dir, n, seed, result)

    return result


# ---------------------------------------------------------------------------
# Prompt text builder
# ---------------------------------------------------------------------------

def build_inventory_text(cases: dict[str, list[str]]) -> str:
    """
    Build the 'AVAILABLE DATA INVENTORY' block injected into LLM prompt templates
    via the {cases_inventory} placeholder.

    Produces text like:
        Only the following 3 case files exist. You MUST ONLY use these caseids and tracks:

        - **caseid 0001**: `Solar8000/HR`, `BIS/BIS`, ...

        You MUST ONLY reference caseids 0001, 0002, 0009. Do NOT use any other caseids.
    """
    n = len(cases)
    lines: list[str] = [
        f"Only the following {n} case file{'s' if n != 1 else ''} exist."
        f" You MUST ONLY use these caseids and tracks:\n",
    ]
    for caseid, tracks in sorted(cases.items()):
        track_str = ", ".join(f"`{t}`" for t in tracks)
        lines.append(f"- **caseid {caseid}**: {track_str}")

    caseid_list = ", ".join(sorted(cases.keys()))
    lines.append(
        f"\nYou MUST ONLY reference caseid{'s' if n != 1 else ''} {caseid_list}."
        f" Do NOT use any other caseids."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Excluding-aware sampler (for multi-run pipelines)
# ---------------------------------------------------------------------------

def sample_cases_excluding(
    exclude: set[str],
    vital_dir: Optional[Path] = None,
    n: int = 3,
    seed: Optional[int] = None,
    use_cache: bool = True,
) -> dict[str, list[str]]:
    """
    Like sample_cases() but skips caseids already in `exclude`.

    Useful for multi-run pipelines where each run should cover fresh cases:

        used = set()
        for run_idx in range(num_runs):
            cases = sample_cases_excluding(exclude=used, n=3, seed=seed+run_idx)
            used.update(cases.keys())

    If fewer than `n` fresh cases remain, returns as many as possible.
    Returns an empty dict when all files have been exhausted.
    """
    import vitaldb

    if vital_dir is None:
        vital_dir = get_vital_dir()

    if not vital_dir.exists():
        raise FileNotFoundError(f"vital_files directory not found: {vital_dir}")

    all_files = sorted(vital_dir.glob("*.vital"))
    available = [f for f in all_files if f.stem not in exclude]

    if not available:
        logger.warning("sample_cases_excluding: no files remain after exclusion")
        return {}

    rng = random.Random(seed)
    n_actual = min(n, len(available))
    chosen = sorted(rng.sample(available, n_actual))

    logger.info(
        f"case_sampler: sampling {n_actual} fresh cases "
        f"(excluded {len(exclude)}, available {len(available)}, seed={seed})"
    )

    result: dict[str, list[str]] = {}
    for f in chosen:
        caseid = f.stem
        cache_key = f"{vital_dir}|n=1|seed=caseid:{caseid}"
        if use_cache:
            cache_file = _cache_path(vital_dir)
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as cf:
                        cache = json.load(cf)
                    if cache_key in cache:
                        result[caseid] = cache[cache_key][caseid]
                        continue
                except Exception:
                    pass
        try:
            vf = vitaldb.VitalFile(str(f))
            tracks = sorted(vf.get_track_names())
            result[caseid] = tracks
            logger.info(f"  caseid {caseid}: {len(tracks)} tracks")
            if use_cache:
                _save_cache(vital_dir, 1, None, {caseid: tracks})
        except Exception as e:
            logger.warning(f"  caseid {caseid}: failed to read ({e}) — skipping")

    return result


# ---------------------------------------------------------------------------
# Convenience: caseid list only (for modules that don't need track info)
# ---------------------------------------------------------------------------

def sample_case_ids(
    vital_dir: Optional[Path] = None,
    n: int = 3,
    seed: Optional[int] = None,
) -> list[str]:
    """
    Like sample_cases() but returns only the sorted caseid strings.
    Faster than sample_cases() because it does not open .vital files.
    """
    if vital_dir is None:
        vital_dir = get_vital_dir()

    if not vital_dir.exists():
        raise FileNotFoundError(f"vital_files directory not found: {vital_dir}")

    all_files = sorted(vital_dir.glob("*.vital"))
    if not all_files:
        raise RuntimeError(f"No .vital files found in {vital_dir}")

    rng = random.Random(seed)
    chosen = sorted(rng.sample(all_files, min(n, len(all_files))))
    return [f.stem for f in chosen]
