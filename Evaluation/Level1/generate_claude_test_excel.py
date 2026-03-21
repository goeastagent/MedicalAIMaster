"""
Evaluation/Level1/generate_claude_test_excel.py

Generates a test Excel file for Claude Code based on level1_dataset.json.
Appends a specific instruction to the query:
"Please explicitly state the expected parameter names in your response."

The output structure matches the 'Detail' sheet of the standard evaluation report.
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Import config to get paths
import sys
sys.path.insert(0, str(Path(__file__).parents[2]))
from Evaluation.Level1.config import Paths

# Columns from test_level1_dataset.py
COLUMNS = [
    "scenario",
    "case_id",
    "query_type",
    "query_type_desc",
    "query_style",
    "difficulty",
    "category",
    "query",
    "expected_params",
    "retrieved_params",
    "expected_behavior",
    "detected_behavior",
    "recall",
    "precision",
    "f1",
    "behavior_match",
    "time_ms",
    "error",
]

QUERY_TYPE_DESC = {
    "Single-Direct":       "param_key가 쿼리에 직접 노출된 단일 파라미터 검색",
    "Single-Semantic":     "param_key 없이 의미/임상 표현으로 단일 파라미터 검색",
    "Single-Abbreviation": "약어나 축약형으로 단일 파라미터 검색",
    "Multi-Independent":   "서로 독립적인 2개 이상 파라미터 동시 검색",
    "Multi-Conditional":   "한 파라미터의 조건에 따라 다른 파라미터를 분석",
    "Adversarial":         "모호하거나 존재하지 않는 파라미터 요청 (clarify/not_found 기대)",
}

INSTRUCTION_SUFFIX = ""

def main():
    # 1. Load dataset
    if not Paths.FINAL_DATASET.exists():
        print(f"Error: {Paths.FINAL_DATASET} not found. Run the pipeline first.")
        return

    with open(Paths.FINAL_DATASET, "r", encoding="utf-8") as f:
        cases = json.load(f)
    
    print(f"Loaded {len(cases)} cases from {Paths.FINAL_DATASET}")

    # 2. Process cases
    rows = []
    for case in cases:
        # Format query with explicit instruction
        original_query = case["query"]
        modified_query = (
            f"Query: {original_query.strip()}\n\n"
            "Response Format:\n"
            "Please provide a list of the expected parameter names."
        )
        
        gt = case.get("ground_truth", {})
        required_params = gt.get("required_parameters", [])
        expected_behavior = gt.get("expected_behavior", "")

        row = {
            "scenario": "Claude-Code-Test",
            "case_id": case["id"],
            "query_type": case.get("query_type", ""),
            "query_type_desc": QUERY_TYPE_DESC.get(case.get("query_type", ""), ""),
            "query_style": case.get("query_style", ""),
            "difficulty": case.get("difficulty", ""),
            "category": case.get("category", ""),
            "query": modified_query,  # Modified query
            "expected_params": ", ".join(required_params),
            "retrieved_params": "",   # Empty for test file
            "expected_behavior": expected_behavior,
            "detected_behavior": "",  # Empty
            "recall": None,
            "precision": None,
            "f1": None,
            "behavior_match": None,
            "time_ms": None,
            "error": ""
        }
        rows.append(row)

    # 3. Create DataFrame
    df = pd.DataFrame(rows, columns=COLUMNS)

    # 4. Save to Excel
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Paths.OUTPUT_DIR / f"claude_code_test_{ts}.xlsx"
    
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Detail", index=False)
        # Create empty sheets for structure compatibility if needed
        pd.DataFrame().to_excel(writer, sheet_name="Aggregated", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Comparison", index=False)

    print(f"Successfully generated Claude Code test file: {output_path}")

if __name__ == "__main__":
    main()
