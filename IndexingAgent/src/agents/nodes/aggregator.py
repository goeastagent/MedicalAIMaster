# src/agents/nodes/aggregator.py
"""
Schema Aggregation Node

DB에서 유니크 컬럼명과 대표 통계를 집계하여
LLM 배치 호출을 준비합니다.

핵심 기능:
- 유니크 컬럼명 추출 (GROUP BY original_name)
- 대표 통계 집계 (AVG min/max/mean, sample values)
- 배치 분할 (config.BATCH_SIZE 단위)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from src.agents.state import AgentState
from src.database.connection import get_db_manager
from src.config import SchemaAggregationConfig, MetadataSemanticConfig

from ..base import BaseNode, DatabaseMixin
from ..registry import register_node


@register_node
class SchemaAggregationNode(BaseNode, DatabaseMixin):
    """
    Schema Aggregation Node (Rule-based)
    
    DB에서 유니크 컬럼명과 대표 통계를 집계하여
    LLM 배치 호출을 준비합니다.
    """
    
    name = "schema_aggregation"
    description = "유니크 컬럼/파일 집계 및 LLM 배치 준비"
    order = 300
    requires_llm = False
    
    # =========================================================================
    # SQL Queries
    # =========================================================================
    
    AGGREGATE_ALL_SQL = """
    SELECT 
        cm.original_name,
        cm.column_type,
        COUNT(DISTINCT cm.file_id) as frequency,
        
        -- 통계 (JSON에서 추출)
        AVG((cm.column_info->>'min')::float) as avg_min,
        AVG((cm.column_info->>'max')::float) as avg_max,
        AVG((cm.column_info->>'mean')::float) as avg_mean,
        AVG((cm.column_info->>'unique_count')::float) as avg_unique_count,
        AVG((cm.column_info->>'unique_ratio')::float) as avg_unique_ratio,
        MAX(cm.column_info->>'unit') as sample_unit,
        
        -- 대표 값 분포 (첫 번째 유효값)
        (SELECT sub.value_distribution
         FROM column_metadata sub 
         WHERE sub.original_name = cm.original_name 
           AND sub.value_distribution IS NOT NULL 
           AND sub.value_distribution != '{}'::jsonb
         LIMIT 1
        ) as sample_distribution

    FROM column_metadata cm
    GROUP BY cm.original_name, cm.column_type
    ORDER BY frequency DESC, cm.original_name;
    """
    
    AGGREGATE_FILES_SQL = """
    SELECT 
        fc.file_id,
        fc.file_name,
        fc.file_extension,
        fc.processor_type,
        fc.file_size_mb,
        fc.file_metadata,
        
        -- 컬럼 정보 요약
        COUNT(cm.col_id) as column_count,
        ARRAY_AGG(DISTINCT cm.original_name) as column_names,
        ARRAY_AGG(DISTINCT cm.column_type) as column_types
        
    FROM file_catalog fc
    LEFT JOIN column_metadata cm ON fc.file_id = cm.file_id
    WHERE fc.semantic_type IS NULL  -- 아직 분석 안 된 파일만
    GROUP BY fc.file_id, fc.file_name, fc.file_extension, 
             fc.processor_type, fc.file_size_mb, fc.file_metadata
    ORDER BY fc.file_name;
    """
    
    # =========================================================================
    # Main Execution
    # =========================================================================
    
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        유니크 컬럼과 파일을 집계하고 LLM 배치를 준비
        
        Args:
            state: AgentState
        
        Returns:
            업데이트된 상태:
            - schema_aggregation_result: 집계 결과 요약
            - unique_columns: 유니크 컬럼 리스트
            - unique_files: 유니크 파일 리스트
            - column_batches: 컬럼 LLM 배치 리스트
            - file_batches: 파일 LLM 배치 리스트
        """
        print("\n" + "=" * 60)
        print("🔄 [Schema Aggregation] 유니크 컬럼/파일 집계")
        print("=" * 60)
        
        # 1. 집계 통계 조회
        stats = self._get_aggregation_stats()
        print(f"\n📊 Current DB Stats:")
        print(f"   Total files: {stats.get('total_files', 0):,}")
        print(f"   Total columns: {stats.get('total_columns', 0):,}")
        print(f"   Unique columns: {stats.get('unique_columns', 0):,}")
        
        if stats.get('unique_by_type'):
            print(f"   By type: {stats.get('unique_by_type')}")
        
        # 2. 유니크 컬럼 집계
        print(f"\n🔍 Aggregating unique columns...")
        unique_columns = self._aggregate_unique_columns()
        print(f"   ✅ Found {len(unique_columns)} unique columns")
        
        # 컬럼 배치 준비
        column_batch_size = MetadataSemanticConfig.COLUMN_BATCH_SIZE
        column_batches = self._prepare_batches(unique_columns, column_batch_size)
        print(f"\n📦 Column LLM Batches:")
        print(f"   Batch size: {column_batch_size}")
        print(f"   Total batches: {len(column_batches)}")
        
        # 샘플 출력
        if unique_columns:
            print(f"\n📝 Sample columns (top 5 by frequency):")
            for col in unique_columns[:5]:
                self._print_column_sample(col)
        
        # 3. 파일 집계
        print(f"\n🔍 Aggregating files for semantic analysis...")
        unique_files = self._aggregate_unique_files()
        print(f"   ✅ Found {len(unique_files)} files to analyze")
        
        # 파일 배치 준비
        file_batch_size = MetadataSemanticConfig.FILE_BATCH_SIZE
        file_batches = self._prepare_batches(unique_files, file_batch_size)
        print(f"\n📦 File LLM Batches:")
        print(f"   Batch size: {file_batch_size}")
        print(f"   Total batches: {len(file_batches)}")
        
        # 샘플 출력
        if unique_files:
            print(f"\n📁 Sample files:")
            for f in unique_files[:5]:
                name = f.get('file_name', '?')
                cols = f.get('column_count', 0)
                ptype = f.get('processor_type', '?')
                print(f"   - {name} ({ptype}, {cols} columns)")
        
        # 4. 결과 구성
        result = {
            "total_columns_in_db": stats.get('total_columns', 0),
            "unique_column_count": len(unique_columns),
            "unique_file_count": len(unique_files),
            "column_batch_size": column_batch_size,
            "file_batch_size": file_batch_size,
            "column_batches": len(column_batches),
            "file_batches": len(file_batches),
            "aggregated_at": datetime.now().isoformat(),
            "stats": stats
        }
        
        print(f"\n✅ [Schema Aggregation] Complete!")
        print(f"   → {len(unique_columns)} unique columns → {len(column_batches)} batches")
        print(f"   → {len(unique_files)} files → {len(file_batches)} batches")
        print(f"   → Ready for LLM analysis!")
        print("=" * 60 + "\n")
        
        return {
            "schema_aggregation_result": result,
            "unique_columns": unique_columns,
            "unique_files": unique_files,
            "column_batches": column_batches,
            "file_batches": file_batches
        }
    
    # =========================================================================
    # Aggregation Methods
    # =========================================================================
    
    def _aggregate_unique_columns(self) -> List[Dict[str, Any]]:
        """DB에서 유니크 컬럼명과 대표 통계 추출"""
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(self.AGGREGATE_ALL_SQL)
            rows = cursor.fetchall()
            
            col_names = [desc[0] for desc in cursor.description]
            
            unique_columns = []
            for row in rows:
                row_dict = dict(zip(col_names, row))
                column_info = self._build_column_info(row_dict)
                unique_columns.append(column_info)
            
            return unique_columns
            
        except Exception as e:
            print(f"[Schema Aggregation] Error aggregating columns: {e}")
            conn.rollback()
            raise
        finally:
            cursor.close()
    
    def _aggregate_unique_files(self) -> List[Dict[str, Any]]:
        """파일 정보 집계"""
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(self.AGGREGATE_FILES_SQL)
            rows = cursor.fetchall()
            
            col_names = [desc[0] for desc in cursor.description]
            
            files = []
            for row in rows:
                row_dict = dict(zip(col_names, row))
                file_info = self._build_file_info(row_dict)
                files.append(file_info)
            
            return files
            
        except Exception as e:
            print(f"[Schema Aggregation] Error aggregating files: {e}")
            conn.rollback()
            raise
        finally:
            cursor.close()
    
    def _get_aggregation_stats(self) -> Dict[str, Any]:
        """집계 통계 조회"""
        db = get_db_manager()
        conn = db.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        try:
            cursor.execute("SELECT COUNT(*) FROM column_metadata")
            stats["total_columns"] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT original_name) FROM column_metadata")
            stats["unique_columns"] = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT column_type, COUNT(DISTINCT original_name) 
                FROM column_metadata 
                GROUP BY column_type
            """)
            stats["unique_by_type"] = dict(cursor.fetchall())
            
            cursor.execute("SELECT COUNT(*) FROM file_catalog")
            stats["total_files"] = cursor.fetchone()[0]
            
        except Exception as e:
            print(f"[Schema Aggregation] Error getting stats: {e}")
            stats["error"] = str(e)
        
        return stats
    
    # =========================================================================
    # Helper Methods: Build Info Dicts
    # =========================================================================
    
    def _build_column_info(self, row_dict: Dict[str, Any]) -> Dict[str, Any]:
        """컬럼 정보 딕셔너리 생성"""
        column_info = {
            "original_name": row_dict["original_name"],
            "column_type": row_dict["column_type"] or "unknown",
            "frequency": row_dict["frequency"] or 0,
        }
        
        # 수치형 통계
        if row_dict.get("avg_min") is not None:
            column_info["avg_min"] = round(row_dict["avg_min"], 2)
        if row_dict.get("avg_max") is not None:
            column_info["avg_max"] = round(row_dict["avg_max"], 2)
        if row_dict.get("avg_mean") is not None:
            column_info["avg_mean"] = round(row_dict["avg_mean"], 2)
        
        # 범주형 통계
        if row_dict.get("avg_unique_count") is not None:
            column_info["avg_unique_count"] = round(row_dict["avg_unique_count"], 1)
        if row_dict.get("avg_unique_ratio") is not None:
            column_info["avg_unique_ratio"] = round(row_dict["avg_unique_ratio"], 3)
        
        # 단위
        if row_dict.get("sample_unit"):
            column_info["sample_unit"] = row_dict["sample_unit"]
        
        # 대표 값 분포
        sample_dist = row_dict.get("sample_distribution")
        if sample_dist and isinstance(sample_dist, dict):
            max_samples = SchemaAggregationConfig.MAX_SAMPLE_VALUES
            top_values = dict(list(sample_dist.items())[:max_samples])
            if top_values:
                column_info["sample_values"] = top_values
        
        return column_info
    
    def _build_file_info(self, row_dict: Dict[str, Any]) -> Dict[str, Any]:
        """파일 정보 딕셔너리 생성"""
        file_info = {
            "file_id": str(row_dict["file_id"]),
            "file_name": row_dict["file_name"],
            "file_extension": row_dict["file_extension"],
            "processor_type": row_dict["processor_type"],
            "file_size_mb": float(row_dict["file_size_mb"]) if row_dict["file_size_mb"] else 0,
            "column_count": row_dict["column_count"] or 0,
            "column_names": row_dict["column_names"][:20] if row_dict["column_names"] else [],
            "column_types": list(set(row_dict["column_types"])) if row_dict["column_types"] else []
        }
        
        # file_metadata에서 주요 정보 추출
        metadata = row_dict.get("file_metadata", {}) or {}
        if metadata:
            file_info["row_count"] = metadata.get("row_count")
            file_info["duration_seconds"] = metadata.get("duration_seconds")
        
        return file_info
    
    # =========================================================================
    # Helper Methods: Batching & Utils
    # =========================================================================
    
    def _prepare_batches(
        self,
        items: List[Dict[str, Any]],
        batch_size: int
    ) -> List[List[Dict[str, Any]]]:
        """아이템을 배치로 분할"""
        batches = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            batches.append(batch)
        return batches
    
    def _print_column_sample(self, col: Dict[str, Any]):
        """컬럼 샘플 출력"""
        freq = col.get('frequency', 0)
        col_type = col.get('column_type', 'unknown')
        name = col.get('original_name', '?')
        
        stat_str = ""
        if col.get('avg_min') is not None:
            stat_str = f"range: [{col.get('avg_min'):.1f}, {col.get('avg_max'):.1f}]"
        elif col.get('sample_values'):
            values = list(col['sample_values'].keys())[:3]
            stat_str = f"values: {values}"
        
        print(f"   - {name} ({col_type}, freq={freq}) {stat_str}")
    
    # =========================================================================
    # Convenience Methods (Standalone Execution)
    # =========================================================================
    
    @classmethod
    def run_standalone(cls, verbose: bool = True) -> Dict[str, Any]:
        """
        독립 실행 (테스트/디버깅용)
        
        Returns:
            Dict with unique_columns, batches, and stats
        """
        node = cls()
        
        if verbose:
            print("\n" + "=" * 60)
            print("🔄 Running Schema Aggregation...")
            print("=" * 60)
        
        # 컬럼 집계
        unique_columns = node._aggregate_unique_columns()
        column_batches = node._prepare_batches(unique_columns, MetadataSemanticConfig.COLUMN_BATCH_SIZE)
        
        # 파일 집계
        unique_files = node._aggregate_unique_files()
        file_batches = node._prepare_batches(unique_files, MetadataSemanticConfig.FILE_BATCH_SIZE)
        
        # 통계
        stats = node._get_aggregation_stats()
        
        result = {
            "unique_columns": unique_columns,
            "column_batches": column_batches,
            "unique_files": unique_files,
            "file_batches": file_batches,
            "stats": stats,
            "unique_column_count": len(unique_columns),
            "unique_file_count": len(unique_files),
            "column_batch_count": len(column_batches),
            "file_batch_count": len(file_batches)
        }
        
        if verbose:
            print(f"\n✅ Aggregation Complete:")
            print(f"   Unique columns: {len(unique_columns)} → {len(column_batches)} batches")
            print(f"   Unique files: {len(unique_files)} → {len(file_batches)} batches")
        
        return result
    
    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """집계 통계 조회"""
        node = cls()
        return node._get_aggregation_stats()
