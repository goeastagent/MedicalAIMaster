import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.agents.state import AgentState, ColumnSchema, AnchorInfo, ProjectContext, OntologyContext
from src.processors.tabular import TabularProcessor
from src.processors.signal import SignalProcessor
from src.utils.llm_client import get_llm_client
from src.utils.ontology_manager import get_ontology_manager
from src.utils.llm_cache import get_llm_cache
from src.config import HumanReviewConfig

# --- Global resource initialization ---
llm_client = get_llm_client()
ontology_manager = get_ontology_manager()
llm_cache = get_llm_cache()  # Global cache instance
processors = [
    TabularProcessor(llm_client),
    SignalProcessor(llm_client)
]



def load_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 1] Load file and extract basic metadata
    """
    file_path = state["file_path"]
    
    print("\n" + "="*80)
    print(f"📂 [LOADER NODE] Starting - {os.path.basename(file_path)}")
    print("="*80)
    
    # 1. Find appropriate Processor
    selected_processor = next((p for p in processors if p.can_handle(file_path)), None)
    
    if not selected_processor:
        return {
            "logs": [f"❌ Error: Unsupported file format ({file_path})"],
            "needs_human_review": True,
            "human_question": "Unsupported file format. How would you like to process this file?"
        }

    # 2. Extract metadata (Anchor detection is also performed here)
    try:
        raw_metadata = selected_processor.extract_metadata(file_path)
        processor_type = raw_metadata.get("processor_type", "unknown")
        
        # Check if Processor failed to find or was uncertain about Anchor
        anchor_info = raw_metadata.get("anchor_info", {})
        anchor_status = anchor_info.get("status", "MISSING")
        anchor_msg = anchor_info.get("msg", "")

        log_message = f"✅ [Loader] {processor_type.upper()} analysis complete. Anchor Status: {anchor_status}"

        print(f"\n✅ [LOADER NODE] Complete")
        print(f"   - Processor: {processor_type}")
        print(f"   - Columns: {len(raw_metadata.get('columns', []))}")
        print(f"   - Anchor Status: {anchor_status}")
        print("="*80)

        return {
            "file_type": processor_type,
            "raw_metadata": raw_metadata,
            "logs": [log_message]
        }
    except Exception as e:
        print(f"\n❌ [LOADER NODE] Error: {str(e)}")
        print("="*80)
        return {
            "logs": [f"❌ [Loader] Critical error: {str(e)}"],
            "error_message": str(e)
        }


def analyze_semantics_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 2] Semantic Analysis (Semantic Reasoning)
    Core brain that finalizes schema based on Processor results
    [NEW] References Global Context (Project Level) to ensure Anchor consistency across files.
    """
    print("\n" + "="*80)
    print("🧠 [ANALYZER NODE] Starting - Semantic Analysis")
    print("="*80)
    
    metadata = state["raw_metadata"]
    local_anchor_info = metadata.get("anchor_info", {})
    human_feedback = state.get("human_feedback")
    
    # Get Global Context (initialize if not exists)
    project_context = state.get("project_context", {
        "master_anchor_name": None, 
        "known_aliases": [], 
        "example_id_values": []
    })
    
    finalized_anchor = state.get("finalized_anchor")
    retry_count = state.get("retry_count", 0)
    
    # Prevent infinite loop: force processing after 3+ retries
    if retry_count >= 3:
        log_msg = f"⚠️ [Analyzer] Retry count exceeded ({retry_count}). Forcing local Anchor."
        
        # Use locally found Anchor as-is
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": local_anchor_info.get("target_column", "unknown"),
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": f"Forced confirmation after {retry_count} retries",
            "mapped_to_master": project_context.get("master_anchor_name")
        }
        
        # Skip schema analysis and complete
        return {
            "finalized_anchor": finalized_anchor,
            "finalized_schema": [],
            "project_context": project_context,
            "needs_human_review": False,
            "human_feedback": None,
            "retry_count": retry_count,
            "logs": [log_msg, "⚠️ [Analyzer] Schema analysis skipped (retry exceeded)"]
        }

    # --- Scenario A: Process user feedback (re-entry) ---
    if human_feedback:
        log_msg = f"🗣️ [Feedback] User feedback received: '{human_feedback}'"
        
        # ⭐ [FIX] Parse user input - distinguish column name vs description
        parsed_column = _parse_human_feedback_to_column(
            feedback=human_feedback,
            available_columns=metadata.get("columns", []),
            master_anchor=project_context.get("master_anchor_name"),
            file_path=state.get("file_path", "")
        )
        
        if parsed_column.get("action") == "skip":
            # Skip request
            log_msg += " → File skip requested"
            return {
                "finalized_anchor": None,
                "finalized_schema": [],
                "project_context": project_context,
                "needs_human_review": False,
                "human_feedback": None,
                "skip_indexing": True,
                "logs": [log_msg, "⏭️ [Analyzer] File skipped by user request"]
            }
        
        determined_column = parsed_column.get("column_name", human_feedback.strip())
        reasoning = parsed_column.get("reasoning", "User manually confirmed.")
        
        print(f"   → Parsing result: '{determined_column}'")
        print(f"   → Reasoning: {reasoning}")
        
        # Force Anchor confirmation based on feedback
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": determined_column,
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": reasoning,
            "mapped_to_master": project_context.get("master_anchor_name") 
        }
        
        # ⭐ [FIX] Reset needs_human_confirmation after feedback processing
        # Prevents re-entering review_required in check_confidence
        if "anchor_info" in metadata:
            metadata["anchor_info"]["needs_human_confirmation"] = False
            metadata["anchor_info"]["status"] = "CONFIRMED"
        
        # Consider feedback processing complete and proceed (don't return)
    
    # --- Scenario B: When Anchor is not yet finalized -> Check Global Context ---
    if not finalized_anchor:
        
        # [NEW] Case 1: Project already has agreed Anchor (Leader)
        if project_context.get("master_anchor_name"):
            master_name = project_context["master_anchor_name"]
            
            # LLM에게 비교 요청 (Global Context vs Local Data)
            comparison = _compare_with_global_context(
                local_metadata=metadata,
                local_anchor_info=local_anchor_info,
                project_context=project_context
            )
            
            # Debug: comparison result log
            comparison_status = comparison.get("status", "UNKNOWN")
            comparison_msg = comparison.get("message", "")
            print(f"\n[DEBUG] Global Anchor comparison result: {comparison_status}")
            print(f"[DEBUG] Message: {comparison_msg}")
            print(f"[DEBUG] Target Column: {comparison.get('target_column', 'N/A')}")
            
            if comparison["status"] == "MATCH":
                # Match success -> auto confirm
                target_col = comparison["target_column"]
                finalized_anchor = {
                    "status": "CONFIRMED",
                    "column_name": target_col,
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": f"Matched with global master anchor '{master_name}'",
                    "mapped_to_master": master_name
                }
                state["logs"].append(f"🔗 [Anchor Link] Matched with Global Anchor '{master_name}' (Local: '{target_col}')")
            
            elif comparison["status"] == "INDIRECT_LINK":
                # ⭐ [NEW] Indirect link success -> auto confirm (no human intervention needed!)
                via_col = comparison["target_column"]
                via_table = comparison.get("via_table", "unknown")
                
                finalized_anchor = {
                    "status": "INDIRECT_LINK",
                    "column_name": via_col,  # Link column (e.g., caseid)
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": comparison.get("message"),
                    "mapped_to_master": master_name,
                    "via_table": via_table,
                    "link_type": "indirect"  # Indirect link via FK
                }
                
                print(f"\n✅ [INDIRECT_LINK] Auto-confirmed indirect link!")
                print(f"   - Link column: {via_col}")
                print(f"   - Via table: {via_table}")
                print(f"   - Master Anchor: {master_name}")
                
                state["logs"].append(
                    f"🔗 [Indirect Link] Indirectly linked to '{master_name}' in '{via_table}' via '{via_col}'"
                )
                
            else:
                # Conflict or missing -> human intervention
                msg = comparison.get("message", "Anchor mismatch occurred")
                
                # Generate natural question with LLM
                natural_question = _generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "master_anchor": master_name,
                        "candidates": local_anchor_info.get("target_column"),
                        "reasoning": msg,
                        "columns": metadata.get("columns", [])
                    },
                    issue_type="anchor_conflict"
                )
                
                return {
                    "needs_human_review": True,
                    "human_question": natural_question,
                    "retry_count": retry_count,  # Keep current retry count
                    "logs": [f"⚠️ [Analyzer] Global Anchor mismatch (Status: {comparison_status}). Retry: {retry_count}/3"]
                }

        # [NEW] Case 2: This is the first file (no Global Context)
        else:
            # Flexible judgment: Processor uncertainty + LLM review
            processor_confidence = local_anchor_info.get("confidence", 0.5 if local_anchor_info.get("needs_human_confirmation") else 0.9)
            
            review_decision = _should_request_human_review(
                file_path=state.get("file_path", ""),
                issue_type="anchor_detection",
                context={
                    "processor_msg": local_anchor_info.get("msg"),
                    "candidates": local_anchor_info.get("target_column"),
                    "columns": metadata.get("columns", []),
                    "processor_needs_confirmation": local_anchor_info.get("needs_human_confirmation", False)
                },
                rule_based_confidence=processor_confidence
            )
            
            if review_decision["needs_review"]:
                question = _generate_natural_human_question(
                    file_path=state.get("file_path", ""),
                    context={
                        "reasoning": local_anchor_info.get("msg"),
                        "candidates": local_anchor_info.get("target_column", "None"),
                        "columns": metadata.get("columns", [])
                    },
                    issue_type="anchor_uncertain"
                )
                
                return {
                    "needs_human_review": True,
                    "human_question": question,
                    "logs": [f"⚠️ [Analyzer] Anchor uncertain (first file). {review_decision['reason']}"]
                }
            
            # Confident -> confirm
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": local_anchor_info.get("target_column"),
                "is_time_series": local_anchor_info.get("is_time_series"),
                "reasoning": local_anchor_info.get("reasoning"),
                "mapped_to_master": None  # Will become master
            }

    # --- 3. Update Global Context (First-Come Leader Strategy) ---
    # If Anchor is confirmed and no master exists, this file's Anchor becomes master
    if finalized_anchor and not project_context.get("master_anchor_name"):
        project_context["master_anchor_name"] = finalized_anchor["column_name"]
        project_context["known_aliases"].append(finalized_anchor["column_name"])
        state["logs"].append(f"👑 [Project Context] New Master Anchor set: '{finalized_anchor['column_name']}'")

    # --- 4. Detailed schema analysis (common) ---
    schema_analysis = _analyze_columns_with_llm(
        columns=metadata.get("columns", []),
        sample_data=metadata.get("column_details", {}),
        anchor_context=finalized_anchor
    )

    print(f"\n✅ [ANALYZER NODE] Complete")
    print(f"   - Anchor: {finalized_anchor.get('column_name', 'N/A')}")
    print(f"   - Mapped to Master: {finalized_anchor.get('mapped_to_master', 'N/A')}")
    print(f"   - Schema Columns: {len(schema_analysis)}")
    print("="*80)

    result = {
        "finalized_anchor": finalized_anchor,
        "finalized_schema": schema_analysis,
        "project_context": project_context,  # Return updated context
        "raw_metadata": metadata,  # ⭐ [FIX] Return updated raw_metadata (needs_human_confirmation reset)
        "needs_human_review": False,
        "human_feedback": None, 
        "logs": ["🧠 [Analyzer] Complete schema and ontology analysis."]
    }
    
    print(f"\n[DEBUG ANALYZER] Return value:")
    print(f"   - finalized_schema: {len(result['finalized_schema'])}")
    print(f"   - needs_human_review: {result['needs_human_review']}")
    
    return result


