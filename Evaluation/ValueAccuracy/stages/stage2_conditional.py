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

def generate_conditional_queries(num_queries: int = 5, output_file: str = "conditional_queries.jsonl"):
    """
    Generates conditional multi-hop queries using LLM.
    """
    # Load prompt template
    prompt_path = Path(__file__).parent.parent / "prompts" / "conditional_query_gen.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # Format prompt
    prompt = prompt_template.replace("{num_queries}", str(num_queries))

    # Initialize LLM client
    llm_client = get_llm_client()
    logger.info(f"Generating {num_queries} conditional multi-hop queries using LLM...")

    # Call LLM
    response = llm_client.ask_json(prompt)
    
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
        q["id"] = f"va_cond_{i+1:03d}"
        q["expected_value"] = None
        q["is_verified_by_execution"] = False

    # Save to JSONL
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_file

    with open(output_path, "w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    logger.info(f"Successfully generated {len(queries)} conditional queries and saved to {output_path}")
    return queries

if __name__ == "__main__":
    load_dotenv()
    generate_conditional_queries(num_queries=5)
