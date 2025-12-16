# src/knowledge/vector_store.py
"""
VectorDB 관리 (ChromaDB)

온톨로지 기반 계층적 임베딩 및 Hybrid Search
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path

from config import EmbeddingConfig, LLMConfig


class VectorStore:
    """
    ChromaDB 기반 VectorDB 관리
    
    전문가 피드백 반영:
    - 계층적 임베딩 (Table + Column + Relationship)
    - Hybrid Search (Keyword + Vector)
    - 확장성 고려 (임베딩 모델 교체 가능)
    """
    
    def __init__(self, db_path: str = "data/processed/vector_db"):
        """
        Args:
            db_path: ChromaDB 저장 경로
        """
        self.db_path = Path(db_path)
        self.client = None
        self.collection = None
        
        # ChromaDB import (선택적)
        try:
            import chromadb
            self.chromadb = chromadb
        except ImportError:
            print("⚠️ ChromaDB가 설치되지 않았습니다. pip install chromadb")
            self.chromadb = None
    
    def initialize(self, embedding_model: str = None):
        """
        ChromaDB 초기화
        
        Args:
            embedding_model: "openai" 또는 "local" (None이면 config에서 가져옴)
        """
        if not self.chromadb:
            raise ImportError("ChromaDB not installed")
        
        # config에서 기본값 가져오기
        if embedding_model is None:
            embedding_model = EmbeddingConfig.PROVIDER
        
        # Persistent client
        self.client = self.chromadb.PersistentClient(path=str(self.db_path))
        
        # 임베딩 함수 선택 (config에서 모델명 가져옴)
        if embedding_model == "openai":
            from chromadb.utils import embedding_functions
            model_name = EmbeddingConfig.OPENAI_MODEL
            embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=LLMConfig.OPENAI_API_KEY,
                model_name=model_name
            )
        elif embedding_model == "local":
            from chromadb.utils import embedding_functions
            model_name = EmbeddingConfig.LOCAL_MODEL
            embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_name
            )
        else:
            raise ValueError(f"Unknown embedding model: {embedding_model}")
        
        # 컬렉션 생성 또는 로드
        self.collection = self.client.get_or_create_collection(
            name="medical_ontology",
            embedding_function=embedding_fn,
            metadata={"description": "Medical data ontology for semantic search"}
        )
        
        print(f"✅ VectorDB 초기화 완료: {self.db_path}")
        print(f"   - 임베딩 Provider: {embedding_model}")
        print(f"   - 모델: {model_name}")
    
    def build_index(self, ontology_context: Dict[str, Any]):
        """
        온톨로지 기반 계층적 임베딩 생성
        
        전문가 피드백:
        - Table Summary Embedding (라우팅용)
        - Column Definition Embedding (매핑용)
        - Relationship Embedding (JOIN용)
        
        Args:
            ontology_context: 온톨로지 컨텍스트
        """
        if not self.collection:
            raise ValueError("VectorStore not initialized. Call initialize() first.")
        
        documents = []
        metadatas = []
        ids = []
        
        print("\n📚 [VectorDB] 임베딩 생성 중...")
        
        # === 1. Table Summary Embedding (신규) ===
        print("   - Table Summary 임베딩...")
        
        table_count = 0
        for file_path, tag_info in ontology_context.get("file_tags", {}).items():
            if tag_info.get("type") == "transactional_data":
                table_name = os.path.basename(file_path).replace(".csv", "")
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
                
                documents.append(table_text)
                metadatas.append({
                    "type": "table_summary",
                    "table_name": table_name,
                    "level": table_level,
                    "num_columns": len(columns)
                })
                ids.append(f"table_{table_name}")
                table_count += 1
        
        print(f"      • {table_count}개 테이블")
        
        # === 2. Column Definition Embedding ===
        print("   - Column Definition 임베딩...")
        
        col_count = 0
        for col_name, definition in ontology_context.get("definitions", {}).items():
            # 풍부한 컨텍스트
            context_text = f"Column: {col_name}\n{definition}"
            
            # 계층 정보 추가
            for h in ontology_context.get("hierarchy", []):
                if h.get("anchor_column") == col_name:
                    context_text += f"\nEntity Level: {h['level']} ({h['entity_name']})"
            
            # 어느 테이블에 속하는지
            for file_path, tag_info in ontology_context.get("file_tags", {}).items():
                if col_name in tag_info.get("columns", []):
                    table = os.path.basename(file_path).replace(".csv", "")
                    context_text += f"\nTable: {table}"
                    break
            
            documents.append(context_text)
            metadatas.append({
                "type": "column_definition",
                "column_name": col_name
            })
            ids.append(f"col_{col_name}")
            col_count += 1
        
        print(f"      • {col_count}개 컬럼")
        
        # === 3. Relationship Embedding ===
        print("   - Relationship 임베딩...")
        
        rel_count = 0
        for rel in ontology_context.get("relationships", []):
            rel_text = f"""Relationship: {rel['source_table']} → {rel['target_table']}
