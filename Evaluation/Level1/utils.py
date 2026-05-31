"""Shared helpers for the Level 1 evaluation pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel

from Evaluation.Level1.models import (
    Category,
    ParamSource,
    SynonymEntry,
    infer_param_source,
)

_VITAL_SIGNAL_PARAM_KEY_RE = re.compile(r"^[A-Za-z0-9_]+/[A-Za-z0-9_]+$")


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


def is_vital_signal_param_key(param_key: str) -> bool:
    """Return True when the key matches the Device/Signal vital track format."""
    return bool(_VITAL_SIGNAL_PARAM_KEY_RE.fullmatch(param_key or ""))


def all_params_are_vital_signals(required_parameters: List[str]) -> bool:
    """Return True when all required params are valid vital track keys."""
    return all(is_vital_signal_param_key(pk) for pk in required_parameters)


def infer_category(required_parameters: List[str]) -> Category:
    """Derive Category for the vital-only Level 1 benchmark.

    Used in Stage 6 when promoting QueryCandidate → Level1Case.
    Returns ADVERSARIAL when required_parameters is empty (source is None).
    """
    source = infer_param_source(required_parameters)
    if source is None:
        return Category.ADVERSARIAL
    if source != ParamSource.SIGNAL or not all_params_are_vital_signals(required_parameters):
        raise ValueError(
            "Level1 generation is configured for vital-only cases; "
            f"unsupported required_parameters={required_parameters!r}"
        )
    return Category.VITAL_ONLY
