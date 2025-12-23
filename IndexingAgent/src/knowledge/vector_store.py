# src/knowledge/vector_store.py
"""
VectorDB 관리 (PostgreSQL pgvector 기반)

Dynamic Schema: 임베딩 모델에 따라 테이블을 동적으로 생성
- 모델별로 다른 테이블 사용 (예: column_embeddings_openai_3072)
- 모델 변경 시 해당 모델의 테이블 참조
"""

import os
from typing import List, Dict, Any, Optional

from config import EmbeddingConfig, LLMConfig


class VectorStore:
    """
    PostgreSQL pgvector 기반 VectorDB 관리 (Dynamic Schema)
    
    - 임베딩 모델에 따라 동적으로 테이블 생성
    - 모델별 테이블명: {base_name}_{provider}_{dimensions}
    - 모델 변경 시 해당 테이블 자동 참조
    """
    
    def __init__(self):
        """초기화"""
        self.conn = None
        self.embedding_client = None
        self.embedding_model = None
        self.dimensions = None
        self.provider = None
        
        # 동적 테이블명 (초기화 시 설정)
        self.column_table = None
        self.table_table = None
        self.relationship_table = None
    
    def _get_table_suffix(self) -> str:
        """현재 모델에 맞는 테이블 접미사 반환"""
        return f"{self.provider}_{self.dimensions}"
    
    def _get_table_names(self) -> Dict[str, str]:
        """현재 모델에 맞는 테이블명들 반환"""
        suffix = self._get_table_suffix()
        return {
            "column": f"column_embeddings_{suffix}",
            "table": f"table_embeddings_{suffix}",
            "relationship": f"relationship_embeddings_{suffix}"
        }
    
    def initialize(self, embedding_model: str = None):
        """
        pgvector 및 임베딩 클라이언트 초기화
        
        Args:
            embedding_model: "openai" 또는 "local" (None이면 config에서 가져옴)
        """
        # config에서 기본값 가져오기
        if embedding_model is None:
            embedding_model = EmbeddingConfig.PROVIDER
        
        self.embedding_model = embedding_model
        self.provider = embedding_model
        
        # 1. PostgreSQL 연결
        try:
            import psycopg2
            from database.connection import get_db_manager
            
            db_manager = get_db_manager()
            self.conn = db_manager.get_connection()
            print(f"✅ PostgreSQL 연결 완료")
        except Exception as e:
            print(f"❌ PostgreSQL 연결 실패: {e}")
            raise
        
        # 2. 임베딩 클라이언트 초기화
        if embedding_model == "openai":
            try:
                from openai import OpenAI
                self.embedding_client = OpenAI(api_key=LLMConfig.OPENAI_API_KEY)
                self.dimensions = EmbeddingConfig.OPENAI_DIMENSIONS
                print(f"✅ OpenAI 임베딩 클라이언트 초기화 ({EmbeddingConfig.OPENAI_MODEL})")
            except Exception as e:
                print(f"❌ OpenAI 클라이언트 초기화 실패: {e}")
                raise
        elif embedding_model == "local":
            try:
                from sentence_transformers import SentenceTransformer
                self.embedding_client = SentenceTransformer(EmbeddingConfig.LOCAL_MODEL)
                self.dimensions = EmbeddingConfig.LOCAL_DIMENSIONS
                print(f"✅ Local 임베딩 모델 로드 ({EmbeddingConfig.LOCAL_MODEL})")
            except Exception as e:
                print(f"❌ Local 임베딩 모델 로드 실패: {e}")
                raise
        else:
            raise ValueError(f"Unknown embedding model: {embedding_model}")
        
        # 3. 테이블명 설정
        table_names = self._get_table_names()
        self.column_table = table_names["column"]
        self.table_table = table_names["table"]
        self.relationship_table = table_names["relationship"]
        
        print(f"\n📋 [Dynamic Schema] 테이블명:")
        print(f"   - Column: {self.column_table}")
        print(f"   - Table: {self.table_table}")
        print(f"   - Relationship: {self.relationship_table}")
        
        # 4. pgvector 확장 및 메타데이터 테이블 자동 생성
        self._ensure_pgvector_extension()
        
        # 5. 테이블 동적 생성
        self._create_tables_if_not_exist()
        
        print(f"\n✅ VectorStore 초기화 완료")
        print(f"   - Provider: {embedding_model}")
        print(f"   - Dimensions: {self.dimensions}")
    
    def _ensure_pgvector_extension(self):
        """pgvector 확장 설치 (없으면 자동 생성)"""
        cursor = self.conn.cursor()
        
        # pgvector 확장 확인 및 설치
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname='vector'")
        if not cursor.fetchone():
            print(f"   - pgvector 확장 설치 중...")
            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                self.conn.commit()
                print(f"   - pgvector 확장 설치 완료")
            except Exception as e:
                raise RuntimeError(f"pgvector 확장 설치 실패: {e}\n"
                                   "해결: brew install pgvector 또는 apt install postgresql-XX-pgvector")
        else:
            print(f"   - pgvector 확장 확인 완료")
        
        # 메타데이터 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embedding_metadata (
                id SERIAL PRIMARY KEY,
                table_name VARCHAR(255) NOT NULL UNIQUE,
                embedding_provider VARCHAR(50) NOT NULL,
                embedding_model VARCHAR(100) NOT NULL,
                dimensions INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # 업데이트 트리거 함수 생성
        cursor.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ language 'plpgsql'
        """)
        
        self.conn.commit()
    
    def _create_tables_if_not_exist(self):
        """현재 모델에 맞는 테이블 동적 생성"""
        cursor = self.conn.cursor()
        dims = self.dimensions
        
        # 1. Column Embeddings 테이블
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.column_table} (
                id SERIAL PRIMARY KEY,
                table_name VARCHAR(255) NOT NULL,
                column_name VARCHAR(255) NOT NULL,
                full_name VARCHAR(500),
                description TEXT,
                description_kr TEXT,
                unit VARCHAR(100),
                typical_range VARCHAR(100),
                embedding vector({dims}),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(table_name, column_name)
            )
        """)
        
        # 2. Table Embeddings 테이블
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_table} (
                id SERIAL PRIMARY KEY,
                table_name VARCHAR(255) NOT NULL UNIQUE,
                description TEXT,
                columns_summary TEXT,
                row_count INTEGER,
                embedding vector({dims}),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # 3. Relationship Embeddings 테이블
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.relationship_table} (
                id SERIAL PRIMARY KEY,
                source_table VARCHAR(255) NOT NULL,
                target_table VARCHAR(255) NOT NULL,
                source_column VARCHAR(255),
                target_column VARCHAR(255),
                relation_type VARCHAR(100),
                description TEXT,
                embedding vector({dims}),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(source_table, target_table, source_column, target_column)
            )
        """)
        
        # Commit table creation before index attempt
        self.conn.commit()
        
        # 4. Vector index creation (HNSW for dims <= 2000, skip for higher dims)
        # HNSW has 2000 dimension limit
        if dims <= 2000:
            try:
                # HNSW index (faster, but limited to 2000 dimensions)
                print(f"   - Creating HNSW indices (dims={dims})")
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.column_table}_hnsw_idx 
                    ON {self.column_table} USING hnsw (embedding vector_cosine_ops)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.table_table}_hnsw_idx 
                    ON {self.table_table} USING hnsw (embedding vector_cosine_ops)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {self.relationship_table}_hnsw_idx 
                    ON {self.relationship_table} USING hnsw (embedding vector_cosine_ops)
                """)
                self.conn.commit()
            except Exception as e:
                self.conn.rollback()  # Rollback to allow subsequent operations
                print(f"   ⚠️ HNSW index creation warning: {e}")
        else:
            # Skip vector index for high dimensions
            # Brute-force search will be used (still fast for small datasets)
            print(f"   - Skipping vector index for dims={dims} (exceeds HNSW 2000 limit)")
            print(f"     Note: Using brute-force search (fast for datasets < 100k rows)")
        
        # 5. 일반 인덱스
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.column_table}_table 
            ON {self.column_table}(table_name)
        """)
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.column_table}_column 
            ON {self.column_table}(column_name)
        """)
        
        # 6. 메타데이터 테이블에 등록
        model_name = EmbeddingConfig.OPENAI_MODEL if self.provider == "openai" else EmbeddingConfig.LOCAL_MODEL
        
        for table_type, table_name in self._get_table_names().items():
            cursor.execute("""
                INSERT INTO embedding_metadata (table_name, embedding_provider, embedding_model, dimensions)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (table_name) DO UPDATE SET
                    embedding_provider = EXCLUDED.embedding_provider,
                    embedding_model = EXCLUDED.embedding_model,
                    dimensions = EXCLUDED.dimensions,
                    updated_at = NOW()
            """, (table_name, self.provider, model_name, self.dimensions))
        
        # 7. 업데이트 트리거 적용
        for table_name in [self.column_table, self.table_table]:
            trigger_name = f"update_{table_name}_updated_at"
            cursor.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
            cursor.execute(f"""
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
            """)
        
        self.conn.commit()
        print(f"   - 테이블 생성/확인 완료 (dimensions: {dims})")
    
    def _get_embedding(self, text: str) -> List[float]:
        """텍스트를 임베딩 벡터로 변환"""
        if self.embedding_model == "openai":
            response = self.embedding_client.embeddings.create(
                model=EmbeddingConfig.OPENAI_MODEL,
                input=text
            )
            return response.data[0].embedding
        else:  # local
            return self.embedding_client.encode(text).tolist()
    
    def build_index(self, ontology_context: Dict[str, Any]):
        """
        온톨로지 기반 계층적 임베딩 생성 및 PostgreSQL 저장
        
        Args:
            ontology_context: 온톨로지 컨텍스트
        """
        if not self.conn or not self.embedding_client:
            raise ValueError("VectorStore not initialized. Call initialize() first.")
        
        cursor = self.conn.cursor()
        
        print(f"\n📚 [VectorDB] 임베딩 생성 중... (테이블: {self._get_table_suffix()})")
        
        # === 1. Table Summary Embedding ===
        print("   - Table Summary 임베딩...")
        table_count = 0
        
        for file_path, tag_info in ontology_context.get("file_tags", {}).items():
            if tag_info.get("type") == "transactional_data":
                table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_").replace("-", "_")
                columns = tag_info.get("columns", [])
                
                # 계층 정보 찾기
                table_level = None
                entity_name = None
                for h in ontology_context.get("hierarchy", []):
                    mapping_table = h.get("mapping_table", "")
                    if mapping_table and table_name in mapping_table:
                        table_level = h["level"]
                        entity_name = h["entity_name"]
                
                # 관계 정보 찾기
                related = []
                for rel in ontology_context.get("relationships", []):
                    if rel["source_table"] == table_name:
                        related.append(f"→ {rel['target_table']} (via {rel['source_column']})")
                    elif rel["target_table"] == table_name:
                        related.append(f"← {rel['source_table']} (via {rel['target_column']})")
                
                # 테이블 요약 텍스트
                table_text = f"""Table: {table_name}
Type: {'Hub Table' if len(related) > 1 else 'Data Table'}
Entity Level: {table_level if table_level else 'Unknown'} ({entity_name if entity_name else 'N/A'})
Columns ({len(columns)}): {', '.join(columns[:15])}{'...' if len(columns) > 15 else ''}
Relationships: {'; '.join(related) if related else 'None'}
Description: Contains {entity_name if entity_name else 'data'} information."""
                
                # 임베딩 생성
                embedding = self._get_embedding(table_text)
                
                # PostgreSQL 저장 (UPSERT)
                cursor.execute(f"""
                    INSERT INTO {self.table_table} (table_name, description, columns_summary, row_count, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (table_name) DO UPDATE SET
                        description = EXCLUDED.description,
                        columns_summary = EXCLUDED.columns_summary,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                """, (
                    table_name,
                    f"Contains {entity_name if entity_name else 'data'} information",
                    ', '.join(columns[:30]),
                    None,
                    embedding
                ))
                
                table_count += 1
        
        print(f"      • {table_count}개 테이블")
        
        # === 2. Column Definition Embedding ===
        print("   - Column Definition 임베딩...")
        col_count = 0
        
        for col_name, definition in ontology_context.get("definitions", {}).items():
            # 풍부한 컨텍스트
            context_text = f"Column: {col_name}\nDefinition: {definition}"
            
            # 계층 정보 추가
            for h in ontology_context.get("hierarchy", []):
                if h.get("anchor_column") == col_name:
                    context_text += f"\nEntity Level: {h['level']} ({h['entity_name']})"
            
            # 어느 테이블에 속하는지
            table_name = None
            for file_path, tag_info in ontology_context.get("file_tags", {}).items():
                if col_name in tag_info.get("columns", []):
                    table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_").replace("-", "_")
                    context_text += f"\nTable: {table_name}"
                    break
            
            # 임베딩 생성
            embedding = self._get_embedding(context_text)
            
            # PostgreSQL 저장 (UPSERT)
            cursor.execute(f"""
                INSERT INTO {self.column_table} (table_name, column_name, description, embedding)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (table_name, column_name) DO UPDATE SET
                    description = EXCLUDED.description,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW()
            """, (
                table_name or 'unknown',
                col_name,
                definition,
                embedding
            ))
            
            col_count += 1
        
        print(f"      • {col_count}개 컬럼 정의")
        
        # === 3. Column Metadata Embedding (NEW) ===
        print("   - Column Metadata 임베딩...")
        meta_count = 0
        
        for table_name, columns in ontology_context.get("column_metadata", {}).items():
            for col_name, col_info in columns.items():
                # 풍부한 메타데이터 텍스트
                meta_text = f"""Column: {col_name}
Full Name: {col_info.get('full_name', col_name)}
Table: {table_name}
Unit: {col_info.get('unit', 'N/A')}
Normal Range: {col_info.get('typical_range', 'N/A')}
Description: {col_info.get('description', '')}
한글 설명: {col_info.get('description_kr', '')}
Data Type: {col_info.get('data_type', 'unknown')}
Keywords: {col_name}, {col_info.get('full_name', '')}, {col_info.get('description_kr', '')}"""
                
                # 임베딩 생성
                embedding = self._get_embedding(meta_text)
                
                # PostgreSQL 저장 (UPSERT)
                cursor.execute(f"""
                    INSERT INTO {self.column_table} 
                    (table_name, column_name, full_name, description, description_kr, unit, typical_range, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (table_name, column_name) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        description = EXCLUDED.description,
                        description_kr = EXCLUDED.description_kr,
                        unit = EXCLUDED.unit,
                        typical_range = EXCLUDED.typical_range,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                """, (
                    table_name,
                    col_name,
                    col_info.get('full_name'),
                    col_info.get('description'),
                    col_info.get('description_kr'),
                    col_info.get('unit'),
                    col_info.get('typical_range'),
                    embedding
                ))
                
                meta_count += 1
        
        print(f"      • {meta_count}개 컬럼 메타데이터")
        
        # === 4. Relationship Embedding ===
        print("   - Relationship 임베딩...")
        rel_count = 0
        
        for rel in ontology_context.get("relationships", []):
            rel_text = f"""Relationship: {rel['source_table']} → {rel['target_table']}
Foreign Key: {rel['source_column']} references {rel['target_column']}
Type: {rel['relation_type']}
Description: {rel.get('description', 'FK relationship')}"""
            
            # 임베딩 생성
            embedding = self._get_embedding(rel_text)
            
            # PostgreSQL 저장 (UPSERT)
            cursor.execute(f"""
                INSERT INTO {self.relationship_table} 
                (source_table, target_table, source_column, target_column, relation_type, description, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_table, target_table, source_column, target_column) DO UPDATE SET
                    relation_type = EXCLUDED.relation_type,
                    description = EXCLUDED.description,
                    embedding = EXCLUDED.embedding
            """, (
                rel["source_table"],
                rel["target_table"],
                rel.get("source_column"),
                rel.get("target_column"),
                rel["relation_type"],
                rel.get('description', 'FK relationship'),
                embedding
            ))
            
            rel_count += 1
        
        print(f"      • {rel_count}개 관계")
        
        # 커밋
        self.conn.commit()
        
        total_embeddings = table_count + col_count + meta_count + rel_count
        print(f"\n✅ VectorDB 구축 완료: {total_embeddings}개 임베딩")
        print(f"   - Table: {table_count}개")
        print(f"   - Column Definition: {col_count}개")
        print(f"   - Column Metadata: {meta_count}개")
        print(f"   - Relationship: {rel_count}개")
        print(f"   - 저장 위치: {self._get_table_suffix()} 테이블들")
    
    def semantic_search(
        self, 
        query: str, 
        n_results: int = 10,
        filter_type: Optional[str] = None
    ) -> List[Dict]:
        """
        시맨틱 검색
        
        Args:
            query: 검색 쿼리
            n_results: 결과 개수
            filter_type: 필터 타입 ("table", "column", "relationship" 또는 None)
        
        Returns:
            검색 결과 리스트
        """
        if not self.conn or not self.embedding_client:
            raise ValueError("VectorStore not initialized")
        
        # 쿼리 임베딩 생성
        query_embedding = self._get_embedding(query)
        
        cursor = self.conn.cursor()
        results = []
        
        # 테이블별로 검색 (동적 테이블명 사용)
        if filter_type is None or filter_type == "column":
            cursor.execute(f"""
                SELECT table_name, column_name, full_name, description, description_kr, 
                       unit, typical_range,
                       1 - (embedding <=> %s::vector) as similarity
                FROM {self.column_table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, n_results))
            
            for row in cursor.fetchall():
                results.append({
                    "type": "column",
                    "table_name": row[0],
                    "column_name": row[1],
                    "full_name": row[2],
                    "description": row[3],
                    "description_kr": row[4],
                    "unit": row[5],
                    "typical_range": row[6],
                    "similarity": float(row[7]) if row[7] else 0
                })
        
        if filter_type is None or filter_type == "table":
            cursor.execute(f"""
                SELECT table_name, description, columns_summary,
                       1 - (embedding <=> %s::vector) as similarity
                FROM {self.table_table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, n_results))
            
            for row in cursor.fetchall():
                results.append({
                    "type": "table",
                    "table_name": row[0],
                    "description": row[1],
                    "columns_summary": row[2],
                    "similarity": float(row[3]) if row[3] else 0
                })
        
        if filter_type is None or filter_type == "relationship":
            cursor.execute(f"""
                SELECT source_table, target_table, source_column, target_column, 
                       relation_type, description,
                       1 - (embedding <=> %s::vector) as similarity
                FROM {self.relationship_table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, n_results))
            
            for row in cursor.fetchall():
                results.append({
                    "type": "relationship",
                    "source_table": row[0],
                    "target_table": row[1],
                    "source_column": row[2],
                    "target_column": row[3],
                    "relation_type": row[4],
                    "description": row[5],
                    "similarity": float(row[6]) if row[6] else 0
                })
        
        # similarity 기준 정렬
        results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        
        return results[:n_results]
    
    def get_stats(self) -> Dict[str, int]:
        """임베딩 통계 조회"""
        if not self.conn:
            return {}
        
        cursor = self.conn.cursor()
        stats = {}
        
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {self.column_table}")
            stats["columns"] = cursor.fetchone()[0]
        except:
            stats["columns"] = 0
        
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {self.table_table}")
            stats["tables"] = cursor.fetchone()[0]
        except:
            stats["tables"] = 0
        
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {self.relationship_table}")
            stats["relationships"] = cursor.fetchone()[0]
        except:
            stats["relationships"] = 0
        
        stats["total"] = stats["columns"] + stats["tables"] + stats["relationships"]
        stats["provider"] = self.provider
        stats["dimensions"] = self.dimensions
        
        return stats
    
    def list_available_models(self) -> List[Dict]:
        """사용 가능한 임베딩 모델/테이블 목록 조회"""
        if not self.conn:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT DISTINCT embedding_provider, embedding_model, dimensions, 
                   COUNT(*) as table_count
            FROM embedding_metadata
            GROUP BY embedding_provider, embedding_model, dimensions
            ORDER BY dimensions DESC
        """)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "provider": row[0],
                "model": row[1],
                "dimensions": row[2],
                "table_count": row[3]
            })
        
        return results
