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

def generate_base_queries(num_queries: int = 10, output_file: str = "base_queries.jsonl"):
    """
    Generates base queries (simple retrieval & calculation) using LLM.
    """
    # Load prompt template
    prompt_path = Path(__file__).parent.parent / "prompts" / "base_query_gen.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # Format prompt
    prompt = prompt_template.replace("{num_queries}", str(num_queries))

    # Initialize LLM client
    llm_client = get_llm_client()
    logger.info(f"Generating {num_queries} base queries using LLM...")

    # Call LLM
    response = llm_client.ask_json(prompt)
    
    # Handle response
    if "error" in response:
        logger.error(f"Failed to generate queries: {response['error']}")
        return []

    # The LLM might return a dict with a key containing the list, or just the list.
    # We need to extract the list of queries.
    queries = []
    if isinstance(response, list):
        queries = response
    elif isinstance(response, dict):
        # Find the first list in the dict values
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
        q["id"] = f"va_base_{i+1:03d}"
        # Add a placeholder for the actual expected value (to be filled in Stage 4)
        q["expected_value"] = None
        q["is_verified_by_execution"] = False

    # Save to JSONL
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_file

    with open(output_path, "w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    logger.info(f"Successfully generated {len(queries)} base queries and saved to {output_path}")
    return queries

if __name__ == "__main__":
    load_dotenv()
    generate_base_queries(num_queries=5)
