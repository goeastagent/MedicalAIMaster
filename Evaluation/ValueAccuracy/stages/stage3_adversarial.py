import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import sys
from typing import Optional

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from shared.llm.client import get_llm_client
from Evaluation.utils.case_sampler import sample_cases, build_inventory_text, get_vital_dir

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_adversarial_queries(
    num_queries: int = 5,
    output_file: str = "adversarial_queries.jsonl",
    n_cases: int = 3,
    seed: Optional[int] = None,
    cases: Optional[dict] = None,
):
    """
    Generates adversarial queries (fake categories, impossible conditions, distractors) using LLM.

    Args:
        num_queries: Total number of queries to generate.
        output_file: Output filename inside the output/ directory.
        n_cases:     Number of .vital files to randomly sample (used when cases=None).
        seed:        Random seed for case sampling reproducibility.
        cases:       Pre-sampled dict {caseid: [tracks]}. If provided, n_cases/seed
                     are ignored and no file I/O sampling occurs.
    """
    # Load prompt template
    prompt_path = Path(__file__).parent.parent / "prompts" / "adversarial_query_gen.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    if cases is None:
        cases = sample_cases(vital_dir=get_vital_dir(), n=n_cases, seed=seed)
    inventory_text = build_inventory_text(cases)
    prompt_template = prompt_template.replace("{cases_inventory}", inventory_text)

    # Format prompt
    prompt = prompt_template.replace("{num_queries}", str(num_queries))

    # Initialize LLM client
    llm_client = get_llm_client()
    logger.info(f"Generating {num_queries} adversarial queries using LLM (caseids: {sorted(cases.keys())})...")

    # Call LLM
    response = llm_client.ask_json(prompt, max_tokens=65536)
    
    # Handle response
    if "error" in response:
        logger.error(f"Failed to generate queries: {response['error']}")
        return []

    # Extract the list of queries
    queries = []
    if isinstance(response, list):
        queries = response
    elif isinstance(response, dict):
        for val in response.values():
            if isinstance(val, list):
                queries = val
                break
        if not queries and "queries" in response:
            queries = response["queries"]

    if not queries:
        logger.error("Could not parse a list of queries from the LLM response.")
        logger.debug(f"Raw response: {response}")
        return []

    # Ensure IDs are unique and formatted correctly
    for i, q in enumerate(queries):
        q["id"] = f"va_adv_{i+1:03d}"
        q["expected_value"] = None
        q["is_verified_by_execution"] = False

    # Save to JSONL
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_file

    with open(output_path, "w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    logger.info(f"Successfully generated {len(queries)} adversarial queries and saved to {output_path}")
    return queries

if __name__ == "__main__":
    import argparse
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--num-queries", type=int, default=5)
    parser.add_argument("--n-cases", type=int, default=3)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    generate_adversarial_queries(num_queries=args.num_queries, n_cases=args.n_cases, seed=args.seed)
