#!/usr/bin/env python3
"""
Pipeline Test: directory_catalog → file_catalog → schema_aggregation

test_full_pipeline_results.py의 입력값을 기반으로 
schema_aggregation까지 실행하고 생성되는 모든 데이터를 출력합니다.

실행 노드 (3-Node Rule-based Pipeline):
- [directory_catalog]: 디렉토리 구조 분석, 파일명 샘플 수집
- [file_catalog]: 파일/컬럼 메타데이터 추출, DB 저장
- [schema_aggregation]: 유니크 컬럼/파일 집계, LLM 배치 준비

출력 데이터:
1. Directory Catalog:
   - directory_catalog 테이블 데이터
   - catalog_dir_ids
   
2. File Catalog:
   - file_catalog 테이블 데이터
   - column_metadata 테이블 데이터
   - catalog_file_ids
   
3. Schema Aggregation:
   - unique_columns (유니크 컬럼 목록)
   - unique_files (유니크 파일 목록)
   - column_batches (컬럼 LLM 배치)
   - file_batches (파일 LLM 배치)
"""

import sys
import os
import json
from typing import Dict, Any, List
from datetime import datetime
from pathlib import Path

# 프로젝트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 데이터 경로 설정 (Open VitalDB만 테스트)
DATA_DIR = Path(__file__).parent / "data" / "raw" / "Open_VitalDB_1.0.0"


# =============================================================================
# Database Setup
# =============================================================================

def reset_database():
    """테스트 전 DB 초기화 (Catalog + Directory만)"""
    print("\n" + "="*80)
    print("🗑️  Resetting Database (Catalog + Directory tables only)...")
    print("="*80)
    
    from src.database import (
        CatalogSchemaManager,
        DirectorySchemaManager,
    )
    
    # 1. 삭제
    try:
        catalog_manager = CatalogSchemaManager()
        catalog_manager.drop_tables(confirm=True)
        print("✅ Catalog tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping catalog: {e}")
    
    try:
        directory_manager = DirectorySchemaManager()
        directory_manager.drop_tables(confirm=True)
        print("✅ Directory tables dropped")
    except Exception as e:
        print(f"⚠️  Error dropping directory: {e}")
    
    # 2. 생성
    try:
        directory_manager = DirectorySchemaManager()
        directory_manager.create_tables()
        print("✅ Directory tables created")
    except Exception as e:
        print(f"⚠️  Error creating directory: {e}")
    
    try:
        catalog_manager = CatalogSchemaManager()
        catalog_manager.create_tables()
        print("✅ Catalog tables created")
    except Exception as e:
        print(f"⚠️  Error creating catalog: {e}")


# =============================================================================
# Data File Discovery
# =============================================================================

def find_data_files() -> list:
    """Open VitalDB 데이터 파일 찾기 (CSV + Vital 파일)"""
    print(f"\n📂 Scanning: {DATA_DIR}")
    
    files = []
    
    if not DATA_DIR.exists():
        print(f"⚠️  Data directory not found: {DATA_DIR}")
        return files
    
    # CSV 파일 스캔
    for f in DATA_DIR.rglob("*.csv"):
        files.append(str(f))
        print(f"   Found: {f.name}")
    
    # Vital 파일 스캔 (생체신호 데이터) - 테스트용으로 3개만
    vital_files = list(DATA_DIR.rglob("*.vital"))[:3]
    for f in vital_files:
        files.append(str(f))
        print(f"   Found: {f.name} (signal)")
    
    print(f"\n📁 Total files found: {len(files)}")
    return files


# =============================================================================
# Pipeline Execution (to schema_aggregation)
# =============================================================================