def human_review_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 3] Human-in-the-loop waiting node
    In actual execution, LangGraph's interrupt mechanism stops here
    In test environment, increase retry count to prevent infinite loop
    """
    print("\n" + "="*80)
    print("🛑 [HUMAN REVIEW NODE] Starting - User confirmation required")
    print("="*80)
    
    question = state.get("human_question", "Confirmation required.")
    retry_count = state.get("retry_count", 0)
    
    # Increase retry count
    new_retry_count = retry_count + 1
    
    print(f"\n⚠️  Question: {question[:150]}...")
    print(f"🔄 Retry count: {new_retry_count}/3")
    print("="*80)
    
    return {
        "retry_count": new_retry_count,
        "logs": [f"🛑 [Human Review] Waiting (retry: {new_retry_count}/3). Question: {question[:100]}..."]
    }


def index_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 4 - Phase 3] Build PostgreSQL DB (ontology-based)
    
    Expert feedback applied:
    - Chunk Processing (safe handling of large files)
    - Auto FK constraint creation (ALTER TABLE)
    - Auto index creation (Level 1-2)
    """
    import pandas as pd
    import os
    
    from database.connection import get_db_manager
    from database.schema_generator import SchemaGenerator
    
    print("\n" + "="*80)
    print("💾 [INDEXER NODE] Starting - PostgreSQL DB construction")
    print("="*80)
    
    schema = state.get("finalized_schema", [])
    file_path = state["file_path"]
    ontology = state.get("ontology_context", {})
    
    # Generate table name
    table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_").replace("-", "_")
    
    # DB manager
    db_manager = get_db_manager()
    
    try:
        # === 1. Load data (pandas auto-creates table) ===
        print(f"\n📥 [Data] Loading data...")
        
        # Check file size
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"   - File size: {file_size_mb:.1f}MB")
        
        total_rows = 0
        
        # SQLAlchemy engine for PostgreSQL (for pandas to_sql)
        engine = db_manager.get_sqlalchemy_engine()
        
        # [TEST MODE] Row limit (check environment variable)
        test_limit = os.environ.get("TEST_ROW_LIMIT")
        limit_kwargs = {}
        if test_limit:
            limit_rows = int(test_limit)
            limit_kwargs = {"nrows": limit_rows}
            print(f"⚠️ [TEST MODE] Data load limit applied: processing top {limit_rows} rows only")

        if file_size_mb > 50:  # Chunk processing for files > 50MB
            print(f"   - Large file - Chunk Processing applied (100,000 rows per chunk)")
            
            chunk_size = 100000
            # [TEST MODE] Apply limit even with chunk processing
            # nrows works with chunksize to limit total rows read
            
            for i, chunk in enumerate(pd.read_csv(file_path, chunksize=chunk_size, **limit_kwargs)):
                chunk.to_sql(
                    table_name, 
                    engine, 
                    if_exists='append' if i > 0 else 'replace',
                    index=False,
                    method='multi'  # PostgreSQL optimization
                )
                total_rows += len(chunk)
                print(f"      • Chunk {i+1}: {len(chunk):,} rows loaded (cumulative: {total_rows:,} rows)")
        else:
            # Load small files at once
            print(f"   - Regular file - loading at once")
            df = pd.read_csv(file_path, **limit_kwargs)
            df.to_sql(
                table_name, 
                engine, 
                if_exists='replace', 
                index=False,
                method='multi'
            )
            total_rows = len(df)
            print(f"   - {total_rows:,} rows loaded")
        
        print(f"✅ Data loading successful")
        
        # === 2. Create indices (performance optimization) ===
        print(f"\n🔍 [Index] Creating indices...")
        
        indices = SchemaGenerator.generate_indices(
            table_name=table_name,
            schema=schema,
            ontology_context=ontology
        )
        
        indices_created = []
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        for idx_ddl in indices:
            try:
                cursor.execute(idx_ddl)
                # Extract index name
                idx_name = idx_ddl.split('"')[1] if '"' in idx_ddl else idx_ddl.split()[2]
                indices_created.append(idx_name)
            except Exception as e:
                print(f"⚠️  Index creation failed: {e}")
        
        conn.commit()
        
        if indices_created:
            print(f"   - {len(indices_created)} indices created: {', '.join(indices_created)}")
        else:
            print(f"   - No indices created")
        
        # === 3. Verification ===
        print(f"\n✅ [Verify] Verifying...")
        
        # Check row count (PostgreSQL)
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        actual_rows = cursor.fetchone()[0]
        
        if actual_rows == total_rows:
            print(f"   - Row count matches: {actual_rows:,} rows ✅")
        else:
            print(f"   ⚠️ Row count mismatch: expected {total_rows:,}, actual {actual_rows:,}")
        
        # === [NEW] Save Column Metadata (Neo4j) ===
        if schema:
            print(f"\n📋 [Column Metadata] Saving column metadata...")
            
            if "column_metadata" not in ontology:
                ontology["column_metadata"] = {}
            
            ontology["column_metadata"][table_name] = {}
            
            for col_schema in schema:
                col_name = col_schema.get("original_name", "unknown")
                ontology["column_metadata"][table_name][col_name] = {
                    "original_name": col_name,
                    "full_name": col_schema.get("full_name"),
                    "inferred_name": col_schema.get("inferred_name"),
                    "description": col_schema.get("description"),
                    "description_kr": col_schema.get("description_kr"),
                    "data_type": col_schema.get("data_type"),
                    "unit": col_schema.get("unit"),
                    "typical_range": col_schema.get("typical_range"),
                    "is_pii": col_schema.get("is_pii", False),
                    "confidence": col_schema.get("confidence", 0)
                }
            
            print(f"   - {len(schema)} column metadata generated")
            
            # Save to Neo4j
            from src.utils.ontology_manager import get_ontology_manager
            ontology_manager = get_ontology_manager()
            ontology_manager.save(ontology)
            print(f"   - Neo4j save complete")
        
        print("="*80)
        
        return {
            "ontology_context": ontology,  # [NEW] Return updated ontology
            "logs": [
                f"💾 [Indexer] {table_name} created ({total_rows:,} rows)",
                f"🔍 [Indexer] Indices: {len(indices_created)}",
                "✅ [Done] Indexing process complete."
            ]
        }
        
    except Exception as e:
        print(f"\n❌ [Error] DB save failed: {str(e)}")
        print("="*80)
        
        import traceback
        traceback.print_exc()
        
        return {
            "logs": [f"❌ [Indexer] DB save failed: {str(e)}"],
            "error_message": str(e)
        }

