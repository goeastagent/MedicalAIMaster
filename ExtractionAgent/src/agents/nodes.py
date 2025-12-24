"""
ExtractionAgent Nodes - Self-Correction Loop + VectorDB 시맨틱 검색 지원

각 노드는 워크플로우의 한 단계를 담당합니다.
- VectorDB를 활용하여 쿼리 관련 컬럼/테이블을 시맨틱 검색
- Self-Correction Loop를 통해 SQL 실행 실패 시 최대 3회까지 재시도
"""

import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
from ExtractionAgent.src.agents.state import ExtractionState
from ExtractionAgent.src.database.postgres import PostgresConnector
from ExtractionAgent.src.database.neo4j import Neo4jConnector
from ExtractionAgent.src.utils.llm_client import LLMClient
from ExtractionAgent.src.config import Config

# Singleton instances
pg_connector = PostgresConnector()
neo4j_connector = Neo4jConnector()
llm_client = LLMClient()

# VectorStore (lazy initialization)
_vector_store = None
_vector_store_initialized = False


def _get_vector_store():
    """VectorStore 싱글톤 반환 (lazy initialization)"""
    global _vector_store, _vector_store_initialized
    
    if not _vector_store_initialized:
        _vector_store_initialized = True
        try:
            from ExtractionAgent.src.knowledge.vector_store import VectorStoreReader
            _vector_store = VectorStoreReader()
            _vector_store.initialize()
            if not _vector_store.is_available():
                _vector_store = None
        except Exception as e:
            print(f"  ⚠️ VectorStore 초기화 실패: {e}")
            _vector_store = None
    
    return _vector_store


# ============================================================================
# Logging Utilities
# ============================================================================

def _log_header(title: str, char: str = "=", width: int = 70):
    """로그 헤더 출력"""
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def _log_subheader(title: str):
    """로그 서브헤더 출력"""
    print(f"\n  ▸ {title}")
    print(f"  {'-' * 50}")


def _log_item(key: str, value: str, indent: int = 4):
    """로그 항목 출력"""
    prefix = " " * indent
    # 긴 값은 줄바꿈
    if len(str(value)) > 60:
        value = str(value)[:60] + "..."
    print(f"{prefix}• {key}: {value}")


def _log_sql(sql: str, indent: int = 4):
    """SQL 쿼리 출력 (포맷팅)"""
    prefix = " " * indent
    print(f"{prefix}┌{'─' * 60}┐")
    for line in sql.strip().split('\n'):
        print(f"{prefix}│ {line[:58]:<58} │")
    print(f"{prefix}└{'─' * 60}┘")


# ============================================================================
# Node Implementations
# ============================================================================

def inspect_context_node(state: ExtractionState) -> Dict[str, Any]:
    """
    1️⃣ INSPECTOR NODE: DB 스키마 및 온톨로지 정보 수집
    
    - PostgreSQL information_schema에서 테이블/컬럼 정보 조회
    - Neo4j에서 온톨로지 정보 조회
    - VectorDB 초기화 (시맨틱 검색 준비)
    - Self-Correction Loop 상태 초기화
    """
    _log_header("1️⃣  INSPECTOR NODE - Context Collection")
    
    # PostgreSQL 스키마 정보
    _log_subheader("Loading PostgreSQL Schema")
    schema_info = pg_connector.get_schema_info()
    
    schema_summary = {}
    for col in schema_info:
        tbl = col['table_name']
        if tbl not in schema_summary:
            schema_summary[tbl] = []
        schema_summary[tbl].append(f"{col['column_name']} ({col['data_type']})")
    
    _log_item("Tables found", str(len(schema_summary)))
    for tbl, cols in list(schema_summary.items())[:5]:  # 처음 5개만 표시
        _log_item(f"  {tbl}", f"{len(cols)} columns")
    if len(schema_summary) > 5:
        print(f"      ... and {len(schema_summary) - 5} more tables")
    
    # Neo4j 온톨로지 정보
    _log_subheader("Loading Neo4j Ontology")
    ontology_info = neo4j_connector.get_ontology_context()
    
    definitions_count = len(ontology_info.get("definitions", {}))
    relationships_count = len(ontology_info.get("relationships", []))
    _log_item("Definitions", str(definitions_count))
    _log_item("Relationships", str(relationships_count))
    
    # VectorDB 초기화
    _log_subheader("Initializing VectorDB")
    vector_store = _get_vector_store()
    if vector_store:
        _log_item("Status", "✅ Available")
        model_info = vector_store.get_current_model_info()
        _log_item("Provider", model_info.get("provider", "unknown"))
        _log_item("Dimensions", str(model_info.get("dimensions", "unknown")))
    else:
        _log_item("Status", "⚠️ Not available (falling back to keyword matching)")
    
    context = {
        "db_schema": schema_summary,
        "ontology": ontology_info,
        "vector_store_available": vector_store is not None
    }
    
    # Self-Correction Loop 상태 초기화
    _log_subheader("Initializing Self-Correction Loop")
    _log_item("retry_count", "0")
    _log_item("max_retries", "3")
    _log_item("sql_history", "[]")
    
    print(f"\n{'=' * 70}")
    print(f"  ✅ Inspector completed - Ready for SQL generation")
    print(f"{'=' * 70}")
    
    return {
        "semantic_context": context,
        "retry_count": 0,
        "max_retries": 3,
        "sql_history": [],
        "error": None,
        "logs": [f"✅ Context loaded: {len(schema_summary)} tables, {definitions_count} definitions, VectorDB: {'Yes' if vector_store else 'No'}"]
    }


