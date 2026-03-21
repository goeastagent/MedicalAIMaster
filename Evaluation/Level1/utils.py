"""Shared helpers for the Level 1 evaluation pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel

from Evaluation.Level1.models import (
    Category,
    ParamSource,
    SynonymEntry,
    infer_param_source,
)


def load_synonym_map(path: Path) -> Dict[str, SynonymEntry]:
    """Load synonym_map.json into dict[param_key, SynonymEntry]."""
    if not path.exists():
        raise FileNotFoundError(
            f"synonym_map.json not found at {path}. Run Stage 1 first."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: SynonymEntry(**v) for k, v in raw.items()}


def append_jsonl(path: Path, item: BaseModel) -> None:
    """Append a single Pydantic model as one JSON line."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(item.model_dump_json() + "\n")


def infer_category(required_parameters: List[str]) -> Category:
    """Derive Category from required_parameters via ParamSource.

    Used in Stage 6 when promoting QueryCandidate → Level1Case.
    Returns ADVERSARIAL when required_parameters is empty (source is None).
    """
    source = infer_param_source(required_parameters)
    if source is None:
        return Category.ADVERSARIAL
    mapping = {
        ParamSource.SIGNAL: Category.VITAL_ONLY,
        ParamSource.TABULAR_CLINICAL: Category.VITAL_CLINICAL,
        ParamSource.TABULAR_LAB: Category.VITAL_LAB,
        ParamSource.MIXED: Category.VITAL_CLINICAL,
    }
    return mapping.get(source, Category.VITAL_ONLY)
