# src/agents/graph.py
"""
VitalExtractionAgent LangGraph Pipeline Builder
================================================

3-Node Sequential Pipeline:
    START
      │
      ▼
┌─────────────────────────────┐
│ query_understanding (100)   │ ← DB 메타데이터 로딩 + LLM 쿼리 분석
│     🤖📊                    │   SchemaContextBuilder → 동적 컨텍스트
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ parameter_resolver (200)    │ ← 파라미터 검색 + Resolution Mode 결정
│     🤖📊                    │   PostgreSQL parameter + Neo4j 보조
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ plan_builder (300)          │ ← Execution Plan JSON 조립
│     📊                      │   DynamicTopology + validation
└───────────────┬─────────────┘
                │
                ▼
              END

Usage:
    from src.agents.graph import build_agent
    
    # Create workflow
    workflow = build_agent()
    
    # Run workflow
    result = workflow.invoke({
        "user_query": "위암 환자의 수술 중 심박수 데이터",
        "logs": []
    })
    
    print(result["execution_plan"])
"""

from typing import List, Optional
from langgraph.graph import StateGraph, END
from .state import VitalExtractionState


def build_agent(
    checkpointer=None,
    include_nodes: Optional[List[str]] = None,
    exclude_nodes: Optional[List[str]] = None
):
    """
    VitalExtractionAgent 파이프라인 빌드
    
    NodeRegistry를 사용하여 order 순서대로 노드를 연결합니다.
    노드를 선택적으로 포함/제외할 수 있습니다.
    
    Args:
        checkpointer: (선택) 상태 저장용 checkpointer
                     Human-in-the-Loop에서 interrupt/resume을 위해 필요
        include_nodes: (선택) 포함할 노드 이름 목록. None이면 모든 활성 노드 포함.
        exclude_nodes: (선택) 제외할 노드 이름 목록.
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Examples:
        # 전체 파이프라인 (3 nodes)
        workflow = build_agent()
        
        # 특정 노드만 포함
        workflow = build_agent(include_nodes=["query_understanding", "plan_builder"])
        
        # 특정 노드 제외
        workflow = build_agent(exclude_nodes=["parameter_resolver"])
    """
    # 노드 클래스 임포트 (이 시점에 @register_node가 자동으로 등록)
    # 직접 사용하지 않지만 import로 registry에 등록됨
    from . import nodes  # noqa: F401
    
    from .registry import get_registry
    
    registry = get_registry()
    
    # 활성화된 노드를 order 순으로 가져오기
    nodes = registry.get_ordered_nodes(include=include_nodes, exclude=exclude_nodes)
    
    if not nodes:
        raise ValueError("No nodes to build pipeline. Check include/exclude filters.")
    
    print(f"\n{'='*60}")
    print("🔧 Building VitalExtractionAgent Pipeline")
    print(f"{'='*60}")
    print(f"📋 Nodes ({len(nodes)}):")
    for node in nodes:
        badges = []
        if node.requires_llm:
            badges.append("🤖")
        if node.requires_db:
            badges.append("📊")
        badge_str = "".join(badges) if badges else "📏"
        print(f"   [{node.order:03d}] {node.name} {badge_str} - {node.description}")
    print(f"{'='*60}\n")
    
    workflow = StateGraph(VitalExtractionState)
    
    # 노드 추가
    for node in nodes:
        workflow.add_node(node.name, node)
    
    # Entry point (첫 번째 노드)
    workflow.set_entry_point(nodes[0].name)
    
    # 순차적 엣지 추가
    for i in range(len(nodes) - 1):
        current_node = nodes[i]
        next_node = nodes[i + 1]
        workflow.add_edge(current_node.name, next_node.name)
    
    # 마지막 노드 → END
    workflow.add_edge(nodes[-1].name, END)
    
    # Compile
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


def build_custom_agent(node_names: List[str], checkpointer=None):
    """
    커스텀 파이프라인 빌드 (지정된 노드만 포함)
    
    Args:
        node_names: 포함할 노드 이름 목록 (순서는 order에 따라 자동 정렬)
        checkpointer: (선택) 상태 저장용 checkpointer
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Example:
        workflow = build_custom_agent([
            "query_understanding",
            "plan_builder"
        ])
    """
    return build_agent(checkpointer=checkpointer, include_nodes=node_names)


def list_available_nodes() -> List[dict]:
    """사용 가능한 모든 노드 목록 반환"""
    # Import to ensure nodes are registered
    import src.agents.nodes  # noqa: F401
    from .registry import get_registry
    return get_registry().list_nodes()


def print_pipeline_info():
    """파이프라인 구성 정보 출력"""
    # Import to ensure nodes are registered
    import src.agents.nodes  # noqa: F401
    from .registry import get_registry
    get_registry().print_pipeline()

