# src/agents/base/mixins.py
"""
Mixins for agent nodes

Provides reusable functionality:
- LLMMixin: LLM client integration with retry logic
- DatabaseMixin: Database connection management
- LoggingMixin: Enhanced logging capabilities
- Neo4jMixin: Neo4j graph database connection management
"""

from typing import Dict, Any, Optional, List, Type
from pydantic import BaseModel


# =============================================================================
# LLMMixin
# =============================================================================

class LLMMixin:
    """
    LLM 호출 기능 제공
    
    사용법:
        class MyNode(BaseNode, LLMMixin):
            requires_llm = True
            
            def execute(self, state):
                response = self.call_llm(prompt, max_tokens=2000)
                return {"result": response}
    """
    
    _llm_client = None
    
    @property
    def llm_client(self):
        """LLM 클라이언트 (lazy initialization)"""
        if self._llm_client is None:
            from shared.llm import get_llm_client
            self._llm_client = get_llm_client()
        return self._llm_client
    
    def call_llm(
        self,
        prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.1,
        system_prompt: Optional[str] = None
    ) -> Optional[str]:
        """
        LLM 호출 (텍스트 응답)
        
        Args:
            prompt: 사용자 프롬프트
            max_tokens: 최대 토큰 수
            temperature: 온도 (0.0 ~ 1.0)
            system_prompt: 시스템 프롬프트 (선택)
            
        Returns:
            LLM 응답 텍스트 또는 None
        """
        try:
            return self.llm_client.ask(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt
            )
        except Exception as e:
            if hasattr(self, 'log'):
                self.log(f"LLM call failed: {e}", "❌")
            return None
    
    def call_llm_json(
        self,
        prompt: str,
        max_tokens: int = 4000,
        temperature: float = 0.1,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        LLM 호출 (JSON 응답)
        
        Args:
            prompt: 사용자 프롬프트
            max_tokens: 최대 토큰 수
            temperature: 온도
            max_retries: 최대 재시도 횟수
            retry_delay: 재시도 대기 시간 (초)
            
        Returns:
            파싱된 JSON dict 또는 None
        """
        import time
        
        for attempt in range(max_retries):
            try:
                # Note: ask_json() doesn't support temperature parameter
                response = self.llm_client.ask_json(
                    prompt,
                    max_tokens=max_tokens
                )
                
                if response is not None:
                    return response
                    
            except Exception as e:
                if hasattr(self, 'log'):
                    self.log(f"LLM JSON call failed (attempt {attempt + 1}): {e}", "⚠️")
                    
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        
        return None
    
    def call_llm_with_schema(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        max_tokens: int = 4000,
        temperature: float = 0.1,
        max_retries: int = 3
    ) -> Optional[BaseModel]:
        """
        LLM 호출 후 Pydantic 모델로 파싱
        
        Args:
            prompt: 사용자 프롬프트
            response_model: Pydantic 모델 클래스
            max_tokens: 최대 토큰 수
            temperature: 온도
            max_retries: 최대 재시도 횟수
            
        Returns:
            Pydantic 모델 인스턴스 또는 None
        """
        response = self.call_llm_json(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries
        )
        
        if response is None:
            return None
        
        try:
            return response_model.model_validate(response)
        except Exception as e:
            if hasattr(self, 'log'):
                self.log(f"Failed to parse LLM response to {response_model.__name__}: {e}", "❌")
            return None


# =============================================================================
# DatabaseMixin
# =============================================================================

class DatabaseMixin:
    """
    데이터베이스 연결 관리 및 Repository 접근
    
    사용법:
        class MyNode(BaseNode, DatabaseMixin):
            def execute(self, state):
                # Repository 사용 (권장)
                files = self.file_repo.get_data_files_with_details()
                params = self.parameter_repo.get_parameters_by_concept()
                
                # 직접 쿼리 사용 (비권장, 복잡한 쿼리에만)
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT ...")
    """
    
    _db_manager = None
    
    # Repository 캐시 (lazy initialization)
    _file_repo = None
    _column_repo = None
    _parameter_repo = None
    _dictionary_repo = None
    _entity_repo = None
    _ontology_repo = None
    _directory_repo = None
    
    @property
    def db_manager(self):
        """DB 매니저 (lazy initialization)"""
        if self._db_manager is None:
            from shared.database import get_db_manager
            self._db_manager = get_db_manager()
        return self._db_manager
    
    # =========================================================================
    # Repository Properties (Lazy Initialization)
    # =========================================================================
    
    @property
    def file_repo(self):
        """FileRepository 인스턴스"""
        if self._file_repo is None:
            from shared.database.repositories import FileRepository
            self._file_repo = FileRepository(self.db_manager)
        return self._file_repo
    
    @property
    def column_repo(self):
        """ColumnRepository 인스턴스"""
        if self._column_repo is None:
            from shared.database.repositories import ColumnRepository
            self._column_repo = ColumnRepository(self.db_manager)
        return self._column_repo
    
    @property
    def parameter_repo(self):
        """ParameterRepository 인스턴스"""
        if self._parameter_repo is None:
            from shared.database.repositories import ParameterRepository
            self._parameter_repo = ParameterRepository(self.db_manager)
        return self._parameter_repo
    
    @property
    def dictionary_repo(self):
        """DictionaryRepository 인스턴스"""
        if self._dictionary_repo is None:
            from shared.database.repositories import DictionaryRepository
            self._dictionary_repo = DictionaryRepository(self.db_manager)
        return self._dictionary_repo
    
    @property
    def entity_repo(self):
        """EntityRepository 인스턴스"""
        if self._entity_repo is None:
            from shared.database.repositories import EntityRepository
            self._entity_repo = EntityRepository(self.db_manager)
        return self._entity_repo
    
    @property
    def ontology_repo(self):
        """OntologyRepository 인스턴스"""
        if self._ontology_repo is None:
            from shared.database.repositories import OntologyRepository
            self._ontology_repo = OntologyRepository(self.db_manager)
        return self._ontology_repo
    
    @property
    def directory_repo(self):
        """DirectoryRepository 인스턴스"""
        if self._directory_repo is None:
            from shared.database.repositories import DirectoryRepository
            self._directory_repo = DirectoryRepository(self.db_manager)
        return self._directory_repo
    
    # =========================================================================
    # Database Connection
    # =========================================================================
    
    def get_connection(self):
        """
        데이터베이스 연결 획득
        
        Returns:
            psycopg2 connection
        """
        return self.db_manager.get_connection()
    
    def execute_query(
        self,
        query: str,
        params: tuple = None,
        fetch: str = "all"
    ) -> Optional[List[Any]]:
        """
        쿼리 실행 헬퍼
        
        Args:
            query: SQL 쿼리
            params: 쿼리 파라미터
            fetch: "all", "one", "none" 중 하나
            
        Returns:
            쿼리 결과
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(query, params)
            
            if fetch == "all":
                return cursor.fetchall()
            elif fetch == "one":
                return cursor.fetchone()
            else:
                conn.commit()
                return None
                
        except Exception as e:
            conn.rollback()
            if hasattr(self, 'log'):
                self.log(f"Query failed: {e}", "❌")
            raise
    
    def execute_many(
        self,
        query: str,
        params_list: List[tuple]
    ) -> int:
        """
        여러 행 삽입/업데이트
        
        Args:
            query: SQL 쿼리
            params_list: 파라미터 목록
            
        Returns:
            처리된 행 수
        """
        if not params_list:
            return 0
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.executemany(query, params_list)
            conn.commit()
            return len(params_list)
        except Exception as e:
            conn.rollback()
            if hasattr(self, 'log'):
                self.log(f"Batch query failed: {e}", "❌")
            raise


# =============================================================================
# LoggingMixin
# =============================================================================

class LoggingMixin:
    """
    향상된 로깅 기능
    
    BaseNode에 기본 log() 메서드가 있지만,
    이 Mixin은 추가 기능을 제공합니다.
    """
    
    _log_buffer: List[str] = []
    _verbose: bool = True
    
    def set_verbose(self, verbose: bool):
        """로깅 출력 여부 설정"""
        self._verbose = verbose
    
    def log_section(self, title: str):
        """섹션 헤더 출력"""
        msg = f"\n--- {title} ---"
        self._log_buffer.append(msg)
        if self._verbose:
            print(msg)
    
    def log_progress(self, current: int, total: int, message: str = ""):
        """진행률 로깅"""
        pct = (current / total * 100) if total > 0 else 0
        msg = f"   [{current}/{total}] ({pct:.0f}%) {message}"
        if self._verbose:
            print(msg, end='\r')
    
    def log_stats(self, stats: Dict[str, Any], title: str = "Statistics"):
        """통계 출력"""
        lines = [f"\n📊 {title}:"]
        for key, value in stats.items():
            if isinstance(value, float):
                lines.append(f"   {key}: {value:.2f}")
            else:
                lines.append(f"   {key}: {value}")
        
        msg = "\n".join(lines)
        self._log_buffer.append(msg)
        if self._verbose:
            print(msg)
    
    def log_table(self, headers: List[str], rows: List[List[Any]], max_rows: int = 10):
        """테이블 형태 출력"""
        if not rows:
            return
        
        # 컬럼 너비 계산
        widths = [len(h) for h in headers]
        for row in rows[:max_rows]:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))
        
        # 헤더
        header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
        separator = "-+-".join("-" * w for w in widths)
        
        lines = [header_line, separator]
        
        # 행
        for row in rows[:max_rows]:
            line = " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))
            lines.append(line)
        
        if len(rows) > max_rows:
            lines.append(f"... and {len(rows) - max_rows} more rows")
        
        msg = "\n".join(lines)
        self._log_buffer.append(msg)
        if self._verbose:
            print(msg)
    
    def get_log_buffer(self) -> List[str]:
        """누적된 로그 반환"""
        return list(self._log_buffer)
    
    def clear_log_buffer(self):
        """로그 버퍼 초기화"""
        self._log_buffer = []


