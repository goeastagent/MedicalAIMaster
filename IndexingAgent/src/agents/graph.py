"""
10-Phase Sequential Indexing Pipeline
======================================

Full Pipeline Flow:
    START
      │
      ▼
┌─────────────────────────────┐
│ Phase 1: Directory Catalog  │ ← 디렉토리 구조 분석, 파일명 샘플 수집 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 2: File Catalog       │ ← 파일별 메타데이터 추출, DB 저장 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 3: Schema Aggregation │ ← 유니크 컬럼/파일 집계, LLM 배치 준비 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 4: File Classification│ ← metadata vs data 파일 분류 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 5: Metadata Semantic  │ ← metadata 파일에서 data_dictionary 추출 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 6: Data Semantic      │ ← data 파일 컬럼 의미 분석 + dictionary 매칭 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 7: Directory Pattern  │ ← 디렉토리 파일명 패턴 분석 + ID 추출 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 8: Entity Identify    │ ← 테이블별 row_represents, entity_identifier (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 9: Relationship Infer │ ← 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ Phase 10: Ontology Enhance  │ ← Concept Hierarchy, Semantic Edges, Medical Terms (LLM)
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

from langgraph.graph import StateGraph, END
from src.agents.state import AgentState
from src.agents.nodes import (
    # Phase 1: Directory Catalog
    phase1_directory_catalog_node,
    # Phase 2: File Catalog
    phase2_file_catalog_node,
    # Phase 3: Schema Aggregation
    phase3_aggregation_node,
    # Phase 4: File Classification
    phase4_classification_node,
    # Phase 5: Metadata Semantic
    phase5_metadata_semantic_node,
    # Phase 6: Data Semantic
    phase6_data_semantic_node,
    # Phase 7: Directory Pattern
    phase7_directory_pattern_node,
    # Phase 8: Entity Identification
    phase8_entity_identification_node,
    # Phase 9: Relationship Inference
    phase9_relationship_inference_node,
    # Phase 10: Ontology Enhancement
    phase10_ontology_enhancement_node,
)


def build_agent(checkpointer=None):
    """
    10-Phase Sequential Indexing Pipeline 빌드
    
    완전한 데이터 인덱싱 파이프라인:
    - Phase 1-3: Rule-based 메타데이터 수집
    - Phase 4-10: LLM 기반 의미 분석 및 온톨로지 구축
    
    Args:
        checkpointer: (선택) 상태 저장용 checkpointer (예: MemorySaver())
                     Human-in-the-Loop에서 interrupt/resume을 위해 필요
    
    Returns:
        컴파일된 LangGraph 워크플로우
    """
    workflow = StateGraph(AgentState)
    
    # ==========================================================================
    # Phase 1: Directory Catalog (Rule-based)
    # 디렉토리 구조 분석, 파일명 샘플 수집
    # ==========================================================================
    workflow.add_node("phase1_directory_catalog", phase1_directory_catalog_node)
    
    # ==========================================================================
    # Phase 2: File Catalog (Rule-based)
    # 파일별 메타데이터 추출, DB 저장
    # ==========================================================================
    workflow.add_node("phase2_file_catalog", phase2_file_catalog_node)
    
    # ==========================================================================
    # Phase 3: Schema Aggregation (Rule-based)
    # 유니크 컬럼/파일 집계, LLM 배치 준비
    # ==========================================================================
    workflow.add_node("phase3_aggregation", phase3_aggregation_node)
    
    # ==========================================================================
    # Phase 4: File Classification (LLM)
    # metadata vs data 파일 분류
    # ==========================================================================
    workflow.add_node("phase4_classification", phase4_classification_node)
    
    # ==========================================================================
    # Phase 5: Metadata Semantic (LLM)
    # metadata 파일에서 data_dictionary 추출
    # ==========================================================================
    workflow.add_node("phase5_metadata_semantic", phase5_metadata_semantic_node)
    
    # ==========================================================================
    # Phase 6: Data Semantic (LLM)
    # data 파일 컬럼 의미 분석 + dictionary 매칭
    # ==========================================================================
    workflow.add_node("phase6_data_semantic", phase6_data_semantic_node)
    
    # ==========================================================================
    # Phase 7: Directory Pattern (LLM)
    # 디렉토리 파일명 패턴 분석 + ID 추출
    # ==========================================================================
    workflow.add_node("phase7_directory_pattern", phase7_directory_pattern_node)
    
    # ==========================================================================
    # Phase 8: Entity Identification (LLM)
    # 테이블별 row_represents, entity_identifier 식별
    # ==========================================================================
    workflow.add_node("phase8_entity_identification", phase8_entity_identification_node)
    
    # ==========================================================================
    # Phase 9: Relationship Inference (LLM)
    # 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology
    # ==========================================================================
    workflow.add_node("phase9_relationship_inference", phase9_relationship_inference_node)
    
    # ==========================================================================
    # Phase 10: Ontology Enhancement (LLM)
    # Concept Hierarchy, Semantic Edges, Medical Terms
    # ==========================================================================
    workflow.add_node("phase10_ontology_enhancement", phase10_ontology_enhancement_node)
    
    # ==========================================================================
    # Edges: Sequential Flow (Phase 1 → 2 → 3 → ... → 10 → END)
    # ==========================================================================
    
    # Entry Point
    workflow.set_entry_point("phase1_directory_catalog")
    
    # Phase 1 → Phase 2
    workflow.add_edge("phase1_directory_catalog", "phase2_file_catalog")
    
    # Phase 2 → Phase 3
    workflow.add_edge("phase2_file_catalog", "phase3_aggregation")
    
    # Phase 3 → Phase 4
    workflow.add_edge("phase3_aggregation", "phase4_classification")
    
    # Phase 4 → Phase 5
    workflow.add_edge("phase4_classification", "phase5_metadata_semantic")
    
    # Phase 5 → Phase 6
    workflow.add_edge("phase5_metadata_semantic", "phase6_data_semantic")
    
    # Phase 6 → Phase 7
    workflow.add_edge("phase6_data_semantic", "phase7_directory_pattern")
    
    # Phase 7 → Phase 8
    workflow.add_edge("phase7_directory_pattern", "phase8_entity_identification")
    
    # Phase 8 → Phase 9
    workflow.add_edge("phase8_entity_identification", "phase9_relationship_inference")
    
    # Phase 9 → Phase 10
    workflow.add_edge("phase9_relationship_inference", "phase10_ontology_enhancement")
    
    # Phase 10 → END
    workflow.add_edge("phase10_ontology_enhancement", END)
    
    # ==========================================================================
    # Compile with Checkpointer
    # ==========================================================================
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


# =============================================================================
# Convenience Functions
# =============================================================================

def build_partial_agent(end_phase: int = 10, checkpointer=None):
    """
    부분 파이프라인 빌드 (특정 Phase까지만 실행)
    
    Args:
        end_phase: 마지막으로 실행할 Phase 번호 (1-10)
        checkpointer: (선택) 상태 저장용 checkpointer
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Example:
        # Phase 1-4까지만 실행 (파일 분류까지)
        workflow = build_partial_agent(end_phase=4)
    """
    if end_phase < 1 or end_phase > 10:
        raise ValueError("end_phase must be between 1 and 10")
    
    # Phase 노드 매핑
    phase_nodes = {
        1: ("phase1_directory_catalog", phase1_directory_catalog_node),
        2: ("phase2_file_catalog", phase2_file_catalog_node),
        3: ("phase3_aggregation", phase3_aggregation_node),
        4: ("phase4_classification", phase4_classification_node),
        5: ("phase5_metadata_semantic", phase5_metadata_semantic_node),
        6: ("phase6_data_semantic", phase6_data_semantic_node),
        7: ("phase7_directory_pattern", phase7_directory_pattern_node),
        8: ("phase8_entity_identification", phase8_entity_identification_node),
        9: ("phase9_relationship_inference", phase9_relationship_inference_node),
        10: ("phase10_ontology_enhancement", phase10_ontology_enhancement_node),
    }
    
    workflow = StateGraph(AgentState)
    
    # 노드 추가 (1부터 end_phase까지)
    for phase_num in range(1, end_phase + 1):
        node_name, node_func = phase_nodes[phase_num]
        workflow.add_node(node_name, node_func)
    
    # Entry Point
    workflow.set_entry_point("phase1_directory_catalog")
    
    # 엣지 추가 (순차적 연결)
    for phase_num in range(1, end_phase):
        current_node = phase_nodes[phase_num][0]
        next_node = phase_nodes[phase_num + 1][0]
        workflow.add_edge(current_node, next_node)
    
    # 마지막 Phase → END
    last_node = phase_nodes[end_phase][0]
    workflow.add_edge(last_node, END)
    
    # Compile
    compile_config = {}
    if checkpointer:
        compile_config["checkpointer"] = checkpointer
    
    return workflow.compile(**compile_config)


# Alias for backward compatibility
build_full_pipeline_agent = build_agent