# --- Helper Functions (Private) ---

def _analyze_columns_with_llm(columns: List[str], sample_data: Any, anchor_context: Dict) -> List[ColumnSchema]:
    """
    [Helper] Analyze column meaning, data type, PII status, units, etc. using LLM
    
    [Enhancements] Column metadata enrichment:
    - full_name: Abbreviation expansion (e.g., sbp → Systolic Blood Pressure)
    - unit: Measurement unit (e.g., mmHg, kg, cm)
    - typical_range: Medical normal range
    - sample_values: Actual sample values
    """
    # Context summary for LLM
    prompt = f"""
    You are a Medical Data Ontologist specializing in clinical database design.
    Analyze the columns of a medical dataset and provide DETAILED metadata.
    
    [Context]
    - Patient Identifier (Anchor): {anchor_context.get('column_name')}
    - Is Time Series: {anchor_context.get('is_time_series')}
    
    [Columns to Analyze]
    """
    
    # If sample_data is a list (from TabularProcessor)
    if isinstance(sample_data, list):
        for col_detail in sample_data:
            col_name = col_detail.get('column_name', 'unknown')
            col_type = col_detail.get('column_type', 'unknown')
            samples = col_detail.get('samples', [])
            
            if col_type == 'categorical':
                unique_vals = col_detail.get('unique_values', [])
                prompt += f"- Column: '{col_name}' | Type: CATEGORICAL | Unique Values: {unique_vals}\n"
            else:
                min_val = col_detail.get('min', 'N/A')
                max_val = col_detail.get('max', 'N/A')
                prompt += f"- Column: '{col_name}' | Type: CONTINUOUS | Range: [{min_val}, {max_val}] | Samples: {samples}\n"
    # If sample_data is a dictionary (backward compatibility)
    elif isinstance(sample_data, dict):
        for col in columns:
            details = sample_data.get(col, {})
            samples = details.get("sample_values", [])
            prompt += f"- Column: '{col}', Samples: {samples}\n"
    else:
        # If neither, provide column names only
        for col in columns:
            prompt += f"- Column: '{col}'\n"

    prompt += """
    [Task]
    For EACH column, provide a JSON object with DETAILED metadata:
    
    1. original_name: The exact column name as provided (REQUIRED)
    2. inferred_name: Human-readable name (e.g., 'sbp' → 'Systolic Blood Pressure')
    3. full_name: Full medical term without abbreviation (e.g., 'Systolic Blood Pressure')
    4. description: Brief medical description (what does this column measure?)
    5. description_kr: Korean description for Korean users (한글 설명)
    6. data_type: SQL compatible type (VARCHAR, INT, FLOAT, TIMESTAMP, BOOLEAN)
    7. unit: Measurement unit if applicable (e.g., "mmHg", "kg", "mg/dL", "bpm", "°C", null if N/A)
    8. typical_range: Normal/typical value range in medical context (e.g., "90-140" for systolic BP, null if N/A)
    9. is_pii: Boolean (true if it contains name, phone, address, social security number)
    10. confidence: 0.0 to 1.0 (how confident are you about this analysis?)
    
    [Examples]
    - 'sbp' → {"original_name": "sbp", "inferred_name": "Systolic BP", "full_name": "Systolic Blood Pressure", 
               "description": "Peak arterial pressure during heart contraction", "description_kr": "심장 수축시 최고 동맥압 (수축기 혈압)",
               "data_type": "FLOAT", "unit": "mmHg", "typical_range": "90-140", "is_pii": false, "confidence": 0.95}
    - 'hr' → {"original_name": "hr", "inferred_name": "Heart Rate", "full_name": "Heart Rate",
              "description": "Number of heartbeats per minute", "description_kr": "분당 심박수",
              "data_type": "INT", "unit": "bpm", "typical_range": "60-100", "is_pii": false, "confidence": 0.95}
    - 'age' → {"original_name": "age", "inferred_name": "Patient Age", "full_name": "Patient Age",
               "description": "Age of the patient", "description_kr": "환자 나이",
               "data_type": "INT", "unit": "years", "typical_range": "0-120", "is_pii": false, "confidence": 0.90}

    Respond with a JSON object: {"columns": [list of column objects]}
    """
    
    # LLM call
    response = llm_client.ask_json(prompt)
    
    # Check if response is list or dict (wrapping list) and parse
    if isinstance(response, dict) and "columns" in response:
        result_list = response["columns"]
    elif isinstance(response, list):
        result_list = response
    else:
        result_list = []  # Error handling needed

    # Map results
    final_schema = []
    for idx, item in enumerate(result_list):
        # Use original_name if available, otherwise match by index
        original = item.get("original_name") or (columns[idx] if idx < len(columns) else "unknown")
        
        final_schema.append({
            "original_name": original,
            "inferred_name": item.get("inferred_name", original),
            "full_name": item.get("full_name", item.get("inferred_name", original)),
            "description": item.get("description", ""),
            "description_kr": item.get("description_kr", ""),
            "data_type": item.get("data_type", "VARCHAR"),
            "unit": item.get("unit"),  # None if not applicable
            "typical_range": item.get("typical_range"),  # None if not applicable
            "standard_concept_id": None, 
            "is_pii": item.get("is_pii", False),
            "confidence": item.get("confidence", 0.5)
        })
        
    return final_schema


def _compare_with_global_context(local_metadata: Dict, local_anchor_info: Dict, project_context: Dict) -> Dict[str, Any]:
    """
    [Helper] Compare current file data with project Global Anchor info (using LLM)
    
    ⭐ [NEW] Check ontology relationships for indirect connections
    e.g., lab_data without subjectid can link to clinical_data.subjectid via caseid
    """
    master_name = project_context["master_anchor_name"]
    local_cols = local_metadata.get("columns", [])
    local_candidate = local_anchor_info.get("target_column")
    
    # Extract table name from current filename
    file_path = local_metadata.get("file_path", "")
    current_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
    
    # 1. 이름이 완전히 같은 경우 (Fast Path)
    if master_name in local_cols:
        return {"status": "MATCH", "target_column": master_name, "message": "Exact name match"}

    # ⭐ [NEW] 2. 온톨로지 기반 간접 연결 확인
    indirect_link = _check_indirect_link_via_ontology(
        current_table=current_table,
        local_cols=local_cols,
        master_anchor=master_name
    )
    
    if indirect_link:
        return {
            "status": "INDIRECT_LINK",
            "target_column": indirect_link["via_column"],
            "via_table": indirect_link["via_table"],
            "master_anchor": master_name,
            "message": indirect_link["message"]
        }

    # 3. 로컬 후보가 없는 경우 (Processor가 못 찾음)
    if not local_candidate:
        return {
            "status": "MISSING",
            "target_column": None,
            "message": f"No anchor candidate found in local file. Master anchor '{master_name}' not found in columns: {local_cols}"
        }

    # 3. LLM을 통한 의미론적 비교
    prompt = f"""
    You are a Medical Data Integration Agent.
    Check if the new file contains the Project's Master Anchor (Patient ID).

    [Project Context / Global Master]
    - Master Anchor Name: '{master_name}'
    - Known Aliases: {project_context.get('known_aliases')}
    
    [New File Info]
    - Candidate Column found by AI: '{local_candidate}'
    - All Columns in file: {local_cols}
    
    [Task]
    Determine if any column in the new file represents the same 'Patient ID' entity as the Global Master.
    - If the candidate '{local_candidate}' is a synonym for '{master_name}' (e.g. 'pid' vs 'subject_id'), return MATCH.
    - If another column in 'All Columns' looks like the ID, return MATCH with that column.
    - If you cannot find a matching column, return MISSING.
    - If you are unsure, return CONFLICT.

    Respond with JSON:
    {{
        "status": "MATCH" or "MISSING" or "CONFLICT",
        "target_column": "name_of_column_in_new_file" (or null if missing),
        "message": "Reasoning for the decision"
    }}
    """
    
    try:
        result = llm_client.ask_json(prompt)
        
        # LLM 응답 검증 및 정규화
        if not isinstance(result, dict):
            return {"status": "CONFLICT", "target_column": None, "message": "LLM returned invalid format"}
        
        status = result.get("status", "CONFLICT").upper()
        if status not in ["MATCH", "MISSING", "CONFLICT"]:
            status = "CONFLICT"
        
        return {
            "status": status,
            "target_column": result.get("target_column"),
            "message": result.get("message", "No explanation provided")
        }
        
    except Exception as e:
        return {"status": "CONFLICT", "target_column": None, "message": f"Error during anchor comparison: {str(e)}"}


# ============================================================================
# Indirect Link Check (Ontology-based)
# ============================================================================

