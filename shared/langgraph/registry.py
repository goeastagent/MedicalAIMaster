# shared/langgraph/registry.py
"""
NodeRegistry - Dynamic node management for LangGraph pipelines

Features:
- Automatic node registration via decorators
- Order-based sorting (100, 200, 300, ...)
- Enable/disable nodes at runtime
- Configuration-based pipeline building
- Singleton pattern for global node registry

Usage:
    from shared.langgraph import register_node, get_registry, BaseNode
    
    @register_node
    class MyNode(BaseNode):
        name = "my_node"
        order = 100
        ...
    
    # Get registry
    registry = get_registry()
    
    # Get ordered nodes for pipeline building
    nodes = registry.get_ordered_nodes()
"""

from typing import Dict, List, Type, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .base_node import BaseNode


class NodeRegistry:
    """
    노드 등록 및 관리 (싱글톤)
    
    사용법:
        # 노드 등록 (데코레이터)
        @register_node
        class QueryUnderstandingNode(BaseNode):
            name = "query_understanding"
            order = 100
            ...
        
        # 레지스트리 사용
        registry = get_registry()
        
        # 모든 활성 노드 가져오기
        nodes = registry.get_enabled_nodes()
        
        # 파이프라인 순서대로 노드 가져오기
        for node in registry.get_ordered_nodes():
            workflow.add_node(node.name, node)
    
    Note:
        클래스 레벨 딕셔너리를 사용하여 모듈 경로와 무관하게 
        동일한 레지스트리를 공유합니다.
    """
    
    _instance = None
    
    # 클래스 레벨에서 직접 데이터 저장 (모듈 경로와 무관하게 공유)
    _global_node_classes: Dict[str, Type["BaseNode"]] = {}
    _global_disabled_nodes: Set[str] = set()
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @property
    def _node_classes(self) -> Dict[str, Type["BaseNode"]]:
        return NodeRegistry._global_node_classes
    
    @property
    def _disabled_nodes(self) -> Set[str]:
        return NodeRegistry._global_disabled_nodes
    
    @classmethod
    def register(cls, node_class: Type["BaseNode"]) -> Type["BaseNode"]:
        """
        노드 클래스 등록
        
        Args:
            node_class: BaseNode를 상속한 클래스
            
        Returns:
            등록된 클래스 (데코레이터 사용 시 반환용)
        """
        # BaseNode import를 지연시켜 순환 참조 방지
        from .base_node import BaseNode
        
        if not issubclass(node_class, BaseNode):
            raise TypeError(f"{node_class} must inherit from BaseNode")
        
        name = node_class.name
        if name == "base":
            raise ValueError(f"Node class {node_class} must define a unique 'name' attribute")
        
        # 클래스 레벨 딕셔너리에 직접 등록 (모듈 경로 무관)
        if name in cls._global_node_classes:
            existing = cls._global_node_classes[name]
            # 같은 클래스면 스킵
            if existing.__name__ == node_class.__name__:
                return node_class
            print(f"⚠️ Overwriting node '{name}': {existing} -> {node_class}")
        
        cls._global_node_classes[name] = node_class
        return node_class
    
    def get_node_class(self, name: str) -> Optional[Type["BaseNode"]]:
        """이름으로 노드 클래스 조회"""
        return self._node_classes.get(name)
    
    def get_node(self, name: str) -> Optional["BaseNode"]:
        """이름으로 노드 인스턴스 생성"""
        node_class = self.get_node_class(name)
        if node_class:
            return node_class()
        return None
    
    def get_all_node_classes(self) -> Dict[str, Type["BaseNode"]]:
        """모든 등록된 노드 클래스 반환"""
        return dict(self._node_classes)
    
    def get_all_nodes(self) -> List["BaseNode"]:
        """모든 등록된 노드 인스턴스 반환 (order 정렬)"""
        nodes = [cls() for cls in self._node_classes.values()]
        return sorted(nodes, key=lambda n: n.order)
    
    def get_enabled_nodes(self) -> List["BaseNode"]:
        """활성화된 노드만 반환 (order 정렬)"""
        nodes = []
        for name, cls in self._node_classes.items():
            if name not in self._disabled_nodes:
                node = cls()
                if node.enabled:
                    nodes.append(node)
        return sorted(nodes, key=lambda n: n.order)
    
    def get_ordered_nodes(
        self,
        include: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None
    ) -> List["BaseNode"]:
        """
        정렬된 노드 목록 반환 (선택적 필터링)
        
        Args:
            include: 포함할 노드 이름 목록 (None이면 모두 포함)
            exclude: 제외할 노드 이름 목록
            
        Returns:
            order 기준 정렬된 노드 인스턴스 목록
        """
        exclude = exclude or []
        exclude = set(exclude) | self._disabled_nodes
        
        nodes = []
        for name, cls in self._node_classes.items():
            if name in exclude:
                continue
            if include is not None and name not in include:
                continue
            
            node = cls()
            if node.enabled:
                nodes.append(node)
        
        return sorted(nodes, key=lambda n: n.order)
    
    # =========================================================================
    # Enable/Disable
    # =========================================================================
    
    def enable_node(self, name: str):
        """노드 활성화"""
        self._disabled_nodes.discard(name)
    
    def disable_node(self, name: str):
        """노드 비활성화"""
        self._disabled_nodes.add(name)
    
    def set_enabled(self, name: str, enabled: bool):
        """노드 활성화 상태 설정"""
        if enabled:
            self.enable_node(name)
        else:
            self.disable_node(name)
    
    def is_enabled(self, name: str) -> bool:
        """노드 활성화 상태 확인"""
        if name not in self._node_classes:
            return False
        if name in self._disabled_nodes:
            return False
        
        node = self.get_node(name)
        return node.enabled if node else False
    
    # =========================================================================
    # Utilities
    # =========================================================================
    
    def list_nodes(self) -> List[Dict]:
        """노드 목록 정보 반환"""
        result = []
        for name, cls in self._node_classes.items():
            node = cls()
            result.append({
                "name": name,
                "order": node.order,
                "description": node.description,
                "requires_llm": node.requires_llm,
                "requires_db": getattr(node, "requires_db", False),
                "enabled": self.is_enabled(name),
                "class": cls.__name__
            })
        return sorted(result, key=lambda x: x["order"])
    
    def print_pipeline(self, title: str = "Pipeline Configuration"):
        """파이프라인 구성 출력"""
        print(f"\n{'='*60}")
        print(f"📋 {title}")
        print(f"{'='*60}")
        
        nodes = self.list_nodes()
        for node in nodes:
            status = "✅" if node["enabled"] else "❌"
            badges = []
            if node["requires_llm"]:
                badges.append("🤖")
            if node.get("requires_db"):
                badges.append("📊")
            badge_str = "".join(badges) if badges else "📏"
            
            print(f"{status} [{node['order']:04d}] {node['name']}")
            print(f"   {badge_str} {node['description']}")
            print()
    
    def clear(self):
        """모든 등록 초기화 (테스트용)"""
        NodeRegistry._global_node_classes.clear()
        NodeRegistry._global_disabled_nodes.clear()
    
    @property
    def node_count(self) -> int:
        """등록된 노드 수"""
        return len(self._node_classes)
    
    @property
    def enabled_count(self) -> int:
        """활성화된 노드 수"""
        return len(self.get_enabled_nodes())


# =============================================================================
# Decorator
# =============================================================================

def register_node(cls: Type["BaseNode"]) -> Type["BaseNode"]:
    """
    노드 등록 데코레이터
    
    사용법:
        @register_node
        class QueryUnderstandingNode(BaseNode):
            name = "query_understanding"
            order = 100
            ...
    """
    return NodeRegistry.register(cls)


# =============================================================================
# Convenience Functions
# =============================================================================

def get_registry() -> NodeRegistry:
    """NodeRegistry 싱글톤 인스턴스 반환"""
    return NodeRegistry()


def get_node_names() -> List[str]:
    """등록된 모든 노드 이름 반환"""
    return list(get_registry().get_all_node_classes().keys())

