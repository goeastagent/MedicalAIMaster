"""
Evaluation/Level1/models.py

Pydantic data models for the Level 1 (Indexing & Retrieval) evaluation dataset.

Model hierarchy:
  Enums          — QueryType, QueryStyle, Category, ExpectedBehavior, ParamSource
  GroundTruth    — expected output for a single query
  Level1Case     — one complete dataset entry (query + ground truth + metadata)
  QueryCandidate — intermediate LLM output before ground truth is attached (Stage 2)
  SynonymEntry   — synonym map entry for one param_key (Stage 1 output)
  ValidationReport — final dataset quality summary (Stage 6 output)
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QueryType(str, Enum):
    """Query complexity taxonomy (Section 3-1 of LEVEL1_DATASET.md).

    Replaces the `difficulty` field — difficulty is derived from this value.
    """
    SINGLE_DIRECT       = "Single-Direct"
    SINGLE_SEMANTIC     = "Single-Semantic"
    SINGLE_ABBREVIATION = "Single-Abbreviation"
    MULTI_INDEPENDENT   = "Multi-Independent"
    MULTI_CONDITIONAL   = "Multi-Conditional"
    ADVERSARIAL         = "Adversarial"


class QueryStyle(str, Enum):
    """Persona-based expression style (Section 3-2)."""
    DOCTOR          = "doctor"
    DATA_SCIENTIST  = "data_scientist"
    LAYPERSON       = "layperson"


class Category(str, Enum):
    """Data source category.

    Retained as an explicit field because `vital+clinical` vs `vital+lab`
    cannot be distinguished from query_type alone — it depends on which
    specific parameters appear in required_parameters.
    """
    VITAL_ONLY      = "vital_only"
    VITAL_CLINICAL  = "vital+clinical"
    VITAL_LAB       = "vital+lab"
    ADVERSARIAL     = "adversarial"


class ExpectedBehavior(str, Enum):
    """What the retrieval system is expected to return."""
    RETRIEVE    = "retrieve"    # return matched param_keys
    NOT_FOUND   = "not_found"   # parameter does not exist in DB
    CLARIFY     = "clarify"     # query is ambiguous; system must ask for clarification


class ParamSource(str, Enum):
    """Physical location of the required parameters."""
    SIGNAL           = "signal"           # .vital files
    TABULAR_CLINICAL = "tabular_clinical" # clinical_data.csv
    TABULAR_LAB      = "tabular_lab"      # lab_data.csv
    MIXED            = "mixed"            # multiple sources


# ---------------------------------------------------------------------------
# Derived helpers
# ---------------------------------------------------------------------------

#: Maps QueryType → difficulty label (used for reporting only)
DIFFICULTY_MAP: Dict[QueryType, str] = {
    QueryType.SINGLE_DIRECT:       "easy",
    QueryType.SINGLE_SEMANTIC:     "easy",
    QueryType.SINGLE_ABBREVIATION: "medium",
    QueryType.MULTI_INDEPENDENT:   "medium",
    QueryType.MULTI_CONDITIONAL:   "hard",
    QueryType.ADVERSARIAL:         "hard",
}

#: Clinical parameter key prefixes that indicate tabular_clinical source
CLINICAL_PARAM_PREFIXES = (
    "intraop_", "preop_", "postop_", "ane_", "optype", "approach",
)

#: Lab parameter key prefixes that indicate tabular_lab source.
#: NOTE: Short prefixes ("k", "na", "ca") may cause false positives if
#: signal param_keys share the same prefix. Refine if needed.
LAB_PARAM_PREFIXES = (
    "hb", "wbc", "plt", "cr", "bun", "na", "k", "ca", "glucose",
    "alb", "ast", "alt", "tbil",
)


def infer_param_source(required_parameters: List[str]) -> Optional[ParamSource]:
    """Derive ParamSource from a list of param_keys.

    Returns None when required_parameters is empty (e.g. adversarial cases).
    """
    if not required_parameters:
        return None

    has_signal   = False
    has_clinical = False
    has_lab      = False

    for key in required_parameters:
        lower = key.lower()
        if any(lower.startswith(p) for p in CLINICAL_PARAM_PREFIXES):
            has_clinical = True
        elif any(lower.startswith(p) for p in LAB_PARAM_PREFIXES):
            has_lab = True
        else:
            has_signal = True

    sources = sum([has_signal, has_clinical, has_lab])
    if sources > 1:
        return ParamSource.MIXED
    if has_clinical:
        return ParamSource.TABULAR_CLINICAL
    if has_lab:
        return ParamSource.TABULAR_LAB
    return ParamSource.SIGNAL


# ---------------------------------------------------------------------------
# Core dataset models
# ---------------------------------------------------------------------------

class GroundTruth(BaseModel):
    """Expected retrieval output for a single query."""

    required_parameters: List[str] = Field(
        default_factory=list,
        description="Exact param_keys the system must return.",
    )
    acceptable_alternatives: Dict[str, List[str]] = Field(
        default_factory=dict,
        description=(
            "Per-parameter alternatives that are also accepted as correct. "
            "Key = required param_key, value = list of interchangeable param_keys. "
            "Only populated when the query does not specify a particular device."
        ),
    )
    expected_behavior: ExpectedBehavior = Field(
        default=ExpectedBehavior.RETRIEVE,
        description="What the retrieval system should do with this query.",
    )
    retrieval_notes: Optional[str] = Field(
        default=None,
        description="Human-readable annotation for auditing or debugging.",
    )

    @field_validator("acceptable_alternatives")
    @classmethod
    def alternatives_keys_must_be_in_required(
        cls, v: Dict[str, List[str]], info
    ) -> Dict[str, List[str]]:
        """Every key in acceptable_alternatives must be a required_parameter."""
        required = info.data.get("required_parameters", [])
        for key in v:
            if key not in required:
                raise ValueError(
                    f"acceptable_alternatives key '{key}' is not in required_parameters."
                )
        return v

    @model_validator(mode="after")
    def not_found_has_empty_required(self) -> "GroundTruth":
        """not_found / clarify cases must have an empty required_parameters list."""
        if self.expected_behavior in (
            ExpectedBehavior.NOT_FOUND,
            ExpectedBehavior.CLARIFY,
        ):
            if self.required_parameters:
                raise ValueError(
                    f"expected_behavior='{self.expected_behavior.value}' requires "
                    "required_parameters to be empty."
                )
        return self


class Level1Case(BaseModel):
    """A single Level 1 evaluation dataset entry."""

    id: str = Field(
        description="Unique identifier. Format: 'L1-001' or 'L1-ADV-001'.",
    )
    category: Category = Field(
        description="Data source category.",
    )
    query_type: QueryType = Field(
        description="Query complexity type. Replaces the old 'difficulty' field.",
    )
    query_style: QueryStyle = Field(
        description="Persona-based expression style.",
    )
    num_required_params: int = Field(
        ge=0,
        description="Number of param_keys in ground_truth.required_parameters.",
    )
    query: str = Field(
        min_length=5,
        description="Natural language query in English.",
    )
    ground_truth: GroundTruth

    # ---- derived / read-only properties ----

    @property
    def difficulty(self) -> str:
        """Derived from query_type. For reporting use only."""
        return DIFFICULTY_MAP[self.query_type]

    @property
    def param_source(self) -> Optional[ParamSource]:
        """Derived from ground_truth.required_parameters. None for adversarial."""
        return infer_param_source(self.ground_truth.required_parameters)

    # ---- validators ----

    @model_validator(mode="after")
    def num_params_matches_required(self) -> "Level1Case":
        """num_required_params must match len(ground_truth.required_parameters)."""
        expected = len(self.ground_truth.required_parameters)
        if self.num_required_params != expected:
            raise ValueError(
                f"num_required_params={self.num_required_params} does not match "
                f"len(required_parameters)={expected}."
            )
        return self

    @model_validator(mode="after")
    def adversarial_category_matches_type(self) -> "Level1Case":
        """category='adversarial' ↔ query_type='Adversarial' must be consistent."""
        is_adv_cat  = self.category == Category.ADVERSARIAL
        is_adv_type = self.query_type == QueryType.ADVERSARIAL
        if is_adv_cat != is_adv_type:
            raise ValueError(
                "category='adversarial' and query_type='Adversarial' must both be "
                "set or both be unset."
            )
        return self

    def to_dict(self) -> dict:
        """Serialise to plain dict, including derived fields."""
        d = self.model_dump()
        d["difficulty"]   = self.difficulty
        d["param_source"] = self.param_source.value if self.param_source else None
        return d


# ---------------------------------------------------------------------------
# Intermediate pipeline models
# ---------------------------------------------------------------------------

class QueryCandidate(BaseModel):
    """Raw LLM output from Stage 2 before ground truth is attached (Stage 3)."""

    query: str
    required_parameters: List[str]
    query_type: QueryType
    query_style: QueryStyle
    generation_notes: Optional[str] = None

    # populated by Stage 3
    ground_truth: Optional[GroundTruth] = None


class SynonymEntry(BaseModel):
    """Synonym map entry for a single param_key (Stage 1 LLM output)."""

    param_key: str = Field(description="Exact param_key from the parameter table.")
    semantic_name: Optional[str] = Field(default=None)
    unit: Optional[str] = Field(default=None)
    concept_category: Optional[str] = Field(default=None)

    # LLM-generated synonym groups
    direct: List[str] = Field(
        default_factory=list,
        description="Raw param_key variants and common abbreviations.",
    )
    semantic_en: List[str] = Field(
        default_factory=list,
        description="Full English clinical expressions.",
    )
    medical_term: List[str] = Field(
        default_factory=list,
        description="Medical / physiological terminology.",
    )
    abbreviation: List[str] = Field(
        default_factory=list,
        description="Short abbreviations used in clinical practice.",
    )

    def all_expressions(self) -> List[str]:
        """Return deduplicated union of all synonym groups."""
        seen: set = set()
        result: List[str] = []
        for expr in (
            self.direct
            + self.semantic_en
            + self.medical_term
            + self.abbreviation
        ):
            if expr and expr not in seen:
                seen.add(expr)
                result.append(expr)
        return result


# ---------------------------------------------------------------------------
# Validation / reporting model
# ---------------------------------------------------------------------------

class ValidationReport(BaseModel):
    """Dataset quality summary produced by Stage 6."""

    total: int
    param_coverage: int = Field(description="Number of unique param_keys used.")

    category_distribution: Dict[str, int] = Field(
        description="Case count per Category value.",
    )
    query_type_distribution: Dict[str, int] = Field(
        description="Case count per QueryType value.",
    )
    style_distribution: Dict[str, int] = Field(
        description="Case count per QueryStyle value.",
    )

    db_existence_check: bool = Field(
        description="True if every required_parameter exists in the DB.",
    )
    dedup_check: bool = Field(
        description="True if no two queries have cosine similarity > dedup threshold.",
    )

    issues: List[str] = Field(
        default_factory=list,
        description="List of failed criteria descriptions.",
    )

    @property
    def passes_minimum_criteria(self) -> bool:
        """True only when all hard constraints are satisfied."""
        return len(self.issues) == 0

    def print_summary(self) -> None:
        status = "PASS" if self.passes_minimum_criteria else "FAIL"
        print(f"\n{'='*60}")
        print(f"  Level 1 Dataset Validation — {status}")
        print(f"{'='*60}")
        print(f"  Total cases      : {self.total}")
        print(f"  Param coverage   : {self.param_coverage} unique param_keys")
        print(f"  DB existence     : {'OK' if self.db_existence_check else 'FAIL'}")
        print(f"  Dedup check      : {'OK' if self.dedup_check else 'FAIL'}")
        print(f"\n  Category distribution:")
        for k, v in sorted(self.category_distribution.items()):
            print(f"    {k:<20} {v:>4}")
        print(f"\n  Query type distribution:")
        for k, v in sorted(self.query_type_distribution.items()):
            print(f"    {k:<25} {v:>4}")
        print(f"\n  Style distribution:")
        for k, v in sorted(self.style_distribution.items()):
            print(f"    {k:<20} {v:>4}")
        if self.issues:
            print(f"\n  Issues:")
            for issue in self.issues:
                print(f"    ✗ {issue}")
        print(f"{'='*60}\n")