def run_pipeline_to_schema_aggregation():
    """directory_catalog → file_catalog → schema_aggregation 실행"""
    print("\n" + "="*80)
    print("🚀 Running Pipeline (directory_catalog → schema_aggregation)")
    print("="*80)
    
    input_files = find_data_files()
    
    if not input_files:
        print("❌ No data files found!")
        return None
    
    from src.agents.graph import build_partial_agent
    
    # schema_aggregation까지만 빌드
    agent = build_partial_agent(until_node="schema_aggregation")
    
    initial_state = {
        # Input Directory
        "input_directory": str(DATA_DIR),
        
        # Dataset Context
        "current_dataset_id": "open_vitaldb_v1.0.0",
        "current_table_name": None,
        "data_catalog": {},
        
        # [directory_catalog] Result (to be filled)
        "directory_catalog_result": None,
        "catalog_dir_ids": [],
        
        # [file_catalog] Result (to be filled)
        "file_catalog_result": None,
        "catalog_file_ids": [],
        
        # [schema_aggregation] Result (to be filled)
        "schema_aggregation_result": None,
        "unique_columns": [],
        "unique_files": [],
        "column_batches": [],
        "file_batches": [],
        
        # Multi-Node Workflow Context
        "input_files": input_files,
        "processing_progress": {
            "phase": "catalog",
            "current_file": None,
            "current_file_index": 0,
            "total_files": len(input_files),
        },
        
        # System
        "logs": [],
    }
    
    print("\n🏃 Starting pipeline execution...")
    start_time = datetime.now()
    
    try:
        final_state = agent.invoke(initial_state)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print("\n" + "="*80)
        print("✅ Pipeline Completed!")
        print(f"   Duration: {duration:.1f} seconds")
        print("="*80)
        
        return final_state
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return None


# =============================================================================
# Data Viewers: State Data
# =============================================================================

def get_fresh_connection():
    """새로운 DB 커넥션 가져오기"""
    from src.database.connection import get_db_manager
    db = get_db_manager()
    conn = db.get_connection()
    try:
        conn.rollback()
    except:
        pass
    return conn


