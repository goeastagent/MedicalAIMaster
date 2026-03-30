import argparse
import json
import logging
import sys
import vitaldb
import numpy as np
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root (needed for case_sampler import)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.utils.case_sampler import sample_case_ids, get_vital_dir

WINDOW_SIZE_SEC = 300  # 5-minute sliding window for quality scanning

CLINICAL_RANGES = {
    "Solar8000/ART_SBP": (40, 300),
    "Solar8000/ART_DBP": (20, 200),
    "Solar8000/ART_MBP": (30, 250),
    "Solar8000/HR": (20, 250),
    "Solar8000/PLETH_SPO2": (50, 100),
    "Solar8000/PLETH_HR": (20, 250),
    "Solar8000/BT": (30, 42),
    "Solar8000/ETCO2": (0, 80),
    "Solar8000/RR_CO2": (0, 60),
    "Solar8000/FIO2": (21, 100),
    "Solar8000/FEO2": (10, 100),
    "Solar8000/VENT_MV": (0, 30),
    "Solar8000/VENT_TV": (0, 2000),
    "Solar8000/VENT_RR": (0, 60),
    "Solar8000/VENT_PIP": (0, 60),
    "Solar8000/VENT_PPLAT": (0, 50),
    "Solar8000/VENT_MAWP": (0, 40),
    "Solar8000/NIBP_MBP": (30, 200),
    "Solar8000/NIBP_SBP": (40, 300),
    "Solar8000/NIBP_DBP": (20, 200),
    "Primus/CO2": (0, 80),
    "Primus/ETCO2": (0, 80),
    "Primus/FIO2": (21, 100),
    "Primus/FEO2": (10, 100),
    "Primus/MAC": (0, 5),
    "Primus/MV": (0, 30),
    "Primus/TV": (0, 2000),
    "Primus/RR_CO2": (0, 60),
    "Primus/AWP": (0, 60),
    "Primus/COMPLIANCE": (5, 150),
    "Primus/PIP_MBAR": (0, 60),
    "Primus/PEEP_MBAR": (0, 30),
    "Primus/PPLAT_MBAR": (0, 50),
    "Primus/MAWP_MBAR": (0, 40),
    "BIS/BIS": (0, 100),
    "BIS/EMG": (0, 100),
    "BIS/SQI": (0, 100),
    "BIS/SEF": (0, 50),
    "BIS/SR": (0, 100),
    "Orchestra/RFTN20_CE": (0, 20),
    "Orchestra/RFTN20_CP": (0, 20),
    "Orchestra/RFTN20_RATE": (0, 50),
    "Orchestra/PPF20_CE": (0, 20),
    "Orchestra/PPF20_CP": (0, 20),
    "Orchestra/PPF20_RATE": (0, 50),
    "SNUADC/ART": (-5000, 5000),
    "SNUADC/ECG_II": (-5, 5),
    "SNUADC/ECG_V5": (-5, 5),
    "SNUADC/PLETH": (-5000, 5000),
}


def _profile_track(vf, track: str, duration: int) -> dict:
    """Analyse a single track: NaN density, artifacts, constant-value windows."""
    try:
        arr = vf.to_numpy([track], 1)
    except Exception as e:
        logger.warning(f"    Cannot read {track}: {e}")
        return {"error": str(e)}

    if arr is None or arr.size == 0:
        return {"error": "empty_array"}

    vals = arr[:, 0]

    if not np.issubdtype(vals.dtype, np.floating) and not np.issubdtype(vals.dtype, np.integer):
        try:
            vals = vals.astype(np.float64)
        except (ValueError, TypeError):
            return {"error": f"non_numeric_dtype:{vals.dtype}"}

    valid_mask = ~np.isnan(vals)
    valid_indices = np.where(valid_mask)[0]

    if len(valid_indices) == 0:
        return {
            "nan_ratio": 1.0,
            "valid_count": 0,
            "valid_data_range_sec": None,
            "sparse_windows": [{"start": 0, "end": duration, "nan_ratio": 1.0}],
            "constant_windows": [],
            "artifact_windows": [],
            "value_stats": None,
        }

    valid_vals = vals[valid_indices]
    overall_nan_ratio = round(1 - len(valid_indices) / len(vals), 3)

    value_stats = {
        "min": round(float(np.min(valid_vals)), 4),
        "max": round(float(np.max(valid_vals)), 4),
        "mean": round(float(np.mean(valid_vals)), 4),
        "std": round(float(np.std(valid_vals, ddof=0)), 4),
        "unique_count": int(min(len(np.unique(valid_vals)), 9999)),
    }

    valid_range = [int(valid_indices[0]), int(valid_indices[-1])]

    # Sliding-window scan
    sparse_windows = []
    constant_windows = []
    artifact_windows = []
    lo, hi = CLINICAL_RANGES.get(track, (None, None))

    for start in range(0, duration, WINDOW_SIZE_SEC):
        end = min(start + WINDOW_SIZE_SEC, duration)
        window = vals[start:end]
        w_valid = window[~np.isnan(window)]
        w_nan_ratio = round(1 - len(w_valid) / len(window), 2) if len(window) > 0 else 1.0

        if w_nan_ratio > 0.8:
            sparse_windows.append({"start": start, "end": end, "nan_ratio": w_nan_ratio})
        elif len(w_valid) > 0 and len(np.unique(w_valid)) <= 2:
            constant_windows.append({
                "start": start, "end": end,
                "unique_values": [round(float(v), 4) for v in np.unique(w_valid)],
            })

        if lo is not None and len(w_valid) > 0:
            out_of_range = np.sum((w_valid < lo) | (w_valid > hi))
            oor_ratio = out_of_range / len(w_valid)
            if oor_ratio > 0.5:
                artifact_windows.append({
                    "start": start, "end": end,
                    "out_of_range_ratio": round(oor_ratio, 2),
                    "sample_values": [round(float(v), 2) for v in w_valid[:5]],
                })

    return {
        "nan_ratio": overall_nan_ratio,
        "valid_count": int(len(valid_indices)),
        "valid_data_range_sec": valid_range,
        "sparse_windows": sparse_windows,
        "constant_windows": constant_windows,
        "artifact_windows": artifact_windows,
        "value_stats": value_stats,
    }


