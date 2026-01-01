# src/agents/nodes/metadata_semantic.py
"""
MetaData Semantic Analysis Node

metadata 파일에서 key-desc-unit을 추출하여 data_dictionary에 저장합니다.

✅ LLM 사용:
  1. 컬럼 역할 추론 (어떤 컬럼이 key/desc/unit인지)
  2. 비구조화 TXT 파일 파싱 (추후 지원)
"""

import os
from typing import Dict, Any, List, Optional
from datetime import datetime
import pandas as pd

from src.agents.state import AgentState
from src.database import (
    get_db_manager,
    ensure_dictionary_schema,
    insert_dictionary_entries_batch,
    DictionarySchemaManager,
)
from src.config import LLMConfig
from src.agents.models.llm_responses import (
    ColumnRoleMapping,
    MetadataSemanticResult,
)
from src.utils.llm_client import get_llm_client

from ..base import BaseNode, LLMMixin, DatabaseMixin
from ..registry import register_node


@register_node
class MetadataSemanticNode(BaseNode, LLMMixin, DatabaseMixin):
    """
    Metadata Semantic Analysis Node (LLM-based)
    
    metadata 파일에서 key-desc-unit을 추출하여 data_dictionary에 저장합니다.
    """
    
    name = "metadata_semantic"
    description = "메타데이터 파일 분석 및 data_dictionary 추출"
    order = 500
    requires_llm = True
    
    # =========================================================================
    # Prompt Template
    # =========================================================================
    
    COLUMN_ROLE_PROMPT = """You are a Medical Data Expert analyzing a metadata/dictionary file.

[Task]
Analyze this file and identify which column serves which role:

- **key_column**: The column containing parameter names/codes (e.g., "age", "hr", "sbp")
  This is the main identifier column that other data files will reference.
  
- **desc_column**: The column containing descriptions or definitions
  Human-readable explanations of what each parameter means.
  
- **unit_column**: The column containing measurement units (e.g., "years", "bpm", "mmHg")
  May be empty or null for some parameters.
  
- **extra_columns**: Other useful columns mapped to their semantic role
  Examples: {{"category": "Category", "reference_value": "Reference value", "data_source": "Data Source"}}

[File Info]
File: {file_name}
Columns: {column_names}

[Columns with Sample Values]
{columns_info}

[Sample Rows (first 5)]
{sample_rows}

[Output Format]
Return ONLY valid JSON (no markdown, no explanation):
{{
  "key_column": "Parameter",
  "desc_column": "Description",
  "unit_column": "Unit",
  "extra_columns": {{"category": "Category", "reference": "Reference value"}},
  "confidence": 0.95,
  "reasoning": "Parameter column contains unique identifiers, Description has explanations, Unit has measurement units"
}}
"""
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        메타데이터 파일에서 key-desc-unit 추출
        
        Args:
            state: AgentState (metadata_files 필요)
        
        Returns:
            업데이트된 상태:
            - metadata_semantic_result: 처리 결과 요약
            - data_dictionary_entries: 추출된 모든 엔트리
        """
        print("\n" + "=" * 60)
        print("📖 [MetaData Semantic] 메타데이터 분석 및 dictionary 추출")
        print("=" * 60)
        
        started_at = datetime.now()
        
        # data_dictionary 테이블 확인/생성
        ensure_dictionary_schema()
        
        # metadata 파일 목록
        metadata_files = state.get("metadata_files", [])
        
        if not metadata_files:
            print("   ⚠️ No metadata files to process")
            return self._create_empty_result("No metadata files")
        
        print(f"   📂 Metadata files to process: {len(metadata_files)}")
        for f in metadata_files:
            print(f"      - {f.split('/')[-1]}")
        
        all_entries = []
        entries_by_file = {}
        processed_files = 0
        llm_calls = 0
        
        for file_path in metadata_files:
            file_name = file_path.split('/')[-1]
            print(f"\n   📄 Processing: {file_name}")
            
            # 1. 파일 상세 정보 조회
            file_info = self._get_metadata_file_details(file_path)
            if not file_info:
                print(f"      ❌ Failed to get file details")
                continue
            
            print(f"      Columns: {[c['name'] for c in file_info['columns']]}")
            
            # 2. LLM 호출 → 컬럼 역할 추론
            print(f"      🤖 Calling LLM for column role mapping...")
            column_mapping = self._call_llm_for_column_roles(file_info)
            llm_calls += 1
            
            if not column_mapping:
                print(f"      ❌ Failed to get column mapping")
                continue
            
            print(f"      ✅ Column roles identified (conf={column_mapping.confidence:.2f}):")
            print(f"         key: {column_mapping.key_column}")
            print(f"         desc: {column_mapping.desc_column}")
            print(f"         unit: {column_mapping.unit_column}")
            if column_mapping.extra_columns:
                print(f"         extra: {column_mapping.extra_columns}")
            
            # 3. Dictionary 엔트리 추출 (파일 직접 읽기)
            entries = self._extract_from_raw_data(file_info, column_mapping)
            
            if not entries:
                # 대안: sample_rows/unique_values 기반 추출
                entries = self._extract_dictionary_entries(file_info, column_mapping)
            
            if entries:
                # 4. DB에 저장
                print(f"      💾 Saving {len(entries)} entries to data_dictionary...")
                inserted = insert_dictionary_entries_batch(entries)
                print(f"      ✅ Saved {inserted} entries")
                
                all_entries.extend(entries)
                entries_by_file[file_name] = len(entries)
                processed_files += 1
            else:
                print(f"      ⚠️ No entries extracted")
        
        # 결과 요약
        completed_at = datetime.now()
        duration = (completed_at - started_at).total_seconds()
        
        result = MetadataSemanticResult(
            total_metadata_files=len(metadata_files),
            processed_files=processed_files,
            total_entries_extracted=len(all_entries),
            entries_by_file=entries_by_file,
            llm_calls=llm_calls,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat()
        )
        
        print(f"\n✅ [MetaData Semantic] Complete!")
        print(f"   📁 Processed files: {processed_files}/{len(metadata_files)}")
        print(f"   📝 Total entries: {len(all_entries)}")
        for fname, count in entries_by_file.items():
            print(f"      - {fname}: {count} entries")
        print(f"   🤖 LLM calls: {llm_calls}")
        print(f"   ⏱️  Duration: {duration:.1f}s")
        print("=" * 60 + "\n")
        
        # 통계 출력
        schema_manager = DictionarySchemaManager()
        stats = schema_manager.get_stats()
        print(f"   📊 Data Dictionary Stats: {stats}")
        
        return {
            "metadata_semantic_result": result.model_dump(),
            "data_dictionary_entries": all_entries,
            "logs": [
                f"📖 [MetaData Semantic] Extracted {len(all_entries)} entries from "
                f"{processed_files} metadata files"
            ]
        }
    
    # =========================================================================
    # File Info Collection
    # =========================================================================
    
    def _get_metadata_file_details(self, file_path: str) -> Optional[Dict[str, Any]]:
        """metadata 파일의 상세 정보 조회"""
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT file_id, file_name, file_path, file_metadata, raw_stats
                FROM file_catalog
                WHERE file_path = %s
            """, (file_path,))
            
            row = cursor.fetchone()
            if not row:
                cursor.execute("""
                    SELECT file_id, file_name, file_path, file_metadata, raw_stats
                    FROM file_catalog
                    WHERE file_name = %s
                """, (file_path.split('/')[-1],))
                row = cursor.fetchone()
            
            if not row:
                return None
            
            file_id, file_name, file_path_db, file_metadata, raw_stats = row
            
            metadata = file_metadata if isinstance(file_metadata, dict) else {}
            raw = raw_stats if isinstance(raw_stats, dict) else {}
            row_count = metadata.get('row_count') or raw.get('row_count', 0)
            sample_rows = raw.get('sample_rows', [])
            
            cursor.execute("""
                SELECT original_name, data_type, column_type, value_distribution
                FROM column_metadata
                WHERE file_id = %s
                ORDER BY col_id
            """, (file_id,))
            
            columns = []
            for col_row in cursor.fetchall():
                col_name, dtype, col_type, value_dist = col_row
                dist = value_dist if isinstance(value_dist, dict) else {}
                unique_values = dist.get('unique_values', [])
                samples = dist.get('samples', [])
                all_unique = unique_values if unique_values else samples
                
                columns.append({
                    "name": col_name,
                    "dtype": dtype or "unknown",
                    "column_type": col_type or "unknown",
                    "all_unique_values": all_unique,
                    "n_unique": len(all_unique)
                })
            
            return {
                "file_id": str(file_id),
                "file_name": file_name,
                "file_path": file_path_db or file_path,
                "row_count": row_count,
                "columns": columns,
                "sample_rows": sample_rows[:5] if sample_rows else []
            }
            
        except Exception as e:
            print(f"   ❌ Error getting metadata file details: {e}")
            return None
    
    # =========================================================================
    # LLM Methods
    # =========================================================================
    
    def _call_llm_for_column_roles(
        self,
        file_info: Dict[str, Any]
    ) -> Optional[ColumnRoleMapping]:
        """LLM을 호출하여 컬럼 역할 추론"""
        llm = get_llm_client()
        
        file_name = file_info['file_name']
        columns = file_info['columns']
        sample_rows = file_info.get('sample_rows', [])
        
        column_names = [c['name'] for c in columns]
        columns_info_text = self._build_columns_info_text(columns)
        sample_rows_text = self._build_sample_rows_text(sample_rows, columns)
        
        prompt = self.COLUMN_ROLE_PROMPT.format(
            file_name=file_name,
            column_names=", ".join(column_names),
            columns_info=columns_info_text,
            sample_rows=sample_rows_text
        )
        
        try:
            data = llm.ask_json(prompt, max_tokens=LLMConfig.MAX_TOKENS)
            
            if data.get("error"):
                print(f"   ❌ LLM returned error: {data.get('error')}")
                return None
            
            return ColumnRoleMapping(
                key_column=data.get('key_column', ''),
                desc_column=data.get('desc_column'),
                unit_column=data.get('unit_column'),
                extra_columns=data.get('extra_columns', {}),
                confidence=data.get('confidence', 0.8),
                reasoning=data.get('reasoning', '')
            )
            
        except Exception as e:
            print(f"   ❌ LLM call error: {e}")
            return None
    
    def _build_columns_info_text(self, columns: List[Dict[str, Any]]) -> str:
        """컬럼 정보를 LLM 프롬프트용 텍스트로 변환"""
        lines = []
        
        for i, col in enumerate(columns, 1):
            col_name = col['name']
            col_type = col.get('column_type', 'unknown')
            n_unique = col.get('n_unique', 0)
            dtype = col.get('dtype', 'unknown')
            unique_vals = col.get('all_unique_values', [])
            
            lines.append(f'{i}. "{col_name}" [{col_type}, {n_unique} unique values]')
            lines.append(f"   dtype: {dtype}")
            
            if unique_vals:
                vals_display = unique_vals[:20]
                vals_str = [str(v)[:50] for v in vals_display]
                lines.append(f"   Sample values: {vals_str}")
                if len(unique_vals) > 20:
                    lines.append(f"   ... and {len(unique_vals) - 20} more values")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_sample_rows_text(self, sample_rows: List[Dict], columns: List[Dict]) -> str:
        """샘플 행을 테이블 형식 텍스트로 변환"""
        if not sample_rows:
            return "(No sample rows available)"
        
        col_names = [c['name'] for c in columns]
        lines = []
        
        header = " | ".join(col_names[:8])
        lines.append(header)
        lines.append("-" * len(header))
        
        for row in sample_rows[:5]:
            if isinstance(row, dict):
                values = [str(row.get(c, ''))[:20] for c in col_names[:8]]
            else:
                values = [str(v)[:20] for v in list(row)[:8]]
            lines.append(" | ".join(values))
        
        return "\n".join(lines)
    
    # =========================================================================
    # Data Dictionary Extraction
    # =========================================================================
    
    def _extract_from_raw_data(
        self,
        file_info: Dict[str, Any],
        column_mapping: ColumnRoleMapping
    ) -> List[Dict[str, Any]]:
        """raw_stats에 저장된 전체 데이터에서 dictionary 엔트리 추출"""
        file_id = file_info['file_id']
        file_name = file_info['file_name']
        file_path = file_info['file_path']
        
        key_col = column_mapping.key_column
        desc_col = column_mapping.desc_column
        unit_col = column_mapping.unit_column
        extra_cols = column_mapping.extra_columns
        
        entries = []
        
        try:
            if os.path.exists(file_path):
                ext = file_path.lower().split('.')[-1]
                
                if ext == 'csv':
                    df = pd.read_csv(file_path)
                elif ext == 'tsv':
                    df = pd.read_csv(file_path, sep='\t')
                elif ext in ['xlsx', 'xls']:
                    df = pd.read_excel(file_path)
                else:
                    print(f"   ⚠️ Unsupported file type: {ext}")
                    return []
                
                for _, row in df.iterrows():
                    key_val = row.get(key_col)
                    if pd.isna(key_val) or key_val == '':
                        continue
                    
                    desc_val = row.get(desc_col) if desc_col else None
                    unit_val = row.get(unit_col) if unit_col else None
                    
                    if pd.isna(desc_val):
                        desc_val = None
                    if pd.isna(unit_val):
                        unit_val = None
                    
                    extra_info = {}
                    for role, col_name in extra_cols.items():
                        if col_name in row.index:
                            val = row[col_name]
                            if not pd.isna(val):
                                extra_info[role] = str(val)
                    
                    entries.append({
                        'source_file_id': file_id,
                        'source_file_name': file_name,
                        'parameter_key': str(key_val),
                        'parameter_desc': str(desc_val) if desc_val else None,
                        'parameter_unit': str(unit_val) if unit_val else None,
                        'extra_info': extra_info,
                        'llm_confidence': column_mapping.confidence
                    })
                
                print(f"      📄 Extracted {len(entries)} entries from file")
                
        except Exception as e:
            print(f"   ❌ Error reading file: {e}")
        
        return entries
    
    def _extract_dictionary_entries(
        self,
        file_info: Dict[str, Any],
        column_mapping: ColumnRoleMapping
    ) -> List[Dict[str, Any]]:
        """파일에서 data_dictionary 엔트리 추출 (sample_rows 기반)"""
        file_id = file_info['file_id']
        file_name = file_info['file_name']
        columns = file_info['columns']
        
        col_values = {c['name']: c.get('all_unique_values', []) for c in columns}
        
        key_col = column_mapping.key_column
        desc_col = column_mapping.desc_column
        unit_col = column_mapping.unit_column
        extra_cols = column_mapping.extra_columns
        
        if not key_col or key_col not in col_values:
            print(f"   ⚠️ Key column '{key_col}' not found in file")
            return []
        
        sample_rows = file_info.get('sample_rows', [])
        entries = []
        
        if sample_rows:
            for row in sample_rows:
                if not isinstance(row, dict):
                    continue
                
                key_val = row.get(key_col)
                if not key_val:
                    continue
                
                desc_val = row.get(desc_col) if desc_col else None
                unit_val = row.get(unit_col) if unit_col else None
                
                extra_info = {}
                for role, col_name in extra_cols.items():
                    if col_name in row:
                        extra_info[role] = row[col_name]
                
                entries.append({
                    'source_file_id': file_id,
                    'source_file_name': file_name,
                    'parameter_key': str(key_val),
                    'parameter_desc': str(desc_val) if desc_val else None,
                    'parameter_unit': str(unit_val) if unit_val else None,
                    'extra_info': extra_info,
                    'llm_confidence': column_mapping.confidence
                })
        else:
            key_values = col_values.get(key_col, [])
            desc_values = col_values.get(desc_col, []) if desc_col else []
            unit_values = col_values.get(unit_col, []) if unit_col else []
            
            for i, key_val in enumerate(key_values):
                desc_val = desc_values[i] if i < len(desc_values) else None
                unit_val = unit_values[i] if i < len(unit_values) else None
                
                entries.append({
                    'source_file_id': file_id,
                    'source_file_name': file_name,
                    'parameter_key': str(key_val),
                    'parameter_desc': str(desc_val) if desc_val else None,
                    'parameter_unit': str(unit_val) if unit_val else None,
                    'extra_info': {},
                    'llm_confidence': column_mapping.confidence
                })
        
        return entries
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _create_empty_result(self, error_msg: str) -> Dict[str, Any]:
        """빈 결과 생성"""
        return {
            "metadata_semantic_result": {
                "total_metadata_files": 0,
                "processed_files": 0,
                "total_entries_extracted": 0,
                "error": error_msg
            },
            "data_dictionary_entries": [],
            "logs": [f"⚠️ [MetaData Semantic] {error_msg}"]
        }
    
    # =========================================================================
    # Convenience Methods (Standalone Execution)
    # =========================================================================
    
    @classmethod
    def run_standalone(cls, metadata_files: List[str] = None) -> Dict[str, Any]:
        """
        독립 실행 (테스트용)
        
        Args:
            metadata_files: 처리할 metadata 파일 경로 목록
                           None이면 DB에서 is_metadata=true인 파일 조회
        
        Returns:
            처리 결과
        """
        node = cls()
        
        if metadata_files is None:
            db = get_db_manager()
            conn = db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT file_path FROM file_catalog 
                WHERE is_metadata = true 
                ORDER BY file_name
            """)
            metadata_files = [row[0] for row in cursor.fetchall()]
        
        state = {"metadata_files": metadata_files}
        return node.execute(state)