def _check_indirect_link_via_ontology(current_table: str, local_cols: list, master_anchor: str) -> Optional[Dict]:
    """
    ⭐ [NEW] Check ontology relationships for indirect connections
    
    Example:
    - lab_data does not have subjectid
    - But ontology has "lab_data.caseid → clinical_data.caseid" relationship
    - clinical_data has subjectid
    - Therefore lab_data is indirectly connected to subjectid via caseid
    
    Returns:
        Indirect link info dict or None
    """
    try:
        # Load ontology
        ontology = ontology_manager.load()
        if not ontology:
            return None
        
        relationships = ontology.get("relationships", [])
        file_tags = ontology.get("file_tags", {})
        
        print(f"\n🔗 [Indirect Link Check] {current_table}")
        print(f"   - Ontology relationships: {len(relationships)}")
        
        # Find relationships where current table is source
        for rel in relationships:
            source_table = rel.get("source_table", "")
            target_table = rel.get("target_table", "")
            source_column = rel.get("source_column", "")
            target_column = rel.get("target_column", "")
            
            # If current_table is source
            if current_table.lower() in source_table.lower() or source_table.lower() in current_table.lower():
                # Check if link column exists in current file
                if source_column in local_cols:
                    # Check if target_table has master_anchor
                    target_has_master = _check_table_has_column(file_tags, target_table, master_anchor)
                    
                    if target_has_master:
                        message = (
                            f"✅ Indirect link found! "
                            f"'{current_table}.{source_column}' → '{target_table}.{target_column}' relation "
                            f"connects to '{master_anchor}'"
                        )
                        print(f"   {message}")
                        
                        return {
                            "via_column": source_column,
                            "via_table": target_table,
                            "via_relation": f"{source_table}.{source_column} → {target_table}.{target_column}",
                            "message": message
                        }
        
        print(f"   - No indirect link found")
        return None
        
    except Exception as e:
        print(f"   ⚠️ Indirect link check error: {e}")
        return None


def _check_table_has_column(file_tags: Dict, table_name: str, column_name: str) -> bool:
    """
    Check if a specific table has a specific column in file_tags
    """
    for file_path, tag_info in file_tags.items():
        # Extract table name from filename
        file_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
        
        if table_name.lower() in file_table.lower() or file_table.lower() in table_name.lower():
            columns = tag_info.get("columns", [])
            if column_name in columns:
                return True
    
    return False


# ============================================================================
# Ontology Builder Functions (Phase 0-1)
# ============================================================================

def _collect_negative_evidence(col_name: str, samples: list, unique_vals: list) -> dict:
    """
    [Rule] Collect negative evidence (detect data quality issues)
    
    Args:
        col_name: Column name
        samples: Sample values list
        unique_vals: Unique values list
    
    Returns:
        Negative evidence dictionary
    """
    import numpy as np
    
    total = len(samples)
    unique = len(unique_vals)
    
    # Calculate nulls
    null_count = sum(
        1 for s in samples 
        if s is None or s == '' or (isinstance(s, float) and np.isnan(s))
    )
    
    negative_evidence = []
    
    # 1. Near unique but has duplicates (possible data error)
    if total > 0 and unique / total > 0.95 and unique != total:
        dup_rate = (total - unique) / total
        negative_evidence.append({
            "type": "near_unique_with_duplicates",
            "detail": f"{unique/total:.1%} unique BUT {dup_rate:.1%} duplicates - possible data error",
            "severity": "medium"
        })
    
    # 2. ID-like but has nulls (cannot be PK)
    if 'id' in col_name.lower() and null_count > 0:
        null_rate = null_count / total
        negative_evidence.append({
            "type": "identifier_with_nulls",
            "detail": f"Column name suggests ID BUT {null_rate:.1%} null values",
            "severity": "high" if null_rate > 0.1 else "low"
        })
    
    # 3. Cardinality too high (possible free text)
    if unique > 100:
        negative_evidence.append({
            "type": "high_cardinality",
            "detail": f"{unique} unique values - might be free text, not categorical",
            "severity": "low"
        })
    
    return {
        "has_issues": len(negative_evidence) > 0,
        "issues": negative_evidence,
        "null_ratio": null_count / total if total > 0 else 0.0
    }


def _summarize_long_values(values: list, max_length: int = 50) -> list:
    """
    [Rule] Summarize long text (Context Window management)
    
    Args:
        values: Values list
        max_length: Maximum length (summarize if exceeded)
    
    Returns:
        Summarized values list
    """
    summarized = []
    
    for val in values:
        val_str = str(val)
        
        if len(val_str) > max_length:
            # Replace with meta info (save tokens)
            preview = val_str[:20].replace('\n', ' ')
            summarized.append(f"[Text: {len(val_str)} chars, starts='{preview}...']")
        else:
            summarized.append(val_str)
    
    return summarized


def _parse_metadata_content(file_path: str) -> dict:
    """
    [Rule] Parse metadata file (CSV → Dictionary)
    
    Args:
        file_path: Metadata file path
    
    Returns:
        definitions dictionary {parameter: description}
    """
    import pandas as pd
    
    definitions = {}
    
    try:
        df = pd.read_csv(file_path)
        
        # Common metadata structure: [Parameter/Name, Description, ...]
        if len(df.columns) >= 2:
            key_col = df.columns[0]
            desc_col = df.columns[1]
            
            for _, row in df.iterrows():
                key = str(row[key_col]).strip()
                desc = str(row[desc_col]).strip()
                
                # Combine additional info (Unit, Type, etc.)
                extra_info = []
                for col in df.columns[2:]:
                    val = row[col]
                    if pd.notna(val) and str(val).strip():
                        extra_info.append(f"{col}={val}")
                
                if extra_info:
                    desc += " | " + " | ".join(extra_info)
                
                definitions[key] = desc
        
        return definitions
        
    except Exception as e:
        print(f"❌ [Parse Error] {file_path}: {e}")
        return {}


def _build_metadata_detection_context(file_path: str, metadata: dict) -> dict:
    """
    [Rule] Build context for metadata detection (preprocessing)
    
    Args:
        file_path: File path
        metadata: raw_metadata extracted by Processor
    
    Returns:
        Context to provide to LLM
    """
    basename = os.path.basename(file_path)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    # Rule: Parse filename
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    columns = metadata.get("columns", [])
    column_details = metadata.get("column_details", [])
    
    # Rule: Organize sample data
    sample_summary = []
    total_text_length = 0
    
    for col_info in column_details[:5]:  # First 5 columns only
        col_name = col_info.get('column_name', 'unknown')
        samples = col_info.get('samples', [])
        col_type = col_info.get('column_type', 'unknown')
        
        # If categorical, also provide unique values
        if col_type == 'categorical':
            unique_vals = col_info.get('unique_values', [])[:20]
            # Summarize long text (Rule)
            unique_vals_summarized = _summarize_long_values(unique_vals, max_length=50)
        else:
            unique_vals = samples[:10]
            unique_vals_summarized = _summarize_long_values(unique_vals, max_length=50)
        
        # Rule: Calculate average text length
        avg_length = 0.0
        if samples:
            text_lengths = [len(str(s)) for s in samples]
            avg_length = sum(text_lengths) / len(text_lengths)
            total_text_length += avg_length
        
        # [NEW] Collect negative evidence (Rule)
        negative_evidence = _collect_negative_evidence(col_name, samples, unique_vals if unique_vals else [])
        
        # Summarize samples too
        samples_summarized = _summarize_long_values(samples[:3], max_length=50)
        
        sample_summary.append({
            "column": col_name,
            "type": col_type,
            "samples": samples_summarized,
            "unique_values": unique_vals_summarized,
            "avg_text_length": round(avg_length, 1),
            "null_ratio": negative_evidence.get("null_ratio", 0.0),  # [NEW]
            "negative_evidence": negative_evidence.get("issues", [])  # [NEW]
        })
    
    # Estimate context size
    context_size = len(json.dumps(sample_summary))
    
    # If too large, reduce samples (Rule)
    if context_size > 3000:
        sample_summary = sample_summary[:3]
        context_size = len(json.dumps(sample_summary))
    
    return {
        "filename": basename,
        "name_parts": parts,
        "base_name": base_name,
        "extension": extension,
        "columns": columns,
        "num_columns": len(columns),
        "sample_data": sample_summary,
        "avg_text_length_overall": round(total_text_length / max(len(sample_summary), 1), 1),
        "context_size_bytes": context_size
    }