def plan_sql_node(state: ExtractionState) -> Dict[str, Any]:
    """
    2️⃣ PLANNER NODE: SQL 생성 (VectorDB 시맨틱 검색 + Self-Correction)
    
    - VectorDB로 쿼리 관련 컬럼/테이블 시맨틱 검색
    - 최초 시도: 스키마 + 온톨로지 + 시맨틱 검색 결과 기반 SQL 생성
    - 재시도: 이전 에러 히스토리를 컨텍스트에 포함하여 수정된 SQL 생성
    """
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    sql_history = state.get("sql_history", [])
    
    _log_header(f"2️⃣  PLANNER NODE - SQL Generation (Attempt {retry_count + 1}/{max_retries})")
    
    context = state["semantic_context"]
    query = state["user_query"]
    
    _log_subheader("Input")
    _log_item("User Query", query)
    _log_item("Retry Count", str(retry_count))
    
    # VectorDB 시맨틱 검색 (최초 시도 시에만)
    semantic_results = None
    if retry_count == 0 and context.get("vector_store_available"):
        _log_subheader("VectorDB Semantic Search")
        semantic_results = _perform_semantic_search(query)
        
        if semantic_results:
            _log_item("Relevant Columns", str(len(semantic_results.get("columns", []))))
            _log_item("Relevant Tables", str(len(semantic_results.get("tables", []))))
            _log_item("Relevant Relationships", str(len(semantic_results.get("relationships", []))))
            
            # 상위 결과 표시
            for col in semantic_results.get("columns", [])[:3]:
                _log_item(f"  📊 {col['table_name']}.{col['column_name']}", 
                         f"similarity: {col['similarity']:.2%}")
        else:
            _log_item("Status", "⚠️ No results (using full schema)")
    
    # 프롬프트 구성 (최초 vs 재시도)
    if retry_count == 0:
        _log_subheader("Building Initial Prompt")
        prompt = _build_initial_prompt(context, query, semantic_results)
    else:
        _log_subheader("Building Retry Prompt (with error history)")
        _log_item("Previous Attempts", str(len(sql_history)))
        for h in sql_history:
            _log_item(f"  Attempt {h['attempt']}", f"Error: {str(h['error'])[:40]}...")
        prompt = _build_retry_prompt(context, query, sql_history, semantic_results)
    
    # LLM 호출
    _log_subheader("Calling LLM")
    response = llm_client.ask_json(prompt)
    
    if "error" in response or not response.get("sql"):
        error_msg = response.get("error", "SQL generation failed - no SQL returned")
        _log_item("Status", "❌ FAILED")
        _log_item("Error", error_msg)
        
        return {
            "error": error_msg,
            "generated_sql": None,
            "logs": [f"❌ SQL generation failed (attempt {retry_count + 1}): {error_msg[:50]}"]
        }
    
    generated_sql = response.get("sql")
    reasoning = response.get("reasoning", "No reasoning provided")
    
    _log_subheader("Generated SQL")
    _log_sql(generated_sql)
    _log_item("Reasoning", reasoning)
    
    print(f"\n{'=' * 70}")
    print(f"  ✅ SQL generated successfully (attempt {retry_count + 1})")
    print(f"{'=' * 70}")
    
    return {
        "sql_plan": response,
        "generated_sql": generated_sql,
        "error": None,  # 이전 에러 클리어
        "logs": [f"✅ SQL generated (attempt {retry_count + 1}): {reasoning[:50]}..."]
    }


