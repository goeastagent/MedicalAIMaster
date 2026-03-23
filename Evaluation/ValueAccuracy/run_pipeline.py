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
from Evaluation.ValueAccuracy.stages.stage4b_ambiguity_check import run_ambiguity_check

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_pipeline():
    """
    Run the full Value Accuracy benchmark dataset generation pipeline.
    """
    logger.info("=== Starting Value Accuracy Dataset Pipeline ===")
    
    # 1. Generate Base Queries (Simple & Calculation)
    logger.info("\n--- Stage 1: Base Queries ---")
    base_queries = generate_base_queries(num_queries=20)
    if not base_queries:
        logger.error("Stage 1 produced 0 queries. Retrying once...")
        base_queries = generate_base_queries(num_queries=20)
    logger.info(f"Stage 1 result: {len(base_queries)} queries")
    
    # 2. Generate Conditional Multi-hop Queries
    logger.info("\n--- Stage 2: Conditional Queries ---")
    cond_queries = generate_conditional_queries(num_queries=20)
    if not cond_queries:
        logger.error("Stage 2 produced 0 queries. Retrying once...")
        cond_queries = generate_conditional_queries(num_queries=20)
    logger.info(f"Stage 2 result: {len(cond_queries)} queries")
    
    # 3. Generate Adversarial Queries
    logger.info("\n--- Stage 3: Adversarial Queries ---")
    generate_adversarial_queries(num_queries=10)
    
    # Check minimum viability before proceeding to validation
    total_generated = len(base_queries) + len(cond_queries)
    if total_generated == 0:
        logger.error("Stages 1-2 both failed. Skipping Stage 4 — no queries to validate.")
        logger.error("=== Pipeline FAILED ===")
        return
    
    # 4. Execute Code and Validate Ground Truth
    logger.info("\n--- Stage 4: Execution & Validation ---")
    validate_and_merge_datasets(output_filename="value_accuracy_dataset.jsonl")
    
    # 4b. Ambiguity Check (determinism, LLM audit, None triage, dedup)
    logger.info("\n--- Stage 4b: Ambiguity Check ---")
    amb_summary = run_ambiguity_check()
    if "error" in amb_summary:
        logger.error(f"Ambiguity check failed: {amb_summary['error']}")
    else:
        logger.info(
            f"Ambiguity check: {amb_summary['kept']}/{amb_summary['total_input']} queries survived "
            f"({amb_summary['removed']} removed)"
        )
    
    logger.info("\n=== Pipeline Completed Successfully ===")
    logger.info("Raw validated dataset: Evaluation/ValueAccuracy/output/value_accuracy_dataset.jsonl")
    logger.info("Clean dataset (post-ambiguity): Evaluation/ValueAccuracy/output/value_accuracy_dataset_clean.jsonl")

if __name__ == "__main__":
    load_dotenv()
    run_pipeline()