def _ask_llm_is_metadata(context: dict) -> dict:
    """
    [LLM] Determine if file is metadata
    
    Args:
        context: Pre-processed context by Rules
    
    Returns:
        Judgment result {is_metadata, confidence, reasoning, indicators}
    """
    # Use global cache
    # Check cache
    cached = llm_cache.get("metadata_detection", context)
    if cached:
        return cached
    
    # LLM prompt
    prompt = f"""
You are a Data Classification Expert.

I have pre-processed file information using rules. Based on these facts, determine if this is METADATA or TRANSACTIONAL DATA.

[PRE-PROCESSED FILE INFORMATION - Extracted by Rules]
Filename: {context['filename']}
Parsed Name Parts: {context['name_parts']}  (parsed by Rule)
Base Name: {context['base_name']}
Extension: {context['extension']}
Number of Columns: {context['num_columns']}
Columns: {context['columns']}

[PRE-PROCESSED SAMPLE DATA - Extracted by Rules]
{json.dumps(context['sample_data'], indent=2)}
(Note: avg_text_length, unique_values, null_ratio, and negative_evidence were calculated by rules)

[IMPORTANT - Check Negative Evidence]
Each column has "negative_evidence" field showing data quality issues if any:
- near_unique_with_duplicates: Almost unique but has some duplicates
- identifier_with_nulls: Column name suggests ID but has null values
- high_cardinality: Too many unique values for categorical

Use this information to improve your judgment.

[DEFINITION]
- METADATA file: Describes OTHER data (e.g., column definitions, parameter lists, codebooks)
  * Contains descriptive text about columns/variables
  * Usually has structure like: [Name/ID, Description, Unit, Type]
  * Content is documentation, not measurements/transactions
  
- TRANSACTIONAL DATA: Actual records/measurements
  * Contains patient records, lab results, events, etc.
  * Values are data points, not descriptions

[YOUR TASK - Interpret Pre-processed Information]
Using the parsed filename and pre-calculated statistics, classify this file:

1. **Filename Analysis**:
   - Look at name_parts: if contains "parameters", "dict", "definition" → likely metadata
   - Look at base_name: what domain does it represent?

2. **Column Structure**:
   - Is it Key-Value format? (e.g., [Parameter, Description, Unit])
   - Or wide transactional format? (many columns with diverse types)

3. **Sample Content Analysis**:
   - Check avg_text_length: Long text (>30 chars) → likely descriptions
   - Check unique_values: Are they codes/IDs or explanatory text?

IMPORTANT: I already did the heavy lifting (parsing, statistics). 
You interpret the MEANING of these pre-processed facts.

[OUTPUT FORMAT - JSON ONLY]
{{
    "is_metadata": true or false,
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation based on filename, structure, and content",
    "indicators": {{
        "filename_hint": "strong/weak/none",
        "structure_hint": "dictionary-like/tabular/unclear",
        "content_type": "descriptive/transactional/mixed"
    }}
}}
"""
    
    try:
        result = llm_client.ask_json(prompt)
        
        # Save to cache
        llm_cache.set("metadata_detection", context, result)
        
        # Validate confidence
        confidence = result.get("confidence", 0.0)
        if confidence < 0.75:
            print(f"⚠️  [Metadata Detection] Low confidence ({confidence:.2%})")
            print(f"    Reasoning: {result.get('reasoning', 'N/A')[:100]}...")
        
        return result
        
    except Exception as e:
        print(f"❌ [Metadata Detection] LLM Error: {e}")
        # Fallback
        return {
            "is_metadata": False,  # Conservative default
            "confidence": 0.0,
            "reasoning": f"LLM error: {str(e)}",
            "indicators": {},
            "needs_human_review": True
        }


def _find_common_columns(current_cols: List[str], existing_tables: dict) -> List[dict]:
    """
    [Rule] Find common columns between current table and existing tables (FK candidate search)
    
    Args:
        current_cols: Column list of current table
        existing_tables: Existing tables info {table_name: {columns: [...], ...}}
    
    Returns:
        FK candidate list
    """
    candidates = []
    
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        # Find exact matching columns (Rule - exact match)
        common_cols = set(current_cols) & set(existing_cols)
        
        for common_col in common_cols:
            candidates.append({
                "column_name": common_col,
                "current_table": "new_table",
                "existing_table": table_name,
                "match_type": "exact_name",
                "confidence_hint": 0.9  # Same name = high probability of FK
            })
    
    # Find similar names (Rule - simple string normalization)
    # e.g., patient_id vs patientid, subjectid vs subject_id
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        for curr_col in current_cols:
            for exist_col in existing_cols:
                # Compare after removing underscores (Rule)
                curr_normalized = curr_col.replace('_', '').lower()
                exist_normalized = exist_col.replace('_', '').lower()
                
                if curr_normalized == exist_normalized and curr_col != exist_col:
                    candidates.append({
                        "current_col": curr_col,
                        "existing_col": exist_col,
                        "existing_table": table_name,
                        "match_type": "similar_name",
                        "confidence_hint": 0.7  # Similar = medium probability
                    })
    
    return candidates


def _extract_filename_hints(filename: str) -> dict:
    """
    [Rule + LLM] Extract semantic hints from filename
    
    Step 1 (Rule): Analyze filename structure
    Step 2 (LLM): Infer meaning (Entity Type, Level)
    
    Args:
        filename: Filename or file path
    
    Returns:
        Filename hints dictionary
    """
    # Use global cache
    
    # === Step 1: Rule-based filename parsing ===
    basename = os.path.basename(filename)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    # Split by underscore (Rule)
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    # Extract prefix/suffix (Rule)
    prefix = parts[0] if len(parts) >= 2 else None
    suffix = parts[-1] if len(parts) >= 2 else None
    
    # Structure info extracted by Rule
    parsed_structure = {
        "original_filename": basename,
        "name_without_ext": name_without_ext,
        "extension": extension,
        "parts": parts,
        "base_name": base_name,
        "prefix": prefix,
        "suffix": suffix,
        "has_underscore": '_' in name_without_ext,
        "num_parts": len(parts)
    }
    
    # === Step 2: LLM-based semantic inference ===
    
    # Check cache
    cached = llm_cache.get("filename_hints", parsed_structure)
    if cached:
        return cached
    
    # LLM prompt
    prompt = f"""
You are a Data Architecture Analyst.

I have parsed the filename structure using rules. Based on this, infer the semantic meaning.

[PARSED FILENAME STRUCTURE - Extracted by Rules]
{json.dumps(parsed_structure, indent=2)}

[YOUR TASK - Semantic Interpretation]
Using the PARSED STRUCTURE, infer:

1. **Entity Type**: What domain entity does base_name represent?
   - Examples: "lab" → Laboratory, "patient" → Patient, "clinical" → Case/Clinical
   - Use domain knowledge (medical, financial, etc.)

2. **Scope**: What is the data scope?
   - individual: Patient, Subject
   - event: Case, Admission, Visit, Stay
   - measurement: Lab, Vital, Sensor
   - treatment: Medication, Procedure

3. **Suggested Hierarchy Level**: (1=highest, 5=lowest)
   - Level 1: Patient, Subject
   - Level 2: Case, Admission, Visit
   - Level 3: Sub-event (ICU Stay)
   - Level 4: Measurement (Lab, Vital)
   - Level 5: Detail

4. **Data Type Indicator**: Based on suffix
   - "data", "records", "events" → transactional
   - "parameters", "dict", "info" → metadata
   - "master", "dim" → reference

5. **Related File Patterns**: Predict related files
   - If "lab_data", likely has "lab_parameters" or "lab_dict"

[OUTPUT FORMAT - JSON]
{{
    "entity_type": "Laboratory" or null,
    "scope": "measurement" or null,
    "suggested_level": 4 or null,
    "data_type_indicator": "transactional" or "metadata",
    "related_file_patterns": ["lab_parameters", "lab_dict"],
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation"
}}
"""
    
    try:
        # Use global llm_client
        hints = llm_client.ask_json(prompt)
        
        # Add default fields
        hints["filename"] = basename
        hints["base_name"] = base_name
        hints["parts"] = parts
        
        # Save to cache
        llm_cache.set("filename_hints", parsed_structure, hints)
        
        # Validate confidence
        if hints.get("confidence", 1.0) < 0.7:
            print(f"⚠️  [Filename Analysis] Low confidence ({hints.get('confidence'):.2%}) for {basename}")
        
        return hints
        
    except Exception as e:
        # On LLM failure, return minimal info
        print(f"❌ [Filename Analysis] LLM Error: {e}")
        return {
            "filename": basename,
            "base_name": base_name,
            "parts": parts,
            "entity_type": None,
            "scope": None,
            "suggested_level": None,
            "data_type_indicator": None,
            "related_file_patterns": [],
            "confidence": 0.0,
            "error": str(e)
        }


def _summarize_existing_tables(ontology_context: dict, processed_files_data: dict = None) -> dict:
    """
    [Rule] Summarize existing table info (for LLM)
    
    Args:
        ontology_context: Current ontology context
        processed_files_data: Column info of processed files (optional)
    
    Returns:
        Table summary dictionary
    """
    tables = {}
    
    # file_tags에서 데이터 파일들만 추출
    for file_path, tag_info in ontology_context.get("file_tags", {}).items():
        if tag_info.get("type") == "transactional_data":
            table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_")
            
            # 컬럼 정보 (저장된 것이 있으면 사용)
            columns = tag_info.get("columns", [])
            
            # 또는 processed_files_data에서 가져오기
            if not columns and processed_files_data:
                columns = processed_files_data.get(file_path, {}).get("columns", [])
            
            tables[table_name] = {
                "file_path": file_path,
                "type": tag_info.get("type"),
                "columns": columns
            }
    
    return tables