def execute_sql_node(state: ExtractionState) -> Dict[str, Any]:
    """
    3️⃣ EXECUTOR NODE: SQL 실행 및 Self-Correction 준비
    
    - SQL 실행 시도
    - 성공 시: 결과 반환
    - 실패 시: 에러를 sql_history에 기록하고 retry_count 증가
    """
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    sql_history = state.get("sql_history", []).copy()
    sql = state.get("generated_sql")
    
    _log_header(f"3️⃣  EXECUTOR NODE - SQL Execution (Attempt {retry_count + 1}/{max_retries})")
    
    if not sql:
        _log_subheader("Error")
        _log_item("Status", "❌ No SQL to execute")
        
        # 에러 히스토리에 추가
        sql_history.append({
            "attempt": retry_count + 1,
            "sql": None,
            "error": "No SQL generated"
        })
        
        return {
            "execution_result": None,
            "error": "No SQL to execute",
            "retry_count": retry_count + 1,
            "sql_history": sql_history,
            "logs": [f"❌ No SQL to execute (attempt {retry_count + 1})"]
        }
    
    _log_subheader("Executing SQL")
    _log_sql(sql)
    
    try:
        results = pg_connector.execute_query(sql)
        
        # 결과가 0건인 경우 - Self-Correction을 위해 히스토리에 기록
        if len(results) == 0:
            _log_subheader("Result")
            _log_item("Status", "⚠️ ZERO ROWS")
            _log_item("Rows returned", "0")
            
            # 에러 히스토리에 추가 (0건 케이스)
            sql_history.append({
                "attempt": retry_count + 1,
                "sql": sql,
                "error": "ZERO_ROWS: Query executed successfully but returned 0 rows. "
                         "This likely means column names or WHERE condition values are incorrect."
            })
            
            _log_subheader("Self-Correction Status (Zero Rows)")
            _log_item("Attempts so far", str(retry_count + 1))
            _log_item("Max retries", str(max_retries))
            _log_item("Will retry", "Yes" if retry_count + 1 < max_retries else "No (max reached)")
            
            print(f"\n{'=' * 70}")
            print(f"  ⚠️ SQL executed but returned 0 rows - triggering self-correction")
            print(f"{'=' * 70}")
            
            return {
                "execution_result": results,  # 빈 리스트 반환
                "error": None,  # SQL 자체는 에러 아님
                "retry_count": retry_count + 1,
                "sql_history": sql_history,
                "logs": [f"⚠️ SQL returned 0 rows (attempt {retry_count + 1}) - will retry"]
            }
        
        # 성공! (rows > 0)
        _log_subheader("Result")
        _log_item("Status", "✅ SUCCESS")
        _log_item("Rows returned", str(len(results)))
        
        # 첫 번째 행의 컬럼들 표시
        columns = list(results[0].keys()) if results else []
        _log_item("Columns", ", ".join(columns[:5]) + ("..." if len(columns) > 5 else ""))
        
        print(f"\n{'=' * 70}")
        print(f"  ✅ SQL executed successfully - {len(results)} rows extracted")
        print(f"{'=' * 70}")
        
        return {
            "execution_result": results,
            "error": None,
            "logs": [f"✅ SQL executed ({len(results)} rows) on attempt {retry_count + 1}"]
        }
        
    except Exception as e:
        error_msg = str(e)
        
        _log_subheader("Error")
        _log_item("Status", "❌ FAILED")
        _log_item("Error Type", type(e).__name__)
        _log_item("Error Message", error_msg[:100])
        
        # 에러 히스토리에 추가
        sql_history.append({
            "attempt": retry_count + 1,
            "sql": sql,
            "error": error_msg
        })
        
        _log_subheader("Self-Correction Status")
        _log_item("Attempts so far", str(retry_count + 1))
        _log_item("Max retries", str(max_retries))
        _log_item("Will retry", "Yes" if retry_count + 1 < max_retries else "No (max reached)")
        
        print(f"\n{'=' * 70}")
        print(f"  ❌ SQL failed - Error recorded for self-correction")
        print(f"{'=' * 70}")
        
        return {
            "execution_result": None,
            "error": error_msg,
            "retry_count": retry_count + 1,
            "sql_history": sql_history,
            "logs": [f"❌ SQL failed (attempt {retry_count + 1}): {error_msg[:50]}..."]
        }


