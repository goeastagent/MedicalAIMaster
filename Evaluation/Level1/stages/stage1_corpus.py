"""
Evaluation/Level1/stages/stage1_corpus.py

Stage 1: Parameter Corpus Auto-Configuration

1. Queries the `parameter` DB table for all distinct, non-identifier param_keys
   that have a semantic_name assigned (i.e., fully indexed).
2. For each param_key, calls the LLM (synonym_gen.txt prompt) to generate
   synonym groups: direct, semantic_en, medical_term, abbreviation.
3. Serialises results to output/synonym_map.json as Dict[param_key, SynonymEntry].

Resumable: param_keys already present in synonym_map.json are skipped, so
the stage can be re-run after a partial failure without re-processing.

Usage (standalone):
    python -m Evaluation.Level1.stages.stage1_corpus
    python -m Evaluation.Level1.stages.stage1_corpus --dry-run   # DB query only, no LLM
    python -m Evaluation.Level1.stages.stage1_corpus --limit 10  # first N params
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import psycopg2

# ---------------------------------------------------------------------------
# Path bootstrap — allow running as __main__ from project root or directly
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Evaluation.Level1.config import DBConfig, GenerationConfig, Paths
from Evaluation.Level1.models import SynonymEntry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Stage1] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _connect() -> psycopg2.extensions.connection:
    """Open a psycopg2 connection using DBConfig."""
    try:
        conn = psycopg2.connect(DBConfig.dsn())
        conn.autocommit = True
        return conn
    except Exception as e:
        log.error("Cannot connect to PostgreSQL: %s", e)
        raise


def load_params_from_db(
    conn: psycopg2.extensions.connection,
    limit: Optional[int] = None,
) -> List[Dict]:
    """Return distinct non-identifier params that have semantic_name set.

    Returns a list of dicts:
        [{"param_key": str, "semantic_name": str, "unit": str, "concept_category": str}, ...]
    """
    sql = """
        SELECT DISTINCT ON (param_key)
               param_key,
               COALESCE(semantic_name, param_key) AS semantic_name,
               COALESCE(unit, '')                 AS unit,
               COALESCE(concept_category, '')     AS concept_category
        FROM   parameter
        WHERE  is_identifier = FALSE
          AND  concept_category IS NOT NULL
          AND  concept_category <> 'Identifiers'
          AND  param_key ~ '^[A-Za-z0-9_]+/[A-Za-z0-9_]+$'
        ORDER  BY param_key, param_id
    """
    if limit is not None:
        sql += f" LIMIT {limit}"

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    return [
        {
            "param_key":        row[0],
            "semantic_name":    row[1],
            "unit":             row[2],
            "concept_category": row[3],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# LLM helper — direct OpenAI call with custom temperature
# ---------------------------------------------------------------------------

def _call_synonym_llm(prompt: str) -> Dict:
    """Call OpenAI with the synonym_gen prompt and return parsed JSON.

    Uses GenerationConfig.SYNONYM_MODEL / SYNONYM_TEMPERATURE directly so
    it doesn't touch the shared singleton client (which has temperature=0).
    Falls back gracefully on any error, returning an empty dict.
    """
    try:
        from openai import OpenAI
        from Evaluation.Level1.config import DBConfig  # noqa — just to trigger load_dotenv
        import os

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=GenerationConfig.SYNONYM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a medical terminology expert. "
                        "Output valid JSON only, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=GenerationConfig.SYNONYM_TEMPERATURE,
            max_tokens=GenerationConfig.SYNONYM_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except Exception as e:
        log.warning("LLM call failed: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Core synonym generation
# ---------------------------------------------------------------------------

def generate_synonym_entry(
    param: Dict,
    prompt_template: str,
    dry_run: bool = False,
) -> SynonymEntry:
    """Build a SynonymEntry for a single parameter.

    In dry_run mode, returns a SynonymEntry with empty synonym lists
    (useful for testing the DB query and prompt rendering).
    """
    filled_prompt = prompt_template.format(
        param_key=param["param_key"],
        semantic_name=param["semantic_name"],
        unit=param["unit"] or "—",
        concept_category=param["concept_category"] or "Unknown",
    )

    if dry_run:
        llm_result = {}
    else:
        llm_result = _call_synonym_llm(filled_prompt)

    # Tolerate missing keys — LLM may omit some groups
    return SynonymEntry(
        param_key=param["param_key"],
        semantic_name=param["semantic_name"],
        unit=param["unit"] or None,
        concept_category=param["concept_category"] or None,
        direct=llm_result.get("direct", [param["param_key"]]),
        semantic_en=llm_result.get("semantic_en", []),
        medical_term=llm_result.get("medical_term", []),
        abbreviation=llm_result.get("abbreviation", []),
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_existing(path: Path) -> Dict[str, dict]:
    """Load synonym_map.json if it exists; return empty dict otherwise."""
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            log.warning("Existing synonym_map.json is corrupt — starting fresh.")
    return {}


def _save(synonym_map: Dict[str, dict], path: Path) -> None:
    """Atomically write synonym_map to JSON (write to .tmp then rename)."""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(synonym_map, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    limit: Optional[int] = None,
    dry_run: bool = False,
    save_every: int = 10,
) -> Dict[str, SynonymEntry]:
    """Run Stage 1.

    Args:
        limit:      Process at most this many params (None = all).
        dry_run:    Skip LLM calls; useful for DB connectivity tests.
        save_every: Checkpoint synonym_map.json every N params.

    Returns:
        Dict[param_key, SynonymEntry] — the full synonym map.
    """
    Paths.ensure_output_dir()
    output_path = Paths.SYNONYM_MAP
    prompt_template = (Paths.PROMPTS_DIR / "synonym_gen.txt").read_text(encoding="utf-8")

    # ── 1. Load existing results (resume support) ──────────────────────────
    existing_raw: Dict[str, dict] = _load_existing(output_path)
    already_done = set(existing_raw.keys())
    if already_done:
        log.info("Resuming: %d param_keys already in synonym_map.json", len(already_done))

    # ── 2. Query DB ────────────────────────────────────────────────────────
    log.info("Connecting to DB: %s@%s:%s/%s",
             DBConfig.USER, DBConfig.HOST, DBConfig.PORT, DBConfig.DATABASE)
    conn = _connect()
    try:
        all_params = load_params_from_db(conn, limit=limit)
    finally:
        conn.close()

    pending = [p for p in all_params if p["param_key"] not in already_done]
    total = len(all_params)
    log.info(
        "DB returned %d params. %d already done, %d to process.",
        total, len(already_done), len(pending),
    )

    if not pending:
        log.info("Nothing to do — synonym_map.json is up to date.")
        # Deserialise and return
        return {k: SynonymEntry(**v) for k, v in existing_raw.items()}

    # ── 3. Generate synonyms ────────────────────────────────────────────────
    synonym_map_raw: Dict[str, dict] = dict(existing_raw)  # mutable working copy
    errors: List[str] = []

    n_pending = len(pending)
    for idx, param in enumerate(pending, start=1):
        key = param["param_key"]
        label = f"[{idx}/{n_pending}]"

        try:
            entry = generate_synonym_entry(param, prompt_template, dry_run=dry_run)
            synonym_map_raw[key] = entry.model_dump()

            expr_count = len(entry.all_expressions())
            log.info(
                "%s %-35s → %d expressions%s",
                label, key, expr_count,
                " (dry-run)" if dry_run else "",
            )

        except Exception as e:
            log.error("%s FAILED: %s — %s", label, key, e)
            errors.append(key)
            # Still save a minimal entry so we don't lose the param_key
            synonym_map_raw[key] = SynonymEntry(
                param_key=key,
                semantic_name=param["semantic_name"],
                unit=param["unit"] or None,
                concept_category=param["concept_category"] or None,
                direct=[key],
            ).model_dump()

        # Checkpoint every N params to avoid losing progress
        if idx % save_every == 0:
            _save(synonym_map_raw, output_path)
            log.info("Checkpoint saved (%d / %d this run)", idx, n_pending)

        # Polite delay between LLM calls to stay within rate limits
        if not dry_run:
            time.sleep(0.3)

    # ── 4. Final save ──────────────────────────────────────────────────────
    _save(synonym_map_raw, output_path)

    # ── 5. Summary ─────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("Stage 1 complete.")
    log.info("  Total params in DB   : %d", total)
    log.info("  Processed this run   : %d", len(pending))
    log.info("  Errors               : %d", len(errors))
    log.info("  synonym_map.json     : %s", output_path)
    if errors:
        log.warning("  Failed param_keys    : %s", errors)

    return {k: SynonymEntry(**v) for k, v in synonym_map_raw.items()}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stage 1 — Build parameter corpus and generate synonym map."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process at most N params (default: all).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Query DB only; skip LLM calls. Useful for connectivity tests.",
    )
    parser.add_argument(
        "--save-every", type=int, default=10,
        help="Checkpoint synonym_map.json every N params (default: 10).",
    )
    args = parser.parse_args()

    run(
        limit=args.limit,
        dry_run=args.dry_run,
        save_every=args.save_every,
    )
