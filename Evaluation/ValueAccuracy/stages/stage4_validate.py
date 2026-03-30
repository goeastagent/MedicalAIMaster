import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Optional
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from Evaluation.ValueAccuracy.utils.vital_executor import VitalExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def process_file(file_path: Path, executor: VitalExecutor) -> list:
    """Reads a JSONL file, executes the Python code for each query, and updates expected_value."""
    if not file_path.exists():
        logger.warning(f"File not found: {file_path}")
        return []

    validated_queries = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            
            try:
                query_data = json.loads(line)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON line in {file_path.name}")
                continue

            code = query_data.get("ground_truth_logic", {}).get("code", "")
            if not code:
                logger.warning(f"No Python code found for ID: {query_data.get('id')}")
                continue

            # Execute the Python code using VitalExecutor
            logger.debug(f"Executing code for {query_data['id']}")
            
            response = executor.execute_code(code)
            
            if not response["success"]:
                logger.error(f"Code Execution failed for {query_data['id']}: {response['error']}")
                # We skip invalid queries to ensure the benchmark is 100% clean
                continue
                
            query_data["expected_value"] = response["result"]
            query_data["is_verified_by_execution"] = True
            validated_queries.append(query_data)
            logger.info(f"Verified {query_data['id']} -> Expected Value: {query_data['expected_value']}")

    return validated_queries

def validate_and_merge_datasets(
    output_filename: str = "value_accuracy_dataset.jsonl",
    input_filenames: Optional[List[str]] = None,
):
    """
    Reads all generated query files, executes their Python code to get the ground truth,
    and merges valid ones into a final benchmark dataset.

    Args:
        output_filename:  Output filename (relative to output/).
        input_filenames:  List of input filenames (relative to output/).  When None,
                          falls back to the default three files from a single run.
    """
    output_dir = Path(__file__).parent.parent / "output"

    if input_filenames is None:
        input_files = [
            output_dir / "base_queries.jsonl",
            output_dir / "conditional_queries.jsonl",
            output_dir / "adversarial_queries.jsonl",
        ]
    else:
        input_files = [output_dir / fname for fname in input_filenames]

    executor = VitalExecutor()

    all_validated_queries = []

    for file_path in input_files:
        logger.info(f"Processing {file_path.name}...")
        validated = process_file(file_path, executor)
        all_validated_queries.append(validated)
        logger.info(f"Successfully validated {len(validated)} queries from {file_path.name}")

    # Flatten list
    final_dataset = [q for sublist in all_validated_queries for q in sublist]

    # Save final dataset
    final_output_path = output_dir / output_filename
    with open(final_output_path, "w", encoding="utf-8") as f:
        for q in final_dataset:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    logger.info(f"=== Validation Complete ===")
    logger.info(f"Total valid queries saved to {final_output_path}: {len(final_dataset)}")

if __name__ == "__main__":
    load_dotenv()
    validate_and_merge_datasets()