def _infer_relationships_with_llm(
    current_table_name: str,
    current_cols: List[str],
    ontology_context: dict,
    current_metadata: dict
) -> dict:
    """
    [Rule 전처리 + LLM 판단] 테이블 간 관계 추론
    
    Args:
        current_table_name: 현재 테이블 이름
        current_cols: 현재 테이블 컬럼 리스트
        ontology_context: 온톨로지 컨텍스트
        current_metadata: 현재 파일의 raw_metadata (카디널리티 분석용)
    
    Returns:
        {relationships: [...], hierarchy: [...], reasoning: "..."}
    """
    # 전역 캐시 및 llm_client 사용
    
    # === 1단계: Rule Prepares ===
    
    # 파일명 힌트 (Rule + LLM)
    filename_hints = _extract_filename_hints(current_table_name)
    
    # 기존 테이블 요약
    existing_tables = _summarize_existing_tables(ontology_context)
    
    # FK 후보 찾기 (Rule)
    fk_candidates = _find_common_columns(current_cols, existing_tables)
    
    # 카디널리티 분석 (현재는 기본 통계만)
    cardinality_hints = {}
    column_details = current_metadata.get("column_details", [])
    
    for col_info in column_details:
        col_name = col_info.get('column_name')
        samples = col_info.get('samples', [])
        
        if samples:
            unique_count = len(set(samples))
            total_count = len(samples)
            ratio = unique_count / total_count if total_count > 0 else 0
            
            cardinality_hints[col_name] = {
                "uniqueness_ratio": round(ratio, 2),
                "pattern": "UNIQUE" if ratio > 0.95 else "REPEATED"
            }
    
    # === 2단계: LLM Decides ===
    
    # 컨텍스트 구성
    llm_context = {
        "current_table": current_table_name,
        "current_cols": current_cols,
        "filename_hints": filename_hints,
        "fk_candidates": fk_candidates,
        "cardinality": cardinality_hints,
        "existing_tables": existing_tables,
        "definitions": ontology_context.get("definitions", {})
    }
    
    # 캐시 확인
    cached = llm_cache.get("relationship_inference", llm_context)
    if cached:
        print(f"✅ [Cache Hit] 관계 추론 캐시 사용")
        return cached
    
    # LLM 프롬프트
    prompt = f"""
You are a Database Schema Architect for Medical Data Integration.

I have pre-processed data using rules. Infer table relationships.

[PRE-PROCESSED INFORMATION]

1. NEW TABLE:
Name: {current_table_name}
Columns: {current_cols}

2. FILENAME HINTS (Parsed by Rule + LLM):
{json.dumps(filename_hints, indent=2)}

3. FK CANDIDATES (Found by Rules - Common Columns):
{json.dumps(fk_candidates, indent=2)}

4. CARDINALITY (Calculated by Rules):
{json.dumps(cardinality_hints, indent=2)}

5. EXISTING TABLES:
{json.dumps(existing_tables, indent=2)}

6. ONTOLOGY DEFINITIONS (Medical Terms):
Available terms: {len(llm_context['definitions'])} definitions
Example: caseid, subjectid, alb, wbc, etc.

[YOUR TASK]

1. **Validate FK Candidates**:
   - Check if common columns are truly Foreign Keys
   - Use CARDINALITY: if REPEATED → likely FK
   - Use FILENAME: if base_names related → likely FK

2. **Determine Relationship Type**:
   - 1:1, 1:N, N:1, or M:N based on cardinality

3. **Infer Hierarchy**:
   - Which entity is parent? (more abstract)
   - Which is child? (more specific)
   - Use domain knowledge

[OUTPUT FORMAT - JSON]
{{
  "relationships": [
    {{
      "source_table": "{current_table_name}",
      "target_table": "existing_table_name",
      "source_column": "column_name",
      "target_column": "column_name",
      "relation_type": "N:1",
      "confidence": 0.95,
      "description": "Brief explanation",
      "llm_inferred": true
    }}
  ],
  "hierarchy": [
    {{
      "level": 1,
      "entity_name": "Patient",
      "anchor_column": "subjectid",
      "mapping_table": null,
      "confidence": 0.9
    }}
  ],
  "reasoning": "Overall explanation"
}}

If no relationships found, return empty lists.
Be conservative: confidence < 0.8 if unsure.
"""
    
    try:
        result = llm_client.ask_json(prompt)
        
        # 캐시 저장
        llm_cache.set("relationship_inference", llm_context, result)
        
        # Confidence 검증
        rels = result.get("relationships", [])
        low_conf_rels = [r for r in rels if r.get("confidence", 0) < 0.8]
        
        if low_conf_rels:
            print(f"⚠️  [Relationship] Low confidence for {len(low_conf_rels)} relationships")
        
        return result
        
    except Exception as e:
        print(f"❌ [Relationship Inference] LLM Error: {e}")
        return {
            "relationships": [],
            "hierarchy": [],
            "reasoning": f"Error: {str(e)}",
            "error": True
        }


def _summarize_existing_tables(ontology_context: dict, processed_files_data: dict = None) -> dict:
    """
    [Rule] Summarize existing table info (for LLM)
    
    Args:
        ontology_context: Current ontology context
        processed_files_data: Column info of processed files (optional)
    
    Returns:
        Table summary dictionary
    """
    tables = {}
    
    # file_tags에서 데이터 파일들만 추출
    for file_path, tag_info in ontology_context.get("file_tags", {}).items():
        if tag_info.get("type") == "transactional_data":
            table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_")
            
            # 컬럼 정보 (저장된 것 사용)
            columns = tag_info.get("columns", [])
            
            tables[table_name] = {
                "file_path": file_path,
                "type": tag_info.get("type"),
                "columns": columns
            }
    
    return tables


# ============================================================================
# LLM 기반 Human Review 판단 (유연한 조건)
# ============================================================================

def _should_request_human_review(
    file_path: str,
    issue_type: str,
    context: Dict[str, Any],
    rule_based_confidence: float = 1.0
) -> Dict[str, Any]:
    """
    [Helper] Human Review가 필요한지 판단 (Rule + LLM Hybrid)
    
    Args:
        file_path: 처리 중인 파일 경로
        issue_type: 이슈 유형 ("metadata_classification", "anchor_detection", "anchor_conflict", etc.)
        context: 판단에 필요한 컨텍스트 정보
        rule_based_confidence: Rule-based 분석에서 얻은 confidence (0~1)
    
    Returns:
        {
            "needs_review": bool,
            "reason": str,
            "confidence": float,
            "suggested_question": str (optional)
        }
    """
    filename = os.path.basename(file_path)
    
    # === 1단계: Rule-based 판단 (빠르고 저렴) ===
    threshold = _get_threshold_for_issue(issue_type)
    
    rule_decision = {
        "needs_review": rule_based_confidence < threshold,
        "reason": f"Confidence {rule_based_confidence:.1%} < Threshold {threshold:.1%}",
        "confidence": rule_based_confidence
    }
    
    # LLM 판단이 비활성화되어 있으면 Rule 결과만 반환
    if not HumanReviewConfig.USE_LLM_FOR_REVIEW_DECISION:
        print(f"   [Rule-only] {issue_type}: needs_review={rule_decision['needs_review']}")
        return rule_decision
    
    # === 2단계: LLM 기반 판단 (더 유연) ===
    # Rule에서 이미 "확실히 필요"하다고 판단한 경우 LLM 호출 생략 (비용 절감)
    if rule_based_confidence < 0.5:
        print(f"   [Rule] Low confidence ({rule_based_confidence:.1%}), skipping LLM check")
        return rule_decision
    
    # LLM에게 판단 요청
    llm_decision = _ask_llm_for_review_decision(
        filename=filename,
        issue_type=issue_type,
        context=context,
        rule_confidence=rule_based_confidence
    )
    
    # === 3단계: Rule과 LLM 결과 종합 ===
    # 둘 중 하나라도 "필요하다"고 하면 Human Review 요청
    final_needs_review = rule_decision["needs_review"] or llm_decision.get("needs_review", False)
    
    combined_reason = []
    if rule_decision["needs_review"]:
        combined_reason.append(f"Rule: {rule_decision['reason']}")
    if llm_decision.get("needs_review"):
        combined_reason.append(f"LLM: {llm_decision.get('reason', 'LLM recommended review')}")
    
    result = {
        "needs_review": final_needs_review,
        "reason": " | ".join(combined_reason) if combined_reason else "No issues detected",
        "confidence": rule_based_confidence,
        "llm_opinion": llm_decision.get("reason", "N/A")
    }
    
    print(f"   [Hybrid] {issue_type}: needs_review={final_needs_review}")
    print(f"            Rule={rule_decision['needs_review']}, LLM={llm_decision.get('needs_review', 'N/A')}")
    
    return result


def _get_threshold_for_issue(issue_type: str) -> float:
    """이슈 유형별 Threshold 반환"""
    thresholds = {
        "metadata_classification": HumanReviewConfig.METADATA_CONFIDENCE_THRESHOLD,
        "anchor_detection": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
        "anchor_conflict": HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD,
        "general": 0.7
    }
    return thresholds.get(issue_type, 0.75)


