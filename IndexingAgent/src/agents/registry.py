# src/agents/registry.py
"""
NodeRegistry - Dynamic node management for the agent pipeline

Features:
- Automatic node registration via decorators
- Order-based sorting (not phase numbering)
- Enable/disable nodes at runtime
- Configuration-based pipeline building
"""

from typing import Dict, List, Type, Optional, Set
from .base.node import BaseNode


class NodeRegistry:
    """
    노드 등록 및 관리
    
    사용법:
        # 노드 등록
        @register_node
        class DirectoryCatalogNode(BaseNode):
            name = "directory_catalog"
            order = 100
            ...
        
        # 레지스트리 사용
        registry = NodeRegistry()
        
        # 모든 활성 노드 가져오기
        nodes = registry.get_enabled_nodes()
        
        # 특정 노드 비활성화
        registry.disable_node("some_node")
        
        # 파이프라인 순서대로 노드 가져오기
        for node in registry.get_ordered_nodes():
            workflow.add_node(node.name, node)
    """
    
    _instance = None
    _node_classes: Dict[str, Type[BaseNode]] = {}
    _disabled_nodes: Set[str] = set()
    
    def __new__(cls):
        """Singleton pattern"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._node_classes = {}
            cls._instance._disabled_nodes = set()
        return cls._instance
    
    @classmethod
    def register(cls, node_class: Type[BaseNode]) -> Type[BaseNode]:
        """
        노드 클래스 등록
        
        Args:
            node_class: BaseNode를 상속한 클래스
            
        Returns:
            등록된 클래스 (데코레이터 사용 시 반환용)
        """
        if not issubclass(node_class, BaseNode):
            raise TypeError(f"{node_class} must inherit from BaseNode")
        
        name = node_class.name
        if name == "base":
            raise ValueError(f"Node class {node_class} must define a unique 'name' attribute")
        
        # Singleton 인스턴스 확보
        instance = cls()
        
        if name in instance._node_classes:
            existing = instance._node_classes[name]
            print(f"⚠️ Overwriting node '{name}': {existing} -> {node_class}")
        
        instance._node_classes[name] = node_class
        return node_class
    
    def get_node_class(self, name: str) -> Optional[Type[BaseNode]]:
        """이름으로 노드 클래스 조회"""
        return self._node_classes.get(name)
    
    def get_node(self, name: str) -> Optional[BaseNode]:
        """이름으로 노드 인스턴스 생성"""
        node_class = self.get_node_class(name)
        if node_class:
            return node_class()
        return None
    
    def get_all_node_classes(self) -> Dict[str, Type[BaseNode]]:
        """모든 등록된 노드 클래스 반환"""
        return dict(self._node_classes)
    
    def get_all_nodes(self) -> List[BaseNode]:
        """모든 등록된 노드 인스턴스 반환 (order 정렬)"""
        nodes = [cls() for cls in self._node_classes.values()]
        return sorted(nodes, key=lambda n: n.order)
    
    def get_enabled_nodes(self) -> List[BaseNode]:
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
    ) -> List[BaseNode]:
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
                "enabled": self.is_enabled(name),
                "class": cls.__name__
            })
        return sorted(result, key=lambda x: x["order"])
    
    def print_pipeline(self):
        """파이프라인 구성 출력"""
        print("\n" + "="*60)
        print("📋 Pipeline Configuration")
        print("="*60)
        
        nodes = self.list_nodes()
        for i, node in enumerate(nodes, 1):
            status = "✅" if node["enabled"] else "❌"
            llm_badge = "🤖" if node["requires_llm"] else "📏"
            
            print(f"{status} [{node['order']:04d}] {node['name']}")
            print(f"   {llm_badge} {node['description']}")
            print(f"   Class: {node['class']}")
            print()
    
    def clear(self):
        """모든 등록 초기화 (테스트용)"""
        self._node_classes.clear()
        self._disabled_nodes.clear()
    
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

def register_node(cls: Type[BaseNode]) -> Type[BaseNode]:
    """
    노드 등록 데코레이터
    
    사용법:
        @register_node
        class DirectoryCatalogNode(BaseNode):
            name = "directory_catalog"
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

