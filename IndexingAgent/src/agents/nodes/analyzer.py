# src/agents/nodes/analyzer.py
"""
Analyzer Node - 시맨틱 분석 및 온톨로지 빌드

[Rule Prepares, LLM Decides 원칙]
- Processor가 추출한 metadata를 기반으로
- LLM이 Entity Identification, 컬럼 분석, 계층 분석을 수행
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from src.agents.state import AgentState
from src.agents.nodes.common import (
    llm_client, llm_cache, ontology_manager,
    create_empty_conversation_history, format_history_for_prompt
)
from src.agents.helpers.llm_helpers import (
    analyze_columns_with_llm,
    analyze_intra_table_hierarchy,
    compare_with_global_context,
    should_request_human_review,
    analyze_entity_with_llm,
)
from src.agents.helpers.feedback_parser import (
    parse_human_feedback_to_column,
    generate_natural_human_question,
    parse_entity_feedback,
)
from src.agents.models import (
    FeedbackParseResult, FeedbackAction, IdentifierSource, IdentificationStatus,
    EntityAnalysisResult, LinkableColumnInfo, EntityRelationType,
)
from src.config import HumanReviewConfig


# =============================================================================
# 데이터 클래스: 분석 컨텍스트 관리 간소화
# =============================================================================

@dataclass
class AnalysisContext:
    """분석에 필요한 모든 컨텍스트를 한 곳에서 관리"""
    # 파일 정보
    file_path: str = ""
    file_type: str = "tabular"
    table_name: str = ""
    
    # 메타데이터
    metadata: Dict = field(default_factory=dict)
    columns: List[str] = field(default_factory=list)
    column_details: List[Dict] = field(default_factory=list)
    
    # 프로젝트/온톨로지 컨텍스트
    project_context: Dict = field(default_factory=dict)
    ontology_context: Dict = field(default_factory=dict)
    conversation_history: Dict = field(default_factory=dict)
    
    # 사용자 피드백
    human_feedback: Optional[str] = None
    retry_count: int = 0
    
    # 분석 결과 (Anchor - Legacy)
    entity_identification: Optional[Dict] = None
    
    # 분석 결과 (Entity Understanding - NEW)
    entity_understanding: Optional[Dict] = None
    
    @classmethod
    def from_state(cls, state: AgentState) -> "AnalysisContext":
        """AgentState에서 AnalysisContext 생성"""
        metadata = state.get("raw_metadata", {})
        file_path = state.get("file_path", "")
        
        return cls(
            file_path=file_path,
            file_type=state.get("file_type", "tabular"),
            table_name=os.path.basename(file_path).replace(".csv", "").replace(".CSV", ""),
            metadata=metadata,
            columns=metadata.get("columns", []),
            column_details=metadata.get("column_details", []),
            project_context=state.get("project_context", {
                "master_entity_identifier": None,
                "known_aliases": [],
                "example_id_values": [],
                "known_entities": {}  # NEW: 발견된 entity 정보
            }),
            ontology_context=state.get("ontology_context", {}),
            conversation_history=state.get("conversation_history") or 
                create_empty_conversation_history(state.get("current_dataset_id", "unknown")),
            human_feedback=state.get("human_feedback"),
            retry_count=state.get("retry_count", 0),
            entity_identification=state.get("entity_identification"),
            entity_understanding=state.get("entity_understanding")  # NEW
        )
    
    @property
    def filename(self) -> str:
        return os.path.basename(self.file_path) if self.file_path else "unknown"
    
    @property
    def master_anchor(self) -> Optional[str]:
        return self.project_context.get("master_entity_identifier")
    
    @property
    def dataset_id(self) -> str:
        return self.conversation_history.get("dataset_id", "unknown")


def analyze_semantics_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 2] Semantic Analysis (Semantic Reasoning)
    
    Processor가 추출한 metadata를 기반으로 LLM이 분석 수행:
    1. Human Feedback 처리 (재실행 시)
    2. Anchor 컬럼 감지 및 확정
    3. 컬럼별 상세 스키마 분석
    4. 테이블 내 계층 관계 분석
    """
    # ==========================================================================
    # 스킵 체크
    # ==========================================================================
    if state.get("skip_indexing"):
        return _handle_skip(state)
    
    print("\n" + "="*80)
    print("🧠 [ANALYZER NODE] Starting - Semantic Analysis")
    print("="*80)
    
    # 컨텍스트 로드 (모든 데이터를 한 곳에서 관리)
    ctx = AnalysisContext.from_state(state)
    
    # 대화 히스토리 로그
    if ctx.conversation_history.get("turns"):
        print(f"   📚 대화 히스토리: {len(ctx.conversation_history.get('turns', []))}개 턴")
    
    # ==========================================================================
    # Retry 초과 시 강제 확정
    # ==========================================================================
    if ctx.retry_count >= HumanReviewConfig.MAX_RETRY_COUNT:
        return _handle_retry_exceeded(ctx)
    
    # =========================================================================
    # 컨텍스트에서 자주 쓰는 변수 추출 (가독성 향상)
    # =========================================================================
    metadata = ctx.metadata
    human_feedback = ctx.human_feedback
    file_path = ctx.file_path
    file_type = ctx.file_type
    project_context = ctx.project_context
    ontology_context = ctx.ontology_context
    conversation_history = ctx.conversation_history
    entity_identification = ctx.entity_identification
    retry_count = ctx.retry_count
    dataset_id = ctx.dataset_id

    # ==========================================================================
    # Step 1: Human Feedback 처리 (재실행 시) - Entity Understanding 우선
    # ==========================================================================
    entity_understanding = state.get("entity_understanding")  # 기존 Entity 정보 가져오기
    
    if human_feedback:
        log_msg = f"🗣️ [Feedback] User feedback received: '{human_feedback}'"
        print(f"   {log_msg}")
        
        if file_path:
            filename = os.path.basename(file_path)
            llm_cache.invalidate_for_file(filename)
        
        # =====================================================================
        # NEW: Entity Feedback 파싱 (다중 컬럼/계층 관계 지원)
        # =====================================================================
        entity_feedback = parse_entity_feedback(
            feedback=human_feedback,
            available_columns=metadata.get("columns", []),
            current_entity=entity_understanding,
            file_context={
                "filename": os.path.basename(file_path),
                "file_type": file_type,
                "column_details": metadata.get("column_details", [])
            }
        )
        
        entity_action = entity_feedback.get("action", "clarify")
        print(f"   🧠 [Entity Feedback] action={entity_action}, intent={entity_feedback.get('user_intent', '')}")
        
        # SKIP 처리
        if entity_action == "skip":
            return {
                "entity_identification": None,
                "finalized_schema": [],
                "entity_understanding": None,
                "project_context": project_context,
                "needs_human_review": False,
                "human_feedback": None,
                "skip_indexing": True,
                "logs": [log_msg, "⏭️ [Analyzer] File skipped by user request"]
            }
        
        # Entity 정보 업데이트 (update_entity 또는 confirm)
        if entity_action in ["update_entity", "confirm"]:
            entity_updates = entity_feedback.get("entity_updates", {})
            
            if entity_updates:
                # 새 Entity Understanding 생성/업데이트
                if not entity_understanding:
                    entity_understanding = {
                        "row_represents": "unknown",
                        "row_represents_kr": "",
                        "entity_identifier": metadata.get("columns", ["id"])[0],
                        "linkable_columns": [],
                        "hierarchy_explanation": "",
                        "confidence": 0.0,
                        "reasoning": "",
                        "status": "NEEDS_REVIEW"
                    }
                
                # 업데이트 적용
                for key, value in entity_updates.items():
                    if value is not None:
                        if key == "linkable_columns" and isinstance(value, list):
                            # LinkableColumnInfo 객체를 dict로 변환
                            entity_understanding[key] = []
                            for lc in value:
                                if hasattr(lc, 'column_name'):  # Pydantic model
                                    entity_understanding[key].append({
                                        "column_name": lc.column_name,
                                        "represents_entity": lc.represents_entity,
                                        "represents_entity_kr": lc.represents_entity_kr,
                                        "relation_type": lc.relation_type.value if hasattr(lc.relation_type, 'value') else str(lc.relation_type),
                                        "cardinality": lc.cardinality,
                                        "is_primary_identifier": lc.is_primary_identifier
                                    })
                                elif isinstance(lc, dict):
                                    entity_understanding[key].append(lc)
                        else:
                            entity_understanding[key] = value
                
                entity_understanding["user_feedback_applied"] = human_feedback
                entity_understanding["status"] = "CONFIRMED"
                entity_understanding["confidence"] = entity_feedback.get("confidence", 0.9)
                
                # Entity identifier 결정 (self relation_type을 가진 컬럼)
                for lc in entity_understanding.get("linkable_columns", []):
                    rel_type = lc.get("relation_type", "")
                    if rel_type == "self":
                        entity_understanding["entity_identifier"] = lc.get("column_name")
                        entity_understanding["row_represents"] = lc.get("represents_entity", "unknown")
                        entity_understanding["row_represents_kr"] = lc.get("represents_entity_kr", "")
                        break
                
                # entity_identification도 동기화 (backward compatibility)
                entity_identification = {
                    "status": "CONFIRMED",
                    "column_name": entity_understanding.get("entity_identifier", "id"),
                    "is_time_series": (file_type == "signal"),
                    "reasoning": f"User confirmed via Entity feedback: {entity_feedback.get('user_intent', '')}",
                    "mapped_to_master": project_context.get("master_entity_identifier"),
                    "identifier_source": "user",
                    "row_represents": entity_understanding.get("row_represents")
                }
                
                print(f"   ✅ [Entity] 사용자 피드백 반영:")
                print(f"      - row_represents: {entity_understanding.get('row_represents_kr', entity_understanding.get('row_represents'))}")
                print(f"      - entity_identifier: {entity_understanding.get('entity_identifier')}")
                print(f"      - linkable_columns: {[lc.get('column_name') for lc in entity_understanding.get('linkable_columns', [])]}")
                if entity_understanding.get("hierarchy_explanation"):
                    print(f"      - hierarchy: {entity_understanding.get('hierarchy_explanation')}")
        
        # CLARIFY: 추가 정보 제공 - Entity 분석에서 human_feedback 활용
        else:
            print(f"   → User provided info (will be used in Entity analysis): {human_feedback[:50]}...")
            # entity_identification는 아래 LLM 분석에서 결정됨
    
    # ==========================================================================
    # Step 2: Entity Analysis (통합) - LLM 호출 1회로 모든 정보 획득
    # ==========================================================================
    # analyze_entity_with_llm 하나로 entity_identification + entity_understanding 모두 생성
    
    entity_understanding = state.get("entity_understanding")
    
    if not entity_identification or not entity_understanding:
        # Entity 분석 수행 (conversation_history 전달로 이전 결정 컨텍스트 활용)
        entity_result: EntityAnalysisResult = analyze_entity_with_llm(
            metadata=metadata,
            project_context=project_context,
            user_feedback=human_feedback,
            ontology_context=ontology_context,
            conversation_history=conversation_history
        )
        
        # EntityAnalysisResult에서 핵심 정보 추출
        identifier_column = entity_result.entity_identifier
        confidence = entity_result.confidence
        needs_confirmation = entity_result.needs_human_confirmation
        reasoning = entity_result.reasoning
        is_time_series = file_type == "signal"
        
        print(f"   🔍 Entity 분석 결과: {identifier_column} ({confidence:.0%})")
        print(f"      - row_represents: {entity_result.row_represents_kr or entity_result.row_represents}")
        print(f"      - linkable_columns: {[lc.column_name for lc in entity_result.linkable_columns]}")
        
        # Human Review가 필요한 경우
        if needs_confirmation and confidence < HumanReviewConfig.ANCHOR_CONFIDENCE_THRESHOLD:
            question = generate_natural_human_question(
                file_path=file_path,
                context={
                    "reasoning": reasoning,
                    "candidates": identifier_column or "None",
                    "columns": metadata.get("columns", []),
                    "row_represents": entity_result.row_represents,
                    "message": f"LLM confidence: {confidence:.0%}"
                },
                issue_type="entity_uncertain",
                conversation_history=conversation_history
            )
            
            return {
                "needs_human_review": True,
                "review_type": "entity",
                "human_question": question,
                "conversation_history": conversation_history,
                "retry_count": retry_count + 1,
                "logs": [f"⚠️ [Analyzer] Entity analysis uncertain ({confidence:.0%}). Human review required."]
            }
        
        # entity_understanding 생성 (EntityAnalysisResult → dict)
        entity_understanding = {
            "row_represents": entity_result.row_represents,
            "row_represents_kr": entity_result.row_represents_kr,
            "entity_identifier": entity_result.entity_identifier,
            "linkable_columns": [
                {
                    "column_name": lc.column_name,
                    "represents_entity": lc.represents_entity,
                    "represents_entity_kr": lc.represents_entity_kr,
                    "relation_type": lc.relation_type.value if hasattr(lc.relation_type, 'value') else str(lc.relation_type),
                    "cardinality": lc.cardinality,
                    "is_primary_identifier": lc.is_primary_identifier
                }
                for lc in entity_result.linkable_columns
            ],
            "hierarchy_explanation": entity_result.hierarchy_explanation,
            "confidence": confidence,
            "reasoning": reasoning,
            "status": entity_result.status,
            "user_feedback_applied": entity_result.user_feedback_applied
        }
        
        # entity_identification 생성 (entity_result에서 추출)
        if identifier_column:
            # 상태 결정
            if confidence >= 0.85:
                status = "CONFIRMED"
            elif confidence >= 0.5:
                status = "AMBIGUOUS"
            else:
                status = "MISSING"
            
            entity_identification = {
                "status": status,
                "column_name": identifier_column,
                "is_time_series": is_time_series,
                "confidence": confidence,
                "reasoning": reasoning,
                "mapped_to_master": project_context.get("master_entity_identifier"),
                "row_represents": entity_result.row_represents
            }
            
            # Signal 파일의 경우 id_value 추가
            if entity_result.id_value is not None:
                entity_identification["id_value"] = entity_result.id_value
        
        # Master Identifier와 비교 (이미 있는 경우)
        master_name = project_context.get("master_entity_identifier")
        if master_name and identifier_column and identifier_column.lower() != master_name.lower():
            # Global Context와 비교
            comparison = compare_with_global_context(
                local_metadata=metadata,
                local_identification_info={
                    "column_name": identifier_column,
                    "confidence": confidence,
                    "is_time_series": is_time_series,
                    "reasoning": reasoning
                },
                project_context=project_context,
                ontology_context=ontology_context
            )
            
            comparison_status = comparison.get("status", "UNKNOWN")
            print(f"   🔗 Global Entity Identifier 비교: {comparison_status}")
            
            if comparison_status == "MATCH":
                target_col = comparison["target_column"]
                entity_identification = {
                    "status": "CONFIRMED",
                    "column_name": target_col,
                    "is_time_series": is_time_series,
                    "reasoning": f"Matched with global master identifier '{master_name}'",
                    "mapped_to_master": master_name,
                    "row_represents": entity_result.row_represents
                }
            
            elif comparison_status == "INDIRECT_LINK":
                via_col = comparison["target_column"]
                via_table = comparison.get("via_table", "unknown")
                
                entity_identification = {
                    "status": "INDIRECT_LINK",
                    "column_name": via_col,
                    "is_time_series": is_time_series,
                    "reasoning": comparison.get("message"),
                    "mapped_to_master": master_name,
                    "via_table": via_table,
                    "link_type": "indirect",
                    "row_represents": entity_result.row_represents
                }
                print(f"   ✅ [INDIRECT_LINK] Auto-confirmed indirect link!")
            
            elif comparison_status == "FK_LINK":
                fk_col = comparison["target_column"]
                via_table = comparison.get("via_table", "unknown")
                via_column = comparison.get("via_column", fk_col)
                fk_path = comparison.get("fk_path", [])
                fk_confidence = comparison.get("confidence", 0.7)
                
                entity_identification = {
                    "status": "FK_LINK",
                    "column_name": fk_col,
                    "is_time_series": is_time_series,
                    "reasoning": comparison.get("message"),
                    "mapped_to_master": master_name,
                    "via_table": via_table,
                    "via_column": via_column,
                    "fk_path": fk_path,
                    "link_type": "fk",
                    "confidence": fk_confidence,
                    "row_represents": entity_result.row_represents
                }
                
                print(f"   ✅ [FK_LINK] Auto-confirmed FK relationship!")
                print(f"      - FK Path: {' → '.join(fk_path)}")
                
                # FK 관계를 온톨로지에 저장
                if ontology_context is not None:
                    current_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
                    new_relationship = {
                        "source_table": current_table,
                        "target_table": via_table,
                        "source_column": fk_col,
                        "target_column": via_column,
                        "relation_type": comparison.get("relation_type", "N:1"),
                        "confidence": fk_confidence,
                        "llm_inferred": True,
                        "description": f"FK inferred: {current_table}.{fk_col} → {via_table}.{via_column}"
                    }
                    
                    if "relationships" not in ontology_context:
                        ontology_context["relationships"] = []
                    
                    # 중복 체크
                    existing_keys = {
                        (r.get("source_table"), r.get("target_table"), 
                         r.get("source_column"), r.get("target_column"))
                        for r in ontology_context.get("relationships", [])
                    }
                    new_key = (current_table, via_table, fk_col, via_column)
                    
                    if new_key not in existing_keys:
                        ontology_context["relationships"].append(new_relationship)
                        print(f"      - FK relationship saved to ontology")
            
            elif comparison_status not in ["MATCH", "INDIRECT_LINK", "FK_LINK"]:
                # Identifier 충돌 - Human Review 필요
                msg = comparison.get("message", "Entity identifier mismatch occurred")
                
                natural_question = generate_natural_human_question(
                    file_path=file_path,
                    context={
                        "master_identifier": master_name,
                        "candidates": identifier_column,
                        "reasoning": msg,
                        "columns": metadata.get("columns", [])
                    },
                    issue_type="entity_conflict",
                    conversation_history=conversation_history
                )
                
                return {
                    "needs_human_review": True,
                    "review_type": "entity",
                    "human_question": natural_question,
                    "conversation_history": conversation_history,
                    "retry_count": retry_count + 1,
                    "logs": [f"⚠️ [Analyzer] Global Entity identifier mismatch ({comparison_status})."]
                }
        
        # Entity 정보를 project_context에 저장 (다른 테이블에서 참조 가능)
        if "known_entities" not in project_context:
            project_context["known_entities"] = {}
        
        for lc in entity_result.linkable_columns:
            project_context["known_entities"][lc.column_name] = {
                "entity": lc.represents_entity,
                "entity_kr": lc.represents_entity_kr,
                "relation_type": lc.relation_type.value if hasattr(lc.relation_type, 'value') else str(lc.relation_type),
                "source_table": ctx.table_name
            }

    # --- Update Global Context ---
    if entity_identification and not project_context.get("master_entity_identifier"):
        project_context["master_entity_identifier"] = entity_identification["column_name"]
        project_context["known_aliases"].append(entity_identification["column_name"])
        print(f"👑 [Project Context] New Master Entity Identifier set: '{entity_identification['column_name']}'")
        
        # entity_identification와 동기화 (backward compatibility)
        if not entity_identification:
            entity_identification = {
                "status": entity_result.status,
                "column_name": entity_result.entity_identifier,
                "is_time_series": (file_type == "signal"),
                "confidence": entity_result.confidence,
                "reasoning": entity_result.reasoning,
                "mapped_to_master": project_context.get("master_entity_identifier"),
                # Entity understanding 추가 정보
                "row_represents": entity_result.row_represents
            }
            
            if entity_result.id_value is not None:
                entity_identification["id_value"] = entity_result.id_value
                entity_identification["caseid_value"] = entity_result.id_value
        
        print(f"   📊 [Entity] 분석 완료: {entity_result.row_represents_kr} (identifier: {entity_result.entity_identifier})")
        if entity_result.hierarchy_explanation:
            print(f"   📊 [Entity] 계층: {entity_result.hierarchy_explanation}")
        
        # Human review가 필요한 경우 (Signal 파일에서 ID 확인 등)
        if entity_result.needs_human_confirmation:
            question = generate_natural_human_question(
                file_path=file_path,
                context={
                    "reasoning": entity_result.reasoning,
                    "candidates": entity_result.entity_identifier,
                    "columns": metadata.get("columns", []),
                    "message": f"LLM confidence: {entity_result.confidence:.0%}"
                },
                issue_type="entity_uncertain",
                conversation_history=conversation_history
            )
            
            return {
                "needs_human_review": True,
                "review_type": "entity",
                "human_question": question,
                "conversation_history": conversation_history,
                "retry_count": retry_count + 1,
                "entity_understanding": entity_understanding,
                "project_context": project_context,
                "logs": [f"⚠️ [Analyzer] Entity uncertain ({entity_result.confidence:.0%}). Human review required."]
            }
    
    else:
        # entity_understanding이 이미 있음 (사용자 피드백으로 설정됨)
        print(f"   ✅ [Entity] 사용자 피드백에서 Entity 정보 로드됨")
        print(f"      - row_represents: {entity_understanding.get('row_represents_kr', entity_understanding.get('row_represents'))}")
        print(f"      - entity_identifier: {entity_understanding.get('entity_identifier')}")
        
        # project_context에 entity 정보 추가 (다른 테이블에서 참조 가능)
        if "known_entities" not in project_context:
            project_context["known_entities"] = {}
        
        for lc in entity_understanding.get("linkable_columns", []):
            col_name = lc.get("column_name")
            if col_name:
                project_context["known_entities"][col_name] = {
                    "entity": lc.get("represents_entity"),
                    "entity_kr": lc.get("represents_entity_kr"),
                    "relation_type": lc.get("relation_type", "reference"),
                    "source_table": ctx.table_name
                }

    # --- LLM 컬럼 분석 (human_feedback 활용) ---
    # NOTE: human_feedback, dataset_id는 이미 위에서 가져옴
    if human_feedback:
        print(f"   📝 [User Feedback] Passing to LLM: '{human_feedback[:50]}...'")
    
    # --- Detailed schema analysis (with user_feedback + ontology definitions) ---
    schema_analysis = analyze_columns_with_llm(
        columns=metadata.get("columns", []),
        sample_data=metadata.get("column_details", []),  # 리스트 기본값 (TabularProcessor 호환)
        entity_context=entity_identification,
        user_feedback=human_feedback,
        ontology_context=ontology_context  # NEW: 온톨로지 정의 전달 (메타데이터에서 추출한 용어)
    )
    
    # --- [NEW] Build analysis_context for traceability ---
    enrichments = []
    
    # Convert Pydantic models to dicts for easier manipulation
    schema_analysis_dicts = []
    for schema_item in schema_analysis:
        # Handle both Pydantic models and dicts
        if hasattr(schema_item, 'model_dump'):
            item_dict = schema_item.model_dump()
        elif hasattr(schema_item, 'dict'):
            item_dict = schema_item.dict()
        elif isinstance(schema_item, dict):
            item_dict = schema_item
        else:
            item_dict = dict(schema_item)
        schema_analysis_dicts.append(item_dict)
    
    for schema_item in schema_analysis_dicts:
        col_name = schema_item.get("original_name")
        if col_name:
            # analysis_context 생성: 분석 근거 (user_feedback 포함)
            # NOTE: user_feedback 원본은 별도 저장하지 않음 (중복 방지)
            context_parts = []
            if human_feedback:
                context_parts.append(f"user_feedback: '{human_feedback}'")
            if schema_item.get("full_name"):
                context_parts.append(f"full_name: '{schema_item.get('full_name')}'")
            if schema_item.get("semantic_type"):
                context_parts.append(f"semantic_type: '{schema_item.get('semantic_type')}'")
            
            analysis_context = "; ".join(context_parts) if context_parts else None
            
            # PostgreSQL에 analysis_context만 저장 (user_feedback 중복 제거)
            schema_item["analysis_context"] = analysis_context
            
            # enriched_definition: LLM이 분석한 풍부한 설명
            enriched_def = schema_item.get("description_kr") or schema_item.get("description", "")
            
            # Neo4j enrichment 준비
            enrichments.append({
                "name": col_name,
                "enriched_definition": enriched_def,
                "analysis_context": analysis_context
            })
    
    # Replace schema_analysis with dict version for downstream use
    schema_analysis = schema_analysis_dicts
    
    if human_feedback:
        print(f"   ✅ [User Feedback] Applied to LLM analysis & stored in analysis_context")
    
    # 배치로 Neo4j Concept 업데이트
    if enrichments:
        from src.utils.ontology_manager import get_ontology_manager
        ontology_mgr = get_ontology_manager()
        ontology_mgr.enrich_concepts_batch(enrichments, dataset_id=dataset_id)

    # --- Intra-table Hierarchy Analysis ---
    table_name = ctx.table_name
    
    print(f"\n🔗 [Hierarchy] Analyzing intra-table hierarchy for {table_name}...")
    hierarchy_info = analyze_intra_table_hierarchy(
        columns=metadata.get("columns", []),
        sample_data=metadata.get("column_details", {}),
        table_name=table_name,
        user_feedback=human_feedback  # NEW: 사용자 피드백 전달
    )
    
    # hierarchy가 발견되면 저장
    intra_table_hierarchy = None
    if hierarchy_info:
        intra_table_hierarchy = hierarchy_info
        
        # 1. PostgreSQL column_metadata에 parent_column/cardinality 추가
        # (schema_analysis의 child_column에 정보 추가)
        child_col = hierarchy_info.get("child_column")
        parent_col = hierarchy_info.get("parent_column")
        cardinality = hierarchy_info.get("cardinality", "N:1")
        
        for schema_item in schema_analysis:
            if schema_item.get("original_name") == child_col:
                schema_item["parent_column"] = parent_col
                schema_item["cardinality"] = cardinality
                schema_item["hierarchy_type"] = hierarchy_info.get("hierarchy_type", "unknown")
                print(f"   ✅ [PostgreSQL] {child_col} metadata updated with parent_column={parent_col}")
                break
        
        # 2. Neo4j에 CHILD_OF 관계 저장 (ontology_context에 추가)
        if ontology_context:
            if "column_hierarchy" not in ontology_context:
                ontology_context["column_hierarchy"] = []
            
            new_hierarchy = {
                "table_name": table_name,
                "child_column": child_col,
                "parent_column": parent_col,
                "cardinality": cardinality,
                "hierarchy_type": hierarchy_info.get("hierarchy_type", "unknown"),
                "reasoning": hierarchy_info.get("reasoning", ""),
                "dataset_id": state.get("current_dataset_id", "unknown")
            }
            
            # 중복 체크
            existing_keys = {
                (h.get("table_name"), h.get("child_column"), h.get("parent_column"))
                for h in ontology_context.get("column_hierarchy", [])
            }
            new_key = (table_name, child_col, parent_col)
            
            if new_key not in existing_keys:
                ontology_context["column_hierarchy"].append(new_hierarchy)
                print(f"   ✅ [Neo4j] CHILD_OF relationship added: {child_col} → {parent_col}")

    print(f"\n✅ [ANALYZER NODE] Complete")
    print(f"   - Entity Identifier: {entity_identification.get('column_name', 'N/A') if entity_identification else 'N/A'}")
    print(f"   - Identification Status: {entity_identification.get('status', 'N/A') if entity_identification else 'N/A'}")
    if entity_identification and entity_identification.get('status') == 'FK_LINK':
        print(f"   - FK Path: {entity_identification.get('fk_path', [])}")
    print(f"   - Schema Columns: {len(schema_analysis)}")
    # Entity Understanding 출력 (NEW)
    if entity_understanding:
        print(f"   - Entity: {entity_understanding.get('row_represents_kr', 'N/A')} ({entity_understanding.get('entity_identifier', 'N/A')})")
        linkable = [lc.get('column_name') for lc in entity_understanding.get('linkable_columns', [])]
        print(f"   - Linkable Columns: {linkable}")
    if intra_table_hierarchy:
        print(f"   - Hierarchy: {intra_table_hierarchy['child_column']} → {intra_table_hierarchy['parent_column']} ({intra_table_hierarchy['cardinality']})")
    print("="*80)

    # ontology_context가 수정되었을 수 있으므로 함께 반환
    result = {
        "entity_identification": entity_identification,
        "finalized_schema": schema_analysis,
        "project_context": project_context,
        "raw_metadata": metadata,
        "needs_human_review": False,
        "human_feedback": None, 
        "logs": ["🧠 [Analyzer] Complete schema and ontology analysis."],
        # Entity Understanding (NEW)
        "entity_understanding": entity_understanding
    }
    
    # ontology_context가 수정되었으면 함께 반환
    if ontology_context:
        result["ontology_context"] = ontology_context
    
    return result


