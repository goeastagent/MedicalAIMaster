# src/database/version_manager.py
"""
Dataset-First Architecture: 테이블 버전 관리

인덱싱 히스토리를 추적하고 스키마 변경을 감지합니다.
"""

import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from psycopg2.extras import Json


class VersionManager:
    """테이블 버전 관리자"""
    
    def __init__(self, db_manager):
        """
        Args:
            db_manager: DatabaseManager 인스턴스
        """
        self.db = db_manager
        self._ensure_version_table()
    
    def _ensure_version_table(self):
        """버전 관리 테이블 생성 (없으면)"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 버전 관리 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS _table_versions (
                    id SERIAL PRIMARY KEY,
                    table_id VARCHAR(500) NOT NULL,
                    dataset_id VARCHAR(255) NOT NULL,
                    table_name VARCHAR(255) NOT NULL,
                    original_filename VARCHAR(255),
                    original_filepath VARCHAR(1000),
                    row_count INTEGER,
                    column_count INTEGER,
                    schema_hash VARCHAR(64),
                    version INTEGER DEFAULT 1,
                    indexed_at TIMESTAMP DEFAULT NOW(),
                    is_current BOOLEAN DEFAULT TRUE,
                    previous_version_id INTEGER REFERENCES _table_versions(id),
                    metadata JSONB DEFAULT '{}'::jsonb
                );
                
                -- 인덱스 생성 (없으면)
                CREATE INDEX IF NOT EXISTS idx_versions_table_id 
                    ON _table_versions(table_id);
                CREATE INDEX IF NOT EXISTS idx_versions_dataset 
                    ON _table_versions(dataset_id);
                CREATE INDEX IF NOT EXISTS idx_versions_current 
                    ON _table_versions(is_current) WHERE is_current = TRUE;
            """)
            
            # 데이터셋 정보 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS _datasets (
                    dataset_id VARCHAR(255) PRIMARY KEY,
                    dataset_name VARCHAR(255),
                    source_path VARCHAR(1000),
                    version VARCHAR(50),
                    master_anchor VARCHAR(255),
                    table_count INTEGER DEFAULT 0,
                    total_rows BIGINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    last_indexed_at TIMESTAMP,
                    metadata JSONB DEFAULT '{}'::jsonb
                );
            """)
            
            conn.commit()
            print("✅ [VersionManager] 버전 관리 테이블 준비 완료")
            
        except Exception as e:
            print(f"⚠️ [VersionManager] 테이블 생성 중 오류 (이미 존재할 수 있음): {e}")
            conn.rollback()
        finally:
            cursor.close()
    
    def record_indexing(
        self,
        table_id: str,
        dataset_id: str,
        table_name: str,
        original_filename: str,
        original_filepath: str,
        row_count: int,
        column_count: int,
        schema_hash: str,
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        인덱싱 기록 (버전 증가)
        
        Returns:
            버전 정보 딕셔너리 {id, version, is_schema_changed}
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. 이전 버전 조회
            cursor.execute("""
                SELECT id, version, schema_hash 
                FROM _table_versions 
                WHERE table_id = %s AND is_current = TRUE
            """, (table_id,))
            
            prev_row = cursor.fetchone()
            prev_version_id = None
            new_version = 1
            is_schema_changed = False
            
            if prev_row:
                prev_version_id = prev_row[0]
                new_version = prev_row[1] + 1
                is_schema_changed = prev_row[2] != schema_hash
                
                # 이전 버전을 is_current = FALSE로 변경
                cursor.execute("""
                    UPDATE _table_versions 
                    SET is_current = FALSE 
                    WHERE id = %s
                """, (prev_version_id,))
            
            # 2. 새 버전 삽입 (metadata는 Json 어댑터로 변환)
            cursor.execute("""
                INSERT INTO _table_versions 
                (table_id, dataset_id, table_name, original_filename, original_filepath,
                 row_count, column_count, schema_hash, version, is_current, 
                 previous_version_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s)
                RETURNING id
            """, (
                table_id, dataset_id, table_name, original_filename, original_filepath,
                row_count, column_count, schema_hash, new_version,
                prev_version_id, 
                Json(metadata) if metadata else Json({})
            ))
            
            new_id = cursor.fetchone()[0]
            
            # 3. 데이터셋 정보 업데이트
            self._update_dataset_stats(cursor, dataset_id)
            
            conn.commit()
            
            print(f"📝 [Version] {table_name} v{new_version} 기록 완료")
            if is_schema_changed:
                print(f"   ⚠️ 스키마 변경 감지!")
            
            return {
                "id": new_id,
                "version": new_version,
                "is_schema_changed": is_schema_changed,
                "previous_version_id": prev_version_id
            }
            
        except Exception as e:
            conn.rollback()
            print(f"❌ [Version] 기록 실패: {e}")
            raise
        finally:
            cursor.close()
    
    def _update_dataset_stats(self, cursor, dataset_id: str):
        """데이터셋 통계 업데이트"""
        cursor.execute("""
            INSERT INTO _datasets (dataset_id, last_indexed_at)
            VALUES (%s, NOW())
            ON CONFLICT (dataset_id) DO UPDATE SET
                last_indexed_at = NOW(),
                table_count = (
                    SELECT COUNT(DISTINCT table_name) 
                    FROM _table_versions 
                    WHERE dataset_id = %s AND is_current = TRUE
                ),
                total_rows = (
                    SELECT COALESCE(SUM(row_count), 0) 
                    FROM _table_versions 
                    WHERE dataset_id = %s AND is_current = TRUE
                )
        """, (dataset_id, dataset_id, dataset_id))
    
    def register_dataset(
        self,
        dataset_id: str,
        dataset_name: str,
        source_path: str,
        version: str,
        master_anchor: Optional[str] = None
    ):
        """데이터셋 정보 등록/업데이트"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO _datasets 
                (dataset_id, dataset_name, source_path, version, master_anchor, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (dataset_id) DO UPDATE SET
                    dataset_name = EXCLUDED.dataset_name,
                    source_path = EXCLUDED.source_path,
                    version = EXCLUDED.version,
                    master_anchor = COALESCE(EXCLUDED.master_anchor, _datasets.master_anchor)
            """, (dataset_id, dataset_name, source_path, version, master_anchor))
            
            conn.commit()
            print(f"📁 [Dataset] {dataset_name} ({dataset_id}) 등록됨")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ [Dataset] 등록 실패: {e}")
        finally:
            cursor.close()
    
    def update_dataset_master_anchor(self, dataset_id: str, master_anchor: str):
        """데이터셋의 Master Anchor 업데이트"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                UPDATE _datasets 
                SET master_anchor = %s 
                WHERE dataset_id = %s
            """, (master_anchor, dataset_id))
            
            conn.commit()
            print(f"👑 [Dataset] {dataset_id} Master Anchor: {master_anchor}")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ [Dataset] Master Anchor 업데이트 실패: {e}")
        finally:
            cursor.close()
    
    def get_table_history(self, table_id: str) -> List[Dict]:
        """테이블 인덱싱 히스토리 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT id, version, row_count, column_count, schema_hash, 
                       indexed_at, is_current, previous_version_id
                FROM _table_versions 
                WHERE table_id = %s 
                ORDER BY version DESC
            """, (table_id,))
            
            columns = ['id', 'version', 'row_count', 'column_count', 'schema_hash',
                       'indexed_at', 'is_current', 'previous_version_id']
            
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        finally:
            cursor.close()
    
    def get_dataset_info(self, dataset_id: str) -> Optional[Dict]:
        """데이터셋 정보 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT dataset_id, dataset_name, source_path, version, 
                       master_anchor, table_count, total_rows, 
                       created_at, last_indexed_at
                FROM _datasets 
                WHERE dataset_id = %s
            """, (dataset_id,))
            
            row = cursor.fetchone()
            if row:
                columns = ['dataset_id', 'dataset_name', 'source_path', 'version',
                           'master_anchor', 'table_count', 'total_rows',
                           'created_at', 'last_indexed_at']
                return dict(zip(columns, row))
            return None
            
        finally:
            cursor.close()
    
    def get_all_datasets(self) -> List[Dict]:
        """모든 데이터셋 목록 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT dataset_id, dataset_name, source_path, version,
                       master_anchor, table_count, total_rows,
                       created_at, last_indexed_at
                FROM _datasets
                ORDER BY created_at DESC
            """)
            
            columns = ['dataset_id', 'dataset_name', 'source_path', 'version',
                       'master_anchor', 'table_count', 'total_rows',
                       'created_at', 'last_indexed_at']
            
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        finally:
            cursor.close()
    
    def get_current_tables(self, dataset_id: Optional[str] = None) -> List[Dict]:
        """현재 버전 테이블 목록 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            query = """
                SELECT table_id, dataset_id, table_name, original_filename,
                       row_count, column_count, version, indexed_at
                FROM _table_versions
                WHERE is_current = TRUE
            """
            params = []
            
            if dataset_id:
                query += " AND dataset_id = %s"
                params.append(dataset_id)
            
            query += " ORDER BY indexed_at DESC"
            
            cursor.execute(query, params)
            
            columns = ['table_id', 'dataset_id', 'table_name', 'original_filename',
                       'row_count', 'column_count', 'version', 'indexed_at']
            
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        finally:
            cursor.close()


# 전역 싱글톤
_global_version_manager = None

def get_version_manager(db_manager=None):
    """전역 VersionManager 반환"""
    global _global_version_manager
    
    if _global_version_manager is None:
        if db_manager is None:
            from database.connection import get_db_manager
            db_manager = get_db_manager()
        _global_version_manager = VersionManager(db_manager)
    
    return _global_version_manager