def print_state_data(state: Dict[str, Any]):
    """Pipeline State에서 반환된 데이터 출력"""
    
    # =============================================================================
    # 1. Directory Catalog Result
    # =============================================================================
    print("\n" + "="*80)
    print("📁 [1] DIRECTORY CATALOG - State Data")
    print("="*80)
    
    dir_result = state.get("directory_catalog_result", {})
    dir_ids = state.get("catalog_dir_ids", [])
    
    print(f"\n📊 Summary:")
    print(f"   Total directories: {dir_result.get('total_dirs', 0)}")
    print(f"   Processed directories: {dir_result.get('processed_dirs', 0)}")
    print(f"   Total files detected: {dir_result.get('total_files', 0)}")
    print(f"   Started at: {dir_result.get('started_at', '-')}")
    print(f"   Completed at: {dir_result.get('completed_at', '-')}")
    
    print(f"\n📋 Catalog Dir IDs ({len(dir_ids)}):")
    for i, did in enumerate(dir_ids[:10]):
        print(f"   [{i+1}] {did}")
    if len(dir_ids) > 10:
        print(f"   ... and {len(dir_ids) - 10} more")
    
    # =============================================================================
    # 2. File Catalog Result
    # =============================================================================
    print("\n" + "="*80)
    print("📦 [2] FILE CATALOG - State Data")
    print("="*80)
    
    file_result = state.get("file_catalog_result", {})
    file_ids = state.get("catalog_file_ids", [])
    
    print(f"\n📊 Summary:")
    print(f"   Total files: {file_result.get('total_files', 0)}")
    print(f"   Processed files: {file_result.get('processed_files', 0)}")
    print(f"   Skipped files: {file_result.get('skipped_files', 0)}")
    print(f"   Failed files: {file_result.get('failed_files', 0)}")
    print(f"   Success rate: {file_result.get('success_rate', '0%')}")
    
    print(f"\n📋 Catalog File IDs ({len(file_ids)}):")
    for i, fid in enumerate(file_ids[:10]):
        print(f"   [{i+1}] {fid}")
    if len(file_ids) > 10:
        print(f"   ... and {len(file_ids) - 10} more")
    
    # 파일별 상세 결과
    results = file_result.get("results", [])
    if results:
        print(f"\n📁 File Processing Results ({len(results)} files):")
        for r in results[:10]:
            fname = os.path.basename(r.get("file_path", "?"))
            success = "✅" if r.get("success") else "❌"
            skipped = " (skipped)" if r.get("skipped") else ""
            cols = r.get("column_count", 0)
            fid = r.get("file_id", "")[:8] if r.get("file_id") else "-"
            print(f"   {success} [{fid}] {fname} ({cols} columns){skipped}")
        if len(results) > 10:
            print(f"   ... and {len(results) - 10} more")
    
    # =============================================================================
    # 3. Schema Aggregation Result
    # =============================================================================
    print("\n" + "="*80)
    print("🔄 [3] SCHEMA AGGREGATION - State Data")
    print("="*80)
    
    agg_result = state.get("schema_aggregation_result", {})
    unique_columns = state.get("unique_columns", [])
    unique_files = state.get("unique_files", [])
    column_batches = state.get("column_batches", [])
    file_batches = state.get("file_batches", [])
    
    print(f"\n📊 Summary:")
    print(f"   Total columns in DB: {agg_result.get('total_columns_in_db', 0)}")
    print(f"   Unique column count: {agg_result.get('unique_column_count', 0)}")
    print(f"   Unique file count: {agg_result.get('unique_file_count', 0)}")
    print(f"   Column batch size: {agg_result.get('column_batch_size', 0)}")
    print(f"   File batch size: {agg_result.get('file_batch_size', 0)}")
    print(f"   Column batches: {agg_result.get('column_batches', 0)}")
    print(f"   File batches: {agg_result.get('file_batches', 0)}")
    print(f"   Aggregated at: {agg_result.get('aggregated_at', '-')}")
    
    # Unique Columns
    print(f"\n📝 Unique Columns ({len(unique_columns)}):")
    print("-"*90)
    print(f"{'Name':<30} {'Type':<12} {'Freq':<6} {'Avg Min':<10} {'Avg Max':<10} {'Unit'}")
    print("-"*90)
    
    for col in unique_columns[:20]:
        name = col.get("original_name", "?")[:28]
        col_type = col.get("column_type", "?")[:10]
        freq = col.get("frequency", 0)
        avg_min = col.get("avg_min")
        avg_max = col.get("avg_max")
        unit = col.get("sample_unit", "-") or "-"
        
        avg_min_str = f"{avg_min:.2f}" if avg_min is not None else "-"
        avg_max_str = f"{avg_max:.2f}" if avg_max is not None else "-"
        
        print(f"{name:<30} {col_type:<12} {freq:<6} {avg_min_str:<10} {avg_max_str:<10} {unit}")
    
    if len(unique_columns) > 20:
        print(f"... and {len(unique_columns) - 20} more columns")
    
    # Unique Files
    print(f"\n📁 Unique Files ({len(unique_files)}):")
    print("-"*90)
    print(f"{'File Name':<35} {'Type':<10} {'Columns':<8} {'Size MB':<10} {'Row Count'}")
    print("-"*90)
    
    for f in unique_files[:20]:
        name = f.get("file_name", "?")[:33]
        ptype = f.get("processor_type", "?")[:8]
        cols = f.get("column_count", 0)
        size = f.get("file_size_mb", 0)
        rows = f.get("row_count")
        rows_str = str(rows) if rows else "-"
        
        print(f"{name:<35} {ptype:<10} {cols:<8} {size:<10.2f} {rows_str}")
    
    if len(unique_files) > 20:
        print(f"... and {len(unique_files) - 20} more files")
    
    # Column Batches
    print(f"\n📦 Column Batches ({len(column_batches)}):")
    for i, batch in enumerate(column_batches[:5]):
        col_names = [c.get("original_name", "?") for c in batch[:5]]
        if len(batch) > 5:
            col_names.append(f"... +{len(batch)-5}")
        print(f"   Batch {i+1}: {len(batch)} columns - {col_names}")
    if len(column_batches) > 5:
        print(f"   ... and {len(column_batches) - 5} more batches")
    
    # File Batches
    print(f"\n📦 File Batches ({len(file_batches)}):")
    for i, batch in enumerate(file_batches[:5]):
        file_names = [f.get("file_name", "?") for f in batch[:3]]
        if len(batch) > 3:
            file_names.append(f"... +{len(batch)-3}")
        print(f"   Batch {i+1}: {len(batch)} files - {file_names}")
    if len(file_batches) > 5:
        print(f"   ... and {len(file_batches) - 5} more batches")