def _ask_llm_for_review_decision(
    filename: str,
    issue_type: str,
    context: Dict[str, Any],
    rule_confidence: float
) -> Dict[str, Any]:
    """LLM에게 Human Review 필요 여부 판단 요청"""
    
    prompt = f"""
    You are an AI assistant helping with medical data processing.
    Based on the following situation, decide if human intervention is needed.

    [Situation]
    - File: {filename}
    - Issue Type: {issue_type}
    - Rule-based Confidence: {rule_confidence:.1%}
    - Context: {json.dumps(context, ensure_ascii=False, default=str)[:500]}...

    [Issue Type Descriptions]
    - metadata_classification: Determining if file is metadata (dictionary) or actual data
    - anchor_detection: Finding the primary identifier column (e.g., patient_id)
    - anchor_conflict: Mismatch between local and global anchor columns

    [Decision Criteria]
    Return "needs_review": true if:
    1. The context shows ambiguous or conflicting information
    2. Critical decisions might affect data integrity
    3. Domain expertise is clearly needed (medical terminology, etc.)
    4. Multiple valid interpretations exist

    Return "needs_review": false if:
    1. The situation is straightforward despite low confidence
    2. Safe defaults can be applied
    3. The issue can be auto-corrected later

    Respond with JSON only:
    {{
        "needs_review": true or false,
        "reason": "Brief explanation in Korean (한국어)"
    }}
    """
    
    try:
        result = llm_client.ask_json(prompt)
        return {
            "needs_review": result.get("needs_review", False),
            "reason": result.get("reason", "LLM did not provide reason")
        }
    except Exception as e:
        print(f"   ⚠️ [LLM Review Decision] Error: {e}")
        # LLM 실패 시 Rule 결과에 의존
        return {"needs_review": False, "reason": f"LLM error: {str(e)}"}


def _parse_human_feedback_to_column(
    feedback: str,
    available_columns: List[str],
    master_anchor: Optional[str],
    file_path: str
) -> Dict[str, Any]:
    """
    [Helper] 사용자 피드백을 파싱하여 실제 컬럼명 추출
    
    입력 유형:
    1. 실제 컬럼명 (예: "caseid", "subjectid") → 그대로 반환
    2. "skip" → 스킵 액션 반환
    3. 설명 (예: "subjectID는 환자ID이고 caseID는 수술 ID야") → LLM으로 해석
    
    Returns:
        {"action": "use_column", "column_name": "caseid", "reasoning": "..."}
        {"action": "skip", "reasoning": "사용자가 스킵 요청"}
    """
    feedback_lower = feedback.strip().lower()
    
    # Case 1: 스킵 요청
    if feedback_lower in ["skip", "스킵", "건너뛰기", "pass"]:
        return {"action": "skip", "reasoning": "사용자가 스킵 요청"}
    
    # Case 2: 실제 컬럼명과 정확히 일치
    columns_lower = [c.lower() for c in available_columns]
    if feedback_lower in columns_lower:
        # 원래 대소문자 유지
        idx = columns_lower.index(feedback_lower)
        return {
            "action": "use_column",
            "column_name": available_columns[idx],
            "reasoning": "User specified column name directly"
        }
    
    # Case 3: Description or complex input → Interpret with LLM
    print(f"   → User input is not a column name. Interpreting with LLM...")
    
    from src.utils.llm_client import get_llm_client
    
    try:
        llm_client = get_llm_client()
        
        prompt = f"""The user has provided feedback about the identifier (Anchor) column of a data file.
Interpret this feedback and determine which column should be used.

[File Information]
- Filename: {os.path.basename(file_path)}
- Available Columns: {available_columns}
- Project Master Anchor: {master_anchor or 'None'}

[User Feedback]
"{feedback}"

[Analysis Request]
1. Identify which column should be used as the Anchor based on the user's feedback.
2. If the feedback describes relationships (e.g., "A is patient ID and B is surgery ID"),
   select the most appropriate column from the file's columns.
3. Prioritize columns that can link to the Master Anchor.

[Response Format - JSON only]
{{
    "column_name": "Selected column name (from available columns list)",
    "reasoning": "Reason for selection",
    "user_intent": "Summary of user's intent"
}}"""
        
        result = llm_client.ask_json(prompt)
        
        if "error" not in result and result.get("column_name"):
            selected = result["column_name"]
            
            # 선택된 컬럼이 실제로 존재하는지 확인
            if selected.lower() in columns_lower:
                idx = columns_lower.index(selected.lower())
                return {
                    "action": "use_column",
                    "column_name": available_columns[idx],
                    "reasoning": result.get("reasoning", "LLM interpretation result"),
                    "user_intent": result.get("user_intent", feedback)
                }
        
        # LLM failed to return valid column → Use first column
        print(f"   ⚠️ LLM failed to return valid column. Using first column: {available_columns[0]}")
        return {
            "action": "use_column",
            "column_name": available_columns[0] if available_columns else "unknown",
            "reasoning": f"LLM interpretation failed. Using default. User input: {feedback}"
        }
        
    except Exception as e:
        print(f"   ⚠️ LLM call failed: {e}")
        # On LLM failure, use first column
        return {
            "action": "use_column",
            "column_name": available_columns[0] if available_columns else feedback.strip(),
            "reasoning": f"LLM failed. Using default. Error: {str(e)}"
        }


def _generate_natural_human_question(
    file_path: str,
    context: Dict[str, Any],
    issue_type: str = "general_uncertainty"
) -> str:
    """
    [Helper] Generate natural questions for users using LLM (Human-in-the-Loop)
    
    Returns:
        Question string to show to the user (English)
    """
    from src.utils.llm_client import get_llm_client
    
    filename = os.path.basename(file_path)
    
    # Extract context
    columns = context.get("columns", [])
    candidates = context.get("candidates", "None")
    reasoning = context.get("reasoning", "No information")
    ai_msg = context.get("message", "")
    global_master = context.get("master_anchor", "None")
    
    # Format column list
    column_list = columns[:10] if len(columns) > 10 else columns
    columns_str = ", ".join(column_list)
    if len(columns) > 10:
        columns_str += f" ... (and {len(columns) - 10} more)"
    
    # === Fallback messages (used when LLM fails) ===
    fallback_messages = {
        "anchor_conflict": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔗 Anchor Column Mismatch - Confirmation Required                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     The project's Master Anchor is '{global_master}'.
│     However, this file appears to use '{candidates}' as the identifier.
│  
│  💡 AI Analysis:
│     {reasoning[:200]}{'...' if len(str(reasoning)) > 200 else ''}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 Action Required:
│     1. Is '{candidates}' the same as '{global_master}'? (e.g., both are Patient ID)
│     2. If not, which column corresponds to '{global_master}'?
│     3. If none exists, type 'skip'.
└─────────────────────────────────────────────────────────────────────────────┘
""",
        "anchor_uncertain": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  🔍 Anchor Column Identification Required                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     AI could not identify a Patient/Case identifier (Anchor) column.
│     Candidate: '{candidates}' (low confidence)
│  
│  💡 AI Analysis:
│     {reasoning[:200]}{'...' if len(str(reasoning)) > 200 else ''}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 Action Required:
│     Please enter the column name that serves as the unique identifier
│     (Patient ID, Subject ID, Case ID, etc.).
│     Type 'skip' if none exists.
└─────────────────────────────────────────────────────────────────────────────┘
""",
        "metadata_uncertain": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  📖 File Type Confirmation Required                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     AI cannot determine if this file is 'metadata (description/dictionary)'
│     or 'actual data'.
│  
│  💡 AI Analysis:
│     {reasoning[:200]}{'...' if len(str(reasoning)) > 200 else ''}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 Action Required:
│     - If metadata (column descriptions, code definitions): type 'metadata'
│     - If actual patient/measurement data: type 'data'
└─────────────────────────────────────────────────────────────────────────────┘
""",
        "general_uncertainty": f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚠️ Confirmation Required                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  📁 File: {filename}
│  
│  ❓ Issue:
│     {ai_msg or 'Uncertainty occurred during data processing.'}
│  
│  📋 Columns in file:
│     {columns_str}
│  
│  🎯 User confirmation is required.
└─────────────────────────────────────────────────────────────────────────────┘
"""
    }
    
    # === LLM prompt ===
    task_descriptions = {
        "anchor_conflict": f"""
In the current file '{filename}', the column '{candidates}' is presumed to be the identifier.
However, the project's Master Anchor is '{global_master}'.
Ask the user if these two columns have the same meaning, or if a different column should be selected.
""",
        "anchor_uncertain": f"""
No clear identifier column was found in the current file '{filename}'.
AI's candidate is '{candidates}' but with low confidence.
Ask the user which column is the patient/case identifier.
""",
        "metadata_uncertain": f"""
It is unclear whether the current file '{filename}' is metadata (description file) or actual data.
Ask the user to confirm the type of file.
""",
        "general_uncertainty": f"Issue during data processing: {ai_msg}"
    }
    
    task_desc = task_descriptions.get(issue_type, task_descriptions["general_uncertainty"])
    
    prompt = f"""You are an AI assistant helping a medical data engineer.
An uncertainty occurred during data processing, and you need to ask the user a question.

[Context]
- Filename: {filename}
- Columns in file: {columns_str}
- AI Analysis: {reasoning}
- Additional info: {ai_msg}

[Issue to Resolve]
{task_desc}

[Question Guidelines]
1. Write in clear, professional English.
2. Be polite and specific in your question.
3. Briefly explain why you're asking this question.
4. Provide options or examples for the user to choose from.
5. Reference specific column names from the column list.
6. Keep it within 3-5 sentences.
7. Do not use code or JSON format.

Question:"""
    
    try:
        llm_client = get_llm_client()
        llm_response = llm_client.ask_text(prompt)
        
        # LLM 응답이 너무 짧으면 fallback 사용
        if len(llm_response.strip()) < 20:
            return fallback_messages.get(issue_type, fallback_messages["general_uncertainty"])
        
        # LLM 응답 포맷팅
        formatted_response = f"""
┌─────────────────────────────────────────────────────────────────────────────┐
│  📁 파일: {filename}
│  📋 컬럼: {columns_str}
├─────────────────────────────────────────────────────────────────────────────┤

{llm_response.strip()}

└─────────────────────────────────────────────────────────────────────────────┘
"""
        return formatted_response
        
    except Exception as e:
        print(f"⚠️ [Question Gen] LLM 호출 실패: {e}")
        return fallback_messages.get(issue_type, fallback_messages["general_uncertainty"])