def _generate_quality_warnings(caseid: str, track: str, profile: dict) -> list[str]:
    """Produce human-readable warnings from a track profile."""
    warnings = []
    if "error" in profile:
        warnings.append(f"caseid {caseid} / {track}: UNREADABLE ({profile['error']})")
        return warnings

    if profile["valid_count"] == 0:
        warnings.append(
            f"caseid {caseid} / {track}: Entire track is NaN. "
            "DO NOT query this track."
        )
        return warnings

    for aw in profile.get("artifact_windows", []):
        warnings.append(
            f"caseid {caseid} / {track}: [{aw['start']}s–{aw['end']}s] contains "
            f"{int(aw['out_of_range_ratio']*100)}% out-of-range values "
            f"(samples: {aw['sample_values']}). Likely calibration artifact. "
            "DO NOT query this window."
        )

    for sw in profile.get("sparse_windows", []):
        if sw["nan_ratio"] >= 1.0:
            warnings.append(
                f"caseid {caseid} / {track}: [{sw['start']}s–{sw['end']}s] is 100% NaN. "
                "DO NOT query this window."
            )

    for cw in profile.get("constant_windows", []):
        warnings.append(
            f"caseid {caseid} / {track}: [{cw['start']}s–{cw['end']}s] has only "
            f"constant value(s) {cw['unique_values']}. Queries here are trivial."
        )

    if profile["nan_ratio"] > 0.8:
        warnings.append(
            f"caseid {caseid} / {track}: Overall NaN ratio is "
            f"{profile['nan_ratio']:.0%}. Very sparse track — avoid if possible."
        )

    return warnings


def extract_metadata(
    n_cases: int = 3,
    seed: Optional[int] = None,
    target_cases: Optional[list[str]] = None,
    output_path: Optional[Path] = None,
):
    """
    Scan .vital files and produce vital_metadata.json + quality_warnings.txt.

    Args:
        n_cases:      Number of .vital files to randomly sample (ignored when
                      target_cases is provided).
        seed:         Random seed for case sampling.
        target_cases: Explicit list of caseid strings (e.g. ["0001", "0042"]).
                      When provided, n_cases and seed are ignored.
        output_path:  Custom Path for the metadata JSON file.  Defaults to
                      Evaluation/Temporal/vital_metadata.json.
    """
    vital_dir = get_vital_dir()

    if not vital_dir.exists():
        logger.error(f"Vital directory not found at {vital_dir}")
        return

    if target_cases is None:
        target_cases = sample_case_ids(vital_dir=vital_dir, n=n_cases, seed=seed)
        logger.info(f"Sampled {len(target_cases)} cases (seed={seed}): {target_cases}")
    else:
        logger.info(f"Using provided cases: {target_cases}")

    metadata = {}
    all_warnings: list[str] = []

    for caseid in target_cases:
        file_path = vital_dir / f"{caseid}.vital"
        if not file_path.exists():
            logger.warning(f"{caseid}.vital not found, skipping.")
            continue

        logger.info(f"Processing {caseid}.vital ...")
        vf = vitaldb.VitalFile(str(file_path))
        tracks = vf.get_track_names()
        if not tracks:
            continue

        ref_track = "SNUADC/ECG_II" if "SNUADC/ECG_II" in tracks else tracks[0]
        duration_sec = len(vf.to_numpy([ref_track], 1))

        logger.info(f"  Duration: {duration_sec}s, Tracks: {len(tracks)}")

        track_profiles = {}
        for track in tracks:
            if track == "EVENT" or "_WAV" in track:
                continue
            logger.info(f"  Profiling {track} ...")
            profile = _profile_track(vf, track, duration_sec)
            track_profiles[track] = profile
            warnings = _generate_quality_warnings(caseid, track, profile)
            all_warnings.extend(warnings)

        metadata[caseid] = {
            "duration_sec": duration_sec,
            "tracks": tracks,
            "track_profiles": track_profiles,
        }

    # Store sampled case list inside the JSON so downstream stages can read it
    default_output_dir = Path(__file__).resolve().parent
    metadata_path = output_path if output_path is not None else (default_output_dir / "vital_metadata.json")
    output_payload = {
        "_sampled_case_ids": sorted(metadata.keys()),
        **metadata,
    }
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2, ensure_ascii=False)
    logger.info(f"Metadata saved to {metadata_path}")

    warnings_path = metadata_path.parent / "quality_warnings.txt"
    with open(warnings_path, "w", encoding="utf-8") as f:
        for w in all_warnings:
            f.write(f"- {w}\n")
    logger.info(f"Quality warnings ({len(all_warnings)} items) saved to {warnings_path}")

    return metadata, all_warnings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract metadata and quality warnings from .vital files.")
    parser.add_argument(
        "--n-cases", type=int, default=3,
        help="Number of .vital files to randomly sample (default: 3)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for case sampling (default: non-deterministic)",
    )
    parser.add_argument(
        "--cases", nargs="+", default=None,
        help="Explicit caseid list (e.g. --cases 0001 0042 0100). Overrides --n-cases/--seed.",
    )
    args = parser.parse_args()
    extract_metadata(n_cases=args.n_cases, seed=args.seed, target_cases=args.cases)
