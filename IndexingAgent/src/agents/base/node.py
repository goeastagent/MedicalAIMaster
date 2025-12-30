# src/agents/base/node.py
"""
BaseNode - Abstract base class for all agent nodes

All nodes in the pipeline should inherit from this class.
Provides:
- Standard execution flow with timing
- Error handling
- Logging interface
- LangGraph compatibility via __call__
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from datetime import datetime


class BaseNode(ABC):
    """
    모든 노드가 상속받는 추상 클래스
    
    서브클래스에서 정의해야 할 것:
    - name: 노드 고유 이름 (예: "directory_catalog")
    - description: 노드 설명
    - order: 실행 순서 (낮을수록 먼저 실행, 10 단위 권장)
    - execute(): 실제 로직
    
    Example:
        class DirectoryCatalogNode(BaseNode):
            name = "directory_catalog"
            description = "디렉토리 구조 분석"
            order = 100
            
            def execute(self, state):
                # 로직
                return {"result": ...}
    """
    
    # === 메타데이터 (서브클래스에서 오버라이드) ===
    name: str = "base"                    # 노드 고유 이름
    description: str = ""                 # 노드 설명
    order: int = 0                        # 실행 순서 (낮을수록 먼저)
    requires_llm: bool = False            # LLM 사용 여부
    enabled: bool = True                  # 활성화 여부
    
    def __init__(self):
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self._logs: List[str] = []
    
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
            state: AgentState dict
            
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
    
    def log(self, message: str, emoji: str = ""):
        """
        로그 메시지 추가
        
        Args:
            message: 로그 메시지
            emoji: 접두사 이모지 (선택)
        """
        prefix = f"{emoji} " if emoji else ""
        log_entry = f"{prefix}[{self.name}] {message}"
        self._logs.append(log_entry)
        print(log_entry)
    
    def _log_start(self):
        """시작 로그"""
        print(f"\n{'='*60}")
        print(f"🚀 [{self.name}] {self.description}")
        print(f"{'='*60}")
    
    def _log_complete(self):
        """완료 로그"""
        self.completed_at = datetime.now()
        duration = self.duration_seconds or 0
        print(f"\n✅ [{self.name}] 완료 ({duration:.1f}s)")
        print(f"{'='*60}\n")
    
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
        print(error_msg)
        
        import traceback
        traceback.print_exc()
        
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

