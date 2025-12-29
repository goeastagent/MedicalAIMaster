"""
Phase 1C: Directory Pattern Analysis Node

디렉토리 내 파일명 패턴을 LLM으로 분석하고, 파일명에서 ID/값을 추출하여 
다른 테이블과의 관계를 연결합니다.

✅ LLM 사용:
  1. 파일명 패턴 식별
  2. 패턴에서 추출 가능한 값이 Data Dictionary의 어떤 컬럼과 매칭되는지 판단

입력 (DB에서 읽기):
  - directory_catalog.filename_samples (Phase -1에서 수집)
  - column_metadata (Phase 1A에서 분석됨)

출력 (DB에 저장):
  - directory_catalog.filename_pattern, filename_columns
  - file_catalog.filename_values (배치 업데이트)
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from src.agents.state import AgentState
from src.database.connection import get_db_manager
from src.config import Phase1CConfig


# =============================================================================
# 전역 리소스
# =============================================================================

_db_manager = None
_llm_client = None


def _get_db():
    """DB Manager 싱글톤 반환"""
    global _db_manager
    if _db_manager is None:
        _db_manager = get_db_manager()
    return _db_manager


def _get_llm():
    """LLM Client 싱글톤 반환"""
    global _llm_client
    if _llm_client is None:
        from src.utils.llm_client import get_llm_client
        _llm_client = get_llm_client()
    return _llm_client


# =============================================================================
# LLM 프롬프트 (영어)
# =============================================================================

SYSTEM_PROMPT = """You are a medical dataset filename pattern analysis expert.

## Task
Given directory filename samples and a data dictionary, analyze:
1. Identify filename patterns for each directory
2. Determine which columns from the data dictionary match values extractable from filenames

## Output Format (JSON)
{
    "directories": [
        {
            "dir_id": "uuid-string",
            "has_pattern": true,
            "pattern": "{caseid:integer}.vital",
            "pattern_regex": "^(\\\\d+)\\\\.vital$",
            "columns": [
                {
                    "name": "caseid",
                    "type": "integer",
                    "position": 1,
                    "matched_column": "caseid",
                    "match_confidence": 0.95,
                    "match_reasoning": "Numeric value in filename matches caseid format in clinical_data"
                }
            ],
            "confidence": 0.95,
            "reasoning": "All 6388 files follow {number}.vital pattern"
        },
        {
            "dir_id": "uuid-string-2",
            "has_pattern": false,
            "pattern": null,
            "pattern_regex": null,
            "columns": [],
            "confidence": 0.9,
            "reasoning": "Various CSV files with no consistent naming pattern"
        }
    ]
}

## Rules
1. pattern_regex must be a valid PostgreSQL regex (use \\\\ for backslash in JSON)
2. position is 1-indexed capture group number
3. type should be "integer" or "text"
4. Only set has_pattern=true if a clear, consistent pattern exists
5. matched_column should reference exact column name from data dictionary
6. If no matching column found in data dictionary, set matched_column to null
"""

USER_PROMPT_TEMPLATE = """
## Data Dictionary
The following tables and columns are available in this dataset:

{data_dictionary}

## Directories to Analyze

{directories_info}

Analyze the filename patterns for each directory and match extractable values to data dictionary columns.
"""


# =============================================================================
# DB 조회 함수 (파일 읽기 없음 - DB에서만 조회)
# =============================================================================

def _get_directories_for_analysis() -> List[Dict]:
    """
    Query directories from directory_catalog (DB)
    
    Data source: directory_catalog table (populated by Phase -1)
    - filename_samples: collected during Phase -1 directory scan
    - file_extensions: counted during Phase -1
    - dir_type: classified during Phase -1
    """
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT dir_id, dir_path, dir_name, file_count, 
               file_extensions, filename_samples, dir_type
        FROM directory_catalog
        WHERE file_count >= %s
          AND filename_pattern IS NULL
        ORDER BY file_count DESC
    """, (Phase1CConfig.MIN_FILES_FOR_PATTERN,))
    
    directories = []
    for row in cursor.fetchall():
        samples = row[5] if row[5] else []
        # LLM에 전달할 샘플 수 제한
        limited_samples = samples[:Phase1CConfig.MAX_SAMPLES_PER_DIR]
        
        directories.append({
            "dir_id": str(row[0]),
            "dir_path": row[1],
            "dir_name": row[2],
            "file_count": row[3],
            "file_extensions": row[4] if row[4] else {},
            "filename_samples": limited_samples,
            "dir_type": row[6]
        })
    
    return directories


