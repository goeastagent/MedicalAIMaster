"""
Evaluation/SemanticValueAccuracy/stages/stage1_metadata.py

Stage 1: Metadata Collection

Collects all context needed by Stage 2 (LLM query generation):
  1. track_names.csv → 196 parameter definitions (Description/Unit/Type)
  2. Per-case .vital files → available track inventory + duration
  3. Device grouping + cross-device pair auto-detection
  4. clinical_data.csv → cohort metadata for target cases + schema

Output: output/metadata_context.json

No PostgreSQL or LLM calls required.

Usage (standalone):
    python -m Evaluation.SemanticValueAccuracy.stages.stage1_metadata
    python -m Evaluation.SemanticValueAccuracy.stages.stage1_metadata --dry-run
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import vitaldb

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.SemanticValueAccuracy.config import (
    CROSS_DEVICE_EQUIVALENCES,
    Paths,
    TARGET_CASE_IDS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage1] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. track_names.csv → param_lookup
# ---------------------------------------------------------------------------

def load_track_names(csv_path: Path) -> Dict[str, Dict[str, str]]:
    """Parse track_names.csv into {param_key: {description, type_hz, unit, device}}."""
    df = pd.read_csv(csv_path)
    lookup: Dict[str, Dict[str, str]] = {}
    for _, row in df.iterrows():
        param = str(row["Parameter"]).strip()
        lookup[param] = {
            "description": str(row.get("Description", "")).strip(),
            "type_hz": str(row.get("Type/Hz", "")).strip(),
            "unit": str(row.get("Unit", "")).strip(),
            "device": param.split("/")[0] if "/" in param else param,
        }
    return lookup


# ---------------------------------------------------------------------------
# 2. Per-case track inventory from .vital files
# ---------------------------------------------------------------------------

def extract_case_inventory(
    vital_dir: Path,
    case_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """For each case, extract track list and recording duration."""
    inventory: Dict[str, Dict[str, Any]] = {}
    for caseid in case_ids:
        fpath = vital_dir / f"{caseid}.vital"
        if not fpath.exists():
            log.warning("  %s.vital not found — skipping", caseid)
            continue

        log.info("  Reading %s.vital ...", caseid)
        vf = vitaldb.VitalFile(str(fpath))
        tracks = vf.get_track_names()
        if not tracks:
            log.warning("  %s.vital has no tracks", caseid)
            inventory[caseid] = {"tracks": [], "duration_sec": 0}
            continue

        ref_track = "SNUADC/ECG_II" if "SNUADC/ECG_II" in tracks else tracks[0]
        arr = vf.to_numpy([ref_track], 1)
        duration = len(arr) if arr is not None else 0

        inventory[caseid] = {
            "tracks": sorted(tracks),
            "duration_sec": duration,
        }
        log.info("    tracks=%d, duration=%ds", len(tracks), duration)

    return inventory


# ---------------------------------------------------------------------------
# 3. Device grouping
# ---------------------------------------------------------------------------

def build_device_groups(param_lookup: Dict[str, Dict]) -> Dict[str, List[str]]:
    """Group param_keys by their device prefix."""
    groups: Dict[str, List[str]] = defaultdict(list)
    for param, info in param_lookup.items():
        groups[info["device"]].append(param)
    return {dev: sorted(params) for dev, params in sorted(groups.items())}


# ---------------------------------------------------------------------------
# 4. Cross-device pair auto-detection
# ---------------------------------------------------------------------------

def detect_cross_device_pairs(
    param_lookup: Dict[str, Dict],
) -> List[Dict[str, Any]]:
    """Find parameters sharing the same description but from different devices."""
    desc_map: Dict[str, List[str]] = defaultdict(list)
    for param, info in param_lookup.items():
        key = info["description"].lower().strip()
        if key:
            desc_map[key].append(param)

    pairs = []
    for desc, params in sorted(desc_map.items()):
        devices = sorted({p.split("/")[0] for p in params})
        if len(devices) > 1:
            pairs.append({
                "concept": desc,
                "sources": sorted(params),
                "devices": devices,
            })
    return pairs


# ---------------------------------------------------------------------------
# 5. Cohort metadata
# ---------------------------------------------------------------------------

def extract_cohort_data(
    csv_path: Path,
    case_ids: List[str],
) -> tuple[List[Dict], Dict[str, Any]]:
    """Load clinical_data.csv, filter to target cases, return rows + schema."""
    df = pd.read_csv(csv_path)

    int_ids = []
    for cid in case_ids:
        try:
            int_ids.append(int(cid))
        except ValueError:
            pass

    target = df[df["caseid"].isin(int_ids)]
    rows = json.loads(target.to_json(orient="records"))

    schema = {
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "total_rows": len(df),
    }
    return rows, schema


# ---------------------------------------------------------------------------
# 6. Manual equivalence enrichment
# ---------------------------------------------------------------------------

def enrich_with_manual_equivalences(
    auto_pairs: List[Dict],
) -> List[Dict]:
    """Merge config.CROSS_DEVICE_EQUIVALENCES into auto-detected pairs."""
    existing_sets: Dict[str, set] = {}
    for pair in auto_pairs:
        existing_sets[pair["concept"]] = set(pair["sources"])

    for a, b in CROSS_DEVICE_EQUIVALENCES:
        found = False
        for pair in auto_pairs:
            if a in pair["sources"] or b in pair["sources"]:
                pair["sources"] = sorted(set(pair["sources"]) | {a, b})
                pair["devices"] = sorted({p.split("/")[0] for p in pair["sources"]})
                found = True
                break
        if not found:
            auto_pairs.append({
                "concept": f"manual: {a} ↔ {b}",
                "sources": sorted([a, b]),
                "devices": sorted({a.split("/")[0], b.split("/")[0]}),
            })
    return auto_pairs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> Dict[str, Any]:
    """Execute Stage 1 and write metadata_context.json."""
    Paths.ensure_output_dir()

    # 1. track_names.csv
    log.info("Loading track_names.csv: %s", Paths.TRACK_NAMES_CSV)
    param_lookup = load_track_names(Paths.TRACK_NAMES_CSV)
    log.info("  %d parameters loaded", len(param_lookup))

    # 2. Case track inventory
    log.info("Extracting case track inventories ...")
    case_inventory = extract_case_inventory(Paths.VITAL_DIR, TARGET_CASE_IDS)

    # 3. Device groups
    log.info("Building device groups ...")
    device_groups = build_device_groups(param_lookup)
    log.info("  %d devices: %s", len(device_groups), list(device_groups.keys()))

    # 4. Cross-device pairs
    log.info("Detecting cross-device pairs ...")
    xdev_pairs = detect_cross_device_pairs(param_lookup)
    xdev_pairs = enrich_with_manual_equivalences(xdev_pairs)
    log.info("  %d cross-device concept groups", len(xdev_pairs))

    # 5. Cohort data
    log.info("Loading cohort data: %s", Paths.CLINICAL_DATA_CSV)
    cohort_rows, cohort_schema = extract_cohort_data(
        Paths.CLINICAL_DATA_CSV, TARGET_CASE_IDS,
    )
    log.info("  %d target cases extracted", len(cohort_rows))

    # 6. Assemble context
    context: Dict[str, Any] = {
        "track_names_ref": param_lookup,
        "device_groups": device_groups,
        "cross_device_pairs": xdev_pairs,
        "cohort_data": cohort_rows,
        "cohort_schema": cohort_schema,
        "case_track_inventory": case_inventory,
        "target_case_ids": TARGET_CASE_IDS,
    }

    # 7. Save
    out_path = Paths.METADATA_CONTEXT
    if dry_run:
        log.info("[DRY-RUN] Would write %s (skipped)", out_path)
    else:
        tmp = out_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(context, f, ensure_ascii=False, indent=2)
        tmp.replace(out_path)
        log.info("Saved: %s", out_path)

    # 8. Summary
    log.info("=" * 60)
    log.info("Stage 1 — Metadata Collection complete")
    log.info("  Parameters     : %d", len(param_lookup))
    log.info("  Devices        : %d", len(device_groups))
    log.info("  XDev pairs     : %d", len(xdev_pairs))
    log.info("  Cohort rows    : %d", len(cohort_rows))
    log.info("  Cases          : %s", list(case_inventory.keys()))
    for cid, inv in case_inventory.items():
        log.info("    %s: %d tracks, %ds",
                 cid, len(inv["tracks"]), inv["duration_sec"])
    log.info("=" * 60)

    return context


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Stage 1 — Metadata collection for SVA dataset generation."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip writing output file.")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
