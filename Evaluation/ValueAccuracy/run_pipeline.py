import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from Evaluation.ValueAccuracy.stages.stage1_base import generate_base_queries
from Evaluation.ValueAccuracy.stages.stage2_conditional import generate_conditional_queries
from Evaluation.ValueAccuracy.stages.stage3_adversarial import generate_adversarial_queries
from Evaluation.ValueAccuracy.stages.stage4_validate import validate_and_merge_datasets

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_pipeline():
    """
    Run the full Value Accuracy benchmark dataset generation pipeline.
    """
    logger.info("=== Starting Value Accuracy Dataset Pipeline ===")
    
    # 1. Generate Base Queries (Simple & Calculation)
    logger.info("\n--- Stage 1: Base Queries ---")
    generate_base_queries(num_queries=20)
    
    # 2. Generate Conditional Multi-hop Queries
    logger.info("\n--- Stage 2: Conditional Queries ---")
    generate_conditional_queries(num_queries=20)
    
    # 3. Generate Adversarial Queries
    logger.info("\n--- Stage 3: Adversarial Queries ---")
    generate_adversarial_queries(num_queries=10)
    
    # 4. Execute SQL and Validate Ground Truth
    logger.info("\n--- Stage 4: Execution & Validation ---")
    validate_and_merge_datasets(output_filename="value_accuracy_dataset.jsonl")
    
    logger.info("\n=== Pipeline Completed Successfully ===")
    logger.info("Final dataset is located at: Evaluation/ValueAccuracy/output/value_accuracy_dataset.jsonl")

if __name__ == "__main__":
    load_dotenv()
    run_pipeline()
