"""
Evaluation/SemanticValueAccuracy/config.py

Single source of truth for the SVA dataset generation + evaluation pipeline.

All tunable parameters live here:
  - Output paths
  - Category targets & oversampling
  - LLM model settings (generation / GT code / audit)
  - Quality filter thresholds
  - 3-Layer scoring weights
  - Minimum dataset acceptance criteria
  - Cross-device equivalences
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

class Paths:
    """All file paths used across pipeline stages."""

    BASE_DIR: Path = Path(__file__).parent.resolve()
    PROJECT_ROOT: Path = BASE_DIR.parent.parent
    OUTPUT_DIR: Path = BASE_DIR / "output"
    PROMPTS_DIR: Path = BASE_DIR / "prompts"
    STAGES_DIR: Path = BASE_DIR / "stages"

    # --- External reference data ---
    TRACK_NAMES_CSV: Path = (
        PROJECT_ROOT / "IndexingAgent" / "data" / "raw"
        / "Open_VitalDB_1.0.0" / "track_names.csv"
    )
    VITAL_DIR: Path = (
        PROJECT_ROOT / "IndexingAgent" / "data" / "raw"
        / "Open_VitalDB_1.0.0" / "vital_files"
    )
    CLINICAL_DATA_CSV: Path = (
        PROJECT_ROOT / "IndexingAgent" / "data" / "raw"
        / "Open_VitalDB_1.0.0" / "clinical_data.csv"
    )

    # --- Stage outputs ---
    METADATA_CONTEXT: Path = OUTPUT_DIR / "metadata_context.json"
    CANDIDATES: Path = OUTPUT_DIR / "sva_candidates.jsonl"
    VERIFIED: Path = OUTPUT_DIR / "sva_verified.jsonl"
    FILTERED: Path = OUTPUT_DIR / "sva_filtered.jsonl"
    FINAL_DATASET: Path = OUTPUT_DIR / "sva_dataset.jsonl"
    VALIDATION_REPORT: Path = OUTPUT_DIR / "sva_validation_report.json"

    @classmethod
    def ensure_output_dir(cls) -> None:
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Category Targets & Oversampling
# ---------------------------------------------------------------------------

class CategoryTargets:
    """Per-category target counts and oversampling ratio."""

    TARGETS: dict[str, int] = {
        "semantic_resolution": 15,
        "cross_device": 10,
        "cohort_signal_join": 10,
        "ontology_based": 10,
        "adversarial_semantic": 5,
    }

    MINIMUMS: dict[str, int] = {
        "semantic_resolution": 10,
        "cross_device": 6,
        "cohort_signal_join": 6,
        "ontology_based": 6,
        "adversarial_semantic": 2,
    }

    OVERSAMPLING_MULTIPLIER: int = 2

    ID_PREFIXES: dict[str, str] = {
        "semantic_resolution": "sva_sem",
        "cross_device": "sva_xdev",
        "cohort_signal_join": "sva_cj",
        "ontology_based": "sva_onto",
        "adversarial_semantic": "sva_adv",
    }

    @classmethod
    def total_target(cls) -> int:
        return sum(cls.TARGETS.values())

    @classmethod
    def total_generation(cls) -> int:
        return sum(cls.TARGETS.values()) * cls.OVERSAMPLING_MULTIPLIER


# ---------------------------------------------------------------------------
# LLM Settings
# ---------------------------------------------------------------------------

class LLMConfig:
    """LLM model and parameter settings for each stage."""

    # Stage 2: query generation — gpt-5 for higher quality + supports 65K output tokens
    GENERATION_MODEL: str = os.getenv("SVA_GEN_MODEL", "gpt-5.2-2025-12-11")
    GENERATION_TEMPERATURE: float = float(os.getenv("SVA_GEN_TEMPERATURE", "0.8"))
    GENERATION_MAX_TOKENS: int = 65536
    BATCH_SIZE: int = 5

    # Stage 3: GT code generation — gpt-5 for more accurate Python code
    GT_CODE_MODEL: str = os.getenv("SVA_GT_MODEL", "gpt-5.2-2025-12-11")
    GT_CODE_TEMPERATURE: float = 0.2
    GT_CODE_MAX_TOKENS: int = 32768
    GT_MAX_RETRIES: int = 3

    # Stage 4: LLM quality audit — gpt-4o: temperature=0 reproducibility, cost-efficient
    AUDIT_MODEL: str = os.getenv("SVA_AUDIT_MODEL", "gpt-4o")
    AUDIT_TEMPERATURE: float = 0.0
    AUDIT_MAX_TOKENS: int = 512


# ---------------------------------------------------------------------------
# Quality Filter Thresholds (Stage 4)
# ---------------------------------------------------------------------------

class FilterConfig:
    """Thresholds for the four quality filters."""

    # Filter 1: track name exposure regex
    TRACK_PATTERN: str = r"\b[A-Z][a-z]+\d*/[A-Z][A-Z0-9_]+\b"

    # Filter 3: semantic dedup
    DEDUP_THRESHOLD: float = float(os.getenv("SVA_DEDUP_THRESHOLD", "0.80"))

    # Filter 4: LLM audit pass criteria
    AUDIT_MIN_SCORE: int = 3           # every criterion >= this
    AUDIT_MIN_AVERAGE: float = 3.5     # average across 6 criteria >= this

    # VitalExecutor timeout (seconds)
    EXECUTOR_TIMEOUT: int = 60


# ---------------------------------------------------------------------------
# 3-Layer Scoring Weights
# ---------------------------------------------------------------------------

class ScoringWeights:
    """Composite score weights for the 3-Layer scoring system."""

    RESOLUTION: float = 0.4
    EXECUTION: float = 0.2
    VALUE: float = 0.4

    VALUE_TOLERANCE: float = 1e-5


# ---------------------------------------------------------------------------
# Minimum Acceptance Criteria (Stage 5)
# ---------------------------------------------------------------------------

class ValidationCriteria:
    """Hard constraints the final dataset must satisfy."""

    ALL_EXECUTION_VERIFIED: bool = True
    NO_TRACK_IN_QUERIES: bool = True
    NULL_RATIO_MAX: float = 0.70
    MIN_CASE_DIVERSITY_PCT: float = 0.20  # each target case >= 20% of dataset


# ---------------------------------------------------------------------------
# Cross-Device Equivalences
# ---------------------------------------------------------------------------

CROSS_DEVICE_EQUIVALENCES: list[tuple[str, str]] = [
    ("Solar8000/HR", "Solar8000/PLETH_HR"),
    ("Solar8000/ETCO2", "Primus/ETCO2"),
    ("Solar8000/VENT_TV", "Primus/TV"),
    ("Solar8000/VENT_MV", "Primus/MV"),
    ("Solar8000/VENT_SET_PCP", "Primus/SET_PIP"),
    ("Solar8000/VENT_SET_TV", "Primus/SET_TV_L"),
    ("Solar8000/VENT_MEAS_PEEP", "Primus/PEEP_MBAR"),
    ("Solar8000/VENT_RR", "Primus/RR_CO2"),
    ("Solar8000/FIO2", "Primus/FIO2"),
    ("Solar8000/FEO2", "Primus/FEO2"),
    ("Solar8000/CO2", "Primus/CO2"),
]


# ---------------------------------------------------------------------------
# Quick sanity check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== SVA Pipeline Config ===")
    print(f"Base dir          : {Paths.BASE_DIR}")
    print(f"Output dir        : {Paths.OUTPUT_DIR}")
    print(f"track_names.csv   : {Paths.TRACK_NAMES_CSV}")
    print(f"  exists?         : {Paths.TRACK_NAMES_CSV.exists()}")
    print(f"Vital dir         : {Paths.VITAL_DIR}")
    print(f"  exists?         : {Paths.VITAL_DIR.exists()}")
    print(f"Clinical data     : {Paths.CLINICAL_DATA_CSV}")
    print(f"  exists?         : {Paths.CLINICAL_DATA_CSV.exists()}")

    print(f"\n--- Category Targets ---")
    for cat, n in CategoryTargets.TARGETS.items():
        prefix = CategoryTargets.ID_PREFIXES[cat]
        gen = n * CategoryTargets.OVERSAMPLING_MULTIPLIER
        print(f"  {cat:<25} target={n:>3}  generate={gen:>3}  prefix={prefix}")
    print(f"  {'TOTAL':<25} target={CategoryTargets.total_target():>3}  "
          f"generate={CategoryTargets.total_generation():>3}")

    print(f"\n--- LLM Settings ---")
    print(f"  Generation : {LLMConfig.GENERATION_MODEL} (temp={LLMConfig.GENERATION_TEMPERATURE})")
    print(f"  GT Code    : {LLMConfig.GT_CODE_MODEL} (temp={LLMConfig.GT_CODE_TEMPERATURE})")
    print(f"  Audit      : {LLMConfig.AUDIT_MODEL} (temp={LLMConfig.AUDIT_TEMPERATURE})")

    print(f"\n--- Scoring Weights ---")
    print(f"  Resolution : {ScoringWeights.RESOLUTION}")
    print(f"  Execution  : {ScoringWeights.EXECUTION}")
    print(f"  Value      : {ScoringWeights.VALUE}")

    print(f"\n--- Cross-Device Equivalences ---")
    for a, b in CROSS_DEVICE_EQUIVALENCES:
        print(f"  {a:<30} ↔ {b}")