Foreign Key: {rel['source_column']} references {rel['target_column']}
Type: {rel['relation_type']}
Description: {rel['description']}"""
            
            documents.append(rel_text)
            metadatas.append({
                "type": "relationship",
                "source": rel["source_table"],
                "target": rel["target_table"]
            })
            ids.append(f"rel_{rel['source_table']}_{rel['target_table']}")
            rel_count += 1
        
        print(f"      • {rel_count}개 관계")
        
        # === 4. 벡터 저장 ===
        print(f"\n💾 [VectorDB] 임베딩 저장 중...")
        
        if documents:
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            
            total_embeddings = len(documents)
            print(f"✅ VectorDB 구축 완료: {total_embeddings}개 임베딩")
            print(f"   - Table: {table_count}개")
            print(f"   - Column: {col_count}개")
            print(f"   - Relationship: {rel_count}개")
            
            # 확장성 메모
            print(f"\n💡 [확장성] 향후 최적화 가능:")
            print(f"   - 임베딩 모델 교체 (OpenAI → Local)")
            print(f"   - Re-ranking 추가")
            print(f"   - Hybrid Search 고도화")
        else:
            print("⚠️ 임베딩할 문서 없음")
    
    def semantic_search(
        self, 
        query: str, 
        n_results: int = 5,
        filter_type: Optional[str] = None
    ) -> List[Dict]:
        """
        시맨틱 검색 (Hybrid Search)
        
        Args:
            query: 검색 쿼리
            n_results: 결과 개수
            filter_type: 필터 타입 ("table", "column", "relationship" 또는 None)
        
        Returns:
            검색 결과 리스트
        """
        if not self.collection:
            raise ValueError("VectorStore not initialized")
        
        # 메타데이터 필터
        where_filter = {"type": filter_type} if filter_type else None
        
        # 벡터 검색
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter
        )
        
        # 결과 포맷팅
        formatted_results = []
        if results and results['documents'] and results['documents'][0]:
            for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
                formatted_results.append({
                    "document": doc,
                    "metadata": meta
                })
        
        return formatted_results
    
    def assemble_context(
        self,
        search_results: List[Dict],
        ontology_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        검색 결과 조립 (LLM 전달용)
        
        검색된 컬럼 + 해당 테이블 + 관련 관계를 묶어서 반환
        
        Args:
            search_results: semantic_search() 결과
            ontology_context: 온톨로지 컨텍스트
        
        Returns:
            조립된 컨텍스트
        """
        assembled = {
            "primary_results": [],
            "related_tables": set(),
            "join_paths": []
        }
        
        for result in search_results:
            doc = result["document"]
            meta = result["metadata"]
            result_type = meta.get("type")
            
            if result_type == "column_definition":
                col_name = meta.get("column_name")
                
                # 이 컬럼이 속한 테이블 찾기
                for file_path, tag_info in ontology_context.get("file_tags", {}).items():
                    if col_name in tag_info.get("columns", []):
                        table_name = os.path.basename(file_path).replace(".csv", "")
                        assembled["related_tables"].add(table_name)
                        
                        # 관련 관계 찾기
                        for rel in ontology_context.get("relationships", []):
                            if rel["source_table"] == table_name or rel["target_table"] == table_name:
                                join_path = f"{rel['source_table']}.{rel['source_column']} = {rel['target_table']}.{rel['target_column']}"
                                if join_path not in assembled["join_paths"]:
                                    assembled["join_paths"].append(join_path)
            
            elif result_type == "table_summary":
                table_name = meta.get("table_name")
                assembled["related_tables"].add(table_name)
            
            assembled["primary_results"].append({
                "document": doc,
                "metadata": meta
            })
        
        # Set을 리스트로 변환
        assembled["related_tables"] = list(assembled["related_tables"])
        
        return assembled