# =============================================================================
# Data Viewers: Database Tables
# =============================================================================

def print_directory_catalog_table(limit: int = 20):
    """directory_catalog 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📂 TABLE: directory_catalog")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM directory_catalog")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT dir_id, dir_name, dir_path, dir_type, file_count, 
                   subdir_count, total_size_bytes, file_extensions, filename_samples
            FROM directory_catalog
            ORDER BY file_count DESC
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'Dir ID':<12} {'Dir Name':<25} {'Type':<12} {'Files':<7} {'Subdirs':<8} {'Size (KB)':<10}")
        print("-"*80)
        
        for row in rows:
            dir_id, dir_name, dir_path, dir_type, file_count, subdir_count, size_bytes, exts, samples = row
            dir_id_short = str(dir_id)[:8] + "..."
            name_short = dir_name[:22] + "..." if len(dir_name) > 25 else dir_name
            type_short = (dir_type or '-')[:10]
            size_kb = size_bytes / 1024 if size_bytes else 0
            
            print(f"{dir_id_short:<12} {name_short:<25} {type_short:<12} {file_count:<7} {subdir_count:<8} {size_kb:<10.1f}")
        
        print(f"\nTotal: {total} directories")
        
        # 파일 확장자 분포 및 샘플 출력
        if rows:
            print("\n📋 Directory Details:")
            for row in rows[:5]:
                dir_id, dir_name, dir_path, dir_type, file_count, subdir_count, size_bytes, exts, samples = row
                print(f"\n   📁 {dir_name}")
                print(f"      Path: {dir_path}")
                if exts:
                    print(f"      Extensions: {exts}")
                if samples:
                    sample_list = samples[:5] if isinstance(samples, list) else []
                    print(f"      Filename samples: {sample_list}")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_file_catalog_table(limit: int = 20):
    """file_catalog 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📦 TABLE: file_catalog")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM file_catalog")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT fc.file_id, fc.file_name, fc.file_extension, fc.processor_type,
                   fc.file_size_mb, fc.is_text_readable, fc.file_metadata,
                   dc.dir_name
            FROM file_catalog fc
            LEFT JOIN directory_catalog dc ON fc.dir_id = dc.dir_id
            ORDER BY fc.file_name
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'File ID':<12} {'File Name':<30} {'Ext':<6} {'Processor':<10} {'Size MB':<8} {'Directory'}")
        print("-"*90)
        
        for row in rows:
            file_id, file_name, ext, processor, size_mb, is_text, metadata, dir_name = row
            file_id_short = str(file_id)[:8] + "..."
            name_short = file_name[:27] + "..." if len(file_name) > 30 else file_name
            dir_short = (dir_name or '-')[:15]
            
            print(f"{file_id_short:<12} {name_short:<30} {ext or '-':<6} {processor or '-':<10} {size_mb or 0:<8.2f} {dir_short}")
        
        print(f"\nTotal: {total} files")
        
        # file_metadata 샘플 출력
        if rows:
            print("\n📋 File Metadata Samples:")
            for row in rows[:3]:
                file_id, file_name, ext, processor, size_mb, is_text, metadata, dir_name = row
                print(f"\n   📄 {file_name}")
                if metadata:
                    print(f"      Metadata: {json.dumps(metadata, indent=8)[:200]}...")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_column_metadata_table(limit: int = 30):
    """column_metadata 테이블 출력"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📊 TABLE: column_metadata")
    print("="*80)
    
    try:
        cursor.execute("SELECT COUNT(*) FROM column_metadata")
        total = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT fc.file_name, cm.original_name, cm.column_type, cm.data_type,
                   cm.column_info, cm.value_distribution
            FROM column_metadata cm
            JOIN file_catalog fc ON cm.file_id = fc.file_id
            ORDER BY fc.file_name, cm.col_id
            LIMIT %s
        """, (limit,))
        
        rows = cursor.fetchall()
        
        print(f"\n{'File':<25} {'Column':<20} {'Type':<12} {'Data Type':<12}")
        print("-"*75)
        
        for row in rows:
            file_name, col_name, col_type, data_type, col_info, val_dist = row
            file_short = file_name[:22] + "..." if len(file_name) > 25 else file_name
            col_short = col_name[:17] + "..." if len(col_name) > 20 else col_name
            
            print(f"{file_short:<25} {col_short:<20} {col_type or '-':<12} {data_type or '-':<12}")
        
        print(f"\nTotal: {total} columns")
        
        # 컬럼 타입별 통계
        cursor.execute("""
            SELECT column_type, COUNT(*) 
            FROM column_metadata 
            GROUP BY column_type
        """)
        stats = cursor.fetchall()
        print("\nColumn Type Distribution:")
        for col_type, cnt in stats:
            print(f"   {col_type or 'null'}: {cnt}")
        
        # column_info / value_distribution 샘플 출력
        if rows:
            print("\n📋 Column Detail Samples:")
            sample_count = 0
            for row in rows:
                if sample_count >= 3:
                    break
                file_name, col_name, col_type, data_type, col_info, val_dist = row
                if col_info or val_dist:
                    print(f"\n   📊 {file_name} → {col_name}")
                    if col_info:
                        info_str = json.dumps(col_info, indent=6)
                        print(f"      column_info: {info_str[:150]}...")
                    if val_dist:
                        dist_str = json.dumps(val_dist, indent=6)
                        print(f"      value_distribution: {dist_str[:150]}...")
                    sample_count += 1
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_summary_stats():
    """전체 요약 통계"""
    conn = get_fresh_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("📈 SUMMARY STATISTICS")
    print("="*80)
    
    tables = [
        ('directory_catalog', 'Directories'),
        ('file_catalog', 'Files'),
        ('column_metadata', 'Columns'),
    ]
    
    print(f"\n{'Table':<25} {'Count':>10}")
    print("-"*40)
    
    for table_name, display_name in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"{display_name:<25} {count:>10}")
        except Exception as e:
            conn.rollback()
            print(f"{display_name:<25} {'ERROR':>10}")


