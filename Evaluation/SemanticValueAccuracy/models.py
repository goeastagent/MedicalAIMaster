"""
Evaluation/SemanticValueAccuracy/models.py

Pydantic data models for the SVA (Semantic Value Accuracy) evaluation pipeline.

Model hierarchy:
  Enums              — QueryCategory, QueryStyle, AnswerType, ExpectedBehavior
  ResolutionTarget   — equivalence group + distractors + rationale
  GroundTruthLogic   — executable Python code for GT computation
  SVACase            — one complete dataset entry (query + resolution + GT)
  SVACaseCandidate   — intermediate LLM output before GT is verified (Stage 2)
  SVAResult          — evaluation result for a single case × scenario
  SVAMetrics         — aggregated metrics across all cases
  ValidationReport   — dataset quality summary (Stage 5 output)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class QueryCategory(str, Enum):
    """SVA query category taxonomy (doc Section 3-2)."""
    SEMANTIC_RESOLUTION = "semantic_resolution"
    CROSS_DEVICE = "cross_device"
    COHORT_SIGNAL_JOIN = "cohort_signal_join"
    ONTOLOGY_BASED = "ontology_based"
    ADVERSARIAL_SEMANTIC = "adversarial_semantic"


class QueryStyle(str, Enum):
    """Expression style within each category."""
    # semantic_resolution
    CLINICAL = "clinical"
    ABBREVIATION = "abbreviation"
    DESCRIPTIVE = "descriptive"
    # cross_device
    IMPLICIT_PREFERENCE = "implicit_preference"
    EXPLICIT_DEVICE_HINT = "explicit_device_hint"
    MULTI_SOURCE_COMPARE = "multi_source_compare"
    # cohort_signal_join
    FILTER_THEN_AGGREGATE = "filter_then_aggregate"
    CONDITIONAL_CROSS_DATA = "conditional_cross_data"
    RANKED_SELECTION = "ranked_selection"
    # ontology_based
    CATEGORY_AGGREGATE = "category_aggregate"
    CATEGORY_DISCOVERY = "category_discovery"
    RELATIONSHIP_BASED = "relationship_based"
    # adversarial_semantic
    NONEXISTENT_CONCEPT = "nonexistent_concept"
    MISLEADING_DEVICE_HINT = "misleading_device_hint"
    AMBIGUOUS_SCOPE = "ambiguous_scope"


class AnswerType(str, Enum):
    """Expected answer value type (doc Section 4-5)."""
    NUMBER = "number"
    DICT = "dict"
    LIST = "list"
    NULL = "null"


class ExpectedBehavior(str, Enum):
    """What the agent is expected to do."""
    RETRIEVE = "retrieve"
    NOT_FOUND = "not_found"
    CLARIFY = "clarify"


# ---------------------------------------------------------------------------
# Category → valid styles mapping
# ---------------------------------------------------------------------------

CATEGORY_STYLES: Dict[QueryCategory, List[QueryStyle]] = {
    QueryCategory.SEMANTIC_RESOLUTION: [
        QueryStyle.CLINICAL, QueryStyle.ABBREVIATION, QueryStyle.DESCRIPTIVE,
    ],
    QueryCategory.CROSS_DEVICE: [
        QueryStyle.IMPLICIT_PREFERENCE, QueryStyle.EXPLICIT_DEVICE_HINT,
        QueryStyle.MULTI_SOURCE_COMPARE,
    ],
    QueryCategory.COHORT_SIGNAL_JOIN: [
        QueryStyle.FILTER_THEN_AGGREGATE, QueryStyle.CONDITIONAL_CROSS_DATA,
        QueryStyle.RANKED_SELECTION,
    ],
    QueryCategory.ONTOLOGY_BASED: [
        QueryStyle.CATEGORY_AGGREGATE, QueryStyle.CATEGORY_DISCOVERY,
        QueryStyle.RELATIONSHIP_BASED,
    ],
    QueryCategory.ADVERSARIAL_SEMANTIC: [
        QueryStyle.NONEXISTENT_CONCEPT, QueryStyle.MISLEADING_DEVICE_HINT,
        QueryStyle.AMBIGUOUS_SCOPE,
    ],
}


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class ResolutionTarget(BaseModel):
    """Parameter resolution ground truth (doc Section 4-3)."""

    equivalence_group: List[str] = Field(
        default_factory=list,
        description="Medically equivalent param_keys. Any selection scores 1.0.",
    )
    distractors: List[str] = Field(
        default_factory=list,
        description="Similar-looking but incorrect param_keys.",
    )
    resolution_rationale: str = Field(
        description="English explanation of equivalence group composition.",
    )
    expected_behavior: ExpectedBehavior = Field(
        default=ExpectedBehavior.RETRIEVE,
    )

    # cohort_signal_join specific
    cohort_filter: Optional[str] = None
    cohort_source: Optional[str] = None
    join_key: Optional[str] = None
    expected_matching_cases: Optional[List[str]] = None

    # ontology_based specific
    device_group_filter: Optional[str] = None
    functional_filter: Optional[str] = None

    @model_validator(mode="after")
    def adversarial_has_empty_group(self) -> "ResolutionTarget":
        if self.expected_behavior == ExpectedBehavior.NOT_FOUND:
            if self.equivalence_group:
                raise ValueError(
                    "expected_behavior='not_found' requires empty equivalence_group."
                )
        return self


class GroundTruthLogic(BaseModel):
    """Executable Python code for GT computation."""
    language: str = "python"
    code: str


# ---------------------------------------------------------------------------
# Core dataset model
# ---------------------------------------------------------------------------

class SVACase(BaseModel):
    """A single SVA evaluation dataset entry (doc Section 4-1)."""

    id: str = Field(description="Unique ID. Format: sva_{category}_{NNN}")
    query_category: QueryCategory
    query_style: QueryStyle
    query: str = Field(min_length=10, description="Semantic query (no track names).")
    answer_type: AnswerType

    resolution_target: ResolutionTarget
    ground_truth_logic: GroundTruthLogic
    equivalence_values: Dict[str, Any] = Field(
        default_factory=dict,
        description="param_key → GT computed value for each equivalence_group member.",
    )

    is_verified_by_execution: bool = False
    verification_timestamp: Optional[str] = None

    # quality audit metadata (populated by Stage 4)
    audit_scores: Optional[Dict[str, int]] = None
    audit_score_avg: Optional[float] = None

    @model_validator(mode="after")
    def style_matches_category(self) -> "SVACase":
        valid = CATEGORY_STYLES.get(self.query_category, [])
        if valid and self.query_style not in valid:
            raise ValueError(
                f"query_style '{self.query_style.value}' is not valid for "
                f"category '{self.query_category.value}'. "
                f"Valid styles: {[s.value for s in valid]}"
            )
        return self


# ---------------------------------------------------------------------------
# Intermediate pipeline model (Stage 2 output, before GT verification)
# ---------------------------------------------------------------------------

class SVACaseCandidate(BaseModel):
    """Raw LLM output from Stage 2 before GT code is generated."""

    query: str
    query_category: QueryCategory
    query_style: QueryStyle
    answer_type: AnswerType
    resolution_target: ResolutionTarget
    generation_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Evaluation result models
# ---------------------------------------------------------------------------

class SVAResult(BaseModel):
    """Evaluation result for a single case × scenario."""

    case_id: str
    scenario: str  # "VitalAgent" or "Claude-Code-CLI"
    query: str
    equivalence_values: Dict[str, Any]
    answer_type: AnswerType = AnswerType.NUMBER

    agent_output: Any = None
    resolved_params: Optional[List[str]] = None
    generated_code: Optional[str] = None
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    code_executed: bool = False

    # scores (populated by scoring.py)
    resolution_score: float = 0.0
    resolution_detail: str = ""
    execution_score: float = 0.0
    execution_detail: str = ""
    value_score: float = 0.0
    value_detail: str = ""
    composite_score: float = 0.0


class SVAMetrics(BaseModel):
    """Aggregated metrics across all cases for one scenario."""

    scenario: str
    n_cases: int
    resolution_accuracy: float = 0.0
    execution_rate: float = 0.0
    value_accuracy: float = 0.0
    composite_score: float = 0.0
    avg_time_ms: float = 0.0

    # breakdown by category
    category_breakdown: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    # breakdown by style
    style_breakdown: Dict[str, Dict[str, float]] = Field(default_factory=dict)

    # resolution detail distribution
    resolution_distribution: Dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation / reporting model (Stage 5 output)
# ---------------------------------------------------------------------------

class ValidationReport(BaseModel):
    """Dataset quality summary produced by Stage 5."""

    generation_timestamp: str
    total_generated: int
    total_after_filter: int
    total_final: int

    category_distribution: Dict[str, int] = Field(default_factory=dict)
    style_distribution: Dict[str, int] = Field(default_factory=dict)
    unique_equivalence_params: int = 0
    execution_verified_pct: float = 0.0
    null_value_ratio: float = 0.0

    filter_stats: Dict[str, int] = Field(default_factory=dict)

    validation_checks: Dict[str, str] = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)

    @property
    def passes_minimum_criteria(self) -> bool:
        return len(self.issues) == 0

    def print_summary(self) -> None:
        status = "PASS" if self.passes_minimum_criteria else "FAIL"
        print(f"\n{'='*60}")
        print(f"  SVA Dataset Validation — {status}")
        print(f"{'='*60}")
        print(f"  Generated        : {self.total_generated}")
        print(f"  After filtering  : {self.total_after_filter}")
        print(f"  Final dataset    : {self.total_final}")
        print(f"  Unique params    : {self.unique_equivalence_params}")
        print(f"  Verified         : {self.execution_verified_pct:.1f}%")
        print(f"  Null ratio       : {self.null_value_ratio:.1%}")
        print(f"\n  Category distribution:")
        for k, v in sorted(self.category_distribution.items()):
            print(f"    {k:<25} {v:>3}")
        print(f"\n  Filter stats:")
        for k, v in sorted(self.filter_stats.items()):
            print(f"    {k:<30} {v:>3} removed")
        if self.issues:
            print(f"\n  Issues:")
            for issue in self.issues:
                print(f"    ✗ {issue}")
        print(f"{'='*60}\n")
