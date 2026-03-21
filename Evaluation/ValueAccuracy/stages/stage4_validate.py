import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from Evaluation.ValueAccuracy.utils.db_executor import DBExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def process_file(file_path: Path, executor: DBExecutor) -> list:
    """Reads a JSONL file, executes the SQL for each query, and updates expected_value."""
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

            sql_code = query_data.get("ground_truth_logic", {}).get("code", "")
            if not sql_code:
                logger.warning(f"No SQL code found for ID: {query_data.get('id')}")
                continue

            # Execute the SQL query
            logger.debug(f"Executing SQL for {query_data['id']}: {sql_code}")
            
            # Use get_single_value if it's a simple scalar query (COUNT, AVG, MAX, etc.)
            # Otherwise, use execute_query. We'll try execute_query first and format the result.
            response = executor.execute_query(sql_code)
            
            if not response["success"]:
                logger.error(f"SQL Execution failed for {query_data['id']}: {response['error']}")
                # We skip invalid SQL queries to ensure the benchmark is 100% clean
                continue
                
            results = response["result"]
            
            # Determine how to store the expected_value
            if not results:
                # Empty result (e.g., adversarial query with impossible conditions)
                query_data["expected_value"] = 0 if "COUNT" in sql_code.upper() else None
            elif len(results) == 1 and len(results[0]) == 1:
                # Single scalar value (e.g., COUNT(*), AVG(match_confidence))
                val = list(results[0].values())[0]
                # Convert Decimal or other DB types to standard Python types for JSON serialization
                if val is not None:
                    try:
                        val = float(val) if '.' in str(val) else int(val)
                    except ValueError:
                        pass # Keep as string if it can't be cast
                query_data["expected_value"] = val
            else:
                # Multiple rows or columns (e.g., GROUP BY)
                # Convert to a list of dicts, ensuring types are serializable
                formatted_results = []
                for row in results:
                    formatted_row = {}
                    for k, v in row.items():
                        if v is not None:
                            try:
                                v = float(v) if '.' in str(v) else int(v)
                            except ValueError:
                                pass
                        formatted_row[k] = v
                    formatted_results.append(formatted_row)
                query_data["expected_value"] = formatted_results

            query_data["is_verified_by_execution"] = True
            validated_queries.append(query_data)
            logger.info(f"Verified {query_data['id']} -> Expected Value: {query_data['expected_value']}")

    return validated_queries

def validate_and_merge_datasets(output_filename: str = "value_accuracy_dataset.jsonl"):
    """
    Reads all generated query files, executes their SQL to get the ground truth,
    and merges valid ones into a final benchmark dataset.
    """
    output_dir = Path(__file__).parent.parent / "output"
    
    input_files = [
        output_dir / "base_queries.jsonl",
        output_dir / "conditional_queries.jsonl",
        output_dir / "adversarial_queries.jsonl"
    ]

    executor = DBExecutor()
    executor.connect()

    all_validated_queries = []

    try:
        for file_path in input_files:
            logger.info(f"Processing {file_path.name}...")
            validated = process_file(file_path, executor)
            all_validated_queries.append(validated)
            logger.info(f"Successfully validated {len(validated)} queries from {file_path.name}")
    finally:
        executor.close()

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
