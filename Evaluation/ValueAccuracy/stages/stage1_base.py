import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from shared.llm.client import get_llm_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BATCH_SIZE = 5
MAX_TOKENS_PER_BATCH = 16384


def _extract_queries(response) -> list:
    """Extract a list of query dicts from an LLM JSON response."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for val in response.values():
            if isinstance(val, list):
                return val
        if "queries" in response:
            return response["queries"]
    return []


def generate_base_queries(num_queries: int = 10, output_file: str = "base_queries.jsonl"):
    """
    Generates base queries (simple retrieval & calculation) using LLM.
    Splits into batches to avoid token truncation.
    """
    prompt_path = Path(__file__).parent.parent / "prompts" / "base_query_gen.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    llm_client = get_llm_client()
    logger.info(f"Generating {num_queries} base queries using LLM...")

    all_queries = []
    remaining = num_queries
    batch_num = 0

    while remaining > 0:
        batch_size = min(BATCH_SIZE, remaining)
        batch_num += 1
        prompt = prompt_template.replace("{num_queries}", str(batch_size))

        logger.info(f"  Batch {batch_num}: requesting {batch_size} queries...")
        response = llm_client.ask_json(prompt, max_tokens=MAX_TOKENS_PER_BATCH)

        if isinstance(response, dict) and "error" in response:
            logger.error(f"  Batch {batch_num} failed: {response['error']}")
            continue

        queries = _extract_queries(response)
        if not queries:
            logger.error(f"  Batch {batch_num}: could not parse queries from response.")
            continue

        all_queries.extend(queries)
        remaining -= batch_size
        logger.info(f"  Batch {batch_num}: got {len(queries)} queries (total so far: {len(all_queries)})")

    if not all_queries:
        logger.error("All batches failed. No queries generated.")
        return []

    for i, q in enumerate(all_queries):
        q["id"] = f"va_base_{i+1:03d}"
        q["expected_value"] = None
        q["is_verified_by_execution"] = False

    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_file

    with open(output_path, "w", encoding="utf-8") as f:
        for q in all_queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    logger.info(f"Successfully generated {len(all_queries)} base queries and saved to {output_path}")
    return all_queries

if __name__ == "__main__":
    load_dotenv()
    generate_base_queries(num_queries=5)
