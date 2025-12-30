# src/database/schema_directory.py
"""
Directory Catalog 스키마

Phase 1에서 디렉토리 레벨 메타데이터를 저장하는 테이블 정의
- directory_catalog: 디렉토리 단위 메타데이터 (파일 통계, 파일명 패턴 등)
"""

from typing import Optional, Dict, Any, List
from .connection import get_db_manager


# =============================================================================
# DDL: 테이블 생성 SQL
# =============================================================================

CREATE_DIRECTORY_CATALOG_SQL = """
CREATE TABLE IF NOT EXISTS directory_catalog (
    -- Primary Key
    dir_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 경로 정보
    dir_path TEXT UNIQUE NOT NULL,           -- 절대 경로 (unique constraint)
    dir_name VARCHAR(255) NOT NULL,          -- 디렉토리명 (예: "vital_files")
    parent_dir_id UUID REFERENCES directory_catalog(dir_id) ON DELETE SET NULL,  -- 상위 디렉토리 FK
    
    -- 파일 통계 (Phase 1: Rule-based 수집)
    file_count INTEGER DEFAULT 0,            -- 총 파일 수 (직계 자식만)
    file_extensions JSONB,                   -- {"vital": 6388, "csv": 3}
    total_size_bytes BIGINT DEFAULT 0,       -- 총 크기
    total_size_mb FLOAT DEFAULT 0.0,
    
    -- 하위 디렉토리 통계
    subdir_count INTEGER DEFAULT 0,          -- 직계 하위 디렉토리 수
    
    -- 파일명 샘플 (Phase 1: LLM 분석용 수집)
    filename_samples JSONB,                  -- ["0001.vital", "0002.vital", ..., "6388.vital"]
    filename_sample_count INTEGER DEFAULT 0, -- 샘플 수
    
    -- 패턴 분석 결과 (Phase 7에서 LLM이 채움)
    filename_pattern TEXT,                   -- "{caseid:integer}.vital"
    filename_columns JSONB,                  -- [{"name": "caseid", "type": "integer", "links_to": {...}}]
    pattern_confidence FLOAT,                -- LLM confidence
    pattern_reasoning TEXT,                  -- LLM reasoning
    pattern_analyzed_at TIMESTAMP,           -- LLM 분석 시점
    
    -- 디렉토리 분류 (Phase 4에서 채워질 수 있음)
    dir_type VARCHAR(50),                    -- "signal_files", "tabular_files", "metadata", "mixed"
    
    -- 메타
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_directory_catalog_parent ON directory_catalog(parent_dir_id);
CREATE INDEX IF NOT EXISTS idx_directory_catalog_dir_type ON directory_catalog(dir_type);
CREATE INDEX IF NOT EXISTS idx_directory_catalog_path ON directory_catalog(dir_path);
"""

# file_catalog에 FK 제약 추가 (directory_catalog가 먼저 생성된 후)
ADD_FILE_CATALOG_DIR_FK_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'fk_file_catalog_dir'
    ) THEN
        ALTER TABLE file_catalog 
        ADD CONSTRAINT fk_file_catalog_dir 
        FOREIGN KEY (dir_id) REFERENCES directory_catalog(dir_id) ON DELETE SET NULL;
    END IF;