def package_result_node(state: ExtractionState) -> Dict[str, Any]:
    """
    4️⃣ PACKAGER NODE: 결과 저장
    
    - 성공한 SQL 실행 결과를 CSV 파일로 저장
    - 최종 통계 출력
    """
    _log_header("4️⃣  PACKAGER NODE - Result Packaging")
    
    results = state.get("execution_result")
    retry_count = state.get("retry_count", 0)
    sql_history = state.get("sql_history", [])
    
    if not results:
        _log_item("Status", "⚠️ No data to save")
        return {"logs": ["⚠️ No data to save"]}
    
    # 출력 디렉토리 생성
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    
    # 파일명 생성
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(Config.OUTPUT_DIR, f"extraction_{timestamp}.csv")
    
    _log_subheader("Saving Results")
    _log_item("Output Directory", Config.OUTPUT_DIR)
    _log_item("Filename", f"extraction_{timestamp}.csv")
    
    # CSV 저장
    df = pd.DataFrame(results)
    df.to_csv(file_path, index=False, encoding='utf-8-sig')
    
    _log_subheader("Summary")
    _log_item("Total Rows", str(len(results)))
    _log_item("Total Columns", str(len(df.columns)))
    _log_item("File Size", f"{os.path.getsize(file_path) / 1024:.1f} KB")
    _log_item("Attempts Required", str(retry_count + 1))
    
    if sql_history:
        _log_subheader("Self-Correction History")
        for h in sql_history:
            _log_item(f"Attempt {h['attempt']}", f"Failed: {str(h['error'])[:40]}...")
        _log_item(f"Attempt {retry_count + 1}", "✅ Success")
    
    print(f"\n{'=' * 70}")
    print(f"  🎉 EXTRACTION COMPLETE")
    print(f"  📁 File: {file_path}")
    print(f"  📊 Rows: {len(results)} | Columns: {len(df.columns)}")
    print(f"  🔄 Attempts: {retry_count + 1}")
    print(f"{'=' * 70}")
    
    return {
        "output_file_path": file_path,
        "logs": [f"💾 Saved: {file_path} ({len(results)} rows, attempt {retry_count + 1})"]
    }


# ============================================================================
# VectorDB Semantic Search
# ============================================================================

def _perform_semantic_search(query: str, n_results: int = 10) -> Optional[Dict[str, List]]:
    """
    VectorDB를 사용하여 쿼리 관련 컬럼/테이블/관계 시맨틱 검색
    
    Args:
        query: 사용자 자연어 쿼리
        n_results: 각 타입별 최대 결과 수
    
    Returns:
        {
            "columns": [...],
            "tables": [...],
            "relationships": [...]
        }
    """
    vector_store = _get_vector_store()
    if not vector_store:
        return None
    
    try:
        # ===============================================================
        # 맨 처음에 한국어 → 영어 번역 (1회만 수행)
        # 일관성을 위해 여기서 번역 후 모든 검색에서 동일한 쿼리 사용
        # ===============================================================
        from ExtractionAgent.src.knowledge.vector_store import _contains_korean, _translate_to_english
        
        search_query = query
        if _contains_korean(query):
            print(f"  🌐 Translating Korean query to English...")
            search_query = _translate_to_english(query)
            print(f"     Original: {query}")
            print(f"     Translated: {search_query}")
        
        # 컬럼 검색
        columns = vector_store.semantic_search(search_query, n_results=n_results, filter_type="column")
        
        # 테이블 검색
        tables = vector_store.semantic_search(search_query, n_results=5, filter_type="table")
        
        # 관계 검색
        relationships = vector_store.semantic_search(search_query, n_results=5, filter_type="relationship")
        
        return {
            "columns": columns,
            "tables": tables,
            "relationships": relationships
        }
    except Exception as e:
        print(f"  ⚠️ Semantic search failed: {e}")
        return None


