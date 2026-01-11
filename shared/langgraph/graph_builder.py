# shared/langgraph/graph_builder.py
"""
Generic LangGraph Pipeline Builder

Node Registry 기반으로 순차적 파이프라인을 동적으로 빌드합니다.

Usage:
    from shared.langgraph import build_sequential_graph
    from my_agent.state import MyAgentState
    
    workflow = build_sequential_graph(
        state_class=MyAgentState,
        node_module="my_agent.nodes",
        include_nodes=["node1", "node2"],
        agent_name="MyAgent"
    )
"""

from typing import List, Optional, Type, Any, Callable
from langgraph.graph import StateGraph, END

from .registry import get_registry


def build_sequential_graph(
    state_class: Type,
    node_module: str = None,
    include_nodes: Optional[List[str]] = None,
    exclude_nodes: Optional[List[str]] = None,
    checkpointer: Any = None,
    agent_name: str = "Agent",
    verbose: bool = True,
    import_nodes: bool = True,
):
    """
    순차적 LangGraph 파이프라인 빌드
    
    NodeRegistry에 등록된 노드들을 order 순서대로 연결하여
    START → node1 → node2 → ... → END 구조의 파이프라인을 생성합니다.
    
    Args:
        state_class: LangGraph State 클래스 (예: AgentState, ExtractionState)
        node_module: 노드가 정의된 모듈 경로 (예: "IndexingAgent.src.agents.nodes")
                     import_nodes=True일 때 이 모듈을 import하여 노드 등록을 트리거
        include_nodes: (선택) 포함할 노드 이름 목록. None이면 모든 활성 노드 포함.
        exclude_nodes: (선택) 제외할 노드 이름 목록.
        checkpointer: (선택) 상태 저장용 checkpointer (Human-in-the-Loop용)
        agent_name: 출력시 사용할 에이전트 이름
        verbose: True면 빌드 정보 출력
        import_nodes: True면 node_module을 import하여 노드 등록 트리거
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Examples:
        # 기본 사용
        workflow = build_sequential_graph(
            state_class=MyState,
            node_module="myagent.nodes",
            agent_name="MyAgent"
        )
        
        # 특정 노드만 포함
        workflow = build_sequential_graph(
            state_class=MyState,
            include_nodes=["node1", "node2"],
            agent_name="MyAgent"
        )
        
        # Human-in-the-Loop 지원
        from langgraph.checkpoint.memory import MemorySaver
        workflow = build_sequential_graph(
            state_class=MyState,
            checkpointer=MemorySaver(),
            agent_name="MyAgent"
        )
    """
    # 노드 모듈 import (registry에 노드 등록 트리거)
    if import_nodes and node_module:
        import importlib
        importlib.import_module(node_module)
    
    registry = get_registry()
    
    # 활성화된 노드를 order 순으로 가져오기
    nodes = registry.get_ordered_nodes(include=include_nodes, exclude=exclude_nodes)
    
    if not nodes:
        raise ValueError(
            f"No nodes to build pipeline. "
            f"Check include/exclude filters or ensure nodes are registered."
        )
    
    # 빌드 정보 출력
    if verbose:
        _print_build_info(nodes, agent_name)
    
    # StateGraph 생성
    workflow = StateGraph(state_class)
    
    # 노드 추가
    for node in nodes:
        workflow.add_node(node.name, node)
    
    # Entry point (첫 번째 노드)
    workflow.set_entry_point(nodes[0].name)
    
    # 순차적 엣지 추가
    for i in range(len(nodes) - 1):
        workflow.add_edge(nodes[i].name, nodes[i + 1].name)
    
    # 마지막 노드 → END
    workflow.add_edge(nodes[-1].name, END)
    
    # Compile
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


def build_partial_graph(
    state_class: Type,
    until_node: str = None,
    until_order: int = None,
    node_module: str = None,
    checkpointer: Any = None,
    agent_name: str = "Agent",
    verbose: bool = True,
):
    """
    부분 파이프라인 빌드 (특정 노드까지만 실행)
    
    Args:
        state_class: LangGraph State 클래스
        until_node: 마지막으로 실행할 노드 이름
        until_order: 마지막으로 실행할 order
        node_module: 노드가 정의된 모듈 경로
        checkpointer: (선택) 상태 저장용 checkpointer
        agent_name: 출력시 사용할 에이전트 이름
        verbose: True면 빌드 정보 출력
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Examples:
        # 특정 노드까지 실행
        workflow = build_partial_graph(
            state_class=MyState,
            until_node="file_classification",
            node_module="myagent.nodes"
        )
        
        # 특정 order까지 실행
        workflow = build_partial_graph(
            state_class=MyState,
            until_order=600,
            node_module="myagent.nodes"
        )
    """
    # 노드 모듈 import (registry에 노드 등록 트리거)
    if node_module:
        import importlib
        importlib.import_module(node_module)
    
    registry = get_registry()
    
    # 노드가 없으면 모듈이 제대로 import되지 않았을 수 있음
    if registry.node_count == 0:
        raise ValueError(
            f"No nodes registered. Ensure node_module '{node_module}' is correct "
            f"and contains @register_node decorated classes."
        )
    
    all_nodes = registry.get_ordered_nodes()
    
    if until_node:
        include_nodes = []
        for node in all_nodes:
            include_nodes.append(node.name)
            if node.name == until_node:
                break
    elif until_order:
        include_nodes = [node.name for node in all_nodes if node.order <= until_order]
    else:
        raise ValueError("Either until_node or until_order must be provided")
    
    return build_sequential_graph(
        state_class=state_class,
        include_nodes=include_nodes,
        checkpointer=checkpointer,
        agent_name=agent_name,
        verbose=verbose,
        import_nodes=False,  # 이미 위에서 import됨
    )


def _print_build_info(nodes: list, agent_name: str):
    """빌드 정보 출력"""
    print(f"\n{'='*60}")
    print(f"🔧 Building {agent_name} Pipeline")
    print(f"{'='*60}")
    print(f"📋 Nodes ({len(nodes)}):")
    
    for node in nodes:
        badges = []
        if getattr(node, 'requires_llm', False):
            badges.append("🤖")
        if getattr(node, 'requires_db', False):
            badges.append("📊")
        if getattr(node, 'requires_neo4j', False):
            badges.append("🔗")
        
        badge_str = "".join(badges) if badges else "📏"
        description = getattr(node, 'description', '')
        
        # order 형식: 3자리 또는 4자리
        order_str = f"{node.order:04d}" if node.order >= 100 else f"{node.order:03d}"
        
        print(f"   [{order_str}] {node.name} {badge_str} - {description}")
    
    print(f"{'='*60}\n")