# =============================================================================
# Neo4jMixin
# =============================================================================

class Neo4jMixin:
    """
    Neo4j 그래프 데이터베이스 연결 관리
    
    사용법:
        class MyNode(BaseNode, Neo4jMixin):
            def execute(self, state):
                driver = self.neo4j_driver
                if driver:
                    with driver.session(database=Neo4jConfig.DATABASE) as session:
                        session.run("MATCH ...")
                
                # 작업 완료 후 드라이버 정리 (선택적)
                self.close_neo4j()
    """
    
    _neo4j_driver = None
    
    @property
    def neo4j_driver(self):
        """
        Neo4j 드라이버 (lazy initialization)
        
        Returns:
            neo4j.Driver 인스턴스 또는 None (연결 실패 시)
        """
        if self._neo4j_driver is None:
            try:
                from neo4j import GraphDatabase
                from shared.config import Neo4jConfig
                
                self._neo4j_driver = GraphDatabase.driver(
                    Neo4jConfig.URI,
                    auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
                )
                self._neo4j_driver.verify_connectivity()
            except Exception as e:
                if hasattr(self, 'log'):
                    self.log(f"Neo4j connection failed: {e}", "⚠️", indent=1)
                return None
        return self._neo4j_driver
    
    def close_neo4j(self):
        """
        Neo4j 드라이버 연결 종료
        
        노드 실행 완료 후 명시적으로 호출하거나,
        finally 블록에서 호출하여 리소스 정리
        """
        if self._neo4j_driver is not None:
            try:
                self._neo4j_driver.close()
            except Exception:
                pass
            self._neo4j_driver = None
    
    def neo4j_session(self, database: Optional[str] = None):
        """
        Neo4j 세션 컨텍스트 매니저
        
        Args:
            database: 데이터베이스 이름 (None이면 Config에서 읽음)
        
        Returns:
            세션 컨텍스트 매니저 또는 None
            
        Usage:
            with self.neo4j_session() as session:
                session.run("MATCH ...")
        """
        driver = self.neo4j_driver
        if driver is None:
            return None
        
        from shared.config import Neo4jConfig
        db_name = database or Neo4jConfig.DATABASE
        return driver.session(database=db_name)