END $$;
"""

# Updated_at 자동 갱신 트리거
CREATE_DIRECTORY_UPDATE_TRIGGER_SQL = """
-- directory_catalog 트리거
DROP TRIGGER IF EXISTS update_directory_catalog_updated_at ON directory_catalog;
CREATE TRIGGER update_directory_catalog_updated_at
    BEFORE UPDATE ON directory_catalog
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
"""


# =============================================================================
# Schema Manager Class
# =============================================================================

class DirectorySchemaManager:
    """Directory Catalog 스키마 관리"""
    
    def __init__(self, db_manager=None):
        self.db = db_manager or get_db_manager()
    
    def create_tables(self) -> bool:
        """
        directory_catalog 테이블 생성
        
        Returns:
            True if successful
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. directory_catalog 테이블 생성
            cursor.execute(CREATE_DIRECTORY_CATALOG_SQL)
            
            # 2. file_catalog에 FK 제약 추가 (테이블이 존재하면)
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'file_catalog'
                )
            """)
            if cursor.fetchone()[0]:
                cursor.execute(ADD_FILE_CATALOG_DIR_FK_SQL)
            
            # 3. 트리거 생성 (update_updated_at_column 함수가 있으면)
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_proc 
                    WHERE proname = 'update_updated_at_column'
                )
            """)
            if cursor.fetchone()[0]:
                cursor.execute(CREATE_DIRECTORY_UPDATE_TRIGGER_SQL)
            
            conn.commit()
            print("[DirectorySchema] Tables created successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[DirectorySchema] Error creating tables: {e}")
            raise
    
    def drop_tables(self, confirm: bool = False) -> bool:
        """
        테이블 삭제 (주의: 모든 데이터 삭제됨)
        
        Args:
            confirm: True로 설정해야 삭제 실행
        """
        if not confirm:
            print("[DirectorySchema] Set confirm=True to drop tables")
            return False
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # FK 제약 먼저 제거
            cursor.execute("""
                ALTER TABLE IF EXISTS file_catalog 
                DROP CONSTRAINT IF EXISTS fk_file_catalog_dir
            """)
            # 테이블 삭제
            cursor.execute("DROP TABLE IF EXISTS directory_catalog CASCADE")
            conn.commit()
            print("[DirectorySchema] Tables dropped successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[DirectorySchema] Error dropping tables: {e}")
            raise
    
    def reset_tables(self) -> bool:
        """테이블 초기화 (삭제 후 재생성)"""
        self.drop_tables(confirm=True)
        return self.create_tables()
    
    def table_exists(self, table_name: str = 'directory_catalog') -> bool:
        """테이블 존재 여부 확인"""
        return self.db.table_exists(table_name)
    
    def get_stats(self) -> dict:
        """directory_catalog 통계 조회"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        try:
            # 전체 디렉토리 수
            cursor.execute("SELECT COUNT(*) FROM directory_catalog")
            stats['total_directories'] = cursor.fetchone()[0]
            
            # dir_type별 수
            cursor.execute("""
                SELECT dir_type, COUNT(*) 
                FROM directory_catalog 
                WHERE dir_type IS NOT NULL
                GROUP BY dir_type
            """)
            stats['directories_by_type'] = dict(cursor.fetchall())
            
            # 패턴 분석 완료 수
            cursor.execute("""
                SELECT COUNT(*) FROM directory_catalog 
                WHERE filename_pattern IS NOT NULL
            """)
            stats['pattern_analyzed'] = cursor.fetchone()[0]
            
            # 총 파일 수 (모든 디렉토리 합계)
            cursor.execute("SELECT COALESCE(SUM(file_count), 0) FROM directory_catalog")
            stats['total_files_in_dirs'] = cursor.fetchone()[0]
            
        except Exception as e:
            print(f"[DirectorySchema] Error getting stats: {e}")
            stats['error'] = str(e)
        
        return stats


# =============================================================================
# CRUD 함수
# =============================================================================

def insert_directory(
    dir_path: str,
    dir_name: str,
    parent_dir_id: Optional[str] = None,
    file_count: int = 0,
    file_extensions: Optional[Dict[str, int]] = None,
    total_size_bytes: int = 0,
    subdir_count: int = 0,
    filename_samples: Optional[List[str]] = None,
    db_manager=None
) -> str:
    """
    directory_catalog에 단일 디렉토리 삽입
    
    Returns:
        dir_id (UUID string)
    """
    import json
    
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO directory_catalog (
                dir_path, dir_name, parent_dir_id,
                file_count, file_extensions, total_size_bytes, total_size_mb,
                subdir_count, filename_samples, filename_sample_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dir_path) DO UPDATE SET
                dir_name = EXCLUDED.dir_name,
                parent_dir_id = EXCLUDED.parent_dir_id,
                file_count = EXCLUDED.file_count,
                file_extensions = EXCLUDED.file_extensions,
                total_size_bytes = EXCLUDED.total_size_bytes,
                total_size_mb = EXCLUDED.total_size_mb,
                subdir_count = EXCLUDED.subdir_count,
                filename_samples = EXCLUDED.filename_samples,
                filename_sample_count = EXCLUDED.filename_sample_count,
                updated_at = NOW()
            RETURNING dir_id
        """, (
            dir_path,
            dir_name,
            parent_dir_id,
            file_count,
            json.dumps(file_extensions or {}),
            total_size_bytes,
            round(total_size_bytes / (1024 * 1024), 2),
            subdir_count,
            json.dumps(filename_samples or []),
            len(filename_samples) if filename_samples else 0
        ))
        
        dir_id = cursor.fetchone()[0]
        conn.commit()
        return str(dir_id)
        
    except Exception as e:
        conn.rollback()
        print(f"[DirectoryCatalog] Error inserting directory: {e}")
        raise


