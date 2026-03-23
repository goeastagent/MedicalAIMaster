"""
Evaluation/Level1/config.py

Single source of truth for the Level 1 dataset generation pipeline.

All tunable parameters live here:
  - Output paths
  - Batch plan (target case counts per query_type × query_style cell)
  - LLM model settings (generation vs. validation)
  - Quality filter thresholds
  - Minimum dataset acceptance criteria
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv

# Support both `python config.py` (direct) and `from Evaluation.Level1 import config` (package)
try:
    from Evaluation.Level1.models import QueryStyle, QueryType
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from Evaluation.Level1.models import QueryStyle, QueryType

load_dotenv()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

class Paths:
    """All file paths used across pipeline stages.

    BASE_DIR is this file's parent directory (Evaluation/Level1/).
    Everything else is relative to it so the pipeline is relocatable.
    """

    BASE_DIR: Path = Path(__file__).parent.resolve()
    OUTPUT_DIR: Path = BASE_DIR / "output"
    PROMPTS_DIR: Path = BASE_DIR / "prompts"
    STAGES_DIR: Path = BASE_DIR / "stages"

    # --- Stage outputs (each stage reads the previous stage's file) ---

    # Stage 1: parameter corpus + synonym map
    SYNONYM_MAP: Path = OUTPUT_DIR / "synonym_map.json"

    # Stage 2: raw LLM-generated query candidates (newline-delimited JSON)
    CANDIDATES: Path = OUTPUT_DIR / "candidates.jsonl"

    # Stage 3: candidates with ground_truth attached
    LABELED: Path = OUTPUT_DIR / "labeled.jsonl"

    # Stage 4: quality-filtered cases (normal cases only)
    FILTERED: Path = OUTPUT_DIR / "filtered.jsonl"

    # Stage 5: filtered + adversarial cases merged
    WITH_ADVERSARIAL: Path = OUTPUT_DIR / "with_adversarial.jsonl"

    # Stage 6: validated final dataset
    FINAL_DATASET: Path = OUTPUT_DIR / "level1_dataset.json"
    VALIDATION_REPORT: Path = OUTPUT_DIR / "validation_report.json"

    @classmethod
    def ensure_output_dir(cls) -> None:
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Batch Plan
# ---------------------------------------------------------------------------

# Target case counts per (QueryType, QueryStyle) cell.
# Adversarial cases have no style breakdown — handled separately in Stage 5.
#
# Source: LEVEL1_DATASET.md Section 3 / Stage 2
# NOTE: Cross-Source removed — current experiment uses vital signals only.
#
#                         Doctor  DataSci  Layperson
# Single-Direct              7       7        6      = 20
# Single-Semantic            7       7        6      = 20
# Single-Abbreviation        7       7        6      = 20
# Multi-Independent          7       7        6      = 20
# Multi-Conditional         10      10       10      = 30
# Adversarial                               20      = 20  (style=N/A)
#                                                  ------
#                                                   130

BatchCell = Tuple[QueryType, QueryStyle]
BatchPlan = Dict[BatchCell, int]


class GenerationConfig:
    """Batch plan and LLM settings for Stages 1–3."""

    # ---- Batch plan --------------------------------------------------------

    BATCH_PLAN: BatchPlan = {
        # Single-Direct
        (QueryType.SINGLE_DIRECT, QueryStyle.DOCTOR):         7,
        (QueryType.SINGLE_DIRECT, QueryStyle.DATA_SCIENTIST): 7,
        (QueryType.SINGLE_DIRECT, QueryStyle.LAYPERSON):      6,
        # Single-Semantic
        (QueryType.SINGLE_SEMANTIC, QueryStyle.DOCTOR):         7,
        (QueryType.SINGLE_SEMANTIC, QueryStyle.DATA_SCIENTIST): 7,
        (QueryType.SINGLE_SEMANTIC, QueryStyle.LAYPERSON):      6,
        # Single-Abbreviation
        (QueryType.SINGLE_ABBREVIATION, QueryStyle.DOCTOR):         7,
        (QueryType.SINGLE_ABBREVIATION, QueryStyle.DATA_SCIENTIST): 7,
        (QueryType.SINGLE_ABBREVIATION, QueryStyle.LAYPERSON):      6,
        # Multi-Independent
        (QueryType.MULTI_INDEPENDENT, QueryStyle.DOCTOR):         7,
        (QueryType.MULTI_INDEPENDENT, QueryStyle.DATA_SCIENTIST): 7,
        (QueryType.MULTI_INDEPENDENT, QueryStyle.LAYPERSON):      6,
        # Multi-Conditional
        (QueryType.MULTI_CONDITIONAL, QueryStyle.DOCTOR):         10,
        (QueryType.MULTI_CONDITIONAL, QueryStyle.DATA_SCIENTIST): 10,
        (QueryType.MULTI_CONDITIONAL, QueryStyle.LAYPERSON):      10,
    }

    # Target adversarial cases (all sub-types combined: Ambiguous/Impossible/Confusing)
    ADVERSARIAL_TARGET: int = 20

    # ---- Parameter batch configuration ------------------------------------

    # For Single-* types: number of param_keys injected per LLM call.
    # Each call generates 1 query per param → PARAMS_PER_BATCH queries per call.
    # e.g., 260 params / 5 per batch = 52 calls per (query_type × query_style) cell.
    # Only params that have passed synonym generation (Stage 1) are used.
    PARAMS_PER_BATCH: int = int(os.getenv("LEVEL1_PARAMS_PER_BATCH", "5"))

    # For Multi-* types: queries are generated from pre-defined
    # medically relevant parameter pairs (see MEDICAL_PARAM_PAIRS below).
    # This value sets how many query variants to request per pair per LLM call.
    QUERIES_PER_PAIR: int = int(os.getenv("LEVEL1_QUERIES_PER_PAIR", "3"))

    # ---- Oversampling ------------------------------------------------------

    # LLM generates GENERATION_MULTIPLIER × target to ensure enough survive
    # quality filtering (Stage 4).
    GENERATION_MULTIPLIER: int = 2

    # ---- LLM for generation (Stage 2 / Stage 5) ----------------------------
    # High temperature for diversity.

    GENERATION_MODEL: str = os.getenv("LEVEL1_GEN_MODEL", "gpt-4o")
    GENERATION_TEMPERATURE: float = float(
        os.getenv("LEVEL1_GEN_TEMPERATURE", "0.8")
    )
    GENERATION_MAX_TOKENS: int = int(
        os.getenv("LEVEL1_GEN_MAX_TOKENS", "1024")
    )

    # Number of query candidates to request per LLM call
    CANDIDATES_PER_CALL: int = 5

    # ---- LLM for synonym generation (Stage 1) ------------------------------

    SYNONYM_MODEL: str = os.getenv("LEVEL1_SYNONYM_MODEL", "gpt-4o")
    SYNONYM_TEMPERATURE: float = 0.3   # slight variation for synonym diversity
    SYNONYM_MAX_TOKENS: int = 512

    # ---- Helpers -----------------------------------------------------------

    @classmethod
    def total_target(cls) -> int:
        """Total normal (non-adversarial) target cases."""
        return sum(cls.BATCH_PLAN.values())

    @classmethod
    def grand_total_target(cls) -> int:
        """Total target cases including adversarial."""
        return cls.total_target() + cls.ADVERSARIAL_TARGET

    @classmethod
    def generation_target(cls, query_type: QueryType, query_style: QueryStyle) -> int:
        """How many candidates to generate for a given cell (after multiplier)."""
        base = cls.BATCH_PLAN.get((query_type, query_style), 0)
        return base * cls.GENERATION_MULTIPLIER


# ---------------------------------------------------------------------------
# Medically Relevant Parameter Pairs (for Multi-* generation, vital signals only)
# ---------------------------------------------------------------------------
# Source: LEVEL1_DATASET.md Section 3-3
#
# Format per entry:
#   {
#     "param_a": str,          # condition param (Multi-Conditional) or first param
#     "param_b": str,          # analysis param (Multi-Conditional) or second param
#     "role_a": str,           # "condition" | "independent" | "vital"
#     "role_b": str,           # "analysis"  | "independent"
#     "clinical_relation": str # one-line description for context
#   }

ParamPair = dict  # typed alias for readability

MEDICAL_PARAM_PAIRS: list[ParamPair] = [
    # ── Cardiopulmonary ──────────────────────────────────────────────────────
    {
        "param_a": "Solar8000/PLETH_SPO2",
        "param_b": "Solar8000/HR",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "Compensatory tachycardia during hypoxemia",
    },
    {
        "param_a": "Solar8000/PLETH_SPO2",
        "param_b": "Primus/FIO2",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "O2 supply-saturation response",
    },
    {
        "param_a": "SNUADC/ECG_II",
        "param_b": "Solar8000/HR",
        "role_a": "independent",
        "role_b": "independent",
        "clinical_relation": "ECG waveform–heart rate validation",
    },
    {
        "param_a": "Solar8000/ETCO2",
        "param_b": "Primus/TV",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "EtCO2–tidal volume relationship",
    },
    {
        "param_a": "Primus/ETCO2",
        "param_b": "Primus/FIO2",
        "role_a": "independent",
        "role_b": "independent",
        "clinical_relation": "Respiratory management correlation",
    },
    # ── Hemodynamic-Pharmacologic ────────────────────────────────────────────
    {
        "param_a": "Solar8000/ART_MBP",
        "param_b": "Orchestra/PPF20_RATE",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "Propofol-induced hypotension (MAP vs infusion rate)",
    },
    {
        "param_a": "Solar8000/ART_SBP",
        "param_b": "Orchestra/RFTN20_RATE",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "SBP–remifentanil infusion rate response",
    },
    {
        "param_a": "Solar8000/ART_MBP",
        "param_b": "Orchestra/RFTN20_CE",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "MAP–remifentanil effect-site concentration",
    },
    {
        "param_a": "Solar8000/ART_DBP",
        "param_b": "Solar8000/HR",
        "role_a": "independent",
        "role_b": "independent",
        "clinical_relation": "DBP–heart rate correlation",
    },
    # ── Anesthesia Depth ─────────────────────────────────────────────────────
    {
        "param_a": "BIS/BIS",
        "param_b": "Orchestra/PPF20_CE",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "Anesthesia depth–propofol effect-site concentration",
    },
    {
        "param_a": "BIS/BIS",
        "param_b": "Orchestra/RFTN20_CE",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "Anesthesia depth–remifentanil effect-site concentration",
    },
    {
        "param_a": "BIS/BIS",
        "param_b": "Solar8000/HR",
        "role_a": "condition",
        "role_b": "analysis",
        "clinical_relation": "Anesthesia depth–heart rate response",
    },
]

# All pairs are vital-only (Cross-Source removed)
MULTI_PAIRS: list[ParamPair] = MEDICAL_PARAM_PAIRS


# ---------------------------------------------------------------------------
# Quality Filter Configuration (Stage 4)
# ---------------------------------------------------------------------------

class FilterConfig:
    """Thresholds and limits for the four quality filters."""

    # Filter 1: param_key exposure check
    # Regex pattern that matches raw param_key format (e.g., "Solar8000/HR")
    PARAM_KEY_PATTERN: str = r"\b[A-Za-z0-9]+/[A-Za-z0-9_]+\b"

    # Filter 2: per-parameter coverage balance
    # Maximum times a single param_key may appear across all cases.
    MAX_CASES_PER_PARAM: int = int(os.getenv("LEVEL1_MAX_PER_PARAM", "8"))

    # Filter 3: semantic deduplication
    # Candidates with cosine similarity above this threshold vs. existing cases
    # are discarded.
    DEDUP_THRESHOLD: float = float(os.getenv("LEVEL1_DEDUP_THRESHOLD", "0.85"))

    # Embedding model for deduplication (OpenAI text-embedding)
    EMBEDDING_MODEL: str = os.getenv(
        "LEVEL1_EMBEDDING_MODEL", "text-embedding-3-small"
    )

    # Filter 4: LLM medical validity check
    # temperature=0 for reproducibility (LLM-as-a-Judge).
    VALIDITY_MODEL: str = os.getenv("LEVEL1_VALIDITY_MODEL", "gpt-4o")
    VALIDITY_TEMPERATURE: float = 0.0
    VALIDITY_MAX_TOKENS: int = 256


# ---------------------------------------------------------------------------
# Adversarial Case Configuration (Stage 5)
# ---------------------------------------------------------------------------

class AdversarialConfig:
    """Breakdown of the 20 adversarial target cases."""

    # How many of each sub-type to generate
    TARGET_AMBIGUOUS:  int = 7   # query is vague; expected: clarify
    TARGET_IMPOSSIBLE: int = 7   # parameter not in DB; expected: not_found
    TARGET_CONFUSING:  int = 6   # same physiological indicator, multiple devices

    # Oversampling for adversarial cases (same principle as normal cases)
    GENERATION_MULTIPLIER: int = 2

    @classmethod
    def total(cls) -> int:
        return cls.TARGET_AMBIGUOUS + cls.TARGET_IMPOSSIBLE + cls.TARGET_CONFUSING


# ---------------------------------------------------------------------------
# Minimum Acceptance Criteria (Stage 6)
# ---------------------------------------------------------------------------

class ValidationCriteria:
    """Hard constraints the final dataset must satisfy to pass Stage 6.

    Source: LEVEL1_DATASET.md Section 5, Stage 6.
    """

    # Minimum unique param_keys covered (≥ 15% of ~260 total)
    MIN_UNIQUE_PARAM_KEYS: int = int(os.getenv("LEVEL1_MIN_UNIQUE_PARAMS", "40"))

    # Every category must have at least this many cases
    MIN_CASES_PER_CATEGORY: int = 1

    # Categories excluded from the MIN_CASES_PER_CATEGORY check.
    # Current experiment uses vital signals only — no clinical/lab data sources.
    EXCLUDED_CATEGORIES: tuple = ("vital+clinical", "vital+lab")

    # Each query style must fall within [MIN_STYLE_PCT, MAX_STYLE_PCT] of total
    MIN_STYLE_PCT: float = 0.25
    MAX_STYLE_PCT: float = 0.40

    # All required_parameters must exist in the parameter table
    REQUIRE_DB_EXISTENCE: bool = True

    # No two queries may exceed dedup threshold
    REQUIRE_NO_DUPLICATES: bool = True


# ---------------------------------------------------------------------------
# DB connection (reuse shared config)
# ---------------------------------------------------------------------------

class DBConfig:
    """PostgreSQL connection settings (delegates to shared config)."""

    HOST:     str = os.getenv("POSTGRES_HOST", "localhost")
    PORT:     int = int(os.getenv("POSTGRES_PORT", "5432"))
    USER:     str = os.getenv("POSTGRES_USER", "postgres")
    PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
    DATABASE: str = os.getenv("POSTGRES_DB", "medical_data")

    @classmethod
    def dsn(cls) -> str:
        """psycopg2 DSN string."""
        return (
            f"host={cls.HOST} port={cls.PORT} dbname={cls.DATABASE} "
            f"user={cls.USER} password={cls.PASSWORD}"
        )


# ---------------------------------------------------------------------------
# Quick sanity check (run as script: python config.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Level 1 Pipeline Config ===")
    print(f"Base dir       : {Paths.BASE_DIR}")
    print(f"Output dir     : {Paths.OUTPUT_DIR}")
    print(f"Prompts dir    : {Paths.PROMPTS_DIR}")

    print(f"\n--- Batch Plan ---")
    total = 0
    for (qt, qs), count in GenerationConfig.BATCH_PLAN.items():
        print(f"  {qt.value:<25} × {qs.value:<15} → {count:>3} cases")
        total += count
    print(f"  {'Adversarial':<25}   {'(all styles)':<15} → {GenerationConfig.ADVERSARIAL_TARGET:>3} cases")
    print(f"  {'TOTAL':<43} → {total + GenerationConfig.ADVERSARIAL_TARGET:>3} cases")

    print(f"\n--- Generation Settings ---")
    print(f"  Model            : {GenerationConfig.GENERATION_MODEL}")
    print(f"  Temperature      : {GenerationConfig.GENERATION_TEMPERATURE}")
    print(f"  Multiplier       : {GenerationConfig.GENERATION_MULTIPLIER}×")
    print(f"  Params per batch : {GenerationConfig.PARAMS_PER_BATCH}  (Single-* types)")
    print(f"  Queries per pair : {GenerationConfig.QUERIES_PER_PAIR}  (Multi-* types)")
    print(f"\n--- Parameter Pairs (vital only) ---")
    print(f"  Multi-* : {len(MULTI_PAIRS)} pairs")
    for p in MULTI_PAIRS:
        print(f"    {p['param_a']:<30} × {p['param_b']:<25} — {p['clinical_relation']}")

    print(f"\n--- Filter Thresholds ---")
    print(f"  Dedup          : cosine > {FilterConfig.DEDUP_THRESHOLD}")
    print(f"  Max/param      : {FilterConfig.MAX_CASES_PER_PARAM} cases")
    print(f"  Validity model : {FilterConfig.VALIDITY_MODEL} (temp={FilterConfig.VALIDITY_TEMPERATURE})")

    print(f"\n--- Validation Criteria ---")
    print(f"  Min unique params : {ValidationCriteria.MIN_UNIQUE_PARAM_KEYS}")
    print(f"  Style range       : {ValidationCriteria.MIN_STYLE_PCT*100:.0f}–{ValidationCriteria.MAX_STYLE_PCT*100:.0f}%")

    print(f"\n--- DB ---")
    print(f"  Host : {DBConfig.HOST}:{DBConfig.PORT}")
    print(f"  DB   : {DBConfig.DATABASE} (user={DBConfig.USER})")
