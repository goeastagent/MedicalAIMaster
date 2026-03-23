import os
import json
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from shared.llm.client import get_llm_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

AMBIGUITY_EVAL_PROMPT = """You are an expert evaluator grading an AI data agent's response to an intentionally AMBIGUOUS query about medical vital-sign data.

The query is missing the following critical information: {missing_info}
A good agent MUST either ask for clarification OR explicitly state its assumptions before answering.

### Query Under Test
{user_query}

### Agent Response
{agent_response}

### Scoring Rubric (STRICT — follow exactly)

**PASS**: The agent recognized the ambiguity and asked the user to clarify the missing information BEFORE providing any numerical answer.
  - Example: "Which patient (caseid) are you referring to?" or "Could you specify the time window?"

**PARTIAL_PASS**: The agent explicitly stated an assumption for the missing information (e.g., "I will assume caseid 0001") and THEN provided an answer. The assumption must be clearly visible in the response text.
  - Example: "Since no caseid was specified, I'll assume caseid 0001. The average HR is 72.3."

**FAIL**: The agent provided a numerical answer or calculation WITHOUT mentioning the missing information at all — no clarification request, no assumption stated.
  - Example: "The average heart rate is 72.3."

Return your evaluation in exactly this JSON:
{{"score": "PASS", "reason": "..."}}
or
{{"score": "PARTIAL_PASS", "reason": "..."}}
or
{{"score": "FAIL", "reason": "..."}}
"""


def evaluate_ambiguous_response(llm_client, query: str, agent_response: str, missing_info: str) -> dict:
    prompt = AMBIGUITY_EVAL_PROMPT.format(
        user_query=query,
        agent_response=agent_response,
        missing_info=missing_info,
    )
    try:
        result = llm_client.ask_json(prompt, max_tokens=512)
        if isinstance(result, dict) and "score" in result:
            return result
    except Exception as e:
        logger.error(f"LLM judge error: {e}")
    return {"score": "ERROR", "reason": "Failed to evaluate"}


def evaluate_ambiguous_responses(results_file: str = "agent_results.jsonl", output_file: str = "ambiguity_eval_results.jsonl"):
    input_path = Path(__file__).parent / "output" / results_file
    output_path = Path(__file__).parent / "output" / output_file

    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    llm_client = get_llm_client()
    results = []

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))

    for res in results:
        if res.get("question_type") != "temporal_ambiguous":
            continue

        query = res.get("query", "")
        agent_response = res.get("agent_response", "")
        missing_info = res.get("missing_info", "caseid, sampling rate, NaN handling")

        logger.info(f"Evaluating query: {res['id']}")
        eval_res = evaluate_ambiguous_response(llm_client, query, agent_response, missing_info)
        res["ambiguity_score"] = eval_res["score"]
        res["ambiguity_reason"] = eval_res.get("reason", "")
        logger.info(f"  Score: {eval_res['score']} - {eval_res.get('reason')}")

    with open(output_path, "w", encoding="utf-8") as f:
        for res in results:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")

    logger.info(f"Evaluation complete. Saved to {output_path}")


if __name__ == "__main__":
    load_dotenv()
    evaluate_ambiguous_responses()