# =============================================================================
# Main
# =============================================================================

def main():
    """메인 함수"""
    print("="*80)
    print("🧪 Pipeline Test: directory_catalog → schema_aggregation")
    print("="*80)
    print(f"   Dataset: Open VitalDB")
    print(f"   Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. DB 리셋
    reset_database()
    
    # 2. 파이프라인 실행 (schema_aggregation까지)
    final_state = run_pipeline_to_schema_aggregation()
    
    if not final_state:
        print("\n❌ Pipeline failed. Cannot show results.")
        return
    
    # 3. State 데이터 출력
    print("\n" + "="*80)
    print("📋 PIPELINE STATE DATA")
    print("="*80)
    print_state_data(final_state)
    
    # 4. DB 테이블 데이터 출력
    print("\n" + "="*80)
    print("📋 DATABASE TABLE CONTENTS")
    print("="*80)
    print_summary_stats()
    print_directory_catalog_table(limit=20)
    print_file_catalog_table(limit=20)
    print_column_metadata_table(limit=30)
    
    # 5. 완료
    print("\n" + "="*80)
    print("✅ All Data Displayed!")
    print("="*80)
    
    # Logs 출력
    logs = final_state.get("logs", [])
    if logs:
        print("\n📝 Pipeline Logs:")
        for log in logs:
            print(f"   {log}")


if __name__ == "__main__":
    main()

