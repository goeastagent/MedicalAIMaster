"""
Dynamic Indexing Pipeline Builder
=================================

NodeRegistry를 사용하여 동적으로 파이프라인을 구성합니다.

Pipeline Flow (order 기반):
    START
      │
      ▼
┌─────────────────────────────┐
│ directory_catalog (100)     │ ← 디렉토리 구조 분석, 파일명 샘플 수집 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ file_catalog (200)          │ ← 파일별 메타데이터 추출, DB 저장 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ schema_aggregation (300)    │ ← 유니크 컬럼/파일 집계, LLM 배치 준비 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ file_classification (400)   │ ← metadata vs data 파일 분류 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ metadata_semantic (500)     │ ← metadata 파일에서 data_dictionary 추출 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ data_semantic (600)         │ ← data 파일 컬럼 의미 분석 + dictionary 매칭 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ directory_pattern (700)     │ ← 디렉토리 파일명 패턴 분석 + ID 추출 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ entity_identification (800) │ ← 테이블별 row_represents, entity_identifier (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ relationship_inference (900)│ ← 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ ontology_enhancement (1000) │ ← Concept Hierarchy, Semantic Edges, Medical Terms (LLM)
└───────────────┬─────────────┘
                │
                ▼
              END

Usage:
    from src.agents.graph import build_agent
    from langgraph.checkpoint.memory import MemorySaver
    
    # Create workflow with checkpointer (for Human-in-the-Loop)
    checkpointer = MemorySaver()
    workflow = build_agent(checkpointer=checkpointer)
    
    # Run workflow
    initial_state = {
        "input_directory": "/path/to/data",
        "input_files": [...],  # Optional: specific files to process
        "current_dataset_id": "my_dataset_v1.0.0",
        "logs": [],
    }
    
    config = {"configurable": {"thread_id": "indexing-session-1"}}
    result = workflow.invoke(initial_state, config)
"""

from typing import List, Optional
from langgraph.graph import StateGraph, END
from src.agents.state import AgentState

# 노드 클래스 임포트 (이 시점에 @register_node가 자동으로 등록)
# 직접 사용하지 않지만 import로 registry에 등록됨
import src.agents.nodes  # noqa: F401

from src.agents.registry import get_registry


def build_agent(
    checkpointer=None,
    include_nodes: Optional[List[str]] = None,
    exclude_nodes: Optional[List[str]] = None
):
    """
    동적 인덱싱 파이프라인 빌드
    
    NodeRegistry를 사용하여 order 순서대로 노드를 연결합니다.
    노드를 선택적으로 포함/제외할 수 있습니다.
    
    Args:
        checkpointer: (선택) 상태 저장용 checkpointer (예: MemorySaver())
                     Human-in-the-Loop에서 interrupt/resume을 위해 필요
        include_nodes: (선택) 포함할 노드 이름 목록. None이면 모든 활성 노드 포함.
        exclude_nodes: (선택) 제외할 노드 이름 목록.
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Examples:
        # 전체 파이프라인
        workflow = build_agent()
        
        # 특정 노드만 포함
        workflow = build_agent(include_nodes=["directory_catalog", "file_catalog"])
        
        # 특정 노드 제외
        workflow = build_agent(exclude_nodes=["ontology_enhancement"])
    """
    registry = get_registry()
    
    # 활성화된 노드를 order 순으로 가져오기
    nodes = registry.get_ordered_nodes(include=include_nodes, exclude=exclude_nodes)
    
    if not nodes:
        raise ValueError("No nodes to build pipeline. Check include/exclude filters.")
    
    print(f"\n{'='*60}")
    print("🔧 Building Dynamic Pipeline")
    print(f"{'='*60}")
    print(f"📋 Nodes ({len(nodes)}):")
    for node in nodes:
        llm_badge = "🤖" if node.requires_llm else "📏"
        print(f"   [{node.order:04d}] {node.name} {llm_badge} - {node.description}")
    print(f"{'='*60}\n")
    
    workflow = StateGraph(AgentState)
    
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


def build_partial_agent(
    until_node: str = None,
    until_order: int = None,
    checkpointer=None
):
    """
    부분 파이프라인 빌드 (특정 노드까지만 실행)
    
    Args:
        until_node: 마지막으로 실행할 노드 이름 (예: "file_classification")
        until_order: 마지막으로 실행할 order (예: 400)
        checkpointer: (선택) 상태 저장용 checkpointer
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Examples:
        # file_classification까지만 실행
        workflow = build_partial_agent(until_node="file_classification")
        
        # order 600까지 실행 (data_semantic 포함)
        workflow = build_partial_agent(until_order=600)
    """
    registry = get_registry()
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
    
    return build_agent(checkpointer=checkpointer, include_nodes=include_nodes)


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
            "directory_catalog",
            "file_catalog",
            "entity_identification"
        ])
    """
    return build_agent(checkpointer=checkpointer, include_nodes=node_names)


def list_available_nodes() -> List[dict]:
    """사용 가능한 모든 노드 목록 반환"""
    return get_registry().list_nodes()


def print_pipeline_info():
    """파이프라인 구성 정보 출력"""
    get_registry().print_pipeline()
