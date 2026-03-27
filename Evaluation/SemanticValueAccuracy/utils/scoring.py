"""
Evaluation/SemanticValueAccuracy/utils/scoring.py

3-Layer Scoring System for SVA evaluation.

  Layer 1: Parameter Resolution Score  — correct semantic interpretation?
  Layer 2: Execution Score             — code ran without errors?
  Layer 3: Value Accuracy Score        — final value matches ground truth?

  Composite = 0.4 * Resolution + 0.2 * Execution + 0.4 * Value
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from Evaluation.SemanticValueAccuracy.config import ScoringWeights


# ---------------------------------------------------------------------------
# Layer 1: Parameter Resolution
# ---------------------------------------------------------------------------

def score_resolution(case: Dict, resolved_params: Optional[List[str]], agent_output: Any, error: Optional[str]) -> Tuple[float, str]:
    """Score parameter resolution (Layer 1).

    Returns (score, detail_label).
    """
    target = case.get("resolution_target", {})
    eq_group = set(target.get("equivalence_group", []))
    expected_behavior = target.get("expected_behavior", "retrieve")

    # Adversarial (empty equivalence_group or not_found)
    if expected_behavior in ("not_found", "clarify") or len(eq_group) == 0:
        if agent_output is None or error:
            return 1.0, "correct_rejection"
        else:
            return 0.0, "hallucination"

    used = set(resolved_params or [])

    if not used:
        return 0.0, "not_attempted"
    if used <= eq_group:
        return 1.0, "correct"
    if used & eq_group:
        return 0.5, "partial_match"
    return 0.0, "wrong_param"


# ---------------------------------------------------------------------------
# Layer 2: Execution
# ---------------------------------------------------------------------------

def score_execution(
    agent_output: Any,
    error: Optional[str],
    expected_behavior: str = "retrieve",
    code_executed: bool = False,
) -> Tuple[float, str]:
    """Score code execution success (Layer 2).

    Args:
        code_executed: True if code was actually run (even if result is None).
                       Distinguishes "code ran, returned None" from "no code ran".

    Returns (score, detail_label).
    """
    if error:
        if "timeout" in error.lower():
            return 0.0, "timeout"
        return 0.0, "runtime_error"

    if agent_output is None:
        if expected_behavior in ("not_found", "clarify"):
            return 1.0, "correct_null"
        if code_executed:
            return 1.0, "success_null"
        return 0.0, "no_output"

    return 1.0, "success"


# ---------------------------------------------------------------------------
# Layer 3: Value Accuracy
# ---------------------------------------------------------------------------

def compare_values(expected: Any, actual: Any, answer_type: str = "number") -> bool:
    """Compare expected vs actual value based on answer_type."""
    # Try to parse string responses
    if isinstance(actual, str):
        try:
            parsed = json.loads(actual.replace("'", '"'))
            if isinstance(parsed, dict) and "answer" in parsed:
                actual = parsed["answer"]
            else:
                actual = parsed
        except Exception:
            pass

    if answer_type == "null":
        return (
            actual is None
            or actual == "None"
            or actual == "null"
            or (isinstance(actual, (list, dict)) and len(actual) == 0)
        )

    if answer_type == "number":
        try:
            return abs(float(expected) - float(actual)) < ScoringWeights.VALUE_TOLERANCE
        except (ValueError, TypeError):
            return False

    if answer_type == "dict":
        return _deep_compare_dict(expected, actual)

    if answer_type == "list":
        return _deep_compare_list(expected, actual)

    return str(expected) == str(actual)


def _deep_compare_dict(expected: dict, actual: Any) -> bool:
    if not isinstance(expected, dict):
        return False
    if not isinstance(actual, dict):
        try:
            actual = json.loads(str(actual).replace("'", '"'))
        except Exception:
            return False
    if set(expected.keys()) != set(actual.keys()):
        return False
    return all(_compare_element(expected[k], actual.get(k)) for k in expected)


def _deep_compare_list(expected: list, actual: Any) -> bool:
    if not isinstance(expected, list):
        return False
    if not isinstance(actual, list):
        try:
            actual = json.loads(str(actual).replace("'", '"'))
        except Exception:
            return False
    if len(expected) != len(actual):
        return False
    return all(_compare_element(e, a) for e, a in zip(expected, actual))


def _compare_element(expected_elem: Any, actual_elem: Any) -> bool:
    if isinstance(expected_elem, (int, float)):
        try:
            return abs(float(expected_elem) - float(actual_elem)) < ScoringWeights.VALUE_TOLERANCE
        except (ValueError, TypeError):
            return False
    if isinstance(expected_elem, dict):
        return _deep_compare_dict(expected_elem, actual_elem)
    if isinstance(expected_elem, list):
        return _deep_compare_list(expected_elem, actual_elem)
    return str(expected_elem).strip().lower() == str(actual_elem).strip().lower()


def score_value(case: Dict, agent_output: Any, answer_type: str = "number") -> Tuple[float, str]:
    """Score value accuracy (Layer 3).

    Returns (score, detail_label).
    """
    eq_values = case.get("equivalence_values", {})

    # Adversarial / null
    if not eq_values or answer_type == "null":
        if compare_values(None, agent_output, "null"):
            return 1.0, "null_match"
        return 0.0, "mismatch"

    # If all equivalence values are None (parameter absent from vital files),
    # a None agent output is the correct answer.
    if all(v is None for v in eq_values.values()):
        if agent_output is None:
            return 1.0, "null_match (absent_param)"
        return 0.0, "mismatch"

    # Check against every equivalence value
    for param_key, expected_val in eq_values.items():
        if expected_val is not None and compare_values(expected_val, agent_output, answer_type):
            return 1.0, f"match ({param_key})"

    return 0.0, "mismatch"


# ---------------------------------------------------------------------------
# Composite Score
# ---------------------------------------------------------------------------

def compute_composite(resolution: float, execution: float, value: float) -> float:
    return (
        ScoringWeights.RESOLUTION * resolution
        + ScoringWeights.EXECUTION * execution
        + ScoringWeights.VALUE * value
    )


# ---------------------------------------------------------------------------
# Param extraction from code
# ---------------------------------------------------------------------------

def extract_params_from_code(code: str) -> List[str]:
    """Extract param_keys from to_numpy() calls in Python code."""
    pattern = r"to_numpy\(\s*\[([^\]]+)\]"
    matches = re.findall(pattern, code)
    params = set()
    for match in matches:
        strings = re.findall(r"['\"]([^'\"]+)['\"]", match)
        params.update(strings)
    return sorted(params)


def parse_agent_answer(raw_output: Any) -> Any:
    """Parse agent output to extract the answer value."""
    if raw_output is None:
        return None

    if isinstance(raw_output, (int, float, list)):
        return raw_output

    if isinstance(raw_output, dict):
        if "answer" in raw_output:
            return raw_output["answer"]
        if "result" in raw_output:
            return raw_output["result"]
        return raw_output

    if isinstance(raw_output, str):
        raw_output = raw_output.strip()
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                if "answer" in parsed:
                    return parsed["answer"]
                if "result" in parsed:
                    return parsed["result"]
                return parsed
            return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        # Try to find JSON in the string
        json_match = re.search(r'\{[^{}]*\}', raw_output)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                if "answer" in parsed:
                    return parsed["answer"]
                return parsed
            except Exception:
                pass

    return raw_output
