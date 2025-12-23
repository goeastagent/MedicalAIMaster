# src/knowledge/vector_store.py
"""
VectorDB 검색 클래스 (PostgreSQL pgvector 기반)

Dynamic Schema: 현재 설정된 임베딩 모델에 맞는 테이블 참조
- 모델별 테이블명: {base_name}_{provider}_{dimensions}
- 모델 변경 시 해당 테이블 자동 참조
"""

from typing import List, Dict, Any, Optional
from ExtractionAgent.src.config import Config, EmbeddingConfig


class VectorStoreReader:
    """
    PostgreSQL pgvector 기반 시맨틱 검색 (읽기 전용, Dynamic Schema)
    
    IndexingAgent가 저장한 임베딩을 검색합니다.
    현재 설정된 임베딩 모델에 맞는 테이블을 자동으로 참조합니다.
    """
    
    def __init__(self):
        """초기화"""
        self.conn = None
        self.embedding_client = None
        self.embedding_model = None
        self.dimensions = None
        self.provider = None
        self._initialized = False
        
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
        
        # 차원 설정
        if embedding_model == "openai":
            self.dimensions = EmbeddingConfig.OPENAI_DIMENSIONS
        else:
            self.dimensions = EmbeddingConfig.LOCAL_DIMENSIONS
        
        # 테이블명 설정
        table_names = self._get_table_names()
        self.column_table = table_names["column"]
        self.table_table = table_names["table"]
        self.relationship_table = table_names["relationship"]
        
        # 1. PostgreSQL 연결
        try:
            import psycopg2
            self.conn = psycopg2.connect(
                host=Config.POSTGRES_HOST,
                port=Config.POSTGRES_PORT,
                dbname=Config.POSTGRES_DB,
                user=Config.POSTGRES_USER,
                password=Config.POSTGRES_PASSWORD
            )
            print(f"✅ [VectorStore] PostgreSQL 연결 완료")
        except Exception as e:
            print(f"⚠️ [VectorStore] PostgreSQL 연결 실패: {e}")
            return
        
        # 2. 임베딩 클라이언트 초기화
        if embedding_model == "openai":
            try:
                from openai import OpenAI
                self.embedding_client = OpenAI(api_key=Config.OPENAI_API_KEY)
                print(f"✅ [VectorStore] OpenAI 임베딩 클라이언트 ({EmbeddingConfig.OPENAI_MODEL})")
            except Exception as e:
                print(f"⚠️ [VectorStore] OpenAI 클라이언트 초기화 실패: {e}")
                return
        elif embedding_model == "local":
            try:
                from sentence_transformers import SentenceTransformer
                self.embedding_client = SentenceTransformer(EmbeddingConfig.LOCAL_MODEL)
                print(f"✅ [VectorStore] Local 임베딩 모델 ({EmbeddingConfig.LOCAL_MODEL})")
            except Exception as e:
                print(f"⚠️ [VectorStore] Local 임베딩 모델 로드 실패: {e}")
                return
        
        # 3. pgvector 테이블 확인
        if not self._verify_tables():
            print(f"⚠️ [VectorStore] 테이블 없음 ({self._get_table_suffix()}) - 시맨틱 검색 비활성화")
            print(f"   → IndexingAgent에서 build_vector_db.py 실행 필요")
            return
        
        self._initialized = True
        print(f"✅ [VectorStore] 초기화 완료")
        print(f"   - Provider: {embedding_model}")
        print(f"   - Dimensions: {self.dimensions}")
        print(f"   - Tables: {self._get_table_suffix()}")
    
    def _verify_tables(self) -> bool:
        """현재 모델에 맞는 pgvector 테이블 존재 확인"""
        if not self.conn:
            return False
        
        try:
            cursor = self.conn.cursor()
            
            # pgvector 확장 확인
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname='vector'")
            if not cursor.fetchone():
                print(f"   ⚠️ pgvector 확장 미설치")
                return False
            
            # 현재 모델에 맞는 column_embeddings 테이블 확인
            cursor.execute("""
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema='public' AND table_name=%s
            """, (self.column_table,))
            
            if not cursor.fetchone():
                print(f"   ⚠️ 테이블 없음: {self.column_table}")
                return False
            
            return True
        except Exception as e:
            print(f"   ⚠️ 테이블 확인 중 오류: {e}")
            return False
    
    def is_available(self) -> bool:
        """VectorStore 사용 가능 여부"""
        return self._initialized
    
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
    
    def semantic_search(
        self, 
        query: str, 
        n_results: int = 10,
        filter_type: Optional[str] = None,
        min_similarity: float = 0.3
    ) -> List[Dict]:
        """
        시맨틱 검색
        
        Args:
            query: 검색 쿼리
            n_results: 결과 개수
            filter_type: 필터 타입 ("table", "column", "relationship" 또는 None)
            min_similarity: 최소 유사도 (이 값 미만은 제외)
        
        Returns:
            검색 결과 리스트
        """
        if not self._initialized:
            return []
        
        # 쿼리 임베딩 생성
        query_embedding = self._get_embedding(query)
        
        cursor = self.conn.cursor()
        results = []
        
        # 컬럼 검색 (동적 테이블명 사용)
        if filter_type is None or filter_type == "column":
            cursor.execute(f"""
                SELECT table_name, column_name, full_name, description, description_kr, 
                       unit, typical_range,
                       1 - (embedding <=> %s::vector) as similarity
                FROM {self.column_table}
                WHERE 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """, (query_embedding, query_embedding, min_similarity, query_embedding, n_results))
            
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
        
        # 테이블 검색
        if filter_type is None or filter_type == "table":
            try:
                cursor.execute(f"""
                    SELECT table_name, description, columns_summary,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM {self.table_table}
                    WHERE 1 - (embedding <=> %s::vector) >= %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (query_embedding, query_embedding, min_similarity, query_embedding, n_results))
                
                for row in cursor.fetchall():
                    results.append({
                        "type": "table",
                        "table_name": row[0],
                        "description": row[1],
                        "columns_summary": row[2],
                        "similarity": float(row[3]) if row[3] else 0
                    })
            except:
                pass  # 테이블이 없을 수 있음
        
        # 관계 검색
        if filter_type is None or filter_type == "relationship":
            try:
                cursor.execute(f"""
                    SELECT source_table, target_table, source_column, target_column, 
                           relation_type, description,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM {self.relationship_table}
                    WHERE 1 - (embedding <=> %s::vector) >= %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, (query_embedding, query_embedding, min_similarity, query_embedding, n_results))
                
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
            except:
                pass  # 테이블이 없을 수 있음
        
        # similarity 기준 정렬
        results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
        
        return results[:n_results]
    
    def search_columns(self, query: str, n_results: int = 10) -> List[Dict]:
        """컬럼만 검색"""
        return self.semantic_search(query, n_results, filter_type="column")
    
    def search_tables(self, query: str, n_results: int = 5) -> List[Dict]:
        """테이블만 검색"""
        return self.semantic_search(query, n_results, filter_type="table")
    
    def get_current_model_info(self) -> Dict[str, Any]:
        """현재 사용 중인 모델 정보 반환"""
        return {
            "provider": self.provider,
            "dimensions": self.dimensions,
            "tables_suffix": self._get_table_suffix() if self._initialized else None,
            "initialized": self._initialized
        }
    
    def list_available_models(self) -> List[Dict]:
        """DB에 저장된 임베딩 모델/테이블 목록 조회"""
        if not self.conn:
            return []
        
        try:
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
        except:
            return []
    
    def format_search_results_for_prompt(self, results: List[Dict]) -> str:
        """검색 결과를 프롬프트용으로 포맷팅"""
        if not results:
            return ""
        
        lines = []
        lines.append("=" * 80)
        lines.append(f"SEMANTIC SEARCH RESULTS (Model: {self._get_table_suffix()})")
        lines.append("=" * 80)
        lines.append("")
        
        for i, result in enumerate(results, 1):
            result_type = result.get("type", "unknown")
            similarity = result.get("similarity", 0)
            
            if result_type == "column":
                col_name = result.get("column_name", "?")
                full_name = result.get("full_name", col_name)
                table_name = result.get("table_name", "?")
                unit = result.get("unit", "")
                typical_range = result.get("typical_range", "")
                
                line = f"{i}. [Column] {table_name}.{col_name}"
                if full_name and full_name != col_name:
                    line += f" ({full_name})"
                if unit:
                    line += f" [{unit}]"
                if typical_range:
                    line += f" (range: {typical_range})"
                line += f" - similarity: {similarity:.2%}"
                
                lines.append(line)
                
                if result.get("description"):
                    lines.append(f"      {result['description'][:100]}")
            
            elif result_type == "table":
                table_name = result.get("table_name", "?")
                lines.append(f"{i}. [Table] {table_name} - similarity: {similarity:.2%}")
                if result.get("columns_summary"):
                    lines.append(f"      Columns: {result['columns_summary'][:80]}...")
            
            elif result_type == "relationship":
                lines.append(
                    f"{i}. [Relationship] {result['source_table']}.{result['source_column']} "
                    f"→ {result['target_table']}.{result['target_column']} - similarity: {similarity:.2%}"
                )
        
        lines.append("")
        return "\n".join(lines)


# 싱글톤 인스턴스
_vector_store_reader = None

def get_vector_store_reader() -> VectorStoreReader:
    """VectorStoreReader 싱글톤 반환"""
    global _vector_store_reader
    if _vector_store_reader is None:
        _vector_store_reader = VectorStoreReader()
        _vector_store_reader.initialize()
    return _vector_store_reader