def ontology_builder_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node] 온톨로지 구축 - Rule Prepares, LLM Decides
    
    파일이 메타데이터인지 판단하고, 메타데이터면 파싱하여 온톨로지에 추가
    """
    print("\n" + "="*80)
    print("📚 [ONTOLOGY BUILDER NODE] 시작")
    print("="*80)
    
    file_path = state["file_path"]
    metadata = state["raw_metadata"]
    
    # 기존 온톨로지 가져오기 (State에서 또는 디스크에서)
    ontology = state.get("ontology_context")
    
    # 첫 파일이거나 ontology가 비어있으면 디스크에서 로드
    if not ontology or not ontology.get("definitions"):
        print(f"   - 온톨로지 로드 시도...")
        ontology = ontology_manager.load()
    
    # 여전히 없으면 빈 구조
    if not ontology:
        ontology = {
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {}
        }
    
    # === Step 1: Rule Prepares (데이터 전처리) ===
    print("\n🔧 [Rule] 데이터 전처리 중...")
    context = _build_metadata_detection_context(file_path, metadata)
    
    print(f"   - 파일명 파싱: {context.get('name_parts')}")
    print(f"   - Base Name: {context.get('base_name')}")
    print(f"   - 컬럼 수: {context.get('num_columns')}개")
    print(f"   - 컨텍스트 크기: {context.get('context_size_bytes', 0)} bytes")
    
    # === Step 2: LLM Decides (메타데이터 여부 판단) ===
    print("\n🧠 [LLM] 메타데이터 여부 판단 중...")
    
    meta_result = _ask_llm_is_metadata(context)
    
    confidence = meta_result.get("confidence", 0.0)
    is_metadata = meta_result.get("is_metadata", False)
    
    print(f"   - 판단: {'메타데이터' if is_metadata else '일반 데이터'}")
    print(f"   - 확신도: {confidence:.2%}")
    print(f"   - Reasoning: {meta_result.get('reasoning', 'N/A')[:80]}...")
    
    # === Step 3: Confidence Check (유연한 판단) ===
    review_decision = _should_request_human_review(
        file_path=file_path,
        issue_type="metadata_classification",
        context={
            "is_metadata": is_metadata,
            "reasoning": meta_result.get("reasoning"),
            "columns": context.get("columns", []),
            "indicators": meta_result.get("indicators", {})
        },
        rule_based_confidence=confidence
    )
    
    if review_decision["needs_review"]:
        print(f"\n⚠️  [Low Confidence] Human Review 요청")
        print(f"   Reason: {review_decision['reason']}")
        
        # 구체적 질문 생성 (LLM)
        specific_question = _generate_natural_human_question(
            file_path=file_path,
            context={
                "reasoning": meta_result.get("reasoning"),
                "message": f"Confidence {confidence:.1%}",
                "columns": context.get("columns", [])
            },
            issue_type="metadata_uncertain"
        )
        
        print("="*80)
        
        return {
            "needs_human_review": True,
            "human_question": specific_question,
            "ontology_context": ontology,  # 현재 상태 유지
            "logs": [f"⚠️ [Ontology] 메타데이터 판단 불확실 ({confidence:.2%}). {review_decision['reason']}"]
        }
    
    # === Step 4: Branching (확신도 높음) ===
    
    # [Branch A] 메타데이터 파일
    if is_metadata:
        print(f"\n📖 [Metadata] 메타데이터 파일로 확정")
        
        # 파일 태그 저장
        ontology["file_tags"][file_path] = {
            "type": "metadata",
            "role": "dictionary",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat()
        }
        
        # 내용 파싱 (Rule)
        print(f"   - 메타데이터 파싱 중...")
        new_definitions = _parse_metadata_content(file_path)
        ontology["definitions"].update(new_definitions)
        
        print(f"   - 용어 {len(new_definitions)}개 추가")
        print(f"   - 총 용어: {len(ontology['definitions'])}개")
        
        # 온톨로지 저장 (영구 보존)
        print(f"   - 온톨로지 저장 중...")
        ontology_manager.save(ontology)
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": True,  # 중요! 메타데이터는 인덱싱 스킵
            "logs": [f"📚 [Ontology] 메타데이터 등록: {len(new_definitions)}개 용어 추가 (저장 완료)"]
        }
    
    # [Branch B] 일반 데이터 파일
    else:
        print(f"\n📊 [Data] 일반 데이터 파일로 확정")
        
        # 컬럼 정보 저장 (관계 추론에 필요)
        columns = metadata.get("columns", [])
        
        ontology["file_tags"][file_path] = {
            "type": "transactional_data",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat(),
            "columns": columns  # [NEW] 컬럼 저장
        }
        
        # Note: Column Metadata는 index_data_node에서 finalized_schema 확정 후 저장됨
        
        # === Phase 2: 관계 추론 (기존 테이블이 있을 때만) ===
        existing_data_files = [
            fp for fp, tag in ontology.get("file_tags", {}).items()
            if tag.get("type") == "transactional_data" and fp != file_path
        ]
        
        if existing_data_files:
            print(f"\n🔗 [Relationship] 관계 추론 시작...")
            print(f"   - 기존 데이터 파일: {len(existing_data_files)}개")
            
            # 관계 추론 (LLM)
            table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_")
            
            relationship_result = _infer_relationships_with_llm(
                current_table_name=table_name,
                current_cols=columns,
                ontology_context=ontology,
                current_metadata=metadata
            )
            
            # 관계 추가
            new_relationships = relationship_result.get("relationships", [])
            if new_relationships:
                print(f"   - 관계 {len(new_relationships)}개 발견")
                
                # 기존 관계와 병합
                existing_rels = ontology.get("relationships", [])
                
                # 중복 체크
                existing_keys = {
                    (r["source_table"], r["target_table"], r["source_column"], r["target_column"])
                    for r in existing_rels
                }
                
                for new_rel in new_relationships:
                    key = (new_rel["source_table"], new_rel["target_table"], 
                           new_rel["source_column"], new_rel["target_column"])
                    if key not in existing_keys:
                        ontology["relationships"].append(new_rel)
                        print(f"      • {new_rel['source_table']}.{new_rel['source_column']} "
                              f"→ {new_rel['target_table']}.{new_rel['target_column']} "
                              f"({new_rel['relation_type']}, conf: {new_rel.get('confidence', 0):.2%})")
            
            # 계층 업데이트 (중복 제거 강화)
            new_hierarchy = relationship_result.get("hierarchy", [])
            if new_hierarchy:
                print(f"   - 계층 정보 업데이트")
                
                # 기존 계층
                existing_hier = ontology.get("hierarchy", [])
                
                # 중복 제거 전략: (level, anchor_column) 조합으로 판단
                merged_hierarchy = {}  # key: (level, anchor), value: hierarchy_dict
                
                # 기존 계층 먼저 추가
                for h in existing_hier:
                    key = (h.get("level"), h.get("anchor_column"))
                    merged_hierarchy[key] = h
                
                # 새 계층 병합 (confidence 높은 것 우선)
                for new_h in new_hierarchy:
                    key = (new_h.get("level"), new_h.get("anchor_column"))
                    
                    if key not in merged_hierarchy:
                        # 새로운 (level, anchor) 조합
                        merged_hierarchy[key] = new_h
                        print(f"      • L{new_h['level']}: {new_h['entity_name']} ({new_h['anchor_column']}) [NEW]")
                    else:
                        # 이미 있는 조합 - confidence 비교
                        existing_conf = merged_hierarchy[key].get("confidence", 0)
                        new_conf = new_h.get("confidence", 0)
                        
                        if new_conf > existing_conf:
                            merged_hierarchy[key] = new_h
                            print(f"      • L{new_h['level']}: {new_h['entity_name']} ({new_h['anchor_column']}) [UPDATED, conf: {new_conf:.2%}]")
                        else:
                            print(f"      • L{new_h['level']}: (중복 스킵, 기존 confidence {existing_conf:.2%} 유지)")
                
                # 리스트로 변환 후 레벨 정렬
                ontology["hierarchy"] = sorted(merged_hierarchy.values(), key=lambda x: x.get("level", 99))
        else:
            print(f"\n   - 기존 데이터 파일 없음. 관계 추론 스킵.")
        
        # 온톨로지 저장
        print(f"   - 온톨로지 저장 중...")
        ontology_manager.save(ontology)
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": False,  # 일반 데이터는 인덱싱 계속
            "logs": ["🔍 [Ontology] 일반 데이터 확인. 관계 추론 완료."]
        }