# =============================================================================
# 헬퍼 함수들
# =============================================================================

def _handle_skip(state: AgentState) -> Dict[str, Any]:
    """스킵 처리"""
    skip_reason = state.get("skip_reason", "unknown")
    file_path = state.get("file_path", "unknown")
    filename = os.path.basename(file_path) if file_path else "unknown"
    
    print("\n" + "="*80)
    print(f"⏭️ [ANALYZER NODE] Skipping - {filename}")
    print(f"   Reason: {skip_reason}")
    print("="*80)
    
    return {
        "skip_indexing": True,
        "skip_reason": skip_reason,
        "needs_human_review": False,
        "logs": [f"⏭️ [Analyzer] Skipped: {filename} ({skip_reason})"]
    }


def _handle_retry_exceeded(ctx: AnalysisContext) -> Dict[str, Any]:
    """Retry 초과 시 강제 확정"""
    log_msg = f"⚠️ [Analyzer] Retry count exceeded ({ctx.retry_count}). Forcing first column as Entity Identifier."
    
    first_column = ctx.columns[0] if ctx.columns else "unknown"
    
    entity_identification = {
        "status": "CONFIRMED",
        "column_name": first_column,
        "is_time_series": False,
        "reasoning": f"Forced confirmation after {ctx.retry_count} retries",
        "mapped_to_master": ctx.master_anchor
    }
    
    return {
        "entity_identification": entity_identification,
        "finalized_schema": [],
        "project_context": ctx.project_context,
        "needs_human_review": False,
        "human_feedback": None,
        "retry_count": ctx.retry_count,
        "logs": [log_msg, "⚠️ [Analyzer] Schema analysis skipped (retry exceeded)"]
    }