def _collect_data_dictionary() -> Dict[str, Any]:
    """
    Collect data dictionary from DB (Phase 1A/1B results)
    
    Data source: 
    - file_catalog: primary_entity, entity_identifier_column (from Phase 1A)
    - column_metadata: semantic_name, description, concept_category (from Phase 1B)
    
    NO file reading - all from DB
    """
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            fc.file_name,
            fc.primary_entity,
            fc.entity_identifier_column,
            cm.original_name,
            cm.semantic_name,
            cm.description,
            cm.value_distribution
        FROM file_catalog fc
        JOIN column_metadata cm ON fc.file_id = cm.file_id
        WHERE fc.is_metadata = FALSE
          AND (cm.description IS NOT NULL OR cm.semantic_name IS NOT NULL)
        ORDER BY fc.file_name, cm.col_id
    """)
    
    # Group by table
    tables = {}
    for row in cursor.fetchall():
        file_name = row[0]
        if file_name not in tables:
            tables[file_name] = {
                "primary_entity": row[1],
                "entity_identifier": row[2],
                "columns": []
            }
        
        # value_distribution에서 샘플 값 추출
        value_dist = row[6] if row[6] else {}
        examples = value_dist.get('samples', []) if isinstance(value_dist, dict) else []
        
        tables[file_name]["columns"].append({
            "name": row[3],
            "type": row[4],
            "description": row[5],
            "examples": examples
        })
    
    return tables


def _collect_data_dictionary_simple() -> Dict[str, Any]:
    """
    Data Dictionary 간단 버전 - Phase 1A 결과가 없어도 동작
    
    column_metadata에서 직접 컬럼 정보 수집
    """
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    dict_entries = {}
    
    # data_dictionary 테이블이 있으면 조회
    try:
        cursor.execute("""
            SELECT 
                parameter_key,
                parameter_desc,
                parameter_unit,
                source_file_name
            FROM data_dictionary
            ORDER BY parameter_key
        """)
        
        for row in cursor.fetchall():
            key = row[0]
            if key not in dict_entries:
                dict_entries[key] = {
                    "description": row[1],
                    "unit": row[2],
                    "source": row[3]
                }
    except Exception as e:
        print(f"   ⚠️ data_dictionary table not available: {e}")
        conn.rollback()
    
    # column_metadata에서 ID 관련 컬럼 수집
    cursor.execute("""
        SELECT DISTINCT
            fc.file_name,
            cm.original_name,
            cm.data_type,
            cm.value_distribution
        FROM file_catalog fc
        JOIN column_metadata cm ON fc.file_id = cm.file_id
        WHERE fc.is_metadata = FALSE
          AND (
              LOWER(cm.original_name) LIKE '%%id%%' 
              OR LOWER(cm.original_name) LIKE '%%case%%'
              OR LOWER(cm.original_name) LIKE '%%subject%%'
          )
        ORDER BY fc.file_name
    """)
    
    id_columns = {}
    for row in cursor.fetchall():
        file_name = row[0]
        if file_name not in id_columns:
            id_columns[file_name] = []
        
        # value_distribution에서 샘플 추출
        value_dist = row[3] if row[3] else {}
        examples = value_dist.get('samples', []) if isinstance(value_dist, dict) else []
        
        id_columns[file_name].append({
            "name": row[1],
            "type": row[2],
            "examples": examples
        })
    
    return {
        "dictionary_entries": dict_entries,
        "id_columns_by_file": id_columns
    }


# =============================================================================
# 배치 처리
# =============================================================================

def _batch_directories(directories: List[Dict], batch_size: int) -> List[List[Dict]]:
    """디렉토리 목록을 배치로 분할"""
    batches = []
    for i in range(0, len(directories), batch_size):
        batches.append(directories[i:i + batch_size])
    return batches


# =============================================================================
# LLM 분석
# =============================================================================

def _analyze_batch(
    directories: List[Dict], 
    data_dictionary: Dict
) -> List[Dict]:
    """
    Analyze directory batch with LLM
    
    Input: All from DB (directories from directory_catalog, data_dictionary from column_metadata)
    Output: Pattern analysis results
    """
    llm = _get_llm()
    
    # Build directories info for prompt
    dirs_info_parts = []
    for i, d in enumerate(directories):
        samples_str = "\n".join([f"  - {s}" for s in d['filename_samples']])
        dirs_info_parts.append(
            f"### Directory {i+1}: {d['dir_name']}\n"
            f"- dir_id: {d['dir_id']}\n"
            f"- File count: {d['file_count']}\n"
            f"- Extensions: {json.dumps(d['file_extensions'])}\n"
            f"- Type: {d['dir_type']}\n"
            f"- Filename samples:\n{samples_str}"
        )
    
    dirs_info = "\n\n".join(dirs_info_parts)
    
    user_prompt = USER_PROMPT_TEMPLATE.format(
        data_dictionary=json.dumps(data_dictionary, indent=2, ensure_ascii=False),
        directories_info=dirs_info
    )
    
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"
    
    try:
        result = llm.ask_json(full_prompt)
        
        if result.get("error"):
            print(f"   ❌ LLM returned error: {result.get('error')}")
            return []
        
        return result.get("directories", [])
        
    except Exception as e:
        print(f"   ❌ LLM call error: {e}")
        return []


# =============================================================================
# DB 저장
# =============================================================================

def _save_pattern_results(results: List[Dict]):
    """Save pattern analysis results to directory_catalog"""
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    saved_count = 0
    
    for r in results:
        try:
            cursor.execute("""
                UPDATE directory_catalog
                SET filename_pattern = %s,
                    filename_columns = %s,
                    pattern_confidence = %s,
                    pattern_reasoning = %s,
                    pattern_analyzed_at = NOW()
                WHERE dir_id = %s
            """, (
                r.get("pattern"),
                json.dumps(r.get("columns", [])),
                r.get("confidence"),
                r.get("reasoning"),
                r["dir_id"]
            ))
            saved_count += 1
        except Exception as e:
            print(f"   ❌ Error saving pattern for dir_id={r.get('dir_id')}: {e}")
            conn.rollback()
            continue
    
    conn.commit()
    print(f"   💾 Saved {saved_count} pattern results to directory_catalog")


def _update_filename_values(results: List[Dict]):
    """
    Batch update file_catalog.filename_values
    
    Uses PostgreSQL regex to extract values from file_name column (already in DB)
    NO file system access - pure DB operation
    
    Note: regexp_matches is a set-returning function, so we use substring instead
    """
    db = _get_db()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    updated_total = 0
    
    for r in results:
        if not r.get("has_pattern") or not r.get("columns"):
            continue
        
        dir_id = r["dir_id"]
        pattern_regex = r.get("pattern_regex")
        
        if not pattern_regex:
            continue
        
        for col in r["columns"]:
            col_name = col.get("name")
            if not col_name:
                continue
                
            col_type = col.get("type", "text")
            
            try:
                # PostgreSQL substring을 사용하여 첫 번째 캡처 그룹 추출
                # substring(file_name from 'pattern')은 첫 번째 캡처 그룹 반환
                if col_type == "integer":
                    # 정수형 캐스팅
                    cursor.execute("""
                        UPDATE file_catalog
                        SET filename_values = CASE 
                            WHEN file_name ~ %s THEN
                                COALESCE(filename_values, '{}'::jsonb) || 
                                jsonb_build_object(%s, substring(file_name from %s)::integer)
                            ELSE filename_values
                        END
                        WHERE dir_id = %s
                          AND file_name ~ %s
                    """, (
                        pattern_regex,  # CASE WHEN condition
                        col_name,       # jsonb key
                        pattern_regex,  # substring pattern (extracts first capture group)
                        dir_id,         # WHERE dir_id
                        pattern_regex   # WHERE file_name ~
                    ))
                else:
                    # 텍스트형
                    cursor.execute("""
                        UPDATE file_catalog
                        SET filename_values = CASE 
                            WHEN file_name ~ %s THEN
                                COALESCE(filename_values, '{}'::jsonb) || 
                                jsonb_build_object(%s, substring(file_name from %s))
                            ELSE filename_values
                        END
                        WHERE dir_id = %s
                          AND file_name ~ %s
                    """, (
                        pattern_regex,
                        col_name,
                        pattern_regex,
                        dir_id,
                        pattern_regex
                    ))
                
                updated_total += cursor.rowcount
                
            except Exception as e:
                print(f"   ❌ Error updating filename_values for dir_id={dir_id}, col={col_name}: {e}")
                conn.rollback()
                continue
        
        conn.commit()
    
    print(f"   💾 Updated filename_values for {updated_total} files")


# =============================================================================
# LangGraph Node Function
# =============================================================================

def phase1c_directory_pattern_node(state: AgentState) -> Dict[str, Any]:
    """
    [Phase 1C] Directory Pattern Analysis Node
    
    All data is read from DB (no file re-reading):
    - directory_catalog: filename_samples, file_extensions (from Phase -1)
    - column_metadata: column info with semantic descriptions (from Phase 1A)
    
    Steps:
    1. Query directories from directory_catalog
    2. Query data dictionary from column_metadata / data_dictionary
    3. Analyze patterns with LLM
    4. Save results to directory_catalog
    5. Batch update file_catalog.filename_values
    
    Args:
        state: AgentState
    
    Returns:
        업데이트된 상태:
        - phase1c_result: 처리 결과 요약
        - phase1c_dir_patterns: {dir_id: pattern_info}
    """
    print("\n" + "=" * 60)
    print("📁 Phase 1C: Directory Pattern Analysis")
    print("=" * 60)
    
    started_at = datetime.now()
    
    # 1. 분석 대상 디렉토리 조회 (DB에서)
    print("\n   📂 Querying directories from DB...")
    directories = _get_directories_for_analysis()
    
    if not directories:
        print("   ⚠️ No directories to analyze (all already analyzed or file_count < MIN_FILES)")
        return {
            "phase1c_result": {
                "status": "skipped",
                "reason": "no_directories",
                "total_dirs": 0,
                "analyzed_dirs": 0,
                "patterns_found": 0
            },
            "phase1c_dir_patterns": {},
            "logs": ["⚠️ [Phase 1C] No directories to analyze"]
        }
    
    print(f"   📂 Found {len(directories)} directories to analyze:")
    for d in directories:
        print(f"      - {d['dir_name']} ({d['file_count']} files, type={d['dir_type']})")
    
    # 2. Data Dictionary 수집 (DB에서)
    print("\n   📖 Collecting data dictionary from DB...")
    data_dictionary = _collect_data_dictionary()
    
    if not data_dictionary:
        # Phase 1A 결과가 없으면 간단 버전 사용
        print("   ⚠️ No semantic data from Phase 1A, using simple dictionary")
        data_dictionary = _collect_data_dictionary_simple()
    
    print(f"   📖 Data dictionary: {len(data_dictionary)} tables/entries")
    
    # 3. 배치 처리
    print(f"\n   🤖 Analyzing patterns with LLM (batch_size={Phase1CConfig.MAX_DIRS_PER_BATCH})...")
    
    all_results = []
    batches = _batch_directories(directories, Phase1CConfig.MAX_DIRS_PER_BATCH)
    
    for i, batch in enumerate(batches):
        print(f"      Batch {i+1}/{len(batches)}: {len(batch)} directories")
        batch_result = _analyze_batch(batch, data_dictionary)
        all_results.extend(batch_result)
        print(f"      ✅ Got {len(batch_result)} results")
    
    # 4. 결과 저장
    print("\n   💾 Saving pattern results to directory_catalog...")
    _save_pattern_results(all_results)
    
    # 5. filename_values 배치 업데이트
    print("\n   💾 Updating file_catalog.filename_values...")
    _update_filename_values(all_results)
    
    # 결과 요약
    completed_at = datetime.now()
    duration = (completed_at - started_at).total_seconds()
    
    patterns_found = sum(1 for r in all_results if r.get("has_pattern"))
    
    result = {
        "status": "completed",
        "total_dirs": len(directories),
        "analyzed_dirs": len(all_results),
        "patterns_found": patterns_found,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": duration
    }
    
    dir_patterns = {r["dir_id"]: r for r in all_results}
    
    print(f"\n✅ Phase 1C Complete!")
    print(f"   📁 Directories analyzed: {len(all_results)}/{len(directories)}")
    print(f"   🔍 Patterns found: {patterns_found}")
    for r in all_results:
        if r.get("has_pattern"):
            print(f"      - {r.get('dir_id', 'unknown')[:8]}: {r.get('pattern')} (conf={r.get('confidence', 0):.2f})")
    print(f"   ⏱️  Duration: {duration:.1f}s")
    print("=" * 60 + "\n")
    
    return {
        "phase1c_result": result,
        "phase1c_dir_patterns": dir_patterns,
        "logs": [
            f"📁 [Phase 1C] Analyzed {len(all_results)} directories, "
            f"found {patterns_found} patterns"
        ]
    }


# =============================================================================
# 편의 함수
# =============================================================================

def run_phase1c_standalone() -> Dict[str, Any]:
    """
    Phase 1C 독립 실행 (테스트용)
    
    Returns:
        처리 결과
    """
    state = {}
    return phase1c_directory_pattern_node(state)

