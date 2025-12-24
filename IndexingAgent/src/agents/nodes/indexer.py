# src/agents/nodes/indexer.py
"""
Indexer Node - PostgreSQL 인덱싱
"""

import os
import pandas as pd
from typing import Dict, Any

from src.agents.state import AgentState
from src.agents.nodes.common import ontology_manager
from src.agents.helpers.llm_helpers import analyze_tracks_with_llm
from src.utils.dataset_detector import detect_dataset_from_path
from src.utils.naming import generate_table_name, generate_table_id, generate_schema_hash
from src.config import ProcessingConfig


def index_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 4 - Phase 3] Build PostgreSQL DB (ontology-based)
    """
    from src.database.connection import get_db_manager
    from src.database.schema_generator import SchemaGenerator
    from src.database.version_manager import get_version_manager
    
    print("\n" + "="*80)
    print("💾 [INDEXER NODE] Starting - PostgreSQL DB construction")
    print("="*80)
    
    schema = state.get("finalized_schema", [])
    file_path = state["file_path"]
    file_type = state.get("file_type", "tabular")
    metadata = state.get("raw_metadata", {})
    ontology = state.get("ontology_context", {})
    
    # === Dataset-First: 데이터셋 ID 및 테이블명 생성 ===
    dataset_id = state.get("current_dataset_id")
    if not dataset_id:
        dataset_id = detect_dataset_from_path(file_path)
        if not dataset_id:
            dataset_id = "default_dataset"
        print(f"📁 [Dataset] Auto-detected: {dataset_id}")
    
    # Signal 파일 (.vital) 특별 처리
    if file_type == "signal" and metadata.get("is_vital_file", False):
        return _handle_vital_file_indexing(state, file_path, metadata, ontology)
    
    table_name = generate_table_name(file_path, dataset_id)
    table_id = generate_table_id(dataset_id, table_name)
    
    print(f"   📋 Dataset: {dataset_id}")
    print(f"   📋 Table: {table_name}")
    
    db_manager = get_db_manager()
    
    try:
        print(f"\n📥 [Data] Loading data...")
        
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"   - File size: {file_size_mb:.1f}MB")
        
        total_rows = 0
        engine = db_manager.get_sqlalchemy_engine()
        
        # Test mode row limit
        test_limit = os.environ.get("TEST_ROW_LIMIT")
        limit_kwargs = {}
        if test_limit:
            limit_rows = int(test_limit)
            limit_kwargs = {"nrows": limit_rows}
            print(f"⚠️ [TEST MODE] Processing top {limit_rows} rows only")

        if file_size_mb > ProcessingConfig.LARGE_FILE_THRESHOLD_MB:
            print(f"   - Large file - Chunk Processing ({ProcessingConfig.CHUNK_SIZE_ROWS} rows/chunk)")
            
            for i, chunk in enumerate(pd.read_csv(file_path, chunksize=ProcessingConfig.CHUNK_SIZE_ROWS, **limit_kwargs)):
                chunk.to_sql(
                    table_name, 
                    engine, 
                    if_exists='append' if i > 0 else 'replace',
                    index=False,
                    method='multi'
                )
                total_rows += len(chunk)
                print(f"      • Chunk {i+1}: {len(chunk):,} rows (cumulative: {total_rows:,})")
        else:
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
        
        # === Create indices ===
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
                idx_name = idx_ddl.split('"')[1] if '"' in idx_ddl else idx_ddl.split()[2]
                indices_created.append(idx_name)
            except Exception as e:
                print(f"⚠️  Index creation failed: {e}")
        
        conn.commit()
        
        if indices_created:
            print(f"   - {len(indices_created)} indices created: {', '.join(indices_created)}")
        
        # === Verification ===
        print(f"\n✅ [Verify] Verifying...")
        
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        actual_rows = cursor.fetchone()[0]
        
        if actual_rows == total_rows:
            print(f"   - Row count matches: {actual_rows:,} rows ✅")
        else:
            print(f"   ⚠️ Row count mismatch: expected {total_rows:,}, actual {actual_rows:,}")
        
        # === Save Column Metadata ===
        if schema:
            print(f"\n📋 [Column Metadata] Saving...")
            
            if "column_metadata" not in ontology:
                ontology["column_metadata"] = {}
            
            ontology["dataset_id"] = dataset_id
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
                    "semantic_type": col_schema.get("semantic_type"),
                    "column_type": col_schema.get("column_type"),
                    "unit": col_schema.get("unit"),
                    "typical_range": col_schema.get("typical_range"),
                    "is_pii": col_schema.get("is_pii", False),
                    "confidence": col_schema.get("confidence", 0),
                    # NEW: value_mappings & hierarchy fields
                    "value_mappings": col_schema.get("value_mappings"),
                    "parent_column": col_schema.get("parent_column"),
                    "cardinality": col_schema.get("cardinality"),
                    "hierarchy_type": col_schema.get("hierarchy_type"),
                    # NEW: analysis_context (user_feedback 포함, 중복 저장 없음)
                    "analysis_context": col_schema.get("analysis_context")
                }
            
            print(f"   - {len(schema)} column metadata generated")
            
            ontology_manager.save(ontology, dataset_id=dataset_id)
            print(f"   - Neo4j save complete (dataset: {dataset_id})")
        
        # === Version Management ===
        print(f"\n📝 [Version] Recording indexing history...")
        try:
            version_manager = get_version_manager(db_manager)
            schema_hash = generate_schema_hash(schema)
            
            version_info = version_manager.record_indexing(
                table_id=table_id,
                dataset_id=dataset_id,
                table_name=table_name,
                original_filename=os.path.basename(file_path),
                original_filepath=file_path,
                row_count=total_rows,
                column_count=len(schema),
                schema_hash=schema_hash
            )
            print(f"   - Version: v{version_info['version']}")
            if version_info.get('is_schema_changed'):
                print(f"   ⚠️ Schema changed from previous version!")
        except Exception as ve:
            print(f"   ⚠️ Version recording failed (non-critical): {ve}")
        
        print("="*80)
        
        return {
            "current_dataset_id": dataset_id,
            "current_table_name": table_name,
            "ontology_context": ontology,
            "logs": [
                f"💾 [Indexer] {table_name} created ({total_rows:,} rows)",
                f"📁 [Indexer] Dataset: {dataset_id}",
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


def _handle_vital_file_indexing(
    state: AgentState, 
    file_path: str, 
    metadata: Dict, 
    ontology: Dict
) -> Dict[str, Any]:
    """
    [옵션 B] Signal 파일 인덱싱 - 정규화된 테이블 구조
    """
    from src.database.connection import get_db_manager
    
    anchor_info = metadata.get("anchor_info", {})
    id_column = anchor_info.get("target_column", "file_id")
    id_value = anchor_info.get("id_value") or anchor_info.get("caseid_value")
    confidence = anchor_info.get("confidence", 0.5)
    needs_confirmation = anchor_info.get("needs_human_confirmation", False)
    
    tracks = metadata.get("columns", [])
    column_details = metadata.get("column_details", {})
    
    print(f"\n📡 [Signal File] Processing (Normalized Tables)...")
    print(f"   - ID: {id_column}={id_value}")
    print(f"   - Confidence: {confidence:.0%}")
    print(f"   - Tracks: {len(tracks)}")
    
    if id_value is None:
        print(f"   ⚠️ ID not found. Skipping indexing.")
        return {
            "logs": [f"⚠️ [Indexer] Signal file skipped: ID not found"],
            "skip_indexing": True,
            "needs_human_review": True,
            "human_question": f"Cannot determine ID for signal file '{os.path.basename(file_path)}'."
        }
    
    if needs_confirmation:
        print(f"   ⚠️ Low confidence ({confidence:.0%}). ID may need verification.")
    
    try:
        db_manager = get_db_manager()
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        # Create tables
        create_tables_sql = """
        CREATE TABLE IF NOT EXISTS signal_files (
            file_id SERIAL PRIMARY KEY,
            id_column VARCHAR(50) NOT NULL,
            id_value VARCHAR(100) NOT NULL,
            file_path TEXT NOT NULL,
            file_name VARCHAR(255),
            file_format VARCHAR(20),
            file_size_mb FLOAT,
            duration_seconds FLOAT,
            track_count INTEGER,
            confidence FLOAT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(file_path)
        );
        
        CREATE INDEX IF NOT EXISTS idx_signal_files_id_value ON signal_files(id_value);
        
        CREATE TABLE IF NOT EXISTS signal_tracks (
            track_id SERIAL PRIMARY KEY,
            file_id INTEGER REFERENCES signal_files(file_id) ON DELETE CASCADE,
            track_name VARCHAR(255) NOT NULL,
            sample_rate FLOAT,
            unit VARCHAR(50),
            min_value FLOAT,
            max_value FLOAT,
            track_type VARCHAR(50),
            inferred_name VARCHAR(255),
            description TEXT,
            clinical_category VARCHAR(100),
            UNIQUE(file_id, track_name)
        );
        
        CREATE INDEX IF NOT EXISTS idx_signal_tracks_file_id ON signal_tracks(file_id);
        """
        
        for stmt in create_tables_sql.strip().split(';'):
            if stmt.strip():
                try:
                    cursor.execute(stmt)
                except Exception:
                    pass
        
        conn.commit()
        print(f"   ✅ Tables ready")
        
        # Insert signal_files record
        ext = os.path.splitext(file_path)[1].lower()
        format_map = {".vital": "vitaldb", ".edf": "edf", ".bdf": "bdf"}
        file_format = format_map.get(ext, "unknown")
        
        insert_file_sql = """
        INSERT INTO signal_files (id_column, id_value, file_path, file_name, file_format, 
                                  file_size_mb, duration_seconds, track_count, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (file_path) 
        DO UPDATE SET 
            id_column = EXCLUDED.id_column,
            id_value = EXCLUDED.id_value,
            confidence = EXCLUDED.confidence
        RETURNING file_id;
        """
        
        cursor.execute(insert_file_sql, (
            id_column,
            str(id_value),
            file_path,
            os.path.basename(file_path),
            file_format,
            metadata.get("file_size_mb", 0),
            metadata.get("duration", 0),
            len(tracks),
            confidence
        ))
        
        file_id = cursor.fetchone()[0]
        conn.commit()
        print(f"   ✅ File registered: file_id={file_id}")
        
        # LLM track analysis
        track_analyses = analyze_tracks_with_llm(tracks, column_details)
        
        # Insert signal_tracks
        insert_track_sql = """
        INSERT INTO signal_tracks (file_id, track_name, sample_rate, unit, min_value, max_value,
                                   track_type, inferred_name, description, clinical_category)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (file_id, track_name) DO UPDATE SET 
            inferred_name = EXCLUDED.inferred_name,
            clinical_category = EXCLUDED.clinical_category;
        """
        
        tracks_inserted = 0
        for track_name in tracks:
            details = column_details.get(track_name, {})
            analysis = track_analyses.get(track_name, {})
            
            cursor.execute(insert_track_sql, (
                file_id,
                track_name,
                details.get("sample_rate"),
                details.get("unit"),
                details.get("min_val"),
                details.get("max_val"),
                details.get("column_type", "unknown"),
                analysis.get("inferred_name", track_name),
                analysis.get("description", ""),
                analysis.get("clinical_category", "unknown")
            ))
            tracks_inserted += 1
        
        conn.commit()
        print(f"   ✅ Tracks registered: {tracks_inserted}")
        
        # Update ontology
        if ontology:
            if "file_tags" not in ontology:
                ontology["file_tags"] = {}
            
            ontology["file_tags"][file_path] = {
                "type": "signal_data",
                "format": file_format,
                "file_id": file_id,
                "id_column": id_column,
                "id_value": id_value,
                "track_count": len(tracks),
                "confidence": confidence,
                "track_analyses": track_analyses
            }
            
            ontology_manager.save(ontology)
            print(f"   ✅ Ontology updated")
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "logs": [
                f"📡 [Indexer] Signal file registered: {id_column}={id_value}",
                f"💾 [Indexer] {tracks_inserted} tracks analyzed",
                "✅ [Done] Signal file indexing complete."
            ]
        }
        
    except Exception as e:
        import traceback
        print(f"\n❌ [Error] Vital file indexing failed: {str(e)}")
        traceback.print_exc()
        print("="*80)
        
        return {
            "logs": [f"❌ [Indexer] Vital file indexing failed: {str(e)}"],
            "error_message": str(e)
        }