def _format_semantic_results(results: Optional[Dict[str, List]]) -> str:
    """시맨틱 검색 결과를 프롬프트용 텍스트로 포맷"""
    if not results:
        return ""
    
    lines = []
    lines.append("=" * 60)
    lines.append("SEMANTIC SEARCH RESULTS (Query-Relevant Information)")
    lines.append("=" * 60)
    lines.append("")
    lines.append("The following columns/tables are semantically related to the user's query.")
    lines.append("Use these as primary candidates for your SQL query.")
    lines.append("")
    
    # 관련 컬럼
    columns = results.get("columns", [])
    if columns:
        lines.append("📊 Relevant Columns:")
        for col in columns[:10]:
            col_name = col.get("column_name", "?")
            table_name = col.get("table_name", "?")
            full_name = col.get("full_name", col_name)
            description = col.get("description", "")
            unit = col.get("unit", "")
            similarity = col.get("similarity", 0)
            
            line = f"  • {table_name}.{col_name}"
            if full_name and full_name != col_name:
                line += f" ({full_name})"
            if unit:
                line += f" [{unit}]"
            line += f" - similarity: {similarity:.1%}"
            lines.append(line)
            
            if description:
                lines.append(f"      {description[:80]}")
        lines.append("")
    
    # 관련 테이블
    tables = results.get("tables", [])
    if tables:
        lines.append("📋 Relevant Tables:")
        for tbl in tables[:5]:
            table_name = tbl.get("table_name", "?")
            description = tbl.get("description", "")
            similarity = tbl.get("similarity", 0)
            lines.append(f"  • {table_name} - similarity: {similarity:.1%}")
            if description:
                lines.append(f"      {description[:60]}")
        lines.append("")
    
    # 관련 관계
    relationships = results.get("relationships", [])
    if relationships:
        lines.append("🔗 Relevant Relationships (for JOINs):")
        for rel in relationships[:5]:
            source = f"{rel.get('source_table', '?')}.{rel.get('source_column', '?')}"
            target = f"{rel.get('target_table', '?')}.{rel.get('target_column', '?')}"
            similarity = rel.get("similarity", 0)
            lines.append(f"  • {source} → {target} - similarity: {similarity:.1%}")
        lines.append("")
    
    return "\n".join(lines)


# ============================================================================
# Prompt Builders
# ============================================================================

def _build_initial_prompt(context: Dict[str, Any], query: str, semantic_results: Optional[Dict] = None) -> str:
    """최초 시도용 프롬프트 (VectorDB 검색 결과 포함)"""
    
    # 시맨틱 검색 결과가 있으면 포함
    semantic_section = ""
    if semantic_results:
        semantic_section = f"""
{_format_semantic_results(semantic_results)}

[IMPORTANT]
The semantic search results above show columns/tables most relevant to the query.
PRIORITIZE using these in your SQL. They are more likely to be correct matches.

"""
    
    return f"""You are a medical data extraction expert. Convert the user's question into a PostgreSQL query.

{semantic_section}[DB Schema]
{_format_schema(context['db_schema'])}

[Ontology & Relationships (Neo4j)]
{_format_ontology(context['ontology'])}

[User Query]
{query}

[Instructions]
1. Use PostgreSQL syntax only.
2. IMPORTANT: Only use tables and columns that exist in the schema above.
3. If semantic search results are provided, PRIORITIZE those columns/tables.
4. Check column names carefully - they are case-sensitive.
5. For time difference calculations, use 'ABS(EXTRACT(EPOCH FROM (t1.time - t2.time)))' format.
6. Return the result as a JSON object.

[Output Format]
{{
  "reasoning": "Brief explanation of your approach",
  "sql": "SELECT ... FROM ... WHERE ..."
}}
"""


