import json
import time
import subprocess
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys
import re

# Add project root to path
project_root = Path(__file__).parents[2]
sys.path.insert(0, str(project_root))

from test_qa_dataset import compare_values

# Dataset Configuration
BENCHMARK_DATASETS = [
    {
        "key": "low",
        "name": "Single-Case Low",
        "path": "testdata/vitaldb_low_qa_pairs_explicit.json",
        "difficulty": "Low",
        "scope": "Single",
    },
    {
        "key": "mid",
        "name": "Single-Case Mid",
        "path": "testdata/vitaldb_mid_qa_pairs_explicit.json",
        "difficulty": "Mid",
        "scope": "Single",
    },
    {
        "key": "high",
        "name": "Single-Case High",
        "path": "testdata/vitaldb_high_qa_pairs_explicit.json",
        "difficulty": "High",
        "scope": "Single",
    },
    {
        "key": "multi",
        "name": "Multi-Case (3)",
        "path": "testdata/case3_low_dataset.json",
        "difficulty": "Low",
        "scope": "Multi",
    },
]

def run_claude_code_value_accuracy(datasets_to_run=None, limit=None, output_filename=None):
    """
    Run Claude Code CLI for Value Accuracy benchmark.
    """
    output_dir = project_root / "Evaluation" / "ValueAccuracy" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if datasets_to_run:
        datasets = [ds for ds in BENCHMARK_DATASETS if ds["key"] in datasets_to_run]
    else:
        datasets = BENCHMARK_DATASETS

    all_results = []
    
    for ds in datasets:
        ds_path = project_root / ds["path"]
        if not ds_path.exists():
            print(f"⚠️ Dataset not found: {ds_path}")
            continue
            
        with open(ds_path, "r", encoding="utf-8") as f:
            qa_pairs = json.load(f)
            
        if limit:
            qa_pairs = qa_pairs[:limit]
            
        print(f"\n{'='*80}")
        print(f"Running Dataset: {ds['name']} ({len(qa_pairs)} queries)")
        print(f"{'='*80}")
        
        for i, qa in enumerate(qa_pairs):
            question = qa["question"]
            expected_answer = qa.get("corrected_answer", qa.get("answer"))
            format_type = qa.get("format", "float")
            expected_param = qa.get("parameter", "N/A")
            
            print(f"[{i+1}/{len(qa_pairs)}] Query: {question[:80]}...")
            
            prompt = (
                f"You are a medical data analysis assistant. You have access to the `vitaldb` python package.\n"
                f"Solve the following query by writing and executing a python script.\n"
                f"Query: {question}\n\n"
                f"After finding the answer, return ONLY a JSON object containing the final answer in this exact format:\n"
                f"{{\"answer\": <your_calculated_value>}}\n"
                f"Do not include any markdown formatting, explanations, or other text outside the JSON."
            )
            
            start_time = time.time()
            
            try:
                # Call Claude Code CLI
                # --dangerously-skip-permissions is REQUIRED so it can write/execute python without asking
                process = subprocess.run(
                    [
                        "claude", "-p", prompt, 
                        "--no-session-persistence", 
                        "--dangerously-skip-permissions"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120 # 2 minutes timeout for code execution
                )
                
                elapsed_ms = (time.time() - start_time) * 1000
                raw_output = process.stdout.strip()
                error_msg = process.stderr.strip() if process.returncode != 0 else ""
                
            except subprocess.TimeoutExpired:
                elapsed_ms = 120000
                raw_output = ""
                error_msg = "TimeoutExpired"
            except Exception as e:
                elapsed_ms = (time.time() - start_time) * 1000
                raw_output = ""
                error_msg = str(e)

            # Parse answer
            actual_answer = None
            try:
                json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    actual_answer = parsed.get("answer")
            except:
                pass
                
            # Compare using existing logic
            if actual_answer is not None:
                is_correct, reason = compare_values(expected_answer, actual_answer, format_type)
            else:
                is_correct, reason = False, "Failed to parse answer from output"
                
            print(f"  -> Time: {elapsed_ms:.1f}ms | Correct: {is_correct} | Reason: {reason}")
            
            all_results.append({
                "dataset": ds["name"],
                "difficulty": ds["difficulty"],
                "question": question,
                "expected_answer": str(expected_answer),
                "actual_answer": str(actual_answer) if actual_answer is not None else "N/A",
                "format": format_type,
                "is_correct": "O" if is_correct else "X",
                "score": 1 if is_correct else 0,
                "reason": reason,
                "expected_param": expected_param,
                "time_ms": elapsed_ms,
                "error_msg": error_msg,
                "raw_output": raw_output
            })

    # Save to Excel
    if not all_results:
        print("No results to save.")
        return
        
    df = pd.DataFrame(all_results)
    
    if output_filename:
        if not output_filename.endswith('.xlsx'):
            output_filename += '.xlsx'
        output_path = output_dir / output_filename
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"claude_code_value_accuracy_{ts}.xlsx"
        
    # Calculate summary
    total = len(df)
    correct = df['score'].sum()
    acc = correct / total * 100 if total > 0 else 0
    avg_time = df['time_ms'].mean()
    
    print(f"\n{'='*80}")
    print(f"Benchmark Complete! Accuracy: {acc:.1f}% ({correct}/{total}) | Avg Time: {avg_time:.1f}ms")
    print(f"Results saved to: {output_path}")
    print(f"{'='*80}")
    
    df.to_excel(output_path, index=False)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", "-d", nargs="+", choices=["low", "mid", "high", "multi"], help="Datasets to run")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of cases per dataset")
    parser.add_argument("--output", "-o", type=str, default=None, help="Custom output filename")
    args = parser.parse_args()
    
    run_claude_code_value_accuracy(args.datasets, args.limit, args.output)