def get_directory_by_path(dir_path: str, db_manager=None) -> Optional[Dict[str, Any]]:
    """경로로 디렉토리 조회"""
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT dir_id, dir_path, dir_name, parent_dir_id,
               file_count, file_extensions, total_size_bytes, total_size_mb,
               subdir_count, filename_samples, filename_sample_count,
               filename_pattern, filename_columns, pattern_confidence,
               dir_type, created_at, updated_at
        FROM directory_catalog
        WHERE dir_path = %s
    """, (dir_path,))
    
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        'dir_id': str(row[0]),
        'dir_path': row[1],
        'dir_name': row[2],
        'parent_dir_id': str(row[3]) if row[3] else None,
        'file_count': row[4],
        'file_extensions': row[5],
        'total_size_bytes': row[6],
        'total_size_mb': row[7],
        'subdir_count': row[8],
        'filename_samples': row[9],
        'filename_sample_count': row[10],
        'filename_pattern': row[11],
        'filename_columns': row[12],
        'pattern_confidence': row[13],
        'dir_type': row[14],
        'created_at': row[15],
        'updated_at': row[16]
    }


def get_directory_by_id(dir_id: str, db_manager=None) -> Optional[Dict[str, Any]]:
    """ID로 디렉토리 조회"""
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT dir_id, dir_path, dir_name, parent_dir_id,
               file_count, file_extensions, total_size_bytes, total_size_mb,
               subdir_count, filename_samples, filename_sample_count,
               filename_pattern, filename_columns, pattern_confidence,
               dir_type, created_at, updated_at
        FROM directory_catalog
        WHERE dir_id = %s
    """, (dir_id,))
    
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        'dir_id': str(row[0]),
        'dir_path': row[1],
        'dir_name': row[2],
        'parent_dir_id': str(row[3]) if row[3] else None,
        'file_count': row[4],
        'file_extensions': row[5],
        'total_size_bytes': row[6],
        'total_size_mb': row[7],
        'subdir_count': row[8],
        'filename_samples': row[9],
        'filename_sample_count': row[10],
        'filename_pattern': row[11],
        'filename_columns': row[12],
        'pattern_confidence': row[13],
        'dir_type': row[14],
        'created_at': row[15],
        'updated_at': row[16]
    }


def update_file_catalog_dir_ids(dir_id: str, file_paths: List[str], db_manager=None) -> int:
    """
    file_catalog의 dir_id 컬럼 업데이트
    
    Args:
        dir_id: directory_catalog의 dir_id
        file_paths: 해당 디렉토리에 속한 파일 경로 목록
    
    Returns:
        업데이트된 파일 수
    """
    if not file_paths:
        return 0
    
    db = db_manager or get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # 배치 업데이트
        placeholders = ', '.join(['%s'] * len(file_paths))
        cursor.execute(f"""
            UPDATE file_catalog 
            SET dir_id = %s 
            WHERE file_path IN ({placeholders})
        """, [dir_id] + file_paths)
        
        updated = cursor.rowcount
        conn.commit()
        return updated
        
    except Exception as e:
        conn.rollback()
        print(f"[DirectoryCatalog] Error updating file_catalog dir_ids: {e}")
        raise


def get_directories_without_pattern() -> List[Dict[str, Any]]:
    """
    패턴 분석이 안 된 디렉토리 목록 조회 (Phase 7용)
    
    Returns:
        [{"dir_id": ..., "dir_path": ..., "filename_samples": [...], ...}, ...]
    """
    db = get_db_manager()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT dir_id, dir_path, dir_name, file_count, file_extensions,
               filename_samples, filename_sample_count
        FROM directory_catalog
        WHERE filename_pattern IS NULL
          AND filename_sample_count > 0
        ORDER BY file_count DESC
    """)
    
    result = []
    for row in cursor.fetchall():
        result.append({
            'dir_id': str(row[0]),
            'dir_path': row[1],
            'dir_name': row[2],
            'file_count': row[3],
            'file_extensions': row[4],
            'filename_samples': row[5],
            'filename_sample_count': row[6]
        })
    
    return result


# =============================================================================
# 편의 함수
# =============================================================================

def init_directory_schema(reset: bool = False) -> DirectorySchemaManager:
    """
    디렉토리 카탈로그 스키마 초기화
    
    Args:
        reset: True면 기존 테이블 삭제 후 재생성
    
    Returns:
        DirectorySchemaManager 인스턴스
    """
    manager = DirectorySchemaManager()
    
    if reset:
        manager.reset_tables()
    else:
        manager.create_tables()
    
    return manager


def ensure_directory_schema():
    """directory_catalog 테이블이 없으면 생성"""
    manager = DirectorySchemaManager()
    if not manager.table_exists():
        manager.create_tables()

