# shared/langgraph/base_node.py
"""
BaseNode - Abstract base class for all LangGraph pipeline nodes

All nodes in ExtractionAgent, IndexingAgent, and other LangGraph-based pipelines
should inherit from this class.

Provides:
- Standard execution flow with timing
- Error handling
- Logging interface (via logging module)
- LangGraph compatibility via __call__

Usage:
    from shared.langgraph import BaseNode, register_node
    
    @register_node
    class MyNode(BaseNode):
        name = "my_node"
        description = "My custom node"
        order = 100
        requires_llm = True
        requires_db = True
        
        def execute(self, state):
            # Your logic here
            return {"result": ...}
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime


def _get_node_logger(node_name: str) -> logging.Logger:
    """Get logger for a specific node."""
    return logging.getLogger(f"LangGraph.{node_name}")


class BaseNode(ABC):
    """
    모든 노드가 상속받는 추상 클래스
    
    서브클래스에서 정의해야 할 것:
    - name: 노드 고유 이름 (예: "query_understanding", "directory_catalog")
    - description: 노드 설명
    - order: 실행 순서 (낮을수록 먼저 실행)
    - execute(): 실제 로직
    
    선택적 속성:
    - requires_llm: LLM 사용 여부 (기본: False)
    - requires_db: DB 접근 여부 (기본: False)
    - enabled: 활성화 여부 (기본: True)
    
    Example:
        @register_node
        class QueryUnderstandingNode(BaseNode):
            name = "query_understanding"
            description = "동적 컨텍스트 로딩 + 쿼리 분석"
            order = 100
            requires_llm = True
            requires_db = True
            
            def execute(self, state):
                # 로직
                return {"schema_context": ..., "intent": ...}
    """
    
    # === 메타데이터 (서브클래스에서 오버라이드) ===
    name: str = "base"                    # 노드 고유 이름
    description: str = ""                 # 노드 설명
    order: int = 0                        # 실행 순서 (낮을수록 먼저)
    requires_llm: bool = False            # LLM 사용 여부
    requires_db: bool = False             # DB 접근 여부
    enabled: bool = True                  # 활성화 여부
    
    def __init__(self):
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self._logs: List[str] = []
        self._logger: Optional[logging.Logger] = None
    
    @property
    def logger(self) -> logging.Logger:
        """Get logger for this node."""
        if self._logger is None:
            self._logger = _get_node_logger(self.name)
        return self._logger
    
    @property
    def node_id(self) -> str:
        """노드 고유 ID (name과 동일)"""
        return self.name
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """실행 시간 (초)"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    # =========================================================================
    # Abstract Method
    # =========================================================================
    
    @abstractmethod
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        노드 실행 로직 (서브클래스에서 구현)
        
        Args:
            state: LangGraph state dict
            
        Returns:
            업데이트할 상태 dict
            (LangGraph가 기존 state와 merge함)
        """
        pass
    
    # =========================================================================
    # LangGraph Interface
    # =========================================================================
    
    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        LangGraph에서 노드 호출 시 사용
        
        - 시작/종료 시간 기록
        - 에러 핸들링
        - 로그 수집
        """
        self.started_at = datetime.now()
        self._logs = []
        
        try:
            self._log_start()
            result = self.execute(state)
            self._log_complete()
            
            # logs 필드가 없으면 추가
            if "logs" not in result:
                result["logs"] = []
            result["logs"].extend(self._logs)
            
            return result
            
        except Exception as e:
            self.completed_at = datetime.now()
            return self._handle_error(state, e)
    
    # =========================================================================
    # Logging
    # =========================================================================
    
    def log(self, message: str, emoji: str = "", indent: int = 0, level: int = logging.INFO):
        """
        로그 메시지 추가
        
        Args:
            message: 로그 메시지
            emoji: 접두사 이모지 (선택)
            indent: 들여쓰기 레벨 (0=없음, 1=3칸, 2=6칸, ...)
            level: 로그 레벨 (logging.DEBUG, INFO, WARNING, ERROR)
        """
        indent_str = "   " * indent
        prefix = f"{emoji} " if emoji else ""
        log_entry = f"{indent_str}{prefix}{message}"
        
        # 내부 로그 리스트에 추가
        self._logs.append(f"[{self.name}] {message}")
        
        # logging 모듈로 출력
        self.logger.log(level, log_entry)
    
    def log_debug(self, message: str, emoji: str = "", indent: int = 0):
        """DEBUG 레벨 로그"""
        self.log(message, emoji, indent, logging.DEBUG)
    
    def log_info(self, message: str, emoji: str = "", indent: int = 0):
        """INFO 레벨 로그"""
        self.log(message, emoji, indent, logging.INFO)
    
    def log_warning(self, message: str, emoji: str = "", indent: int = 0):
        """WARNING 레벨 로그"""
        self.log(message, emoji, indent, logging.WARNING)
    
    def log_error(self, message: str, emoji: str = "", indent: int = 0):
        """ERROR 레벨 로그"""
        self.log(message, emoji, indent, logging.ERROR)
    
    def _log_start(self):
        """시작 로그"""
        self.logger.info("=" * 50)
        self.logger.info(f"🚀 [{self.order:04d}] {self.name} - {self.description}")
        self.logger.info("=" * 50)
    
    def _log_complete(self):
        """완료 로그"""
        self.completed_at = datetime.now()
        duration = self.duration_seconds or 0
        self.logger.info(f"✅ [{self.name}] completed ({duration:.2f}s)")
    
    # =========================================================================
    # Error Handling
    # =========================================================================
    
    def _handle_error(self, state: Dict[str, Any], error: Exception) -> Dict[str, Any]:
        """
        에러 핸들링 (서브클래스에서 오버라이드 가능)
        
        Args:
            state: 현재 상태
            error: 발생한 예외
            
        Returns:
            에러 정보가 포함된 상태 업데이트
        """
        error_msg = f"❌ [{self.name}] Error: {error}"
        self.logger.error(error_msg)
        self.logger.exception("Traceback:")
        
        return {
            "error_message": str(error),
            "logs": [error_msg]
        }
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} order={self.order}>"
    
    def __lt__(self, other: "BaseNode") -> bool:
        """order 기준 정렬용"""
        return self.order < other.order