def _build_retry_prompt(context: Dict[str, Any], query: str, sql_history: List[Dict], 
                        semantic_results: Optional[Dict] = None) -> str:
    """재시도용 프롬프트 (에러 히스토리 + 시맨틱 검색 결과 포함)"""
    
    history_text = "\n\n".join([
        f"--- Attempt {h['attempt']} ---\n"
        f"SQL: {h['sql']}\n"
        f"Error: {h['error']}"
        for h in sql_history
    ])
    
    # 0건 케이스 여부 확인
    has_zero_rows = any("ZERO_ROWS" in str(h.get("error", "")) for h in sql_history)
    
    # 0건 케이스에 대한 특별 분석 힌트
    zero_rows_hint = ""
    if has_zero_rows:
        zero_rows_hint = """
[⚠️ ZERO ROWS ANALYSIS - CRITICAL]
Your SQL executed successfully but returned 0 rows. This is NOT a syntax error.
You need to analyze WHY no data matched your query conditions.

COMMON CAUSES & FIXES:
1. COLUMN NAME MISMATCH:
   - You might have used a column name that doesn't exist
   - Example: 'gender' vs 'sex', 'patient_id' vs 'subjectid'
   - FIX: Check the schema below and use the EXACT column names

2. VALUE MISMATCH:
   - WHERE condition values might not match actual data
   - Example: WHERE sex = 'male' but actual values are 'M'/'F'
   - FIX: Remove or adjust the WHERE conditions

3. TOO RESTRICTIVE CONDITIONS:
   - Multiple WHERE conditions might have no intersection
   - FIX: Try with fewer conditions first

[ACTION REQUIRED]
- FIRST: Identify which column/value caused the 0 rows
- SECOND: Check the schema for correct column names
- THIRD: Generate a corrected SQL with proper column names and realistic conditions

"""
    
    # 시맨틱 검색 결과가 있으면 포함
    semantic_section = ""
    if semantic_results:
        semantic_section = f"""
{_format_semantic_results(semantic_results)}

[HINT]
The semantic search results show verified column/table names.
Use these to fix any column/table name errors from previous attempts.

"""
    
    return f"""You are a medical data extraction expert. Your previous SQL attempts FAILED.
Carefully analyze the errors and generate a CORRECTED SQL query.

[PREVIOUS FAILED ATTEMPTS - LEARN FROM THESE ERRORS]
{history_text}
{zero_rows_hint}
{semantic_section}[DB Schema - VERIFY TABLE/COLUMN NAMES HERE]
{_format_schema(context['db_schema'])}

[Ontology & Relationships (Neo4j)]
{_format_ontology(context['ontology'])}

[User Query]
{query}

[Instructions]
1. CAREFULLY analyze why the previous SQL(s) failed.
2. Common issues to check:
   - Table name typos or non-existent tables
   - Column name typos or non-existent columns  
   - Incorrect JOIN conditions
   - Missing table aliases
   - Incorrect data types in comparisons
   - WHERE condition values that don't match actual data
3. VERIFY all table and column names exist in the schema above.
4. If semantic search results are provided, USE those verified column names.
5. Generate a corrected SQL that fixes the specific errors.

[Output Format]
{{
  "reasoning": "What was wrong and how you fixed it",
  "sql": "SELECT ... FROM ... WHERE ..."
}}
"""


def _format_schema(schema: Dict[str, List[str]]) -> str:
    """스키마를 읽기 쉬운 텍스트로 포맷"""
    lines = []
    for table, columns in schema.items():
        lines.append(f"Table: {table}")
        for col in columns[:20]:  # 테이블당 최대 20개 컬럼
            lines.append(f"  - {col}")
        if len(columns) > 20:
            lines.append(f"  ... and {len(columns) - 20} more columns")
        lines.append("")
    return "\n".join(lines)


def _format_ontology(ontology: Dict[str, Any]) -> str:
    """온톨로지를 읽기 쉬운 텍스트로 포맷"""
    lines = []
    
    # Definitions
    definitions = ontology.get("definitions", {})
    if definitions:
        lines.append("Definitions:")
        for term, definition in list(definitions.items())[:20]:
            lines.append(f"  - {term}: {definition[:100]}")
        if len(definitions) > 20:
            lines.append(f"  ... and {len(definitions) - 20} more definitions")
    
    # Relationships
    relationships = ontology.get("relationships", [])
    if relationships:
        lines.append("\nRelationships:")
        for rel in relationships[:10]:
            lines.append(
                f"  - {rel.get('source_table', '?')}.{rel.get('source_column', '?')} → "
                f"{rel.get('target_table', '?')}.{rel.get('target_column', '?')}"
            )
        if len(relationships) > 10:
            lines.append(f"  ... and {len(relationships) - 10} more relationships")
    
    return "\n".join(lines) if lines else "No ontology information available."
