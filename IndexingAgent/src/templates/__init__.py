# src/templates/__init__.py
"""
LLM Prompt Templates

Centralized prompt management for consistency and easy updates.
"""

from src.templates.prompts import (
    # Column Analysis
    COLUMN_ANALYSIS_PROMPT,
    # Track Analysis
    TRACK_ANALYSIS_PROMPT,
    # Metadata Detection
    METADATA_DETECTION_PROMPT,
    # Anchor Detection
    ANCHOR_COMPARISON_PROMPT,
    # Relationship Inference
    RELATIONSHIP_INFERENCE_PROMPT,
    # Filename Analysis
    FILENAME_ANALYSIS_PROMPT,
    # Human Review
    REVIEW_DECISION_PROMPT,
    FEEDBACK_PARSING_PROMPT,
    # Question Generation
    QUESTION_GENERATION_PROMPT,
)

__all__ = [
    "COLUMN_ANALYSIS_PROMPT",
    "TRACK_ANALYSIS_PROMPT",
    "METADATA_DETECTION_PROMPT",
    "ANCHOR_COMPARISON_PROMPT",
    "RELATIONSHIP_INFERENCE_PROMPT",
    "FILENAME_ANALYSIS_PROMPT",
    "REVIEW_DECISION_PROMPT",
    "FEEDBACK_PARSING_PROMPT",
    "QUESTION_GENERATION_PROMPT",
]

